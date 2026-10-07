"""In-process relay for prompts that a running shell command shows on its terminal."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from api.services.conversation.conversation_agent_turn_lifecycle import (
    clear_conversation_agent_attention,
    publish_conversation_agent_attention,
)

from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
    record_user_interaction_asked,
    record_user_interaction_resolved,
)

from .shell_process_runner import CommandInputReply

logger = logging.getLogger(__name__)

COMMAND_INPUT_TIMEOUT_SECONDS = 300.0
MAX_COMMAND_INPUT_CHARS = 4_096


class CommandInputNotFoundError(LookupError):
    """The request is unknown, already answered, or expired."""


class CommandInputConflictError(RuntimeError):
    """The request belongs to a different agent task."""


@dataclass
class _PendingCommandInput:
    request_id: str
    agent_task_id: str
    prompt: str
    secret: bool
    command_echo: str
    created_at: float
    expires_at: float
    future: "asyncio.Future[CommandInputReply]" = field(repr=False)

    def public_view(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent_task_id": self.agent_task_id,
            "prompt": self.prompt,
            "secret": self.secret,
            "command": self.command_echo,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


def validate_command_input_text(value: Optional[str]) -> str:
    """Return a single-line answer, rejecting control characters and oversize input."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Input must be text")
    text = value.rstrip("\r\n")
    if len(text) > MAX_COMMAND_INPUT_CHARS:
        raise ValueError(f"Input must be at most {MAX_COMMAND_INPUT_CHARS} characters")
    if any((ord(character) < 32 and character != "\t") or ord(character) == 127 for character in text):
        raise ValueError("Input must be a single line without control characters")
    return text


class CommandInputBroker:
    """Pending prompt registry shared by ShellService and the command-input routes."""

    _pending: Dict[str, _PendingCommandInput] = {}

    @classmethod
    async def request_input(
        cls,
        *,
        agent_task_id: Optional[str],
        prompt: str,
        secret: bool,
        command_echo: str,
        websocket_manager: Any,
        timeout_seconds: float = COMMAND_INPUT_TIMEOUT_SECONDS,
    ) -> CommandInputReply:
        if websocket_manager is None or not isinstance(agent_task_id, str) or not agent_task_id.strip():
            return CommandInputReply(status="unavailable")
        now = time.time()
        pending = _PendingCommandInput(
            request_id=f"command-input-{uuid.uuid4()}",
            agent_task_id=agent_task_id.strip(),
            prompt=prompt,
            secret=bool(secret),
            command_echo=command_echo,
            created_at=now,
            expires_at=now + float(timeout_seconds),
            future=asyncio.get_running_loop().create_future(),
        )
        cls._pending[pending.request_id] = pending
        try:
            event: Dict[str, Any] = {
                "event_type": "execution_approval_request",
                "approval_id": pending.request_id,
                "agent_task_id": pending.agent_task_id,
                "command": command_echo,
                "reason": f"The command is asking for input: {prompt}",
                "risk_level": "medium" if pending.secret else "low",
                "execution_type": "command_input",
                "command_input": pending.public_view(),
            }
            try:
                await websocket_manager.broadcast(event)
            except Exception as exc:
                logger.error("Failed to broadcast command input request %s: %s", pending.request_id, exc)
                return CommandInputReply(status="unavailable")
            await record_user_interaction_asked(
                pending.agent_task_id,
                interaction_id=pending.request_id,
                kind="command_input",
                prompt=prompt,
                input_type="secret" if pending.secret else "text",
                broadcast=websocket_manager.broadcast,
            )
            try:
                await publish_conversation_agent_attention(pending.agent_task_id, pending.request_id)
            except Exception:
                logger.exception("Failed to project command input attention for %s", pending.request_id)
            try:
                reply = await asyncio.wait_for(pending.future, timeout=float(timeout_seconds))
            except asyncio.TimeoutError:
                logger.info("Command input request %s timed out", pending.request_id)
                reply = CommandInputReply(status="timeout")
            await record_user_interaction_resolved(
                pending.agent_task_id,
                interaction_id=pending.request_id,
                status={"answered": "answered", "canceled": "canceled"}.get(reply.status, "timed_out"),
                response=reply.text if reply.status == "answered" else None,
                response_hidden=pending.secret and reply.status == "answered",
                broadcast=websocket_manager.broadcast,
            )
            return reply
        finally:
            cls._pending.pop(pending.request_id, None)
            if not pending.future.done():
                pending.future.cancel()
            try:
                await clear_conversation_agent_attention(pending.agent_task_id, pending.request_id)
            except Exception:
                logger.exception("Failed to clear command input attention for %s", pending.request_id)

    @classmethod
    def respond(
        cls,
        request_id: str,
        *,
        action: str,
        value: Optional[str] = None,
        agent_task_id: Optional[str] = None,
    ) -> None:
        pending = cls._pending.get(request_id)
        if pending is None or pending.future.done():
            raise CommandInputNotFoundError(f"command input request {request_id!r} is not pending")
        if agent_task_id and agent_task_id != pending.agent_task_id:
            raise CommandInputConflictError(
                f"command input request {request_id!r} does not belong to agent task {agent_task_id!r}"
            )
        if action == "cancel":
            pending.future.set_result(CommandInputReply(status="canceled"))
            return
        if action != "answer":
            raise ValueError("action must be 'answer' or 'cancel'")
        text = validate_command_input_text(value)
        pending.future.set_result(CommandInputReply(status="answered", text=text))

    @classmethod
    def pending_for_task(cls, agent_task_id: str) -> List[Dict[str, Any]]:
        return [
            pending.public_view()
            for pending in list(cls._pending.values())
            if pending.agent_task_id == agent_task_id and not pending.future.done()
        ]


__all__ = [
    "COMMAND_INPUT_TIMEOUT_SECONDS",
    "MAX_COMMAND_INPUT_CHARS",
    "CommandInputBroker",
    "CommandInputConflictError",
    "CommandInputNotFoundError",
    "validate_command_input_text",
]
