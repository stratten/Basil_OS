"""
Agent Execution Core for LangGraph Agent Execution.

Handles the core execution phase: context preparation, callback setup, and agent invocation.
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple, TYPE_CHECKING

from ..planning.agent_context_assembler import AgentContextAssembler
from ...shared.agent_runtime_context import get_current_agent_context
from ...shared.prompt_context_trimming import (
    build_context_overflow_resume_input,
    parse_token_limit_error,
    trim_oldest_context,
)
from .llama_cpp_langchain_adapter import LocalModelContextWindowExceeded
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


def _is_transient_error(error: Exception) -> bool:
    """
    Check if an error is a transient network error that should be retried.
    
    Args:
        error: The exception to check
        
    Returns:
        True if the error is transient and should be retried
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # Network-related errors
    transient_indicators = [
        "timeout",
        "connection",
        "network",
        "connection reset",
        "connection refused",
        "connection aborted",
        "broken pipe",
        "temporary failure",
        "service unavailable",
        "gateway timeout",
        "bad gateway",
        "request timeout",
        "read timeout",
        "connect timeout",
        "socket",
        "dns",
        "name resolution",
        "eof",
        "end of file"
    ]
    
    # Check error message
    for indicator in transient_indicators:
        if indicator in error_str:
            return True
    
    # Check error type (common network exception types)
    transient_types = [
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "OSError",  # Many network errors manifest as OSError
    ]
    
    if error_type in transient_types:
        return True
    
    # Check for httpx/requests specific errors
    if "httpx" in error_str or "requests" in error_str:
        if any(indicator in error_str for indicator in ["timeout", "connection", "network"]):
            return True
    
    return False


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
    max_transient_retries: int = 2
) -> Tuple[Any, str]:
    """
    Execute the agent with automatic token-limit retry and transient error retry.
    
    This function handles two types of retries:
    1. Token limit errors: Trims context and retries (existing behavior)
    2. Transient network errors: Retries with exponential backoff (new behavior)
    
    Note: General error retry is also handled by LangChain's native mechanisms:
    - LLM-level retries via .with_retry() on the model
    - Tool errors fed back to agent via handle_parsing_errors
    - Agent sees errors and can reason about recovery
    """
    import asyncio
    import time
    
    current_input = user_input
    transient_retry_count = 0
    pass_capture_offset = agent_tool_action_capture_offset(get_current_agent_context())

    def _is_cancelled() -> bool:
        return bool(cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set())

    async def _await_agent_invoke(input_text: str) -> Any:
        if _is_cancelled():
            raise asyncio.CancelledError()

        invoke_task = asyncio.create_task(agent_executor.ainvoke(
            {"input": input_text},
            config={"callbacks": callbacks} if callbacks else None,
        ))

        if cancel_event is None or not hasattr(cancel_event, "wait"):
            return await invoke_task

        cancel_task = asyncio.create_task(cancel_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {invoke_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done and cancel_task.result():
                invoke_task.cancel()
                await asyncio.gather(invoke_task, return_exceptions=True)
                raise asyncio.CancelledError()
            return await invoke_task
        except asyncio.CancelledError:
            invoke_task.cancel()
            cancel_task.cancel()
            await asyncio.gather(invoke_task, cancel_task, return_exceptions=True)
            raise
        finally:
            if not cancel_task.done():
                cancel_task.cancel()

    async def _wait_for_retry_backoff(seconds: float) -> None:
        if _is_cancelled():
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
    
    for trim_attempt in range(max_trim_retries + 1):
        try:
            result = await _await_agent_invoke(current_input)
            _relabel_execution_timeout(result)
            return result, current_input

        except RepeatedInvalidToolCallStop as guard_stop:
            # The agent looped on the same invalid tool call past the guard's
            # stop threshold. Convert it into a controlled synthetic result so
            # downstream finalization produces a partial/failure outcome instead
            # of waiting for the executor's wall-clock cap.
            logger.warning(
                "🛑 Tool repetition guard stopped the pass: tool=%s repeat_count=%s",
                guard_stop.tool_name,
                guard_stop.repeat_count,
            )
            recovered_steps = captured_agent_actions_as_intermediate_steps(
                get_current_agent_context(),
                since_offset=pass_capture_offset,
            )
            synthetic_result = {
                "output": guard_stop.agent_output,
                "intermediate_steps": recovered_steps,
                "tool_repetition_guard_stop": guard_stop.diagnostic,
            }
            return synthetic_result, current_input

        except ValueError as _stream_err:
            if "No generation chunks were returned" in str(_stream_err):
                logger.warning("⚠️ STREAMING EMPTY: retrying cancellation-aware async invoke once")
                try:
                    result = await _await_agent_invoke(current_input)
                except ValueError as retry_error:
                    if "No generation chunks were returned" not in str(retry_error):
                        raise
                    logger.error("❌ STREAMING EMPTY: async retry also returned no generation")
                    return {
                        "output": "The agent returned no response after a retry.",
                        "intermediate_steps": [],
                        "empty_generation_failure": True,
                    }, current_input
                _relabel_execution_timeout(result)
                return result, current_input
            else:
                raise
                
        except Exception as _err:
            error_str = str(_err)

            from ....model_usage_service import is_model_unreachable_error
            handler = next(
                (cb for cb in (callbacks or []) if hasattr(cb, "completed_llm_calls")),
                None,
            )
            no_progress_yet = handler is None or handler.completed_llm_calls == 0

            # Check if this is a transient network error
            if _is_transient_error(_err):
                if transient_retry_count >= max_transient_retries:
                    logger.error(
                        f"❌ Transient error persisted after {max_transient_retries} retries: {error_str[:200]}"
                    )
                    if no_progress_yet and is_model_unreachable_error(_err):
                        raise ModelUnavailableBeforeFirstResponse(_err) from _err
                    raise
                
                # Exponential backoff: 1s, 2s, 4s
                backoff_seconds = 2 ** transient_retry_count
                logger.warning(
                    f"⚠️ Transient network error detected (attempt {transient_retry_count + 1}/{max_transient_retries}): "
                    f"{error_str[:200]}. Retrying after {backoff_seconds}s backoff..."
                )
                
                await _wait_for_retry_backoff(backoff_seconds)
                transient_retry_count += 1
                continue  # Retry the same input without trimming

            # Authentication/authorization failures are never worth retrying with
            # backoff (a bad key stays bad), but are still eligible for a one-time
            # local fallback if nothing has succeeded yet this task.
            if no_progress_yet and is_model_unreachable_error(_err):
                raise ModelUnavailableBeforeFirstResponse(_err) from _err

            # Check if this is a context-window overflow: either the local
            # llama.cpp path's typed exception (computed from the model's own
            # tokenizer, never parsed from error text), or a cloud provider's
            # detectable wording via parse_token_limit_error.
            if isinstance(_err, LocalModelContextWindowExceeded):
                actual_tokens, max_tokens = _err.actual_tokens, _err.max_tokens
            else:
                token_info = parse_token_limit_error(error_str)
                if token_info is None:
                    # Not a transient error or token error - re-raise
                    raise
                actual_tokens, max_tokens = token_info

            # Measure against every step captured since this pass started, not
            # just since the last failure -- once a digest resume has run, a
            # second overflow with no newly-recorded step would otherwise be
            # misread as the zero-steps case and fall through to a blind char
            # trim of the (now short) digest text, which has no safe trim
            # points and would raise instead of retrying or exhausting cleanly.
            recovered_steps = captured_agent_actions_as_intermediate_steps(
                get_current_agent_context(), since_offset=pass_capture_offset,
            )

            if trim_attempt >= max_trim_retries:
                logger.error(f"❌ Token limit exceeded after {max_trim_retries} trim attempts: {actual_tokens:,} > {max_tokens:,}")
                if recovered_steps:
                    logger.warning(
                        "⚠️ Finalizing %s captured step(s) instead of raising a resultless failure",
                        len(recovered_steps),
                    )
                    return {
                        "output": (
                            f"Stopped: the model's context window was exceeded "
                            f"({actual_tokens:,} > {max_tokens:,} tokens) after "
                            f"{max_trim_retries} attempt(s) to continue. "
                            f"{len(recovered_steps)} tool step(s) completed before that."
                        ),
                        "intermediate_steps": recovered_steps,
                        "context_window_exceeded": {
                            "actual_tokens": actual_tokens,
                            "max_tokens": max_tokens,
                        },
                    }, current_input
                raise

            if recovered_steps:
                logger.warning(
                    "⚠️ Prompt too long: %s > %s tokens (attempt %s/%s). Resuming "
                    "with a digest of %s captured tool step(s) instead of blindly "
                    "trimming the original input.",
                    f"{actual_tokens:,}", f"{max_tokens:,}", trim_attempt + 1, max_trim_retries, len(recovered_steps),
                )
                current_input = build_context_overflow_resume_input(user_input, recovered_steps)
            else:
                overage_tokens = actual_tokens - max_tokens + 5000
                chars_to_remove = overage_tokens * 4

                logger.warning(
                    f"⚠️ Prompt too long: {actual_tokens:,} > {max_tokens:,} tokens "
                    f"(attempt {trim_attempt + 1}/{max_trim_retries}). "
                    f"Trimming ~{chars_to_remove:,} chars from context..."
                )

                trimmed_input = trim_oldest_context(current_input, chars_to_remove, logger)

                if trimmed_input is None:
                    logger.error("❌ Cannot trim context further - no safe trim points found")
                    raise

                current_input = trimmed_input

            logger.info(f"📏 Retrying with updated input ({len(current_input):,} chars)")
            # Reset transient retry count when trimming (new attempt)
            transient_retry_count = 0

    raise RuntimeError("Execution loop completed without result")
