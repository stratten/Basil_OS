"""A shell command that rewrites a file the file tool versions advances that file's managed-history head."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.service import (
    AgentTaskMutations,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.managed_file_history.repository import (
    ManagedFileHistoryRepository,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    AGENT_RUN_STARTED_AT_KEY,
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history import (
    managed_file_history_wiring,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.blob_store import (
    ManagedHistoryBlobStore,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
    ManagedFileHistoryService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
    LocalTextFileWriter,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import (
    ShellService,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest_asyncio.fixture
async def managed_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "managed_file_history.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    await AgentTaskMutations(db_path).store_agent_task(
        agent_task_id="task-shell-hook", original_prompt="prompt", transcribed_prompt="prompt",
    )
    service = ManagedFileHistoryService(
        db_path=db_path,
        blob_store=ManagedHistoryBlobStore(tmp_path / "blobs"),
        text_writer=LocalTextFileWriter([tmp_path]),
    )
    monkeypatch.setattr(
        managed_file_history_wiring, "get_managed_file_history_service", lambda *, text_writer: service
    )
    return db_path, service


async def _run_rewrite(tmp_path: Path, target: Path, text: str) -> dict:
    shell = ShellService()
    shell._home_root = tmp_path.resolve()
    token = set_current_agent_context(
        {
            "root_task_id": "task-shell-hook",
            "agent_task_id": "task-shell-hook",
            AGENT_RUN_STARTED_AT_KEY: time.time() - 5,
        }
    )
    try:
        return await shell.execute_command(
            "bash",
            ["-c", f"printf %s '{text}' > '{target}'"],
            cwd=str(tmp_path),
            skip_approval_check=True,
        )
    finally:
        reset_current_agent_context(token)


@pytest.mark.asyncio
async def test_a_shell_command_rewriting_a_tracked_file_advances_its_head(managed_setup, tmp_path: Path) -> None:
    db_path, service = managed_setup
    target = tmp_path / "tracker.md"
    created = await service.apply_managed_write(
        root_task_id="task-shell-hook", agent_task_id="task-shell-hook", path=str(target), content="v1", mode="create",
    )
    assert created["success"] is True

    result = await _run_rewrite(tmp_path, target, "from-the-shell")

    assert result["success"] is True
    assert target.read_text() == "from-the-shell"
    head = ManagedFileHistoryRepository(db_path).get_head(str(target.resolve()))
    assert head is not None
    assert head["current_sha256"] == _digest("from-the-shell")
    follow_up = await service.apply_managed_write(
        root_task_id="task-shell-hook", agent_task_id="task-shell-hook", path=str(target), content="v3", mode="overwrite",
    )
    assert follow_up["success"] is True


@pytest.mark.asyncio
async def test_a_history_failure_never_changes_the_command_result(
    managed_setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken(*, text_writer):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(managed_file_history_wiring, "get_managed_file_history_service", _broken)
    target = tmp_path / "plain.md"

    result = await _run_rewrite(tmp_path, target, "still written")

    assert result["success"] is True
    assert target.read_text() == "still written"
