"""In-loop checklist enforcement: a one-time cue after a set of records is found, and a gate that sends back a final answer while required items are open or no item was ever made."""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

from ..runtime.agent_checklist_gate import ChecklistCompletionGate
from ..runtime.agent_checklist_prompt import build_mid_run_cue
from .agent_loop_model_recovery import AgentRunFlags

logger = logging.getLogger(__name__)


def _messages(state: Any) -> list[Any]:
    messages = state.get("messages") if hasattr(state, "get") else None
    return list(messages or [])


class ChecklistGateMiddleware(AgentMiddleware):
    """Hold back a final answer while required checklist items the model can still work are open."""

    def __init__(self, flags: AgentRunFlags, gate: Optional[ChecklistCompletionGate] = None) -> None:
        super().__init__()
        self.flags = flags
        self.gate = gate or ChecklistCompletionGate()
        self.cue_sent = False

    async def abefore_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        """Once per run, right after a tool result, remind the model to track a set of records the run has found."""
        if self.cue_sent or self.flags.terminal():
            return None
        messages = _messages(state)
        if not messages or not isinstance(messages[-1], ToolMessage):
            return None
        context = get_current_agent_context()
        try:
            from api.dependencies import get_sqlite_knowledge_service

            from ..runtime.agent_checklist_service import AgentChecklistService

            owed = await AgentChecklistService(get_sqlite_knowledge_service()).records_without_checklist(context)
        except Exception:
            return None
        if not owed:
            return None
        self.cue_sent = True
        logger.info("[AgentTelemetry] checklist-cue sent after a set of records was found")
        return {"messages": [HumanMessage(content=build_mid_run_cue())]}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        if self.flags.terminal():
            return None
        messages = _messages(state)
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or last.tool_calls or getattr(last, "invalid_tool_calls", None):
            return None
        message = await self.gate.review_final_answer(get_current_agent_context())
        if message is None:
            return None
        return {"messages": [HumanMessage(content=message)], "jump_to": "model"}
