"""LangChain callback support for streaming setup-agent events."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from langchain_core.callbacks import AsyncCallbackHandler

from api.routes.setup_assistant.models import SetupAgentEvent, SetupAgentEventKind

SetupAgentEventEmitter = Callable[[SetupAgentEvent], Awaitable[None]]


class SetupAgentProgressCallback(AsyncCallbackHandler):
    """Translate setup-agent LangChain progress into setup stream events."""

    def __init__(self, event_emitter: SetupAgentEventEmitter) -> None:
        super().__init__()
        self.event_emitter = event_emitter
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def on_chain_start(
        self,
        serialized: Any,
        inputs: Any = None,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: Any = None,
        metadata: Any = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        # LangChain fires ``on_chain_start`` for every nested chain inside an
        # agent graph run (each model node, each tool node, each middleware
        # hook). We only want to signal a new user-facing turn
        # for the top-level invocation, otherwise the frontend clears the
        # latest ``narrate_progress`` line on every internal step and the user
        # sees the generic fallback flashing back in between narrations.
        if parent_run_id is not None:
            return
        await self._emit_event(
            SetupAgentEvent(
                kind=SetupAgentEventKind.turn_started,
                payload={"run_id": str(run_id) if run_id else None},
            )
        )

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: Any = None,
        **kwargs: Any,
    ) -> None:
        await self._emit_event(
            SetupAgentEvent(
                kind=SetupAgentEventKind.error,
                payload={"message": str(error), "run_id": str(run_id) if run_id else None},
            )
        )

    async def _emit_event(self, event: SetupAgentEvent) -> None:
        try:
            await self.event_emitter(event)
        except Exception as exc:  # pragma: no cover - streaming should not crash the agent.
            self.logger.warning("Setup agent progress emission failed: %s", exc)

