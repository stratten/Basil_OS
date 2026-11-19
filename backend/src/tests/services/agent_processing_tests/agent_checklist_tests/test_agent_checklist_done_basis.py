"""Done-basis behavior of the task checklist: the column, its migration, its repository rules, the verifier's use of it, and its logging."""

import sqlite3

import pytest
from pydantic import ValidationError

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_work.migrations import (
    migrate_agent_work_session_tables,
)
from api.routes.agent_tasks.checklist_routes import ChecklistItemPatchRequest
from api.services.agent_processing.lifecycle.runtime import agent_checklist_signoff
from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import (
    EVIDENCE_MAX_CHARS,
    build_checklist_evidence,
)
from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import item_for_model
from api.services.agent_processing.lifecycle.runtime.agent_checklist_signoff import (
    apply_checklist_review,
    parse_checklist_review,
)

IDS = {"root_task_id": "root-1", "agent_task_id": "root-1"}


class _Recorder:
    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(message % args if args else message)


@pytest.fixture
def published(monkeypatch):
    messages = []

    async def capture(self, message):
        messages.append(message)

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster.AgentTaskEventBroadcaster.broadcast", capture
    )
    return messages


async def _service_with_session(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(agent_task_id="root-1", original_prompt="Inbox", transcribed_prompt="Inbox", status="processing")
    await service.agent_work_session_repository.get_or_create_root_session(root_task_id="root-1", goal="Inbox", collection_type="agent_work")
    session = await service.agent_work_session_repository.get_latest_session_for_root("root-1")
    return service, session


async def _add(service, session, title, status="pending"):
    created = await service.agent_checklist_repository.add_item(session_id=session["id"], title=title, status=status, actor="agent", agent_task_id="root-1")
    return created["item"]


async def _get(service, session, item):
    return await service.agent_checklist_repository.get_item(session["id"], item["id"])


def _short(item):
    return item["id"][:8]


@pytest.mark.asyncio
async def test_migration_adds_the_column_to_an_existing_table_and_keeps_its_rows(tmp_path):
    service, session = await _service_with_session(tmp_path)
    item = await _add(service, session, "Reply to the GP office", status="done")
    conn = sqlite3.connect(tmp_path / "knowledge.db")
    conn.row_factory = sqlite3.Row
    conn.execute("ALTER TABLE agent_checklist_items DROP COLUMN done_basis")
    conn.commit()
    assert "done_basis" not in {row["name"] for row in conn.execute("PRAGMA table_info(agent_checklist_items)").fetchall()}

    migrate_agent_work_session_tables(conn)
    migrate_agent_work_session_tables(conn)
    conn.commit()

    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(agent_checklist_items)").fetchall()}
    assert columns["done_basis"]["dflt_value"] == "''" and columns["done_basis"]["notnull"] == 1
    assert conn.execute("SELECT done_basis, status FROM agent_checklist_items WHERE id = ?", (item["id"],)).fetchone()["done_basis"] == ""
    conn.close()
    reread = await _get(service, session, item)
    assert reread["status"] == "done" and reread["done_basis"] == ""


@pytest.mark.asyncio
async def test_a_new_item_has_an_empty_basis(tmp_path):
    service, session = await _service_with_session(tmp_path)
    item = await _add(service, session, "Book a referral")
    assert item["done_basis"] == ""


@pytest.mark.asyncio
async def test_an_inferred_done_is_marked_and_a_user_confirmation_clears_it(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    item = await _add(service, session, "Archive the newsletter")

    inferred = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="system", done_basis="inferred", event_text="Outcome check (inferred): The response says it was archived.")
    assert inferred["changed"] and inferred["item"]["status"] == "done" and inferred["item"]["done_basis"] == "inferred"

    confirmed = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, expected_revision=inferred["item"]["revision"], actor="user")
    assert confirmed["changed"] and confirmed["item"]["done_basis"] == "" and confirmed["item"]["revision"] == inferred["item"]["revision"] + 1

    events = await repo.list_events(session["id"], item["id"])
    assert events[-1]["kind"] == "status" and events[-1]["text"] == "done (confirmed)" and events[-1]["actor"] == "user"
    assert events[-2]["text"].startswith("pending to done: Outcome check (inferred):")


@pytest.mark.asyncio
async def test_leaving_done_or_a_non_user_repeat_never_leaves_a_stale_marker_or_clears_a_real_one(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    item = await _add(service, session, "Archive the newsletter")
    await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="system", done_basis="inferred")

    repeat = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="agent")
    assert repeat["changed"] is False and repeat["item"]["done_basis"] == "inferred"

    reopened = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "pending"}, actor="user")
    assert reopened["item"]["status"] == "pending" and reopened["item"]["done_basis"] == ""

    ignored = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "pending"}, actor="system", done_basis="inferred")
    assert ignored["changed"] is False and ignored["item"]["done_basis"] == ""

    again = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="agent")
    assert again["item"]["status"] == "done" and again["item"]["done_basis"] == ""


