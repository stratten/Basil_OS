"""Read-only approval gate, locked results, evidence capture, and scoped cleanup for the routing accuracy check."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import routing_accuracy_check as cli  # noqa: E402
from routing_accuracy_core import runner as runner_module  # noqa: E402
from routing_accuracy_core.cases import build_cases  # noqa: E402
from routing_accuracy_core.cleanup import CleanupRefused, _delete_residue, plan_cleanup, run_cleanup  # noqa: E402
from routing_accuracy_core.evidence import collect_evidence, evidence_path_for, validate_evidence  # noqa: E402
from routing_accuracy_core.locked_store import LockedStoreError, digest_path, lock_existing, verify_locked, write_locked  # noqa: E402
from routing_accuracy_core.read_only_gate import MAX_AUTO_APPROVALS_PER_CASE, judge_approval  # noqa: E402
from routing_accuracy_core.report import build_document, save_document  # noqa: E402
from routing_accuracy_core.route_tokens import PASS, RoutingVerdict  # noqa: E402
from routing_accuracy_core.runner import BackendClient, CaseResult, _release_read_only, run_case  # noqa: E402
from routing_accuracy_core.task_scope import count_rows, discover, open_read_only, other_references  # noqa: E402


def _id() -> str:
    return str(uuid.uuid4())


# ------------------------------------------------------------------ the approval gate


def _card(execution_type="shell", command="ls -la", script=None, risk="low", approval_id="ap-1"):
    return {"approval_id": approval_id, "execution_type": execution_type, "command": command, "script_content": script, "risk_level": risk, "revision": 0}


@pytest.mark.parametrize("command", ["ls -la", "cat notes.txt | head -5", "bash -lc 'ls -la'", "env"])
def test_the_gate_approves_a_shell_command_the_classifier_proves_read_only(command):
    assert judge_approval(_card(command=command)).approve is True


@pytest.mark.parametrize(
    "command",
    ["mkdir /tmp/x", "python3 -c 'print(1)'", "ls; rm x", "echo hi > f", "env touch /tmp/x", "curl https://example.com", "killall Mail"],
)
def test_the_gate_refuses_a_shell_command_that_is_not_proven_read_only(command):
    assert judge_approval(_card(command=command)).approve is False


def test_the_gate_approves_a_read_only_applescript_and_refuses_a_sending_one():
    read = 'tell application "Mail" to get subject of every message of inbox'
    send = 'tell application "Mail" to send (make new outgoing message with properties {subject:"x"})'
    assert judge_approval(_card("applescript", command="", script=read)).approve is True
    assert judge_approval(_card("applescript", command="", script=send)).approve is False


@pytest.mark.parametrize("kind", ["connect", "settings_change", "provider_permission", "browser_foreground_control", "browser_sensitive_fill", "", "mcp"])
def test_the_gate_never_approves_any_other_kind_of_card(kind):
    assert judge_approval(_card(kind, command="ls")).approve is False


@pytest.mark.parametrize("risk", ["high", "critical", "HIGH"])
def test_the_gate_refuses_a_high_risk_card_even_if_the_command_looks_read_only(risk):
    assert judge_approval(_card(command="ls", risk=risk)).approve is False


# ------------------------------------------------------------------ the runner's use of the gate


class _GateClient:
    """Pending cards stay listed until a decision is made. The status moves on once nothing is pending."""

    def __init__(self, cards, statuses=("awaiting_user_input", "completed")):
        self._cards = list(cards)
        self._statuses = list(statuses)
        self.events: list[str] = []
        self.approved: list[str] = []
        self.denied: list[str] = []
        self.canceled: list[str] = []
        self.submitted = None

    def submit(self, prompt, model_id, reference_paths):
        self.submitted = (prompt, model_id, reference_paths)
        return "task-1"

    def status(self, task_id):
        return self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]

    def pending_approvals(self, task_id):
        return [card for card in self._cards if card["approval_id"] not in self.approved + self.denied]

    def approve_approval(self, task_id, approval):
        self.events.append("approved")
        self.approved.append(approval["approval_id"])

    def deny_approval(self, task_id, approval):
        self.events.append("denied")
        self.denied.append(approval["approval_id"])

    def cancel(self, task_id):
        self.events.append("canceled")
        self.canceled.append(task_id)


def _ledger(tmp_path, receipts):
    database = tmp_path / "ledger.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE agent_work_receipts (agent_task_id TEXT, service TEXT, method TEXT, requested_effect_json TEXT, execution_state TEXT, created_at TEXT)"
    )
    for index, (service, method) in enumerate(receipts):
        connection.execute(
            "INSERT INTO agent_work_receipts VALUES (?, ?, ?, ?, 'succeeded', ?)", ("task-1", service, method, json.dumps({"parameters": {}}), f"2026-11-06 14:00:{index:02d}")
        )
    connection.commit()
    connection.close()
    return database


def _case(case_id):
    return next(c for c in build_cases() if c.case_id == case_id)


def test_a_read_only_card_is_approved_and_the_run_continues_to_its_own_end(tmp_path):
    database = _ledger(tmp_path, [("shell_service", "execute_command")])
    client = _GateClient([_card(command="ls -la")])

    result = run_case(client, _case("shell_no_reload"), "m1", None, database, sleep=lambda _s: None)

    assert client.approved == ["ap-1"] and client.denied == [] and client.canceled == []
    assert result.auto_approved == 1 and not result.canceled_by_check
    assert result.verdict.verdict == PASS


def test_a_card_that_is_not_read_only_is_still_scored_denied_and_canceled(tmp_path):
    database = _ledger(tmp_path, [])
    client = _GateClient([_card(command="mkdir /tmp/x")], statuses=("awaiting_user_input", "canceled"))

    result = run_case(client, _case("shell_no_reload"), "m1", None, database, sleep=lambda _s: None)

    assert client.approved == [] and client.denied == ["ap-1"] and client.events[-1] == "canceled"
    assert result.auto_approved == 0 and result.canceled_by_check
    assert result.verdict.route == ("svc:shell_service.execute_command",)


def test_a_read_only_card_beside_a_blocking_one_is_approved_and_the_other_is_denied(tmp_path):
    database = _ledger(tmp_path, [])
    cards = [_card(command="ls", approval_id="ap-read"), _card(command="mkdir /tmp/x", approval_id="ap-write")]
    client = _GateClient(cards, statuses=("awaiting_user_input", "canceled"))

    result = run_case(client, _case("shell_no_reload"), "m1", None, database, sleep=lambda _s: None)

    assert client.approved == ["ap-read"] and client.denied == ["ap-write"]
    assert result.auto_approved == 1


def test_a_card_approved_on_an_earlier_poll_is_not_approved_twice_or_treated_as_blocking():
    client = _GateClient([])
    card = _card(command="ls")

    blocking = _release_read_only(client, "task-1", [card], {"ap-1"})

    assert blocking == [] and client.approved == []


def test_after_the_per_case_limit_even_a_read_only_card_blocks():
    client = _GateClient([])
    released = {f"old-{index}" for index in range(MAX_AUTO_APPROVALS_PER_CASE)}

    blocking = _release_read_only(client, "task-1", [_card(command="ls", approval_id="ap-9")], released)

    assert [card["approval_id"] for card in blocking] == ["ap-9"] and client.approved == []


def test_a_decision_never_asks_the_backend_to_remember_the_choice(monkeypatch):
    sent = {}

    class _Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(runner_module.requests, "post", lambda url, json=None, **_k: sent.update(body=json, url=url) or _Response())

    BackendClient(token="t").approve_approval("task-1", _card())

    assert sent["body"]["approved"] is True and "remember_choice" not in sent["body"]
    assert sent["url"].endswith("/api/v1/agent-tasks/approval/decide")


def test_cancel_sends_the_json_body_the_route_requires_and_raises_when_the_backend_refuses(monkeypatch):
    sent = {}

    def fake_post(url, json=None, **_kwargs):
        sent.update(url=url, body=json)
        return _Reply(422)

    monkeypatch.setattr(runner_module.requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="422"):
        BackendClient(token="t").cancel("task-1")

    assert sent["url"].endswith("/api/v1/agent-tasks/sessions/task-1/cancel")
    assert isinstance(sent["body"], dict) and "reason" in sent["body"]


@pytest.mark.parametrize("ended_status", ["canceled", "failed"])
@pytest.mark.parametrize("case_id", ["file_read_text", "none_arithmetic"])
def test_a_task_that_was_canceled_or_failed_without_a_call_is_incomplete_not_an_answer_without_tools(tmp_path, ended_status, case_id):
    database = _ledger(tmp_path, [])

    result = run_case(_GateClient([], statuses=(ended_status,)), _case(case_id), "m1", tmp_path, database, sleep=lambda _s: None)

    assert result.verdict.verdict == "INCOMPLETE"


def test_a_task_that_completed_without_a_call_is_still_an_answer_without_tools(tmp_path):
    database = _ledger(tmp_path, [])

    result = run_case(_GateClient([], statuses=("completed",)), _case("none_arithmetic"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert result.verdict.verdict == "PASS"


def test_a_task_stopped_on_an_input_required_card_is_canceled_not_left_waiting(tmp_path):
    database = _ledger(tmp_path, [])
    client = _GateClient([], statuses=("awaiting_user_input", "canceled"))

    result = run_case(client, _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert client.canceled == ["task-1"]
    assert result.canceled_by_check and not result.still_running
    assert result.verdict.verdict == "FAIL"


def test_an_input_required_task_that_will_not_cancel_is_reported_as_still_running(tmp_path):
    database = _ledger(tmp_path, [])
    client = _GateClient([], statuses=("awaiting_user_input",))

    result = run_case(client, _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None, settle_timeout_s=0.01)

    assert client.canceled == ["task-1"] and result.still_running


def test_a_task_that_completed_is_not_canceled(tmp_path):
    database = _ledger(tmp_path, [])
    client = _GateClient([], statuses=("completed",))

    run_case(client, _case("none_arithmetic"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert client.canceled == []


def test_a_cancel_the_backend_refuses_is_reported_as_a_harness_error_not_a_quiet_success(tmp_path):
    database = _ledger(tmp_path, [("file_service", "read_text_file")] * 4)

    class _RefusingClient(_GateClient):
        def cancel(self, task_id):
            raise RuntimeError("422")

    result = run_case(_RefusingClient([], statuses=("processing",)), _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert "422" in result.error


# ------------------------------------------------------------------ the client's lookup and delete calls


class _Reply:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_a_connection_is_found_by_its_exact_display_name_only_when_it_is_unique(monkeypatch):
    connections = [{"id": "c1", "friendly_name": "Gmail - Basil"}, {"id": "c2", "friendly_name": "Gmail - Baobab"}]
    monkeypatch.setattr(runner_module.requests, "get", lambda *a, **k: _Reply(payload={"connections": connections}))
    client = BackendClient(token="t")

    assert client.connection_id_by_name("Gmail - Basil") == "c1"
    assert client.connection_id_by_name("Gmail") is None
    connections.append({"id": "c3", "friendly_name": "Gmail - Basil"})
    assert client.connection_id_by_name("Gmail - Basil") is None


@pytest.mark.parametrize("status,raises", [(200, False), (404, False), (500, True)])
def test_deleting_a_task_that_is_already_gone_counts_as_deleted(monkeypatch, status, raises):
    seen = {}
    monkeypatch.setattr(runner_module.requests, "delete", lambda url, params=None, **_k: seen.update(url=url, params=params) or _Reply(status))
    client = BackendClient(token="t")

    if raises:
        with pytest.raises(RuntimeError):
            client.delete_task("t1")
    else:
        client.delete_task("t1")
    assert seen["params"] == {"cascade": "false"}


# ------------------------------------------------------------------ locked files


def test_a_locked_file_is_read_only_verifies_and_is_never_overwritten(tmp_path):
    path = tmp_path / "run.json"

    digest = write_locked(path, {"a": 1})

    assert verify_locked(path) == {"a": 1}
    assert not os.stat(path).st_mode & 0o222
    assert digest_path(path).read_text().split()[0] == digest
    with pytest.raises(FileExistsError):
        write_locked(path, {"a": 2})
    assert verify_locked(path) == {"a": 1}


def test_a_locked_file_that_was_altered_or_made_writable_no_longer_verifies(tmp_path):
    path = tmp_path / "run.json"
    write_locked(path, {"a": 1})

    os.chmod(path, 0o644)
    with pytest.raises(LockedStoreError, match="writable"):
        verify_locked(path)
    path.write_text('{"a": 2}\n')
    os.chmod(path, 0o444)
    with pytest.raises(LockedStoreError, match="no longer matches"):
        verify_locked(path)


def test_a_file_without_a_digest_or_missing_entirely_does_not_verify(tmp_path):
    path = tmp_path / "run.json"
    with pytest.raises(LockedStoreError, match="does not exist"):
        verify_locked(path)
    path.write_text("{}\n")
    os.chmod(path, 0o444)
    with pytest.raises(LockedStoreError, match="sha256"):
        verify_locked(path)


def test_an_older_unlocked_file_can_be_locked_in_place_once(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"a": 1}\n')

    lock_existing(path)

    assert verify_locked(path) == {"a": 1}
    with pytest.raises(LockedStoreError, match="already has a digest"):
        lock_existing(path)


# ------------------------------------------------------------------ scope, evidence, cleanup


def _build_database(path: Path, mine: list[str], others: list[str]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, status TEXT, root_task_id TEXT, previous_task_id TEXT, result_data TEXT);
        CREATE TABLE agent_work_receipts (id INTEGER PRIMARY KEY, agent_task_id TEXT REFERENCES agent_tasks(id) ON DELETE SET NULL, service TEXT, method TEXT, blob BLOB);
        CREATE TABLE agent_work_sessions (id TEXT PRIMARY KEY, agent_task_id TEXT REFERENCES agent_tasks(id) ON DELETE SET NULL, root_task_id TEXT);
        CREATE TABLE agent_checklist_items (id INTEGER PRIMARY KEY, session_id TEXT, text TEXT, created_by_task_id TEXT);
        CREATE TABLE execution_approvals (id TEXT PRIMARY KEY, agent_task_id TEXT, root_task_id TEXT, status TEXT, command TEXT);
        CREATE TABLE unrelated (id INTEGER PRIMARY KEY, note TEXT);
        CREATE VIRTUAL TABLE agent_task_search_fts USING fts5(root_task_id UNINDEXED, content);
        """
    )
    for task_id in mine + others:
        connection.execute("INSERT INTO agent_tasks VALUES (?, 'completed', ?, NULL, ?)", (task_id, task_id, f"answer for {task_id}"))
        connection.execute("INSERT INTO agent_work_receipts (agent_task_id, service, method, blob) VALUES (?, 'shell_service', 'execute_command', ?)", (task_id, b"\x00\x01"))
        connection.execute("INSERT INTO agent_work_sessions VALUES (?, ?, ?)", (f"sess-{task_id}", task_id, task_id))
        connection.execute("INSERT INTO agent_checklist_items (session_id, text, created_by_task_id) VALUES (?, 'step', ?)", (f"sess-{task_id}", task_id))
        connection.execute("INSERT INTO execution_approvals VALUES (?, ?, ?, 'denied', 'ls')", (f"ap-{task_id}", task_id, task_id))
        connection.execute("INSERT INTO agent_task_search_fts (root_task_id, content) VALUES (?, 'text')", (task_id,))
    connection.execute("INSERT INTO unrelated (note) VALUES ('keep')")
    # A receipt left detached by some earlier, unrelated task deletion. Cleanup must leave it alone.
    connection.execute("INSERT INTO agent_work_receipts (agent_task_id, service, method) VALUES (NULL, 'old_service', 'old_method')")
    connection.commit()
    connection.close()


