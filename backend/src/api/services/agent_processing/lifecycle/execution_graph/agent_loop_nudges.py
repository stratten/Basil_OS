"""In-loop completion nudges and progress callbacks for Basil's inner agent loop."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional, Sequence

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from api.core.logging.api_logger import api_logger

from .agent_loop_messages import ai_message_text, messages_to_intermediate_steps, tool_call_action
from .agent_loop_model_recovery import AgentRunFlags
from .agent_loop_tool_surface import ToolSurfaceTracker
from .conversation_turns import current_turn_messages
from .discovery_handoff import build_discovery_handoff
from .service_tooling.staged_tool_loading_repair import scripting_floor_owed

logger = api_logger.getChild("agent_loop_nudges")

SCRIPTING_FLOOR_PROMPT = (
    "MANDATORY LAST-RESORT SCRIPTING FLOOR:\n"
    "- The specialized tools tried so far did not accomplish the request "
    "(a tool or method failed or could not do it) and no script has been attempted yet.\n"
    "- AppleScript (applescript_service_*) and shell/Python (shell_service_*) are bound and available right now.\n"
    "- You MUST now attempt to accomplish the user's actual intent directly with a script before this can be "
    "reported as not possible. Inspect the needed app/file/system/email state and perform the work via scripting.\n"
    "- Only after a real scripting attempt has genuinely failed may you conclude it cannot be done; then report "
    "exactly what you tried and what happened."
)
INVALID_TOOL_CALL_REPAIR_PROMPT = (
    "Your last response tried to call a tool, but the call could not be parsed ({details}). "
    "Call the tool again with valid JSON arguments that match its schema, or answer without calling a tool."
)
MAX_INVALID_TOOL_CALL_REPAIRS = 2
_SCRIPTING_TOOL_PREFIXES = ("applescript_service_", "shell_service_")


def default_source_catalog() -> list[dict[str, Any]]:
    from api.services.retrieval.factory import get_unified_retrieval_service

    catalog = get_unified_retrieval_service().catalog()
    sources = catalog.get("sources") if isinstance(catalog, dict) else None
    return list(sources or [])


async def _call_hook(hook: Any, *args: Any, **kwargs: Any) -> None:
    try:
        result = hook(*args, **kwargs)
        if inspect.isawaitable(result):
            await result
    except Exception as hook_error:
        logger.debug("Progress callback failed: %s", hook_error)


def _messages(state: Any) -> list[Any]:
    messages = state.get("messages") if hasattr(state, "get") else None
    return list(messages or [])


class CompletionNudgeMiddleware(AgentMiddleware):
    """Inject the discovery handoff, the scripting floor, and malformed-call repairs inside one run."""

    def __init__(
        self,
        tracker: ToolSurfaceTracker,
        flags: AgentRunFlags,
        *,
        source_catalog_loader: Callable[[], list[dict[str, Any]]] = default_source_catalog,
    ) -> None:
        super().__init__()
        self.tracker = tracker
        self.flags = flags
        self.source_catalog_loader = source_catalog_loader
        self.discovery_handoff_used = False
        self.scripting_floor_used = False
        self.invalid_tool_call_repairs = 0

    async def abefore_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        if self.discovery_handoff_used:
            return None
        steps = messages_to_intermediate_steps(current_turn_messages(_messages(state)))
        if build_discovery_handoff(steps, []) is None:
            return None
        self.discovery_handoff_used = True
        try:
            handoff = build_discovery_handoff(steps, self.source_catalog_loader())
        except Exception as catalog_error:
            logger.warning("Could not build input discovery handoff: %s", catalog_error)
            return None
        if handoff is None:
            return None
        logger.info(
            "[AgentTelemetry] staged-input-discovery prepared_files=%s source_count=%s",
            len(handoff.prepared_files),
            len(handoff.source_catalog),
        )
        return {"messages": [HumanMessage(content=handoff.render().strip())]}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        if self.flags.terminal():
            return None
        messages = _messages(state)
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or last.tool_calls:
            return None
        invalid_calls = list(getattr(last, "invalid_tool_calls", None) or [])
        if invalid_calls and self.invalid_tool_call_repairs < MAX_INVALID_TOOL_CALL_REPAIRS and last.id:
            self.invalid_tool_call_repairs += 1
            details = "; ".join(
                f"{call.get('name') or 'unknown tool'}: {call.get('error') or 'invalid arguments'}"
                for call in invalid_calls
            )
            logger.warning("[AgentTelemetry] invalid-tool-call-repair attempt=%s details=%s", self.invalid_tool_call_repairs, details[:300])
            return {
                "messages": [
                    RemoveMessage(id=last.id),
                    HumanMessage(content=INVALID_TOOL_CALL_REPAIR_PROMPT.format(details=details)),
                ],
                "jump_to": "model",
            }
        if self.scripting_floor_used or not self._scripting_tools_available():
            return None
        if not scripting_floor_owed(messages_to_intermediate_steps(current_turn_messages(messages))):
            return None
        self.scripting_floor_used = True
        logger.info(
            "[AgentTelemetry] scripting-floor owed=True triggered=True loaded_families=%s",
            self.tracker.loaded_families,
        )
        return {"messages": [HumanMessage(content=SCRIPTING_FLOOR_PROMPT)], "jump_to": "model"}

    def _scripting_tools_available(self) -> bool:
        return any(name.startswith(_SCRIPTING_TOOL_PREFIXES) for name in self.tracker.surface_names)


class ProgressBridgeMiddleware(AgentMiddleware):
    """Fire the per-iteration and per-action callbacks AgentExecutor used to fire."""

    def __init__(self, callbacks: Optional[Sequence[Any]]) -> None:
        super().__init__()
        self.callbacks = [callback for callback in (callbacks or []) if callback is not None]
        self.model_calls = 0

    async def abefore_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        self.model_calls += 1
        if self.model_calls == 1:
            return None
        for callback in self.callbacks:
            hook = getattr(callback, "on_chain_start", None)
            if callable(hook):
                await _call_hook(hook, {"name": "agent_iteration"}, None, name="agent_iteration")
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        messages = _messages(state)
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return None
        text = ai_message_text(last)
        for call in last.tool_calls:
            action = tool_call_action(call, text)
            for callback in self.callbacks:
                hook = getattr(callback, "on_agent_action", None)
                if callable(hook):
                    await _call_hook(hook, action)
        return None
