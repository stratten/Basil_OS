"""The outcome verifier's sign-off on the task checklist: parsing its decisions and applying them safely."""

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import AgentChecklistService
from api.services.agent_processing.lifecycle.runtime.agent_checklist_signoff import (
    MAX_REVIEW_NEW_ITEMS,
    MAX_REVIEW_UPDATES,
    SIGNOFF_RULES,
    apply_checklist_review,
    parse_checklist_review,
)

IDS = {"root_task_id": "root-1", "agent_task_id": "root-1"}


@pytest_asyncio.fixture
async def checklist(tmp_path, monkeypatch):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(agent_task_id="root-1", original_prompt="Inbox", transcribed_prompt="Inbox", status="processing")
    published = []

    async def capture(self, message):
        published.append(message)

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster.AgentTaskEventBroadcaster.broadcast", capture
    )
    session = await service.agent_work_session_repository.get_or_create_root_session(root_task_id="root-1", goal="Inbox", collection_type="agent_work")
    session = await service.agent_work_session_repository.get_latest_session_for_root("root-1")
    items = {}
    for name in ("alpha", "bravo", "charlie"):
        created = await service.agent_checklist_repository.add_item(
            session_id=session["id"], title=f"Reply to {name}", status="done", actor="agent", agent_task_id="root-1"
        )
        items[name] = created["item"]
    return service, session, items, published


def _short(item):
    return item["id"][:8]


async def _status_by_title(service, session):
    return {item["title"]: item["status"] for item in await service.agent_checklist_repository.list_items(session["id"])}


def test_parser_keeps_valid_decisions_and_drops_malformed_ones():
    review = parse_checklist_review({
        "checklist_review": {
            "items": [
                {"item": "abcd1234", "status": "Waiting_User", "reason": "Only proposed a reply.", "waiting_on": "Approve the reply"},
                {"item": "", "status": "done", "reason": "no id"},
                {"item": "abcd5678", "status": "finished", "reason": "bad status"},
                {"item": "abcd9999", "status": "done", "reason": ""},
                "not an object",
            ],
            "new_items": [{"title": "  Confirm   Thursday  "}, {"title": ""}, {"title": "Odd status", "status": "done"}],
        }
    })

    assert review["items"] == [{"item": "abcd1234", "status": "waiting_user", "reason": "Only proposed a reply.", "waiting_on": "Approve the reply"}]
    assert [entry["title"] for entry in review["new_items"]] == ["Confirm Thursday", "Odd status"]
    assert [entry["status"] for entry in review["new_items"]] == ["waiting_user", "waiting_user"]


@pytest.mark.parametrize("value", [None, {}, {"checklist_review": "none"}, {"checklist_review": {"items": [], "new_items": []}}])
def test_parser_returns_none_when_nothing_was_decided(value):
    assert parse_checklist_review(value or {}) is None


def test_parser_caps_the_number_of_decisions():
    many_updates = [{"item": f"abcd{n:04d}", "status": "done", "reason": "ok"} for n in range(MAX_REVIEW_UPDATES + 20)]
    many_new = [{"title": f"New {n}"} for n in range(MAX_REVIEW_NEW_ITEMS + 5)]

    review = parse_checklist_review({"checklist_review": {"items": many_updates, "new_items": many_new}})

    assert len(review["items"]) == MAX_REVIEW_UPDATES and len(review["new_items"]) == MAX_REVIEW_NEW_ITEMS


def test_rules_state_the_outcome_definition_the_verifier_must_apply():
    assert "not a log of what the agent did" in SIGNOFF_RULES
    assert "does not complete an item" in SIGNOFF_RULES
    assert "waiting_user" in SIGNOFF_RULES and "new_items" in SIGNOFF_RULES
    assert "never changes outcome" in SIGNOFF_RULES
    assert "agent's own judgment that nothing is needed does not complete an item" in SIGNOFF_RULES


