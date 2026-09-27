"""Activate ACP v1/v2 `session/request_permission` through the existing approval surface (Package 4B.3).

Bound to exactly one provider run's agent-issued session ID. Reuses the
envelope/option/subject validation from `provider_permission_request_coordinator`
(Package 4B.1) and the durable `provider_permission` interaction contract from
`provider_permission_action_summary`/`ProviderInteractionRepository` (Package
4B.2). When the bound run has no live WebSocket channel
(`routing_service.websocket_manager` is falsy), this coordinator takes the
identical fail-closed path as Package 4B.1: no persistence, no publication,
no user prompt, ever. When a live channel exists, it persists a pending
`provider_permission` interaction before publishing an `execution_approval_request`
event through the existing `ApprovalOverlay`, awaits the user's REST decision
via `ProviderInteractionDeliveryRegistry`, and answers the ACP request with
that decision. It never grants an `allow_once`/`allow_always` option that the
provider did not offer and never persists an interaction when no `reject`-kind
option exists to fail closed onto if the user cannot be reached.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Sequence

from api.services.agent_providers.acp.protocol import ACP_PROTOCOL_VERSION
from api.services.agent_providers.acp.session_client import AcpRequestError
from .provider_permission_request_coordinator import (
    normalize_provider_permission_request,
)

_ALLOW_KIND_PRIORITY = ("allow_once", "allow_always")
_REJECT_KIND_PRIORITY = ("reject_once", "reject_always")


def _select_kind_option(
    options: Sequence[Mapping[str, str]], priority: Sequence[str]
) -> dict[str, str] | None:
    for preferred_kind in priority:
        for option in options:
            if option["kind"] == preferred_kind:
                return dict(option)
    return None


class ProviderPermissionActivationCoordinator:
    """Answer ACP v1/v2 `session/request_permission` requests via the approval surface, or fail closed."""

    def __init__(
        self,
        *,
        routing_service: Any,
        provider_interaction_repository: Any,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        provider_run_id: str,
        logger: logging.Logger | None = None,
        protocol_version: int = ACP_PROTOCOL_VERSION,
        delegated_interaction_callback: Any | None = None,
    ) -> None:
        self._routing_service = routing_service
        self._provider_interaction_repository = provider_interaction_repository
        self._agent_task_id = agent_task_id
        self._root_task_id = root_task_id
        self._previous_task_id = previous_task_id
        self._provider_run_id = provider_run_id
        self._logger = logger or logging.getLogger(__name__)
        self._session_id: str | None = None
        self._active_interaction_id: str | None = None
        self._protocol_version = protocol_version
        self._delegated_interaction_callback = delegated_interaction_callback

    def bind_session(self, session_id: str) -> None:
        """Bind this coordinator to the agent-issued session ID exactly once."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if self._session_id is not None and self._session_id != session_id:
            raise ValueError(
                "ProviderPermissionActivationCoordinator is already bound to a different session"
            )
        self._session_id = session_id

    def _can_activate(self) -> bool:
        return bool(getattr(self._routing_service, "websocket_manager", None))

    async def handle_request_permission(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Answer one `session/request_permission` request. Registered via `register_request_handler`."""
        from api.services.agent_providers.interaction_delivery import (
            ProviderInteractionDeliveryRegistry,
        )

        if not isinstance(params, Mapping):
            raise AcpRequestError(-32602, "session/request_permission params must be an object")

        session_id = params.get("sessionId")
        if self._session_id is None or session_id != self._session_id:
            raise AcpRequestError(
                -32602, "session/request_permission sessionId does not match the bound session"
            )

        title, description, options, subject = normalize_provider_permission_request(
            params,
            protocol_version=self._protocol_version,
        )

        reject_option = _select_kind_option(options, _REJECT_KIND_PRIORITY)
        if reject_option is None:
            self._logger.info(
                "Declining session/request_permission for provider run %s: no reject-kind option "
                "was offered",
                self._provider_run_id,
            )
            raise AcpRequestError(
                -32601,
                "session/request_permission cannot be safely declined without a reject-kind option",
            )

        if not self._can_activate():
            self._logger.info(
                "Declining session/request_permission for provider run %s via a reject-kind option: "
                "no live WebSocket channel is available to reach the user",
                self._provider_run_id,
            )
            return {"outcome": {"outcome": "selected", "optionId": reject_option["optionId"]}}

        allow_option = _select_kind_option(options, _ALLOW_KIND_PRIORITY)

        try:
            interaction = await self._provider_interaction_repository.create_permission_interaction(
                provider_run_id=self._provider_run_id,
                agent_task_id=self._agent_task_id,
                root_task_id=self._root_task_id or self._agent_task_id,
                action_summary={
                    "title": title,
                    "description": description,
                    "options": options,
                    "subject": subject,
                },
            )
        except Exception as exc:  # noqa: BLE001 - persistence failure must still fail closed.
            self._logger.warning(
                "Failed to persist provider_permission interaction for run %s; declining via a "
                "reject-kind option: %s",
                self._provider_run_id,
                exc,
            )
            return {"outcome": {"outcome": "selected", "optionId": reject_option["optionId"]}}

        interaction_id = str(interaction["id"])
        self._active_interaction_id = interaction_id
        if self._delegated_interaction_callback is not None:
            await self._delegated_interaction_callback(
                interaction_id=interaction_id,
                permission=True,
            )
        future = ProviderInteractionDeliveryRegistry.register(interaction_id)
        requested_schema = interaction.get("requested_schema")
        persisted_subject = (
            requested_schema.get("subject")
            if isinstance(requested_schema, Mapping)
            else None
        )

        try:
            published = await self._routing_service.publish_provider_permission_request(
                agent_task_id=self._agent_task_id,
                root_task_id=self._root_task_id,
                previous_task_id=self._previous_task_id,
                interaction_id=interaction_id,
                provider_run_id=self._provider_run_id,
                title=title,
                description=description,
                subject=persisted_subject,
                allow_option_id=allow_option["optionId"] if allow_option else None,
                reject_option_id=reject_option["optionId"],
            )
            if not published:
                ProviderInteractionDeliveryRegistry.resolve(interaction_id, "cancel", None)
            resolution = await future
        except asyncio.CancelledError:
            ProviderInteractionDeliveryRegistry.resolve(interaction_id, "cancel", None)
            try:
                refreshed = await self._provider_interaction_repository.get_interaction(interaction_id)
                if refreshed is not None and refreshed["status"] == "pending":
                    await self._provider_interaction_repository.cancel_permission_interaction(
                        interaction_id=interaction_id,
                        provider_run_id=self._provider_run_id,
                        agent_task_id=self._agent_task_id,
                        expected_revision=int(refreshed["revision"]),
                    )
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask cancellation.
                self._logger.warning(
                    "Failed to persist cancellation for provider permission interaction %s: %s",
                    interaction_id,
                    exc,
                )
            if self._delegated_interaction_callback is not None:
                await self._delegated_interaction_callback(
                    interaction_id=interaction_id,
                    permission=True,
                    resolved=True,
                )
            await self._routing_service.publish_provider_permission_resolved(
                agent_task_id=self._agent_task_id,
                root_task_id=self._root_task_id,
                previous_task_id=self._previous_task_id,
                interaction_id=interaction_id,
            )
            raise
        finally:
            ProviderInteractionDeliveryRegistry.discard(interaction_id)
            self._active_interaction_id = None

        selected_option_id = None
        if resolution.get("outcome") == "selected":
            values = resolution.get("values") or {}
            selected_option_id = values.get("optionId")

        if selected_option_id is None:
            # Coordinator-owned cancellation (run shutdown) or a failed UI
            # publication, neither of which traverses the REST route. Persist
            # the terminal state here so the row never lingers `pending`.
            try:
                refreshed = await self._provider_interaction_repository.get_interaction(interaction_id)
                if refreshed is not None and refreshed["status"] == "pending":
                    await self._provider_interaction_repository.cancel_permission_interaction(
                        interaction_id=interaction_id,
                        provider_run_id=self._provider_run_id,
                        agent_task_id=self._agent_task_id,
                        expected_revision=int(refreshed["revision"]),
                    )
            except Exception as exc:  # noqa: BLE001 - do not leave the provider waiting on cleanup.
                self._logger.warning(
                    "Failed to persist fallback cancellation for provider permission interaction "
                    "%s: %s",
                    interaction_id,
                    exc,
                )
            selected_option_id = reject_option["optionId"]

        if self._delegated_interaction_callback is not None:
            await self._delegated_interaction_callback(
                interaction_id=interaction_id,
                permission=True,
                resolved=True,
            )
        await self._routing_service.publish_provider_permission_resolved(
            agent_task_id=self._agent_task_id,
            root_task_id=self._root_task_id,
            previous_task_id=self._previous_task_id,
            interaction_id=interaction_id,
        )

        return {"outcome": {"outcome": "selected", "optionId": selected_option_id}}

    async def cancel_pending_interaction(self) -> None:
        """Resolve any interaction this coordinator is currently awaiting as `cancel`.

        Called from the provider run's cancellation/shutdown paths so a
        cancelled run never leaves a dangling future or an unresolved
        `pending` durable row.
        """
        from api.services.agent_providers.interaction_delivery import (
            ProviderInteractionDeliveryRegistry,
        )

        interaction_id = self._active_interaction_id
        if interaction_id is None:
            return
        try:
            await self._provider_interaction_repository.supersede_pending_for_run(self._provider_run_id)
        except Exception as exc:  # noqa: BLE001 - cleanup must never raise during shutdown.
            self._logger.warning(
                "Failed to supersede pending provider interactions for run %s: %s",
                self._provider_run_id,
                exc,
            )
        finally:
            ProviderInteractionDeliveryRegistry.resolve(interaction_id, "cancel", None)


__all__ = ["ProviderPermissionActivationCoordinator"]
