"""
Agent Execution Core for LangGraph Agent Execution.

Handles the core execution phase: context preparation, callback setup, and agent invocation.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from ..planning.agent_context_assembler import AgentContextAssembler
from ...shared.agent_runtime_context import get_current_agent_context
from ...shared.prompt_context_trimming import (
    build_context_overflow_resume_input,
    trim_oldest_context,
)
from ...shared.workflow_budget_pause import current_pausable_deadline
from .model_error_policy import (
    CONTEXT_OVERFLOW,
    EMPTY_GENERATION,
    TRANSIENT,
    TRANSIENT_EXHAUSTED,
    classify_model_error,
    overflow_chars_to_remove,
    overflow_token_summary,
)
from .model_errors import PassBudgetExhausted
from .service_tooling.tool_call_repetition_guard import (
    RepeatedInvalidToolCallStop,
    agent_tool_action_capture_offset,
    captured_agent_actions_as_intermediate_steps,
)

if TYPE_CHECKING:
    from .agent_progress_system import PlanningState
    from .activity_progress_callback import ActivityProgressCallbackHandler

logger = logging.getLogger(__name__)


class ModelUnavailableBeforeFirstResponse(Exception):
    """Raised by execute_with_token_retry when the preferred model could not be
    reached at all (network/auth failure) and zero LLM calls succeeded for this
    task -- i.e. it is safe for the caller to substitute a local fallback model
    and restart, since no tool actions or partial output exist yet to reconcile.

    Never raised once at least one LLM call has already succeeded; in that case
    the original exception propagates unchanged and the agent stops, per the
    settled no-mid-execution-swap decision.
    """

    def __init__(self, original_error: Exception):
        super().__init__(str(original_error))
        self.original_error = original_error


def format_chain_context(state: "PlanningState") -> str:
    """Format all available agent context into the user input string."""
    assembled = AgentContextAssembler().assemble(
        current_request=state.user_agent_task,
        context=state.context or {},
    )
    if assembled.sections:
        logger.info(
            "🔗 CONTEXT FORMATTED: sections=%s omitted=%s budget_chars=%s",
            [section.name for section in assembled.sections],
            assembled.omitted_sections,
            assembled.budget_chars,
        )
    else:
        logger.info("ℹ️ No additional agent context - standalone agent task")
    return assembled.user_input


def setup_live_callbacks(
    state: "PlanningState",
    coordinator: Any
) -> List["ActivityProgressCallbackHandler"]:
    """Set up live progress callbacks for streaming step updates during execution."""
    from .activity_progress_callback import ActivityProgressCallbackHandler
    from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
    
    live_callbacks = []
    
    try:
        ws_manager = coordinator._websocket_manager or state.context.get("websocket_manager")
        todo_id = state.context.get("agent_task_id")
        notifier = WorkflowStatusNotifier(
            websocket_manager=ws_manager,
            agent_task_id=todo_id,
            root_task_id=state.context.get("root_task_id"),
            previous_task_id=state.context.get("previous_task_id"),
        )
        
        if notifier and todo_id:
            from ..runtime.turn_timing import get_or_create_turn_timing
            turn_timing = get_or_create_turn_timing(state.context)
            live_callbacks = [ActivityProgressCallbackHandler(
                notifier=notifier, 
                todo_id=todo_id, 
                available_tools=state.available_tools.tools if state.available_tools else None,
                turn_timing=turn_timing,
            )]
            logger.info(f"✅ Attaching live progress callbacks for agent task {todo_id}")
        else:
            logger.warning(f"⚠️ No activity callbacks: notifier={notifier is not None}, todo_id={todo_id}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to create live progress callbacks: {e}")
    
    if live_callbacks:
        logger.info(f"🔧 DEBUG: Live progress callbacks attached: count={len(live_callbacks)}")
    else:
        logger.info("⚠️ DEBUG: No live progress callbacks attached")
    
    return live_callbacks


_BUDGET_POLL_SECONDS = 1.0


def _supports_pause_accounting(deadline: Any) -> bool:
    return callable(getattr(deadline, "paused_seconds", None))


def _paused_seconds(deadline: Any) -> float:
    if not _supports_pause_accounting(deadline):
        return 0.0
    try:
        return float(deadline.paused_seconds())
    except Exception:
        return 0.0


def _pass_budget_message(budget_seconds: Optional[float]) -> str:
    minutes = max(1, int(round(float(budget_seconds or 0.0) / 60.0)))
    return (
        f"Basil stopped this pass after {minutes} minute(s) of active work. "
        "Time spent waiting for approvals or your input was not counted."
    )


def _relabel_execution_timeout(result: Any) -> None:
    """Rewrite LangChain's ambiguous force-stop string to a precise timeout.

    With ``max_iterations=None``, LangChain's ``return_stopped_response("force")``
    can only fire on the executor's wall-clock cap, yet it emits the generic
    ``"Agent stopped due to iteration limit or time limit."`` string. Rewrite it
    in place so the finalizer's user-facing summary names the real cause, and
    flag ``execution_timed_out`` for downstream handling. Mirrors the synthetic
    result handling for RepeatedInvalidToolCallStop above.
    """
    if not isinstance(result, dict):
        return
    from .agent_result_synthesis import normalize_agent_executor_output
    from .execution_limits import (
        LANGCHAIN_FORCE_STOP_SENTINEL,
        execution_timeout_message,
    )

    if normalize_agent_executor_output(result.get("output")).strip() == LANGCHAIN_FORCE_STOP_SENTINEL:
        logger.warning(
            "⏱️ Executor hit its wall-clock cap; relabeling LangChain force-stop "
            "message as an explicit execution timeout"
        )
        result["output"] = execution_timeout_message()
        result["execution_timed_out"] = True


async def execute_with_token_retry(
    agent_executor: Any,
    user_input: str,
    callbacks: List[Any],
    cancel_event: Any = None,
    max_trim_retries: int = 2,
    max_transient_retries: int = 2,
    pass_budget_seconds: Optional[float] = None,
    workflow_deadline: Any = None,
) -> Tuple[Any, str]:
    """Run one agent pass, recovering from each model failure kind in the way that fits it.

    ``model_error_policy`` defines the failure kinds and their recovery. LangChain's ``.with_retry`` already repeats a single failed model call for typed ``TransientModelError`` failures; this loop never restarts the pass for those, because a restart re-executes tool calls that already ran.

    ``pass_budget_seconds`` replaces the native executor time cap for staged passes. It counts only active time: paused intervals recorded on the workflow deadline (approvals, command input, deliberate waits) are excluded.
    """
    import asyncio
    import time

    current_input = user_input
    trim_attempts = 0
    transient_attempts = 0
    empty_generation_retried = False
    pass_capture_offset = agent_tool_action_capture_offset(get_current_agent_context())
    budget_deadline = (
        workflow_deadline if _supports_pause_accounting(workflow_deadline) else current_pausable_deadline()
    )
    pass_started_at = time.monotonic()
    paused_at_start = _paused_seconds(budget_deadline)

    def _is_canceled() -> bool:
        return bool(cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set())

    def _active_pass_seconds() -> float:
        paused_during_pass = max(0.0, _paused_seconds(budget_deadline) - paused_at_start)
        return max(0.0, (time.monotonic() - pass_started_at) - paused_during_pass)

    def _budget_remaining() -> Optional[float]:
        if pass_budget_seconds is None:
            return None
        return float(pass_budget_seconds) - _active_pass_seconds()

    def _captured_steps() -> List[Any]:
        return captured_agent_actions_as_intermediate_steps(
            get_current_agent_context(),
            since_offset=pass_capture_offset,
        )

    async def _await_agent_invoke(input_text: str) -> Any:
        if _is_canceled():
            raise asyncio.CancelledError()

        invoke_task = asyncio.create_task(agent_executor.ainvoke(
            {"input": input_text},
            config={"callbacks": callbacks} if callbacks else None,
        ))
        cancel_task = None
        waiters = {invoke_task}
        if cancel_event is not None and hasattr(cancel_event, "wait"):
            cancel_task = asyncio.create_task(cancel_event.wait())
            waiters.add(cancel_task)

        try:
            while True:
                remaining = _budget_remaining()
                if remaining is not None and remaining <= 0:
                    invoke_task.cancel()
                    await asyncio.gather(invoke_task, return_exceptions=True)
                    raise PassBudgetExhausted()
                wait_timeout = None if remaining is None else min(remaining, _BUDGET_POLL_SECONDS)
                done, _pending = await asyncio.wait(
                    waiters,
                    timeout=wait_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task is not None and cancel_task in done and cancel_task.result():
                    invoke_task.cancel()
                    await asyncio.gather(invoke_task, return_exceptions=True)
                    raise asyncio.CancelledError()
                if invoke_task in done:
                    return invoke_task.result()
        except asyncio.CancelledError:
            invoke_task.cancel()
            pending_cleanup = [invoke_task]
            if cancel_task is not None:
                cancel_task.cancel()
                pending_cleanup.append(cancel_task)
            await asyncio.gather(*pending_cleanup, return_exceptions=True)
            raise
        finally:
            if cancel_task is not None and not cancel_task.done():
                cancel_task.cancel()

    async def _wait_for_retry_backoff(seconds: float) -> None:
        if _is_canceled():
            raise asyncio.CancelledError()
        if cancel_event is None or not hasattr(cancel_event, "wait"):
            await asyncio.sleep(seconds)
            return
        sleep_task = asyncio.create_task(asyncio.sleep(seconds))
        cancel_task = asyncio.create_task(cancel_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {sleep_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done and cancel_task.result():
                sleep_task.cancel()
                await asyncio.gather(sleep_task, return_exceptions=True)
                raise asyncio.CancelledError()
        finally:
            for task in (sleep_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleep_task, cancel_task, return_exceptions=True)

    while True:
        try:
            result = await _await_agent_invoke(current_input)
            _relabel_execution_timeout(result)
            return result, current_input

        except RepeatedInvalidToolCallStop as guard_stop:
            # The agent looped on the same invalid tool call past the guard's
            # stop threshold. Convert it into a controlled synthetic result so
            # downstream finalization produces a partial/failure outcome instead
            # of waiting for the pass budget.
            logger.warning(
                "🛑 Tool repetition guard stopped the pass: tool=%s repeat_count=%s",
                guard_stop.tool_name,
                guard_stop.repeat_count,
            )
            synthetic_result = {
                "output": guard_stop.agent_output,
                "intermediate_steps": _captured_steps(),
                "tool_repetition_guard_stop": guard_stop.diagnostic,
            }
            return synthetic_result, current_input

        except PassBudgetExhausted:
            active_seconds = _active_pass_seconds()
            logger.warning(
                "⏱️ Pass budget exhausted: %.1fs active of %.1fs allowed; returning captured steps",
                active_seconds,
                float(pass_budget_seconds or 0.0),
            )
            return {
                "output": _pass_budget_message(pass_budget_seconds),
                "intermediate_steps": _captured_steps(),
                "execution_timed_out": True,
                "pass_budget_exhausted": {
                    "budget_seconds": float(pass_budget_seconds or 0.0),
                    "active_seconds": round(active_seconds, 1),
                },
            }, current_input

        except Exception as _err:
            error_str = str(_err)
            classification = classify_model_error(_err)

            from ....model_usage_service import is_model_unreachable_error
            handler = next(
                (cb for cb in (callbacks or []) if hasattr(cb, "completed_llm_calls")),
                None,
            )
            no_progress_yet = handler is None or handler.completed_llm_calls == 0

            if classification.kind == EMPTY_GENERATION:
                if empty_generation_retried:
                    logger.error("❌ STREAMING EMPTY: async retry also returned no generation")
                    return {
                        "output": "The agent returned no response after a retry.",
                        "intermediate_steps": [],
                        "empty_generation_failure": True,
                    }, current_input
                empty_generation_retried = True
                logger.warning("⚠️ STREAMING EMPTY: retrying cancellation-aware async invoke once")
                continue

            if classification.kind == CONTEXT_OVERFLOW:
                actual_tokens = classification.actual_tokens
                max_tokens = classification.max_tokens
                token_summary = overflow_token_summary(actual_tokens, max_tokens)
                # Measure against every step captured since this pass started, not
                # just since the last failure -- once a digest resume has run, a
                # second overflow with no newly-recorded step would otherwise be
                # misread as the zero-steps case and fall through to a blind char
                # trim of the (now short) digest text.
                recovered_steps = _captured_steps()

                if trim_attempts >= max_trim_retries:
                    logger.error(
                        "❌ Context window exceeded after %s trim attempt(s)%s",
                        max_trim_retries,
                        token_summary,
                    )
                    if recovered_steps:
                        logger.warning(
                            "⚠️ Finalizing %s captured step(s) instead of raising a resultless failure",
                            len(recovered_steps),
                        )
                        return {
                            "output": (
                                f"Stopped: the model's context window was exceeded{token_summary} "
                                f"after {max_trim_retries} attempt(s) to continue. "
                                f"{len(recovered_steps)} tool step(s) completed before that."
                            ),
                            "intermediate_steps": recovered_steps,
                            "context_window_exceeded": {
                                "actual_tokens": actual_tokens,
                                "max_tokens": max_tokens,
                            },
                        }, current_input
                    raise

                trim_attempts += 1
                if recovered_steps:
                    logger.warning(
                        "⚠️ Prompt too long%s (attempt %s/%s). Resuming with a digest of %s captured tool step(s).",
                        token_summary,
                        trim_attempts,
                        max_trim_retries,
                        len(recovered_steps),
                    )
                    current_input = build_context_overflow_resume_input(user_input, recovered_steps)
                else:
                    chars_to_remove = overflow_chars_to_remove(current_input, actual_tokens, max_tokens)
                    logger.warning(
                        "⚠️ Prompt too long%s (attempt %s/%s). Trimming ~%s chars from context...",
                        token_summary,
                        trim_attempts,
                        max_trim_retries,
                        f"{chars_to_remove:,}",
                    )
                    trimmed_input = trim_oldest_context(current_input, chars_to_remove, logger)
                    if trimmed_input is None:
                        logger.error("❌ Cannot trim context further - no safe trim points found")
                        raise
                    current_input = trimmed_input

                logger.info(f"📏 Retrying with updated input ({len(current_input):,} chars)")
                transient_attempts = 0
                continue

            if classification.kind == TRANSIENT:
                if transient_attempts >= max_transient_retries:
                    logger.error(
                        f"❌ Transient error persisted after {max_transient_retries} retries: {error_str[:200]}"
                    )
                    if no_progress_yet and is_model_unreachable_error(_err):
                        raise ModelUnavailableBeforeFirstResponse(_err) from _err
                    raise
                backoff_seconds = 2 ** transient_attempts
                logger.warning(
                    f"⚠️ Transient network error detected (attempt {transient_attempts + 1}/{max_transient_retries}): "
                    f"{error_str[:200]}. Retrying after {backoff_seconds}s backoff..."
                )
                await _wait_for_retry_backoff(backoff_seconds)
                transient_attempts += 1
                continue

            if classification.kind == TRANSIENT_EXHAUSTED:
                logger.error(
                    "❌ Model call still failing after LLM-level retries; not restarting the pass: %s",
                    error_str[:200],
                )

            # Authentication/authorization failures are never worth retrying with
            # backoff (a bad key stays bad), but are still eligible for a one-time
            # local fallback if nothing has succeeded yet this task.
            if no_progress_yet and is_model_unreachable_error(_err):
                raise ModelUnavailableBeforeFirstResponse(_err) from _err
            raise