@pytest.mark.asyncio
async def test_verifier_reopens_proposal_only_items_and_adds_an_untracked_outcome(checklist):
    service, session, items, published = checklist
    review = parse_checklist_review({
        "checklist_review": {
            "items": [
                {"item": _short(items["alpha"]), "status": "waiting_user", "reason": "Only a reply was proposed.", "waiting_on": "Approve the reply to alpha"},
                {"item": _short(items["bravo"]), "status": "waiting_user", "reason": "Only a reply was proposed."},
            ],
            "new_items": [{"title": "Add the NYC AI Demos event to the calendar", "detail": "Thursday 6 PM", "waiting_on": "Your calendar"}],
        }
    })

    summary = await apply_checklist_review(service, IDS, review)

    statuses = await _status_by_title(service, session)
    assert summary["updated"] == 2 and summary["created"] == 1 and summary["skipped"] == []
    assert statuses["Reply to alpha"] == "waiting_user" and statuses["Reply to bravo"] == "waiting_user"
    assert statuses["Reply to charlie"] == "done"
    assert statuses["Add the NYC AI Demos event to the calendar"] == "waiting_user"
    events = await service.agent_checklist_repository.list_events(session["id"], items["alpha"]["id"])
    assert events[-1]["actor"] == "system" and "Outcome check: Only a reply was proposed." in events[-1]["text"]
    reopened = [item for item in await service.agent_checklist_repository.list_items(session["id"]) if item["title"] == "Reply to alpha"][0]
    assert reopened["waiting_on"] == "Approve the reply to alpha"
    assert len(published) == 1 and published[0]["counts"]["done"] == 1


@pytest.mark.asyncio
async def test_verifier_confirms_an_open_item_done_and_clears_its_wait(checklist):
    service, session, items, _published = checklist
    await service.agent_checklist_repository.update_item(
        session_id=session["id"], item_id=items["charlie"]["id"], changes={"status": "waiting_user", "waiting_on": "Approve"}, actor="agent"
    )
    review = parse_checklist_review({"checklist_review": {"items": [{"item": _short(items["charlie"]), "status": "done", "reason": "The tool trace shows the reply was sent."}]}})

    summary = await apply_checklist_review(service, IDS, review)

    current = [item for item in await service.agent_checklist_repository.list_items(session["id"]) if item["title"] == "Reply to charlie"][0]
    assert summary["updated"] == 1 and current["status"] == "done" and current["waiting_on"] == ""


@pytest.mark.asyncio
async def test_verifier_does_not_override_the_users_latest_change_or_a_stopped_checklist(checklist):
    service, session, items, published = checklist
    await service.agent_checklist_repository.update_item(
        session_id=session["id"], item_id=items["alpha"]["id"], changes={"status": "done", "note": "I did this by phone"}, actor="user"
    )
    review = parse_checklist_review({"checklist_review": {"items": [{"item": _short(items["alpha"]), "status": "waiting_user", "reason": "Only proposed."}]}})

    skipped = await apply_checklist_review(service, IDS, review)
    await service.agent_checklist_repository.set_closed(session["id"], True)
    review_after_stop = parse_checklist_review({
        "checklist_review": {"items": [{"item": _short(items["bravo"]), "status": "waiting_user", "reason": "Only proposed."}], "new_items": [{"title": "Brand new"}]}
    })
    stopped = await apply_checklist_review(service, IDS, review_after_stop)

    statuses = await _status_by_title(service, session)
    assert skipped["updated"] == 0 and "last changed by the user" in skipped["skipped"][0]
    assert stopped["updated"] == 0 and stopped["created"] == 0 and stopped["skipped"] == ["tracking was stopped by the user"]
    assert statuses["Reply to alpha"] == "done" and statuses["Reply to bravo"] == "done" and "Brand new" not in statuses
    assert published == []


@pytest.mark.asyncio
async def test_verifier_skips_stale_items_unknown_ids_and_duplicate_titles(checklist, monkeypatch):
    service, session, items, _published = checklist
    original_snapshot = AgentChecklistService.snapshot

    async def stale_snapshot(self, session_id, **kwargs):
        taken = await original_snapshot(self, session_id, **kwargs)
        await service.agent_checklist_repository.update_item(
            session_id=session_id, item_id=items["alpha"]["id"], changes={"note": "agent note"}, actor="agent"
        )
        return taken

    monkeypatch.setattr(AgentChecklistService, "snapshot", stale_snapshot)
    review = parse_checklist_review({
        "checklist_review": {
            "items": [
                {"item": _short(items["alpha"]), "status": "waiting_user", "reason": "Only proposed."},
                {"item": "zzzzzzzz", "status": "dropped", "reason": "No such item."},
                {"item": "abc", "status": "dropped", "reason": "Too short to match."},
            ],
            "new_items": [{"title": "reply to BRAVO"}],
        }
    })

    summary = await apply_checklist_review(service, IDS, review)

    statuses = await _status_by_title(service, session)
    assert summary["updated"] == 0 and summary["created"] == 0 and len(summary["skipped"]) == 4
    assert any("changed while the outcome check ran" in reason for reason in summary["skipped"])
    assert statuses["Reply to alpha"] == "done" and len(statuses) == 3


