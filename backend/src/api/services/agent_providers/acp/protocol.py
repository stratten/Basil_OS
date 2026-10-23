"""Version-negotiated ACP contracts shared by the client and transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

ACP_PROTOCOL_V1 = 1
ACP_PROTOCOL_VERSION = 2
SUPPORTED_ACP_PROTOCOL_VERSIONS = (ACP_PROTOCOL_V1, ACP_PROTOCOL_VERSION)
MAX_JSON_RPC_LINE_BYTES = 1_048_576
MAX_STDERR_BYTES = 8_192

RequestHandler = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
NotificationHandler = Callable[[Mapping[str, Any]], Awaitable[None]]


class AcpClientError(RuntimeError):
    """Base error for the persistent ACP session client."""


class AcpClientProtocolError(AcpClientError):
    """The peer emitted a malformed or unsupported protocol message."""


class AcpClientTimeoutError(AcpClientError):
    """An outgoing request was not answered before its deadline."""


@dataclass(frozen=True, init=False)
class AcpRemoteRequestError(AcpClientError):
    """The peer rejected one otherwise well-formed outgoing JSON-RPC request."""

    code: int
    message_text: str

    def __init__(self, code: int, message_text: str) -> None:
        AcpClientError.__init__(self, message_text)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message_text", message_text)


class AcpRequestError(AcpClientError):
    """Raise from an incoming-request handler to return a specific JSON-RPC error."""

    def __init__(self, code: int, message_text: str) -> None:
        super().__init__(message_text)
        self.code = code
        self.message_text = message_text


class AcpClientClosedError(AcpClientError):
    """An operation was attempted after the session was closed or poisoned."""


@dataclass(frozen=True)
class AcpAuthMethod:
    """An ACP agent-advertised non-secret authentication method."""

    method_id: str
    name: str | None
    description: str | None


@dataclass(frozen=True)
class AcpInitializeResult:
    """Validated, version-normalized fields from one ACP initialize response."""

    protocol_version: int
    agent_capabilities: dict[str, Any]
    agent_info: dict[str, Any] | None
    auth_methods: tuple[AcpAuthMethod, ...]


@dataclass(frozen=True)
class AcpSessionHandle:
    """A created ACP session identified by its agent-issued session id."""

    session_id: str


def build_acp_initialize_params(
    *,
    client_capabilities: Mapping[str, Any],
    client_info: Mapping[str, str],
) -> dict[str, Any]:
    """Build the v2 envelope used to negotiate the newest supported ACP version."""
    return {
        "protocolVersion": ACP_PROTOCOL_VERSION,
        "capabilities": dict(client_capabilities),
        "info": dict(client_info),
    }


def _parse_auth_methods(result: Mapping[str, Any]) -> tuple[AcpAuthMethod, ...]:
    raw_auth_methods = result.get("authMethods")
    if raw_auth_methods is None:
        return ()
    if not isinstance(raw_auth_methods, list):
        raise AcpClientProtocolError("initialize response authMethods must be a list")
    parsed: list[AcpAuthMethod] = []
    seen_method_ids: set[str] = set()
    for item in raw_auth_methods:
        if not isinstance(item, Mapping):
            raise AcpClientProtocolError(
                "initialize response authMethods entries must be objects"
            )
        method_id = item.get("id")
        if (
            not isinstance(method_id, str)
            or not method_id
            or len(method_id) > 128
            or any(
                not character.isascii()
                or not character.isprintable()
                or character.isspace()
                for character in method_id
            )
        ):
            raise AcpClientProtocolError(
                "initialize response authMethods entries must have a printable non-whitespace id"
            )
        if method_id in seen_method_ids:
            raise AcpClientProtocolError(
                "initialize response authMethods contains duplicate id"
            )
        name = item.get("name")
        description = item.get("description")
        if name is not None and not isinstance(name, str):
            raise AcpClientProtocolError(
                "initialize response authMethods entry name must be a string"
            )
        if description is not None and not isinstance(description, str):
            raise AcpClientProtocolError(
                "initialize response authMethods entry description must be a string"
            )
        seen_method_ids.add(method_id)
        parsed.append(
            AcpAuthMethod(
                method_id=method_id,
                name=name,
                description=description,
            )
        )
    return tuple(parsed)


def parse_acp_initialize_result(result: Mapping[str, Any]) -> AcpInitializeResult:
    """Validate a v1 or v2 initialize result and normalize its common fields."""
    protocol_version = result.get("protocolVersion")
    if type(protocol_version) is not int or protocol_version not in SUPPORTED_ACP_PROTOCOL_VERSIONS:
        raise AcpClientProtocolError(
            "unsupported ACP protocol version "
            f"{protocol_version!r}; Basil supports {SUPPORTED_ACP_PROTOCOL_VERSIONS!r}"
        )
    if protocol_version == ACP_PROTOCOL_V1:
        capability_field = "agentCapabilities"
        info_field = "agentInfo"
        info_required = False
    else:
        capability_field = "capabilities"
        info_field = "info"
        info_required = True
    capabilities = result.get(capability_field)
    if not isinstance(capabilities, Mapping):
        raise AcpClientProtocolError(
            f"initialize response {capability_field} must be an object"
        )
    info = result.get(info_field)
    if info is None and not info_required:
        return AcpInitializeResult(
            protocol_version=protocol_version,
            agent_capabilities=dict(capabilities),
            agent_info=None,
            auth_methods=_parse_auth_methods(result),
        )
    if (
        not isinstance(info, Mapping)
        or not isinstance(info.get("name"), str)
        or not info["name"]
        or not isinstance(info.get("version"), str)
        or not info["version"]
    ):
        raise AcpClientProtocolError(
            f"initialize response {info_field} must contain non-empty name and version strings"
        )
    return AcpInitializeResult(
        protocol_version=protocol_version,
        agent_capabilities=dict(capabilities),
        agent_info=dict(info),
        auth_methods=_parse_auth_methods(result),
    )