@pytest.fixture
def world(tmp_path):
    mine, others = [_id(), _id()], [_id()]
    database = tmp_path / "kb.db"
    _build_database(database, mine, others)
    return database, mine, others


def _count(database, sql, *args):
    connection = sqlite3.connect(database)
    try:
        return connection.execute(sql, args).fetchone()[0]
    finally:
        connection.close()


class _DeletingClient:
    """Stands in for the app's delete route: it removes the task row with foreign keys on, so receipts and sessions are detached (task id set to NULL) rather than deleted, exactly as in the real database."""

    def __init__(self, database):
        self._database = database
        self.deleted: list[str] = []

    def delete_task(self, task_id):
        self.deleted.append(task_id)
        connection = sqlite3.connect(self._database)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM agent_tasks WHERE id = ?", (task_id,))
        connection.commit()
        connection.close()


def test_scope_counts_only_this_runs_rows_in_every_table_that_holds_them(world):
    database, mine, _others = world
    connection = open_read_only(database)

    counts = count_rows(connection, discover(connection, mine))

    assert counts == {
        "agent_tasks": 2, "agent_work_receipts": 2, "agent_work_sessions": 2, "execution_approvals": 2,
        "agent_task_search_fts": 2, "session:agent_checklist_items": 2,
    }
    assert "unrelated" not in counts


