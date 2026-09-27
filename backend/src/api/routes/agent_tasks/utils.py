"""Shared helpers for agent task routes."""

import ast
import json
from typing import Any, Dict, List, Optional

from .projections.artifact_presentation import normalize_file_entry
from .projections.finalizer_result import get_finalizer_envelope


def clean_agent_output(raw_output: str) -> str:
    """Clean up raw agent output that may contain stringified Python structures."""
    if not raw_output or not isinstance(raw_output, str):
        return raw_output or ""

    # Check if it looks like a stringified Python list: [{'text': "...
    if raw_output.strip().startswith("[{'text':") or raw_output.strip().startswith('[{"text":'):
        try:
            parsed = ast.literal_eval(raw_output)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                # Extract just the text content
                text_parts = [item.get('text', '') for item in parsed if isinstance(item, dict)]
                return '\n'.join(text_parts)
        except Exception:
            pass  # If parsing fails, continue with string cleanup

    # Replace literal \n with actual newlines
    if '\\n' in raw_output:
        raw_output = raw_output.replace('\\n', '\n')

    return raw_output


def _get_finalizer_payload_files(result_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return finalizer result_payload.files across historical and current storage shapes."""
    candidate_envelopes: List[Dict[str, Any]] = []
    for key in ("finalizer_result", "final_envelope"):
        candidate = result_data.get(key)
        if isinstance(candidate, dict):
            candidate_envelopes.append(candidate)

    nested_data = result_data.get("data")
    if isinstance(nested_data, dict):
        for key in ("finalizer_result", "final_envelope"):
            candidate = nested_data.get(key)
            if isinstance(candidate, dict):
                candidate_envelopes.append(candidate)

    for finalizer in candidate_envelopes:
        payload = finalizer.get("result_payload")
        if not isinstance(payload, dict):
            continue

        files = payload.get("files")
        if isinstance(files, list):
            return [file for file in files if isinstance(file, dict)]

    return []


def _get_finalizer_payload_file_count(result_data: Dict[str, Any]) -> int:
    return len(_get_finalizer_payload_files(result_data))


def _extract_finalizer_message(result_data: Dict[str, Any]) -> Optional[str]:
    """Extract the user-visible final answer before generic workflow status text."""
    finalizer = get_finalizer_envelope(result_data)
    if not finalizer:
        return None

    payload = finalizer.get("result_payload")
    if isinstance(payload, dict):
        for key in ("message", "result", "output_text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

    summary = finalizer.get("summary_text")
    if isinstance(summary, str) and summary.strip():
        return summary

    return None


def _extract_failure_message(result_data: Dict[str, Any]) -> Optional[str]:
    """Return durable failure or partial text that should survive rehydration."""
    failure_info = result_data.get("failure_info")
    if isinstance(failure_info, dict):
        error = failure_info.get("error")
        if isinstance(error, str) and error.strip():
            return error

    for key in ("workflow_result", "message", "error"):
        value = result_data.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return None


def extract_result_outcome(result_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract the structured finalizer outcome used for UI severity."""
    if not isinstance(result_data, dict):
        return None

    finalizer = get_finalizer_envelope(result_data)
    if isinstance(finalizer, dict):
        payload = finalizer.get("result_payload")
        if isinstance(payload, dict):
            outcome = payload.get("outcome")
            if isinstance(outcome, str) and outcome.strip():
                return outcome.strip()

    payload = result_data.get("result_payload")
    if isinstance(payload, dict):
        outcome = payload.get("outcome")
        if isinstance(outcome, str) and outcome.strip():
            return outcome.strip()

    return None


def derive_result_severity(status: Optional[str], result_data: Optional[Dict[str, Any]]) -> str:
    """Map lifecycle status plus finalizer outcome to visual severity."""
    outcome = (extract_result_outcome(result_data) or "").strip().lower()
    if outcome == "partial":
        return "warning"
    if outcome == "completed_with_warnings":
        return "success"
    if outcome == "failure":
        return "error"
    if outcome == "success":
        return "success"

    normalized_status = (status or "").strip().lower()
    if normalized_status == "failed":
        return "error"
    if normalized_status == "completed":
        return "success"
    return "neutral"


def extract_list_preview(agent_task) -> tuple:
    """Extract preview text and file count from an agent task for list display."""
    result_preview = None
    file_count = 0
    if agent_task.result_data:
        result_preview = _extract_finalizer_message(agent_task.result_data) or (
            agent_task.result_data.get("message") or
            agent_task.result_data.get("result") or
            agent_task.result_data.get("enhanced_output") or
            agent_task.result_data.get("agent_output") or
            agent_task.result_data.get("full_content")
        ) or _extract_failure_message(agent_task.result_data)
        if result_preview:
            result_preview = clean_agent_output(result_preview)
            if len(result_preview) > 100:
                result_preview = result_preview[:100] + "..."

        file_count = _get_finalizer_payload_file_count(agent_task.result_data)
        if file_count == 0:
            files = agent_task.result_data.get("files", [])
            file_count = len(files) if isinstance(files, list) else 0
    return result_preview, file_count


def extract_result_data(cmd):
    result_msg = None
    cmd_files = []
    ref_paths = []
    err_msg = None
    if cmd.result_data:
        result_msg = _extract_finalizer_message(cmd.result_data) or (
            cmd.result_data.get("message") or
            cmd.result_data.get("result") or
            cmd.result_data.get("enhanced_output") or
            cmd.result_data.get("agent_output") or
            cmd.result_data.get("full_content")
        )

        if result_msg:
            result_msg = clean_agent_output(result_msg)

        if not result_msg and cmd.status == "awaiting_user_input":
            checkpoint_data = cmd.result_data.get("checkpoint_data", {})
            if checkpoint_data:
                result_msg = checkpoint_data.get("prompt")

        if not result_msg and cmd.status == "failed":
            result_msg = _extract_failure_message(cmd.result_data)
            if result_msg:
                result_msg = clean_agent_output(result_msg)

        # 1) The finalizer envelope is the canonical artifact contract.
        for f in _get_finalizer_payload_files(cmd.result_data):
            cmd_files.append(normalize_file_entry(f))

        # 2) Fall back to historical top-level files when no finalizer files exist.
        if not cmd_files:
            raw_files = cmd.result_data.get("files", [])
            if isinstance(raw_files, list):
                for f in raw_files:
                    if isinstance(f, dict):
                        cmd_files.append(normalize_file_entry(f))

        # Filter out entries with empty name and path
        cmd_files = [f for f in cmd_files if f["name"] or f["path"]]

        failure_info = cmd.result_data.get("failure_info")
        if isinstance(failure_info, dict):
            err_msg = failure_info.get("error")

    # Extract reference_paths from accumulated_artifacts
    if cmd.accumulated_artifacts and isinstance(cmd.accumulated_artifacts, dict):
        paths = cmd.accumulated_artifacts.get("reference_paths", [])
        if isinstance(paths, list):
            ref_paths = [p for p in paths if isinstance(p, str) and p]

    # Read execution_timeline from dedicated column
    timeline = cmd.execution_timeline

    return result_msg, cmd_files, ref_paths, err_msg, timeline


def extract_checkpoint_data(cmd) -> Optional[Dict[str, Any]]:
    """Return the durable input request for a non-terminal task."""
    status = getattr(cmd, "status", None)
    if status == "awaiting_user_input":
        result_data = getattr(cmd, "result_data", None)
        if not isinstance(result_data, dict):
            return None
        checkpoint_data = result_data.get("checkpoint_data")
        return checkpoint_data if isinstance(checkpoint_data, dict) else None
    if status != "needs_clarification":
        return None
    task_id = getattr(cmd, "id", None)
    operation_parameters = getattr(cmd, "operation_parameters", None)
    if not isinstance(task_id, str) or not task_id:
        return None
    if not isinstance(operation_parameters, dict):
        return None
    prompt = operation_parameters.get("clarification_message")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    return {
        "checkpoint_id": f"clarification-{task_id}",
        "prompt": prompt.strip(),
        "input_type": "data",
        "metadata": {"source": "clarification"},
    }


def extract_original_model_id(agent_task_record) -> Optional[str]:
    """Return the model_id captured in accumulated_artifacts at submission
    time, if any. This is the same field agent_task_routing_service.py's
    build_routing_request reads to decide which model a retry re-routes to,
    so it is the authoritative "model originally used" for a given attempt."""
    artifacts = getattr(agent_task_record, "accumulated_artifacts", None)
    if isinstance(artifacts, dict):
        model_id = artifacts.get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            return model_id
    return None


def build_retry_context(agent_task_record) -> Dict[str, Any]:
    """Build compact, durable context for the next retry attempt."""
    result_data = agent_task_record.result_data or {}
    execution_timeline = agent_task_record.execution_timeline or []
    finalizer_result = result_data.get("finalizer_result") if isinstance(result_data, dict) else None
    failure_info = result_data.get("failure_info") if isinstance(result_data, dict) else None

    return {
        "agent_task_id": agent_task_record.id,
        "original_prompt": agent_task_record.original_prompt,
        "transcribed_prompt": agent_task_record.transcribed_prompt,
        "previous_status": agent_task_record.status,
        "failure_summary": extract_failure_summary(result_data, finalizer_result, failure_info),
        "partial_result": extract_partial_result(result_data, finalizer_result),
        "self_assessment": finalizer_result.get("self_assessment") if isinstance(finalizer_result, dict) else None,
        "tool_attempts": extract_tool_attempts(execution_timeline),
        "blockers": extract_retry_blockers(result_data, execution_timeline),
        "files": extract_retry_files(result_data, finalizer_result),
        "timeline_entry_count": len(execution_timeline),
    }


def extract_failure_summary(result_data: Dict[str, Any], finalizer_result: Any, failure_info: Any) -> Optional[str]:
    if isinstance(failure_info, dict) and failure_info.get("error"):
        return str(failure_info["error"])
    if isinstance(result_data, dict):
        for key in ("message", "error", "workflow_result"):
            if result_data.get(key):
                return str(result_data[key])
    if isinstance(finalizer_result, dict):
        return finalizer_result.get("summary_text")
    return None


def extract_partial_result(result_data: Dict[str, Any], finalizer_result: Any) -> Optional[str]:
    if isinstance(finalizer_result, dict) and finalizer_result.get("summary_text"):
        return str(finalizer_result["summary_text"])
    if isinstance(result_data, dict):
        failure_info = result_data.get("failure_info")
        if isinstance(failure_info, dict) and failure_info.get("error"):
            return str(failure_info["error"])[:4000]
        for key in ("workflow_result", "enhanced_output", "agent_output", "full_content"):
            if result_data.get(key):
                return str(result_data[key])[:4000]
    return None


def extract_tool_attempts(execution_timeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    for entry in execution_timeline:
        if entry.get("type") not in {"tool_start", "tool_complete"}:
            continue
        metadata = entry.get("metadata") or {}
        attempts.append({
            "type": entry.get("type"),
            "tool_name": metadata.get("tool_name"),
            "status": metadata.get("status"),
            "summary": entry.get("summary") or entry.get("content"),
            "body": (entry.get("body") or "")[:2000],
        })
    return attempts[-12:]


def extract_retry_blockers(result_data: Any, execution_timeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    for value in walk_nested_values(result_data):
        if isinstance(value, dict):
            if value.get("approval_timed_out") or value.get("user_action_required"):
                blockers.append(value)
            error = value.get("error")
            if isinstance(error, dict):
                kind = str(error.get("kind") or "")
                if kind.startswith("auth") or kind in {"permission_denied", "blocked", "timeout"}:
                    blockers.append(error)

    for entry in execution_timeline:
        body = entry.get("body")
        if not isinstance(body, str) or not body.strip().startswith("{"):
            continue
        try:
            parsed = json.loads(body)
        except Exception:
            continue
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                blockers.append(error)

    return blockers[-8:]


def extract_retry_files(result_data: Dict[str, Any], finalizer_result: Any) -> List[Any]:
    files: List[Any] = []
    if isinstance(result_data, dict):
        for key in ("files", "reference_paths"):
            value = result_data.get(key)
            if isinstance(value, list):
                files.extend(value)
        files.extend(_get_finalizer_payload_files(result_data))
    elif isinstance(finalizer_result, dict):
        payload = finalizer_result.get("result_payload")
        if isinstance(payload, dict) and isinstance(payload.get("files"), list):
            files.extend(payload["files"])
    return files[:20]


def walk_nested_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_nested_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_nested_values(child)
