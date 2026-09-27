import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.conversation_repository import (
    ConversationAgentNarrationContext,
    ConversationAgentNarrationRecoveryCandidate,
)
from api.services.conversation import conversation_agent_narration_service as narration_module
from api.services.conversation.conversation_agent_narration_service import (
    ConversationAgentNarrationService,
    recover_conversation_agent_narrations,
)


def make_context(
    *,
    agent_task_id="task-1",
    turn_lifecycle="completed",
    narration_lifecycle="ready",
    attempt_count=0,
    terminal_outcome="Agent task completed.",
    assistant_model_id="selected-model",
) -> ConversationAgentNarrationContext:
    return ConversationAgentNarrationContext(
        conversation_id="conversation-1",
        user_message_id="user-1",
        user_content="Please summarize the release notes.",
        user_metadata={},
        assistant_message_id="assistant-1",
        assistant_model_id=assistant_model_id,
        assistant_metadata={
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": turn_lifecycle,
                "agent_task_id": agent_task_id,
                "terminal_outcome": terminal_outcome,
                "user_message_id": "user-1",
                "narration": {"lifecycle": narration_lifecycle, "attempt_count": attempt_count},
            }
        },
    )


def make_task(status="completed", message="The release notes were compiled successfully.") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        result_data={"message": message},
        accumulated_artifacts=None,
        execution_timeline=[],
    )


async def fake_stream(tokens):
    for token in tokens:
        yield token


async def fake_stream_then_raise():
    yield "partial "
    raise RuntimeError("stream interrupted")


def build_service(
    *,
    context: ConversationAgentNarrationContext | None,
    task=None,
    task_error: Exception | None = None,
    models: list | None = None,
) -> tuple[ConversationAgentNarrationService, dict]:
    recorded: dict = {"tokens": [], "resets": [], "statuses": [], "content_updates": [], "metadata_updates": []}

    async def get_agent_task(_agent_task_id):
        if task_error is not None:
            raise task_error
        return task

    model_calls = {"index": 0}
    resolved_models = models if models is not None else []

    async def get_model_for_task(*, capabilities, explicit_model_id):
        recorded.setdefault("model_calls", []).append(explicit_model_id)
        index = model_calls["index"]
        model_calls["index"] += 1
        if index >= len(resolved_models):
            return None
        return resolved_models[index]

    async def send_token(token, message_id, conversation_id, is_final=False):
        recorded["tokens"].append((token, message_id, conversation_id, is_final))

    async def send_stream_reset(message_id, conversation_id, attempt_count):
        recorded["resets"].append((message_id, conversation_id, attempt_count))

    async def broadcast_status(payload):
        recorded["statuses"].append(payload)

    async def update_message(*, message_id, content):
        recorded["content_updates"].append((message_id, content))

    async def merge_message_metadata(message_id, patch):
        recorded["metadata_updates"].append((message_id, patch))

    async def get_conversation_agent_narration_context(_agent_task_id):
        return context

    repository = SimpleNamespace(
        get_conversation_agent_narration_context=get_conversation_agent_narration_context,
        update_message=update_message,
        merge_message_metadata=merge_message_metadata,
    )

    sleeps: list[float] = []

    async def sleep(seconds):
        sleeps.append(seconds)

    recorded["sleeps"] = sleeps

    service = ConversationAgentNarrationService(
        repository=repository,
        get_agent_task=get_agent_task,
        get_model_for_task=get_model_for_task,
        send_token=send_token,
        send_stream_reset=send_stream_reset,
        broadcast_status=broadcast_status,
        sleep=sleep,
    )

    return service, recorded


