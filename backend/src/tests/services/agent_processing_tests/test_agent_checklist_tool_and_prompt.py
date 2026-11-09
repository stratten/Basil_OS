"""Model surface for the task checklist: the tool, the bounded per-turn block, and core registration."""

import json

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.models.reasoning.model_runtime_profile import TOOL_RENDERING_SLIM_SCHEMA
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import CORE_TOOL_NAMES
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import (
    build_turn_runtime_context,
    strip_runtime_context,
)
from api.services.agent_processing.lifecycle.runtime.agent_checklist_prompt import build_checklist_prompt_section
from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import AgentChecklistService
from api.services.agent_processing.tools.internal_basil_tools.checklist_tool import create_checklist_tool

EMPTY_NOTES = {"content": "", "revision": 0, "updated_by": None, "carried_from_task_id": None}


def _item(index, status="pending", **extra):
    return {"id": f"{index:08d}-aaaa", "title": f"Item {index}", "status": status, "required": False, "sort_order": index, **extra}


def _counts(total, done=0, waiting_user=0):
    return {"total": total, "done": done, "open": total - done, "waiting_user": waiting_user, "waiting_external": 0, "required_open": 0}


def test_block_is_empty_when_there_is_nothing_to_show():
    assert build_checklist_prompt_section([], _counts(0), EMPTY_NOTES, prompt_budget_tokens=20000) == ""


def test_block_lists_waiting_on_the_user_first_and_tags_user_edits():
    items = [
        _item(1, "pending"),
        _item(2, "waiting_user", waiting_on="Pick a visit time", last_actor="user", title="Book GP visit"),
        _item(3, "done"),
    ]

    section = build_checklist_prompt_section(items, _counts(3, done=1, waiting_user=1), EMPTY_NOTES, prompt_budget_tokens=20000)

    lines = section.splitlines()
    assert "1 of 3 done, 1 waiting on the user" in lines[0]
    assert lines[1].startswith("- [waiting_user] Book GP visit (id 00000002)")
    assert "waiting on: Pick a visit time" in lines[1] and "(edited by the user)" in lines[1]
    assert lines[2].startswith("- [pending] Item 1")
    assert "Item 3" not in section


@pytest.mark.parametrize("budget_tokens", [20000, 12000, 100000])
def test_block_stays_under_its_cap_with_hundreds_of_items_and_long_titles(budget_tokens):
    items = [_item(index, "pending", title="very long title " * 40) for index in range(1, 501)]

    section = build_checklist_prompt_section(items, _counts(500), EMPTY_NOTES, prompt_budget_tokens=budget_tokens)

    cap = min(3000, int(budget_tokens * 3 * 0.03))
    assert len(section) <= cap + 80
    assert "more open items" in section


def test_small_windows_get_counts_and_the_top_three_only():
    items = [_item(index, "pending") for index in range(1, 40)]
    notes = {**EMPTY_NOTES, "content": "n" * 900}

    section = build_checklist_prompt_section(items, _counts(39), notes, prompt_budget_tokens=4000)

    assert len(section) <= 500
    assert section.count("- [pending]") == 3 and "36 more open items" in section
    assert "n" * 20 not in section and "NOTES exist" in section


def test_notes_are_inline_only_when_short_and_labeled_when_carried_or_user_edited():
    short = {**EMPTY_NOTES, "content": "Waiting on clinic.", "updated_by": "system", "carried_from_task_id": "run-1"}
    long = {**EMPTY_NOTES, "content": "x" * 1800}
    edited = {**EMPTY_NOTES, "content": "Plan B.", "updated_by": "user"}
    items = [_item(1)]

    carried = build_checklist_prompt_section(items, _counts(1), short, prompt_budget_tokens=30000)
    breadcrumb = build_checklist_prompt_section(items, _counts(1), long, prompt_budget_tokens=30000)
    by_user = build_checklist_prompt_section(items, _counts(1), edited, prompt_budget_tokens=30000)

    assert "carried from the previous run, verify before relying on it" in carried and "Waiting on clinic." in carried
    assert "1800 characters" in breadcrumb and "x" * 50 not in breadcrumb
    assert "last edited by the user" in by_user


def test_runtime_context_carries_the_block_and_synthesis_strips_it():
    context = build_turn_runtime_context(checklist_section="\nCHECKLIST (test)")

    assert "CHECKLIST (test)" in context
    assert strip_runtime_context(f"{context}\n\nthe request") == "the request"


def test_checklist_is_a_core_tool_with_a_slim_variant():
    assert "checklist" in CORE_TOOL_NAMES
    full = create_checklist_tool().description
    slim = create_checklist_tool(profile=_SlimProfile()).description
    assert create_checklist_tool().name == "checklist" and len(slim) < len(full)


