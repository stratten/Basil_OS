"""Normalize a bounded, JSON-serializable durable provider-permission action summary (Package 4B.2)."""

from __future__ import annotations

import json
from typing import Any

from api.services.agent_providers.acp.session_client import AcpRequestError

from .provider_permission_request_coordinator import (
    MAX_DESCRIPTION_BYTES,
    MAX_TITLE_BYTES,
    _require_nonblank_string,
    _validate_options,
    _validate_subject,
)

MAX_SUBJECT_BYTES = 16_384


class InvalidPermissionActionSummaryError(RuntimeError):
    """The title, description, options, or subject cannot be normalized."""


def _normalize_subject(subject: Any) -> dict[str, Any] | None:
    _validate_subject(subject)
    if subject is None:
        return None
    try:
        serialized_subject = json.dumps(subject, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidPermissionActionSummaryError("subject must be JSON-serializable") from exc
    if len(serialized_subject.encode("utf-8", errors="replace")) > MAX_SUBJECT_BYTES:
        raise InvalidPermissionActionSummaryError("subject exceeds the maximum allowed length")
    parsed_subject = json.loads(serialized_subject)
    if not isinstance(parsed_subject, dict):
        raise InvalidPermissionActionSummaryError("subject must serialize to an object")
    return parsed_subject


def normalize_permission_action_summary(
    *,
    title: Any,
    description: Any,
    options: Any,
    subject: Any,
) -> dict[str, Any]:
    """Validate and normalize one bounded, JSON-serializable `session/request_permission` action summary for durable persistence."""
    try:
        clean_title = _require_nonblank_string(
            title, field_name="title", maximum_bytes=MAX_TITLE_BYTES
        )
        if description is not None and not isinstance(description, str):
            raise AcpRequestError(-32602, "description must be a string or null")
        if (
            isinstance(description, str)
            and len(description.encode("utf-8", errors="replace")) > MAX_DESCRIPTION_BYTES
        ):
            raise AcpRequestError(-32602, "description exceeds the maximum allowed length")
        clean_options = _validate_options(options)
        clean_subject = _normalize_subject(subject)
    except AcpRequestError as exc:
        raise InvalidPermissionActionSummaryError(str(exc)) from exc

    return {
        "title": clean_title,
        "description": description if isinstance(description, str) else None,
        "options": clean_options,
        "subject": clean_subject,
    }


__all__ = ["InvalidPermissionActionSummaryError", "normalize_permission_action_summary"]
