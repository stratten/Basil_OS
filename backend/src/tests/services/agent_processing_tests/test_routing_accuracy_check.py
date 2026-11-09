"""Tests for the routing accuracy check: scoring, ledger reading, comparison, case definitions, fixture, and the runner against a fake backend."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from routing_accuracy_core import fixture as fixture_module  # noqa: E402
from routing_accuracy_core.cases import FIXTURE_DIR_TOKEN, alt, build_cases  # noqa: E402
from routing_accuracy_core.ledger_reader import read_receipts  # noqa: E402
from routing_accuracy_core.report import (  # noqa: E402
    build_document,
    compare,
    has_regression,
    load_document,
    render_comparison,
    render_text,
    save_document,
    summarize,
)
from routing_accuracy_core.route_tokens import (  # noqa: E402
    FAIL,
    INCOMPLETE,
    PASS,
    PASS_ALT,
    Receipt,
    RoutingExpectation,
    score_route,
    substantive_window,
    tokens_for,
    with_implied_loads,
)
from routing_accuracy_core.runner import CaseResult, run_case  # noqa: E402


def _direct(method: str, **parameters) -> Receipt:
    return Receipt("direct_tool", method, parameters)


def _load(*families: str) -> Receipt:
    return _direct("load_tool_family", family_names=list(families))


def _svc(service: str, method: str) -> Receipt:
    return Receipt(service, method, {})


# ---------------------------------------------------------------- tokens


def test_tokens_name_each_loaded_family_and_normalize_case():
    assert tokens_for(_load("File", " external ")) == ("load:file", "load:external")


def test_tokens_accept_a_single_string_family_and_ignore_malformed_family_names():
    assert tokens_for(_direct("load_tool_family", family_names="shell")) == ("load:shell",)
    assert tokens_for(_direct("load_tool_family", family_names=None)) == ()
    assert tokens_for(_direct("load_tool_family", family_names=[""])) == ()


def test_tokens_for_external_catalog_carry_the_connection_only_for_call_tool():
    assert tokens_for(_direct("external_catalog", action="list_servers")) == ("ext:list_servers",)
    assert tokens_for(_direct("external_catalog", action="call_tool", connection_id="abc")) == ("ext:call_tool", "ext:call_tool@abc")
    assert tokens_for(_direct("external_catalog")) == ("ext:unknown",)


def test_tokens_for_other_direct_and_service_tools():
    assert tokens_for(_direct("web_search", query="x")) == ("tool:web_search",)
    assert tokens_for(_svc("shell_service", "execute_command")) == ("svc:shell_service.execute_command",)


def test_bookkeeping_tools_do_not_count_toward_the_window():
    receipts = [_direct("checklist"), _direct("skill_search"), _load("file"), _direct("checklist_notes"), _svc("file_service", "read_text_file")]

    window = substantive_window(receipts, window_size=4)

    assert [r.method for r in window] == ["load_tool_family", "read_text_file"]


def test_the_window_stops_at_its_size():
    receipts = [_direct("web_search")] * 9

    assert len(substantive_window(receipts, window_size=4)) == 4


# ---------------------------------------------------------------- scoring


_FILE_EXPECTATION = RoutingExpectation(
    preferred=(alt("load:file"), alt("svc:file_service.*")),
    acceptable=(alt("svc:shell_service.execute_command"),),
    forbidden=("svc:applescript_service.*",),
)


def test_a_preferred_route_passes():
    verdict = score_route(_FILE_EXPECTATION, [_load("file"), _svc("file_service", "read_text_file")], run_finished=False)

    assert verdict.verdict == PASS
    assert verdict.first_call == ("load:file",)
    assert verdict.load_calls == 1


def test_an_acceptable_route_is_pass_alt_not_pass():
    verdict = score_route(_FILE_EXPECTATION, [_svc("shell_service", "execute_command")], run_finished=True)

    assert verdict.verdict == PASS_ALT


def test_a_forbidden_route_fails_even_when_a_preferred_route_is_also_present():
    receipts = [_load("file"), _svc("applescript_service", "execute_applescript")]

    verdict = score_route(_FILE_EXPECTATION, receipts, run_finished=False)

    assert verdict.verdict == FAIL
    assert verdict.forbidden_hits == ("svc:applescript_service.*",)


def test_an_unexpected_route_fails_once_the_window_is_full():
    receipts = [_direct("web_search")] * 4

    verdict = score_route(_FILE_EXPECTATION, receipts, run_finished=False, window_size=4)

    assert verdict.verdict == FAIL
    assert "no preferred or acceptable route" in verdict.reason


def test_an_unfinished_short_window_is_incomplete_not_a_failure():
    verdict = score_route(_FILE_EXPECTATION, [_direct("web_search")], run_finished=False, window_size=4)

    assert verdict.verdict == INCOMPLETE


def test_answering_without_tools_fails_a_tool_case_once_the_run_finished():
    verdict = score_route(_FILE_EXPECTATION, [], run_finished=True)

    assert verdict.verdict == FAIL
    assert "without using any tool" in verdict.reason


def test_a_multi_pattern_alternative_needs_every_pattern():
    expectation = RoutingExpectation(preferred=(alt("load:file", "load:external"),))

    assert score_route(expectation, [_load("file")], run_finished=True).verdict == FAIL
    assert score_route(expectation, [_load("file"), _load("external")], run_finished=False).verdict == PASS
    assert score_route(expectation, [_load("file", "external")], run_finished=False).verdict == PASS


# ------------------------------------------------------- call-through (implied loads)


_FAMILIES_BY_TOOL = {
    "file_service_prepare_file_by_path": ["file"],
    "web_search": ["external"],
    "browser_tabs": ["browser"],
    "shell_service_execute_command": [],
}


def _resolve(tool_name: str) -> list[str]:
    return list(_FAMILIES_BY_TOOL.get(tool_name, []))


def test_a_direct_call_to_an_unloaded_tool_scores_as_its_load_plus_the_call():
    expanded = with_implied_loads([_direct("web_search")], _resolve)

    assert [tokens_for(receipt) for receipt in expanded] == [("load:external",), ("tool:web_search",)]
    assert expanded[0].implied is True
    assert expanded[1].implied is False


def test_a_family_loaded_explicitly_first_adds_no_implied_load():
    expanded = with_implied_loads([_load("external"), _direct("web_search")], _resolve)

    assert [tokens_for(receipt) for receipt in expanded] == [("load:external",), ("tool:web_search",)]
    assert all(not receipt.implied for receipt in expanded)


def test_a_family_is_implied_only_once_and_always_bound_tools_never_imply_one():
    receipts = [_direct("web_search"), _direct("web_search"), _svc("shell_service", "execute_command")]

    expanded = with_implied_loads(receipts, _resolve)

    assert sum(1 for receipt in expanded if receipt.implied) == 1


def test_implied_loads_do_not_use_up_window_slots():
    receipts = [_direct("web_search"), _svc("file_service", "prepare_file_by_path"), _direct("browser_tabs"), _direct("browser_tabs"), _direct("web_search")]

    window = substantive_window(with_implied_loads(receipts, _resolve), window_size=4)

    assert [receipt.method for receipt in window if not receipt.implied] == ["web_search", "prepare_file_by_path", "browser_tabs", "browser_tabs"]


def test_a_two_family_task_solved_by_direct_calls_passes_a_two_load_expectation():
    expectation = RoutingExpectation(preferred=(alt("load:file", "load:external"),))
    receipts = [_direct("web_search"), _svc("file_service", "prepare_file_by_path")]

    assert score_route(expectation, receipts, run_finished=True).verdict == PASS


def test_direct_call_scoring_reports_the_call_with_its_load_as_the_first_call_and_counts_explicit_loads_only():
    verdict = score_route(RoutingExpectation(preferred=(alt("tool:web_search"),)), [_direct("web_search")], run_finished=True)

    assert verdict.verdict == PASS
    assert verdict.first_call == ("load:external", "tool:web_search")
    assert verdict.load_calls == 0
    assert verdict.substantive_calls == 1


def test_an_implied_load_still_trips_a_forbidden_load_pattern():
    expectation = RoutingExpectation(preferred=(alt("ext:list_servers"),), forbidden=("load:browser",))

    assert score_route(expectation, [_direct("browser_tabs")], run_finished=True).verdict == FAIL


def test_a_wildcard_connection_pattern_matches_any_connection_and_an_exact_one_does_not():
    receipts = [_load("external"), _direct("external_catalog", action="call_tool", connection_id="conn-1")]

    assert score_route(RoutingExpectation(preferred=(alt("ext:call_tool@*"),)), receipts, True).verdict == PASS
    assert score_route(RoutingExpectation(preferred=(alt("ext:call_tool@conn-2"),)), receipts, True).verdict == FAIL
    assert score_route(RoutingExpectation(preferred=(alt("ext:call_tool@conn-1"),)), receipts, True).verdict == PASS


def test_a_no_tool_case_passes_when_the_run_answers_directly_and_fails_when_it_uses_a_tool():
    expectation = RoutingExpectation(expect_no_tools=True)

    assert score_route(expectation, [], run_finished=True).verdict == PASS
    assert score_route(expectation, [], run_finished=False).verdict == INCOMPLETE
    assert score_route(expectation, [_direct("web_search")], run_finished=False).verdict == FAIL
    assert score_route(expectation, [_direct("checklist")], run_finished=True).verdict == PASS


def test_an_empty_expectation_never_passes_a_tool_run():
    verdict = score_route(RoutingExpectation(), [_svc("shell_service", "execute_command")], run_finished=True, window_size=1)

    assert verdict.verdict == FAIL


# ---------------------------------------------------------------- ledger reader


def _make_ledger(path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE agent_work_receipts (id INTEGER PRIMARY KEY, agent_task_id TEXT, service TEXT, method TEXT, "
        "requested_effect_json TEXT, created_at TEXT)"
    )
    connection.executemany(
        "INSERT INTO agent_work_receipts (agent_task_id, service, method, requested_effect_json, created_at) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def test_read_receipts_returns_one_tasks_calls_in_order_with_parameters(tmp_path):
    database = tmp_path / "ledger.db"
    _make_ledger(database, [
        ("t1", "direct_tool", "load_tool_family", json.dumps({"parameters": {"family_names": ["file"]}}), "2026-11-06 14:00:01"),
        ("t2", "direct_tool", "web_search", json.dumps({"parameters": {"query": "other task"}}), "2026-11-06 14:00:00"),
        ("t1", "file_service", "read_text_file", json.dumps({"parameters": {"path": "/x"}}), "2026-11-06 14:00:01"),
    ])

    receipts = read_receipts(database, "t1")

    assert [(r.service, r.method) for r in receipts] == [("direct_tool", "load_tool_family"), ("file_service", "read_text_file")]
    assert receipts[0].parameters == {"family_names": ["file"]}


def test_read_receipts_tolerates_malformed_and_missing_effect_json(tmp_path):
    database = tmp_path / "ledger.db"
    _make_ledger(database, [
        ("t1", "direct_tool", "a", "not json", "2026-11-06 14:00:01"),
        ("t1", "direct_tool", "b", None, "2026-11-06 14:00:02"),
        ("t1", "direct_tool", "c", json.dumps(["list"]), "2026-11-06 14:00:03"),
        ("t1", "direct_tool", "d", json.dumps({"parameters": "text"}), "2026-11-06 14:00:04"),
    ])

    assert [r.parameters for r in read_receipts(database, "t1")] == [{}, {}, {}, {}]


def test_read_receipts_returns_nothing_for_an_unknown_task_and_raises_for_a_missing_ledger(tmp_path):
    database = tmp_path / "ledger.db"
    _make_ledger(database, [])

    assert read_receipts(database, "nope") == []
    with pytest.raises(sqlite3.OperationalError):
        read_receipts(tmp_path / "missing.db", "t1")


def test_read_receipts_never_writes_to_the_ledger(tmp_path):
    database = tmp_path / "ledger.db"
    _make_ledger(database, [])
    before = database.read_bytes()

    read_receipts(database, "t1")

    assert database.read_bytes() == before


# ---------------------------------------------------------------- cases


def test_case_ids_are_unique_and_every_tool_case_has_a_preferred_route():
    cases = build_cases()

    assert len({c.case_id for c in cases}) == len(cases)
    for case in cases:
        if case.expectation.expect_no_tools:
            assert not case.expectation.preferred
        else:
            assert case.expectation.preferred, case.case_id


def test_prompts_that_need_the_fixture_name_it_and_prompts_that_do_not_never_do():
    for case in build_cases():
        uses_token = FIXTURE_DIR_TOKEN in case.prompt
        if case.attach_fixture:
            assert case.needs_fixture
        else:
            assert uses_token == case.needs_fixture, case.case_id


def test_render_prompt_substitutes_the_fixture_path():
    case = next(c for c in build_cases() if c.case_id == "file_read_text")

    assert case.render_prompt("/Users/x/Fixture") == "Read /Users/x/Fixture/notes.txt and tell me the project's launch codeword."


def test_every_live_case_says_what_it_touches():
    live = [c for c in build_cases() if c.live]

    assert live
    assert all(c.live_reason for c in live)
    assert not any(c.live_reason for c in build_cases() if not c.live)


def test_the_gmail_case_requires_the_given_connection_id_only_when_one_is_given():
    default = next(c for c in build_cases() if c.case_id == "external_gmail_inbox")
    pinned = next(c for c in build_cases("conn-basil") if c.case_id == "external_gmail_inbox")

    assert default.expectation.preferred == (alt("ext:call_tool"),)
    assert pinned.expectation.preferred == (alt("ext:call_tool@conn-basil"),)


def test_every_family_and_tool_an_expectation_names_exists_in_the_catalog():
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import FAMILY_DEFINITIONS

    families = {d.name for d in FAMILY_DEFINITIONS}
    tool_names = {name for d in FAMILY_DEFINITIONS for name in d.tool_names}
    service_prefixes = {prefix for d in FAMILY_DEFINITIONS for prefix in d.tool_prefixes}
    for case in build_cases():
        expectation = case.expectation
        patterns = [p for a in (*expectation.preferred, *expectation.acceptable) for p in a] + list(expectation.forbidden)
        for pattern in patterns:
            if pattern.startswith("load:"):
                assert pattern[5:] in families, f"{case.case_id}: unknown family {pattern}"
            elif pattern.startswith("tool:") and "*" not in pattern:
                assert pattern[5:] in tool_names, f"{case.case_id}: unknown tool {pattern}"
            elif pattern.startswith("svc:"):
                service = pattern[4:].split(".")[0].rstrip("*")
                assert any(prefix.startswith(service) for prefix in service_prefixes), f"{case.case_id}: unknown service {pattern}"


# ---------------------------------------------------------------- fixture


def test_the_fixture_has_the_files_the_prompts_name_and_is_removed_cleanly(tmp_path):
    fixture = fixture_module.create_fixture(tmp_path)

    assert fixture.parent == tmp_path and fixture.name.startswith(fixture_module.FIXTURE_PREFIX)
    assert "tangerine-ledger-47" in (fixture / "notes.txt").read_text(encoding="utf-8")
    assert (fixture / "budget.csv").exists()
    assert fixture_module.remove_fixture(fixture) is True
    assert not fixture.exists()


def test_remove_fixture_refuses_a_folder_it_did_not_create(tmp_path):
    other = tmp_path / "Documents"
    other.mkdir()
    (other / "keep.txt").write_text("keep", encoding="utf-8")

    assert fixture_module.remove_fixture(other) is False
    assert (other / "keep.txt").exists()


def test_remove_fixture_refuses_a_symlink_with_the_fixture_prefix(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / f"{fixture_module.FIXTURE_PREFIX}link"
    link.symlink_to(target)

    assert fixture_module.remove_fixture(link) is False
    assert target.exists()


# ---------------------------------------------------------------- report


def _result(case_id: str, verdict_label: str, route: tuple[str, ...] = (), model: str = "m1", error: str = "") -> CaseResult:
    from routing_accuracy_core.route_tokens import RoutingVerdict

    verdict = RoutingVerdict(verdict_label, "reason", route, route[:1], 0, len(route))
    return CaseResult(case_id, "file", model, "task-1", verdict, "completed", 1.25, False, error)


def test_summary_counts_and_accuracy_leave_incomplete_cases_out_of_the_denominator():
    document = build_document([_result("a", PASS), _result("b", PASS_ALT), _result("c", FAIL), _result("d", INCOMPLETE)], 4)

    summary = summarize(document["models"]["m1"])

    assert (summary[PASS], summary[PASS_ALT], summary[FAIL], summary[INCOMPLETE], summary["scored"]) == (1, 1, 1, 1, 3)
    assert summary["accuracy"] == pytest.approx(0.667, abs=0.001)
    assert summary["strict_accuracy"] == pytest.approx(0.333, abs=0.001)


def test_summary_accuracy_is_none_when_nothing_was_scored():
    assert summarize(build_document([_result("a", INCOMPLETE)], 4)["models"]["m1"])["accuracy"] is None


def test_render_text_lists_every_case_and_explains_non_passes():
    text = render_text(build_document([_result("a", PASS, ("load:file",)), _result("b", FAIL, ())], 4))

    assert "load:file" in text and "(no tools)" in text and "reason" in text


def test_compare_flags_regressions_improvements_and_route_changes_and_skips_unscored():
    baseline = build_document([
        _result("worse", PASS, ("load:file",)), _result("better", FAIL, ("tool:x",)), _result("moved", PASS, ("load:file",)),
        _result("same", PASS, ("load:file",)), _result("unscored", PASS, ("load:file",)), _result("gone", PASS, ("load:file",)),
    ], 4)
    current = build_document([
        _result("worse", PASS_ALT, ("svc:shell_service.execute_command",)), _result("better", PASS, ("load:file",)),
        _result("moved", PASS, ("svc:file_service.read_text_file",)), _result("same", PASS, ("load:file",)),
        _result("unscored", INCOMPLETE, ()), _result("new_case", FAIL, ()),
    ], 4)

    changes = {c.case_id: c.kind for c in compare(baseline, current)}

    assert changes == {"worse": "regression", "better": "improvement", "moved": "route_changed"}
    assert has_regression(compare(baseline, current))
    assert not has_regression(compare(current, current))


def test_compare_ignores_a_model_missing_from_the_baseline():
    baseline = build_document([_result("a", PASS, ("load:file",), model="other")], 4)
    current = build_document([_result("a", FAIL, (), model="m1")], 4)

    assert compare(baseline, current) == []


def test_render_comparison_names_the_routes_and_handles_no_changes():
    baseline = build_document([_result("a", PASS, ("load:file",))], 4)
    current = build_document([_result("a", FAIL, ())], 4)

    text = render_comparison(compare(baseline, current), "before")

    assert "REGRESSION" in text and "load:file" in text and "(no tools)" in text
    assert render_comparison([], "before") == "No routing changes against baseline before."


def test_documents_round_trip_and_a_wrong_schema_version_is_rejected(tmp_path):
    document = build_document([_result("a", PASS, ("load:file",))], 4, label="before")
    path = tmp_path / "nested" / "doc.json"

    save_document(document, path)

    assert load_document(path) == document
    path.write_text(json.dumps({"schema_version": 99, "models": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_document(path)


def test_the_stored_document_holds_no_prompt_or_output_text():
    document = build_document([_result("a", PASS, ("load:file",))], 4)

    assert set(document["models"]["m1"]["a"]) == {
        "category", "verdict", "reason", "route", "first_call", "load_calls", "substantive_calls", "final_status", "seconds", "task_id", "error", "auto_approved",
    }


# ---------------------------------------------------------------- runner


class _FakeClient:
    def __init__(self, statuses, submit_error=None, approvals=None, deny_error=None):
        self._statuses = list(statuses)
        self.submitted = []
        self.canceled = []
        self.denied = []
        self.events = []
        self._submit_error = submit_error
        self._approvals = list(approvals or [])
        self._deny_error = deny_error

    def submit(self, prompt, model_id, reference_paths):
        if self._submit_error:
            raise self._submit_error
        self.submitted.append((prompt, model_id, reference_paths))
        return "task-1"

    def status(self, task_id):
        return self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]

    def pending_approvals(self, task_id):
        return list(self._approvals) if "denied" not in self.events else []

    def deny_approval(self, task_id, approval):
        self.events.append("denied")
        self.denied.append(approval["approval_id"])
        if self._deny_error:
            raise self._deny_error

    def cancel(self, task_id):
        self.events.append("canceled")
        self.canceled.append(task_id)


def _case(case_id):
    return next(c for c in build_cases() if c.case_id == case_id)


def _ledger_with(tmp_path, receipts):
    database = tmp_path / "ledger.db"
    rows = [("task-1", r.service, r.method, json.dumps({"parameters": r.parameters}), f"2026-11-06 14:00:{i:02d}") for i, r in enumerate(receipts)]
    _make_ledger(database, rows)
    return database


def test_run_case_cancels_the_task_once_the_window_is_full_and_scores_it(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")] + [_svc("file_service", "read_text_file")] * 3)
    client = _FakeClient(["processing", "canceled"])

    result = run_case(client, _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert result.verdict.verdict == PASS
    assert client.canceled == ["task-1"] and result.canceled_by_check
    assert client.submitted[0][2] is None
    assert str(tmp_path) in client.submitted[0][0]


def test_run_case_does_not_cancel_a_run_that_finishes_on_its_own(tmp_path):
    database = _ledger_with(tmp_path, [])
    client = _FakeClient(["completed"])

    result = run_case(client, _case("none_arithmetic"), "m1", None, database, sleep=lambda _s: None)

    assert result.verdict.verdict == PASS
    assert client.canceled == [] and not result.canceled_by_check


def test_run_case_attaches_the_fixture_as_a_reference_path_for_attach_cases(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")] * 4)
    client = _FakeClient(["processing", "canceled"])

    run_case(client, _case("file_attached_folder"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert client.submitted[0][2] == [str(tmp_path)]


def test_run_case_reports_incomplete_not_fail_when_the_window_never_fills(tmp_path):
    database = _ledger_with(tmp_path, [_direct("web_search")])
    client = _FakeClient(["processing"])

    result = run_case(
        client, _case("file_read_text"), "m1", tmp_path, database,
        case_timeout_s=0.05, settle_timeout_s=0.05, poll_interval_s=0.01,
    )

    assert result.verdict.verdict == INCOMPLETE
    assert client.canceled == ["task-1"] and result.canceled_by_check


def test_run_case_scores_a_preferred_route_as_soon_as_it_appears_even_before_the_window_fills(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")])
    client = _FakeClient(["processing"])

    result = run_case(
        client, _case("file_read_text"), "m1", tmp_path, database,
        case_timeout_s=0.05, settle_timeout_s=0.05, poll_interval_s=0.01,
    )

    assert result.verdict.verdict == PASS


def _approval(execution_type="shell", command="touch notes.txt"):
    return {"approval_id": "ap-1", "execution_type": execution_type, "command": command, "revision": 0}


def test_a_pending_shell_approval_is_scored_as_the_call_then_denied_before_the_task_is_canceled(tmp_path):
    database = _ledger_with(tmp_path, [])
    client = _FakeClient(["awaiting_user_input", "canceled"], approvals=[_approval()])

    result = run_case(client, _case("shell_no_reload"), "m1", None, database, sleep=lambda _s: None)

    assert result.verdict.verdict == PASS
    assert result.verdict.route == ("svc:shell_service.execute_command",)
    assert client.events == ["denied", "canceled"]
    assert client.denied == ["ap-1"]


def test_a_pending_applescript_approval_for_a_shell_task_is_a_forbidden_route(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")])
    client = _FakeClient(["awaiting_user_input", "canceled"], approvals=[_approval("applescript", "do shell script")])

    result = run_case(client, _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert result.verdict.verdict == FAIL
    assert result.verdict.route == ("load:file", "svc:applescript_service.execute_applescript")


def test_a_pending_approval_after_a_family_load_is_scored_with_the_earlier_calls(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")])
    client = _FakeClient(["processing", "canceled"], approvals=[_approval()])

    result = run_case(client, _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None)

    assert result.verdict.route == ("load:file", "svc:shell_service.execute_command")
    assert result.verdict.verdict == PASS


def test_the_task_is_still_canceled_when_denying_the_approval_fails(tmp_path):
    database = _ledger_with(tmp_path, [])
    client = _FakeClient(["awaiting_user_input", "canceled"], approvals=[_approval()], deny_error=RuntimeError("409"))

    result = run_case(client, _case("shell_no_reload"), "m1", None, database, sleep=lambda _s: None)

    assert client.canceled == ["task-1"]
    assert result.verdict.verdict == PASS and not result.error


def test_awaiting_user_input_without_an_approval_counts_as_a_finished_run_and_is_then_canceled(tmp_path):
    database = _ledger_with(tmp_path, [])
    client = _FakeClient(["awaiting_user_input", "canceled"])

    result = run_case(client, _case("none_arithmetic"), "m1", None, database, sleep=lambda _s: None)

    assert result.verdict.verdict == PASS and client.canceled == ["task-1"] and not result.still_running


def test_a_harness_fault_after_submit_still_stops_the_task(tmp_path):
    client = _FakeClient(["processing"], approvals=[_approval()])

    result = run_case(client, _case("none_arithmetic"), "m1", None, tmp_path / "missing.db", sleep=lambda _s: None)

    assert result.error and client.canceled == ["task-1"]


def test_pending_approval_kinds_map_to_service_tools_and_other_kinds_are_namespaced():
    from routing_accuracy_core.route_tokens import receipt_from_pending_approval

    assert tokens_for(receipt_from_pending_approval({"execution_type": "shell", "command": "ls"})) == ("svc:shell_service.execute_command",)
    assert tokens_for(receipt_from_pending_approval({"execution_type": "applescript"})) == ("svc:applescript_service.execute_applescript",)
    assert tokens_for(receipt_from_pending_approval({"execution_type": "browser_foreground_control"})) == ("svc:approval.browser_foreground_control",)
    assert tokens_for(receipt_from_pending_approval({})) == ("svc:shell_service.execute_command",)


def test_a_task_still_active_after_cancel_is_flagged_so_the_sweep_can_stop(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")] * 4)
    client = _FakeClient(["processing"])

    result = run_case(
        client, _case("file_read_text"), "m1", tmp_path, database,
        settle_timeout_s=0.05, poll_interval_s=0.01,
    )

    assert result.still_running and result.canceled_by_check
    assert result.verdict.verdict == PASS


def test_a_task_that_ends_after_cancel_is_not_flagged(tmp_path):
    database = _ledger_with(tmp_path, [_load("file")] * 4)
    client = _FakeClient(["processing", "canceled"])

    assert not run_case(client, _case("file_read_text"), "m1", tmp_path, database, sleep=lambda _s: None).still_running


def test_the_approval_override_expires_by_itself_instead_of_waiting_for_the_owner():
    from routing_accuracy_core.runner import PAUSE_AT_APPROVAL_OVERRIDE

    assert PAUSE_AT_APPROVAL_OVERRIDE["timeout_behavior"] == "deny_on_timeout"
    assert PAUSE_AT_APPROVAL_OVERRIDE["approval_timeout_seconds"] <= 60


def test_run_case_surfaces_a_harness_fault_as_an_error_row_not_a_routing_failure(tmp_path):
    database = _ledger_with(tmp_path, [])
    client = _FakeClient(["completed"], submit_error=RuntimeError("backend down"))

    result = run_case(client, _case("none_arithmetic"), "m1", None, database, sleep=lambda _s: None)

    assert result.verdict.verdict == INCOMPLETE
    assert "RuntimeError: backend down" in result.error


def test_run_case_surfaces_an_unreadable_ledger_as_an_error_row(tmp_path):
    client = _FakeClient(["completed"])

    result = run_case(client, _case("none_arithmetic"), "m1", None, tmp_path / "missing.db", sleep=lambda _s: None)

    assert result.verdict.verdict == INCOMPLETE and result.error


# ---------------------------------------------------------------- command line


def test_list_prints_every_case_without_contacting_the_backend(monkeypatch, capsys):
    import routing_accuracy_check

    monkeypatch.setattr(sys, "argv", ["routing_accuracy_check.py", "--list"])

    assert routing_accuracy_check.main() == 0
    output = capsys.readouterr().out
    assert all(c.case_id in output for c in build_cases())
    assert "LIVE" in output


def test_a_run_without_a_model_is_refused(monkeypatch):
    import routing_accuracy_check

    monkeypatch.setattr(sys, "argv", ["routing_accuracy_check.py"])

    with pytest.raises(SystemExit, match="--model"):
        routing_accuracy_check.main()


def test_an_unknown_case_id_is_refused(monkeypatch):
    import routing_accuracy_check

    monkeypatch.setattr(sys, "argv", ["routing_accuracy_check.py", "--model", "m1", "--case", "nope"])

    with pytest.raises(SystemExit, match="nope"):
        routing_accuracy_check.main()