class _SlimProfile:
    """Stand-in for a runtime profile that asks for compact tool descriptions."""

    tool_rendering = TOOL_RENDERING_SLIM_SCHEMA


def _use_context(monkeypatch, context):
    monkeypatch.setattr("api.services.agent_processing.shared.get_current_agent_context", lambda: context)


@pytest_asyncio.fixture
async def wired(tmp_path, monkeypatch):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(agent_task_id="root-1", original_prompt="Inbox", transcribed_prompt="Inbox", status="processing")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    published = []

    async def capture(self, message):
        published.append(message)

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster.AgentTaskEventBroadcaster.broadcast", capture
    )
    _use_context(monkeypatch, {"agent_task_id": "root-1", "root_task_id": "root-1", "user_agent_task": "Inbox"})
    return service, published


async def _call(tool, **arguments):
    return json.loads(await tool.ainvoke(arguments))


@pytest.mark.asyncio
async def test_tool_round_trip_by_short_id_with_references_and_live_event(wired):
    service, published = wired
    tool = create_checklist_tool()

    added = await _call(
        tool, action="add", title="Reply to the clinic", required=True,
        refs=[{"ref_kind": "gmail_thread", "source_system": "gmail", "external_id": "thread-9", "label": "Clinic"}],
    )
    short = added["item"]["id"]
    updated = await _call(tool, action="update", item=short, status="waiting_user", waiting_on="Choose a slot", event_text="two slots")
    found = await _call(tool, action="find", external_id="thread-9")
    listed = await _call(tool, action="list")
    duplicate = await _call(tool, action="add", title="Again", refs=[{"ref_kind": "gmail_thread", "source_system": "gmail", "external_id": "thread-9"}])

    assert added["created"] and len(short) == 8
    assert updated["item"]["status"] == "waiting_user" and updated["item"]["waiting_on"] == "Choose a slot"
    assert [item["id"] for item in found["items"]] == [short] and found["items"][0]["refs"][0]["label"] == "Clinic"
    assert listed["counts"]["waiting_user"] == 1 and len(listed["items"]) == 1
    assert duplicate["created"] is False and duplicate["item"]["id"] == short
    assert published and published[-1]["event_type"] == "agent_checklist_updated" and published[-1]["root_task_id"] == "root-1"


@pytest.mark.asyncio
async def test_tool_returns_correctable_errors_instead_of_raising(wired):
    tool = create_checklist_tool()
    await _call(tool, action="add", title="Real")

    bad_status = await _call(tool, action="add", title="X", status="discovered")
    unknown = await _call(tool, action="update", item="deadbeef", status="done")
    empty_update = await _call(tool, action="update", item="deadbeef")
    empty_find = await _call(tool, action="find")
    blank_title = await _call(tool, action="add", title="  ")

    assert bad_status["success"] is False and "status must be one of" in bad_status["error"]
    assert unknown["success"] is False and "No checklist item matches" in unknown["error"]
    assert "at least one field" in empty_update["error"] and "external_id or query" in empty_find["error"]
    assert blank_title["success"] is False and "title is required" in blank_title["error"]


def _email_entry(number, **extra):
    return {
        "title": f"Reply to sender {number}", "status": "waiting_user", "waiting_on": f"Approve the reply to sender {number}",
        "refs": [{"ref_kind": "gmail_thread", "source_system": "gmail", "external_id": f"thread-{number}", "label": f"Thread {number}"}],
        **extra,
    }


@pytest.mark.asyncio
async def test_add_with_items_creates_one_item_per_entry_in_a_single_call_and_publishes_once(wired):
    _service, published = wired
    tool = create_checklist_tool()
    published.clear()

    added = await _call(tool, action="add", items=[_email_entry(number) for number in range(1, 6)])
    listed = await _call(tool, action="list")

    assert added["success"] is True and added["created"] == 5 and len(added["items"]) == 5
    assert "errors" not in added and "already_tracked" not in added
    assert [item["title"] for item in listed["items"]] == [f"Reply to sender {number}" for number in range(1, 6)]
    assert listed["counts"]["waiting_user"] == 5
    assert all(item["refs"][0]["external_id"].startswith("thread-") for item in added["items"])
    assert len([message for message in published if message["event_type"] == "agent_checklist_updated"]) == 1


@pytest.mark.asyncio
async def test_add_with_items_reports_bad_entries_and_duplicates_but_still_adds_the_rest(wired):
    tool = create_checklist_tool()
    await _call(tool, action="add", items=[_email_entry(1)])

    mixed = await _call(tool, action="add", items=[_email_entry(1), {"title": "  "}, _email_entry(2, status="discovered"), _email_entry(3)])

    assert mixed["success"] is True and mixed["created"] == 1 and mixed["items"][0]["title"] == "Reply to sender 3"
    assert [item["title"] for item in mixed["already_tracked"]] == ["Reply to sender 1"]
    assert len(mixed["errors"]) == 2
    assert "items[2]" in mixed["errors"][0] and "title is required" in mixed["errors"][0]
    assert "items[3]" in mixed["errors"][1] and "status must be one of" in mixed["errors"][1]


