"""Contract tests for the opt-in production-local ledger validation harness."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


def _load_harness():
    harness_path = Path(__file__).with_name("live_work_ledger_validation.py")
    spec = importlib.util.spec_from_file_location("live_work_ledger_validation", harness_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def test_live_harness_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv(harness.LIVE_OPT_IN_ENV, raising=False)

    with pytest.raises(ValueError, match="BASIL_LIVE_WORK_LEDGER_VALIDATION=1"):
        harness.load_configuration()


def test_live_harness_rejects_missing_database_before_api_access(monkeypatch, tmp_path):
    monkeypatch.setenv(harness.LIVE_OPT_IN_ENV, "1")
    monkeypatch.setenv(harness.DATABASE_ENV, str(tmp_path / "missing.db"))
    monkeypatch.setenv(harness.EVIDENCE_PATH_ENV, str(tmp_path / "evidence.json"))
    monkeypatch.setenv(harness.DATE_FROM_ENV, "2026-07-01")
    monkeypatch.setenv(harness.DATE_TO_ENV, "2026-07-02")

    with pytest.raises(ValueError, match="Knowledge database does not exist"):
        harness.load_configuration()


def test_port_discovery_has_no_default_fallback(tmp_path):
    with pytest.raises(ValueError, match="Current server port file is missing"):
        harness.discover_current_server_port(tmp_path / ".server_port")

    port_file = tmp_path / ".server_port"
    port_file.write_text("not-a-port")
    with pytest.raises(ValueError, match="Current server port file is invalid"):
        harness.discover_current_server_port(port_file)


def test_read_only_prompt_is_bounded_and_rejects_mail_writes():
    prompt = harness.build_read_only_mail_prompt(
        "Validation Inbox",
        "2026-07-01T00:00:00",
        "2026-07-02T00:00:00",
    )

    assert "get_email_metadata" in prompt
    assert "2026-07-01T00:00:00" in prompt
    assert "2026-07-02T00:00:00" in prompt
    for forbidden_action in ("compose", "draft", "send", "reply", "move", "delete"):
        assert forbidden_action in prompt


def test_generated_script_evidence_is_date_bounded_metadata_only():
    evidence = harness.generated_mail_script_evidence(
        "inbox",
        "2026-07-01T00:00:00",
        "2026-07-02T00:00:00",
    )

    assert len(evidence["sha256"]) == 64
    assert evidence["input"]["folder"] == "inbox"
    assert evidence["contract"] == {
        "metadata_only": True,
        "date_bounded": True,
        "no_mail_write_tokens": True,
    }


def test_read_ledger_evidence_uses_read_only_queries(tmp_path):
    database_path = tmp_path / "knowledge.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE agent_work_sessions (
                id TEXT, root_task_id TEXT, scope_json TEXT, status TEXT,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE agent_work_receipts (
                id TEXT, session_id TEXT, agent_task_id TEXT, service TEXT,
                method TEXT, receipt_key TEXT, requested_effect_json TEXT,
                execution_state TEXT, verification_status TEXT, evidence_json TEXT,
                discrepancy_json TEXT, created_at TEXT
            );
            CREATE TABLE agent_work_items (
                id TEXT, session_id TEXT, external_id TEXT, created_at TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO agent_work_sessions VALUES (?, ?, ?, ?, ?, ?)",
            ("session-1", "root-1", json.dumps({"coverage": {"scanned": "1"}}), "active", "a", "b"),
        )
        connection.execute(
            "INSERT INTO agent_work_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "receipt-1",
                "session-1",
                "root-1",
                "email_service",
                "get_email_metadata",
                "tool-1",
                json.dumps({"material_write": False}),
                "succeeded",
                "not_applicable",
                json.dumps({"result": {"coverage_metadata": {"scanned": "1"}}}),
                "{}",
                "c",
            ),
        )
        connection.execute(
            "INSERT INTO agent_work_items VALUES (?, ?, ?, ?)",
            ("item-1", "session-1", "message-1", "c"),
        )

    evidence = harness.read_ledger_evidence(database_path, "root-1")

    assert evidence["session_count"] == 1
    assert evidence["receipt_count"] == 1
    assert evidence["item_count"] == 1
    assert evidence["receipts"][0]["requested_effect"]["material_write"] is False


def test_capture_validation_requires_matching_receipt_and_output_coverage():
    with pytest.raises(RuntimeError, match="No observable"):
        harness.validate_capture_evidence(
            {"sessions": [], "receipts": []},
            "root-1",
        )

    validation = harness.validate_capture_evidence(
        {
            "sessions": [{"scope": {"coverage": {"scanned": "1"}}}],
            "item_count": 1,
            "receipts": [
                {
                    "agent_task_id": "root-1",
                    "service": "email_service",
                    "method": "get_email_metadata",
                    "receipt_key": "email-call-1",
                    "requested_effect": {"material_write": False},
                    "evidence": {},
                }
            ],
        },
        "root-1",
    )

    assert validation == {
        "matching_receipt_count": 1,
        "output_coverage": [{"scanned": "1"}],
        "item_count": 1,
    }


def test_capture_validation_rejects_duplicate_email_receipts():
    receipt = {
        "agent_task_id": "root-1",
        "service": "email_service",
        "method": "get_email_metadata",
        "receipt_key": "email-call-1",
        "requested_effect": {"material_write": False},
        "evidence": {},
    }

    with pytest.raises(RuntimeError, match="exactly one"):
        harness.validate_capture_evidence(
            {
                "sessions": [{"scope": {"coverage": {"scanned": "1"}}}],
                "item_count": 1,
                "receipts": [receipt, {**receipt, "receipt_key": "email-call-2"}],
            },
            "root-1",
        )
