"""Expose only the loaded tool families to the model while every tool stays registered."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage

from api.core.logging.api_logger import api_logger

from .agent_loop_messages import is_pause_request, messages_to_intermediate_steps
from .service_tooling.staged_tool_loading_repair import collect_new_tool_families_from_steps
from .service_tooling.tool_family_catalog import (
    BASELINE_FALLBACK_FAMILY_NAMES,
    create_load_tool_family_tool,
    select_core_tools,
    select_tools_for_families,
)

logger = api_logger.getChild("agent_loop_tool_surface")


def tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or "")


class ToolSurfaceTracker:
    """Track the loaded tool families and the tool names the model may call right now."""

    def __init__(
        self,
        all_tools: Sequence[Any],
        *,
        initial_families: Iterable[str] = (),
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self.all_tools = list(all_tools)
        self.loaded_families: list[str] = []
        for family in initial_families:
            if family and family not in self.loaded_families:
                self.loaded_families.append(family)
        self.context = context if isinstance(context, dict) else None
        self.loader_tool = create_load_tool_family_tool(
            self.all_tools,
            get_available_families=self.available_families,
        )
        self.core_tool_count = len(select_core_tools(self.all_tools, self.loader_tool))
        self._recorded_diagnostics: set[str] = set()
        self._surface_names: frozenset[str] = frozenset(tool_name(item) for item in self.surface_tools())
        self._publish_loaded_families()

    def available_families(self) -> set[str]:
        return set(self.loaded_families) | set(BASELINE_FALLBACK_FAMILY_NAMES) | {"core"}

    def registered_tools(self) -> list[Any]:
        return [*self.all_tools, self.loader_tool]

    def surface_tools(self) -> list[Any]:
        if not self.loaded_families:
            return select_core_tools(self.all_tools, self.loader_tool)
        return select_tools_for_families(
            self.all_tools,
            [*self.loaded_families, *sorted(BASELINE_FALLBACK_FAMILY_NAMES)],
            include_core_tools=True,
            loader_tool=self.loader_tool,
        )

    @property
    def surface_names(self) -> frozenset[str]:
        return self._surface_names

    def refresh(self, intermediate_steps: Sequence[Any]) -> bool:
        """Load any newly requested or repaired families; return True when the surface grew."""
        decision = collect_new_tool_families_from_steps(intermediate_steps, self.loaded_families)
        self._record_diagnostic(decision)
        if not decision.new_families:
            return False
        if decision.repair_families or decision.suggested_families:
            logger.info(
                "[AgentTelemetry] staged-tool-repair "
                f"repair_families={decision.repair_families} "
                f"suggested_families={decision.suggested_families} "
                f"loaded_families={self.loaded_families}"
            )
        self.loaded_families.extend(decision.new_families)
        self._surface_names = frozenset(tool_name(item) for item in self.surface_tools())
        self._publish_loaded_families()
        return True

    def _record_diagnostic(self, decision: Any) -> None:
        if not decision.diagnostic or self.context is None:
            return
        key = json.dumps(decision.details, sort_keys=True, default=str)
        if key in self._recorded_diagnostics:
            return
        self._recorded_diagnostics.add(key)
        diagnostics = self.context.setdefault("staged_tool_loading_diagnostics", [])
        if isinstance(diagnostics, list):
            diagnostics.append(decision.details)

    def _publish_loaded_families(self) -> None:
        if self.context is not None:
            self.context["loaded_tool_families"] = list(self.loaded_families)


class ToolSurfaceMiddleware(AgentMiddleware):
    """Bind only the current tool surface for each model call and reject calls outside it."""

    def __init__(
        self,
        tracker: ToolSurfaceTracker,
        *,
        on_surface_change: Optional[Callable[[list[Any]], None]] = None,
    ) -> None:
        super().__init__()
        self.tracker = tracker
        self.on_surface_change = on_surface_change
        self._surface_reported = False

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        grew = self.tracker.refresh(messages_to_intermediate_steps(request.messages))
        if (grew or not self._surface_reported) and self.on_surface_change is not None:
            self._surface_reported = True
            try:
                self.on_surface_change(self.tracker.surface_tools())
            except Exception as telemetry_error:
                logger.debug("Tool surface telemetry failed: %s", telemetry_error)
        surface_names = self.tracker.surface_names
        surface = [item for item in request.tools if tool_name(item) in surface_names]
        return await handler(request.override(tools=surface))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        call_name = str(request.tool_call.get("name") or "")
        call_id = str(request.tool_call.get("id") or "")
        if request.tool is not None and call_name not in self.tracker.surface_names:
            available = ", ".join(sorted(self.tracker.surface_names))
            return ToolMessage(
                content=f"{call_name} is not a valid tool, try one of [{available}].",
                tool_call_id=call_id,
                name=call_name,
                status="error",
            )
        try:
            return await handler(request)
        except Exception as error:
            if is_pause_request(error) and getattr(error, "basil_tool_call_id", None) is None:
                error.basil_tool_call_id = call_id
            raise
