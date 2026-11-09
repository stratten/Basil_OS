"""Durable storage for tool results too large to place in the conversation.

A result is written to a hidden folder inside the task chain's scratch workspace, so every turn of the chain can read it back, and it is removed after the retention period.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
from api.services.agent_processing.tools.direct_application_interactions.shared import agent_task_workspace

logger = logging.getLogger(__name__)

STORE_DIRECTORY_NAME = ".tool_results"
RETENTION_DAYS = 14
_RESULT_ID_PATTERN = re.compile(r"^r-[0-9a-f]{8}$")


def current_chain_id() -> Optional[str]:
    """The root task id of the running task chain, or None outside an agent run."""
    context = get_current_agent_context()
    chain_id = context.get("root_task_id") or context.get("agent_task_id")
    return str(chain_id) if chain_id else None


def _store_directory(create: bool) -> Optional[Path]:
    chain_id = current_chain_id()
    if chain_id is None:
        return None
    workspace = agent_task_workspace.resolve_agent_task_workspace(chain_id, create=create)
    directory = workspace / STORE_DIRECTORY_NAME
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_result(text: str) -> Optional[Dict[str, Any]]:
    """Write one result and return its id, absolute path, workspace-relative file name, and size, or None when there is no task chain or the write fails."""
    partial: Optional[Path] = None
    try:
        directory = _store_directory(create=True)
        if directory is None:
            return None
        result_id = f"r-{uuid.uuid4().hex[:8]}"
        target = directory / f"{result_id}.txt"
        partial = directory / f".{result_id}.partial"
        partial.write_text(text, encoding="utf-8", errors="replace")
        os.replace(partial, target)
        return {"result_id": result_id, "path": str(target), "file": f"{STORE_DIRECTORY_NAME}/{result_id}.txt", "size_chars": len(text)}
    except Exception as exc:
        logger.warning("Could not store an oversized tool result: %s", exc)
        if partial is not None:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        return None


def load_result(result_id: str) -> Optional[str]:
    """Read a stored result of the current task chain, or None when the id is malformed, unknown, or belongs to another chain."""
    if not isinstance(result_id, str):
        return None
    cleaned = result_id.strip()
    if not _RESULT_ID_PATTERN.match(cleaned):
        return None
    try:
        directory = _store_directory(create=False)
        if directory is None:
            return None
        target = directory / f"{cleaned}.txt"
        return target.read_text(encoding="utf-8") if target.is_file() else None
    except Exception as exc:
        logger.warning("Could not read stored result %s: %s", cleaned, exc)
        return None


def sweep_expired(max_age_days: int = RETENTION_DAYS, *, now: Optional[float] = None) -> int:
    """Delete stored results older than the retention period from every chain's workspace and return how many files were removed."""
    cutoff = (time.time() if now is None else now) - max_age_days * 86400
    removed = 0
    try:
        root = agent_task_workspace.agent_task_workspaces_root()
        directories = list(root.glob(f"*/{STORE_DIRECTORY_NAME}")) if root.is_dir() else []
    except OSError as exc:
        logger.warning("Could not list stored tool results for cleanup: %s", exc)
        return 0
    for directory in directories:
        try:
            entries = list(directory.iterdir())
        except OSError as exc:
            logger.debug("Could not list %s: %s", directory, exc)
            continue
        for entry in entries:
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError as exc:
                logger.debug("Could not remove %s: %s", entry, exc)
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed
