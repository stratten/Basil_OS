from __future__ import annotations

import asyncio
import json as _json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..execution_graph.agent_step_parser import parse_agent_steps_from_output
from ..execution_graph.standardized_file_operation_parser import StandardizedFileOperationParser
from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
from ...shared.serialization import convert_to_serializable_dict
from .recovery import _format_exception_with_causes
from .task_state_persistence import _store_execution_context

if TYPE_CHECKING:
    from ..execution_graph.agent_progress_system import PlanningState

logger = logging.getLogger(__name__)


def _compact_trace_text(value: Any, limit: int = 2000) -> Optional[str]:
    """Return a bounded string representation for persisted tool traces."""
    if value is None:
        return None

    if isinstance(value, str):
        text = value
    else:
        try:
            text = _json.dumps(convert_to_serializable_dict(value), ensure_ascii=False)
        except Exception:
            text = str(value)

    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " ... [truncated]"


def _summarize_intermediate_steps(intermediate_steps: List[Any]) -> List[Dict[str, Any]]:
    """Convert LangChain intermediate steps into compact JSON-safe trace records."""
    summaries: List[Dict[str, Any]] = []

    for index, step in enumerate(intermediate_steps or []):
        if isinstance(step, tuple) and len(step) >= 2:
            action, observation = step[0], step[1]
            tool_name = getattr(action, "tool", None)
            tool_input = getattr(action, "tool_input", None)
            log = getattr(action, "log", None)
        else:
            action = None
            observation = step
            tool_name = None
            tool_input = None
            log = None

        summaries.append({
            "index": index,
            "tool": tool_name,
            "tool_input": convert_to_serializable_dict(tool_input),
            "action_type": type(action).__name__ if action is not None else None,
            "log_preview": _compact_trace_text(log),
            "observation_preview": _compact_trace_text(observation),
        })

    return summaries


def _merge_step_details_into_timeline(
    execution_timeline: Optional[List[Dict]],
    dynamic_steps: List[Any],
    final_envelope: Optional[Dict],
) -> List[Dict]:
    """Merge live callback timeline with parsed step/finalizer tray details."""
    merged: List[Dict] = list(execution_timeline or [])
    seen_ids = {
        entry.get("id")
        for entry in merged
        if isinstance(entry, dict) and entry.get("id")
    }

    for step in dynamic_steps or []:
        if not isinstance(step, dict):
            continue
        for detail in step.get("details") or []:
            if not isinstance(detail, dict):
                continue
            detail_id = detail.get("id")
            if detail_id and detail_id in seen_ids:
                continue
            if detail_id:
                seen_ids.add(detail_id)
            merged.append(detail)

    if final_envelope and isinstance(final_envelope, dict):
        summary = final_envelope.get("summary_text")
        if summary:
            entry_id = "final_summary"
            if entry_id not in seen_ids:
                payload = final_envelope.get("result_payload") or {}
                merged.append({
                    "id": entry_id,
                    "type": "step",
                    "timestamp": datetime.now().isoformat(),
                    "content": "Final result summary",
                    "detail_kind": "final_summary",
                    "summary": "Final result summary",
                    "body": summary,
                    "metadata": {
                        "source": "finalizer",
                        "files": payload.get("files") if isinstance(payload, dict) else [],
                        "steps": payload.get("steps") if isinstance(payload, dict) else None,
                    },
                    "streaming": False,
                })
                seen_ids.add(entry_id)

        payload = final_envelope.get("result_payload")
        files = payload.get("files") if isinstance(payload, dict) else []
        if isinstance(files, list):
            for file_info in files:
                if not isinstance(file_info, dict):
                    continue
                path = file_info.get("full_path") or file_info.get("path") or file_info.get("name")
                if not path:
                    continue
                operation = str(file_info.get("operation") or "created").replace("_", " ").capitalize()
                source_path = file_info.get("source_path")
                display_path = f"{source_path} → {path}" if source_path else str(path)
                entry_id = f"artifact_{uuid.uuid5(uuid.NAMESPACE_URL, str(path)).hex[:10]}"
                if entry_id in seen_ids:
                    continue
                merged.append({
                    "id": entry_id,
                    "type": "tool_complete",
                    "timestamp": datetime.now().isoformat(),
                    "content": f"{operation} artifact: {file_info.get('name') or path}",
                    "detail_kind": "artifact",
                    "summary": f"{operation}: {file_info.get('name') or path}",
                    "body": display_path,
                    "metadata": {
                        "source": "finalizer",
                        "file": file_info,
                    },
                    "streaming": False,
                })
                seen_ids.add(entry_id)

    return merged


