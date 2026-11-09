"""In-turn nudge that keeps weaker local models on the setup agent's presentation tools.

The setup conversation only shows choosable cards (``set_chips``) and the session agenda
(``propose_session_agenda``) when the model calls those tools. Local models often write their whole
reply as plain text instead, so the user gets a wall of prose with no options. This middleware asks the
model once, per turn, to resend that reply through the tools. If the model still answers in plain text,
the runtime shows that text as before, so the nudge can only improve a turn and never block one.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from api.routes.setup_assistant.models import SetupAssistantPhase
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_messages import ai_message_text

logger = logging.getLogger(__name__)

SETUP_NUDGE_MARKER = "basil_setup_presentation_nudge"

_PRESENTATION_TOOL_NAMES = frozenset({"say", "set_chips"})

PLAIN_REPLY_NUDGE = (
    "You wrote your reply as plain text. Basil shows plain text as a bare message with no options, and the user "
    "can only pick from choosable cards that you create with set_chips.\n"
    "- Resend the same reply now: call say with the message, then call set_chips with 2 to 4 short, action-shaped "
    "options whenever your message asks a question or offers a choice. Set multi_select to true when the answers "
    "are not mutually exclusive.\n"
    "- Do not write the reply as plain text again."
)

AGENDA_NUDGE_ADDENDUM = (
    "\n- The seeded agenda catalog is still unadopted, so call propose_session_agenda once with the agenda you "
    "want to work through before you call say. Keep every title under 80 characters and every intent under 480."
)


class SetupPresentationNudgeMiddleware(AgentMiddleware):
    """Ask once per turn for a reply that went out as plain text to be resent through say and set_chips."""

    def __init__(self, *, phase: SetupAssistantPhase, agenda_owed: bool, finalize_mode: bool = False) -> None:
        super().__init__()
        self.phase = phase
        self.agenda_owed = agenda_owed
        self.finalize_mode = finalize_mode
        self.nudge_used = False

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        if self.nudge_used or self.finalize_mode:
            return None
        if self.phase == SetupAssistantPhase.deterministic_discovery:
            return None
        messages = list(state.get("messages") or []) if hasattr(state, "get") else []
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or last.tool_calls or not ai_message_text(last):
            return None
        if _presentation_tool_used_this_turn(messages):
            return None
        self.nudge_used = True
        logger.info("[SetupAgent] plain-text reply nudge triggered (phase=%s, agenda_owed=%s)", self.phase.value, self.agenda_owed)
        nudge = HumanMessage(
            content=PLAIN_REPLY_NUDGE + (AGENDA_NUDGE_ADDENDUM if self.agenda_owed else ""),
            additional_kwargs={SETUP_NUDGE_MARKER: True},
        )
        removal = [RemoveMessage(id=last.id)] if last.id else []
        return {"messages": [*removal, nudge], "jump_to": "model"}


def _presentation_tool_used_this_turn(messages: list[Any]) -> bool:
    """True when say or set_chips was already called since the turn's own input message."""

    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not (message.additional_kwargs or {}).get(SETUP_NUDGE_MARKER):
            return False
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("name") in _PRESENTATION_TOOL_NAMES:
                    return True
    return False
