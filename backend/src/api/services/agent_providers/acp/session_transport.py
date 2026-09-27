"""Subprocess transport, JSON-RPC framing, and correlation for ACP sessions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from typing import Any, Mapping, Sequence

from .protocol import (
    MAX_JSON_RPC_LINE_BYTES,
    MAX_STDERR_BYTES,
    AcpClientClosedError,
    AcpClientError,
    AcpClientProtocolError,
    AcpClientTimeoutError,
    AcpRemoteRequestError,
    AcpRequestError,
    NotificationHandler,
    RequestHandler,
)


class AcpSessionTransport:
    """Own the ACP subprocess, wire framing, response correlation, and read loop."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: Mapping[str, str] | None,
        start_new_session: bool,
        request_timeout_seconds: float,
    ) -> None:
        self._argv = tuple(argv)
        self._cwd = cwd
        self._env = dict(env) if env is not None else None
        self._start_new_session = start_new_session
        self._request_timeout_seconds = request_timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._last_pid: int | None = None
        self._last_exit_code: int | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_bytes = bytearray()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._pending_incoming: set[str | int] = set()
        self._seen_incoming_request_ids: set[str | int] = set()
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._next_request_id = 1
        self._reader_error: AcpClientError | None = None
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}
        self._has_started = False
        self._lifecycle_lock = asyncio.Lock()

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        return self._process

    @property
    def stderr_text(self) -> str:
        return self._stderr_bytes.decode("utf-8", errors="replace")

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else self._last_pid

    @property
    def exit_code(self) -> int | None:
        return self._process.returncode if self._process is not None else self._last_exit_code

    @property
    def has_exited(self) -> bool:
        return self.exit_code is not None

    @property
    def reader_error(self) -> AcpClientError | None:
        return self._reader_error

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a non-empty string")
        self._request_handlers[method] = handler

    def register_notification_handler(self, method: str, handler: NotificationHandler) -> None:
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a non-empty string")
        self._notification_handlers[method] = handler

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._has_started:
                raise AcpClientError("ACP session client is already started")
            self._has_started = True
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self._argv,
                    cwd=self._cwd,
                    env=self._env,
                    start_new_session=self._start_new_session,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=MAX_JSON_RPC_LINE_BYTES,
                )
            except BaseException:
                self._has_started = False
                raise
            self._last_pid = self._process.pid
            self._reader_task = asyncio.create_task(self._read_loop())
            self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def wait_for_exit(self) -> int:
        process = self._require_process()
        exit_code = await process.wait()
        reader_task = self._reader_task
        if reader_task is not None and reader_task is not asyncio.current_task():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(reader_task)
        if self._reader_error is not None:
            raise self._reader_error
        return exit_code

    async def wait_for_exit_within(self, timeout: float) -> bool:
        process = self._process
        if process is None or process.returncode is not None:
            return True
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def close(self) -> None:
        async with self._lifecycle_lock:
            process = self._process
            if process is not None:
                if process.returncode is None:
                    self._terminate_process_tree(process)
                    try:
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        self._kill_process_tree(process)
                        await process.wait()
                else:
                    await process.wait()
                self._last_pid = process.pid
                self._last_exit_code = process.returncode
            await self._stop_task("_reader_task")
            await self._stop_task("_stderr_task")
            self._process = None
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()
            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
            closed_error = AcpClientClosedError("ACP session client is closed")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(closed_error)
            self._pending.clear()
            self._pending_incoming.clear()
            self._seen_incoming_request_ids.clear()

    async def send_request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if self._reader_error is not None:
            raise self._reader_error
        process = self._require_process()
        if process.stdin is None:
            raise AcpClientError("ACP process does not expose a stdin pipe")
        request_id = self._next_request_id
        self._next_request_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        except BaseException:
            self._pending.pop(request_id, None)
            raise
        try:
            return await asyncio.wait_for(future, timeout=self._request_timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise AcpClientTimeoutError(f"timed out waiting for JSON-RPC response id {request_id}") from exc

    async def send_notification(self, method: str, params: Mapping[str, Any]) -> None:
        if self._reader_error is not None:
            raise self._reader_error
        self._require_process()
        await self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    async def _stop_task(self, attribute: str) -> None:
        task = getattr(self, attribute)
        setattr(self, attribute, None)
        if task is not None:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise AcpClientClosedError("ACP session client is not started or has been closed")
        return self._process

    def _terminate_process_tree(self, process: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(ProcessLookupError):
            if self._start_new_session:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()

    def _kill_process_tree(self, process: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(ProcessLookupError):
            if self._start_new_session:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()

    async def _write(self, payload: Mapping[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise AcpClientError("ACP process does not expose a stdin pipe")
        process.stdin.write(_encode_message(payload))
        await process.stdin.drain()

    async def _read_loop(self) -> None:
        process = self._require_process()
        assert process.stdout is not None
        try:
            while True:
                try:
                    line = await process.stdout.readline()
                except ValueError:
                    self._poison(AcpClientProtocolError("peer emitted a JSON-RPC line exceeding the stream limit"))
                    return
                if not line:
                    exit_code = await process.wait()
                    if self._pending or exit_code != 0:
                        self._poison(AcpClientProtocolError(f"peer closed its stdout with exit code {exit_code}: {self.stderr_text!r}"))
                    return
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._poison(AcpClientProtocolError(f"peer emitted invalid JSON-RPC payload: {line!r}"))
                    return
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    self._poison(AcpClientProtocolError("peer emitted a non-JSON-RPC-2.0 message"))
                    return
                if not await self._dispatch_message(message):
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            self._poison(AcpClientProtocolError(f"ACP read loop failed: {exc!r}"))

    async def _dispatch_message(self, message: dict[str, Any]) -> bool:
        has_id = "id" in message
        has_method = "method" in message
        has_result_or_error = "result" in message or "error" in message
        if not has_id:
            if has_result_or_error:
                return self._fail("peer notification must not contain result or error")
            method = message.get("method")
            params = message.get("params", {})
            if not isinstance(method, str) or not method:
                return self._fail("peer notification must contain a non-empty method")
            if not isinstance(params, Mapping):
                return self._fail("peer notification params must be an object")
            handler = self._notification_handlers.get(method)
            if handler is not None:
                await handler(params)
            return True
        if has_method and has_result_or_error:
            return self._fail("peer message must not contain both method and result/error")
        if has_method:
            method = message.get("method")
            request_id = message["id"]
            params = message.get("params", {})
            if not isinstance(method, str) or not method:
                return self._fail("peer request must contain a non-empty method")
            if type(request_id) not in (int, str):
                return self._fail("peer request id must be a string or non-boolean integer")
            if not isinstance(params, Mapping):
                return self._fail("peer request params must be an object")
            self._dispatch_incoming_request(request_id, method, params)
            return True
        if not has_result_or_error:
            return self._fail("peer message with id must contain method, result, or error")
        if "result" in message and "error" in message:
            return self._fail("peer response must not contain both result and error")
        self._handle_response(message)
        return self._reader_error is None

    def _fail(self, message: str) -> bool:
        self._poison(AcpClientProtocolError(message))
        return False

    def _handle_response(self, message: dict[str, Any]) -> None:
        response_id = message["id"]
        future = self._pending.get(response_id) if type(response_id) is int else None
        if future is None:
            self._poison(AcpClientProtocolError(f"peer sent a response for unknown or already-resolved id {response_id!r}"))
            return
        if future.done():
            self._pending.pop(response_id)
            return
        if "error" in message:
            error = message["error"]
            if not isinstance(error, Mapping) or type(error.get("code")) is not int or not isinstance(error.get("message"), str):
                self._poison(AcpClientProtocolError("peer response error must be a JSON-RPC error object"))
                return
            self._pending.pop(response_id)
            future.set_exception(
                AcpRemoteRequestError(int(error["code"]), str(error["message"]))
            )
            return
        self._pending.pop(response_id)
        future.set_result(message)

    def _dispatch_incoming_request(self, request_id: str | int, method: str, params: Mapping[str, Any]) -> None:
        if request_id in self._seen_incoming_request_ids:
            self._track_background_task(asyncio.create_task(self._write_error_response(request_id, code=-32600, message_text=f"duplicate request id {request_id!r} was already received")))
            return
        self._seen_incoming_request_ids.add(request_id)
        self._pending_incoming.add(request_id)
        self._track_background_task(asyncio.create_task(self._run_incoming_request(request_id, method, params)))

    async def _run_incoming_request(self, request_id: str | int, method: str, params: Mapping[str, Any]) -> None:
        try:
            handler = self._request_handlers.get(method)
            if handler is None:
                await self._write_error_response(request_id, code=-32601, message_text=f"method {method!r} is not supported")
                return
            try:
                result = await handler(params)
            except AcpRequestError as exc:
                await self._write_error_response(request_id, code=exc.code, message_text=exc.message_text)
                return
            except Exception as exc:
                await self._write_error_response(request_id, code=-32603, message_text=f"handler for {method!r} failed: {exc!r}")
                return
            if not isinstance(result, Mapping):
                await self._write_error_response(request_id, code=-32603, message_text=f"handler for {method!r} returned a non-object result")
                return
            await self._write({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})
        finally:
            self._pending_incoming.discard(request_id)

    async def _write_error_response(self, request_id: Any, *, code: int, message_text: str) -> None:
        if self._reader_error is None and self._process is not None:
            await self._write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message_text}})

    def _track_background_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._handle_background_task_completion)

    def _handle_background_task_completion(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self._poison(AcpClientProtocolError(f"ACP incoming request handling failed: {error!r}"))

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while chunk := await process.stderr.read(1_024):
            remaining = MAX_STDERR_BYTES - len(self._stderr_bytes)
            if remaining > 0:
                self._stderr_bytes.extend(chunk[:remaining])

    def _poison(self, error: AcpClientError) -> None:
        if self._reader_error is None:
            self._reader_error = error
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()


def _encode_message(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
