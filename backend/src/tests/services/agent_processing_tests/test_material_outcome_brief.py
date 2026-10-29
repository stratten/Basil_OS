"""Tests for compact, receipt-grounded material-outcome evidence briefs."""

from __future__ import annotations

import json

from api.services.agent_processing.shared.material_outcome_brief import (
    build_material_outcome_brief,
    summarize_material_effects,
)


def _material_step(
    verification_status: str,
    *,
    effect: dict | None = None,
    discrepancy: dict | None = None,
) -> dict:
    return {
        "result": {
            "material_operation": {
                "contract_version": 1,
                "material_write": True,
                "receipts": [
                    {
                        "entity": {
                            "entity_type": "message",
                            "source_system": "mail",
                            "source_scope": {"account": "primary"},
                            "external_id": f"message-{verification_status}",
                        },
                        "requested_effect": effect or {"operation": "move", "folder": "Archive"},
                        "execution_state": (
                            "failed"
                            if verification_status == "failed"
                            else "succeeded"
                        ),
                        "observed_postcondition": (
                            {"folder": "Archive"}
                            if verification_status == "verified"
                            else {}
                        ),
                        "verification_status": verification_status,
                        "evidence": (
                            {"readback": "matched"}
                            if verification_status == "verified"
                            else {}
                        ),
                        "discrepancy": discrepancy or {},
                    }
                ],
            }
        }
    }


def test_build_material_outcome_brief_returns_none_without_material_receipts():
    assert build_material_outcome_brief(
        [{"result": {"count": 3}}]
    ) is None


def test_build_material_outcome_brief_allows_verified_effect_claims():
    brief = build_material_outcome_brief([_material_step("verified")])

    assert brief is not None
    assert "Verified changes you may state as done" in brief
    assert '{"folder":"Archive","operation":"move"}' in brief
    assert "not confirmed" not in brief


def test_build_material_outcome_brief_forbids_unverified_completion_claims():
    brief = build_material_outcome_brief([_material_step("unverified")])

    assert brief is not None
    assert "do not state these as completed" in brief
    assert "attempted or uncertain" in brief


def test_build_material_outcome_brief_includes_failed_discrepancy():
    brief = build_material_outcome_brief(
        [
            _material_step(
                "failed",
                discrepancy={"expected_folder": "Archive", "actual_folder": "Inbox"},
            )
        ]
    )

    assert brief is not None
    assert "Changes that failed" in brief
    assert '"actual_folder":"Inbox"' in brief


def test_identical_effects_are_deduplicated_without_a_count():
    effect = {"operation": "move", "folder": "Archive"}
    brief = build_material_outcome_brief(
        [
            _material_step("verified", effect=effect),
            _material_step("verified", effect=effect),
        ]
    )

    assert brief is not None
    assert brief.count(json.dumps(effect, sort_keys=True, separators=(",", ":"))) == 1
    assert "receipt_count" not in brief


def test_more_than_six_distinct_effects_are_bounded_without_counting():
    brief = build_material_outcome_brief(
        [
            _material_step(
                "verified",
                effect={"operation": "tag", "label": f"label-{index}"},
            )
            for index in range(7)
        ]
    )

    assert brief is not None
    assert brief.count('"operation":"tag"') == 6
    assert "and other changes" in brief
    assert "7" not in brief


def test_later_verified_receipt_resolves_same_effect_for_backstop():
    effect = {"operation": "create", "kind": "calendar_draft"}
    summary = summarize_material_effects(
        [
            _material_step("unverified", effect=effect),
            _material_step("verified", effect=effect),
        ]
    )

    assert summary.verified_effects == (
        '{"kind":"calendar_draft","operation":"create"}',
    )
    assert summary.has_unresolved is False
