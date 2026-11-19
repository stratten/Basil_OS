"""Per-schedule checklist carry-over: config round trip and seeding at run start."""

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.scheduled_chain_config import (
    normalize_chain_config,
    parse_chain_config,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.scheduled_checklist_carry import (
    carry_checklist_into_run,
)


def test_carry_checklist_defaults_off_and_keeps_existing_canonical_forms():
    assert normalize_chain_config(None) == {"mode": "independent"}
    assert normalize_chain_config({"mode": "independent"}) == {"mode": "independent"}
    assert normalize_chain_config({"mode": "chained", "max_runs": 3}) == {"mode": "chained", "carry_over": True, "max_runs": 3}
    assert parse_chain_config({"mode": "independent"}).carry_checklist is False


def test_carry_checklist_applies_to_independent_and_chained_schedules():
    independent = normalize_chain_config({"mode": "independent", "carry_checklist": True})
    chained = normalize_chain_config({"mode": "chained", "max_runs": 3, "carry_checklist": True})

    assert independent == {"mode": "independent", "carry_checklist": True}
    assert chained["carry_checklist"] is True
    assert parse_chain_config(independent).carry_checklist is True and not parse_chain_config(independent).is_chained
    assert parse_chain_config(chained).carry_checklist is True and parse_chain_config(chained).is_chained


def test_carry_checklist_must_be_a_boolean():
    with pytest.raises(ValueError):
        normalize_chain_config({"mode": "independent", "carry_checklist": "yes"})


class _Repo:
    def __init__(self, anchor=None, error=None):
        self.anchor, self.error = anchor, error

    async def latest_chain_anchor(self, schedule_id, run_id):
        if self.error:
            raise self.error
        return self.anchor


async def _previous_run(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    for task_id in ("run-1", "run-2"):
        await service.store_agent_task(agent_task_id=task_id, original_prompt="Inbox", transcribed_prompt="Inbox", status="completed")
    first = await service.agent_work_session_repository.get_or_create_root_session(
        root_task_id="run-1", goal="Inbox", collection_type="agent_work", agent_task_id="run-1"
    )
    repo = service.agent_checklist_repository
    waiting = (await repo.add_item(session_id=first["id"], title="Wait for the GP", status="waiting_external"))["item"]
    finished = (await repo.add_item(session_id=first["id"], title="Finished"))["item"]
    await repo.update_item(session_id=first["id"], item_id=finished["id"], changes={"status": "done"})
    await service.agent_checklist_notes_repository.append_notes(first["id"], "Clinic replies on Fridays.", actor="agent")
    return service, waiting


def _schedule(carry):
    return {"id": "sched-1", "agent_task_text": "Sort my inbox", "chain_config": {"mode": "independent", **({"carry_checklist": True} if carry else {})}}


@pytest.mark.asyncio
async def test_open_items_and_notes_seed_the_new_run_and_done_items_stay_behind(tmp_path):
    service, _ = await _previous_run(tmp_path)

    notice = await carry_checklist_into_run(
        _Repo({"root_task_id": "run-1"}), _schedule(True), run_id="r2", new_root_task_id="run-2",
        continuing_chain=False, knowledge_service=service,
    )
    session = await service.agent_work_session_repository.get_latest_session_for_root("run-2")
    carried = await service.agent_checklist_repository.list_items(session["id"])
    notes = await service.agent_checklist_notes_repository.get_notes(session["id"])

    assert notice == "Carried 1 open checklist item and the checklist notes over from the previous run."
    assert [(item["title"], item["origin"], item["status"]) for item in carried] == [("Wait for the GP", "carried", "waiting_external")]
    assert notes["content"] == "Clinic replies on Fridays." and notes["updated_by"] == "system" and notes["carried_from_task_id"] == "run-1"


@pytest.mark.asyncio
async def test_nothing_is_carried_when_off_when_continuing_a_chain_or_when_there_is_no_earlier_run(tmp_path):
    service, _ = await _previous_run(tmp_path)
    anchor = {"root_task_id": "run-1"}

    off = await carry_checklist_into_run(_Repo(anchor), _schedule(False), run_id="r2", new_root_task_id="run-2", continuing_chain=False, knowledge_service=service)
    continuing = await carry_checklist_into_run(_Repo(anchor), _schedule(True), run_id="r2", new_root_task_id="run-2", continuing_chain=True, knowledge_service=service)
    first_run = await carry_checklist_into_run(_Repo(None), _schedule(True), run_id="r2", new_root_task_id="run-2", continuing_chain=False, knowledge_service=service)

    assert (off, continuing, first_run) == (None, None, None)
    assert await service.agent_work_session_repository.get_latest_session_for_root("run-2") is None


@pytest.mark.asyncio
async def test_a_lookup_failure_never_blocks_the_run_and_a_second_call_copies_nothing_more(tmp_path):
    service, _ = await _previous_run(tmp_path)

    failed = await carry_checklist_into_run(
        _Repo(error=RuntimeError("db busy")), _schedule(True), run_id="r2", new_root_task_id="run-2", continuing_chain=False, knowledge_service=service,
    )
    first = await carry_checklist_into_run(_Repo({"root_task_id": "run-1"}), _schedule(True), run_id="r2", new_root_task_id="run-2", continuing_chain=False, knowledge_service=service)
    again = await carry_checklist_into_run(_Repo({"root_task_id": "run-1"}), _schedule(True), run_id="r2", new_root_task_id="run-2", continuing_chain=False, knowledge_service=service)

    assert failed is None and first is not None and again is None
    session = await service.agent_work_session_repository.get_latest_session_for_root("run-2")
    assert len(await service.agent_checklist_repository.list_items(session["id"])) == 1
