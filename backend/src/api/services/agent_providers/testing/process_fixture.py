"""Deterministic local external ACP runtime fixture entry point."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

from api.services.agent_providers.acp.protocol import ACP_PROTOCOL_V1, ACP_PROTOCOL_VERSION

AGENT_INFO = {"name": "Basil ACP process fixture", "version": "2.0.0-fixture"}


def read_message() -> dict[str, Any]:
    line = sys.stdin.buffer.readline()
    if not line:
        raise EOFError("fixture stdin closed before an expected message")
    return json.loads(line.decode("utf-8"))


def write_message(payload: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def write_raw_line(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def respond_initialize(
    request_id: Any,
    *,
    agent_capabilities: Mapping[str, Any] | None = None,
    protocol_version: int = ACP_PROTOCOL_VERSION,
) -> None:
    capabilities = (
        dict(agent_capabilities) if agent_capabilities is not None else {}
    )
    if protocol_version == ACP_PROTOCOL_V1:
        result = {
            "protocolVersion": ACP_PROTOCOL_V1,
            "agentCapabilities": capabilities,
            "agentInfo": AGENT_INFO,
        }
    else:
        result = {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "capabilities": capabilities,
            "info": AGENT_INFO,
        }
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def respond_session_new(request_id: Any, session_id: str) -> None:
    write_message({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": session_id}})


def write_session_update(session_id: str, update: Any) -> None:
    write_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session_id, "update": update}})


def send_request_and_read_response(request_id: Any, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
    write_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
    return read_message()


def initialize_session_and_prompt(*, protocol_version: int = ACP_PROTOCOL_VERSION) -> tuple[int, str | None]:
    initialize_request = read_message()
    if initialize_request.get("method") != "initialize":
        return 2, None
    respond_initialize(
        initialize_request.get("id"),
        protocol_version=protocol_version,
    )
    session_request = read_message()
    if session_request.get("method") != "session/new":
        return 3, None
    session_id = "fixture-process-session"
    respond_session_new(session_request.get("id"), session_id)
    prompt_request = read_message()
    if prompt_request.get("method") != "session/prompt":
        return 4, None
    write_message({"jsonrpc": "2.0", "id": prompt_request.get("id"), "result": {}})
    return 0, session_id


def run_v1_clean_exit_mode() -> int:
    initialize_request = read_message()
    if initialize_request.get("method") != "initialize":
        return 2
    respond_initialize(
        initialize_request.get("id"),
        protocol_version=ACP_PROTOCOL_V1,
    )
    session_request = read_message()
    if session_request.get("method") != "session/new":
        return 3
    session_id = "fixture-process-session"
    respond_session_new(session_request.get("id"), session_id)
    prompt_request = read_message()
    if prompt_request.get("method") != "session/prompt":
        return 4
    write_message(
        {"jsonrpc": "2.0", "id": prompt_request.get("id"), "result": {"stopReason": "end_turn"}}
    )
    return 0


def run_clean_exit_mode() -> int:
    status, _ = initialize_session_and_prompt()
    return status


def run_persistent_after_prompt_mode() -> int:
    status, _ = initialize_session_and_prompt()
    if status:
        return status
    while True:
        time.sleep(1)


def run_activity_stream_mode() -> int:
    status, session_id = initialize_session_and_prompt()
    if status:
        return status
    assert session_id is not None
    thought_text = "Inspecting\x00 the workspace before responding.\r\n" + ("x" * 9_000)
    write_session_update(session_id, {"sessionUpdate": "agent_thought_chunk", "messageId": "thought-1", "content": {"type": "text", "text": thought_text}})
    message_update = {"sessionUpdate": "agent_message_chunk", "messageId": "message-1", "content": {"type": "text", "text": "I inspected the workspace."}}
    write_session_update(session_id, dict(message_update))
    write_session_update(session_id, dict(message_update))
    tool_update = {"sessionUpdate": "tool_call_update", "toolCallId": "tool-1", "title": "Inspect project files", "kind": "read", "locations": [{"path": "/tmp/a.py", "line": 1}, {"path": "/tmp/b.py", "line": 2}]}
    write_session_update(session_id, {**tool_update, "status": "in_progress"})
    write_session_update(session_id, {**tool_update, "status": "completed"})
    write_session_update(session_id, {"sessionUpdate": "terminal_output_chunk", "terminalId": "terminal-1", "output": "pytest passed"})
    write_session_update(session_id, {"sessionUpdate": "state_update", "state": "idle", "stopReason": "end_turn"})
    write_session_update(session_id, {"sessionUpdate": "future_update", "text": "unrecognized update kind"})
    write_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session_id, "update": "not-an-object"}})
    return 0


def run_startup_crash_mode() -> int:
    sys.stderr.write("fixture: simulated startup crash before initialize response\n")
    sys.stderr.flush()
    return 17


def _initialize_and_session(*, protocol_version: int = ACP_PROTOCOL_VERSION) -> tuple[int, str | None]:
    initialize_request = read_message()
    if initialize_request.get("method") != "initialize":
        return 2, None
    respond_initialize(
        initialize_request.get("id"),
        protocol_version=protocol_version,
    )
    session_request = read_message()
    if session_request.get("method") != "session/new":
        return 3, None
    session_id = "fixture-process-session"
    respond_session_new(session_request.get("id"), session_id)
    return 0, session_id


def run_protocol_violation_after_initialize_mode() -> int:
    initialize_request = read_message()
    if initialize_request.get("method") != "initialize":
        return 2
    respond_initialize(initialize_request.get("id"))
    session_request = read_message()
    if session_request.get("method") != "session/new":
        return 3
    write_raw_line(b"{not-json}\n")
    time.sleep(1.0)
    return 0


def run_crash_after_session_mode() -> int:
    status, _ = _initialize_and_session()
    if status:
        return status
    prompt_request = read_message()
    if prompt_request.get("method") != "session/prompt":
        return 4
    sys.stderr.write("fixture: simulated crash after accepting a prompt\n")
    sys.stderr.flush()
    os._exit(1)


def run_protocol_violation_after_prompt_mode() -> int:
    status, _ = initialize_session_and_prompt()
    if status:
        return status
    write_raw_line(b"{not-json}\n")
    return 0


def run_hang_before_initialize_mode() -> int:
    time.sleep(60)
    return 0


def run_ignores_sigterm_mode() -> int:
    status, _ = _initialize_and_session()
    if status:
        return status
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
    return 0


def run_spawns_child_and_hangs_mode() -> int:
    child_pid_file = os.environ.get("BASIL_ACP_TEST_CHILD_PID_FILE")
    if not child_pid_file:
        return 5
    status, _ = _initialize_and_session()
    if status:
        return status
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open(child_pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(grandchild.pid))
    time.sleep(60)
    return 0


def run_environment_probe_mode() -> int:
    initialize_request = read_message()
    if initialize_request.get("method") != "initialize":
        return 2
    observed_env: dict[str, Any] = {"BASIL_ACP_TEST_ALLOWED": os.environ.get("BASIL_ACP_TEST_ALLOWED"), "BASIL_ACP_TEST_FORBIDDEN": os.environ.get("BASIL_ACP_TEST_FORBIDDEN"), "PATH": os.environ.get("PATH")}
    respond_initialize(initialize_request.get("id"), agent_capabilities={"observedEnv": observed_env, "workingDirectory": os.getcwd()})
    session_request = read_message()
    if session_request.get("method") != "session/new":
        return 3
    respond_session_new(session_request.get("id"), "fixture-process-session")
    prompt_request = read_message()
    if prompt_request.get("method") != "session/prompt":
        return 4
    write_message({"jsonrpc": "2.0", "id": prompt_request.get("id"), "result": {}})
    return 0


def _request_permission(request_id: str, params: Mapping[str, Any]) -> tuple[int, str | None, dict[str, Any] | None]:
    status, session_id = initialize_session_and_prompt()
    if status:
        return status, None, None
    assert session_id is not None
    request = dict(params)
    request["sessionId"] = request.get("sessionId", session_id)
    return 0, session_id, send_request_and_read_response(request_id, "session/request_permission", request)


def run_elicitation_single_field_mode() -> int:
    status, session_id = initialize_session_and_prompt()
    if status:
        return status
    assert session_id is not None
    response = send_request_and_read_response("fixture-elicit-1", "elicitation/create", {"sessionId": session_id, "mode": "form", "message": "How should I approach this refactoring?", "requestedSchema": {"type": "object", "properties": {"strategy": {"type": "string", "enum": ["conservative", "balanced", "aggressive"]}}, "required": ["strategy"]}})
    result = response.get("result") or {}
    write_session_update(session_id, {"sessionUpdate": "agent_message_chunk", "messageId": "message-elicit-ack", "content": {"type": "text", "text": f"Received elicitation outcome: {result.get('outcome')}"}})
    return 0


def run_elicitation_before_prompt_response_mode() -> int:
    status, session_id = _initialize_and_session()
    if status:
        return status
    assert session_id is not None
    prompt_request = read_message()
    if prompt_request.get("method") != "session/prompt":
        return 4
    response = send_request_and_read_response(
        "fixture-elicit-before-prompt-response-1",
        "elicitation/create",
        {
            "sessionId": session_id,
            "mode": "form",
            "message": "How should I approach this refactoring?",
            "requestedSchema": {
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "string",
                        "enum": ["conservative", "balanced", "aggressive"],
                    }
                },
                "required": ["strategy"],
            },
        },
    )
    result = response.get("result") or {}
    if result != {"outcome": "accept", "content": {"strategy": "balanced"}}:
        return 6
    write_message({"jsonrpc": "2.0", "id": prompt_request.get("id"), "result": {}})
    write_session_update(
        session_id,
        {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-elicit-before-prompt-response-ack",
            "content": {"type": "text", "text": "Received elicitation outcome: accept"},
        },
    )
    return 0


def run_elicitation_unsupported_schema_mode() -> int:
    status, session_id = initialize_session_and_prompt()
    if status:
        return status
    assert session_id is not None
    response = send_request_and_read_response("fixture-elicit-unsupported-1", "elicitation/create", {"sessionId": session_id, "mode": "form", "message": "How many retries should I allow?", "requestedSchema": {"type": "object", "properties": {"retries": {"type": "number"}}, "required": ["retries"]}})
    return 0 if (response.get("result") or {}).get("outcome") == "decline" else 6


def _permission_options() -> list[dict[str, str]]:
    return [{"optionId": "allow-once", "name": "Allow", "kind": "allow_once"}, {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}]


def run_permission_request_denied_mode() -> int:
    status, session_id, response = _request_permission("fixture-permission-denied-1", {"title": "Run `rm -rf /tmp/scratch`?", "description": "The agent wants to delete a scratch directory.", "options": _permission_options(), "subject": {"type": "command", "command": "rm -rf /tmp/scratch", "cwd": "/tmp"}})
    if status:
        return status
    assert session_id is not None and response is not None
    result = response.get("result")
    if not isinstance(result, dict) or result.get("outcome") != {"outcome": "selected", "optionId": "reject-once"}:
        return 6
    write_session_update(session_id, {"sessionUpdate": "agent_message_chunk", "messageId": "message-permission-ack", "content": {"type": "text", "text": "Permission request was declined."}})
    return 0


def run_permission_request_unsupported_action_mode() -> int:
    status, _, response = _request_permission("fixture-permission-unsupported-1", {"title": "Continue with elevated permissions?", "options": [{"optionId": "allow-once", "name": "Allow", "kind": "allow_once"}]})
    return status if status else (0 if isinstance(response and response.get("error"), dict) and response["error"].get("code") == -32601 else 6)


def run_permission_request_malformed_session_mode() -> int:
    status, _, response = _request_permission("fixture-permission-malformed-session-1", {"sessionId": "not-the-bound-session", "title": "Approve this operation?", "options": [{"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}]})
    return status if status else (0 if isinstance(response and response.get("error"), dict) and response["error"].get("code") == -32602 else 6)


def run_permission_request_malformed_envelope_mode() -> int:
    status, _, response = _request_permission("fixture-permission-malformed-envelope-1", {"options": [{"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}]})
    return status if status else (0 if isinstance(response and response.get("error"), dict) and response["error"].get("code") == -32602 else 6)


def run_permission_request_duplicate_option_ids_mode() -> int:
    status, _, response = _request_permission("fixture-permission-duplicate-1", {"title": "Approve this operation?", "options": [{"optionId": "dup-1", "name": "Allow", "kind": "allow_once"}, {"optionId": "dup-1", "name": "Reject", "kind": "reject_once"}]})
    return status if status else (0 if isinstance(response and response.get("error"), dict) and response["error"].get("code") == -32602 else 6)


def run_permission_request_activation_round_trip_mode() -> int:
    status, session_id, response = _request_permission("fixture-permission-activation-1", {"title": "Run `rm -rf /tmp/scratch`?", "description": "The agent wants to delete a scratch directory.", "options": _permission_options(), "subject": {"type": "command", "command": "rm -rf /tmp/scratch", "cwd": "/tmp"}})
    if status:
        return status
    assert session_id is not None and response is not None
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("outcome"), dict):
        return 6
    selected_option_id = result["outcome"].get("optionId")
    if result["outcome"].get("outcome") != "selected" or selected_option_id not in {"allow-once", "reject-once"}:
        return 6
    write_session_update(session_id, {"sessionUpdate": "agent_message_chunk", "messageId": "message-permission-activation-ack", "content": {"type": "text", "text": f"Permission request resolved with {selected_option_id}."}})
    return 0


def run_permission_request_before_prompt_response_mode() -> int:
    status, session_id = _initialize_and_session()
    if status:
        return status
    assert session_id is not None
    prompt_request = read_message()
    if prompt_request.get("method") != "session/prompt":
        return 4
    response = send_request_and_read_response(
        "fixture-permission-before-prompt-response-1",
        "session/request_permission",
        {
            "sessionId": session_id,
            "title": "Run `rm -rf /tmp/scratch`?",
            "description": "The agent wants to delete a scratch directory.",
            "options": _permission_options(),
            "subject": {"type": "command", "command": "rm -rf /tmp/scratch", "cwd": "/tmp"},
        },
    )
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("outcome"), dict):
        return 6
    selected_option_id = result["outcome"].get("optionId")
    if result["outcome"].get("outcome") != "selected" or selected_option_id not in {"allow-once", "reject-once"}:
        return 6
    write_message({"jsonrpc": "2.0", "id": prompt_request.get("id"), "result": {}})
    write_session_update(
        session_id,
        {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-permission-before-prompt-response-ack",
            "content": {
                "type": "text",
                "text": f"Permission request resolved with {selected_option_id}.",
            },
        },
    )
    return 0


_MODES: dict[str, Callable[[], int]] = {
    "v1_clean_exit": run_v1_clean_exit_mode,
    "clean_exit": run_clean_exit_mode,
    "persistent_after_prompt": run_persistent_after_prompt_mode,
    "activity_stream": run_activity_stream_mode,
    "elicitation_single_field": run_elicitation_single_field_mode,
    "elicitation_before_prompt_response": run_elicitation_before_prompt_response_mode,
    "elicitation_unsupported_schema": run_elicitation_unsupported_schema_mode,
    "permission_request_denied": run_permission_request_denied_mode,
    "permission_request_unsupported_action": run_permission_request_unsupported_action_mode,
    "permission_request_malformed_session": run_permission_request_malformed_session_mode,
    "permission_request_malformed_envelope": run_permission_request_malformed_envelope_mode,
    "permission_request_duplicate_option_ids": run_permission_request_duplicate_option_ids_mode,
    "permission_request_activation_round_trip": run_permission_request_activation_round_trip_mode,
    "permission_request_before_prompt_response": run_permission_request_before_prompt_response_mode,
    "startup_crash": run_startup_crash_mode,
    "protocol_violation_after_initialize": run_protocol_violation_after_initialize_mode,
    "crash_after_session": run_crash_after_session_mode,
    "protocol_violation_after_prompt": run_protocol_violation_after_prompt_mode,
    "hang_before_initialize": run_hang_before_initialize_mode,
    "ignores_sigterm": run_ignores_sigterm_mode,
    "spawns_child_and_hangs": run_spawns_child_and_hangs_mode,
    "environment_probe": run_environment_probe_mode,
}


def run_fixture(mode: str) -> int:
    """Dispatch the requested deterministic fixture mode."""

    return _MODES.get(mode, lambda: 9)()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse fixture arguments and run exactly one mode."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-mode", choices=tuple(_MODES))
    arguments = parser.parse_args(argv)
    if arguments.fixture_mode is None:
        parser.error("--fixture-mode is required")
    return run_fixture(arguments.fixture_mode)


if __name__ == "__main__":
    raise SystemExit(main())