@pytest.mark.asyncio
async def test_a_verified_done_replaces_an_inferred_one(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    item = await _add(service, session, "Archive the newsletter")
    await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="system", done_basis="inferred")

    verified = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="system", done_basis="")

    assert verified["changed"] and verified["item"]["done_basis"] == ""
    assert (await repo.list_events(session["id"], item["id"]))[-1]["text"] == "done (confirmed)"


def test_the_edit_request_cannot_set_the_basis():
    with pytest.raises(ValidationError):
        ChecklistItemPatchRequest(status="done", done_basis="inferred")


@pytest.mark.parametrize("raw,expected", [("inferred", "inferred"), (" Verified ", "verified"), ("guess", ""), (None, ""), (7, "")])
def test_the_parser_keeps_only_a_known_basis(raw, expected):
    review = parse_checklist_review({"checklist_review": {"items": [{"item": "abcd1234", "status": "done", "reason": "Reported archived.", "basis": raw}]}})
    assert review["items"][0]["basis"] == expected


@pytest.mark.asyncio
async def test_the_verifier_closes_items_with_a_basis_and_the_log_says_which(tmp_path, published, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(agent_checklist_signoff, "decision_logger", recorder)
    service, session = await _service_with_session(tmp_path)
    inferred_item = await _add(service, session, "Archive the newsletter")
    verified_item = await _add(service, session, "Send the invoice")
    review = parse_checklist_review({
        "checklist_review": {
            "items": [
                {"item": _short(inferred_item), "status": "done", "reason": "The response says it was archived.", "basis": "inferred"},
                {"item": _short(verified_item), "status": "done", "reason": "The tool trace shows the send succeeded.", "basis": "verified"},
            ]
        }
    })

    summary = await apply_checklist_review(service, IDS, review)

    assert summary["updated"] == 2
    assert (await _get(service, session, inferred_item))["done_basis"] == "inferred"
    assert (await _get(service, session, verified_item))["done_basis"] == ""
    events = await service.agent_checklist_repository.list_events(session["id"], inferred_item["id"])
    assert "Outcome check (inferred): The response says it was archived." in events[-1]["text"]
    assert any("(inferred)" in line and "The response says it was archived." in line for line in recorder.lines)
    assert any(line.startswith("Checklist sign-off for root-1:") for line in recorder.lines)
    assert len(published) == 1


@pytest.mark.asyncio
async def test_a_done_update_with_no_basis_is_treated_as_verified(tmp_path, published):
    service, session = await _service_with_session(tmp_path)
    item = await _add(service, session, "Send the invoice")
    review = parse_checklist_review({"checklist_review": {"items": [{"item": _short(item), "status": "done", "reason": "Sent."}]}})

    await apply_checklist_review(service, IDS, review)

    current = await _get(service, session, item)
    assert current["status"] == "done" and current["done_basis"] == ""


def test_the_finalizer_helper_logs_when_the_verifier_decided_nothing(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph.async_finalizer import _log_no_checklist_decisions

    recorder = _Recorder()
    monkeypatch.setattr(agent_checklist_signoff, "decision_logger", recorder)

    _log_no_checklist_decisions("task-9")

    assert recorder.lines == ["Checklist sign-off for task-9: the verifier made no checklist decisions"]


def test_the_agent_sees_the_basis_only_when_it_is_set():
    base = {"id": "7f3a9c12-0000", "title": "Archive it", "status": "done", "required": False, "refs": []}
    assert "done_basis" not in item_for_model({**base, "done_basis": ""})
    assert item_for_model({**base, "done_basis": "inferred"})["done_basis"] == "inferred"


def test_the_evidence_marks_inferred_items_and_lists_open_items_first():
    items = [
        {"id": f"{n:08d}-0000", "title": f"Finished {n}", "status": "done", "done_basis": "inferred" if n == 0 else "", "required": False, "waiting_on": "", "last_actor": "agent"}
        for n in range(40)
    ]
    items.append({"id": "99999999-0000", "title": "Still open", "status": "pending", "done_basis": "", "required": False, "waiting_on": "", "last_actor": "agent"})
    counts = {"total": 41, "done": 40, "waiting_user": 0, "waiting_external": 0, "required_open": 0}

    evidence = build_checklist_evidence(items, counts)

    assert "- [99999999] [pending] Still open" in evidence
    assert evidence.index("Still open") < evidence.index("Finished 1")
    assert "- [00000000] [done] Finished 0 (inferred done)" in evidence
    assert sum(1 for line in evidence.splitlines() if line.startswith("- [") and line.endswith("(inferred done)")) == 1
    assert len(evidence) <= EVIDENCE_MAX_CHARS
    assert "and " in evidence and " more items" in evidence
    assert evidence.endswith("which are missing.")