@pytest.mark.asyncio
async def test_add_with_items_rejects_title_plus_items_and_oversized_batches(wired):
    tool = create_checklist_tool()

    both = await _call(tool, action="add", title="One", items=[_email_entry(1)])
    too_many = await _call(tool, action="add", items=[{"title": f"Step {number}"} for number in range(26)])
    listed = await _call(tool, action="list")

    assert both["success"] is False and "either title or items" in both["error"]
    assert too_many["success"] is False and "at most 25 entries" in too_many["error"]
    assert listed["items"] == []


@pytest.mark.asyncio
async def test_prompt_section_reflects_the_list_and_user_edits_but_never_creates_a_session(wired):
    service, _published = wired
    checklist = AgentChecklistService(service)
    context = {"agent_task_id": "root-1", "root_task_id": "root-1"}

    assert await checklist.prompt_section(context, prompt_budget_tokens=20000) == ""
    assert await service.agent_work_session_repository.get_latest_session_for_root("root-1") is None

    added = await _call(create_checklist_tool(), action="add", title="Book the visit")
    session = await service.agent_work_session_repository.get_latest_session_for_root("root-1")
    await service.agent_checklist_repository.update_item(
        session_id=session["id"], item_id=(await service.agent_checklist_repository.list_items(session["id"]))[0]["id"],
        changes={"status": "in_progress"}, actor="user",
    )
    section = await checklist.prompt_section(context, prompt_budget_tokens=20000)

    assert added["created"] and "Book the visit" in section and "(edited by the user)" in section
    assert section.startswith("\nCHECKLIST")


@pytest.mark.asyncio
async def test_a_follow_up_in_the_same_chain_sees_the_same_checklist(wired, monkeypatch):
    service, _published = wired
    await _call(create_checklist_tool(), action="add", title="Carry me")
    _use_context(monkeypatch, {"agent_task_id": "follow-up-2", "root_task_id": "root-1"})
    listed = await _call(create_checklist_tool(), action="list")

    assert [item["title"] for item in listed["items"]] == ["Carry me"]


async def _seed_ledger(service, count):
    await service.agent_work_session_repository.get_or_create_root_session(root_task_id="root-1", goal="g", collection_type="agent_work")
    session = await service.agent_work_session_repository.get_latest_session_for_root("root-1")
    await service.agent_work_item_repository.add_items(session_id=session["id"], items=[{"external_id": f"thread-{n}"} for n in range(count)])


@pytest.mark.asyncio
async def test_empty_checklist_with_ledger_records_gets_a_one_line_hint(wired):
    service, _published = wired
    checklist = AgentChecklistService(service)
    context = {"agent_task_id": "root-1", "root_task_id": "root-1"}

    await _seed_ledger(service, 2)
    few = await checklist.prompt_section(context, prompt_budget_tokens=20000)
    await _seed_ledger(service, 3)
    hinted = await checklist.prompt_section(context, prompt_budget_tokens=20000)
    await _call(create_checklist_tool(), action="add", title="One real item")
    with_items = await checklist.prompt_section(context, prompt_budget_tokens=20000)

    assert few == ""
    assert hinted.startswith("\nCHECKLIST (empty)") and "coverage ledger" in hinted and hinted.count("\n") == 1
    assert "(empty)" not in with_items and "One real item" in with_items


def test_set_of_records_guidance_is_in_the_system_prompt_and_both_tool_descriptions():
    from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE

    for text in (AGENT_SYSTEM_PROMPT_TEMPLATE, create_checklist_tool().description, create_checklist_tool(profile=_SlimProfile()).description):
        assert "one item per record" in text or "item for each record" in text
        assert "waiting_user" in text
        assert "items" in text


def test_checklist_is_described_as_outcomes_not_agent_steps_on_every_surface():
    from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_prompt import (
        build_empty_checklist_review,
        build_ledger_hint,
        build_mid_run_cue,
    )

    surfaces = (
        AGENT_SYSTEM_PROMPT_TEMPLATE,
        create_checklist_tool().description,
        create_checklist_tool(profile=_SlimProfile()).description,
        build_ledger_hint(),
        build_mid_run_cue(),
        build_empty_checklist_review(),
    )
    for text in surfaces:
        lowered = text.lower()
        assert "propose an action on" not in lowered
        assert "propose a reply" in lowered or "proposal" in lowered or "outcome" in lowered
    for text in surfaces[:3] + surfaces[4:5]:
        assert "outcome" in text.lower()
    assert "step list" not in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "does not complete an item" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "does not complete an item" in create_checklist_tool().description
