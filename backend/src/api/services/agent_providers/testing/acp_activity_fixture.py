"""Deterministic ACP activity fixture peer for inactivity-timeout tests.

Test infrastructure only. It reads one JSON-RPC request from stdin and then, per ``--fixture-mode``, emits a scripted pattern of ``session/update`` notifications before (or instead of) answering it. It never selects or invokes any real external provider.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Mapping, Sequence

MODES = ("steady_activity", "silent", "open_tool_call_silence", "endless_activity")


def _read_message() -> dict[str, Any]:
    line = sys.stdin.buffer.readline()
    if not line:
        raise EOFError("fixture stdin closed before an expected message")
    return json.loads(line.decode("utf-8"))


def _write_message(payload: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(
        json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    )
    sys.stdout.buffer.flush()


def _update(session_id: str, update: Mapping[str, Any]) -> None:
    _write_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": session_id, "update": dict(update)},
        }
    )


def _chunk(index: int) -> dict[str, Any]:
    return {
        "sessionUpdate": "agent_message_chunk",
        "messageId": f"message-{index}",
        "content": {"type": "text", "text": f"chunk {index}"},
    }


def _respond(request_id: Any) -> None:
    _write_message({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-mode", required=True, choices=MODES)
    args = parser.parse_args(argv)
    request = _read_message()
    request_id = request.get("id")
    params = request.get("params") if isinstance(request.get("params"), Mapping) else {}
    session_id = str(params.get("sessionId") or "fixture-session")
    mode = args.fixture_mode
    if mode == "steady_activity":
        for index in range(6):
            time.sleep(0.2)
            _update(session_id, _chunk(index))
        _respond(request_id)
        return 0
    if mode == "silent":
        time.sleep(30)
        _respond(request_id)
        return 0
    if mode == "open_tool_call_silence":
        _update(
            session_id,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tool-1",
                "title": "Run tests",
                "kind": "execute",
                "status": "in_progress",
            },
        )
        time.sleep(1.0)
        _update(session_id, {"sessionUpdate": "tool_call_update", "toolCallId": "tool-1", "status": "completed"})
        _respond(request_id)
        return 0
    index = 0
    while True:
        time.sleep(0.1)
        _update(session_id, _chunk(index))
        index += 1


if __name__ == "__main__":
    raise SystemExit(main())