@pytest.mark.asyncio
async def test_selected_model_narrates_completed_task_into_placeholder():
    context = make_context()
    model = SimpleNamespace(chat_completion_streaming=lambda _m: fake_stream(["The ", "notes ", "are ready."]))
    service, recorded = build_service(context=context, task=make_task(), models=[model])

    await service.narrate("task-1")

    assert recorded["content_updates"] == [("assistant-1", "The notes are ready.")]
    completed_updates = [
        patch["conversation_turn"]["narration"]
        for _mid, patch in recorded["metadata_updates"]
        if patch["conversation_turn"]["narration"]["lifecycle"] == "completed"
    ]
    assert completed_updates == [{"lifecycle": "completed", "attempt_count": 1}]
    assert recorded["tokens"][-1] == ("", "assistant-1", "conversation-1", True)
    assert recorded["statuses"][-1]["narration_state"] == "completed"
    assert recorded["model_calls"] == ["selected-model"]


@pytest.mark.asyncio
async def test_missing_selected_model_falls_back_to_default_reasoning_model():
    context = make_context()
    default_model = SimpleNamespace(chat_completion_streaming=lambda _m: fake_stream(["Fallback narration."]))
    service, recorded = build_service(context=context, task=make_task(), models=[None, default_model])

    await service.narrate("task-1")

    assert recorded["model_calls"] == ["selected-model", None]
    assert recorded["content_updates"] == [("assistant-1", "Fallback narration.")]


@pytest.mark.asyncio
async def test_both_model_resolutions_failing_exhausts_retries_and_persists_fallback():
    context = make_context(terminal_outcome="Agent task failed.")
    service, recorded = build_service(context=context, task=make_task(status="failed"), models=[])

    await service.narrate("task-1")

    assert len(recorded["resets"]) == 2
    assert recorded["resets"][0] == ("assistant-1", "conversation-1", 2)
    assert recorded["resets"][1] == ("assistant-1", "conversation-1", 3)
    assert recorded["sleeps"] == [1.0, 2.0]
    assert recorded["content_updates"][-1][0] == "assistant-1"
    assert "Agent task failed." in recorded["content_updates"][-1][1]
    final_narration = recorded["metadata_updates"][-1][1]["conversation_turn"]["narration"]
    assert final_narration == {"lifecycle": "failed", "attempt_count": 3}
    assert recorded["statuses"][-1]["narration_state"] == "failed"


@pytest.mark.asyncio
async def test_stream_error_resets_before_next_attempt_and_stores_only_successful_content():
    context = make_context()
    failing_model = SimpleNamespace(chat_completion_streaming=lambda _m: fake_stream_then_raise())
    succeeding_model = SimpleNamespace(chat_completion_streaming=lambda _m: fake_stream(["Recovered narration."]))
    service, recorded = build_service(
        context=context,
        task=make_task(),
        models=[failing_model, succeeding_model],
    )

    await service.narrate("task-1")

    assert len(recorded["resets"]) == 1
    assert recorded["content_updates"] == [("assistant-1", "Recovered narration.")]


@pytest.mark.asyncio
async def test_retrying_recovery_retries_the_persisted_attempt_instead_of_skipping_it():
    context = make_context(narration_lifecycle="retrying", attempt_count=1)
    model = SimpleNamespace(chat_completion_streaming=lambda _m: fake_stream(["Recovered attempt two."]))
    service, recorded = build_service(context=context, task=make_task(), models=[model])

    await service.narrate("task-1")

    assert recorded["resets"] == [("assistant-1", "conversation-1", 2)]
    narration_updates = [
        patch["conversation_turn"]["narration"]
        for _message_id, patch in recorded["metadata_updates"]
    ]
    assert narration_updates[0] == {"lifecycle": "retrying", "attempt_count": 1}
    assert narration_updates[1] == {"lifecycle": "narrating", "attempt_count": 2}
    assert narration_updates[-1] == {"lifecycle": "completed", "attempt_count": 2}


@pytest.mark.asyncio
async def test_thinking_only_output_is_treated_as_empty_and_exhausts_retries():
    empty_model = SimpleNamespace(
        chat_completion_streaming=lambda _m: fake_stream(["<think>reasoning</think>"])
    )
    service, recorded = build_service(
        context=make_context(),
        task=make_task(),
        models=[empty_model, empty_model, empty_model],
    )

    await service.narrate("task-1")

    assert recorded["content_updates"][-1][0] == "assistant-1"
    assert "could not prepare" in recorded["content_updates"][-1][1]