def test_a_follow_up_task_under_one_of_these_roots_is_reported_as_another_reference(world):
    database, mine, _others = world
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO agent_tasks VALUES (?, 'completed', ?, ?, NULL)", (_id(), mine[0], mine[0]))
    connection.commit()
    connection.close()
    reader = open_read_only(database)

    found = other_references(reader, discover(reader, mine))

    assert found == {"agent_tasks.root_task_id": 1, "agent_tasks.previous_task_id": 1}


def test_a_pointer_from_a_row_already_in_scope_is_not_an_outside_reference_but_one_from_elsewhere_is(world):
    database, mine, _others = world
    reader = open_read_only(database)
    assert other_references(reader, discover(reader, mine)) == {}
    reader.close()
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO agent_checklist_items (session_id, text, created_by_task_id) VALUES ('another-session', 'x', ?)", (mine[0],))
    connection.commit()
    connection.close()
    reader = open_read_only(database)

    assert other_references(reader, discover(reader, mine)) == {"agent_checklist_items.created_by_task_id": 1}


def test_evidence_holds_every_counted_row_except_the_search_index_and_validates(world):
    database, mine, _others = world

    evidence = collect_evidence(database, mine)

    assert evidence["row_counts"]["agent_tasks"] == 2
    assert {row["id"] for row in evidence["tables"]["agent_tasks"]} == set(mine)
    assert evidence["tables"]["agent_work_receipts"][0]["blob"] == "<2 bytes>"
    assert len(evidence["session_tables"]["agent_checklist_items"]) == 2
    assert evidence["derived_tables_not_captured"] == ["agent_task_search_fts"]
    validate_evidence(evidence, mine)


def test_evidence_that_covers_other_tasks_or_lost_rows_does_not_validate(world):
    database, mine, others = world
    evidence = collect_evidence(database, mine)

    with pytest.raises(ValueError, match="exactly the task ids"):
        validate_evidence(evidence, mine + others)
    evidence["tables"]["agent_tasks"].pop()
    with pytest.raises(ValueError, match="holds 1 rows for agent_tasks but counted 2"):
        validate_evidence(evidence, mine)


def test_a_very_long_value_is_cut_and_the_cut_is_recorded(world):
    database, mine, _others = world
    connection = sqlite3.connect(database)
    connection.execute("UPDATE agent_tasks SET result_data = ? WHERE id = ?", ("x" * 60_000, mine[0]))
    connection.commit()
    connection.close()

    evidence = collect_evidence(database, mine)

    kept = next(row for row in evidence["tables"]["agent_tasks"] if row["id"] == mine[0])["result_data"]
    assert kept.endswith("[truncated 10000 characters]") and evidence["truncated_values"] == 1


def test_the_plan_names_every_reason_cleanup_must_not_start(world):
    database, mine, _others = world
    snapshot = collect_evidence(database, mine)["row_counts"]
    connection = sqlite3.connect(database)
    connection.execute("UPDATE agent_tasks SET status = 'processing' WHERE id = ?", (mine[0],))
    connection.execute("UPDATE execution_approvals SET status = 'pending' WHERE agent_task_id = ?", (mine[1],))
    connection.execute("INSERT INTO agent_work_receipts (agent_task_id, service, method) VALUES (?, 's', 'm')", (mine[1],))
    connection.commit()
    connection.close()

    blockers = plan_cleanup(database, mine, snapshot).blockers

    assert any("still active" in text for text in blockers)
    assert any("approval card(s) are still pending" in text for text in blockers)
    assert any("rows changed since the snapshot" in text for text in blockers)


def test_something_that_is_not_a_task_id_is_refused_before_the_database_is_opened(tmp_path):
    with pytest.raises(CleanupRefused, match="not task ids"):
        plan_cleanup(tmp_path / "missing.db", [""], None)


def test_cleanup_removes_this_runs_rows_everywhere_and_nothing_else(world):
    database, mine, others = world
    snapshot = collect_evidence(database, mine)["row_counts"]
    client = _DeletingClient(database)

    outcome = run_cleanup(client, database, mine, snapshot)

    assert sorted(client.deleted) == sorted(mine) and outcome["remaining"] == {}
    marks = ",".join("?" * len(mine))
    for table, column in (("agent_tasks", "id"), ("agent_work_receipts", "agent_task_id"), ("agent_work_sessions", "agent_task_id"), ("execution_approvals", "agent_task_id"), ("agent_task_search_fts", "root_task_id")):
        assert _count(database, f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({marks})", *mine) == 0
    assert _count(database, "SELECT COUNT(*) FROM agent_checklist_items WHERE session_id LIKE 'sess-%'") == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_tasks WHERE id = ?", others[0]) == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE agent_task_id = ?", others[0]) == 1
    assert _count(database, "SELECT COUNT(*) FROM unrelated") == 1


def test_cleanup_removes_the_receipts_and_sessions_the_delete_route_detaches_and_leaves_older_orphans_alone(world):
    database, mine, _others = world
    snapshot = collect_evidence(database, mine)["row_counts"]

    run_cleanup(_DeletingClient(database), database, mine, snapshot)

    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE agent_task_id IS NULL") == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE service = 'old_service'") == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts") == 2
    assert _count(database, "SELECT COUNT(*) FROM agent_work_sessions WHERE agent_task_id IS NULL") == 0
    assert _count(database, "SELECT COUNT(*) FROM agent_work_sessions") == 1


