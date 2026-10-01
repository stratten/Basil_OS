"""Fail-closed ACP v1/v2 `session/request_permission` protocol contract (Package 4B.1).

Validates the request envelope, session identity, and `PermissionOption`
shape against the documented negotiated ACP v1/v2 contract, then answers with the
protocol-correct JSON-RPC error for a malformed request or a request this
package cannot safely decline, or with a `selected` outcome pointing at a
reject-kind option when one is present. Never grants an `allow_once` or
`allow_always` option, never emits the `canceled` outcome (reserved for the
client's own `session/cancel` handling), never persists a provider-permission
interaction, never publishes a WebSocket event, and never advertises a
negotiated permission capability. Persistence, delivery, and activation
through the existing approval surface are owned by Packages 4B.2 and 4B.3.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from api.services.agent_providers.acp.protocol import ACP_PROTOCOL_V1, ACP_PROTOCOL_VERSION
from api.services.agent_providers.acp.session_client import AcpRequestError

MAX_TITLE_BYTES = 512
MAX_DESCRIPTION_BYTES = 2_048
MAX_OPTION_NAME_BYTES = 256
MAX_OPTION_ID_BYTES = 256
MAX_OPTION_KIND_BYTES = 64
MAX_OPTIONS = 20
MAX_COMMAND_BYTES = 4_096
MAX_CWD_BYTES = 4_096
MAX_TERMINAL_ID_BYTES = 256
MAX_TOOL_CALL_ID_BYTES = 256

_REJECT_KIND_PRIORITY = ("reject_once", "reject_always")
_OPTION_ALLOWED_KEYS = {"optionId", "name", "kind", "_meta"}


def _require_nonblank_string(value: Any, *, field_name: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcpRequestError(-32602, f"{field_name} must be a nonblank string")
    if len(value.encode("utf-8", errors="replace")) > maximum_bytes:
        raise AcpRequestError(-32602, f"{field_name} exceeds the maximum allowed length")
    return value


def _validate_options(options: Any) -> list[dict[str, str]]:
    if (
        not isinstance(options, Sequence)
        or isinstance(options, (str, bytes, bytearray))
        or not options
        or len(options) > MAX_OPTIONS
    ):
        raise AcpRequestError(-32602, f"options must contain between 1 and {MAX_OPTIONS} entries")
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for option in options:
        if not isinstance(option, Mapping):
            raise AcpRequestError(-32602, "every option must be an object")
        unsupported = set(option) - _OPTION_ALLOWED_KEYS
        if unsupported:
            raise AcpRequestError(-32602, f"option contains unsupported keys: {sorted(unsupported)!r}")
        option_id = _require_nonblank_string(
            option.get("optionId"), field_name="option optionId", maximum_bytes=MAX_OPTION_ID_BYTES
        )
        name = _require_nonblank_string(
            option.get("name"), field_name="option name", maximum_bytes=MAX_OPTION_NAME_BYTES
        )
        kind = _require_nonblank_string(
            option.get("kind"), field_name="option kind", maximum_bytes=MAX_OPTION_KIND_BYTES
        )
        if option_id in seen_ids:
            raise AcpRequestError(-32602, f"duplicate option optionId {option_id!r}")
        seen_ids.add(option_id)
        normalized.append({"optionId": option_id, "name": name, "kind": kind})
    return normalized


def _validate_subject(subject: Any) -> None:
    """Validate a recognized `subject` shape; tolerate an unrecognized `type` as forward-compatible."""
    if subject is None:
        return
    if not isinstance(subject, Mapping):
        raise AcpRequestError(-32602, "subject must be an object or null")
    subject_type = subject.get("type")
    if not isinstance(subject_type, str) or not subject_type.strip():
        raise AcpRequestError(-32602, "subject.type must be a nonblank string")

    if subject_type == "tool_call":
        tool_call = subject.get("toolCall")
        tool_call_id = tool_call.get("toolCallId") if isinstance(tool_call, Mapping) else None
        _require_nonblank_string(
            tool_call_id,
            field_name="tool_call subject.toolCall.toolCallId",
            maximum_bytes=MAX_TOOL_CALL_ID_BYTES,
        )
        return

    if subject_type == "command":
        _require_nonblank_string(
            subject.get("command"),
            field_name="command subject.command",
            maximum_bytes=MAX_COMMAND_BYTES,
        )
        cwd = _require_nonblank_string(
            subject.get("cwd"),
            field_name="command subject.cwd",
            maximum_bytes=MAX_CWD_BYTES,
        )
        if not isinstance(cwd, str) or not cwd.startswith("/"):
            raise AcpRequestError(-32602, "command subject.cwd must be an absolute path string")
        for optional_key, maximum_bytes in (
            ("terminalId", MAX_TERMINAL_ID_BYTES),
            ("toolCallId", MAX_TOOL_CALL_ID_BYTES),
        ):
            value = subject.get(optional_key)
            if value is not None:
                _require_nonblank_string(
                    value,
                    field_name=f"command subject.{optional_key}",
                    maximum_bytes=maximum_bytes,
                )
        return

    # Unrecognized/custom subject.type: forward-compatible per ACP v2's
    # RequestPermissionSubject union. Not malformed; Basil does not interpret
    # its content in this package and still applies the fail-closed decision.
    return


def normalize_provider_permission_request(
    params: Mapping[str, Any],
    *,
    protocol_version: int,
) -> tuple[str, str | None, list[dict[str, str]], Mapping[str, Any] | None]:
    """Normalize documented ACP v1 or v2 permission fields before policy handling."""
    if protocol_version == ACP_PROTOCOL_V1:
        tool_call = params.get("toolCall")
        if not isinstance(tool_call, Mapping):
            raise AcpRequestError(-32602, "ACP v1 session/request_permission requires toolCall")
        tool_call_id = _require_nonblank_string(
            tool_call.get("toolCallId"),
            field_name="ACP v1 toolCall.toolCallId",
            maximum_bytes=MAX_TOOL_CALL_ID_BYTES,
        )
        raw_title = tool_call.get("title")
        title = (
            _require_nonblank_string(
                raw_title,
                field_name="ACP v1 toolCall.title",
                maximum_bytes=MAX_TITLE_BYTES,
            )
            if raw_title is not None
            else "Provider tool request"
        )
        return (
            title,
            None,
            _validate_options(params.get("options")),
            {"type": "tool_call", "toolCall": {"toolCallId": tool_call_id}},
        )
    if protocol_version != ACP_PROTOCOL_VERSION:
        raise AcpRequestError(-32602, f"unsupported negotiated ACP protocol version {protocol_version!r}")
    title = _require_nonblank_string(
        params.get("title"),
        field_name="title",
        maximum_bytes=MAX_TITLE_BYTES,
    )
    description = params.get("description")
    if description is not None and not isinstance(description, str):
        raise AcpRequestError(-32602, "description must be a string or null")
    if (
        isinstance(description, str)
        and len(description.encode("utf-8", errors="replace")) > MAX_DESCRIPTION_BYTES
    ):
        raise AcpRequestError(-32602, "description exceeds the maximum allowed length")
    subject = params.get("subject")
    _validate_subject(subject)
    return title, description, _validate_options(params.get("options")), subject


def _select_reject_option(options: Sequence[Mapping[str, str]]) -> dict[str, str] | None:
    for preferred_kind in _REJECT_KIND_PRIORITY:
        for option in options:
            if option["kind"] == preferred_kind:
                return dict(option)
    return None


class ProviderPermissionRequestCoordinator:
    """Answer ACP v1/v2 `session/request_permission` requests with a fail-closed decision.

    Bound to exactly one provider run's agent-issued session ID. Never grants
    an `allow_once`/`allow_always` option and never persists, publishes, or
    surfaces a request to the user; see the module docstring.
    """

    def __init__(
        self,
        *,
        provider_run_id: str | None = None,
        logger: logging.Logger | None = None,
        protocol_version: int = ACP_PROTOCOL_VERSION,
    ) -> None:
        self._provider_run_id = provider_run_id
        self._logger = logger or logging.getLogger(__name__)
        self._protocol_version = protocol_version
        self._session_id: str | None = None

    def bind_session(self, session_id: str) -> None:
        """Bind this coordinator to the agent-issued session ID exactly once."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if self._session_id is not None and self._session_id != session_id:
            raise ValueError(
                "ProviderPermissionRequestCoordinator is already bound to a different session"
            )
        self._session_id = session_id

    async def handle_request_permission(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Answer one `session/request_permission` request. Registered via `register_request_handler`."""
        if not isinstance(params, Mapping):
            raise AcpRequestError(-32602, "session/request_permission params must be an object")

        session_id = params.get("sessionId")
        if self._session_id is None or session_id != self._session_id:
            raise AcpRequestError(
                -32602, "session/request_permission sessionId does not match the bound session"
            )

        _, _, options, _ = normalize_provider_permission_request(
            params,
            protocol_version=self._protocol_version,
        )

        reject_option = _select_reject_option(options)
        if reject_option is None:
            self._logger.info(
                "Declining session/request_permission for provider run %s: no reject-kind option "
                "was offered and the permission capability is not enabled",
                self._provider_run_id,
            )
            raise AcpRequestError(
                -32601,
                "session/request_permission cannot be safely declined without a reject-kind "
                "option; the permission capability is not enabled",
            )

        self._logger.info(
            "Declining session/request_permission for provider run %s via a reject-kind option",
            self._provider_run_id,
        )
        return {"outcome": {"outcome": "selected", "optionId": reject_option["optionId"]}}


__all__ = ["ProviderPermissionRequestCoordinator", "normalize_provider_permission_request"]