@pytest.mark.asyncio
async def test_cancelled_task_uses_durable_terminal_outcome_in_prompt():
    context = make_context(turn_lifecycle="cancelled", terminal_outcome="Agent task was cancelled.")
    captured_messages = {}

    async def capturing_stream(messages):
        captured_messages["messages"] = messages
        yield "Understood, it was cancelled."

    model = SimpleNamespace(chat_completion_streaming=capturing_stream)
    service, recorded = build_service(context=context, task=make_task(status="cancelled"), models=[model])

    await service.narrate("task-1")

    prompt_text = captured_messages["messages"][1]["content"]
    assert "Agent task was cancelled." in prompt_text
    assert recorded["content_updates"] == [("assistant-1", "Understood, it was cancelled.")]
    assert recorded["statuses"][-1]["lifecycle"] == "cancelled"
    assert recorded["statuses"][-1]["agent_status"] == "cancelled"


@pytest.mark.asyncio
async def test_missing_context_produces_no_model_call_or_mutation():
    service, recorded = build_service(context=None, task=make_task(), models=[SimpleNamespace()])

    await service.narrate("task-1")

    assert recorded["content_updates"] == []
    assert recorded.get("model_calls", []) == []


@pytest.mark.asyncio
async def test_nonterminal_turn_produces_no_model_call_or_mutation():
    context = make_context(turn_lifecycle="running")
    service, recorded = build_service(context=context, task=make_task(), models=[SimpleNamespace()])

    await service.narrate("task-1")

    assert recorded["content_updates"] == []
    assert recorded.get("model_calls", []) == []


@pytest.mark.asyncio
async def test_already_completed_narration_produces_no_model_call_or_mutation():
    context = make_context(narration_lifecycle="completed")
    service, recorded = build_service(context=context, task=make_task(), models=[SimpleNamespace()])

    await service.narrate("task-1")

    assert recorded["content_updates"] == []
    assert recorded.get("model_calls", []) == []


@pytest.mark.asyncio
async def test_already_failed_narration_produces_no_model_call_or_mutation():
    context = make_context(narration_lifecycle="failed")
    service, recorded = build_service(context=context, task=make_task(), models=[SimpleNamespace()])

    await service.narrate("task-1")

    assert recorded["content_updates"] == []
    assert recorded.get("model_calls", []) == []


@pytest.mark.asyncio
async def test_task_load_error_is_bounded_and_follows_retry_and_fallback():
    context = make_context()
    service, recorded = build_service(
        context=context,
        task_error=RuntimeError("<secret internal trace>"),
        models=[],
    )

    await service.narrate("task-1")

    fallback_content = recorded["content_updates"][-1][1]
    assert "<secret internal trace>" not in fallback_content
    assert recorded.get("model_calls", []) == []


@pytest.mark.asyncio
async def test_model_resolution_error_retries_and_preserves_failed_terminal_status():
    context = make_context(
        turn_lifecycle="failed",
        terminal_outcome="Agent task failed. Preparing a conversation response.",
    )
    service, recorded = build_service(context=context, task=make_task(status="failed"))

    async def failing_model_resolution(**_kwargs):
        raise RuntimeError("unavailable model service")

    service._get_model_for_task = failing_model_resolution

    await service.narrate("task-1")

    assert recorded["content_updates"][-1][0] == "assistant-1"
    assert recorded["statuses"][-1]["lifecycle"] == "failed"
    assert recorded["statuses"][-1]["agent_status"] == "failed"


@pytest.mark.asyncio
async def test_missing_task_attributes_retry_and_fallback_without_escaping():
    service, recorded = build_service(context=make_context(), task=object())

    await service.narrate("task-1")

    assert recorded["content_updates"][-1][0] == "assistant-1"
    assert recorded["metadata_updates"][-1][1]["conversation_turn"]["narration"] == {
        "lifecycle": "failed",
        "attempt_count": 3,
    }


