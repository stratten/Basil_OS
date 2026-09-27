"""Data model for one local web preview dev-server session."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal, Optional

LocalPreviewSessionStatus = Literal["starting", "running", "stopped", "error", "denied"]


@dataclass
class LocalPreviewSession:
    """In-memory record of one approved local dev-server preview session.

    Not durable: does not survive a backend restart. `stdout_tail` and
    `stderr_tail` are bounded ring-buffer strings, never the full process
    output, and exist only as evidence for why a session failed to start.
    """

    session_id: str
    agent_task_id: str
    artifact_id: str
    command: str
    args: list[str]
    cwd: str
    host: str
    port: int
    status: LocalPreviewSessionStatus
    pid: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    stopped_at: Optional[float] = None
    last_error: Optional[str] = None
    stdout_tail: str = ""
    stderr_tail: str = ""

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dto(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_task_id": self.agent_task_id,
            "artifact_id": self.artifact_id,
            "status": self.status,
            "url": self.url,
            "host": self.host,
            "port": self.port,
            "pid": self.pid,
            "last_error": self.last_error,
            "command": self.command,
            "args": self.args,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "stopped_at": self.stopped_at,
        }
