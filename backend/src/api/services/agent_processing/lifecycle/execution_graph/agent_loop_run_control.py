"""Deliver the user's queued notes and pause requests at the agent loop's next model call."""

from __future__ import annotations

from typing import Any, Optional, Sequence
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import BaseMessage, HumanMessage

from api.core.logging.api_logger import api_logger

from ...shared.agent_run_control import AgentRunControl, QueuedRunMessage
from ...tools.internal_basil_tools.checkpoint_tool import CheckpointRequest
from ..runtime.user_interaction_timeline import record_user_interaction_entry

logger = api_logger.getChild("agent_loop_run_control")

USER_PAUSE_PROMPT = "Paused at your request"


def user_note_message(text: str) -> HumanMessage:
    return HumanMessage(
        content=(
            "The user sent you a note while you were working:\n\n"
            f"{text}\n\n"
            "Take it into account from here on."
        )
    )


class UserPauseRequest(CheckpointRequest):
    """A pause the user asked for, saved and resumed like a question checkpoint."""

    is_user_pause = True

    def __init__(self, pending_messages: Sequence[BaseMessage] = ()) -> None:
        super().__init__(
            {
                "checkpoint_id": f"pause_{uuid4().hex}",
                "prompt": USER_PAUSE_PROMPT,
                "input_type": "text",
                "metadata": {"source": "user_pause"},
            }
        )
        self.basil_pending_messages = list(pending_messages)


class RunControlMiddleware(AgentMiddleware):
    """Before each model call, add the user's queued notes and honor a pending pause."""

    def __init__(self, control: AgentRunControl, agent_task_id: str, broadcast: Any = None) -> None:
        super().__init__()
        self.control = control
        self.agent_task_id = agent_task_id
        self.broadcast = broadcast

    async def abefore_model(self, state: Any, runtime: Any) -> Optional[dict[str, Any]]:
        notes = self.control.drain()
        messages = [user_note_message(note.text) for note in notes]
        for note in notes:
            await record_user_interaction_entry(
                self.agent_task_id,
                interaction_id=note.message_id,
                kind="guidance",
                prompt=note.text,
                status="resolved",
                asked_at=note.queued_at,
                broadcast=self.broadcast,
            )
        if notes:
            logger.info("📝 Delivered %s user note(s) to %s", len(notes), self.agent_task_id)
        if self.control.pause_requested():
            self.control.clear_pause()
            logger.info("⏸️ Pausing %s at the user's request", self.agent_task_id)
            raise UserPauseRequest(pending_messages=messages)
        return {"messages": messages} if messages else None


async def record_undelivered_notes(
    agent_task_id: str,
    notes: Sequence[QueuedRunMessage],
    broadcast: Any = None,
) -> None:
    for note in notes:
        await record_user_interaction_entry(
            agent_task_id,
            interaction_id=note.message_id,
            kind="guidance",
            prompt=note.text,
            status="canceled",
            asked_at=note.queued_at,
            broadcast=broadcast,
        )
