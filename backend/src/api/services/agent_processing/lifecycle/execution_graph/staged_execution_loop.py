"""Staged tool-loading executor loop.

Runs the bounded sequence of LangChain executor passes that progressively
expand the bound tool surface as the model loads tool families. Extracted from
``agent_graph_nodes`` so the loop, its termination predicate, and the
redundant-reload recovery live in one focused, testable module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from api.core.logging.api_logger import api_logger

from ...shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from ..runtime.activity_phase_notifier import emit_activity_phase
from .agent_execution_core import execute_with_token_retry, format_chain_context
from .execution_limits import AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS
from .agent_executor_factory import create_agent_executor
from .agent_result_synthesis import normalize_agent_executor_output
from .workflow_deadline import deadline_evidence, deadline_from_context
from .service_tooling.staged_tool_loading_repair import (
    collect_new_tool_families_from_steps,
    scripting_floor_owed,
)
from .discovery_handoff import build_discovery_handoff
from .service_tooling.tool_family_catalog import (
    BASELINE_FALLBACK_FAMILY_NAMES,
    create_load_tool_family_tool,
    select_core_tools,
    select_tools_for_families,
)

logger = api_logger.getChild("staged_execution_loop")

MAX_STAGED_EXECUTION_PASSES = 4


@dataclass(frozen=True)
class StagedExecutionRequest:
    """Inputs required to run the staged tool-loading passes."""

    langchain_llm: Any
    state: Any
    user_profile_context: str
    communication_context_section: str
    custom_instructions_section: str
    selected_skill_section: str
    live_callbacks: Any
    cancel_event: Any


@dataclass
class StagedExecutionResult:
    """Outputs consumed by finalization and legacy recovery."""

    result: dict[str, Any]
    loaded_families: list[str]
    intermediate_steps: list[Any]
    agent_output: str
    final_input: Any
    active_tools_for_recovery: list[Any]
    core_tools: list[Any]


def _redundant_reload_correction_block(all_tools: list[Any], families: list[str]) -> str:
    """Build a corrective instruction naming already-available family tools."""
    correction_tools = select_tools_for_families(all_tools, families, include_core_tools=False)
    tool_names = [
        name
        for name in (str(getattr(item, "name", "") or "") for item in correction_tools)
        if name
    ]
    return (
        "\n\nCRITICAL - REDUNDANT TOOL-FAMILY LOAD DETECTED:\n"
        f"- The tool families [{', '.join(families)}] are ALREADY available. "
        "Do NOT call load_tool_family for them again.\n"
        f"- Their exact tools are bound and ready to call now: {', '.join(tool_names)}.\n"
        "- Call the appropriate tool directly to perform the task instead of reloading."
    )


async def run_staged_tool_loading(request: StagedExecutionRequest) -> StagedExecutionResult:
    """Run bounded staged executor passes and return the aggregate outcome."""
    state = request.state
    deadline = deadline_from_context(state.context)

    all_tools = list(state.available_tools.tools)

    delegated_supervision = (
        state.context.get("delegated_supervision")
        if isinstance(state.context, dict)
        else None
    )
    loaded_families: list[str] = (
        ["delegation"]
        if isinstance(delegated_supervision, dict)
        and str(delegated_supervision.get("delegated_agent_run_id") or "").strip()
        else []
    )

    def _current_available_families() -> set[str]:
        return set(loaded_families) | set(BASELINE_FALLBACK_FAMILY_NAMES) | {"core"}

    family_loader_tool = create_load_tool_family_tool(
        all_tools,
        get_available_families=_current_available_families,
    )
    core_tools = select_core_tools(all_tools, family_loader_tool)

    user_input = format_chain_context(state)
    result: dict[str, Any] = {}
    final_input = user_input
    intermediate_steps: list[Any] = []
    active_tools_for_recovery = core_tools
    reload_correction: list[str] = []
    discovery_handoff_text = ""
    discovery_handoff_used = False

    for expansion_count in range(MAX_STAGED_EXECUTION_PASSES):
        await emit_activity_phase(
            state,
            phase="staged_tool_loading",
            lifecycle_state="in_progress",
            title=f"Loading execution tools (pass {expansion_count + 1})",
            source="staged_execution_loop",
        )
        if loaded_families:
            # Keep the generic execution fallbacks (automation, shell) present on
            # every expanded pass, matching select_core_tools. Otherwise loading
            # any specialized family silently strips AppleScript/shell from the
            # bound surface, which makes the model believe its documented "always
            # available" fallbacks are gone and defeats last-resort scripting.
            active_tools = select_tools_for_families(
                all_tools,
                list(loaded_families) + sorted(BASELINE_FALLBACK_FAMILY_NAMES),
                include_core_tools=True,
                loader_tool=family_loader_tool,
            )
            tool_surface_stage = "expanded"
            pass_input = (
                f"{user_input}\n\n"
                "STAGED TOOL LOADING STATE:\n"
                f"- Loaded tool families: {', '.join(loaded_families)}\n"
                "- Continue the original task now using the exact full schemas currently available.\n"
                "- If another family is genuinely required, call load_tool_family with every additional family needed."
            )
        else:
            active_tools = core_tools
            tool_surface_stage = "core"
            pass_input = user_input

        if reload_correction:
            pass_input = f"{pass_input}{_redundant_reload_correction_block(all_tools, reload_correction)}"
        if discovery_handoff_text:
            pass_input = f"{pass_input}{discovery_handoff_text}"

        active_tools_for_recovery = active_tools
        logger.info(
            "[AgentTelemetry] staged-tool-surface "
            f"stage={tool_surface_stage} loaded_families={loaded_families or []} "
            f"initial_tool_count={len(core_tools)} expanded_tool_count={len(active_tools)} "
            f"all_tool_count={len(all_tools)} expansion_count={expansion_count}"
        )
        max_execution_time = AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS
        if deadline is not None:
            if not deadline.can_start_execution(
                per_pass_cap_seconds=AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS,
            ):
                if state.context is not None:
                    state.context["workflow_deadline_evidence"] = deadline_evidence(
                        deadline,
                        reason="insufficient_remaining_time_for_staged_pass",
                    )
                logger.warning("Skipping staged execution pass due to workflow deadline")
                break
            max_execution_time = deadline.execution_seconds_available(
                per_pass_cap_seconds=AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS,
            )

        agent_executor = create_agent_executor(
            request.langchain_llm,
            active_tools,
            user_profile_context=request.user_profile_context,
            communication_context_section=request.communication_context_section,
            custom_instructions_section=request.custom_instructions_section,
            preloaded_skill_section=request.selected_skill_section,
            staged_tool_metadata={
                "stage": tool_surface_stage,
                "loaded_families": loaded_families,
                "family_count": len(loaded_families),
                "initial_tool_count": len(core_tools),
                "expanded_tool_count": len(active_tools),
                "expansion_count": expansion_count,
            },
            max_execution_time_seconds=max_execution_time,
        )

        runtime_context_token = set_current_agent_context(state.context)
        try:
            result, final_input = await execute_with_token_retry(
                agent_executor=agent_executor,
                user_input=pass_input,
                callbacks=request.live_callbacks,
                cancel_event=request.cancel_event,
            )
        finally:
            reset_current_agent_context(runtime_context_token)

        pass_intermediate_steps = result.get("intermediate_steps", [])
        intermediate_steps.extend(pass_intermediate_steps)
        load_decision = collect_new_tool_families_from_steps(pass_intermediate_steps, loaded_families)
        new_families = load_decision.new_families
        if load_decision.diagnostic and state.context is not None:
            diagnostics = state.context.setdefault("staged_tool_loading_diagnostics", [])
            if isinstance(diagnostics, list):
                diagnostics.append(load_decision.details)
        if load_decision.repair_families or load_decision.suggested_families:
            logger.info(
                "[AgentTelemetry] staged-tool-repair "
                f"repair_families={load_decision.repair_families} "
                f"suggested_families={load_decision.suggested_families} "
                f"loaded_families={loaded_families}"
            )

        if not new_families:
            if not discovery_handoff_used:
                try:
                    from api.services.retrieval.factory import get_unified_retrieval_service

                    catalog = get_unified_retrieval_service().catalog()
                    sources = catalog.get("sources") if isinstance(catalog, dict) else []
                    handoff = build_discovery_handoff(pass_intermediate_steps, sources or [])
                except Exception as exc:
                    logger.warning("Could not build input discovery handoff: %s", exc)
                    handoff = None
                if handoff is not None and expansion_count + 1 < MAX_STAGED_EXECUTION_PASSES:
                    discovery_handoff_used = True
                    discovery_handoff_text = handoff.render()
                    reload_correction = []
                    logger.info(
                        "[AgentTelemetry] staged-input-discovery "
                        "prepared_files=%s source_count=%s",
                        len(handoff.prepared_files),
                        len(handoff.source_catalog),
                    )
                    continue
            only_reloaded = (
                bool(load_decision.requested_families)
                and not load_decision.had_non_loader_activity
            )
            if only_reloaded and expansion_count + 1 < MAX_STAGED_EXECUTION_PASSES:
                reload_correction = list(load_decision.requested_families)
                logger.warning(
                    "[AgentTelemetry] staged-tool-redundant-reload "
                    f"reloaded_families={reload_correction} expansion_count={expansion_count}; "
                    "granting corrective pass"
                )
                continue
            break

        reload_correction = []
        loaded_families.extend(new_families)
        if expansion_count == MAX_STAGED_EXECUTION_PASSES - 1:
            logger.warning(
                "Staged tool loading reached expansion limit with loaded_families=%s",
                loaded_families,
            )

    # LAST-RESORT SCRIPTING FLOOR: if the run was blocked (a specialized tool or
    # method failed or was unavailable) and no AppleScript/shell was ever
    # attempted, grant exactly one forced scripting pass before giving up. This
    # is deterministic and free on the success path: scripting_floor_owed is
    # False whenever nothing failed. It runs at most once (no loop).
    floor_owed = scripting_floor_owed(intermediate_steps)
    floor_triggered = False
    if floor_owed:
        floor_can_run = True
        floor_max_execution_time = AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS
        if deadline is not None:
            if not deadline.can_start_execution(
                per_pass_cap_seconds=AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS,
            ):
                if state.context is not None:
                    state.context["workflow_deadline_evidence"] = deadline_evidence(
                        deadline,
                        reason="insufficient_remaining_time_for_scripting_floor",
                    )
                floor_can_run = False
            else:
                floor_max_execution_time = deadline.execution_seconds_available(
                    per_pass_cap_seconds=AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS,
                )
        floor_cancel_event = request.cancel_event
        if (
            floor_cancel_event is not None
            and hasattr(floor_cancel_event, "is_set")
            and floor_cancel_event.is_set()
        ):
            floor_can_run = False
        floor_tools: list[Any] = []
        if floor_can_run:
            floor_tools = select_tools_for_families(
                all_tools,
                list(loaded_families) + sorted(BASELINE_FALLBACK_FAMILY_NAMES),
                include_core_tools=True,
                loader_tool=family_loader_tool,
            )
        floor_has_scripting_tool = any(
            str(getattr(tool_item, "name", "") or "").startswith(
                ("applescript_service_", "shell_service_")
            )
            for tool_item in floor_tools
        )
        if floor_can_run and floor_has_scripting_tool:
            floor_triggered = True
            active_tools_for_recovery = floor_tools
            floor_input = (
                f"{user_input}\n\n"
                "MANDATORY LAST-RESORT SCRIPTING FLOOR:\n"
                "- The specialized tools tried so far did not accomplish the request "
                "(a tool or method failed or could not do it) and no script has been attempted yet.\n"
                "- AppleScript (applescript_service_*) and shell/Python (shell_service_*) are bound and available right now.\n"
                "- You MUST now attempt to accomplish the user's actual intent directly with a script before this can be "
                "reported as not possible. Inspect the needed app/file/system/email state and perform the work via scripting.\n"
                "- Only after a real scripting attempt has genuinely failed may you conclude it cannot be done; then report "
                "exactly what you tried and what happened."
            )
            floor_executor = create_agent_executor(
                request.langchain_llm,
                floor_tools,
                user_profile_context=request.user_profile_context,
                communication_context_section=request.communication_context_section,
                custom_instructions_section=request.custom_instructions_section,
                preloaded_skill_section=request.selected_skill_section,
                staged_tool_metadata={
                    "stage": "scripting_floor",
                    "loaded_families": loaded_families,
                    "family_count": len(loaded_families),
                    "initial_tool_count": len(core_tools),
                    "expanded_tool_count": len(floor_tools),
                    "expansion_count": MAX_STAGED_EXECUTION_PASSES,
                },
                max_execution_time_seconds=floor_max_execution_time,
            )
            runtime_context_token = set_current_agent_context(state.context)
            try:
                result, final_input = await execute_with_token_retry(
                    agent_executor=floor_executor,
                    user_input=floor_input,
                    callbacks=request.live_callbacks,
                    cancel_event=request.cancel_event,
                )
            finally:
                reset_current_agent_context(runtime_context_token)
            intermediate_steps.extend(result.get("intermediate_steps", []))
    logger.info(
        "[AgentTelemetry] scripting-floor "
        f"owed={floor_owed} triggered={floor_triggered} loaded_families={loaded_families or []}"
    )

    if state.context is not None:
        state.context["loaded_tool_families"] = list(loaded_families)
    await emit_activity_phase(
        state,
        phase="staged_tool_loading",
        lifecycle_state="completed",
        title="Execution tools ready",
        source="staged_execution_loop",
    )

    cancel_event = request.cancel_event
    if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
        raise asyncio.CancelledError()

    agent_output = normalize_agent_executor_output(result.get("output"))

    return StagedExecutionResult(
        result=result,
        loaded_families=loaded_families,
        intermediate_steps=intermediate_steps,
        agent_output=agent_output,
        final_input=final_input,
        active_tools_for_recovery=active_tools_for_recovery,
        core_tools=core_tools,
    )