def test_cleanup_deletes_nothing_when_a_precondition_fails(world):
    database, mine, _others = world
    snapshot = collect_evidence(database, mine)["row_counts"]
    connection = sqlite3.connect(database)
    connection.execute("UPDATE agent_tasks SET status = 'processing' WHERE id = ?", (mine[0],))
    connection.commit()
    connection.close()
    client = _DeletingClient(database)

    with pytest.raises(CleanupRefused, match="still active"):
        run_cleanup(client, database, mine, snapshot)

    assert client.deleted == [] and _count(database, "SELECT COUNT(*) FROM agent_work_receipts") == 4


def test_the_row_deletes_are_one_transaction_so_a_failure_leaves_everything_in_place(world):
    database, mine, _others = world
    connection = sqlite3.connect(database)
    connection.execute("CREATE TRIGGER stop_receipt_delete BEFORE DELETE ON agent_work_receipts BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    connection.commit()
    connection.close()
    reader = open_read_only(database)
    scope = discover(reader, mine)
    reader.close()

    with pytest.raises(sqlite3.DatabaseError):
        _delete_residue(database, scope)

    assert _count(database, "SELECT COUNT(*) FROM agent_checklist_items") == 3
    assert _count(database, "SELECT COUNT(*) FROM execution_approvals") == 3


def _orphan_what_an_old_cleanup_left(database, mine):
    """Reproduce an old cleanup: the delete route detaches receipts and sessions, and nothing deletes them afterward."""
    client = _DeletingClient(database)
    for task_id in mine:
        client.delete_task(task_id)


def test_repair_removes_only_the_detached_rows_the_snapshot_recorded(world):
    from routing_accuracy_core.cleanup import repair_orphans

    database, mine, _others = world
    evidence = collect_evidence(database, mine)
    _orphan_what_an_old_cleanup_left(database, mine)
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE agent_task_id IS NULL") == 3

    removed = repair_orphans(database, evidence)

    assert removed == {"agent_work_receipts": 2, "agent_work_sessions": 2}
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE service = 'old_service'") == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts") == 2
    assert repair_orphans(database, evidence) == {}


