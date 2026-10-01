import asyncio
import sqlite3
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.conversation import conversation_summary_contract as contract
from api.services.conversation import conversation_turn_summarizer as summarizer_module
from api.services.conversation.conversation_service import ConversationService
from api.services.conversation.conversation_turn_contract import CONVERSATION_TURN_METADATA_KEY
from api.services.conversation.conversation_turn_summarizer import (
    ConversationTurnSummarizer,
    SummaryPassOutcome,
    clean_summary_output,
    local_model_is_idle,
)

REGISTRY = {"local-model": {"location": "local"}, "cloud-model": {"location": "cloud"}}


class FakeLocalModel:
    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.native_execution_lock = threading.RLock()

    async def generate_from_messages(self, messages, *, max_tokens=None, preserve_thinking=False):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if self.error is not None:
            raise self.error
        return f"<think>private notes</think>Summary {len(self.calls)}"


class FakeCloudModel:
    def __init__(self):
        self.calls = []

    async def generate_from_messages(self, messages, *, max_tokens=None, preserve_thinking=False, enable_web_search=True):
        self.calls.append({"messages": messages, "enable_web_search": enable_web_search})
        return f"Cloud summary {len(self.calls)}"


@pytest.fixture(autouse=True)
def small_thresholds(monkeypatch):
    monkeypatch.setattr(summarizer_module, "SUMMARY_ELIGIBILITY_TOKENS", 10)
    monkeypatch.setattr(summarizer_module, "get_model", REGISTRY.get)


@pytest_asyncio.fixture
async def service(tmp_path):
    conversation_service = ConversationService(
        model_service=MagicMock(),
        development_mode=True,
        sqlite_knowledge_service=SQLiteKnowledgeService(tmp_path / "summaries.db"),
    )
    try:
        yield conversation_service
    finally:
        await conversation_service.shutdown_background_tasks()


async def seed(service, exchanges, *, model_id="local-model", assistant_metadata=None):
    conversation = await service.create_conversation()
    repository = service.conversation_repository
    anchors = []
    for index in range(exchanges):
        await repository.add_message(conversation.id, "user", f"Question {index} about the release plan")
        anchors.append(
            await repository.add_message(
                conversation.id,
                "assistant",
                f"Answer {index} with the details",
                model_id=model_id,
                metadata=assistant_metadata,
            )
        )
    return conversation.id, anchors


def make_summarizer(service, *, active=None, load_model=None, schedule_task=None):
    active_models = active or {}
    return ConversationTurnSummarizer(
        repository=service.conversation_repository,
        load_conversation=service.get_conversation,
        get_active_model=active_models.get,
        load_model=load_model or AsyncMock(return_value=None),
        schedule_task=schedule_task or service._schedule_background_task,
    )


async def persisted(service, conversation_id):
    return await service.conversation_repository.get_conversation_with_messages(conversation_id)


async def summaries(service, conversation_id):
    data = await persisted(service, conversation_id)
    return {
        item["id"]: item["metadata"].get(contract.TURN_SUMMARY_METADATA_KEY)
        for item in data["messages"]
        if item["role"] == "assistant"
    }


def backdate(service, conversation_id):
    with sqlite3.connect(service.conversation_repository.db_path) as connection:
        connection.execute("UPDATE conversations SET updated_at = '2020-01-01 00:00:00' WHERE id = ?", (conversation_id,))


@pytest.mark.asyncio
async def test_short_conversation_is_not_eligible(service, monkeypatch):
    monkeypatch.setattr(summarizer_module, "SUMMARY_ELIGIBILITY_TOKENS", 100000)
    conversation_id, _ = await seed(service, 5)
    model = FakeLocalModel()
    outcome = await make_summarizer(service, active={"local-model": model}).run_pass(conversation_id)
    assert outcome.eligible is False
    assert model.calls == []


