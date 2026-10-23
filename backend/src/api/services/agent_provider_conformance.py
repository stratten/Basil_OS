"""Deterministic ACP v2 initialization conformance harness.

This module is test and discovery infrastructure only. It validates Basil's
raw stdio framing against the embedded fixture peer without selecting or
invoking any real external provider. Package 0B may reuse the transport
primitive only after a separately approved local-provider probe plan.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import dataclass
import json
import sys
import time
from typing import Any, Mapping, Sequence


ACP_PROTOCOL_VERSION = 2
HARNESS_INFO = {
    "name": "Basil ACP conformance harness",
    "version": "0.1.0",
}
MAX_STDERR_BYTES = 8_192


class AcpConformanceError(RuntimeError):
    """Base error for a deterministic ACP conformance failure."""


class AcpConformanceProtocolError(AcpConformanceError):
    """The fixture emitted a malformed or incompatible JSON-RPC response."""


class AcpConformanceTimeoutError(AcpConformanceError):
    """The fixture did not produce the required response before the deadline."""


@dataclass(frozen=True)
class AcpInitializeResult:
    """Validated fields returned from an ACP v2 initialize response."""

    protocol_version: int
    capabilities: dict[str, Any]
    agent_info: dict[str, str]
    notifications: tuple[dict[str, Any], ...]
    stderr_text: str


class AcpStdioConformanceProbe:
    """Own one bounded ACP initialize exchange with a local fixture process."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        response_timeout_seconds: float = 1.0,
    ) -> None:
        if not argv or not all(isinstance(argument, str) and argument for argument in argv):
            raise ValueError("argv must contain at least one non-empty string")
        if not 0 < response_timeout_seconds < float("inf"):
            raise ValueError("response_timeout_seconds must be greater than zero")

        self._argv = tuple(argv)
        self._cwd = cwd
        self._response_timeout_seconds = response_timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_bytes = bytearray()
        self._notifications: list[dict[str, Any]] = []
        self._next_request_id = 1
        self._has_started = False
        self._has_initialized = False
        self._lifecycle_lock = asyncio.Lock()

    async def __aenter__(self) -> "AcpStdioConformanceProbe":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    @property
    def stderr_text(self) -> str:
        """Return bounded fixture stderr for diagnostic assertions only."""

        return self._stderr_bytes.decode("utf-8", errors="replace")

    async def start(self) -> None:
        """Start the local fixture process once."""

        async with self._lifecycle_lock:
            if self._has_started:
                raise RuntimeError("ACP conformance probe is already started")

            self._has_started = True
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self._argv,
                    cwd=self._cwd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except BaseException:
                self._has_started = False
                raise
            self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))

    async def initialize(self) -> AcpInitializeResult:
        """Send ACP v2 initialize and validate its one matching response."""

        self._require_process()
        if self._has_initialized:
            raise RuntimeError("ACP conformance probe is already initialized")
        self._has_initialized = True
        response = await self._request(
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "capabilities": {},
                "info": HARNESS_INFO,
            },
        )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise AcpConformanceProtocolError("initialize response result must be an object")

        protocol_version = result.get("protocolVersion")
        if type(protocol_version) is not int or protocol_version != ACP_PROTOCOL_VERSION:
            raise AcpConformanceProtocolError(
                f"expected ACP protocol version {ACP_PROTOCOL_VERSION}, got {protocol_version!r}"
            )

        capabilities = result.get("capabilities")
        if not isinstance(capabilities, Mapping):
            raise AcpConformanceProtocolError("initialize response capabilities must be an object")

        info = result.get("info")
        if (
            not isinstance(info, Mapping)
            or not isinstance(info.get("name"), str)
            or not info.get("name")
            or not isinstance(info.get("version"), str)
            or not info.get("version")
        ):
            raise AcpConformanceProtocolError(
                "initialize response info must contain non-empty name and version strings"
            )

        return AcpInitializeResult(
            protocol_version=protocol_version,
            capabilities=dict(capabilities),
            agent_info={"name": info["name"], "version": info["version"]},
            notifications=tuple(self._notifications),
            stderr_text=self.stderr_text,
        )

    async def close(self) -> None:
        """Terminate the fixture process and await the bounded stderr drainer."""

        async with self._lifecycle_lock:
            process = self._process
            self._process = None
            if process is not None:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        with contextlib.suppress(ProcessLookupError):
                            process.kill()
                        await process.wait()
                else:
                    await process.wait()

            stderr_task = self._stderr_task
            self._stderr_task = None
            if stderr_task is not None:
                if process is None and not stderr_task.done():
                    stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task

    async def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        process = self._require_process()
        if process.stdin is None or process.stdout is None:
            raise AcpConformanceError("fixture process does not expose stdio pipes")

        request_id = self._next_request_id
        self._next_request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        process.stdin.write(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        )
        await process.stdin.drain()

        deadline = time.monotonic() + self._response_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcpConformanceTimeoutError(
                    f"timed out waiting for JSON-RPC response id {request_id}"
                )
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise AcpConformanceTimeoutError(
                    f"timed out waiting for JSON-RPC response id {request_id}"
                ) from exc
            except ValueError as exc:
                raise AcpConformanceProtocolError(
                    "fixture emitted a JSON-RPC line exceeding the stream limit"
                ) from exc

            if not line:
                raise AcpConformanceProtocolError(
                    f"fixture exited before JSON-RPC response id {request_id}: {self.stderr_text!r}"
                )

            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AcpConformanceProtocolError(
                    f"fixture emitted invalid JSON-RPC payload: {line!r}"
                ) from exc

            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise AcpConformanceProtocolError("fixture emitted a non-JSON-RPC-2.0 message")

            if "id" not in message:
                if not isinstance(message.get("method"), str) or not message["method"]:
                    raise AcpConformanceProtocolError(
                        "fixture notification must contain a non-empty method"
                    )
                if "result" in message or "error" in message:
                    raise AcpConformanceProtocolError(
                        "fixture notification must not contain result or error"
                    )
                self._notifications.append(message)
                continue

            if "method" in message:
                raise AcpConformanceProtocolError("fixture response must not contain method")
            if type(message["id"]) is not type(request_id) or message["id"] != request_id:
                raise AcpConformanceProtocolError(
                    f"expected JSON-RPC response id {request_id}, got {message['id']!r}"
                )
            if "error" in message:
                raise AcpConformanceProtocolError(
                    f"fixture returned JSON-RPC error: {message['error']!r}"
                )
            if "result" not in message:
                raise AcpConformanceProtocolError(
                    "fixture response must contain either result or error"
                )
            return message

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return

        while True:
            chunk = await process.stderr.read(1_024)
            if not chunk:
                return
            remaining = MAX_STDERR_BYTES - len(self._stderr_bytes)
            if remaining > 0:
                self._stderr_bytes.extend(chunk[:remaining])

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("ACP conformance probe is not started")
        return self._process


