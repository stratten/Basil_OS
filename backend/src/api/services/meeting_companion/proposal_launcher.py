"""Starts approved Companion proposals through the To-Do domain.

An approval becomes an ordinary To-Do, and agent work becomes an ordinary To-Do worker, so every existing execution approval gate applies. Imports of the application wiring are local to the methods to avoid an import cycle with ``api.dependencies``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .proposals import ProposalLaunchError


class TodoProposalLauncher:
    def __init__(
        self,
        *,
        todo_service_provider: Optional[Callable[[], Any]] = None,
        bridge_provider: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._todo_service_provider = todo_service_provider
        self._bridge_provider = bridge_provider

    def _todo_service(self) -> Any:
        if self._todo_service_provider is not None:
            return self._todo_service_provider()
        from api.dependencies import get_todo_service

        return get_todo_service()

    def _bridge(self) -> Any:
        if self._bridge_provider is not None:
            return self._bridge_provider()
        from api.services.todos.agent_task_bridge import get_todo_agent_task_bridge

        return get_todo_agent_task_bridge()

    async def create_todo(
        self, *, session_key: str, proposal_id: str, title: str, description: str, excerpt: str, responsibility: str, system_created: bool,
    ) -> str:
        from api.services.todos.service import TodoTransitionError

        try:
            detail = await self._todo_service().create_todo_from_companion_proposal(
                session_key=session_key,
                proposal_id=proposal_id,
                title=title,
                description=description,
                excerpt=excerpt,
                responsibility=responsibility,
                system_created=system_created,
            )
        except TodoTransitionError as error:
            raise ProposalLaunchError(str(error)) from error
        return str(detail.id)

    async def launch_worker(self, todo_id: str) -> str:
        from api.services.todos.service import TodoConflictError, TodoNotFoundError, TodoTransitionError

        bridge = self._bridge()
        if bridge is None:
            raise ProposalLaunchError("The To-Do worker is not ready yet. Try again in a moment.")
        service = self._todo_service()
        try:
            detail = await service.get_item_detail(todo_id)
            launched = await service.launch_todo_worker(
                todo_id=todo_id,
                expected_revision=detail.revision,
                launcher=bridge.launch_todo_item_agent_task,
            )
        except TodoConflictError as error:
            raise ProposalLaunchError("The To-Do changed while it was starting. Try again.") from error
        except TodoNotFoundError as error:
            raise ProposalLaunchError("The To-Do no longer exists.") from error
        except TodoTransitionError as error:
            raise ProposalLaunchError(str(error)) from error
        return str(launched.agent_task_id)
