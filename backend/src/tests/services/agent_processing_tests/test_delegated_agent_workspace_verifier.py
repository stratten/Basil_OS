"""Focused coverage for DelegatedAgentWorkspaceVerifier (Package 5D.7D)."""

from __future__ import annotations

import hashlib
import sqlite3
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.delegation import delegated_agent_workspace_verifier
from api.services.agent_processing.lifecycle.delegation.delegated_agent_workspace_verifier import (
    MAX_VERIFY_FILE_BYTES,
    DelegatedAgentWorkspaceVerificationError,
    DelegatedAgentWorkspaceVerifier,
    _relative_workspace_path,
)

_ASSESSMENT = {
    "parallelism_reason": "fixture parent requires one bounded delegated child",
    "independence_rationale": "the child has no dependency in this verification test",
    "expected_benefit": "proves deterministic workspace verification",
    "parent_work_can_continue": False,
    "child_cannot_delegate": True,
}


async def _verification_fixture(tmp_path, *, run_status: str = "supervision_due", grant_status: str = "active", profile_status: str = "enabled"):
    knowledge = SQLiteKnowledgeService(tmp_path / "verify.db")
    await knowledge.store_agent_task(
        agent_task_id="parent",
        original_prompt="parent task",
        transcribed_prompt="parent task",
        status="processing",
        root_task_id="parent",
    )
    await knowledge.store_agent_task(
        agent_task_id="child",
        original_prompt="child task",
        transcribed_prompt="child task",
        status="routing",
        root_task_id="parent",
    )
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    profile = await knowledge.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
    if profile_status != "enabled":
        await knowledge.provider_profile_repository.set_profile_status(str(profile["id"]), profile_status)
        profile = await knowledge.provider_profile_repository.get_profile(str(profile["id"]))
        assert profile is not None
    grant = await knowledge.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(workspace_root),
    )
    if grant_status != "active":
        with sqlite3.connect(knowledge.db_path) as conn:
            conn.execute(
                "UPDATE provider_workspace_grants SET status = ? WHERE id = ?",
                (grant_status, str(grant["id"])),
            )
            conn.commit()
        grant = await knowledge.provider_profile_repository.get_workspace_grant(str(grant["id"]))
        assert grant is not None
    runs = knowledge.delegated_agent_repository
    await runs.reserve_child_agent_task(
        parent_agent_task_id="parent",
        root_task_id="parent",
        child_agent_task_id="child",
        executor_kind="acp_provider",
        strategic_assessment=_ASSESSMENT,
    )
    run = await runs.admit_reserved_run(
        child_agent_task_id="child",
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    if run_status != "admitted":
        transitions = ["running", "idle", "supervision_due"] if run_status == "supervision_due" else [run_status]
        for next_status in transitions:
            run = await runs.transition_run(
                delegated_agent_run_id=run["id"],
                expected_revision=run["revision"],
                next_status=next_status,
            )
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            """
            INSERT INTO provider_discovery_proposals (
                id, agent_task_id, root_task_id, status, grounding_tier, confidence,
                provider_candidates_json, service_candidates_json, evidence_json,
                exact_user_constraints_json, rationale, proposal_fingerprint, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "proposal-1", "parent", "parent", "proposed", "explicit_reference_or_chain_context", "high",
                "[]", "[]", "[]", "{}", "fixture proposal", "fingerprint-1",
                "2099-01-01T00:00:00", "2099-01-01T00:00:00", "2099-01-01T00:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO provider_target_authorizations (
                id, parent_authorization_id, proposal_id, agent_task_id, root_task_id, status, reason_code,
                selected_provider_profile_id, selected_workspace_grant_id, reference_paths_json,
                choice_snapshot_json, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "authorization-1", None, "proposal-1", "parent", "parent", "authorized", "verified_current_authority",
                str(profile["id"]), str(grant["id"]), "[]", "{}", "2099-01-01T00:00:00", "2099-01-01T00:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO provider_target_delegations (
                id, authorization_id, parent_agent_task_id, root_task_id, child_agent_task_id,
                delegated_agent_run_id, provider_profile_id, workspace_grant_id,
                selected_connection_id, selected_tool_name, selected_service_policy,
                legacy_lifecycle_snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                "delegation-1", "authorization-1", "parent", "parent", "child", run["id"],
                str(profile["id"]), str(grant["id"]), None, None, None,
                "2099-01-01T00:00:00", "2099-01-01T00:00:00",
            ),
        )
        conn.commit()
    evidence_repository = knowledge.delegated_agent_evidence_repository
    artifact = await evidence_repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="activity:artifact:1",
        source="provider_activity",
        kind="artifact_locator",
        provenance="provider_reported",
        verification_state="pending",
        summary="Provider reported one workspace artifact.",
        structured_data={"operation": "write"},
        artifact_locator="output.txt",
    )
    verifier = DelegatedAgentWorkspaceVerifier(
        delegated_agent_repository=knowledge.delegated_agent_repository,
        evidence_repository=evidence_repository,
        provider_target_delegation_repository=knowledge.provider_target_delegation_repository,
        provider_profile_repository=knowledge.provider_profile_repository,
    )
    return SimpleNamespace(
        knowledge=knowledge,
        workspace_root=workspace_root,
        profile=profile,
        grant=grant,
        run=run,
        artifact=artifact,
        verifier=verifier,
        evidence_repository=evidence_repository,
    )


def _verification_count(db_path: str, run_id: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            """
            SELECT COUNT(*) FROM delegated_agent_evidence
            WHERE delegated_agent_run_id = ? AND source = 'parent_verification'
            """,
            (run_id,),
        ).fetchone()[0]
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_regular_utf8_file_verifies_with_digest_and_no_locator_in_structured_data(tmp_path) -> None:
    fixture = await _verification_fixture(tmp_path)
    content = b"PRIMARY_GRAPH_DELEGATION"
    target = fixture.workspace_root / "output.txt"
    target.write_bytes(content)
    expected_digest = hashlib.sha256(content).hexdigest()

    result = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )

    assert result["source"] == "parent_verification"
    assert result["kind"] == "workspace_artifact_verification"
    assert result["provenance"] == "basil_observed"
    assert result["verification_state"] == "verified"
    assert result["structured_data"]["artifact_evidence_id"] == fixture.artifact["id"]
    assert result["structured_data"]["reason"] == "regular_file"
    assert result["structured_data"]["byte_count"] == len(content)
    assert result["structured_data"]["sha256"] == expected_digest
    assert "artifact_locator" not in result["structured_data"]
    assert "content" not in result["structured_data"]
    assert "body" not in result["structured_data"]


@pytest.mark.asyncio
async def test_second_verification_returns_first_immutable_record(tmp_path) -> None:
    fixture = await _verification_fixture(tmp_path)
    (fixture.workspace_root / "output.txt").write_text("stable\n", encoding="utf-8")

    first = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )
    second = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )

    assert second["id"] == first["id"]
    assert _verification_count(fixture.knowledge.db_path, fixture.run["id"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("missing", "missing"),
        ("directory", "not_regular_file"),
        ("symlink", "symlink_not_allowed"),
        ("broken_symlink", "symlink_not_allowed"),
        ("too_large", "too_large"),
    ],
)
async def test_mismatch_cases_append_one_verification_record(tmp_path, setup: str, reason: str) -> None:
    fixture = await _verification_fixture(tmp_path)
    if setup == "missing":
        pass
    elif setup == "directory":
        (fixture.workspace_root / "output.txt").mkdir()
    elif setup == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        (fixture.workspace_root / "output.txt").symlink_to(outside)
    elif setup == "broken_symlink":
        (fixture.workspace_root / "output.txt").symlink_to(tmp_path / "missing-target.txt")
    elif setup == "too_large":
        (fixture.workspace_root / "output.txt").write_bytes(b"x" * (MAX_VERIFY_FILE_BYTES + 1))

    result = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )

    assert result["verification_state"] == "verification_mismatch"
    assert result["structured_data"]["reason"] == reason
    assert _verification_count(fixture.knowledge.db_path, fixture.run["id"]) == 1


@pytest.mark.asyncio
async def test_file_changed_during_hashing_records_a_mismatch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = await _verification_fixture(tmp_path)
    target = fixture.workspace_root / "output.txt"
    target.write_bytes(b"before-verification")
    original_sha256 = hashlib.sha256

    class MutatingDigest:
        def __init__(self) -> None:
            self._digest = original_sha256()

        def update(self, chunk: bytes) -> None:
            self._digest.update(chunk)
            target.write_bytes(b"changed-during-verification")

        def hexdigest(self) -> str:
            return self._digest.hexdigest()

    monkeypatch.setattr(delegated_agent_workspace_verifier.hashlib, "sha256", MutatingDigest)

    result = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )

    assert result["verification_state"] == "verification_mismatch"
    assert result["structured_data"]["reason"] == "changed_during_verification"
    assert result["structured_data"]["sha256"] is None


@pytest.mark.asyncio
async def test_binary_fixture_verifies_by_digest_without_exposing_bytes(tmp_path) -> None:
    fixture = await _verification_fixture(tmp_path)
    content = bytes(range(256))
    (fixture.workspace_root / "output.txt").write_bytes(content)

    result = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )

    assert result["verification_state"] == "verified"
    assert result["structured_data"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert "content" not in result["structured_data"]
    assert "body" not in result["structured_data"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parent_id", "artifact_id", "run_status", "executor_kind", "grant_status", "profile_status"),
    [
        ("other-parent", None, "supervision_due", "acp_provider", "active", "enabled"),
        (None, "foreign-artifact", "supervision_due", "acp_provider", "active", "enabled"),
        (None, None, "running", "acp_provider", "active", "enabled"),
        (None, None, "supervision_due", "internal_agent", "active", "enabled"),
        (None, None, "supervision_due", "acp_provider", "revoked", "enabled"),
        (None, None, "supervision_due", "acp_provider", "active", "disabled"),
    ],
)
async def test_authority_failures_raise_without_appending_verification(
    tmp_path,
    parent_id,
    artifact_id,
    run_status,
    executor_kind,
    grant_status,
    profile_status,
) -> None:
    fixture = await _verification_fixture(
        tmp_path,
        run_status=run_status,
        grant_status=grant_status,
        profile_status=profile_status,
    )
    if executor_kind != "acp_provider":
        with sqlite3.connect(fixture.knowledge.db_path) as conn:
            conn.execute(
                "UPDATE delegated_agent_runs SET executor_kind = ? WHERE id = ?",
                (executor_kind, fixture.run["id"]),
            )
            conn.commit()
    effective_parent = parent_id or "parent"
    effective_artifact = artifact_id or fixture.artifact["id"]
    if artifact_id == "foreign-artifact":
        foreign = await fixture.evidence_repository.append_evidence(
            delegated_agent_run_id=fixture.run["id"],
            delegated_agent_turn_id=None,
            source_event_key="activity:foreign",
            source="provider_activity",
            kind="message",
            provenance="provider_reported",
            verification_state="not_applicable",
            summary="Not an artifact locator.",
            structured_data={},
            artifact_locator=None,
        )
        effective_artifact = foreign["id"]

    with pytest.raises(DelegatedAgentWorkspaceVerificationError):
        await fixture.verifier.verify_artifact(
            parent_agent_task_id=effective_parent,
            delegated_agent_run_id=fixture.run["id"],
            artifact_evidence_id=effective_artifact,
        )
    assert _verification_count(fixture.knowledge.db_path, fixture.run["id"]) == 0


@pytest.mark.asyncio
async def test_foreign_artifact_evidence_is_rejected_without_appending_verification(tmp_path) -> None:
    fixture = await _verification_fixture(tmp_path)
    await fixture.knowledge.store_agent_task(
        agent_task_id="other-parent",
        original_prompt="other parent task",
        transcribed_prompt="other parent task",
        status="processing",
        root_task_id="other-parent",
    )
    await fixture.knowledge.store_agent_task(
        agent_task_id="other-child",
        original_prompt="other child task",
        transcribed_prompt="other child task",
        status="routing",
        root_task_id="other-parent",
    )
    runs = fixture.knowledge.delegated_agent_repository
    await runs.reserve_child_agent_task(
        parent_agent_task_id="other-parent",
        root_task_id="other-parent",
        child_agent_task_id="other-child",
        executor_kind="acp_provider",
        strategic_assessment=_ASSESSMENT,
    )
    foreign_run = await runs.admit_reserved_run(
        child_agent_task_id="other-child",
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    foreign_artifact = await fixture.evidence_repository.append_evidence(
        delegated_agent_run_id=foreign_run["id"],
        delegated_agent_turn_id=None,
        source_event_key="activity:foreign-artifact",
        source="provider_activity",
        kind="artifact_locator",
        provenance="provider_reported",
        verification_state="pending",
        summary="Other provider reported one workspace artifact.",
        structured_data={},
        artifact_locator="output.txt",
    )

    with pytest.raises(DelegatedAgentWorkspaceVerificationError, match="provider-reported artifact locator"):
        await fixture.verifier.verify_artifact(
            parent_agent_task_id="parent",
            delegated_agent_run_id=fixture.run["id"],
            artifact_evidence_id=foreign_artifact["id"],
        )

    assert _verification_count(fixture.knowledge.db_path, fixture.run["id"]) == 0


@pytest.mark.parametrize(
    "locator",
    [
        "C:\\Windows\\System32\\config.sys",
        "file:///private/tmp/not-allowed.txt",
        "../escape.txt",
    ],
)
def test_malformed_locators_raise_before_filesystem_access(locator: str) -> None:
    with pytest.raises(DelegatedAgentWorkspaceVerificationError, match="workspace-relative"):
        _relative_workspace_path(locator)


@pytest.mark.asyncio
async def test_get_verification_for_settlement_accepts_only_admissible_records(tmp_path) -> None:
    fixture = await _verification_fixture(tmp_path)
    (fixture.workspace_root / "output.txt").write_text("verified\n", encoding="utf-8")
    verified = await fixture.verifier.verify_artifact(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        artifact_evidence_id=fixture.artifact["id"],
    )
    accepted = await fixture.verifier.get_verification_for_settlement(
        parent_agent_task_id="parent",
        delegated_agent_run_id=fixture.run["id"],
        verification_evidence_id=verified["id"],
    )
    assert accepted["verification_state"] == "verified"

    with pytest.raises(DelegatedAgentWorkspaceVerificationError, match="not admissible"):
        await fixture.verifier.get_verification_for_settlement(
            parent_agent_task_id="parent",
            delegated_agent_run_id=fixture.run["id"],
            verification_evidence_id=fixture.artifact["id"],
        )