@pytest.mark.asyncio
async def test_pass_summarizes_oldest_exchanges_with_the_producing_model_and_builds_a_brief(service):
    conversation_id, anchors = await seed(service, 7)
    backdate(service, conversation_id)
    model = FakeLocalModel()
    outcome = await make_summarizer(service, active={"local-model": model}).run_pass(conversation_id)

    assert outcome.summarized == 4
    assert outcome.brief_updated is True
    stored = await summaries(service, conversation_id)
    for index in range(4):
        record = stored[anchors[index]]
        assert record["status"] == "completed"
        assert record["text"] == f"Summary {index + 1}"
        assert record["model_id"] == "local-model"
        assert record["source_fingerprint"] == contract.exchange_fingerprint(
            f"Question {index} about the release plan",
            f"Answer {index} with the details",
        )
    assert stored[anchors[4]] is None
    assert stored[anchors[5]] is None and stored[anchors[6]] is None
    assert all(isinstance(call["max_tokens"], int) and call["max_tokens"] > 0 for call in model.calls)

    data = await persisted(service, conversation_id)
    brief = data["metadata"][contract.CONVERSATION_BRIEF_METADATA_KEY]
    assert brief["text"] == "Summary 5"
    assert brief["covered_anchor_ids"] == anchors[:4]
    assert brief["model_id"] == "local-model"
    assert data["updated_at"] == "2020-01-01 00:00:00"


@pytest.mark.asyncio
async def test_later_pass_continues_and_folds_new_summaries_into_the_brief(service):
    conversation_id, anchors = await seed(service, 11)
    model = FakeLocalModel()
    summarizer = make_summarizer(service, active={"local-model": model})
    await summarizer.run_pass(conversation_id)
    outcome = await summarizer.run_pass(conversation_id)

    assert outcome.summarized == 4
    assert outcome.brief_updated is True
    assert len(model.calls) == 10
    assert "Current brief:\n<<<\nSummary 5\n>>>" in model.calls[-1]["messages"][1]["content"]
    data = await persisted(service, conversation_id)
    assert data["metadata"][contract.CONVERSATION_BRIEF_METADATA_KEY]["covered_anchor_ids"] == anchors[:8]


@pytest.mark.asyncio
async def test_edited_reply_is_resummarized_and_the_brief_is_rebuilt(service):
    conversation_id, anchors = await seed(service, 7)
    model = FakeLocalModel()
    summarizer = make_summarizer(service, active={"local-model": model})
    await summarizer.run_pass(conversation_id)
    await service.conversation_repository.update_message(message_id=anchors[1], content="Answer 1 corrected")

    outcome = await summarizer.run_pass(conversation_id)

    assert outcome.summarized == 2
    stored = await summaries(service, conversation_id)
    assert stored[anchors[1]]["source_fingerprint"] == contract.exchange_fingerprint(
        "Question 1 about the release plan",
        "Answer 1 corrected",
    )
    assert stored[anchors[1]]["attempt_count"] == 1
    assert "Current brief:\n<<<\n(none yet)\n>>>" in model.calls[-1]["messages"][1]["content"]
    data = await persisted(service, conversation_id)
    assert data["metadata"][contract.CONVERSATION_BRIEF_METADATA_KEY]["covered_anchor_ids"] == anchors[:5]


@pytest.mark.asyncio
async def test_local_model_that_is_not_loaded_is_never_loaded(service):
    conversation_id, _ = await seed(service, 3)
    load_model = AsyncMock()
    outcome = await make_summarizer(service, load_model=load_model).run_pass(conversation_id)
    assert outcome.skipped_unavailable == 1
    load_model.assert_not_awaited()
    assert all(value is None for value in (await summaries(service, conversation_id)).values())


@pytest.mark.asyncio
async def test_unknown_model_location_is_never_loaded(service):
    conversation_id, _ = await seed(service, 3, model_id="mystery-model")
    load_model = AsyncMock()
    outcome = await make_summarizer(service, load_model=load_model).run_pass(conversation_id)
    assert outcome.skipped_unavailable == 1
    load_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_cloud_model_is_prepared_and_web_search_is_disabled(service):
    conversation_id, anchors = await seed(service, 3, model_id="cloud-model")
    cloud = FakeCloudModel()
    load_model = AsyncMock(return_value=cloud)
    outcome = await make_summarizer(service, load_model=load_model).run_pass(conversation_id)
    assert outcome.summarized == 1
    load_model.assert_awaited_once_with("cloud-model")
    assert cloud.calls[0]["enable_web_search"] is False
    assert (await summaries(service, conversation_id))[anchors[0]]["text"] == "Cloud summary 1"


