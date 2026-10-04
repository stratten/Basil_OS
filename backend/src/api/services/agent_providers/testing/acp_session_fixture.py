"""Deterministic multi-message ACP session fixture peer.

This module is test infrastructure only. It plays the agent role of a persistent ACP v1 or v2 session against `AcpSessionClient`, scripted per `--fixture-mode` to exercise session creation, ordered notifications, an incoming agent-initiated request, cancellation, and the client's fail-closed handling of malformed, duplicate, out-of-order, and unsupported messages. It never selects or invokes any real external provider.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Mapping, Sequence

from api.services.agent_providers.acp.protocol import (
    ACP_PROTOCOL_V1,
    ACP_PROTOCOL_VERSION,
    MAX_JSON_RPC_LINE_BYTES,
)


AGENT_INFO = {"name": "Basil ACP session fixture", "version": "1.0.0"}


def _read_message() -> dict[str, Any]:
    line = sys.stdin.buffer.readline()
    if not line:
        raise EOFError("fixture stdin closed before an expected message")
    return json.loads(line.decode("utf-8"))


def _write_message(payload: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(
        json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        + b"\n"
    )
    sys.stdout.buffer.flush()


def _write_raw_line(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _read_and_respond_session_new(session_id: str) -> None:
    request = _read_message()
    _write_message(
        {"jsonrpc": "2.0", "id": request.get("id"), "result": {"sessionId": session_id}}
    )


def _valid_v2_initialize_request(request: Mapping[str, Any]) -> bool:
    if request.get("method") != "initialize":
        return False
    params = request.get("params")
    if not isinstance(params, Mapping):
        return False
    if params.get("protocolVersion") != ACP_PROTOCOL_VERSION:
        return False
    if "clientCapabilities" in params or "clientInfo" in params:
        return False
    capabilities = params.get("capabilities")
    info = params.get("info")
    return (
        isinstance(capabilities, Mapping)
        and isinstance(info, Mapping)
        and isinstance(info.get("name"), str)
        and bool(info["name"])
        and isinstance(info.get("version"), str)
        and bool(info["version"])
    )


def _handle_initialize(mode: str) -> int | None:
    request = _read_message()
    if request.get("method") != "initialize":
        return 2
    if not _valid_v2_initialize_request(request):
        return 3
    request_id = request.get("id")

    if mode == "unsupported_protocol_version":
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": 3,
                    "capabilities": {},
                    "info": AGENT_INFO,
                },
            }
        )
        return 0
    if mode == "malformed_initialize_result":
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"protocolVersion": ACP_PROTOCOL_VERSION},
            }
        )
        return 0
    if mode == "malformed_agent_info":
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": ACP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "info": {"name": "fixture without a version"},
                },
            }
        )
        return 0
    if mode == "v1_missing_agent_capabilities":
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": ACP_PROTOCOL_V1,
                    "agentInfo": AGENT_INFO,
                },
            }
        )
        return 0
    if mode == "v1_without_agent_info":
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": ACP_PROTOCOL_V1,
                    "agentCapabilities": {"sessionCapabilities": {"close": {}}},
                },
            }
        )
        return None
    if mode in {"v1_success", "v1_cancel_notification"}:
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": ACP_PROTOCOL_V1,
                    "agentCapabilities": {"sessionCapabilities": {"close": {}}},
                    "agentInfo": AGENT_INFO,
                },
            }
        )
        return None
    if mode in {
        "auth_success",
        "auth_unadvertised_method",
        "auth_remote_rejection",
    }:
        auth_method_id = (
            "different-method" if mode == "auth_unadvertised_method" else "api-key"
        )
        _write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": ACP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "info": AGENT_INFO,
                    "authMethods": [
                        {
                            "id": auth_method_id,
                            "name": "API Key",
                        }
                    ],
                },
            }
        )
        return None
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "capabilities": {"session": {}},
                "info": AGENT_INFO,
            },
        }
    )
    return None


def _run_success_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")

    prompt_request = _read_message()
    if prompt_request.get("method") != "session/prompt":
        return 2
    prompt_id = prompt_request.get("id")

    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {"kind": "message_chunk", "text": "step 1"},
            },
        }
    )
    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {"kind": "message_chunk", "text": "step 2"},
            },
        }
    )
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": "fixture-permission-1",
            "method": "session/request_permission",
            "params": {
                "sessionId": "fixture-session-1",
                "title": "Run tests",
                "description": "The fixture requests permission to run its test command.",
                "options": [
                    {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "deny", "name": "Deny", "kind": "reject_once"},
                ],
            },
        }
    )
    permission_response = _read_message()
    if permission_response.get("id") != "fixture-permission-1" or "result" not in permission_response:
        return 3

    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {"kind": "state_update", "state": "idle", "stopReason": "end_turn"},
            },
        }
    )
    _write_message({"jsonrpc": "2.0", "id": prompt_id, "result": {}})
    return 0


def _run_auth_success_mode() -> int:
    authentication_request = _read_message()
    if (
        authentication_request.get("method") != "authenticate"
        or authentication_request.get("params") != {"methodId": "api-key"}
    ):
        return 2
    _write_message(
        {"jsonrpc": "2.0", "id": authentication_request.get("id"), "result": {}}
    )
    _read_and_respond_session_new("fixture-session-1")
    return 0


def _run_auth_unadvertised_method_mode() -> int:
    try:
        unexpected_request = _read_message()
    except EOFError:
        return 0
    return 2 if unexpected_request.get("method") == "authenticate" else 3


def _run_auth_remote_rejection_mode() -> int:
    authentication_request = _read_message()
    if (
        authentication_request.get("method") != "authenticate"
        or authentication_request.get("params") != {"methodId": "api-key"}
    ):
        return 2
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": authentication_request.get("id"),
            "error": {"code": -32001, "message": "Authentication required"},
        }
    )
    time.sleep(60)
    return 0


def _run_cancel_notification_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")

    cancel_notification = _read_message()
    if cancel_notification.get("method") != "session/cancel" or "id" in cancel_notification:
        return 2

    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {"kind": "state_update", "state": "idle", "stopReason": "cancelled"},
            },
        }
    )
    return 0


def _run_v1_success_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    prompt_request = _read_message()
    if prompt_request.get("method") != "session/prompt":
        return 2
    prompt_id = prompt_request.get("id")
    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "messageId": "message-v1-1",
                    "content": {"type": "text", "text": "Read-only analysis complete."},
                },
            },
        }
    )
    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tool-v1-1",
                    "title": "Read README",
                    "kind": "read",
                    "status": "pending",
                },
            },
        }
    )
    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tool-v1-1",
                    "status": "completed",
                },
            },
        }
    )
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": prompt_id,
            "result": {"stopReason": "end_turn"},
        }
    )
    return 0


def _run_v1_cancel_notification_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    cancel_notification = _read_message()
    if cancel_notification.get("method") != "session/cancel" or "id" in cancel_notification:
        return 2
    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "fixture-session-1",
                "update": {
                    "sessionUpdate": "state_update",
                    "state": "idle",
                    "stopReason": "cancelled",
                },
            },
        }
    )
    return 0


def _run_malformed_message_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    _write_raw_line(b"{not-json}\n")
    return 0


def _run_duplicate_response_mode() -> int:
    request = _read_message()
    request_id = request.get("id")
    _write_message(
        {"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "fixture-session-1"}}
    )
    _write_message(
        {"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "fixture-session-1"}}
    )
    return 0


def _run_boolean_response_id_mode() -> int:
    _read_message()
    _write_message({"jsonrpc": "2.0", "id": True, "result": {"sessionId": "fixture-session-1"}})
    return 0


def _run_response_with_result_and_error_mode() -> int:
    request = _read_message()
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"sessionId": "fixture-session-1"},
            "error": {"code": -32600, "message": "malformed response"},
        }
    )
    return 0


def _run_invalid_error_object_mode() -> int:
    request = _read_message()
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": "not-an-integer", "message": 42},
        }
    )
    return 0


def _run_invalid_notification_params_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    _write_message({"jsonrpc": "2.0", "method": "session/update", "params": ["not", "an", "object"]})
    return 0


def _run_invalid_incoming_request_id_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": True,
            "method": "session/request_permission",
            "params": {},
        }
    )
    return 0


def _run_unsupported_incoming_request_mode() -> int:
    # The unsupported request is sent while session/new is still pending, so the client cannot send its next request before answering it.
    session_request = _read_message()

    _write_message(
        {
            "jsonrpc": "2.0",
            "id": "fixture-unsupported-1",
            "method": "unsupported/method",
            "params": {},
        }
    )
    error_response = _read_message()
    if error_response.get("id") != "fixture-unsupported-1" or "error" not in error_response:
        return 3
    if error_response["error"].get("code") != -32601:
        return 4

    _write_message(
        {"jsonrpc": "2.0", "id": session_request.get("id"), "result": {"sessionId": "fixture-session-1"}}
    )
    _read_and_respond_session_new("fixture-session-2")
    return 0


def _run_duplicate_incoming_request_id_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")

    _write_message(
        {
            "jsonrpc": "2.0",
            "id": "dup-1",
            "method": "session/request_permission",
            "params": {"marker": "A"},
        }
    )
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": "dup-1",
            "method": "session/request_permission",
            "params": {"marker": "B"},
        }
    )
    first_response = _read_message()
    second_response = _read_message()
    responses = [first_response, second_response]
    if not all(response.get("id") == "dup-1" for response in responses):
        return 5
    has_result = any("result" in response for response in responses)
    has_duplicate_error = any(
        "error" in response and "duplicate" in response["error"].get("message", "")
        for response in responses
    )
    if not (has_result and has_duplicate_error):
        return 6
    return 0


def _run_out_of_order_responses_mode() -> int:
    first_request = _read_message()
    second_request = _read_message()
    first_id = first_request.get("id")
    second_id = second_request.get("id")
    first_cwd = (first_request.get("params") or {}).get("cwd")
    second_cwd = (second_request.get("params") or {}).get("cwd")
    _write_message(
        {"jsonrpc": "2.0", "id": second_id, "result": {"sessionId": f"session-for-{second_cwd}"}}
    )
    _write_message(
        {"jsonrpc": "2.0", "id": first_id, "result": {"sessionId": f"session-for-{first_cwd}"}}
    )
    return 0


def _run_oversized_line_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    _write_raw_line(b"x" * 70_000 + b"\n")
    return 0


def _run_large_valid_line_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    request = _read_message()
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"sessionId": "fixture-session-large-" + ("x" * 131_072)},
        }
    )
    return 0


def _run_transport_oversized_line_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    _write_raw_line(b"x" * (MAX_JSON_RPC_LINE_BYTES + 1) + b"\n")
    return 0


def _run_no_response_after_prompt_mode() -> int:
    _read_and_respond_session_new("fixture-session-1")
    prompt_request = _read_message()
    if prompt_request.get("method") != "session/prompt":
        return 2
    time.sleep(60)
    return 0


def _run_fixture(mode: str) -> int:
    exit_code = _handle_initialize(mode)
    if exit_code is not None:
        return exit_code

    if mode == "success":
        return _run_success_mode()
    if mode == "auth_success":
        return _run_auth_success_mode()
    if mode == "auth_unadvertised_method":
        return _run_auth_unadvertised_method_mode()
    if mode == "auth_remote_rejection":
        return _run_auth_remote_rejection_mode()
    if mode == "cancel_notification":
        return _run_cancel_notification_mode()
    if mode == "v1_success":
        return _run_v1_success_mode()
    if mode == "v1_cancel_notification":
        return _run_v1_cancel_notification_mode()
    if mode == "malformed_message":
        return _run_malformed_message_mode()
    if mode == "duplicate_response":
        return _run_duplicate_response_mode()
    if mode == "boolean_response_id":
        return _run_boolean_response_id_mode()
    if mode == "response_with_result_and_error":
        return _run_response_with_result_and_error_mode()
    if mode == "invalid_error_object":
        return _run_invalid_error_object_mode()
    if mode == "invalid_notification_params":
        return _run_invalid_notification_params_mode()
    if mode == "invalid_incoming_request_id":
        return _run_invalid_incoming_request_id_mode()
    if mode == "unsupported_incoming_request":
        return _run_unsupported_incoming_request_mode()
    if mode == "duplicate_incoming_request_id":
        return _run_duplicate_incoming_request_id_mode()
    if mode == "out_of_order_responses":
        return _run_out_of_order_responses_mode()
    if mode == "oversized_line":
        return _run_oversized_line_mode()
    if mode == "large_valid_line":
        return _run_large_valid_line_mode()
    if mode == "transport_oversized_line":
        return _run_transport_oversized_line_mode()
    if mode == "no_response_after_prompt":
        return _run_no_response_after_prompt_mode()
    return 9


def main(argv: Sequence[str] | None = None) -> int:
    """Expose only the deterministic fixture modes for the focused test suite."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-mode",
        choices=(
            "success",
            "cancel_notification",
            "v1_success",
            "v1_cancel_notification",
            "v1_missing_agent_capabilities",
            "v1_without_agent_info",
            "unsupported_protocol_version",
            "malformed_initialize_result",
            "malformed_agent_info",
            "auth_success",
            "auth_unadvertised_method",
            "auth_remote_rejection",
            "malformed_message",
            "duplicate_response",
            "boolean_response_id",
            "response_with_result_and_error",
            "invalid_error_object",
            "invalid_notification_params",
            "invalid_incoming_request_id",
            "unsupported_incoming_request",
            "duplicate_incoming_request_id",
            "out_of_order_responses",
            "oversized_line",
            "large_valid_line",
            "transport_oversized_line",
            "no_response_after_prompt",
        ),
    )
    arguments = parser.parse_args(argv)
    if arguments.fixture_mode is None:
        parser.error("--fixture-mode is required")
    return _run_fixture(arguments.fixture_mode)


if __name__ == "__main__":
    raise SystemExit(main())
