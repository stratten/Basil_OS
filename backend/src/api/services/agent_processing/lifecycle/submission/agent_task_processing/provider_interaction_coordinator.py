"""Coordinate ACP v2 `elicitation/create` (form mode) provider user-input interactions.

Bound to exactly one provider run. Validates and normalizes a flat,
string/enum-only `requestedSchema`, persists a durable interaction row
before any delivery, awaits the user's answer through
`ProviderInteractionDeliveryRegistry`, and returns the ACP-correct
`elicitation/create` response. Never handles `session/request_permission`
(Package 4B) or `url`-mode elicitation (deferred; see the module docstring
of `provider_interaction_schema.py` for the forward-compatibility contract).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Sequence

from api.services.agent_providers.acp.session_client import AcpRequestError
from api.services.agent_processing.shared.workflow_budget_pause import pause_workflow_budget

MAX_MESSAGE_BYTES = 2_048
MAX_FIELD_LABEL_BYTES = 256
MAX_FIELD_VALUE_BYTES = 4_096
MAX_FIELDS = 20
MAX_ENUM_OPTIONS = 50

_SUPPORTED_OUTCOMES = ("accept", "decline", "cancel")


def _bounded(value: Any, *, maximum_bytes: int) -> str:
    text = str(value if value is not None else "")
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum_bytes:
        return text
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore")


class UnsupportedElicitationSchemaError(RuntimeError):
    """The requested form schema is not a flat string/enum schema Basil can render."""


def _normalize_form_fields(requested_schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize a restricted flat JSON Schema into ordered display fields.

    Supports only `{"type": "string"}` properties, optionally with a string
    `enum`. Anything else (number, integer, boolean, array, object, or a
    schema with zero or more than `MAX_FIELDS` properties) raises
    `UnsupportedElicitationSchemaError`, which the caller treats as a
    graceful `decline`.
    """
    if not isinstance(requested_schema, Mapping) or requested_schema.get("type") != "object":
        raise UnsupportedElicitationSchemaError("requestedSchema must be a flat object schema")
    properties = requested_schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        raise UnsupportedElicitationSchemaError("requestedSchema must declare at least one property")
    if len(properties) > MAX_FIELDS:
        raise UnsupportedElicitationSchemaError("requestedSchema declares too many properties")
    required = requested_schema.get("required")
    if required is None:
        required_names: set[str] = set()
    elif (
        not isinstance(required, Sequence)
        or isinstance(required, str)
        or not all(isinstance(name, str) for name in required)
        or len(set(required)) != len(required)
        or any(name not in properties for name in required)
    ):
        raise UnsupportedElicitationSchemaError(
            "requestedSchema required must be a unique string array of property names"
        )
    else:
        required_names = set(required)

    fields: list[dict[str, Any]] = []
    for name, spec in properties.items():
        if not isinstance(name, str) or not name.strip():
            raise UnsupportedElicitationSchemaError("every property name must be a non-empty string")
        if not isinstance(spec, Mapping) or spec.get("type") != "string":
            raise UnsupportedElicitationSchemaError(f"property {name!r} must declare type 'string'")
        unsupported_keywords = set(spec) - {"type", "enum", "title", "default"}
        if unsupported_keywords:
            raise UnsupportedElicitationSchemaError(
                f"property {name!r} contains unsupported keywords: {sorted(unsupported_keywords)!r}"
            )
        enum_values = spec.get("enum")
        if enum_values is not None:
            if (
                not isinstance(enum_values, Sequence)
                or isinstance(enum_values, str)
                or not enum_values
                or len(enum_values) > MAX_ENUM_OPTIONS
                or not all(isinstance(item, str) and item for item in enum_values)
            ):
                raise UnsupportedElicitationSchemaError(
                    f"property {name!r} enum must be a non-empty string array"
                )
            if any(
                len(item.encode("utf-8", errors="replace")) > MAX_FIELD_VALUE_BYTES
                for item in enum_values
            ):
                raise UnsupportedElicitationSchemaError(
                    f"property {name!r} enum contains an option that is too long"
                )
            kind = "choice"
            options = [
                {
                    "id": f"{name}-option-{index}",
                    "label": _bounded(item, maximum_bytes=MAX_FIELD_LABEL_BYTES),
                    "value": _bounded(item, maximum_bytes=MAX_FIELD_VALUE_BYTES),
                }
                for index, item in enumerate(enum_values)
            ]
        else:
            kind = "text"
            options = None
        default_value = spec.get("default")
        if default_value is not None and not isinstance(default_value, str):
            raise UnsupportedElicitationSchemaError(f"property {name!r} default must be a string")
        if (
            isinstance(default_value, str)
            and len(default_value.encode("utf-8", errors="replace")) > MAX_FIELD_VALUE_BYTES
        ):
            raise UnsupportedElicitationSchemaError(f"property {name!r} default exceeds the maximum length")
        title = spec.get("title")
        if title is not None and not isinstance(title, str):
            raise UnsupportedElicitationSchemaError(f"property {name!r} title must be a string")
        fields.append(
            {
                "name": name,
                "label": _bounded(title or name, maximum_bytes=MAX_FIELD_LABEL_BYTES),
                "kind": kind,
                "required": name in required_names,
                "default_value": (
                    default_value if isinstance(default_value, str) else None
                ),
                "options": options,
            }
        )
    return fields