def _merge_execution_timelines(
    persisted_timeline: Optional[List[Dict]],
    final_timeline: Optional[List[Dict]],
) -> List[Dict]:
    """Merge finalization timeline entries into already-persisted live progress."""
    merged: List[Dict] = []
    indexes_by_id: Dict[str, int] = {}

    def append_or_replace(entry: Any) -> None:
        if not isinstance(entry, dict):
            return

        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            existing_index = indexes_by_id.get(entry_id)
            if existing_index is not None:
                merged[existing_index] = {**merged[existing_index], **entry}
                return
            indexes_by_id[entry_id] = len(merged)

        merged.append(entry)

    for existing in persisted_timeline or []:
        append_or_replace(existing)

    for new_entry in final_timeline or []:
        append_or_replace(new_entry)

    return merged


def synthesize_skill_from_execution_trace(
    *,
    title: str,
    original_prompt: str,
    execution_timeline: Optional[List[Dict[str, Any]]] = None,
    intermediate_step_summaries: Optional[List[Dict[str, Any]]] = None,
    final_envelope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Reject legacy template-based skill synthesis.

    This symbol remains temporarily so existing route imports keep loading
    during the rebuild. The replacement path is the model-driven SkillEvaluator,
    which creates reviewable skill candidates rather than directly returning a
    mechanical SKILL.md body.
    """
    raise RuntimeError(
        "Template-based skill synthesis is disabled; use the model-driven "
        "SkillEvaluator proposal flow instead."
    )


def maybe_run_post_task_evaluators(
    *,
    agent_task_id: Optional[str],
    original_prompt: Any,
    final_envelope: Optional[Dict[str, Any]],
    execution_timeline: Optional[List[Dict[str, Any]]],
    intermediate_step_summaries: List[Dict[str, Any]],
) -> None:
    """Schedule opt-in post-task evaluators without delaying task completion."""
    if not agent_task_id or not _is_after_task_intelligence_enabled():
        return
    if isinstance(final_envelope, dict) and final_envelope.get("success") is False:
        return
    # A reconciliation workspace freezes background skill capture so it can
    # reconcile a stable snapshot; skip scheduling while one owns the queue.
    if _is_reconciliation_active():
        logger.info(
            "Skipping post-task evaluators for %s: reconciliation workspace is open",
            agent_task_id,
        )
        return

    try:
        from api.services.memory.post_task_evaluator_orchestrator import (
            get_post_task_evaluator_orchestrator,
        )
        from api.services.skills.skill_evaluator import CompletedTask

        result_summary = None
        if isinstance(final_envelope, dict):
            result_summary = final_envelope.get("summary_text")

        task = CompletedTask(
            id=agent_task_id,
            title=None,
            original_prompt=str(original_prompt or ""),
            transcribed_prompt=None,
            result_summary=str(result_summary) if result_summary else None,
            execution_timeline=execution_timeline or [],
            intermediate_step_summaries=intermediate_step_summaries,
            completed_at=None,
        )
        asyncio.create_task(
            get_post_task_evaluator_orchestrator().run_for_completed_task(task=task),
            name=f"post-task-evaluators-{agent_task_id}",
        )
    except Exception:
        logger.exception("Failed to schedule post-task evaluators")


def _is_after_task_intelligence_enabled() -> bool:
    try:
        from api.core.preferences.preferences_io import load_preferences

        settings = getattr(load_preferences(), "memory_intelligence", None)
        return bool(
            getattr(settings, "memory_after_task_enabled", False)
            or getattr(settings, "skill_after_task_enabled", False)
        )
    except Exception:
        logger.exception("Failed to read post-task intelligence settings")
        return False


def _is_reconciliation_active() -> bool:
    try:
        from api.services.skills.reconciliation import reconciliation_gate

        return reconciliation_gate.is_active()
    except Exception:
        logger.exception("Failed to read reconciliation gate state")
        return False


async def process_agent_result(
    result: Dict[str, Any],
    state: "PlanningState",
    coordinator: Any,
    intermediate_steps: List[Any],
    final_envelope: Optional[Dict],
    finalize_attempts: int,
    progress_steps: Optional[List[Dict]] = None,
    execution_timeline: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """Process the agent execution result into the final output structure."""
    agent_output = result.get("output", "")
    
    custom_parser = StandardizedFileOperationParser()
    custom_parser.set_intermediate_steps(intermediate_steps)
    enhanced_agent_output = custom_parser._inject_standardized_messages(agent_output)
    
    full_agent_content = []
    parser_agent_content = []
    if enhanced_agent_output:
        full_agent_content.append(str(enhanced_agent_output))
    parser_seed_is_finalizer_envelope = False
    if isinstance(agent_output, str) and agent_output.strip().startswith("{"):
        try:
            parsed_output = _json.loads(agent_output)
            parser_seed_is_finalizer_envelope = (
                isinstance(parsed_output, dict)
                and "summary_text" in parsed_output
                and "result_payload" in parsed_output
            )
        except Exception:
            parser_seed_is_finalizer_envelope = False
    if agent_output and not parser_seed_is_finalizer_envelope:
        parser_agent_content.append(str(agent_output))
    
    for step in intermediate_steps:
        if isinstance(step, tuple) and len(step) >= 2:
            action, observation = step[0], step[1]
            tool_name = getattr(action, 'tool', None)
            if hasattr(action, 'log') and action.log:
                full_agent_content.append(str(action.log))
                if tool_name != 'finalize_agent_task_result':
                    parser_agent_content.append(str(action.log))
            if observation:
                full_agent_content.append(str(observation))
                if tool_name != 'finalize_agent_task_result':
                    parser_agent_content.append(str(observation))
    
    combined_content = []
    for content in full_agent_content:
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and 'text' in item:
                    combined_content.append(item['text'])
                else:
                    combined_content.append(str(item))
        elif isinstance(content, dict) and 'text' in content:
            combined_content.append(content['text'])
        else:
            combined_content.append(str(content))
    
    agent_output = "\n".join(combined_content)

    parser_combined_content = []
    for content in parser_agent_content:
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and 'text' in item:
                    parser_combined_content.append(item['text'])
                else:
                    parser_combined_content.append(str(item))
        elif isinstance(content, dict) and 'text' in content:
            parser_combined_content.append(content['text'])
        else:
            parser_combined_content.append(str(content))
    parser_agent_output = "\n".join(parser_combined_content)
    
    logger.info(f"🔍 AGENT CONTENT FOR STEP PARSING:\n{parser_agent_output}")
    logger.info(f"🔍 STEP MARKERS FOUND: {parser_agent_output.count('STEP_START')}, {parser_agent_output.count('STEP_COMPLETE')}")
    
    agent_task_id = state.context.get("agent_task_id") if state.context else None
    root_task_id = state.context.get("root_task_id") if state.context else None
    previous_task_id = state.context.get("previous_task_id") if state.context else None
    todo_id = agent_task_id
    
    ws_manager = coordinator._websocket_manager or state.context.get("websocket_manager")
    notifier = WorkflowStatusNotifier(
        websocket_manager=ws_manager,
        agent_task_id=agent_task_id,
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
    )
    logger.info(f"🔧 DEBUG: notifier created with websocket_manager={ws_manager is not None}, agent_task_id={agent_task_id}")
    
    try:
        await notifier.send_agent_progress_update(message="Starting execution…", details=None)
    except Exception:
        pass
    
    dynamic_steps = await parse_agent_steps_from_output(
        agent_output=parser_agent_output,
        todo_id=todo_id,
        notifier=notifier
    )
    
    logger.info("✅ DYNAMIC AGENT EXECUTION COMPLETED")
    logger.info(f"📤 Agent executed {len(intermediate_steps)} tool calls")
    logger.info(f"📋 Reported {len(dynamic_steps)} progress steps")
    
    thinking_history = state.context.get("thinking_history") if state.context else None
    enriched_timeline = _merge_step_details_into_timeline(
        execution_timeline=execution_timeline,
        dynamic_steps=dynamic_steps,
        final_envelope=final_envelope,
    )

    await _store_execution_context(
        agent_task_id=agent_task_id,
        agent_output=agent_output,
        enhanced_output=enhanced_agent_output,
        full_content="\n\n".join(full_agent_content) if full_agent_content else agent_output,
        intermediate_steps=intermediate_steps,
        dynamic_steps=dynamic_steps,
        final_envelope=final_envelope,
        thinking_history=thinking_history,
        progress_steps=progress_steps,
        execution_timeline=enriched_timeline
    )
    
    _log_finalizer_debug(final_envelope, finalize_attempts)
    intermediate_step_summaries = _summarize_intermediate_steps(intermediate_steps)
    maybe_run_post_task_evaluators(
        agent_task_id=agent_task_id,
        original_prompt=state.user_agent_task,
        final_envelope=final_envelope,
        execution_timeline=enriched_timeline,
        intermediate_step_summaries=intermediate_step_summaries,
    )
    
    base_result = {
        "execution_method": "dynamic_langchain_agent",
        "user_agent_task": state.user_agent_task,
        "agent_output": agent_output,
        "tools_used": [tool.name for tool in state.available_tools.tools],
        "intermediate_steps": intermediate_step_summaries,
        "intermediate_step_summaries": intermediate_step_summaries,
        "intermediate_steps_count": len(intermediate_steps),
        "dynamic_steps": dynamic_steps,
        "total_tool_calls": len(intermediate_steps),
        "status": "completed",
        "result": agent_output
    }
    
    if state.context.get("recovery_attempted"):
        base_result["recovery_attempted"] = True
        base_result["accumulated_output"] = state.context.get("accumulated_output", "")

    if final_envelope and isinstance(final_envelope, dict):
        logger.info("🧪 FINALIZER DEBUG: returning final_envelope to caller")
        return {
            "final_envelope": final_envelope,
            "workflow_result": final_envelope.get("summary_text", ""),
            "tool_execution_results": [base_result],
        }

    full_content = "\n\n".join(full_agent_content) if full_agent_content else agent_output
    has_useful_content = bool(full_content and full_content.strip() and len(full_content.strip()) > 50)

    if has_useful_content:
        logger.info(f"🔧 FINALIZER FALLBACK: No envelope but agent produced {len(full_content)} chars of content — constructing synthetic envelope")
        synthetic_envelope = {
            "success": True,
            "auto_recovered": True,
            "summary_text": full_content,
            "result_payload": {
                "files": [],
                "result_type": "auto_recovered",
            },
        }
        base_result["status"] = "completed_auto_recovered"
        return {
            "final_envelope": synthetic_envelope,
            "workflow_result": full_content,
            "tool_execution_results": [base_result],
        }

    logger.info("🧪 FINALIZER DEBUG: returning base_result without final_envelope (no recoverable content)")
    return {"tool_execution_results": [base_result]}


def _log_finalizer_debug(final_envelope: Optional[Dict], finalize_attempts: int) -> None:
    """Log debug information about finalizer results."""
    try:
        if final_envelope and isinstance(final_envelope, dict):
            rp = final_envelope.get("result_payload") or {}
            files = rp.get("files") or []
            logger.info(f"🧪 FINALIZER DEBUG: attempts={finalize_attempts}; envelope present; files_count={len(files)}; files={[f.get('name') for f in files if isinstance(f, dict)]}")
            logger.info(f"🧪 FINALIZER DEBUG: summary_preview={final_envelope.get('summary_text','')[:200]}")
        else:
            logger.info(f"🧪 FINALIZER DEBUG: attempts={finalize_attempts}; no successful finalizer envelope found; using fallback output")
    except Exception as _dbg_err:
        logger.info(f"🧪 FINALIZER DEBUG: logging error: {_dbg_err}")


def handle_execution_error(
    error: Exception,
    state: "PlanningState",
    thinking_history: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Handle execution errors with possible recovery from captured finalizer."""
    import traceback

    detailed_error = _format_exception_with_causes(error)

    logger.error(f"❌ DYNAMIC AGENT EXECUTION FAILED: {detailed_error}")
    logger.error(f"❌ Traceback: {traceback.format_exc()}")

    captured_envelope = state.context.get("captured_finalizer_envelope") if state.context else None

    if captured_envelope and isinstance(captured_envelope, dict):
        logger.info(
            f"✅ RECOVERY: Found captured finalizer envelope (success={captured_envelope.get('success')}) — returning it"
        )
        return {
            "final_envelope": captured_envelope,
            "workflow_result": captured_envelope.get("summary_text", ""),
            "thinking_history": thinking_history or [],
            "tool_execution_results": [{
                "execution_method": "dynamic_langchain_agent",
                "user_agent_task": state.user_agent_task,
                "status": "completed_with_post_error",
                "post_error": detailed_error,
                "tools_available": [tool.name for tool in state.available_tools.tools] if state.available_tools else []
            }],
        }

    logger.warning("⚠️ RECOVERY: No captured finalizer envelope available")
    return {
        "thinking_history": thinking_history or [],
        "tool_execution_results": [{
            "execution_method": "dynamic_langchain_agent",
            "user_agent_task": state.user_agent_task,
            "status": "failed",
            "error": detailed_error,
            "tools_available": [tool.name for tool in state.available_tools.tools] if state.available_tools else []
        }]
    }