def _write_fixture_message(payload: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(
        json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    )
    sys.stdout.buffer.flush()


def _run_fixture(mode: str) -> int:
    """Run a deterministic local ACP peer for the focused test suite."""

    request_line = sys.stdin.buffer.readline()
    if not request_line:
        return 2
    try:
        request = json.loads(request_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 3

    if request != {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "capabilities": {},
            "info": HARNESS_INFO,
        },
    }:
        return 4

    request_id = request.get("id")
    if mode == "malformed_json":
        sys.stdout.buffer.write(b"{not-json}\n")
        sys.stdout.buffer.flush()
        return 0
    if mode == "oversized_line":
        sys.stdout.buffer.write(b"x" * 70_000 + b"\n")
        sys.stdout.buffer.flush()
        return 0
    if mode == "no_response":
        time.sleep(60)
        return 0
    if mode == "notification_then_no_response":
        _write_fixture_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "fixture-session", "update": "ready"},
            }
        )
        time.sleep(60)
        return 0
    if mode == "notification_then_success":
        _write_fixture_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "fixture-session", "update": "ready"},
            }
        )
    if mode == "stderr_then_success":
        sys.stderr.buffer.write(b"x" * (MAX_STDERR_BYTES + 1_024))
        sys.stderr.buffer.flush()

    response_id = (
        "unexpected-id"
        if mode == "mismatched_id"
        else True
        if mode == "boolean_id"
        else request_id
    )
    protocol_version = (
        1
        if mode == "unsupported_version"
        else 2.0
        if mode == "non_integer_protocol_version"
        else ACP_PROTOCOL_VERSION
    )
    response = {
        "jsonrpc": "2.0",
        "id": response_id,
        "result": {
            "protocolVersion": protocol_version,
            "capabilities": {"session": {}},
            "info": {"name": "Basil ACP fixture", "version": "1.0.0"},
        },
    }
    if mode == "response_with_method":
        response["method"] = "session/update"
    _write_fixture_message(response)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Expose only the deterministic fixture mode for the focused test suite."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-mode",
        choices=(
            "success",
            "notification_then_success",
            "mismatched_id",
            "malformed_json",
            "oversized_line",
            "unsupported_version",
            "no_response",
            "notification_then_no_response",
            "stderr_then_success",
            "non_integer_protocol_version",
            "boolean_id",
            "response_with_method",
        ),
    )
    arguments = parser.parse_args(argv)
    if arguments.fixture_mode is None:
        parser.error("--fixture-mode is required")
    return _run_fixture(arguments.fixture_mode)


if __name__ == "__main__":
    raise SystemExit(main())