def test_a_repair_dry_run_reports_the_rows_and_deletes_nothing(world):
    from routing_accuracy_core.cleanup import repair_orphans

    database, mine, _others = world
    evidence = collect_evidence(database, mine)
    _orphan_what_an_old_cleanup_left(database, mine)

    assert repair_orphans(database, evidence, dry_run=True) == {"agent_work_receipts": 2, "agent_work_sessions": 2}
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts") == 4


def test_repair_leaves_a_detached_row_alone_when_it_no_longer_matches_what_was_captured(world):
    from routing_accuracy_core.cleanup import repair_orphans

    database, mine, _others = world
    evidence = collect_evidence(database, mine)
    _orphan_what_an_old_cleanup_left(database, mine)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE agent_work_receipts SET method = 'changed later' WHERE agent_task_id IS NULL AND service = 'shell_service' AND id = (SELECT MIN(id) FROM agent_work_receipts WHERE service = 'shell_service')")
    connection.commit()
    connection.close()

    assert repair_orphans(database, evidence)["agent_work_receipts"] == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE method = 'changed later'") == 1


def test_the_repair_command_needs_verified_files_and_then_removes_the_detached_rows(world, tmp_path):
    database, mine, _others = world
    results = _results_file(tmp_path / "run.json", mine)
    assert cli._finalize(results, database, cleanup=False, dry_run=False) == 0
    _orphan_what_an_old_cleanup_left(database, mine)

    assert cli._repair(results, database, dry_run=False) == 0

    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts") == 2
    os.chmod(evidence_path_for(results), 0o644)
    assert cli._repair(results, database, dry_run=False) == 2


# ------------------------------------------------------------------ prompts whose answer is already in the model's context


def test_a_prompt_answerable_from_context_passes_with_no_tools_or_the_preferred_tool_but_not_a_forbidden_route():
    from routing_accuracy_core.route_tokens import Receipt, score_route

    expectation = _case("external_list_connections").expectation
    listed = Receipt("direct_tool", "external_catalog", {"action": "list_servers"})
    scripted = Receipt("applescript_service", "execute_applescript", {})

    assert score_route(expectation, [], run_finished=True).verdict == PASS
    assert score_route(expectation, [], run_finished=False).verdict == "INCOMPLETE"
    assert score_route(expectation, [listed], run_finished=True).verdict == PASS
    assert score_route(expectation, [scripted], run_finished=True).verdict == "FAIL"