@pytest.mark.asyncio
async def test_busy_local_model_stops_the_pass_without_recording_a_failure(service):
    conversation_id, _ = await seed(service, 3)
    model = FakeLocalModel()
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock():
        with model.native_execution_lock:
            acquired.set()
            release.wait(5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert acquired.wait(5)
    try:
        outcome = await make_summarizer(service, active={"local-model": model}).run_pass(conversation_id)
    finally:
        release.set()
        holder.join(5)
    assert outcome.stopped_busy is True
    assert model.calls == []
    assert all(value is None for value in (await summaries(service, conversation_id)).values())


@pytest.mark.asyncio
async def test_failures_are_recorded_and_retries_stop_at_the_limit(service):
    conversation_id, anchors = await seed(service, 3)
    model = FakeLocalModel(error=RuntimeError("model crashed"))
    summarizer = make_summarizer(service, active={"local-model": model})
    for attempt in range(1, contract.MAX_TURN_SUMMARY_ATTEMPTS + 1):
        outcome = await summarizer.run_pass(conversation_id)
        assert outcome.failed == 1
        record = (await summaries(service, conversation_id))[anchors[0]]
        assert record["status"] == "failed"
        assert record["attempt_count"] == attempt
        assert record["text"] is None
    outcome = await summarizer.run_pass(conversation_id)
    assert outcome.failed == 0
    assert len(model.calls) == contract.MAX_TURN_SUMMARY_ATTEMPTS


@pytest.mark.asyncio
async def test_agent_task_and_unattributed_exchanges_are_skipped(service):
    agent_metadata = {CONVERSATION_TURN_METADATA_KEY: {"route": "agent_task", "lifecycle": "completed"}}
    agent_conversation, _ = await seed(service, 4, assistant_metadata=agent_metadata)
    unattributed_conversation, _ = await seed(service, 4, model_id=None)
    model = FakeLocalModel()
    summarizer = make_summarizer(service, active={"local-model": model})
    assert (await summarizer.run_pass(agent_conversation)).summarized == 0
    assert (await summarizer.run_pass(unattributed_conversation)).summarized == 0
    assert model.calls == []


@pytest.mark.asyncio
async def test_request_pass_coalesces_requests_into_one_rerun(service):
    tasks = []
    scheduled = []

    def schedule(coroutine, name):
        task = asyncio.get_running_loop().create_task(coroutine)
        tasks.append(task)
        scheduled.append(name)
        return task

    summarizer = make_summarizer(service, schedule_task=schedule)
    gate = asyncio.Event()
    runs = []

    async def fake_run_pass(conversation_id):
        runs.append(conversation_id)
        await gate.wait()
        return SummaryPassOutcome()

    summarizer.run_pass = fake_run_pass
    summarizer.request_pass("c1")
    await asyncio.sleep(0)
    summarizer.request_pass("c1")
    summarizer.request_pass("c1")
    gate.set()
    await asyncio.gather(*tasks)
    assert scheduled == ["conversation-summaries-c1"]
    assert runs == ["c1", "c1"]

    summarizer.request_pass("c1")
    await asyncio.gather(*tasks)
    assert len(scheduled) == 2


def test_clean_summary_output_strips_reasoning_and_rejects_bad_output():
    assert clean_summary_output("<think>x</think>  Done.  ", 100) == "Done."
    assert clean_summary_output("one two three four", 9) == "one two"
    for bad in ("<think>never closed", "   ", None):
        with pytest.raises(ValueError):
            clean_summary_output(bad, 100)


def test_models_without_a_native_lock_count_as_idle():
    assert local_model_is_idle(object()) is True
    assert local_model_is_idle(MagicMock()) is True
    assert local_model_is_idle(FakeLocalModel()) is True