@pytest.mark.asyncio
async def test_verifier_without_a_checklist_changes_nothing_and_never_raises(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    review = parse_checklist_review({"checklist_review": {"items": [{"item": "abcd1234", "status": "done", "reason": "x"}]}})

    summary = await apply_checklist_review(service, IDS, review)

    assert summary["updated"] == 0 and summary["skipped"] == ["no checklist for this chain"]
    assert await service.agent_work_session_repository.get_latest_session_for_root("root-1") is None


def _evaluation_json(**extra):
    import json

    return json.dumps({"outcome": "success", "success": True, "failure_basis": "none", "user_reason": "", "technical_reason": "ok", "should_retry": False, **extra})


def test_evaluation_response_carries_the_checklist_review_without_changing_the_verdict():
    from api.services.agent_processing.lifecycle.finalization.evaluation import parse_evaluation_response

    decided = parse_evaluation_response(_evaluation_json(checklist_review={
        "items": [{"item": "abcd1234", "status": "waiting_user", "reason": "Only proposed."}], "new_items": [{"title": "Confirm Thursday"}],
    }))
    silent = parse_evaluation_response(_evaluation_json())
    empty = parse_evaluation_response(_evaluation_json(checklist_review={"items": [], "new_items": []}))

    assert decided.checklist_review["items"][0]["status"] == "waiting_user" and decided.checklist_review["new_items"][0]["title"] == "Confirm Thursday"
    assert (decided.outcome, decided.success, decided.should_retry, decided.continuation_instructions) == ("success", True, False, None)
    assert silent.checklist_review is None and empty.checklist_review is None


def test_evidence_shows_ids_and_user_edits_and_the_prompt_asks_for_a_review():
    from api.services.agent_processing.lifecycle.finalization.evaluation import build_evaluation_prompt
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import build_checklist_evidence

    items = [
        {"id": "7f3a9c12-0000", "title": "Reply to Avigail", "status": "done", "required": False, "waiting_on": "", "last_actor": "agent"},
        {"id": "9b8e1d34-0000", "title": "Confirm Thursday", "status": "waiting_user", "required": False, "waiting_on": "Pick a time", "last_actor": "user"},
    ]
    counts = {"total": 2, "done": 1, "waiting_user": 1, "waiting_external": 0, "required_open": 0}

    evidence = build_checklist_evidence(items, counts)
    prompt = build_evaluation_prompt(
        original_prompt="Triage my inbox", self_assessment=None, full_agent_output="Five proposals.", max_output_chars=5000,
        steps=[], tool_error_history=None, evaluation_context=evidence,
    )

    assert "- [7f3a9c12] [done] Reply to Avigail" in evidence
    assert "- [9b8e1d34] [waiting_user] Confirm Thursday, waiting on: Pick a time (edited by the user)" in evidence
    assert SIGNOFF_RULES in evidence and "Do not change the outcome" in evidence
    assert '"checklist_review"' in prompt and "CHECKLIST REVIEW" in prompt and SIGNOFF_RULES in prompt


@pytest.mark.asyncio
async def test_a_stopped_checklist_gives_the_verifier_no_block(checklist, monkeypatch):
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import finalizer_checklist_block

    service, session, _items, _published = checklist
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)

    running = await finalizer_checklist_block(IDS)
    await service.agent_checklist_repository.set_closed(session["id"], True)
    stopped = await finalizer_checklist_block(IDS)

    assert "3 of 3 done" in running and stopped == ""


@pytest.mark.asyncio
async def test_the_finalizer_hands_the_review_to_the_async_verifier_in_the_envelope():
    from unittest.mock import AsyncMock, patch

    from api.services.agent_processing.lifecycle.finalization.evaluation import FinalizerEvaluation
    from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import finalize_agent_task_result

    review = {"items": [{"item": "abcd1234", "status": "waiting_user", "reason": "Only proposed.", "waiting_on": ""}], "new_items": []}
    verdict = FinalizerEvaluation(
        outcome="success", success=True, outcome_reason="", technical_reason="ok", llm_reasoning="", should_retry=False,
        failure_basis="none", checklist_review=review,
    )
    with patch(
        "api.services.agent_processing.lifecycle.finalization.result_finalizer_tool.evaluate_finalizer_with_llm", new=AsyncMock(return_value=verdict)
    ):
        envelope = await finalize_agent_task_result(
            original_prompt="Triage my inbox", agent_task_id=None, active_app=None, steps=[], standardized_messages=["Five proposals."],
            metrics={"steps_completed": 0, "steps_total": 0}, llm_model=object(),
        )

    assert envelope["checklist_review"] == review and envelope["outcome"] == "success"
