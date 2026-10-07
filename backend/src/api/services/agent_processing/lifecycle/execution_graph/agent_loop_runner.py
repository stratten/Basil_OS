"""Run Basil's inner agent loop as one LangChain ``create_agent`` conversation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from api.core.logging.api_logger import api_logger

from ...shared.agent_runtime_context import (
    AGENT_RUN_STARTED_AT_KEY,
    reset_current_agent_context,
    set_current_agent_context,
)
from ...shared.agent_run_control import discard_run_control, run_control_for
from ...shared.workflow_budget_pause import current_pausable_deadline
from ..runtime.activity_phase_notifier import emit_activity_phase
from ..planning.agent_context_assembler import CONVERSATION_THREAD_SEEDED_KEY
from .agent_conversation_thread import prepare_thread_for_model
from .agent_execution_core import format_chain_context
from .agent_executor_factory import _log_prompt_tool_surface_telemetry
from .agent_loop_messages import (
    count_ai_messages,
    final_agent_output,
    is_pause_request,
    messages_to_intermediate_steps,
    seed_resumed_messages,
    serialize_agent_messages,
)
from .agent_loop_model_recovery import AgentRunFlags, ModelRecoveryMiddleware
from .agent_loop_nudges import CompletionNudgeMiddleware, ProgressBridgeMiddleware
from .agent_loop_run_control import RunControlMiddleware, record_undelivered_notes
from .agent_loop_tool_surface import ToolSurfaceMiddleware, ToolSurfaceTracker
from .context_window_budget import model_display_label, prompt_budget_tokens, resolve_context_window_tokens
from .conversation_turns import (
    current_turn_messages,
    mark_turn_input,
    render_thread_recap,
    turn_input_index,
    turn_input_text,
)
from .execution_limits import AGENT_RUN_MAX_ACTIVE_SECONDS, active_time_limit_message
from .service_tooling.tool_call_repetition_guard import (
    RepeatedInvalidToolCallStop,
    wrap_tools_with_repetition_guard,
)
from .service_tooling.tool_input_normalization import normalize_structured_tool_args_schemas
from .system_prompts import get_agent_system_prompt
from .workflow_deadline import deadline_evidence, deadline_from_context

logger = api_logger.getChild("agent_loop_runner")

AGENT_LOOP_GRAPH_NAME = "basil_inner_loop"
AGENT_LOOP_RECURSION_LIMIT = 10_000
_BUDGET_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class AgentRunRequest:
    """Inputs for one run of the inner agent loop."""

    langchain_llm: Any
    state: Any
    user_profile_context: str
    communication_context_section: str
    custom_instructions_section: str
    selected_skill_section: str
    live_callbacks: Any
    cancel_event: Any
    prior_thread: Any = None


@dataclass
class AgentRunResult:
    """Outputs consumed by synthesis, finalization, and finalizer recovery."""

    result: dict[str, Any]
    loaded_families: list[str]
    intermediate_steps: list[Any]
    agent_output: str
    final_input: str
    messages: list[BaseMessage]
    surface_tools: list[Any]
    system_prompt_text: str


@dataclass
class AgentDriveOutcome:
    messages: list[BaseMessage]
    budget_exhausted: bool = False
    active_seconds: float = 0.0
    guard_stop: Optional[RepeatedInvalidToolCallStop] = None


def build_system_prompt(request: AgentRunRequest) -> str:
    return get_agent_system_prompt(
        user_profile_context=request.user_profile_context,
        communication_context_section=request.communication_context_section,
        custom_instructions_section=request.custom_instructions_section,
        preloaded_skill_section=request.selected_skill_section,
    )


def prepare_agent_tools(tools: Sequence[Any]) -> list[Any]:
    return wrap_tools_with_repetition_guard(normalize_structured_tool_args_schemas(list(tools)))


def build_agent_loop_graph(
    *,
    langchain_llm: Any,
    tools: Sequence[Any],
    system_prompt_text: str,
    middleware: Sequence[Any],
) -> Any:
    return create_agent(
        langchain_llm,
        tools=list(tools),
        system_prompt=system_prompt_text,
        middleware=list(middleware),
        checkpointer=False,
        name=AGENT_LOOP_GRAPH_NAME,
    )


def _is_canceled(cancel_event: Any) -> bool:
    return bool(cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set())


def _stop_live_tool_runs(callbacks: Sequence[Any]) -> None:
    for callback in callbacks or ():
        stop = getattr(callback, "stop_active_tool_runs", None)
        if callable(stop):
            stop()


def _budget_deadline(workflow_deadline: Any) -> Any:
    if callable(getattr(workflow_deadline, "paused_seconds", None)):
        return workflow_deadline
    return current_pausable_deadline()


def _paused_seconds(deadline: Any) -> float:
    if not callable(getattr(deadline, "paused_seconds", None)):
        return 0.0
    try:
        return float(deadline.paused_seconds())
    except Exception:
        return 0.0


async def drive_agent_loop(
    graph: Any,
    messages: Sequence[BaseMessage],
    *,
    callbacks: Any,
    cancel_event: Any,
    budget_seconds: Optional[float],
    workflow_deadline: Any = None,
    attach_messages_on_pause: bool = True,
) -> AgentDriveOutcome:
    """Stream one graph run under a pause-aware active-time budget and cooperative cancellation."""
    snapshot: list[BaseMessage] = list(messages)
    config: dict[str, Any] = {"recursion_limit": AGENT_LOOP_RECURSION_LIMIT}
    if callbacks:
        config["callbacks"] = list(callbacks)

    async def _consume() -> None:
        async for mode, data in graph.astream(
            {"messages": list(messages)},
            config=config,
            stream_mode=["values", "messages"],
        ):
            if mode == "values" and isinstance(data, dict) and isinstance(data.get("messages"), list):
                snapshot[:] = data["messages"]

    budget_deadline = _budget_deadline(workflow_deadline)
    started_at = time.monotonic()
    paused_at_start = _paused_seconds(budget_deadline)

    def _active_seconds() -> float:
        paused_during_run = max(0.0, _paused_seconds(budget_deadline) - paused_at_start)
        return max(0.0, (time.monotonic() - started_at) - paused_during_run)

    if _is_canceled(cancel_event):
        raise asyncio.CancelledError()
    run_task = asyncio.create_task(_consume())
    cancel_task = (
        asyncio.create_task(cancel_event.wait())
        if cancel_event is not None and hasattr(cancel_event, "wait")
        else None
    )
    waiters = {run_task} if cancel_task is None else {run_task, cancel_task}
    try:
        while True:
            remaining = None if budget_seconds is None else float(budget_seconds) - _active_seconds()
            if remaining is not None and remaining <= 0:
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
                return AgentDriveOutcome(messages=list(snapshot), budget_exhausted=True, active_seconds=_active_seconds())
            wait_timeout = None if remaining is None else min(remaining, _BUDGET_POLL_SECONDS)
            done, _pending = await asyncio.wait(waiters, timeout=wait_timeout, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task is not None and cancel_task in done:
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
                raise asyncio.CancelledError()
            if run_task not in done:
                continue
            try:
                run_task.result()
            except RepeatedInvalidToolCallStop as guard_stop:
                return AgentDriveOutcome(messages=list(snapshot), active_seconds=_active_seconds(), guard_stop=guard_stop)
            except Exception as error:
                if attach_messages_on_pause and is_pause_request(error):
                    error.basil_agent_messages = serialize_agent_messages(
                        [*snapshot, *getattr(error, "basil_pending_messages", ())]
                    )
                raise
            return AgentDriveOutcome(messages=list(snapshot), active_seconds=_active_seconds())
    except asyncio.CancelledError:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
        raise
    finally:
        if cancel_task is not None and not cancel_task.done():
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)


def _initial_families(context: Optional[dict[str, Any]]) -> list[str]:
    supervision = context.get("delegated_supervision") if isinstance(context, dict) else None
    if isinstance(supervision, dict) and str(supervision.get("delegated_agent_run_id") or "").strip():
        return ["delegation"]
    return []


def _initial_messages(state: Any, prior_thread: Any = None, langchain_llm: Any = None) -> list[BaseMessage]:
    resume_input = getattr(state, "agent_resume_input", None)
    if resume_input is not None:
        seeded = seed_resumed_messages(
            getattr(state, "agent_messages", None),
            resume_input,
            getattr(state, "agent_pending_tool_call_id", None),
        )
        if seeded:
            logger.info("🔁 Resuming the paused agent conversation with %s message(s)", len(seeded))
            return seeded
    prior_messages = prepare_thread_for_model(prior_thread, langchain_llm)
    if prior_messages:
        context = getattr(state, "context", None)
        if isinstance(context, dict):
            context[CONVERSATION_THREAD_SEEDED_KEY] = True
        logger.info("🧵 Continuing the previous turn's conversation with %s message(s)", len(prior_messages))
    return [*prior_messages, mark_turn_input(HumanMessage(content=format_chain_context(state)))]


def _synthesis_input(messages: Sequence[BaseMessage]) -> str:
    """The current request, preceded by a short recap when earlier turns are in the conversation."""
    text = turn_input_text(messages)
    index = turn_input_index(messages)
    if not index:
        return text
    recap = render_thread_recap(messages[:index])
    return f"{recap}\n\n{text}" if recap else text


async def run_agent_loop(request: AgentRunRequest) -> AgentRunResult:
    """Run the whole task as one conversation and return the aggregate outcome."""
    state = request.state
    context = state.context if isinstance(state.context, dict) else None
    deadline = deadline_from_context(state.context)
    if context is not None:
        context.setdefault(AGENT_RUN_STARTED_AT_KEY, time.time())

    tracker = ToolSurfaceTracker(
        state.available_tools.tools,
        initial_families=_initial_families(context),
        context=context,
    )
    system_prompt_text = build_system_prompt(request)
    messages = _initial_messages(state, request.prior_thread, request.langchain_llm)
    final_input = _synthesis_input(messages)
    await emit_activity_phase(
        state,
        phase="staged_tool_loading",
        lifecycle_state="in_progress",
        title="Loading execution tools",
        source="agent_loop_runner",
    )

    budget_seconds = float(AGENT_RUN_MAX_ACTIVE_SECONDS)
    can_start = True
    if deadline is not None:
        if deadline.can_start_execution(per_pass_cap_seconds=AGENT_RUN_MAX_ACTIVE_SECONDS):
            budget_seconds = deadline.execution_seconds_available(per_pass_cap_seconds=AGENT_RUN_MAX_ACTIVE_SECONDS)
        else:
            can_start = False
            if context is not None:
                context["workflow_deadline_evidence"] = deadline_evidence(
                    deadline,
                    reason="insufficient_remaining_time_for_agent_run",
                )
            logger.warning("Skipping the agent run due to workflow deadline")

    flags = AgentRunFlags()

    def _report_surface(surface_tools: list[Any]) -> None:
        stage = "expanded" if tracker.loaded_families else "core"
        logger.info(
            "[AgentTelemetry] staged-tool-surface "
            f"stage={stage} loaded_families={tracker.loaded_families} "
            f"initial_tool_count={tracker.core_tool_count} expanded_tool_count={len(surface_tools)} "
            f"all_tool_count={len(tracker.all_tools)} expansion_count={len(tracker.loaded_families)}"
        )
        _log_prompt_tool_surface_telemetry(
            langchain_llm=request.langchain_llm,
            tools=surface_tools,
            system_prompt_text=system_prompt_text,
            staged_tool_metadata={
                "stage": stage,
                "loaded_families": list(tracker.loaded_families),
                "family_count": len(tracker.loaded_families),
                "initial_tool_count": tracker.core_tool_count,
                "expanded_tool_count": len(surface_tools),
                "expansion_count": len(tracker.loaded_families),
            },
        )

    if can_start:
        window_tokens = await resolve_context_window_tokens(request.langchain_llm, context)
        budget_tokens = prompt_budget_tokens(request.langchain_llm, window_tokens)
        if budget_tokens:
            logger.info("📏 Prompt budget %s tokens for a %s-token context window", budget_tokens, window_tokens)
        agent_task_id = str((context or {}).get("agent_task_id") or "").strip()
        run_control = run_control_for(agent_task_id) if agent_task_id else None
        broadcast = getattr((context or {}).get("websocket_manager"), "broadcast", None)
        graph = build_agent_loop_graph(
            langchain_llm=request.langchain_llm,
            tools=prepare_agent_tools(tracker.registered_tools()),
            system_prompt_text=system_prompt_text,
            middleware=[
                *([RunControlMiddleware(run_control, agent_task_id, broadcast)] if run_control is not None else []),
                ProgressBridgeMiddleware(request.live_callbacks),
                ToolSurfaceMiddleware(tracker, on_surface_change=_report_surface),
                ModelRecoveryMiddleware(
                    flags,
                    completed_model_calls=count_ai_messages(current_turn_messages(messages)),
                    prompt_budget_tokens=budget_tokens,
                    context_window_tokens=window_tokens,
                    model_label=model_display_label(request.langchain_llm, context),
                ),
                CompletionNudgeMiddleware(tracker, flags),
            ],
        )
        runtime_context_token = set_current_agent_context(state.context)
        undelivered_notes: list[Any] = []
        if run_control is not None:
            run_control.attach()
        try:
            outcome = await drive_agent_loop(
                graph,
                messages,
                callbacks=request.live_callbacks,
                cancel_event=request.cancel_event,
                budget_seconds=budget_seconds,
                workflow_deadline=deadline,
            )
        except asyncio.CancelledError:
            _stop_live_tool_runs(request.live_callbacks)
            raise
        finally:
            reset_current_agent_context(runtime_context_token)
            if run_control is not None:
                undelivered_notes = run_control.detach()
                discard_run_control(agent_task_id, run_control)
        if undelivered_notes:
            await record_undelivered_notes(agent_task_id, undelivered_notes, broadcast)
    else:
        outcome = AgentDriveOutcome(messages=list(messages))

    turn_messages = current_turn_messages(outcome.messages)
    steps = messages_to_intermediate_steps(turn_messages)
    if not can_start:
        result: dict[str, Any] = {"output": "", "intermediate_steps": steps, "execution_timed_out": True}
    elif outcome.guard_stop is not None:
        logger.warning(
            "🛑 Tool repetition guard stopped the run: tool=%s repeat_count=%s",
            outcome.guard_stop.tool_name,
            outcome.guard_stop.repeat_count,
        )
        result = {
            "output": outcome.guard_stop.agent_output,
            "intermediate_steps": steps,
            "tool_repetition_guard_stop": outcome.guard_stop.diagnostic,
        }
    elif outcome.budget_exhausted:
        logger.warning(
            "⏱️ Agent run budget exhausted: %.1fs active of %.1fs allowed",
            outcome.active_seconds,
            budget_seconds,
        )
        result = {
            "output": active_time_limit_message(budget_seconds),
            "intermediate_steps": steps,
            "execution_timed_out": True,
            "pass_budget_exhausted": {
                "budget_seconds": budget_seconds,
                "active_seconds": round(outcome.active_seconds, 1),
            },
        }
    else:
        result = {
            "output": final_agent_output(turn_messages),
            "intermediate_steps": steps,
            **flags.as_result_fields(),
        }

    await emit_activity_phase(
        state,
        phase="staged_tool_loading",
        lifecycle_state="completed",
        title="Execution tools ready",
        source="agent_loop_runner",
    )
    if _is_canceled(request.cancel_event):
        raise asyncio.CancelledError()

    return AgentRunResult(
        result=result,
        loaded_families=list(tracker.loaded_families),
        intermediate_steps=steps,
        agent_output=str(result.get("output") or ""),
        final_input=final_input,
        messages=list(outcome.messages),
        surface_tools=tracker.surface_tools(),
        system_prompt_text=system_prompt_text,
    )


class FinalizerRecoveryAgent:
    """Run the finalizer-recovery prompt as its own short loop behind the ``ainvoke`` shape recovery expects."""

    def __init__(
        self,
        *,
        langchain_llm: Any,
        tools: Sequence[Any],
        system_prompt_text: str,
        cancel_event: Any,
        budget_seconds: Optional[float],
        workflow_deadline: Any = None,
    ) -> None:
        self.langchain_llm = langchain_llm
        self.tools = list(tools)
        self.system_prompt_text = system_prompt_text
        self.cancel_event = cancel_event
        self.budget_seconds = budget_seconds
        self.workflow_deadline = workflow_deadline

    async def ainvoke(self, inputs: dict[str, Any], config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        callbacks = list((config or {}).get("callbacks") or [])
        graph = build_agent_loop_graph(
            langchain_llm=self.langchain_llm,
            tools=prepare_agent_tools(self.tools),
            system_prompt_text=self.system_prompt_text,
            middleware=[
                ProgressBridgeMiddleware(callbacks),
                ModelRecoveryMiddleware(AgentRunFlags(), completed_model_calls=1),
            ],
        )
        outcome = await drive_agent_loop(
            graph,
            [HumanMessage(content=str(inputs.get("input") or ""))],
            callbacks=callbacks,
            cancel_event=self.cancel_event,
            budget_seconds=self.budget_seconds,
            workflow_deadline=self.workflow_deadline,
            attach_messages_on_pause=False,
        )
        return {
            "output": final_agent_output(outcome.messages),
            "intermediate_steps": messages_to_intermediate_steps(outcome.messages),
        }