def validate_submitted_values(
    fields: Sequence[Mapping[str, Any]], values: Mapping[str, Any] | None
) -> dict[str, str]:
    """Validate submitted values against the persisted field definitions.

    Raises `ValueError` (the route maps this to HTTP 422) on any violation:
    an unknown field name, a missing required field, a non-string value, an
    overlong value, or a choice value outside its declared enum.
    """
    clean_values: dict[str, str] = {}
    submitted = dict(values) if isinstance(values, Mapping) else {}
    allowed_names = {field["name"] for field in fields}
    unknown = set(submitted) - allowed_names
    if unknown:
        raise ValueError(f"unknown field(s) in submitted values: {sorted(unknown)!r}")
    for field in fields:
        name = field["name"]
        raw_value = submitted.get(name)
        if raw_value is None:
            if field["required"]:
                raise ValueError(f"field {name!r} is required")
            continue
        if not isinstance(raw_value, str):
            raise ValueError(f"field {name!r} must be a string")
        if len(raw_value.encode("utf-8", errors="replace")) > MAX_FIELD_VALUE_BYTES:
            raise ValueError(f"field {name!r} exceeds the maximum allowed length")
        if field["kind"] == "choice":
            allowed_values = {option["value"] for option in (field["options"] or [])}
            if raw_value not in allowed_values:
                raise ValueError(f"field {name!r} value is not one of its declared choices")
        clean_values[name] = raw_value
    return clean_values


def _submitted_values_summary(
    fields: Sequence[Mapping[str, Any]], values: Mapping[str, Any] | None
) -> str | None:
    if not isinstance(values, Mapping):
        return None
    lines: list[str] = []
    for field in fields:
        value = values.get(field["name"])
        if value is None or value == "":
            continue
        option_labels = {
            option.get("value"): option.get("label")
            for option in (field.get("options") or [])
            if isinstance(option, Mapping)
        }
        lines.append(f"{field.get('label') or field['name']}: {option_labels.get(value) or value}")
    return "\n".join(lines) or None


