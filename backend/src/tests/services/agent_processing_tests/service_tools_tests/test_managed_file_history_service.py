"""Managed file-history service: apply/restore/conflict/bounds/eligibility."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.service import (
    AgentTaskMutations,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.managed_file_history.repository import (
    ManagedFileHistoryRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.managed_file_history.migrations import (
    migrate_managed_file_history_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.blob_store import (
    ManagedHistoryBlobStore,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
    ManagedFileHistoryService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history import (
    managed_file_history_service as managed_history_service_module,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
    LocalTextFileWriter,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "managed_file_history.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    return db_path


@pytest.fixture
def service(temp_db_path: str, tmp_path: Path) -> ManagedFileHistoryService:
    blob_root = tmp_path / "blobs"
    return ManagedFileHistoryService(
        db_path=temp_db_path,
        blob_store=ManagedHistoryBlobStore(blob_root),
        text_writer=LocalTextFileWriter([tmp_path]),
    )


async def _seed_task(temp_db_path: str, task_id: str) -> None:
    mutations = AgentTaskMutations(temp_db_path)
    await mutations.store_agent_task(
        agent_task_id=task_id,
        original_prompt="prompt",
        transcribed_prompt="prompt",
    )


@pytest.mark.asyncio
async def test_create_then_overwrite_is_versioned(service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path) -> None:
    await _seed_task(temp_db_path, "task-1")
    target = tmp_path / "report.md"

    created = await service.apply_managed_write(
        root_task_id="task-1", agent_task_id="task-1", path=str(target), content="v1", mode="create",
    )
    assert created["success"] is True

    overwritten = await service.apply_managed_write(
        root_task_id="task-1", agent_task_id="task-1", path=str(target), content="v2", mode="overwrite",
    )
    assert overwritten["success"] is True
    assert target.read_text() == "v2"

    versions = await service.list_versions(str(target.resolve()))
    assert len(versions) == 2
    assert versions[0]["operation"] == "overwrite"
    assert versions[1]["operation"] == "create"


@pytest.mark.asyncio
async def test_overwrite_without_create_bootstraps_baseline(service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path) -> None:
    await _seed_task(temp_db_path, "task-2")
    target = tmp_path / "existing.txt"
    target.write_text("pre-existing")

    result = await service.apply_managed_write(
        root_task_id="task-2", agent_task_id="task-2", path=str(target), content="managed now", mode="overwrite",
    )
    assert result["success"] is True
    assert target.read_text() == "managed now"


@pytest.mark.asyncio
async def test_external_modification_causes_conflict_not_silent_overwrite(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-3")
    target = tmp_path / "drift.txt"
    await service.apply_managed_write(root_task_id="task-3", agent_task_id="task-3", path=str(target), content="v1", mode="create")

    target.write_text("modified outside managed history")

    result = await service.apply_managed_write(
        root_task_id="task-3", agent_task_id="task-3", path=str(target), content="v2", mode="overwrite",
    )
    assert result["success"] is False
    assert result["error_type"] == "managed_history_drift"
    assert target.read_text() == "modified outside managed history"


@pytest.mark.asyncio
async def test_caller_stale_digest_is_preserved_and_does_not_create_history(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-stale")
    target = tmp_path / "caller-stale.txt"
    await service.apply_managed_write(
        root_task_id="task-stale", agent_task_id="task-stale", path=str(target), content="v1", mode="create",
    )

    result = await service.apply_managed_write(
        root_task_id="task-stale",
        agent_task_id="task-stale",
        path=str(target),
        content="must not replace v1",
        mode="overwrite",
        expected_sha256="0" * 64,
    )

    assert result["success"] is False
    assert result["error_type"] == "stale_target"
    assert target.read_text() == "v1"
    assert len(await service.list_versions(str(target.resolve()))) == 1


@pytest.mark.asyncio
async def test_drift_conflict_releases_the_unapplied_preimage_blob(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-blob-cleanup")
    target = tmp_path / "drift-cleanup.txt"
    await service.apply_managed_write(
        root_task_id="task-blob-cleanup", agent_task_id="task-blob-cleanup", path=str(target), content="v1", mode="create",
    )
    target.write_text("outside change")

    result = await service.apply_managed_write(
        root_task_id="task-blob-cleanup", agent_task_id="task-blob-cleanup", path=str(target), content="v2", mode="overwrite",
    )

    assert result["error_type"] == "managed_history_drift"
    with get_sync_connection(temp_db_path) as conn:
        rows = conn.execute(
            "SELECT ref_count FROM managed_file_blobs WHERE ref_count > 0"
        ).fetchall()
    assert [row["ref_count"] for row in rows] == [1]


@pytest.mark.asyncio
async def test_restore_version_requires_no_approval_and_marks_displaced_reverted(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-4")
    target = tmp_path / "restorable.txt"
    await service.apply_managed_write(root_task_id="task-4", agent_task_id="task-4", path=str(target), content="v1", mode="create")
    await service.apply_managed_write(root_task_id="task-4", agent_task_id="task-4", path=str(target), content="v2", mode="overwrite")

    versions = await service.list_versions(str(target.resolve()))
    v1_change_id = versions[1]["id"]

    restore = await service.restore_version(
        root_task_id="task-4", canonical_path=str(target.resolve()), restores_change_id=v1_change_id,
    )
    assert restore["success"] is True
    assert target.read_text() == "v1"

    versions_after = await service.list_versions(str(target.resolve()))
    assert versions_after[0]["operation"] == "rollback"
    assert versions_after[0]["origin"] == "user"
    assert {version["id"] for version in versions_after} >= {v1_change_id, versions[0]["id"]}


@pytest.mark.asyncio
async def test_rollback_of_a_rollback_restores_the_displaced_version(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-round-trip")
    target = tmp_path / "round-trip.txt"
    await service.apply_managed_write(
        root_task_id="task-round-trip", agent_task_id="task-round-trip", path=str(target), content="v1", mode="create",
    )
    await service.apply_managed_write(
        root_task_id="task-round-trip", agent_task_id="task-round-trip", path=str(target), content="v2", mode="overwrite",
    )
    versions = await service.list_versions(str(target.resolve()))
    v2_change_id = versions[0]["id"]
    v1_change_id = versions[1]["id"]
    await service.restore_version(
        root_task_id="task-round-trip", canonical_path=str(target.resolve()), restores_change_id=v1_change_id,
    )

    restored = await service.restore_version(
        root_task_id="task-round-trip", canonical_path=str(target.resolve()), restores_change_id=v2_change_id,
    )

    assert restored["success"] is True
    assert target.read_text() == "v2"


@pytest.mark.asyncio
async def test_restore_rejects_a_change_from_another_root_task(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-owner")
    await _seed_task(temp_db_path, "task-other")
    target = tmp_path / "root-bound.txt"
    await service.apply_managed_write(
        root_task_id="task-owner", agent_task_id="task-owner", path=str(target), content="v1", mode="create",
    )
    version_id = (await service.list_versions(str(target.resolve())))[0]["id"]

    result = await service.restore_version(
        root_task_id="task-other", canonical_path=str(target.resolve()), restores_change_id=version_id,
    )

    assert result["success"] is False
    assert target.read_text() == "v1"


@pytest.mark.asyncio
async def test_restart_reconciliation_releases_prepared_preimage_references(
    temp_db_path: str,
) -> None:
    await _seed_task(temp_db_path, "task-recovery")
    repository = ManagedFileHistoryRepository(temp_db_path)
    repository.upsert_blob_ref("a" * 64, 1)
    prepared = repository.prepare_change(
        root_task_id="task-recovery",
        agent_task_id="task-recovery",
        canonical_path="/tmp/recovery.txt",
        operation="overwrite",
        origin="model",
        pre_image_sha256="a" * 64,
        pre_image_size_bytes=1,
        expected_precondition_sha256="a" * 64,
    )

    with get_sync_connection(temp_db_path) as conn:
        migrate_managed_file_history_tables(conn)
        conn.commit()

    reconciled = repository.get_change(prepared["id"])
    assert reconciled is not None
    assert reconciled["state"] == "failed"
    with get_sync_connection(temp_db_path) as conn:
        blob = conn.execute(
            "SELECT ref_count, pending_deletion FROM managed_file_blobs WHERE sha256 = ?",
            ("a" * 64,),
        ).fetchone()
    assert blob["ref_count"] == 0
    assert blob["pending_deletion"] == 1


@pytest.mark.asyncio
async def test_restore_conflicts_on_drift_and_does_not_write(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-5")
    target = tmp_path / "drift-restore.txt"
    await service.apply_managed_write(root_task_id="task-5", agent_task_id="task-5", path=str(target), content="v1", mode="create")
    await service.apply_managed_write(root_task_id="task-5", agent_task_id="task-5", path=str(target), content="v2", mode="overwrite")
    versions = await service.list_versions(str(target.resolve()))
    v1_change_id = versions[1]["id"]

    target.write_text("modified outside managed history right before restore")

    restore = await service.restore_version(
        root_task_id="task-5", canonical_path=str(target.resolve()), restores_change_id=v1_change_id,
    )
    assert restore["success"] is False
    assert restore["error_type"] == "managed_history_drift"
    assert target.read_text() == "modified outside managed history right before restore"


@pytest.mark.asyncio
async def test_ineligible_path_falls_back_to_plain_write_and_is_not_versioned(
    service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path,
) -> None:
    await _seed_task(temp_db_path, "task-6")
    hidden_dir = tmp_path / ".config"
    hidden_dir.mkdir()
    target = hidden_dir / "settings.txt"

    result = await service.apply_managed_write(
        root_task_id="task-6", agent_task_id="task-6", path=str(target), content="hidden", mode="create",
    )
    assert result["success"] is True
    assert target.read_text() == "hidden"

    versions = await service.list_versions(str(target.resolve()))
    assert versions == []


@pytest.mark.asyncio
async def test_per_change_bound_rejects_oversized_write(service: ManagedFileHistoryService, temp_db_path: str, tmp_path: Path) -> None:
    await _seed_task(temp_db_path, "task-7")
    target = tmp_path / "big.txt"

    result = await service.apply_managed_write(
        root_task_id="task-7",
        agent_task_id="task-7",
        path=str(target),
        content="x" * (10 * 1024 * 1024 + 1),
        mode="create",
    )
    assert result["success"] is False
    assert result["error_type"] == "managed_history_bounds_exceeded"
    assert not target.exists()


@pytest.mark.asyncio
async def test_task_bound_counts_pre_and_post_images(
    service: ManagedFileHistoryService,
    temp_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_task(temp_db_path, "task-byte-accounting")
    target = tmp_path / "accounting.txt"
    monkeypatch.setattr(managed_history_service_module, "MAX_TASK_BYTES", 5)
    created = await service.apply_managed_write(
        root_task_id="task-byte-accounting",
        agent_task_id="task-byte-accounting",
        path=str(target),
        content="v1",
        mode="create",
    )

    rejected = await service.apply_managed_write(
        root_task_id="task-byte-accounting",
        agent_task_id="task-byte-accounting",
        path=str(target),
        content="v2",
        mode="overwrite",
    )

    assert created["success"] is True
    assert rejected["error_type"] == "managed_history_bounds_exceeded"
    assert target.read_text() == "v1"


@pytest.mark.asyncio
async def test_blob_store_supports_concurrent_identical_snapshots(tmp_path: Path) -> None:
    store = ManagedHistoryBlobStore(tmp_path / "concurrent-blobs")

    results = await asyncio.gather(
        *(asyncio.to_thread(store.put, b"same snapshot") for _ in range(8))
    )

    assert len({digest for digest, _ in results}) == 1
    assert {size for _, size in results} == {13}
