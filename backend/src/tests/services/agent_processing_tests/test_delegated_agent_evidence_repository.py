import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_evidence_repository import (
    DelegatedAgentEvidenceError,
    DelegatedAgentEvidenceRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_repository import (
    DelegatedAgentRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.delegated_agent_migrations import (
    migrate_delegated_agent_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.delegated_agent_schema import (
    get_delegated_agent_schema_statements,
)
from api.services.agent_processing.lifecycle.delegation.delegated_agent_evidence_service import (
    DelegatedAgentEvidenceService,
)

_ASSESSMENT = {
    "parallelism_reason": "fixture parent requires one bounded delegated child",
    "independence_rationale": "the child has no dependency in this persistence test",
    "expected_benefit": "proves durable evidence ownership",
    "parent_work_can_continue": False,
    "child_cannot_delegate": True,
}


def _setup_database(db_path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, root_task_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'routing')"
        )
        connection.executemany(
            "INSERT INTO agent_tasks (id, root_task_id) VALUES (?, ?)",
            [("parent", "parent"), ("child", "parent")],
        )
        migrate_delegated_agent_tables(connection)
        connection.commit()
    finally:
        connection.close()


async def _admit(db_path):
    runs = DelegatedAgentRepository(str(db_path))
    await runs.reserve_child_agent_task(
        parent_agent_task_id="parent",
        root_task_id="parent",
        child_agent_task_id="child",
        executor_kind="internal_agent",
        strategic_assessment=_ASSESSMENT,
    )
    run = await runs.admit_reserved_run(
        child_agent_task_id="child",
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    return runs, run


def test_migration_adds_evidence_table_and_indexes_without_backfill(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    connection = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        count = connection.execute("SELECT COUNT(*) FROM delegated_agent_evidence").fetchone()[0]
    finally:
        connection.close()
    assert "delegated_agent_evidence" in tables
    assert "idx_delegated_agent_evidence_run_sequence" in indexes
    assert "idx_delegated_agent_evidence_turn_sequence" in indexes
    assert count == 0


def test_migration_upgrades_existing_delegated_runs_without_backfilling_evidence(tmp_path) -> None:
    db_path = tmp_path / "pre-evidence.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, root_task_id TEXT NOT NULL, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO agent_tasks (id, root_task_id, status) VALUES (?, ?, 'routing')",
            [("parent", "parent"), ("child", "parent")],
        )
        for statement in get_delegated_agent_schema_statements()[:-3]:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO delegated_agent_runs (
                id, parent_agent_task_id, root_task_id, child_agent_task_id, executor_kind,
                admitted_scope_json, evidence_policy_json, dependency_run_ids_json,
                parent_continuation_required, status, revision, created_at, updated_at, settled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-run", "parent", "parent", "child", "internal_agent", "{}", "{}",
                "[]", 1, "settled", 1, "2026-08-09T00:00:00", "2026-08-09T00:00:00",
                "2026-08-09T00:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO delegated_agent_turns (
                id, delegated_agent_run_id, turn_sequence, controller_instruction, status,
                terminal_response_json, created_at, started_at, settled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-turn", "legacy-run", 1, "continue", "idle",
                '{"raw":"historical terminal response"}', "2026-08-09T00:00:00",
                "2026-08-09T00:00:00", "2026-08-09T00:00:00",
            ),
        )
        migrate_delegated_agent_tables(connection)
        run_count = connection.execute("SELECT COUNT(*) FROM delegated_agent_runs").fetchone()[0]
        terminal_response = connection.execute(
            "SELECT terminal_response_json FROM delegated_agent_turns WHERE id = 'legacy-turn'"
        ).fetchone()[0]
        evidence_count = connection.execute("SELECT COUNT(*) FROM delegated_agent_evidence").fetchone()[0]
    finally:
        connection.close()
    assert run_count == 1
    assert terminal_response == '{"raw":"historical terminal response"}'
    assert evidence_count == 0


@pytest.mark.asyncio
async def test_append_is_ordered_and_exact_replay_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    first = await repository.append_evidence(
        delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="activity:1",
        source="provider_activity", kind="message", provenance="provider_reported",
        verification_state="not_applicable", summary="Provider reported a bounded status update.",
        structured_data={"state": "working"}, artifact_locator=None,
    )
    replay = await repository.append_evidence(
        delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="activity:1",
        source="provider_activity", kind="message", provenance="provider_reported",
        verification_state="not_applicable", summary="Provider reported a bounded status update.",
        structured_data={"state": "working"}, artifact_locator=None,
    )
    second = await repository.append_evidence(
        delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="activity:2",
        source="provider_activity", kind="artifact", provenance="provider_reported",
        verification_state="pending", summary="Provider reported one workspace artifact.",
        structured_data={"operation": "write"}, artifact_locator="parent_graph_e2e_probe.txt",
    )
    page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"])
    assert first["sequence"] == 1
    assert replay["id"] == first["id"]
    assert replay["idempotent_replay"] is True
    assert second["sequence"] == 2
    assert [item["sequence"] for item in page["items"]] == [1, 2]


@pytest.mark.asyncio
async def test_rejects_foreign_turn_contradictory_replay_and_oversized_data(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    await repository.append_evidence(
        delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="event",
        source="provider_activity", kind="message", provenance="provider_reported",
        verification_state="not_applicable", summary="A bounded summary.", structured_data={}, artifact_locator=None,
    )
    with pytest.raises(DelegatedAgentEvidenceError, match="contradictory"):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="event",
            source="provider_activity", kind="message", provenance="provider_reported",
            verification_state="not_applicable", summary="A different bounded summary.", structured_data={}, artifact_locator=None,
        )
    with get_sync_connection(str(db_path), ensure_schema=False) as connection:
        connection.executemany(
            "INSERT INTO agent_tasks (id, root_task_id, status) VALUES (?, ?, 'routing')",
            [("other-parent", "other-parent"), ("other-child", "other-parent")],
        )
        connection.execute(
            """
            INSERT INTO delegated_agent_runs (
                id, parent_agent_task_id, root_task_id, child_agent_task_id, executor_kind,
                admitted_scope_json, evidence_policy_json, dependency_run_ids_json,
                parent_continuation_required, status, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "other-run", "other-parent", "other-parent", "other-child", "internal_agent",
                "{}", "{}", "[]", 1, "admitted", 0, "2026-08-09T00:00:00", "2026-08-09T00:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO delegated_agent_turns (
                id, delegated_agent_run_id, turn_sequence, controller_instruction, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("other-turn", "other-run", 1, "continue", "created", "2026-08-09T00:00:00"),
        )
        connection.commit()
    with pytest.raises(DelegatedAgentEvidenceError, match="turn is not owned"):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"], delegated_agent_turn_id="other-turn", source_event_key="foreign-turn",
            source="provider_activity", kind="message", provenance="provider_reported",
            verification_state="not_applicable", summary="A bounded summary.", structured_data={}, artifact_locator=None,
        )
    with pytest.raises(DelegatedAgentEvidenceError, match="exceeds"):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="oversized",
            source="provider_activity", kind="message", provenance="provider_reported",
            verification_state="not_applicable", summary="x" * 2_001, structured_data={}, artifact_locator=None,
        )
    with pytest.raises(DelegatedAgentEvidenceError, match="structured_data exceeds"):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key="oversized-json",
            source="provider_activity", kind="message", provenance="provider_reported",
            verification_state="not_applicable", summary="A bounded summary.", structured_data={"value": "x" * 4_000}, artifact_locator=None,
        )
    for locator in ("/private/tmp/not-allowed.txt", "../not-allowed.txt", "file:///private/tmp/not-allowed.txt"):
        with pytest.raises(DelegatedAgentEvidenceError, match="workspace-relative"):
            await repository.append_evidence(
                delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key=f"locator:{locator}",
                source="provider_activity", kind="artifact", provenance="provider_reported",
                verification_state="pending", summary="A bounded summary.", structured_data={}, artifact_locator=locator,
            )


@pytest.mark.asyncio
async def test_parent_owned_report_card_is_bounded_and_historical_empty_run_is_unavailable(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    service = DelegatedAgentEvidenceService(delegated_agent_repository=runs, evidence_repository=repository)
    empty = await service.build_parent_report_card(parent_agent_task_id="parent", delegated_agent_run_id=run["id"])
    assert empty["capture_state"] == "unavailable"
    assert empty["evidence_count"] == 0
    for sequence in range(7):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"], delegated_agent_turn_id=None, source_event_key=f"artifact:{sequence}",
            source="provider_activity", kind="artifact", provenance="provider_reported",
            verification_state="pending", summary=f"Provider reported artifact {sequence}.",
            structured_data={"sequence": sequence}, artifact_locator=f"output-{sequence}.txt",
        )
    report = await service.build_parent_report_card(parent_agent_task_id="parent", delegated_agent_run_id=run["id"])
    assert report["capture_state"] == "available"
    assert report["evidence_count"] == 7
    assert len(report["claims"]) == 6
    assert len(report["artifacts"]) == 6
    assert report["artifacts"][0]["artifact_locator"] == "output-1.txt"
    assert await repository.get_evidence_for_parent(
        parent_agent_task_id="other-parent", delegated_agent_run_id=run["id"], evidence_id=report["claims"][0]["evidence_id"]
    ) is None
    with pytest.raises(ValueError, match="not owned"):
        await service.build_parent_report_card(parent_agent_task_id="other-parent", delegated_agent_run_id=run["id"])


@pytest.mark.asyncio
async def test_list_evidence_for_run_pages_by_sequence(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    for sequence in (1, 2):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"],
            delegated_agent_turn_id=None,
            source_event_key=f"page:{sequence}",
            source="provider_activity",
            kind="message",
            provenance="provider_reported",
            verification_state="not_applicable",
            summary=f"Bounded summary {sequence}.",
            structured_data={"sequence": sequence},
            artifact_locator=None,
        )
    first_page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"], limit=1)
    assert len(first_page["items"]) == 1
    assert first_page["items"][0]["sequence"] == 1
    assert first_page["next_after_sequence"] == 1
    second_page = await repository.list_evidence_for_run(
        delegated_agent_run_id=run["id"],
        after_sequence=1,
        limit=1,
    )
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["sequence"] == 2
    assert second_page["next_after_sequence"] is None


@pytest.mark.asyncio
async def test_append_rolls_back_when_structured_data_is_not_serializable(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    with pytest.raises(DelegatedAgentEvidenceError, match="JSON serializable"):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"],
            delegated_agent_turn_id=None,
            source_event_key="rollback",
            source="provider_activity",
            kind="message",
            provenance="provider_reported",
            verification_state="not_applicable",
            summary="A bounded summary.",
            structured_data={"bad": object()},
            artifact_locator=None,
        )
    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM delegated_agent_evidence WHERE delegated_agent_run_id = ?",
            (run["id"],),
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 0


@pytest.mark.asyncio
async def test_evidence_cascades_when_its_delegated_run_is_deleted(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    await repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="cascade",
        source="provider_activity",
        kind="message",
        provenance="provider_reported",
        verification_state="not_applicable",
        summary="A bounded summary.",
        structured_data={},
        artifact_locator=None,
    )
    with get_sync_connection(str(db_path), ensure_schema=False) as connection:
        connection.execute("DELETE FROM delegated_agent_runs WHERE id = ?", (run["id"],))
        connection.commit()
        evidence_count = connection.execute("SELECT COUNT(*) FROM delegated_agent_evidence").fetchone()[0]
    assert evidence_count == 0


@pytest.mark.asyncio
async def test_parent_source_event_lookup_enforces_ownership(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    evidence = await repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="parent-verification:artifact:evidence-1:v1",
        source="parent_verification",
        kind="workspace_artifact_verification",
        provenance="basil_observed",
        verification_state="verified",
        summary="Basil verified one provider-reported workspace artifact.",
        structured_data={"artifact_evidence_id": "evidence-1", "reason": "regular_file"},
        artifact_locator=None,
    )
    same_parent = await repository.get_evidence_for_parent_by_source_event_key(
        parent_agent_task_id="parent",
        delegated_agent_run_id=run["id"],
        source_event_key="parent-verification:artifact:evidence-1:v1",
    )
    assert same_parent is not None
    assert same_parent["id"] == evidence["id"]
    foreign_parent = await repository.get_evidence_for_parent_by_source_event_key(
        parent_agent_task_id="other-parent",
        delegated_agent_run_id=run["id"],
        source_event_key="parent-verification:artifact:evidence-1:v1",
    )
    assert foreign_parent is None


@pytest.mark.asyncio
async def test_parent_inspection_omits_artifact_locator_and_enforces_evidence_ownership(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    service = DelegatedAgentEvidenceService(delegated_agent_repository=runs, evidence_repository=repository)
    evidence = await repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="artifact:inspection",
        source="provider_activity",
        kind="artifact_locator",
        provenance="provider_reported",
        verification_state="pending",
        summary="Provider reported one workspace artifact.",
        structured_data={"activity_kind": "tool_call"},
        artifact_locator="private-report.txt",
    )

    inspection = await service.inspect_parent_evidence(
        parent_agent_task_id="parent",
        delegated_agent_run_id=run["id"],
        evidence_id=evidence["id"],
        after_sequence=None,
        limit=12,
    )

    assert inspection["items"] == [{
        "evidence_id": evidence["id"],
        "sequence": evidence["sequence"],
        "source": "provider_activity",
        "kind": "artifact_locator",
        "provenance": "provider_reported",
        "verification_state": "pending",
        "summary": "Provider reported one workspace artifact.",
        "structured_data": {"activity_kind": "tool_call"},
        "created_at": evidence["created_at"],
    }]
    with pytest.raises(ValueError, match="not owned"):
        await service.inspect_parent_evidence(
            parent_agent_task_id="other-parent",
            delegated_agent_run_id=run["id"],
            evidence_id=evidence["id"],
            after_sequence=None,
            limit=12,
        )


@pytest.mark.asyncio
async def test_list_runs_for_parent_returns_all_owned_runs_in_creation_order(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    runs, first = await _admit(db_path)
    connection = sqlite3.connect(db_path)
    connection.executemany(
        "INSERT INTO agent_tasks (id, root_task_id) VALUES (?, ?)",
        [
            ("child-b", "parent"),
            ("foreign-parent", "foreign-parent"),
            ("foreign-child", "foreign-parent"),
        ],
    )
    connection.commit()
    connection.close()
    await runs.reserve_child_agent_task(
        parent_agent_task_id="parent",
        root_task_id="parent",
        child_agent_task_id="child-b",
        executor_kind="internal_agent",
        strategic_assessment=_ASSESSMENT,
    )
    second = await runs.admit_reserved_run(
        child_agent_task_id="child-b",
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    await runs.reserve_child_agent_task(
        parent_agent_task_id="foreign-parent",
        root_task_id="foreign-parent",
        child_agent_task_id="foreign-child",
        executor_kind="internal_agent",
        strategic_assessment=_ASSESSMENT,
    )
    foreign = await runs.admit_reserved_run(
        child_agent_task_id="foreign-child",
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    await runs.transition_run(
        delegated_agent_run_id=first["id"],
        expected_revision=first["revision"],
        next_status="settled",
    )

    owned = await runs.list_runs_for_parent("parent")
    assert [row["id"] for row in owned] == [first["id"], second["id"]]
    assert owned[0]["status"] == "settled"
    assert owned[1]["status"] == "admitted"
    assert foreign["id"] not in {row["id"] for row in owned}


@pytest.mark.asyncio
async def test_get_report_card_aggregate_uses_exact_count_and_latest_summary(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    for sequence in range(26):
        await repository.append_evidence(
            delegated_agent_run_id=run["id"],
            delegated_agent_turn_id=None,
            source_event_key=f"aggregate:{sequence}",
            source="provider_activity",
            kind="message",
            provenance="provider_reported",
            verification_state="not_applicable",
            summary=f"Summary {sequence}.",
            structured_data={"sequence": sequence},
            artifact_locator=None,
        )
    aggregate = await repository.get_report_card_aggregate(run["id"])
    assert aggregate["evidence_count"] == 26
    assert aggregate["latest_summary"] == "Summary 25."
    assert aggregate["verification_state"] == "not_applicable"


@pytest.mark.asyncio
async def test_get_report_card_aggregate_reports_verification_states(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    _runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    assert (await repository.get_report_card_aggregate(run["id"]))["verification_state"] == "unavailable"
    await repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="verified",
        source="parent_verification",
        kind="workspace_artifact_verification",
        provenance="basil_observed",
        verification_state="verified",
        summary="Verified artifact.",
        structured_data={},
        artifact_locator=None,
    )
    assert (await repository.get_report_card_aggregate(run["id"]))["verification_state"] == "verified"
    await repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="mismatch",
        source="parent_verification",
        kind="workspace_artifact_verification",
        provenance="basil_observed",
        verification_state="verification_mismatch",
        summary="Mismatch artifact.",
        structured_data={},
        artifact_locator=None,
    )
    assert (await repository.get_report_card_aggregate(run["id"]))["verification_state"] == "verification_mismatch"


@pytest.mark.asyncio
async def test_build_parent_report_cards_returns_selected_fields_only(tmp_path) -> None:
    db_path = tmp_path / "evidence.db"
    _setup_database(db_path)
    runs, run = await _admit(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    service = DelegatedAgentEvidenceService(delegated_agent_repository=runs, evidence_repository=repository)
    await repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="card:1",
        source="provider_activity",
        kind="message",
        provenance="provider_reported",
        verification_state="not_applicable",
        summary="Provider completed this turn.",
        structured_data={"raw": "must-not-leak"},
        artifact_locator=None,
    )
    cards = await service.build_parent_report_cards(parent_agent_task_id="parent")
    assert len(cards) == 1
    assert set(cards[0]) == {
        "delegated_agent_run_id",
        "run_status",
        "run_revision",
        "capture_state",
        "evidence_count",
        "latest_summary",
        "verification_state",
    }
    report = await service.build_parent_report_card(parent_agent_task_id="parent", delegated_agent_run_id=run["id"])
    assert "claims" in report
    assert "artifacts" in report
    assert "structured_data" not in str(report)
