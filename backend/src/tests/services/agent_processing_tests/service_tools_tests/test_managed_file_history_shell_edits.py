"""Managed history re-baselines tracked files that a shell command rewrote during the agent run."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

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
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.blob_store import (
    ManagedHistoryBlobStore,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
    ManagedFileHistoryService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
    LocalTextFileWriter,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "managed_file_history.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    return db_path


@pytest.fixture
def service(temp_db_path: str, tmp_path: Path) -> ManagedFileHistoryService:
    return ManagedFileHistoryService(
        db_path=temp_db_path,
        blob_store=ManagedHistoryBlobStore(tmp_path / "blobs"),
        text_writer=LocalTextFileWriter([tmp_path]),
    )


async def _seed_task(temp_db_path: str, task_id: str) -> None:
    await AgentTaskMutations(temp_db_path).store_agent_task(
        agent_task_id=task_id,
        original_prompt="prompt",
        transcribed_prompt="prompt",
    )


async def _create(service: ManagedFileHistoryService, task_id: str, target: Path, content: str) -> None:
    created = await service.apply_managed_write(
        root_task_id=task_id, agent_task_id=task_id, path=str(target), content=content, mode="create",
    )
    assert created["success"] is True


@pytest.mark.asyncio
async def test_a_shell_rewrite_inside_the_run_window_advances_the_head_and_unblocks_the_next_managed_write(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-shell")
    target = tmp_path / "doc.md"
    run_started_at = time.time() - 5
    await _create(service, "task-shell", target, "v1")

    target.write_text("rewritten by a script")

    recorded = await service.record_shell_edits(
        root_task_id="task-shell", agent_task_id="task-shell", run_started_at=run_started_at,
    )

    assert recorded == [str(target.resolve())]
    head = ManagedFileHistoryRepository(temp_db_path).get_head(str(target.resolve()))
    assert head is not None
    assert head["current_sha256"] == _digest("rewritten by a script")
    versions = await service.list_versions(str(target.resolve()))
    assert len(versions) == 2
    assert versions[0]["operation"] == "overwrite"
    assert versions[0]["origin"] == "model"
    assert versions[0]["pre_image_sha256"] == _digest("v1")
    assert versions[0]["post_image_sha256"] == _digest("rewritten by a script")

    follow_up = await service.apply_managed_write(
        root_task_id="task-shell", agent_task_id="task-shell", path=str(target), content="v3", mode="overwrite",
    )
    assert follow_up["success"] is True
    assert target.read_text() == "v3"


@pytest.mark.asyncio
async def test_an_edit_older_than_the_run_window_stays_drift(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-old")
    target = tmp_path / "old.md"
    await _create(service, "task-old", target, "v1")
    target.write_text("edited long ago")
    long_ago = time.time() - 3600
    os.utime(target, (long_ago, long_ago))

    recorded = await service.record_shell_edits(
        root_task_id="task-old", agent_task_id="task-old", run_started_at=time.time() - 5,
    )

    assert recorded == []
    head = ManagedFileHistoryRepository(temp_db_path).get_head(str(target.resolve()))
    assert head is not None
    assert head["current_sha256"] == _digest("v1")
    result = await service.apply_managed_write(
        root_task_id="task-old", agent_task_id="task-old", path=str(target), content="v2", mode="overwrite",
    )
    assert result["error_type"] == "managed_history_drift"


@pytest.mark.asyncio
async def test_a_file_a_command_did_not_change_records_nothing(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-unchanged")
    target = tmp_path / "same.md"
    run_started_at = time.time() - 5
    await _create(service, "task-unchanged", target, "v1")
    target.write_text("v1")

    recorded = await service.record_shell_edits(
        root_task_id="task-unchanged", agent_task_id="task-unchanged", run_started_at=run_started_at,
    )

    assert recorded == []
    assert len(await service.list_versions(str(target.resolve()))) == 1


@pytest.mark.asyncio
async def test_a_deleted_tracked_file_is_skipped_without_failing_the_others(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-mixed")
    gone = tmp_path / "a-gone.md"
    kept = tmp_path / "b-kept.md"
    run_started_at = time.time() - 5
    await _create(service, "task-mixed", gone, "gone v1")
    await _create(service, "task-mixed", kept, "kept v1")
    gone.unlink()
    kept.write_text("kept rewritten")

    recorded = await service.record_shell_edits(
        root_task_id="task-mixed", agent_task_id="task-mixed", run_started_at=run_started_at,
    )

    assert recorded == [str(kept.resolve())]


@pytest.mark.asyncio
async def test_files_tracked_only_under_another_root_task_are_not_touched(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-owner")
    await _seed_task(temp_db_path, "task-other")
    target = tmp_path / "owned.md"
    run_started_at = time.time() - 5
    await _create(service, "task-owner", target, "v1")
    target.write_text("rewritten")

    recorded = await service.record_shell_edits(
        root_task_id="task-other", agent_task_id="task-other", run_started_at=run_started_at,
    )

    assert recorded == []
    head = ManagedFileHistoryRepository(temp_db_path).get_head(str(target.resolve()))
    assert head is not None
    assert head["current_sha256"] == _digest("v1")
