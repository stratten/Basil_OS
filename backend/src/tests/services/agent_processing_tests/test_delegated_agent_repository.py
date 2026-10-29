"""Contract coverage for generic delegated-agent durable admissions and turns."""

from __future__ import annotations

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_repository import (
    DelegatedAgentConflictError,
    DelegatedAgentRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_evidence_repository import (
    DelegatedAgentEvidenceRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.delegated_agent_migrations import (
    migrate_delegated_agent_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService


def _setup_database(db_path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE agent_tasks (
                id TEXT PRIMARY KEY,
                root_task_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'routing'
            )
            """
        )
        connection.executemany(
            "INSERT INTO agent_tasks (id, root_task_id) VALUES (?, ?)",
            [
                ("root", "root"),
                ("child-one", "root"),
                ("child-two", "root"),
                ("child-three", "root"),
                ("child-four", "root"),
            ],
        )
        migrate_delegated_agent_tables(connection)
        connection.commit()
    finally:
        connection.close()


_ASSESSMENT = {
    "parallelism_reason": "isolated fixture children run concurrently in this test",
    "independence_rationale": "each child owns a disjoint mutable path",
    "expected_benefit": "verifies admission limits without serial waiting",
    "parent_work_can_continue": True,
    "child_cannot_delegate": True,
}


def test_sqlite_knowledge_service_installs_delegated_agent_tables_on_fresh_database(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "fresh.db")
    connection = sqlite3.connect(service.db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert {
        "delegated_agent_runs",
        "delegated_agent_turns",
        "delegated_agent_outcomes",
        "delegated_agent_events",
        "delegated_agent_child_reservations",
        "delegated_agent_evidence",
    }.issubset(tables)
    assert isinstance(service.delegated_agent_evidence_repository, DelegatedAgentEvidenceRepository)


def test_migration_adds_reservations_to_a_pre_reservation_run_schema(tmp_path) -> None:
    db_path = tmp_path / "pre-reservation.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE agent_tasks (
                id TEXT PRIMARY KEY,
                root_task_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'routing'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE delegated_agent_runs (
                id TEXT PRIMARY KEY,
                parent_agent_task_id TEXT NOT NULL,
                root_task_id TEXT NOT NULL,
                child_agent_task_id TEXT NOT NULL UNIQUE,
                executor_kind TEXT NOT NULL,
                admitted_scope_json TEXT NOT NULL DEFAULT '{}',
                evidence_policy_json TEXT NOT NULL DEFAULT '{}',
                dependency_run_ids_json TEXT NOT NULL DEFAULT '[]',
                parent_continuation_required INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                settled_at TIMESTAMP
            )
            """
        )

        migrate_delegated_agent_tables(connection)
        reservation_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(delegated_agent_child_reservations)"
            )
        }
    finally:
        connection.close()

    assert "strategic_assessment_json" in reservation_columns


async def _admit(
    repository: DelegatedAgentRepository,
    child_id: str,
    scope: dict[str, object],
    *,
    dependency_run_ids: list[str] | None = None,
):
    await repository.reserve_child_agent_task(
        parent_agent_task_id="root",
        root_task_id="root",
        child_agent_task_id=child_id,
        executor_kind="internal_agent",
        dependency_run_ids=dependency_run_ids,
        strategic_assessment=_ASSESSMENT,
    )
    return await repository.admit_reserved_run(
        child_agent_task_id=child_id,
        admitted_scope=scope,
        evidence_policy={"required": "provider_reported"},
        dependency_run_ids=dependency_run_ids,
    )


@pytest.mark.asyncio
async def test_admission_allows_three_independent_children_and_rejects_a_fourth(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))

    await _admit(repository, "child-one", {"mutable_paths": ["one.py"]})
    await _admit(repository, "child-two", {"mutable_paths": ["two.py"]})
    await _admit(repository, "child-three", {"mutable_paths": ["three.py"]})

    with pytest.raises(DelegatedAgentConflictError, match="three active"):
        await _admit(repository, "child-four", {"mutable_paths": ["four.py"]})


@pytest.mark.asyncio
async def test_admission_rejects_overlapping_mutable_scope_and_allows_read_only_overlap(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))

    await _admit(repository, "child-one", {"mutable_paths": ["shared.py"]})
    with pytest.raises(DelegatedAgentConflictError, match="mutable scope"):
        await _admit(repository, "child-two", {"mutable_paths": ["shared.py"]})

    admitted = await _admit(
        repository,
        "child-two",
        {"read_only": True, "mutable_paths": ["shared.py"]},
    )

    assert admitted["status"] == "admitted"


@pytest.mark.asyncio
async def test_turn_must_settle_before_follow_up_and_outcome_is_durable(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))
    admitted = await _admit(repository, "child-one", {"mutable_paths": ["one.py"]})

    turn = await repository.start_turn(
        delegated_agent_run_id=admitted["id"],
        expected_revision=admitted["revision"],
        controller_instruction="Implement the accepted child brief directly.",
    )
    with pytest.raises(DelegatedAgentConflictError, match="not eligible"):
        await repository.start_turn(
            delegated_agent_run_id=admitted["id"],
            expected_revision=admitted["revision"] + 1,
            controller_instruction="Send a concurrent follow-up.",
        )

    idle = await repository.settle_turn_idle(
        delegated_agent_run_id=admitted["id"],
        turn_id=turn["id"],
        expected_revision=admitted["revision"] + 1,
        terminal_response={"stop_reason": "end_turn", "message": "Need verification."},
    )
    settled = await repository.record_outcome(
        delegated_agent_run_id=idle["id"],
        expected_revision=idle["revision"],
        transport_state="completed",
        executor_result_state="incomplete",
        evidence_state="unavailable",
        summary="The child ended a turn without required evidence.",
        receipt_references=[],
        terminal_status="failed",
    )

    assert settled["status"] == "failed"


@pytest.mark.asyncio
async def test_reserved_child_admission_records_one_event_per_revision(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))

    reservation = await repository.reserve_child_agent_task(
        parent_agent_task_id="root",
        root_task_id="root",
        child_agent_task_id="child-one",
        executor_kind="internal_agent",
        strategic_assessment=_ASSESSMENT,
    )
    admitted = await repository.admit_reserved_run(
        child_agent_task_id=reservation["child_agent_task_id"],
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    running = await repository.transition_run(
        delegated_agent_run_id=admitted["id"],
        expected_revision=admitted["revision"],
        next_status="running",
    )

    assert (await repository.mark_reservation_dispatched("child-one"))["status"] == "dispatched"
    assert [(event["revision"], event["event_kind"]) for event in await repository.list_events(admitted["id"])] == [
        (0, "admitted"),
        (1, "status:running"),
    ]
    assert running["revision"] == 1


@pytest.mark.asyncio
async def test_reservation_rejects_a_missing_or_incomplete_strategic_assessment(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))

    with pytest.raises(DelegatedAgentConflictError, match="strategic_assessment"):
        await repository.reserve_child_agent_task(
            parent_agent_task_id="root",
            root_task_id="root",
            child_agent_task_id="child-one",
            executor_kind="internal_agent",
        )

    with pytest.raises(DelegatedAgentConflictError, match="child_cannot_delegate"):
        await repository.reserve_child_agent_task(
            parent_agent_task_id="root",
            root_task_id="root",
            child_agent_task_id="child-one",
            executor_kind="internal_agent",
            strategic_assessment={**_ASSESSMENT, "child_cannot_delegate": False},
        )


@pytest.mark.asyncio
async def test_blocked_dependency_has_no_run_or_dispatch(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))

    dependency = await _admit(repository, "child-one", {"mutable_paths": ["one.py"]})

    await repository.reserve_child_agent_task(
        parent_agent_task_id="root",
        root_task_id="root",
        child_agent_task_id="child-two",
        executor_kind="internal_agent",
        dependency_run_ids=[dependency["id"]],
        strategic_assessment=_ASSESSMENT,
    )
    blocked = await repository.admit_reserved_run(
        child_agent_task_id="child-two",
        admitted_scope={"mutable_paths": ["two.py"]},
        evidence_policy={"required": "provider_reported"},
        dependency_run_ids=[dependency["id"]],
    )

    assert blocked["ready"] is False
    assert blocked["blocked_dependency_run_ids"] == [dependency["id"]]
    assert await repository.get_run_for_child("child-two") is None

    await repository.record_outcome(
        delegated_agent_run_id=dependency["id"],
        expected_revision=dependency["revision"],
        transport_state="internal_agent",
        executor_result_state="completed",
        evidence_state="provider_reported",
        summary="Dependency finished.",
        receipt_references=[],
        terminal_status="settled",
    )
    ready = await repository.admit_reserved_run(
        child_agent_task_id="child-two",
        admitted_scope={"mutable_paths": ["two.py"]},
        evidence_policy={"required": "provider_reported"},
        dependency_run_ids=[dependency["id"]],
    )

    assert ready.get("ready", True) is True
    assert ready["status"] == "admitted"
    second_attempt = await repository.admit_reserved_run(
        child_agent_task_id="child-two",
        admitted_scope={"mutable_paths": ["two.py"]},
        evidence_policy={"required": "provider_reported"},
        dependency_run_ids=[dependency["id"]],
    )
    assert second_attempt["id"] == ready["id"]


@pytest.mark.asyncio
async def test_duplicate_outcome_conflict_is_treated_as_idempotent(tmp_path) -> None:
    db_path = tmp_path / "delegated-agent.db"
    _setup_database(db_path)
    repository = DelegatedAgentRepository(str(db_path))
    admitted = await _admit(repository, "child-one", {"mutable_paths": ["one.py"]})

    settled = await repository.record_outcome(
        delegated_agent_run_id=admitted["id"],
        expected_revision=admitted["revision"],
        transport_state="internal_agent",
        executor_result_state="completed",
        evidence_state="provider_reported",
        summary="First terminal report.",
        receipt_references=[],
        terminal_status="settled",
    )

    with pytest.raises(DelegatedAgentConflictError, match="already terminal"):
        await repository.record_outcome(
            delegated_agent_run_id=admitted["id"],
            expected_revision=settled["revision"],
            transport_state="internal_agent",
            executor_result_state="completed",
            evidence_state="provider_reported",
            summary="Duplicate terminal report.",
            receipt_references=[],
            terminal_status="settled",
        )

    refreshed = await repository.get_run(admitted["id"])
    assert refreshed["status"] == "settled"
