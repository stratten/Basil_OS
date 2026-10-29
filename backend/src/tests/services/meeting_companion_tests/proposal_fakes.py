"""A fake To-Do launcher for proposal tests: records calls, can fail on demand and can be held open."""

import asyncio
from typing import Any, Dict, List, Optional, Sequence


class FakeLauncher:
    def __init__(self) -> None:
        self.created: List[Dict[str, Any]] = []
        self.launched: List[str] = []
        self.references: List[Dict[str, Any]] = []
        self.create_error: Optional[Exception] = None
        self.launch_error: Optional[Exception] = None
        self.gate: Optional["asyncio.Event"] = None

    async def create_todo(
        self, *, session_key: str, proposal_id: str, title: str, description: str, excerpt: str, responsibility: str, system_created: bool,
    ) -> str:
        if self.gate is not None:
            await self.gate.wait()
        if self.create_error is not None:
            raise self.create_error
        self.created.append(
            {
                "session_key": session_key,
                "proposal_id": proposal_id,
                "title": title,
                "description": description,
                "excerpt": excerpt,
                "responsibility": responsibility,
                "system_created": system_created,
            }
        )
        return f"todo-{len(self.created)}"

    async def launch_worker(self, todo_id: str) -> str:
        if self.launch_error is not None:
            raise self.launch_error
        self.launched.append(todo_id)
        return f"task-{len(self.launched)}"

    async def attach_references(self, todo_id: str, paths: Sequence[str]) -> None:
        self.references.append({"todo_id": todo_id, "paths": list(paths)})