class ProviderInteractionCoordinator:
    """Answer ACP `elicitation/create` (form mode) requests for one bound provider run."""

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
        self._delegated_interaction_callback = delegated_interaction_callback

    def bind_session(self, session_id: str) -> None:
        """Bind this coordinator to the agent-issued session ID exactly once."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if self._session_id is not None and self._session_id != session_id:
            raise ValueError("ProviderInteractionCoordinator is already bound to a different session")
        self._session_id = session_id

    async def handle_elicitation_create(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Answer one `elicitation/create` request. Registered via `register_request_handler`."""
        from api.services.agent_providers.interaction_delivery import (
            ProviderInteractionDeliveryRegistry,
        )

        if not isinstance(params, Mapping) or params.get("mode") != "form":
            raise AcpRequestError(-32602, "elicitation mode is not advertised by this client")
        if self._session_id is None or params.get("sessionId") != self._session_id:
            raise AcpRequestError(-32602, "elicitation sessionId does not match the bound session")

        requested_schema = params.get("requestedSchema")
        message = _bounded(
            params.get("message") or "The provider needs input.", maximum_bytes=MAX_MESSAGE_BYTES
        )
        try:
            fields = _normalize_form_fields(requested_schema if isinstance(requested_schema, Mapping) else {})
        except UnsupportedElicitationSchemaError as exc:
            self._logger.info(
                "Declining unsupported elicitation schema for provider run %s: %s",
                self._provider_run_id,
                exc,
            )
            return {"outcome": "decline"}

        interaction = await self._provider_interaction_repository.create_interaction(
            provider_run_id=self._provider_run_id,
            agent_task_id=self._agent_task_id,
            root_task_id=self._root_task_id or self._agent_task_id,
            message=message,
            requested_schema=dict(requested_schema),
            fields=fields,
        )
        interaction_id = str(interaction["id"])
        self._active_interaction_id = interaction_id
        if self._delegated_interaction_callback is not None:
            await self._delegated_interaction_callback(
                interaction_id=interaction_id,
                permission=False,
            )
        future = ProviderInteractionDeliveryRegistry.register(interaction_id)
        resolution: Mapping[str, Any] | None = None

        try:
            published = await self._routing_service.publish_provider_interaction_request(
                agent_task_id=self._agent_task_id,
                root_task_id=self._root_task_id,
                previous_task_id=self._previous_task_id,
                interaction_id=interaction_id,
                provider_run_id=self._provider_run_id,
                message=message,
                fields=fields,
            )
            if not published:
                ProviderInteractionDeliveryRegistry.resolve(interaction_id, "cancel", None)
            with pause_workflow_budget("provider_user_input"):
                resolution = await future
        except asyncio.CancelledError:
            await self.cancel_pending_interaction()
            raise
        finally:
            if resolution is None:
                await self.cancel_pending_interaction()
            ProviderInteractionDeliveryRegistry.discard(interaction_id)
            self._active_interaction_id = None

        assert resolution is not None
        outcome = resolution.get("outcome")
        if outcome not in _SUPPORTED_OUTCOMES:
            outcome = "cancel"
        values = resolution.get("values") if outcome == "accept" else None

        # The HTTP response route writes the terminal interaction state before
        # delivering its future. This fallback covers coordinator-owned
        # cancellation and a failed UI publication, neither of which traverses
        # that route.
        try:
            refreshed = await self._provider_interaction_repository.get_interaction(interaction_id)
            if refreshed is not None and refreshed["status"] == "pending":
                expected_revision = int(refreshed["revision"])
                if outcome == "accept":
                    await self._provider_interaction_repository.mark_answered(
                        interaction_id=interaction_id,
                        expected_revision=expected_revision,
                        submitted_values=values or {},
                    )
                elif outcome == "decline":
                    await self._provider_interaction_repository.mark_declined(
                        interaction_id=interaction_id,
                        expected_revision=expected_revision,
                    )
                else:
                    await self._provider_interaction_repository.mark_canceled(
                        interaction_id=interaction_id,
                        expected_revision=expected_revision,
                    )
        except Exception as exc:  # noqa: BLE001 - do not leave the provider waiting on cleanup.
            self._logger.warning(
                "Failed to persist fallback resolution for provider interaction %s: %s",
                interaction_id,
                exc,
            )

        if self._delegated_interaction_callback is not None:
            await self._delegated_interaction_callback(
                interaction_id=interaction_id,
                permission=False,
                resolved=True,
            )
        await self._routing_service.publish_provider_interaction_resolved(
            agent_task_id=self._agent_task_id,
            root_task_id=self._root_task_id,
            previous_task_id=self._previous_task_id,
            interaction_id=interaction_id,
            status={"accept": "answered", "decline": "denied"}.get(outcome, "cancelled"),
            response=_submitted_values_summary(fields, values) if outcome == "accept" else None,
        )

        if outcome == "accept":
            return {"outcome": "accept", "content": values or {}}
        return {"outcome": outcome}

    async def cancel_pending_interaction(self) -> None:
        """Resolve any interaction this coordinator is currently awaiting as `cancel`.

        Called from the provider run's cancellation/shutdown paths so a
        canceled run never leaves a dangling future or an unresolved
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


__all__ = [
    "ProviderInteractionCoordinator",
    "UnsupportedElicitationSchemaError",
    "validate_submitted_values",
]
