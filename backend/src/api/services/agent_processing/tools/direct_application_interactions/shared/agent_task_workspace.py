"""Per-agent-task scratch workspace directory.

Every agent task run gets a small workspace folder under Basil's storage
root for scripts, intermediate files, and other scratch content the agent
generates while getting the job done -- regardless of whether the task also
reads or writes real files elsewhere via absolute paths. Giving shell
commands a stable, pre-existing default location for this kind of work is
what keeps the model from inventing ad hoc scratch folders on the Desktop or
elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

from api.core.config.api_settings import settings

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]")
_MAX_ID_LENGTH = 128


def _sanitize_task_id(task_id: str) -> str:
    sanitized = _SAFE_ID_PATTERN.sub("_", task_id.strip())[:_MAX_ID_LENGTH]
    return sanitized or "unknown"


def agent_task_workspaces_root() -> Path:
    """Parent directory holding every agent task's scratch workspace."""
    return settings.STORAGE_DIR / "agent_task_workspaces"


def resolve_agent_task_workspace(task_id: str, *, create: bool = True) -> Path:
    """Return this task's scratch workspace, keyed by root task id.

    Callers should pass the root task id when available so every follow-up
    turn in one conversation shares a single workspace; falling back to the
    agent task id is fine for single-turn tasks (root == agent task id).
    """
    workspace = agent_task_workspaces_root() / _sanitize_task_id(task_id)
    if create:
        workspace.mkdir(parents=True, exist_ok=True)
    return workspace
