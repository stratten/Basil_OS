"""Immutable provider-target checkpoint projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import uuid

from .authorization_support import (
    CHECKPOINT_PROMPT,
    CHOICE_TOKEN_PREFIX,
    ProviderTargetAuthorizationError,
    _ValidatedSelection,
    _strip_sensitive_fields,
)


class ProviderTargetAuthorizationCheckpointFactory:
    """Build and project immutable provider-target checkpoint payloads."""

    @staticmethod
    def build_choice_snapshot(
        *,
        options: Sequence[_ValidatedSelection],
        cancel_value: str | None,
    ) -> list[dict[str, object]]:
        snapshot: list[dict[str, object]] = []
        for option in options:
            token = f"{CHOICE_TOKEN_PREFIX}{uuid.uuid4()}"
            snapshot.append(
                {
                    "token": token,
                    "label": option.display_label,
                    "description": option.description or "",
                    "provider_profile_id": option.provider_profile_id,
                    "workspace_grant_id": option.workspace_grant_id,
                    "connection_id": option.selected_connection_id,
                    "tool_name": option.selected_tool_name,
                }
            )
        if cancel_value is not None:
            snapshot.append({"cancel_value": cancel_value})
        return snapshot

    @staticmethod
    def cancel_value_from_snapshot(choice_snapshot: Sequence[object]) -> str | None:
        for item in choice_snapshot:
            if isinstance(item, Mapping):
                cancel_value = item.get("cancel_value")
                if isinstance(cancel_value, str) and cancel_value.strip():
                    return cancel_value.strip()
        return None

    @staticmethod
    def match_choice_token(
        choice_snapshot: Sequence[object],
        response_value: str,
    ) -> Mapping[str, object] | None:
        for item in choice_snapshot:
            if not isinstance(item, Mapping):
                continue
            token = item.get("token")
            if isinstance(token, str) and token == response_value:
                return item
        return None

    @staticmethod
    def checkpoint_options_from_snapshot(
        choice_snapshot: Sequence[object],
    ) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        for index, item in enumerate(choice_snapshot):
            if not isinstance(item, Mapping) or "token" not in item:
                continue
            token = item.get("token")
            label = item.get("label")
            description = item.get("description")
            if (
                not isinstance(token, str)
                or not token.startswith(CHOICE_TOKEN_PREFIX)
                or not isinstance(label, str)
                or not isinstance(description, str)
            ):
                raise ProviderTargetAuthorizationError(
                    "choice_snapshot contains an invalid target option"
                )
            options.append(
                {
                    "id": f"target-option-{index + 1}",
                    "label": label,
                    "value": token,
                    "description": description,
                }
            )
        return options

    def public_result(self, record: Mapping[str, object]) -> dict[str, object]:
        payload = _strip_sensitive_fields(record)
        if record.get("status") == "needs_user":
            authorization_id = str(record["id"])
            choice_snapshot = record.get("choice_snapshot")
            if not isinstance(choice_snapshot, list):
                raise ProviderTargetAuthorizationError("choice_snapshot is malformed")
            cancel_value = self.cancel_value_from_snapshot(choice_snapshot)
            if cancel_value is None:
                raise ProviderTargetAuthorizationError("choice_snapshot has no cancellation token")
            payload["checkpoint"] = {
                "checkpoint_id": authorization_id,
                "input_type": "choice",
                "prompt": CHECKPOINT_PROMPT,
                "options": self.checkpoint_options_from_snapshot(choice_snapshot),
                "metadata": {
                    "source": "provider_target_authorization",
                    "authorization_id": authorization_id,
                    "cancel_value": cancel_value,
                },
            }
        return payload