@pytest.mark.asyncio
async def test_malformed_task_result_never_enters_prompt_as_repr():
    class Unprintable:
        def __repr__(self):
            raise RuntimeError("should never be called")

    context = make_context()
    captured_messages = {}

    async def capturing_stream(messages):
        captured_messages["messages"] = messages
        yield "Narration despite malformed result."

    model = SimpleNamespace(chat_completion_streaming=capturing_stream)
    malformed_task = SimpleNamespace(
        status="completed",
        result_data={"message": Unprintable()},
        accumulated_artifacts=None,
        execution_timeline=[],
    )
    service, recorded = build_service(context=context, task=malformed_task, models=[model])

    await service.narrate("task-1")

    prompt_text = captured_messages["messages"][1]["content"]
    assert "No durable task result was available." in prompt_text
    assert recorded["content_updates"] == [("assistant-1", "Narration despite malformed result.")]


@pytest.mark.asyncio
async def test_task_result_prompt_is_limited_to_the_configured_character_bound():
    context = make_context()
    captured_messages = {}
    oversized_result = "a" * 12000 + "UNSAFE-TAIL"

    async def capturing_stream(messages):
        captured_messages["messages"] = messages
        yield "Bounded narration."

    model = SimpleNamespace(chat_completion_streaming=capturing_stream)
    service, _recorded = build_service(
        context=context,
        task=make_task(message=oversized_result),
        models=[model],
    )

    await service.narrate("task-1")

    prompt_text = captured_messages["messages"][1]["content"]
    task_result = prompt_text.split("Agent Task result:\n", 1)[1]
    assert len(task_result) == 12000
    assert "UNSAFE-TAIL" not in task_result


@pytest.mark.asyncio
async def test_concurrent_narrate_calls_serialize_to_one_stream():
    context_holder = {"context": make_context()}
    call_count = {"value": 0}
    entered = asyncio.Event()
    release = asyncio.Event()

    async def counting_stream(_messages):
        call_count["value"] += 1
        entered.set()
        await release.wait()
        yield "Single narration."

    async def get_conversation_agent_narration_context(_agent_task_id):
        return context_holder["context"]

    async def merge_message_metadata(_message_id, patch):
        narration = patch.get("conversation_turn", {}).get("narration")
        if narration and narration.get("lifecycle") == "completed":
            context_holder["context"] = make_context(narration_lifecycle="completed", attempt_count=1)

    model = SimpleNamespace(chat_completion_streaming=counting_stream)
    service, recorded = build_service(context=context_holder["context"], task=make_task(), models=[model])
    service._repository.get_conversation_agent_narration_context = get_conversation_agent_narration_context
    service._repository.merge_message_metadata = merge_message_metadata

    first = asyncio.create_task(service.narrate("task-1"))
    await entered.wait()
    second = asyncio.create_task(service.narrate("task-1"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    assert call_count["value"] == 1
    assert recorded["content_updates"] == [("assistant-1", "Single narration.")]


@pytest.mark.asyncio
async def test_recover_conversation_agent_narrations_starts_each_unique_candidate(monkeypatch):
    candidates = [
        ConversationAgentNarrationRecoveryCandidate(
            agent_task_id="task-a", assistant_message_id="assistant-a", narration_lifecycle="ready",
        ),
        ConversationAgentNarrationRecoveryCandidate(
            agent_task_id="task-b", assistant_message_id="assistant-b", narration_lifecycle="retrying",
        ),
    ]
    started: list[str] = []

    class FakeService:
        def __init__(self):
            self._repository = SimpleNamespace(
                list_recoverable_conversation_agent_narrations=AsyncMock(return_value=candidates)
            )

        def start_narration(self, agent_task_id):
            started.append(agent_task_id)

    fake_service = FakeService()
    monkeypatch.setattr(
        narration_module,
        "get_registered_conversation_agent_narration_service",
        lambda: fake_service,
    )

    scheduled_count = await recover_conversation_agent_narrations()

    assert scheduled_count == 2
    assert started == ["task-a", "task-b"]
