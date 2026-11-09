"""Persistence coverage for the per-chain agent checklist and its notes."""

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_work import checklist_repository


async def _service_with_session(tmp_path, root="root-task"):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id=root, original_prompt="Sort inbox", transcribed_prompt="Sort inbox", status="processing"
    )
    session = await service.agent_work_session_repository.get_or_create_root_session(
        root_task_id=root, goal="Sort inbox", collection_type="agent_work", agent_task_id=root
    )
    return service, session


@pytest.mark.asyncio
async def test_item_lifecycle_records_revisions_events_and_clears_stale_waiting_on(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository

    created = await repo.add_item(session_id=session["id"], title="Reply to the GP office", required=True, agent_task_id="root-task")
    item = created["item"]
    assert created["created"] and item["status"] == "pending" and item["revision"] == 1 and item["required"]

    waiting = await repo.update_item(
        session_id=session["id"], item_id=item["id"], changes={"status": "waiting_user", "waiting_on": "Pick a visit time"},
        expected_revision=1, agent_task_id="root-task", event_text="two slots offered",
    )
    assert waiting["item"]["revision"] == 2 and waiting["item"]["waiting_on"] == "Pick a visit time"

    done = await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "done"}, actor="user")
    assert done["item"]["status"] == "done" and done["item"]["waiting_on"] == ""

    events = await repo.list_events(session["id"], item["id"])
    assert [event["kind"] for event in events] == ["added", "status", "status"]
    assert events[1]["text"] == "pending to waiting_user: two slots offered"
    assert events[2]["actor"] == "user"


@pytest.mark.asyncio
async def test_stale_revision_is_a_conflict_that_writes_nothing(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    item = (await repo.add_item(session_id=session["id"], title="Book a referral"))["item"]
    await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"title": "Book a GP referral"}, actor="user")

    result = await repo.update_item(
        session_id=session["id"], item_id=item["id"], changes={"status": "done"}, expected_revision=1, actor="agent"
    )

    assert result["conflict"] is True and result["current"]["title"] == "Book a GP referral"
    assert (await repo.get_item(session["id"], item["id"]))["status"] == "pending"


@pytest.mark.asyncio
async def test_invalid_status_and_empty_title_are_rejected(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    with pytest.raises(ValueError):
        await repo.add_item(session_id=session["id"], title="   ")
    item = (await repo.add_item(session_id=session["id"], title="Real item"))["item"]
    with pytest.raises(ValueError):
        await repo.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "discovered"})


