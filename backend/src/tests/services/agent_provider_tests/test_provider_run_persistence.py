"""Focused persistence coverage for attended generic ACP provider runs."""

from __future__ import annotations

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunConflictError,
    ProviderRunPersistenceError,
    ProviderRunTransitionError,
)

PROVIDER_TABLES = (
    "provider_profiles",
    "provider_workspace_grants",
    "provider_runs",
)

PROVIDER_INDEXES = (
    "idx_provider_profiles_status",
    "idx_provider_workspace_grants_profile_status",
    "idx_provider_runs_root_status",
    "idx_provider_runs_profile_status",
)


def _provider_schema_objects(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type IN ('table', 'index')
          AND (
            name IN (?, ?, ?, ?, ?, ?, ?)
          )
        """,
        (*PROVIDER_TABLES, *PROVIDER_INDEXES),
    ).fetchall()
    return {row[0] for row in rows}


def _drop_provider_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_provider_runs_profile_status")
    conn.execute("DROP INDEX IF EXISTS idx_provider_runs_root_status")
    conn.execute("DROP INDEX IF EXISTS idx_provider_workspace_grants_profile_status")
    conn.execute("DROP INDEX IF EXISTS idx_provider_profiles_status")
    conn.execute("DROP TABLE IF EXISTS provider_runs")
    conn.execute("DROP TABLE IF EXISTS provider_workspace_grants")
    conn.execute("DROP TABLE IF EXISTS provider_profiles")
    conn.commit()


async def _seed_profile_and_grant(
    service: SQLiteKnowledgeService,
    *,
    display_name: str = "Fixture Provider",
    launch_argv: tuple[str, ...] = ("fixture-acp", "--stdio"),
    environment_allowlist: tuple[str, ...] = ("PATH", "HOME"),
    workspace_root: str = "/tmp/BasilACP-workspace",
) -> tuple[dict[str, object], dict[str, object]]:
    profile = await service.provider_profile_repository.create_profile(
        display_name=display_name,
        launch_argv=launch_argv,
        environment_allowlist=environment_allowlist,
    )
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=workspace_root,
    )
    return profile, grant


async def _seed_agent_tasks(
    service: SQLiteKnowledgeService,
    *,
    root_task_id: str = "root-task",
    agent_task_id: str = "agent-task",
    create_root: bool = True,
) -> None:
    if create_root:
        await service.store_agent_task(
            agent_task_id=root_task_id,
            original_prompt="Root prompt",
            transcribed_prompt="Root prompt",
            status="processing",
        )
    if agent_task_id != root_task_id:
        await service.store_agent_task(
            agent_task_id=agent_task_id,
            original_prompt="Child prompt",
            transcribed_prompt="Child prompt",
            status="processing",
            root_task_id=root_task_id,
            chain_sequence_number=1,
        )


@pytest.mark.asyncio
async def test_fresh_initialization_creates_provider_tables_and_indexes(tmp_path) -> None:
    db_path = tmp_path / "provider_runs.db"
    SQLiteKnowledgeService(db_path)

    with sqlite3.connect(db_path) as conn:
        objects = _provider_schema_objects(conn)

    assert set(PROVIDER_TABLES).issubset(objects)
    assert set(PROVIDER_INDEXES).issubset(objects)


@pytest.mark.asyncio
async def test_legacy_database_migration_repairs_provider_schema_and_preserves_records(
    tmp_path,
) -> None:
    db_path = tmp_path / "provider_runs.db"
    service = SQLiteKnowledgeService(db_path)

    with sqlite3.connect(db_path) as conn:
        _drop_provider_schema(conn)
        assert not set(PROVIDER_TABLES).issubset(_provider_schema_objects(conn))

    SchemaManager(str(db_path)).initialize_db()

    profile, grant = await _seed_profile_and_grant(service)
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )

    with sqlite3.connect(db_path) as conn:
        objects_after_first_repair = _provider_schema_objects(conn)
    assert set(PROVIDER_TABLES).issubset(objects_after_first_repair)
    assert set(PROVIDER_INDEXES).issubset(objects_after_first_repair)

    SchemaManager(str(db_path)).initialize_db()

    with sqlite3.connect(db_path) as conn:
        objects_after_second_init = _provider_schema_objects(conn)
    assert objects_after_second_init == objects_after_first_repair

    restored_profile = await service.provider_profile_repository.get_profile(str(profile["id"]))
    restored_run = await service.provider_run_repository.get_run(str(run["id"]))

    assert restored_profile is not None
    assert restored_profile["display_name"] == profile["display_name"]
    assert restored_run is not None
    assert restored_run["status"] == "created"
    assert restored_run["workspace_grant_id"] == grant["id"]


@pytest.mark.asyncio
async def test_legacy_provider_configuration_rows_receive_only_metadata_defaults(
    tmp_path,
) -> None:
    db_path = tmp_path / "provider_runs.db"
    SQLiteKnowledgeService(db_path)

    with sqlite3.connect(db_path) as conn:
        _drop_provider_schema(conn)
        conn.executescript(
            """
            CREATE TABLE provider_profiles (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                transport TEXT NOT NULL,
                launch_argv_json TEXT NOT NULL,
                environment_allowlist_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'enabled',
                capability_state TEXT NOT NULL DEFAULT 'unverified',
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                removed_at TIMESTAMP
            );
            CREATE TABLE provider_workspace_grants (
                id TEXT PRIMARY KEY,
                provider_profile_id TEXT NOT NULL,
                canonical_workspace_root TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                revoked_at TIMESTAMP,
                UNIQUE (provider_profile_id, canonical_workspace_root)
            );
            INSERT INTO provider_profiles (
                id, display_name, transport, launch_argv_json,
                environment_allowlist_json, status, capability_state,
                created_at, updated_at, removed_at
            ) VALUES (
                'legacy-profile', 'Legacy Provider', 'acp_stdio', '["fixture-acp"]',
                '["PATH"]', 'disabled', 'unverified',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00', NULL
            );
            INSERT INTO provider_workspace_grants (
                id, provider_profile_id, canonical_workspace_root, status,
                created_at, updated_at, revoked_at
            ) VALUES (
                'legacy-grant', 'legacy-profile', '/tmp/legacy-workspace', 'active',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00', NULL
            );
            """
        )
        conn.commit()

    SchemaManager(str(db_path)).initialize_db()
    repository = SQLiteKnowledgeService(db_path).provider_profile_repository
    profile = await repository.get_profile("legacy-profile")
    grants = await repository.list_workspace_grants_for_profile("legacy-profile")

    assert profile is not None
    assert profile["description"] is None
    assert profile["routing_hints"] == ()
    assert profile["revision"] == 0
    assert profile["authentication_method_id"] is None
    assert grants == [
        {
            "id": "legacy-grant",
            "provider_profile_id": "legacy-profile",
            "canonical_workspace_root": "/tmp/legacy-workspace",
            "status": "active",
            "workspace_label": "/tmp/legacy-workspace",
            "description": None,
            "routing_hints": (),
            "revision": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "revoked_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_profile_round_trip_and_soft_removal_filtering(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    created = await service.provider_profile_repository.create_profile(
        display_name="Local ACP",
        launch_argv=(" my-acp ", "--stdio"),
        environment_allowlist=(" PATH ", "HOME"),
    )

    loaded = await service.provider_profile_repository.get_profile(str(created["id"]))

    assert loaded == created
    assert loaded["transport"] == "acp_stdio"
    assert loaded["status"] == "enabled"
    assert loaded["capability_state"] == "unverified"
    assert loaded["launch_argv"] == (" my-acp ", "--stdio")
    assert loaded["environment_allowlist"] == ("PATH", "HOME")

    removed = await service.provider_profile_repository.set_profile_status(
        str(created["id"]),
        "removed",
    )
    assert removed["status"] == "removed"
    assert removed["removed_at"] is not None
    assert await service.provider_profile_repository.list_profiles() == []
    assert len(await service.provider_profile_repository.list_profiles(include_removed=True)) == 1


@pytest.mark.asyncio
async def test_profile_rejects_invalid_persisted_json(tmp_path) -> None:
    db_path = tmp_path / "provider_runs.db"
    service = SQLiteKnowledgeService(db_path)
    profile = await service.provider_profile_repository.create_profile(
        display_name="Local ACP",
        launch_argv=("my-acp",),
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE provider_profiles SET launch_argv_json = ? WHERE id = ?",
            ("not-json", profile["id"]),
        )
        conn.commit()

    with pytest.raises(ProviderRunPersistenceError, match="launch_argv_json contains invalid JSON"):
        await service.provider_profile_repository.get_profile(str(profile["id"]))


@pytest.mark.asyncio
async def test_grant_reactivation_and_cross_profile_run_rejection(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile_a, _ = await _seed_profile_and_grant(
        service,
        display_name="Profile A",
        workspace_root="/tmp/workspace-a",
    )
    profile_b = await service.provider_profile_repository.create_profile(
        display_name="Profile B",
        launch_argv=("other-acp",),
    )
    grant_a = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile_a["id"]),
        canonical_workspace_root="/tmp/workspace-a",
    )
    revoked = await service.provider_profile_repository.revoke_workspace_grant(str(grant_a["id"]))
    assert revoked["status"] == "revoked"

    reactivated = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile_a["id"]),
        canonical_workspace_root="/tmp/workspace-a",
    )
    assert reactivated["id"] == grant_a["id"]
    assert reactivated["status"] == "active"
    assert reactivated["revoked_at"] is None

    await _seed_agent_tasks(service)
    with pytest.raises(ProviderRunConflictError, match="does not belong to profile"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task",
            root_task_id="root-task",
            provider_profile_id=str(profile_b["id"]),
            workspace_grant_id=str(grant_a["id"]),
        )


@pytest.mark.asyncio
async def test_create_run_requires_tasks_and_rejects_duplicate_agent_task_run(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service)

    with pytest.raises(ProviderRunConflictError, match="agent task 'agent-task' does not exist"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task",
            root_task_id="root-task",
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
        )

    await service.store_agent_task(
        agent_task_id="agent-task-with-missing-root",
        original_prompt="Child prompt",
        transcribed_prompt="Child prompt",
        status="processing",
        root_task_id="root-task",
    )
    with pytest.raises(ProviderRunConflictError, match="root task 'root-task' does not exist"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task-with-missing-root",
            root_task_id="root-task",
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
        )

    await _seed_agent_tasks(service)
    await service.store_agent_task(
        agent_task_id="unrelated-root-task",
        original_prompt="Unrelated root prompt",
        transcribed_prompt="Unrelated root prompt",
        status="processing",
    )
    with pytest.raises(ProviderRunConflictError, match="does not match the Agent Task root"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task",
            root_task_id="unrelated-root-task",
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
        )

    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )

    assert run["status"] == "created"
    assert run["capabilities"] is None
    assert run["revision"] == 0

    with pytest.raises(ProviderRunConflictError, match="already exists for agent task"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task",
            root_task_id="root-task",
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
        )


@pytest.mark.asyncio
async def test_mark_run_initialized_is_atomic_and_revision_safe(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service)
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )

    initialized = await service.provider_run_repository.mark_run_initialized(
        provider_run_id=str(run["id"]),
        expected_revision=0,
        capabilities={"session": {}},
        runtime_version="1.0.0",
        provider_session_id="provider-session-1",
        launch_fingerprint="fp-1",
    )

    assert initialized["status"] == "running"
    assert initialized["capabilities"] == {"session": {}}
    assert initialized["runtime_version"] == "1.0.0"
    assert initialized["provider_session_id"] == "provider-session-1"
    assert initialized["launch_fingerprint"] == "fp-1"
    assert initialized["started_at"] is not None
    assert initialized["revision"] == 1

    with pytest.raises(ProviderRunConflictError, match="is not in created status"):
        await service.provider_run_repository.mark_run_initialized(
            provider_run_id=str(run["id"]),
            expected_revision=1,
            capabilities={"session": {}},
            runtime_version="1.0.0",
        )

    service_two = SQLiteKnowledgeService(tmp_path / "provider_runs_stale.db")
    profile_two, grant_two = await _seed_profile_and_grant(service_two)
    await _seed_agent_tasks(service_two, agent_task_id="agent-task-2")
    run_two = await service_two.provider_run_repository.create_run(
        agent_task_id="agent-task-2",
        root_task_id="root-task",
        provider_profile_id=str(profile_two["id"]),
        workspace_grant_id=str(grant_two["id"]),
    )
    with pytest.raises(ProviderRunConflictError, match="revision mismatch"):
        await service_two.provider_run_repository.mark_run_initialized(
            provider_run_id=str(run_two["id"]),
            expected_revision=99,
            capabilities={"session": {}},
            runtime_version="1.0.0",
        )


@pytest.mark.asyncio
async def test_allowed_transitions_and_terminal_guardrails(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service)
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )
    running = await service.provider_run_repository.mark_run_initialized(
        provider_run_id=str(run["id"]),
        expected_revision=0,
        capabilities={"session": {}},
        runtime_version="1.0.0",
    )
    waiting = await service.provider_run_repository.transition_run(
        provider_run_id=str(running["id"]),
        expected_revision=running["revision"],
        next_status="waiting_user_input",
    )
    resumed = await service.provider_run_repository.transition_run(
        provider_run_id=str(waiting["id"]),
        expected_revision=waiting["revision"],
        next_status="running",
    )
    cancelling = await service.provider_run_repository.transition_run(
        provider_run_id=str(resumed["id"]),
        expected_revision=resumed["revision"],
        next_status="cancelling",
    )

    with pytest.raises(ProviderRunConflictError, match="revision mismatch"):
        await service.provider_run_repository.transition_run(
            provider_run_id=str(cancelling["id"]),
            expected_revision=cancelling["revision"] - 1,
            next_status="cancelled",
        )

    cancelled = await service.provider_run_repository.transition_run(
        provider_run_id=str(cancelling["id"]),
        expected_revision=cancelling["revision"],
        next_status="cancelled",
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["terminal_at"] is not None

    with pytest.raises(ProviderRunConflictError, match="revision mismatch"):
        await service.provider_run_repository.transition_run(
            provider_run_id=str(cancelled["id"]),
            expected_revision=cancelled["revision"] - 1,
            next_status="running",
        )

    with pytest.raises(ProviderRunTransitionError, match="terminal"):
        await service.provider_run_repository.transition_run(
            provider_run_id=str(cancelled["id"]),
            expected_revision=cancelled["revision"],
            next_status="running",
        )


@pytest.mark.asyncio
async def test_interrupted_recovery_and_profile_status_blocks_new_runs(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(service)
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )
    running = await service.provider_run_repository.mark_run_initialized(
        provider_run_id=str(run["id"]),
        expected_revision=0,
        capabilities={"session": {}},
        runtime_version="1.0.0",
    )

    with pytest.raises(ProviderRunPersistenceError, match="terminal_reason"):
        await service.provider_run_repository.transition_run(
            provider_run_id=str(running["id"]),
            expected_revision=running["revision"],
            next_status="interrupted",
        )

    interrupted = await service.provider_run_repository.transition_run(
        provider_run_id=str(running["id"]),
        expected_revision=running["revision"],
        next_status="interrupted",
        terminal_reason="process exited unexpectedly",
    )
    recoverable = await service.provider_run_repository.transition_run(
        provider_run_id=str(interrupted["id"]),
        expected_revision=interrupted["revision"],
        next_status="recoverable",
    )
    resumed = await service.provider_run_repository.transition_run(
        provider_run_id=str(recoverable["id"]),
        expected_revision=recoverable["revision"],
        next_status="running",
    )
    assert resumed["status"] == "running"
    assert resumed["provider_session_id"] == running["provider_session_id"]
    assert resumed["launch_fingerprint"] == running["launch_fingerprint"]
    assert resumed["capabilities"] == running["capabilities"]

    second_repository = SQLiteKnowledgeService(tmp_path / "provider_runs.db").provider_run_repository
    stale_running = await second_repository.get_run(str(run["id"]))
    assert stale_running is not None
    waiting = await service.provider_run_repository.transition_run(
        provider_run_id=str(run["id"]),
        expected_revision=resumed["revision"],
        next_status="waiting_permission",
    )
    with pytest.raises(ProviderRunConflictError, match="revision mismatch"):
        await second_repository.transition_run(
            provider_run_id=str(run["id"]),
            expected_revision=stale_running["revision"],
            next_status="cancelling",
        )
    assert waiting["status"] == "waiting_permission"

    await service.provider_profile_repository.set_profile_status(str(profile["id"]), "disabled")
    await _seed_agent_tasks(
        service,
        agent_task_id="agent-task-2",
        create_root=False,
    )
    with pytest.raises(ProviderRunConflictError, match="is not enabled"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task-2",
            root_task_id="root-task",
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
        )

    historical = await service.provider_run_repository.get_run(str(run["id"]))
    assert historical is not None
    assert historical["provider_profile_id"] == profile["id"]

    await service.provider_profile_repository.set_profile_status(str(profile["id"]), "removed")
    await _seed_agent_tasks(
        service,
        agent_task_id="agent-task-3",
        create_root=False,
    )
    with pytest.raises(ProviderRunConflictError, match="is not enabled"):
        await service.provider_run_repository.create_run(
            agent_task_id="agent-task-3",
            root_task_id="root-task",
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
        )


@pytest.mark.asyncio
async def test_profile_foreign_key_preserves_historical_provider_run(tmp_path) -> None:
    db_path = tmp_path / "provider_runs.db"
    service = SQLiteKnowledgeService(db_path)
    profile, grant = await _seed_profile_and_grant(service)
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM provider_profiles WHERE id = ?", (profile["id"],))

    historical = await service.provider_run_repository.get_run(str(run["id"]))
    assert historical is not None
    assert historical["provider_profile_id"] == profile["id"]


@pytest.mark.asyncio
async def test_embedded_secret_argv_values_are_rejected_before_insert(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    repo = service.provider_profile_repository

    with pytest.raises(ProviderRunPersistenceError, match="secret-bearing flag '--api-key'"):
        await repo.create_profile(
            display_name="Bad Provider",
            launch_argv=("acp", "--api-key=secret"),
        )

    with pytest.raises(ProviderRunPersistenceError, match="secret-bearing flag '--token'"):
        await repo.create_profile(
            display_name="Bad Provider",
            launch_argv=("acp", "--token"),
        )

    with pytest.raises(ProviderRunPersistenceError, match="secret-bearing flag '--token'"):
        await repo.create_profile(
            display_name="Bad Provider",
            launch_argv=("acp", "wrapper--token=secret"),
        )

    with pytest.raises(ProviderRunPersistenceError, match="secret-like value prefix 'sk-'"):
        await repo.create_profile(
            display_name="Bad Provider",
            launch_argv=("sk-example",),
        )

    with pytest.raises(ProviderRunPersistenceError, match="secret-like value prefix 'ghp_'"):
        await repo.create_profile(
            display_name="Bad Provider",
            launch_argv=("ghp_example",),
        )


@pytest.mark.asyncio
async def test_get_workspace_grant_returns_none_for_a_missing_id_and_the_row_when_present(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    repo = service.provider_profile_repository
    profile, grant = await _seed_profile_and_grant(service)

    assert await repo.get_workspace_grant("missing") is None

    loaded = await repo.get_workspace_grant(str(grant["id"]))
    assert loaded == grant
    assert loaded["provider_profile_id"] == profile["id"]


@pytest.mark.asyncio
async def test_registry_profile_configuration_uses_revision_cas_and_requires_an_executable(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    repo = service.provider_profile_repository
    with pytest.raises(ProviderRunPersistenceError, match="does not exist"):
        await repo.create_profile(
            display_name="Missing runtime",
            launch_argv=("/missing/provider",),
            initial_status="disabled",
            require_executable=True,
        )
    unavailable_profile = await repo.create_profile(
        display_name="Unavailable runtime",
        launch_argv=("/missing/provider",),
        initial_status="disabled",
    )
    with pytest.raises(ProviderRunPersistenceError, match="does not exist"):
        await repo.set_profile_registry_status(
            provider_profile_id=str(unavailable_profile["id"]),
            expected_revision=0,
            next_status="enabled",
        )
    unavailable_after_enable = await repo.get_profile(str(unavailable_profile["id"]))
    assert unavailable_after_enable is not None
    assert unavailable_after_enable["status"] == "disabled"
    assert unavailable_after_enable["revision"] == 0

    profile = await repo.create_profile(
        display_name="Registry Provider",
        launch_argv=("fixture-acp", "--stdio"),
        description="Initial metadata",
        routing_hints=("fixture",),
        initial_status="disabled",
    )

    assert profile["status"] == "disabled"
    assert profile["description"] == "Initial metadata"
    assert profile["routing_hints"] == ("fixture",)
    assert profile["revision"] == 0

    with pytest.raises(ProviderRunPersistenceError, match="environment variable name"):
        await repo.update_profile_configuration(
            provider_profile_id=str(profile["id"]),
            expected_revision=0,
            display_name="Registry Provider",
            launch_argv=("/bin/sh",),
            environment_allowlist=("PATH=/tmp",),
            authentication_method_id=None,
            description="Updated metadata",
            routing_hints=("fixture",),
        )
    with pytest.raises(ProviderRunPersistenceError, match="at most 8"):
        await repo.update_profile_configuration(
            provider_profile_id=str(profile["id"]),
            expected_revision=0,
            display_name="Registry Provider",
            launch_argv=("/bin/sh",),
            environment_allowlist=(),
            authentication_method_id=None,
            description="Updated metadata",
            routing_hints=tuple(str(index) for index in range(9)),
        )
    before_update = await repo.get_profile(str(profile["id"]))
    assert before_update is not None
    assert before_update["revision"] == 0
    assert before_update["description"] == "Initial metadata"

    updated = await repo.update_profile_configuration(
        provider_profile_id=str(profile["id"]),
        expected_revision=0,
        display_name="Registry Provider",
        launch_argv=("/bin/sh", "-c", "echo fixture"),
        environment_allowlist=("PATH",),
        authentication_method_id="api-key",
        description="Updated metadata",
        routing_hints=("fixture", "local"),
    )

    assert updated["revision"] == 1
    assert updated["description"] == "Updated metadata"
    assert updated["authentication_method_id"] == "api-key"
    with pytest.raises(ProviderRunConflictError, match="revision mismatch"):
        await repo.update_profile_configuration(
            provider_profile_id=str(profile["id"]),
            expected_revision=0,
            display_name="Stale update",
            launch_argv=("/bin/sh",),
            environment_allowlist=(),
            authentication_method_id=None,
            description=None,
            routing_hints=(),
        )

    enabled = await repo.set_profile_registry_status(
        provider_profile_id=str(profile["id"]),
        expected_revision=1,
        next_status="enabled",
    )
    assert enabled["status"] == "enabled"
    assert enabled["revision"] == 2

    with pytest.raises(ProviderRunPersistenceError, match="does not exist"):
        await repo.update_profile_configuration(
            provider_profile_id=str(profile["id"]),
            expected_revision=2,
            display_name="Invalid runtime",
            launch_argv=("/missing/provider",),
            environment_allowlist=(),
            authentication_method_id=None,
            description=None,
            routing_hints=(),
        )
    unchanged = await repo.get_profile(str(profile["id"]))
    assert unchanged is not None
    assert unchanged["display_name"] == "Registry Provider"
    assert unchanged["revision"] == 2


@pytest.mark.asyncio
async def test_registry_workspace_configuration_reactivates_only_revoked_grants_with_cas(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    repo = service.provider_profile_repository
    profile = await repo.create_profile(
        display_name="Registry Provider",
        launch_argv=("fixture-acp", "--stdio"),
        initial_status="disabled",
    )
    root = str(tmp_path / "workspace")
    grant = await repo.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=root,
        workspace_label="Fixture workspace",
        description="Temporary root",
        routing_hints=("fixture",),
        reject_active_duplicate=True,
    )

    assert grant["workspace_label"] == "Fixture workspace"
    assert grant["revision"] == 0
    with pytest.raises(ProviderRunConflictError, match="already granted"):
        await repo.grant_workspace(
            provider_profile_id=str(profile["id"]),
            canonical_workspace_root=root,
            workspace_label="Duplicate",
            reject_active_duplicate=True,
        )

    updated = await repo.update_workspace_grant_configuration(
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
        expected_revision=0,
        workspace_label="Renamed fixture",
        description=None,
        routing_hints=("temporary",),
    )
    assert updated["revision"] == 1
    revoked = await repo.revoke_workspace_grant_if_revision(
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
        expected_revision=1,
    )
    assert revoked["status"] == "revoked"
    assert revoked["revision"] == 2

    reactivated = await repo.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=root,
        workspace_label="Restored fixture",
        description=None,
        routing_hints=(),
        reject_active_duplicate=True,
    )
    assert reactivated["id"] == grant["id"]
    assert reactivated["status"] == "active"
    assert reactivated["revision"] == 3

    other_profile = await repo.create_profile(
        display_name="Other Registry Provider",
        launch_argv=("other-fixture-acp",),
        initial_status="disabled",
    )
    with pytest.raises(ProviderRunConflictError, match="does not exist for profile"):
        await repo.revoke_workspace_grant_if_revision(
            provider_profile_id=str(other_profile["id"]),
            workspace_grant_id=str(grant["id"]),
            expected_revision=3,
        )

    await repo.set_profile_registry_status(
        provider_profile_id=str(profile["id"]),
        expected_revision=0,
        next_status="removed",
    )
    with pytest.raises(ProviderRunConflictError, match="does not exist"):
        await repo.update_workspace_grant_configuration(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            expected_revision=3,
            workspace_label="Cannot update",
            description=None,
            routing_hints=(),
        )
    with pytest.raises(ProviderRunConflictError, match="does not exist"):
        await repo.revoke_workspace_grant_if_revision(
            provider_profile_id=str(profile["id"]),
            workspace_grant_id=str(grant["id"]),
            expected_revision=3,
        )


def test_provider_registry_schema_migration_adds_metadata_and_revision_columns(tmp_path) -> None:
    db_path = tmp_path / "provider_runs.db"
    SQLiteKnowledgeService(db_path)

    with sqlite3.connect(db_path) as conn:
        profile_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(provider_profiles)")
        }
        grant_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(provider_workspace_grants)")
        }

    assert {
        "description",
        "routing_hints_json",
        "revision",
        "authentication_method_id",
    }.issubset(profile_columns)
    assert {
        "workspace_label",
        "description",
        "routing_hints_json",
        "revision",
    }.issubset(grant_columns)