def test_answering_without_tools_is_still_a_failure_for_a_prompt_that_needs_a_tool():
    from routing_accuracy_core.route_tokens import score_route

    verdict = score_route(_case("file_read_text").expectation, [], run_finished=True)

    assert verdict.verdict == "FAIL" and "without using any tool" in verdict.reason


# ------------------------------------------------------------------ the command line


def _results_file(path: Path, task_ids: list[str]) -> Path:
    verdict = RoutingVerdict(PASS, "ok", ("svc:shell_service.execute_command",), ("svc:shell_service.execute_command",), 0, 1)
    results = [CaseResult(f"case_{index}", "shell", "m1", task_id, verdict, "completed", 1.0, False) for index, task_id in enumerate(task_ids)]
    save_document(build_document(results, 4), path)
    return path


def test_finalize_locks_the_results_captures_the_evidence_and_leaves_the_rows_without_cleanup(world, tmp_path):
    database, mine, _others = world
    results = _results_file(tmp_path / "run.json", mine)

    assert cli._finalize(results, database, cleanup=False, dry_run=False) == 0

    assert verify_locked(results)["models"]["m1"]
    assert verify_locked(evidence_path_for(results))["task_ids"] == sorted(mine)
    assert _count(database, "SELECT COUNT(*) FROM agent_tasks") == 3


def test_finalize_with_cleanup_deletes_only_after_both_files_verify(world, tmp_path, monkeypatch):
    database, mine, others = world
    results = _results_file(tmp_path / "run.json", mine)
    monkeypatch.setattr(cli, "BackendClient", lambda: _DeletingClient(database))

    assert cli._finalize(results, database, cleanup=True, dry_run=False) == 0

    assert _count(database, "SELECT COUNT(*) FROM agent_tasks") == 1
    assert _count(database, "SELECT COUNT(*) FROM agent_work_receipts WHERE agent_task_id = ?", others[0]) == 1
    captured = verify_locked(evidence_path_for(results))
    assert {row["id"] for row in captured["tables"]["agent_tasks"]} == set(mine)


def test_finalize_refuses_to_clean_up_when_the_evidence_file_was_tampered_with(world, tmp_path, monkeypatch):
    database, mine, _others = world
    results = _results_file(tmp_path / "run.json", mine)
    assert cli._finalize(results, database, cleanup=False, dry_run=False) == 0
    evidence = evidence_path_for(results)
    os.chmod(evidence, 0o644)
    evidence.write_text("{}\n")
    os.chmod(evidence, 0o444)
    monkeypatch.setattr(cli, "BackendClient", lambda: _DeletingClient(database))

    assert cli._finalize(results, database, cleanup=True, dry_run=False) == 2

    assert _count(database, "SELECT COUNT(*) FROM agent_tasks") == 3


def test_a_dry_run_reports_blockers_and_deletes_nothing(world, tmp_path, capsys):
    database, mine, _others = world
    results = _results_file(tmp_path / "run.json", mine)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE agent_tasks SET status = 'processing' WHERE id = ?", (mine[0],))
    connection.commit()
    connection.close()

    assert cli._finalize(results, database, cleanup=True, dry_run=True) == 2

    assert "still active" in capsys.readouterr().out
    assert _count(database, "SELECT COUNT(*) FROM agent_tasks") == 3


def test_cleanup_without_out_and_an_existing_out_path_are_refused_before_any_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check", "--model", "m1", "--cleanup"])
    with pytest.raises(SystemExit, match="--cleanup needs --out"):
        cli.main()

    existing = tmp_path / "run.json"
    existing.write_text("{}")
    monkeypatch.setattr(sys, "argv", ["check", "--model", "m1", "--out", str(existing)])
    with pytest.raises(SystemExit, match="already exists"):
        cli.main()