@pytest.mark.asyncio
async def test_adding_an_item_with_an_existing_reference_returns_the_existing_item(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    ref = {"ref_kind": "gmail_thread", "source_system": "gmail", "external_id": "thread-1", "label": "Insurance claim"}

    first = await repo.add_item(session_id=session["id"], title="Handle insurance claim", refs=[ref])
    second = await repo.add_item(session_id=session["id"], title="Insurance claim again", refs=[ref])
    found = await repo.find_items(session["id"], external_id="thread-1")

    assert first["created"] and second["created"] is False and second["duplicate"] is True
    assert second["item"]["id"] == first["item"]["id"]
    assert [item["id"] for item in found] == [first["item"]["id"]]


@pytest.mark.asyncio
async def test_one_item_can_carry_several_references_and_be_found_by_any(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    item = (await repo.add_item(
        session_id=session["id"], title="Ship the field change",
        refs=[{"ref_kind": "gmail_thread", "source_system": "gmail", "external_id": "t-9", "role": "origin"}],
    ))["item"]
    await repo.add_ref(
        session_id=session["id"], item_id=item["id"],
        ref={"ref_kind": "speakeasy_request", "source_system": "speakeasy", "external_id": "req-4", "role": "delegated_to"},
    )
    await repo.add_ref(
        session_id=session["id"], item_id=item["id"],
        ref={"ref_kind": "salesforce_deployment", "source_system": "salesforce", "source_scope": "org-a", "external_id": "0Af1", "role": "produced"},
    )

    by_request = await repo.find_items(session["id"], external_id="req-4", ref_kind="speakeasy_request")
    wrong_kind = await repo.find_items(session["id"], external_id="req-4", ref_kind="gmail_thread")

    assert [found["id"] for found in by_request] == [item["id"]]
    assert wrong_kind == []
    assert {ref["role"] for ref in by_request[0]["refs"]} == {"origin", "delegated_to", "produced"}


@pytest.mark.asyncio
async def test_reference_and_item_caps_hold(tmp_path, monkeypatch):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    refs = [{"ref_kind": "file", "external_id": f"/tmp/{index}.txt", "label": "x" * 500} for index in range(30)]
    item = (await repo.add_item(session_id=session["id"], title="Many refs", refs=refs))["item"]
    assert len(item["refs"]) == 12 and all(len(ref["label"]) <= 120 for ref in item["refs"])

    monkeypatch.setattr(checklist_repository, "MAX_ITEMS_PER_SESSION", 2)
    await repo.add_item(session_id=session["id"], title="Second")
    rejected = await repo.add_item(session_id=session["id"], title="Third")
    assert rejected["created"] is False and "limit" in rejected["rejected"]


@pytest.mark.asyncio
async def test_counts_exclude_archived_and_dropped_and_closing_reopens_on_new_work(tmp_path):
    service, session = await _service_with_session(tmp_path)
    repo = service.agent_checklist_repository
    ids = [(await repo.add_item(session_id=session["id"], title=f"Step {n}", required=n == 0))["item"]["id"] for n in range(5)]
    await repo.update_item(session_id=session["id"], item_id=ids[0], changes={"status": "done"})
    await repo.update_item(session_id=session["id"], item_id=ids[1], changes={"status": "waiting_user", "waiting_on": "Decision"})
    await repo.update_item(session_id=session["id"], item_id=ids[2], changes={"status": "dropped"})
    await repo.set_archived(session_id=session["id"], item_id=ids[3], archived=True)

    state = await repo.get_state(session["id"])
    by_root = await repo.counts_for_roots(["root-task", "no-such-root"])

    assert state["counts"] == {"total": 3, "done": 1, "open": 2, "waiting_user": 1, "waiting_external": 0, "required_open": 0}
    assert by_root == {"root-task": state["counts"]}
    assert len(await repo.list_items(session["id"])) == 4
    assert len(await repo.list_items(session["id"], include_archived=True)) == 5

    assert (await repo.set_closed(session["id"], True))["closed_at"]
    await repo.add_item(session_id=session["id"], title="New work")
    assert (await repo.get_state(session["id"]))["closed_at"] is None


@pytest.mark.asyncio
async def test_checklist_items_never_enter_the_coverage_ledger(tmp_path):
    service, session = await _service_with_session(tmp_path)
    await service.agent_checklist_repository.add_item(session_id=session["id"], title="User step")
    item = (await service.agent_checklist_repository.list_items(session["id"]))[0]
    await service.agent_checklist_repository.update_item(session_id=session["id"], item_id=item["id"], changes={"status": "in_progress"})

    claimed = await service.agent_work_item_repository.claim_next(
        session_id=session["id"], statuses=["in_progress", "discovered"], limit=5, mark_status="in_progress"
    )
    summary = await service.agent_work_session_repository.summarize(session["id"])

    assert claimed == []
    assert not summary.get("unresolved_count")


@pytest.mark.asyncio
async def test_captured_work_item_with_the_same_external_id_is_linked(tmp_path):
    service, session = await _service_with_session(tmp_path)
    await service.agent_work_item_repository.add_items(
        session_id=session["id"], items=[{"external_id": "thread-77", "source_system": "gmail"}]
    )
    captured = (await service.agent_work_item_repository.get_items(session_id=session["id"]))[0]

    item = (await service.agent_checklist_repository.add_item(
        session_id=session["id"], title="Reply", refs=[{"ref_kind": "gmail_thread", "external_id": "thread-77"}]
    ))["item"]

    assert (await service.agent_checklist_repository.get_item(session["id"], item["id"]))["work_item_id"] == captured["id"]


@pytest.mark.asyncio
async def test_carry_copies_only_open_items_once(tmp_path):
    service, first = await _service_with_session(tmp_path, root="run-1")
    await service.store_agent_task(agent_task_id="run-2", original_prompt="Sort inbox", transcribed_prompt="Sort inbox", status="processing")
    second = await service.agent_work_session_repository.get_or_create_root_session(
        root_task_id="run-2", goal="Sort inbox", collection_type="agent_work", agent_task_id="run-2"
    )
    repo = service.agent_checklist_repository
    open_item = (await repo.add_item(
        session_id=first["id"], title="Await the referral", status="waiting_external",
        refs=[{"ref_kind": "gmail_thread", "external_id": "t-1"}],
    ))["item"]
    done_item = (await repo.add_item(session_id=first["id"], title="Already done"))["item"]
    await repo.update_item(session_id=first["id"], item_id=done_item["id"], changes={"status": "done"})
    dropped = (await repo.add_item(session_id=first["id"], title="Dropped"))["item"]
    await repo.update_item(session_id=first["id"], item_id=dropped["id"], changes={"status": "dropped"})

    copied = await repo.copy_carryable_items(from_session_id=first["id"], to_session_id=second["id"], agent_task_id="run-2")
    again = await repo.copy_carryable_items(from_session_id=first["id"], to_session_id=second["id"], agent_task_id="run-2")
    carried = await repo.list_items(second["id"])

    assert (copied, again) == (1, 0)
    assert [item["title"] for item in carried] == ["Await the referral"]
    assert carried[0]["origin"] == "carried" and carried[0]["carried_from_item_id"] == open_item["id"]
    assert carried[0]["refs"][0]["external_id"] == "t-1"


@pytest.mark.asyncio
async def test_notes_append_edit_cap_and_revision_conflict(tmp_path):
    service, session = await _service_with_session(tmp_path)
    notes = service.agent_checklist_notes_repository

    first = await notes.append_notes(session["id"], "Waiting on the clinic.", actor="agent")
    assert first["ok"] and first["notes"]["revision"] == 1

    stale = await notes.append_notes(session["id"], "late", actor="user", expected_revision=0)
    assert stale["conflict"] is True

    over = await notes.append_notes(session["id"], "x" * 50, max_chars=40)
    assert over["rejected"] == "over_limit" and over["limit"] == 40 and "Condense" in over["error"]

    missing = await notes.edit_notes(session["id"], "not there", "y")
    assert "not found" in missing["error"]

    await notes.append_notes(session["id"], "Waiting on the clinic.")
    ambiguous = await notes.edit_notes(session["id"], "Waiting on the clinic.", "Done.")
    assert "2 times" in ambiguous["error"]

    shrunk = await notes.set_notes(session["id"], "Short.", max_chars=10)
    assert shrunk["ok"] and shrunk["notes"]["content"] == "Short."
    assert (await notes.get_notes(session["id"]))["revision"] == shrunk["notes"]["revision"]


@pytest.mark.asyncio
async def test_deleting_the_work_session_removes_checklist_rows(tmp_path):
    service, session = await _service_with_session(tmp_path)
    item = (await service.agent_checklist_repository.add_item(
        session_id=session["id"], title="Step", refs=[{"ref_kind": "url", "external_id": "https://example.com"}]
    ))["item"]
    await service.agent_checklist_notes_repository.append_notes(session["id"], "note")

    connection = sqlite3.connect(tmp_path / "knowledge.db")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("DELETE FROM agent_work_sessions WHERE id = ?", (session["id"],))
    connection.commit()
    remaining = [
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("agent_checklists", "agent_checklist_items", "agent_checklist_refs", "agent_checklist_events")
    ]
    connection.close()

    assert item["id"] and remaining == [0, 0, 0, 0]


def test_opening_an_existing_database_adds_the_checklist_tables(tmp_path):
    database = tmp_path / "knowledge.db"
    SQLiteKnowledgeService(database)
    connection = sqlite3.connect(database)
    for table in ("agent_checklist_events", "agent_checklist_refs", "agent_checklist_items", "agent_checklists"):
        connection.execute(f"DROP TABLE {table}")
    connection.commit()
    connection.close()

    SQLiteKnowledgeService(database)

    connection = sqlite3.connect(database)
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    connection.close()
    assert {"agent_checklists", "agent_checklist_items", "agent_checklist_refs", "agent_checklist_events"} <= names


@pytest.mark.asyncio
async def test_deleting_the_chain_removes_its_checklist_but_keeps_captured_evidence(tmp_path):
    service, session = await _service_with_session(tmp_path)
    await service.agent_work_item_repository.add_items(session_id=session["id"], items=[{"external_id": "thread-5"}])
    await service.agent_checklist_repository.add_item(
        session_id=session["id"], title="Step", refs=[{"ref_kind": "gmail_thread", "external_id": "thread-5"}]
    )
    await service.agent_checklist_notes_repository.append_notes(session["id"], "private note")

    assert await service.agent_task_service.delete_agent_task("root-task", cascade=True) is True

    connection = sqlite3.connect(tmp_path / "knowledge.db")
    counts = [
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("agent_checklists", "agent_checklist_items", "agent_checklist_refs", "agent_checklist_events", "agent_work_items")
    ]
    connection.close()
    assert counts == [0, 0, 0, 0, 1]
