"""Contract tests for the tool-scenario smoke harness definitions."""

import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from model_scenario_smoke_core.ledger_evidence import (  # noqa: E402
    all_required_groups_satisfied,
    any_expected_invoked,
    invoked_service_methods,
)
from model_scenario_smoke_core.scenarios import MIXED_TOOL_SCENARIO_IDS  # noqa: E402
from model_scenario_smoke_core.tool_scenarios import (  # noqa: E402
    FAMILY_TO_TOOL_SCENARIO_ID,
    TOOL_SCENARIO_SPECS,
    distinct_families_for_spec,
)


def test_every_family_except_core_has_a_tool_scenario():
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
        get_family_names,
    )

    for family_name in get_family_names():
        if family_name == "core":
            continue
        assert family_name in FAMILY_TO_TOOL_SCENARIO_ID, (
            f"missing tool scenario for family {family_name!r}"
        )
        scenario_id = FAMILY_TO_TOOL_SCENARIO_ID[family_name]
        assert scenario_id in TOOL_SCENARIO_SPECS
        assert TOOL_SCENARIO_SPECS[scenario_id].family == family_name


def test_ledger_evidence_reads_distinct_service_methods(tmp_path):
    database_path = tmp_path / "knowledge.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE agent_work_receipts (
                id TEXT, session_id TEXT, agent_task_id TEXT, service TEXT,
                method TEXT, receipt_key TEXT, requested_effect_json TEXT,
                execution_state TEXT, verification_status TEXT, evidence_json TEXT,
                discrepancy_json TEXT, created_at TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO agent_work_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "receipt-1",
                "session-1",
                "task-1",
                "shell_service",
                "execute_command",
                "tool-1",
                "{}",
                "succeeded",
                "verified",
                "{}",
                "{}",
                "a",
            ),
        )
        connection.execute(
            "INSERT INTO agent_work_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "receipt-2",
                "session-1",
                "task-1",
                "email_service",
                "get_email_metadata",
                "tool-2",
                "{}",
                "succeeded",
                "not_applicable",
                "{}",
                "{}",
                "b",
            ),
        )

    invoked = invoked_service_methods(database_path, "task-1")
    assert invoked == {
        ("shell_service", "execute_command"),
        ("email_service", "get_email_metadata"),
    }
    assert any_expected_invoked(
        database_path,
        "task-1",
        (("shell_service", "execute_command"),),
    )
    assert not any_expected_invoked(
        database_path,
        "task-1",
        (("direct_tool", "web_search"),),
    )
    assert all_required_groups_satisfied(
        database_path,
        "task-1",
        (
            (("shell_service", "execute_command"),),
            (("email_service", "get_email_metadata"),),
        ),
    )
    assert not all_required_groups_satisfied(
        database_path,
        "task-1",
        (
            (("shell_service", "execute_command"),),
            (("direct_tool", "web_search"),),
        ),
    )


def test_mixed_scenarios_expect_at_least_two_distinct_families():
    for scenario_id in MIXED_TOOL_SCENARIO_IDS:
        spec = TOOL_SCENARIO_SPECS[scenario_id]
        families = distinct_families_for_spec(spec)
        assert len(families) >= 2, (
            f"{scenario_id} should cover at least two families, got {sorted(families)}"
        )
