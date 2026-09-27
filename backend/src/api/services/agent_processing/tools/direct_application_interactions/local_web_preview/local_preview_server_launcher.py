"""Approval-gated launcher for local dev-server preview sessions.

Reuses `ExecutionApprovalService` (the same interactive-approval path shell
commands use) to gate starting a server, then supervises it as a
non-blocking background process — unlike `ShellService.execute_command`,
which always awaits process exit under a hard timeout and is unsuitable for
a server that runs indefinitely.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
import uuid
from typing import List, Optional

from api.core.runtime.validation_profile import (
    ValidationRuntimeProfile,
    is_validation_runtime,
)
from api.services.agent_processing.tools.safety import ExecutionApprovalService
from ..shared.cwd_allowlist import detect_repo_root, home_root, resolve_and_validate_cwd
from .local_preview_session import LocalPreviewSession
from .local_preview_session_registry import LocalPreviewSessionRegistry

logger = logging.getLogger(__name__)

_MAX_TAIL_CHARS = 4_000
_READY_POLL_INTERVAL_S = 0.25
_READY_POLL_TIMEOUT_S = 10.0
_LOOPBACK_HOST = "127.0.0.1"


class LocalPreviewServerLauncher:
    def __init__(self, registry: LocalPreviewSessionRegistry, websocket_manager=None) -> None:
        self._registry = registry
        self._websocket_manager = websocket_manager
        self._repo_root = detect_repo_root()
        self._home_root = home_root()

    async def start_session(
        self,
        *,
        agent_task_id: str,
        artifact_id: str,
        command: str,
        args: Optional[List[str]],
        cwd: str,
        host: str = "127.0.0.1",
        port: int,
    ) -> LocalPreviewSession:
        argv = [command] + (args or [])
        full_command = " ".join(shlex.quote(a) for a in argv)
        session_id = str(uuid.uuid4())

        if host != _LOOPBACK_HOST:
            return self._error_session(
                session_id=session_id,
                agent_task_id=agent_task_id,
                artifact_id=artifact_id,
                command=command,
                args=args,
                cwd=cwd,
                host=host,
                port=port,
                error="Local preview servers must use 127.0.0.1.",
            )
        if not command.strip():
            return self._error_session(
                session_id=session_id,
                agent_task_id=agent_task_id,
                artifact_id=artifact_id,
                command=command,
                args=args,
                cwd=cwd,
                host=host,
                port=port,
                error="A preview-server command is required.",
            )
        if not 1 <= port <= 65_535:
            return self._error_session(
                session_id=session_id,
                agent_task_id=agent_task_id,
                artifact_id=artifact_id,
                command=command,
                args=args,
                cwd=cwd,
                host=host,
                port=port,
                error="Preview-server port must be between 1 and 65535.",
            )

        allowed_roots = (self._home_root, self._repo_root)
        if is_validation_runtime():
            allowed_roots += (ValidationRuntimeProfile.from_environment().session_root,)
        safe_cwd, cwd_error = resolve_and_validate_cwd(cwd, allowed_roots=allowed_roots)
        if cwd_error:
            return self._error_session(
                session_id=session_id,
                agent_task_id=agent_task_id,
                artifact_id=artifact_id,
                command=command,
                args=args,
                cwd=cwd,
                host=host,
                port=port,
                error=cwd_error,
            )

        approval_service = ExecutionApprovalService(websocket_manager=self._websocket_manager)
        approval_outcome = await approval_service.request_approval_with_outcome(
            full_command,
            context={
                "cwd": str(safe_cwd),
                "source": "local_web_preview",
                "description": f"Start local preview server on port {port}: {full_command}",
                "agent_task_id": agent_task_id,
            },
        )
        if not approval_outcome.approved:
            session = LocalPreviewSession(
                session_id=session_id, agent_task_id=agent_task_id, artifact_id=artifact_id,
                command=command, args=args or [], cwd=str(safe_cwd), host=host, port=port,
                status="denied", last_error=approval_outcome.reason,
            )
            self._registry.put(session, None)
            return session

        existing_session_id = self._registry.get_active_session_id_for_artifact(agent_task_id, artifact_id)
        if existing_session_id:
            await self.stop_session(existing_session_id)

        session = LocalPreviewSession(
            session_id=session_id, agent_task_id=agent_task_id, artifact_id=artifact_id,
            command=command, args=args or [], cwd=str(safe_cwd), host=host, port=port,
            status="starting",
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=str(safe_cwd), env=os.environ.copy(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            session.status = "error"
            session.last_error = (
                f"Executable not found: {shlex.quote(command)}"
                if isinstance(exc, FileNotFoundError)
                else f"Could not start preview server: {exc}"
            )
            self._registry.put(session, None)
            return session

        session.pid = process.pid
        self._registry.put(session, process)
        asyncio.create_task(self._drain_output(session_id, process))
        ready = await self._wait_until_listening(host, port)
        current = self._registry.get(session_id)
        if current is None:
            return session
        if ready:
            current.status = "running"
        elif current.status == "starting":
            current.status = "error"
            current.last_error = f"Server did not start listening on {host}:{port} within {_READY_POLL_TIMEOUT_S:.0f}s."
            await self._terminate_process(session_id, process)
        return current

    def _error_session(
        self,
        *,
        session_id: str,
        agent_task_id: str,
        artifact_id: str,
        command: str,
        args: Optional[List[str]],
        cwd: str,
        host: str,
        port: int,
        error: str,
    ) -> LocalPreviewSession:
        session = LocalPreviewSession(
            session_id=session_id,
            agent_task_id=agent_task_id,
            artifact_id=artifact_id,
            command=command,
            args=args or [],
            cwd=cwd,
            host=host,
            port=port,
            status="error",
            last_error=error,
        )
        self._registry.put(session, None)
        return session

    async def stop_session(self, session_id: str) -> Optional[LocalPreviewSession]:
        session = self._registry.get(session_id)
        if session is None:
            return None
        process = self._registry.get_process(session_id)
        if process is not None:
            await self._terminate_process(session_id, process)
        session.status = "stopped"
        session.stopped_at = time.time()
        self._registry.remove_process(session_id)
        return session

    async def stop_all_sessions(self) -> None:
        for session in list(self._registry.all_active_sessions()):
            await self.stop_session(session.session_id)

    async def _terminate_process(self, session_id: str, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._registry.remove_process(session_id)

    async def _drain_output(self, session_id: str, process: asyncio.subprocess.Process) -> None:
        async def _drain(stream: asyncio.StreamReader, attr: str) -> None:
            while True:
                chunk = await stream.read(1024)
                if not chunk:
                    break
                session = self._registry.get(session_id)
                if session is None:
                    continue
                text = getattr(session, attr) + chunk.decode("utf-8", errors="replace")
                setattr(session, attr, text[-_MAX_TAIL_CHARS:])

        if process.stdout is not None:
            asyncio.create_task(_drain(process.stdout, "stdout_tail"))
        if process.stderr is not None:
            asyncio.create_task(_drain(process.stderr, "stderr_tail"))
        await process.wait()
        session = self._registry.get(session_id)
        if session is not None and session.status in ("starting", "running"):
            session.status = "error" if process.returncode != 0 else "stopped"
            session.stopped_at = time.time()
            if process.returncode != 0:
                session.last_error = f"Server process exited with code {process.returncode}."
        self._registry.remove_process(session_id)

    async def _wait_until_listening(self, host: str, port: int) -> bool:
        deadline = time.time() + _READY_POLL_TIMEOUT_S
        while time.time() < deadline:
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.0)
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                await asyncio.sleep(_READY_POLL_INTERVAL_S)
        return False
