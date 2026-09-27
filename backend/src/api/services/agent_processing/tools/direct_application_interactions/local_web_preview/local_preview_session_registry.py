"""Process-lifetime registry of active local web preview sessions."""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

from .local_preview_session import LocalPreviewSession


class LocalPreviewSessionRegistry:
    """Holds session metadata and the live subprocess handle for each session.

    Deliberately in-memory only: a backend restart clears this registry and
    orphaned dev-server processes are terminated by the shutdown hook
    registered in `backend/src/api/dependencies.py` (Slice 6.3), not by
    recovery on the next startup.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, LocalPreviewSession] = {}
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._artifact_sessions: Dict[tuple[str, str], str] = {}  # (agent_task_id, artifact_id) -> session_id

    def put(self, session: LocalPreviewSession, process: Optional[asyncio.subprocess.Process]) -> None:
        self._sessions[session.session_id] = session
        if process is not None:
            self._processes[session.session_id] = process
            self._artifact_sessions[(session.agent_task_id, session.artifact_id)] = session.session_id

    def get(self, session_id: str) -> Optional[LocalPreviewSession]:
        return self._sessions.get(session_id)

    def get_process(self, session_id: str) -> Optional[asyncio.subprocess.Process]:
        return self._processes.get(session_id)

    def get_active_session_id_for_artifact(self, agent_task_id: str, artifact_id: str) -> Optional[str]:
        session_id = self._artifact_sessions.get((agent_task_id, artifact_id))
        if session_id is None:
            return None
        session = self._sessions.get(session_id)
        process = self._processes.get(session_id)
        if session is None or process is None or process.returncode is not None:
            return None
        return session_id

    def remove_process(self, session_id: str) -> None:
        self._processes.pop(session_id, None)

    def all_active_sessions(self) -> list[LocalPreviewSession]:
        return [
            session
            for session_id, session in self._sessions.items()
            if (process := self._processes.get(session_id)) is not None and process.returncode is None
        ]
