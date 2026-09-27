from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution_graph.agent_progress_system import PlanningState

logger = logging.getLogger(__name__)


def _format_exception_with_causes(error: Exception) -> str:
    """Return an error message that keeps useful wrapped exception details."""
    messages: List[str] = []
    seen_ids = set()
    current: Optional[BaseException] = error

    while current is not None and id(current) not in seen_ids:
        seen_ids.add(id(current))
        detail = str(current).strip()
        if detail:
            message = f"{type(current).__name__}: {detail}"
            if message not in messages:
                messages.append(message)

        current = current.__cause__ or current.__context__

    if not messages:
        return type(error).__name__

    return " | Caused by: ".join(messages)


def capture_finalizer_result(intermediate_steps: List[Any]) -> Tuple[Optional[Dict], int]:
    """Capture the finalizer tool output from intermediate steps. Prefers the LAST successful finalizer."""
    final_envelope = None
    finalize_attempts = 0
    last_success_index = -1
    
    try:
        for step in intermediate_steps:
            if isinstance(step, tuple) and len(step) >= 2:
                action, observation = step[0], step[1]
                tool_name = getattr(action, 'tool', None)
                if tool_name == 'finalize_agent_task_result' and observation is not None:
                    finalize_attempts += 1
                    parsed = None
                    try:
                        parsed = _json.loads(observation if isinstance(observation, str) else str(observation))
                    except Exception:
                        if isinstance(observation, dict):
                            parsed = observation
                    if isinstance(parsed, dict):
                        current_index = intermediate_steps.index(step)
                        if parsed.get('success') is True:
                            final_envelope = parsed
                            last_success_index = current_index
                        else:
                            if final_envelope is None and last_success_index < 0:
                                final_envelope = parsed
    except Exception:
        final_envelope = None
    
    return final_envelope, finalize_attempts


async def attempt_finalization_recovery(
    state: "PlanningState",
    agent_executor: Any,
    intermediate_steps: List[Any],
    agent_output: str,
    callbacks: List[Any]
) -> Tuple[Optional[Dict], List[Any]]:
    """Attempt recovery when agent didn't call finalizer but produced output.

    Instead of brittle heuristics to decide whether recovery is warranted,
    we gather all available context and let the model itself evaluate whether
    it succeeded and package its work via the finalizer tool.  The only
    hard gate is checkpoint flow-control (the agent is waiting for user
    input, not failing to finalize).
    """
    logger.info("🔍 RECOVERY CHECK: No finalization detected, checking if recovery needed...")

    # Gather ALL available context: agent text output + every tool observation
    accumulated_parts: List[str] = []
    if agent_output:
        accumulated_parts.append(str(agent_output))

    for step in intermediate_steps:
        if isinstance(step, tuple) and len(step) >= 2:
            action, observation = step[0], step[1]
            if hasattr(action, 'log') and action.log:
                accumulated_parts.append(str(action.log))
            if observation:
                accumulated_parts.append(str(observation))

    full_output = "\n\n".join(accumulated_parts)
    logger.info(f"🔍 RECOVERY CHECK: Accumulated output length: {len(full_output)} chars")

    # Only hard gate: checkpoint flow — agent is waiting for user input, not failing
    is_checkpoint = any(
        keyword in full_output.lower()
        for keyword in ['awaiting', 'need your input', 'please confirm', 'which option']
    )
    if is_checkpoint:
        logger.info("🔍 RECOVERY CHECK: Detected checkpoint pattern, skipping recovery")
        return None, intermediate_steps

    # If the agent did zero work (no text, no tool calls), nothing to recover
    has_any_work = bool(accumulated_parts)
    if not has_any_work:
        logger.info("🔍 RECOVERY CHECK: No agent output or tool work to recover from")
        return None, intermediate_steps

    logger.info("🚨 RECOVERY TRIGGERED: Agent produced output but didn't finalize. Attempting recovery...")

    agent_task_id = state.context.get("agent_task_id", "unknown")
    active_app = state.context.get("active_app", "Unknown")
    original_prompt = state.user_agent_task
    output_preview = full_output[:2000] + ("..." if len(full_output) > 2000 else "")

    recovery_prompt = f"""You completed work on the following request but did not call finalize_agent_task_result as your final step.

Original request: "{original_prompt}"

Your work so far (text output and tool results):
{output_preview}

Review your work above and then call finalize_agent_task_result with:
- original_prompt: "{original_prompt}"
- agent_task_id: "{agent_task_id}"
- active_app: "{active_app}"
- steps: [array of your tool executions]
- raw_messages: [your full output text from above]
- self_assessment: your honest evaluation of whether the work fully addresses the request
- success: true if your work satisfactorily addresses the request, false if it does not

This is your ONLY remaining task. Call the finalizer now."""
    
    logger.info("🔧 RECOVERY: Executing recovery iteration with focused prompt")
    
    try:
        recovery_result = await agent_executor.ainvoke(
            {"input": recovery_prompt},
            config={"callbacks": callbacks} if callbacks else None,
        )
        
        recovery_steps = recovery_result.get("intermediate_steps", [])
        recovery_envelope = None
        
        for step in recovery_steps:
            if isinstance(step, tuple) and len(step) >= 2:
                action, observation = step[0], step[1]
                tool_name = getattr(action, 'tool', None)
                if tool_name == 'finalize_agent_task_result' and observation is not None:
                    try:
                        recovery_envelope = _json.loads(observation if isinstance(observation, str) else str(observation))
                    except Exception:
                        if isinstance(observation, dict):
                            recovery_envelope = observation
                    if isinstance(recovery_envelope, dict):
                        logger.info("✅ RECOVERY SUCCESS: Agent finalized after recovery prompt")
                        updated_steps = list(intermediate_steps) + list(recovery_steps)
                        return recovery_envelope, updated_steps
        
        logger.warning("⚠️ RECOVERY FAILED: Agent still didn't finalize after recovery attempt")
        state.context["recovery_attempted"] = True
        state.context["accumulated_output"] = full_output
        return None, intermediate_steps
        
    except Exception as recovery_err:
        logger.error(f"❌ RECOVERY ERROR: Failed to execute recovery: {recovery_err}")
        state.context["recovery_attempted"] = True
        state.context["accumulated_output"] = full_output
        return None, intermediate_steps
