import asyncio

import pytest

from api.core.knowledge.sqlite.conversation_repository import (
    ConversationRepository,
    ConversationTurnAdmissionConflict,
)
from api.services.conversation.conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    ConversationTurnLifecycle,
    ConversationTurnNarrationLifecycle,
    ConversationTurnRoute,
    build_conversation_turn_placeholder_metadata,
    parse_conversation_turn_metadata,
)


@pytest.fixture
def repository(tmp_path):
    return ConversationRepository(tmp_path / "conversation-turns.db")


@pytest.mark.asyncio
async def test_placeholder_metadata_has_stable_pending_shape():
    metadata = build_conversation_turn_placeholder_metadata(
        ConversationTurnRoute.AGENT_TASK,
    )

    assert metadata == {
        CONVERSATION_TURN_METADATA_KEY: {
            "route": "agent_task",
            "lifecycle": ConversationTurnLifecycle.PENDING.value,
            "agent_task_id": None,
            "terminal_outcome": None,
            "user_message_id": None,
            "narration": {
                "lifecycle": ConversationTurnNarrationLifecycle.PENDING.value,
                "attempt_count": 0,
            },
        }
    }


@pytest.mark.asyncio
async def test_create_message_pair_persists_both_messages_atomically(repository):
    conversation_id = await repository.create_conversation()
    user_metadata = {
        "surface": "basil_board_chats",
        "request_id": "request-1",
    }
    assistant_metadata = build_conversation_turn_placeholder_metadata(
        ConversationTurnRoute.AGENT_TASK,
    )

    pair = await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Prepare the release checklist",
        user_metadata=user_metadata,
        assistant_metadata=assistant_metadata,
        assistant_model_id="model-1",
    )

    persisted = await repository.get_conversation_with_messages(conversation_id)

    assert pair.conversation_id == conversation_id
    assert [message["id"] for message in persisted["messages"]] == [
        pair.user_message_id,
        pair.assistant_message_id,
    ]
    assert persisted["message_count"] == 2
    assert persisted["messages"][0] == {
        "id": pair.user_message_id,
        "role": "user",
        "content": "Prepare the release checklist",
        "timestamp": persisted["messages"][0]["timestamp"],
        "model_id": None,
        "metadata": user_metadata,
    }
    assert persisted["messages"][1] == {
        "id": pair.assistant_message_id,
        "role": "assistant",
        "content": "",
        "timestamp": persisted["messages"][1]["timestamp"],
        "model_id": "model-1",
        "metadata": {
            CONVERSATION_TURN_METADATA_KEY: {
                **assistant_metadata[CONVERSATION_TURN_METADATA_KEY],
                "user_message_id": pair.user_message_id,
            }
        },
    }
    assert user_metadata == {
        "surface": "basil_board_chats",
        "request_id": "request-1",
    }
    assert assistant_metadata == build_conversation_turn_placeholder_metadata(
        ConversationTurnRoute.AGENT_TASK,
    )


@pytest.mark.asyncio
async def test_create_message_pair_for_missing_conversation_commits_neither_row(repository):
    with pytest.raises(ValueError, match="Conversation missing-conversation not found"):
        await repository.create_message_pair(
            conversation_id="missing-conversation",
            user_content="No durable turn",
            user_metadata=None,
            assistant_metadata=None,
        )

    assert await repository.get_conversation_with_messages("missing-conversation") is None


@pytest.mark.asyncio
async def test_create_message_pair_rolls_back_when_placeholder_serialization_fails(repository):
    conversation_id = await repository.create_conversation()

    with pytest.raises(TypeError):
        await repository.create_message_pair(
            conversation_id=conversation_id,
            user_content="The user row must not persist alone",
            user_metadata={"surface": "basil_board_chats"},
            assistant_metadata={"non_serializable": object()},
        )

    persisted = await repository.get_conversation_with_messages(conversation_id)
    assert persisted["message_count"] == 0
    assert persisted["messages"] == []


@pytest.mark.asyncio
async def test_merge_message_metadata_preserves_unrelated_nested_keys(repository):
    conversation_id = await repository.create_conversation()
    pair = await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Use context from earlier",
        user_metadata={"surface": "basil_board_chats"},
        assistant_metadata={
            "conversation_turn": {
                "route": "contextual_agent",
                "lifecycle": "pending",
                "agent_task_id": None,
                "terminal_outcome": None,
            },
            "thinking": "existing reasoning",
        },
    )

    merged = await repository.merge_message_metadata(
        pair.assistant_message_id,
        {
            "conversation_turn": {
                "lifecycle": "completed",
                "terminal_outcome": "answer persisted",
            },
            "result_source": "contextual_agent",
        },
    )

    assert merged == {
        "conversation_turn": {
            "route": "contextual_agent",
            "lifecycle": "completed",
            "agent_task_id": None,
            "terminal_outcome": "answer persisted",
            "user_message_id": pair.user_message_id,
        },
        "thinking": "existing reasoning",
        "result_source": "contextual_agent",
    }
    persisted = await repository.get_conversation_with_messages(conversation_id)
    assert persisted["messages"][1]["metadata"] == merged


@pytest.mark.asyncio
async def test_concurrent_metadata_merges_preserve_both_patches(repository):
    conversation_id = await repository.create_conversation()
    pair = await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Route this turn",
        user_metadata=None,
        assistant_metadata=build_conversation_turn_placeholder_metadata(
            ConversationTurnRoute.AGENT_TASK,
        ),
    )

    await asyncio.gather(
        repository.merge_message_metadata(
            pair.assistant_message_id,
            {"conversation_turn": {"lifecycle": "running"}},
        ),
        repository.merge_message_metadata(
            pair.assistant_message_id,
            {"conversation_turn": {"agent_task_id": "task-1"}},
        ),
    )

    persisted = await repository.get_conversation_with_messages(conversation_id)
    assert persisted["messages"][1]["metadata"] == {
        CONVERSATION_TURN_METADATA_KEY: {
            "route": "agent_task",
            "lifecycle": "running",
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": pair.user_message_id,
            "narration": {
                "lifecycle": ConversationTurnNarrationLifecycle.PENDING.value,
                "attempt_count": 0,
            },
        }
    }


@pytest.mark.asyncio
async def test_merge_message_metadata_rejects_empty_patch_and_unknown_message(repository):
    with pytest.raises(ValueError, match="metadata_patch must not be empty"):
        await repository.merge_message_metadata("missing-message", {})

    with pytest.raises(ValueError, match="Conversation message missing-message not found"):
        await repository.merge_message_metadata("missing-message", {"state": "running"})


@pytest.mark.asyncio
async def test_bounded_recent_messages_excludes_system_and_returns_chronological_tail(repository):
    conversation_id = await repository.create_conversation(system_message="System instruction")
    await repository.add_message(conversation_id, "user", "first")
    await repository.add_message(conversation_id, "assistant", "second")
    await repository.add_message(conversation_id, "user", "third")

    messages = await repository.get_bounded_recent_messages(
        conversation_id=conversation_id,
        message_limit=2,
        character_limit=20,
    )

    assert [message["role"] for message in messages] == ["assistant", "user"]
    assert [message["content"] for message in messages] == ["second", "third"]
    assert all(message["content_truncated"] is False for message in messages)
    assert all(message["role"] != "system" for message in messages)


@pytest.mark.asyncio
async def test_bounded_recent_messages_truncates_newest_message_to_character_budget(repository):
    conversation_id = await repository.create_conversation()
    await repository.add_message(conversation_id, "user", "older")
    await repository.add_message(conversation_id, "assistant", "newest response")

    messages = await repository.get_bounded_recent_messages(
        conversation_id=conversation_id,
        message_limit=2,
        character_limit=6,
    )

    assert messages == [
        {
            "id": messages[0]["id"],
            "role": "assistant",
            "content": "newest",
            "content_truncated": True,
            "timestamp": messages[0]["timestamp"],
            "model_id": None,
            "metadata": {},
        }
    ]


@pytest.mark.asyncio
async def test_bounded_recent_messages_omits_older_message_that_exceeds_remaining_budget(
    repository,
):
    conversation_id = await repository.create_conversation()
    await repository.add_message(conversation_id, "user", "older message is too long")
    await repository.add_message(conversation_id, "assistant", "new")

    messages = await repository.get_bounded_recent_messages(
        conversation_id=conversation_id,
        message_limit=2,
        character_limit=6,
    )

    assert [message["content"] for message in messages] == ["new"]
    assert messages[0]["content_truncated"] is False


@pytest.mark.asyncio
async def test_bounded_recent_messages_retains_long_user_message_after_empty_assistant_placeholder(
    repository,
):
    conversation_id = await repository.create_conversation()
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="very long user message",
        user_metadata=None,
        assistant_metadata={},
    )

    messages = await repository.get_bounded_recent_messages(
        conversation_id=conversation_id,
        message_limit=2,
        character_limit=6,
    )

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert [message["content"] for message in messages] == ["very l", ""]
    assert messages[0]["content_truncated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message_limit", "character_limit", "error_message"),
    [
        (0, 10, "message_limit must be at least 1"),
        (1, 0, "character_limit must be at least 1"),
    ],
)
async def test_bounded_recent_messages_rejects_invalid_bounds(
    repository,
    message_limit,
    character_limit,
    error_message,
):
    conversation_id = await repository.create_conversation()

    with pytest.raises(ValueError, match=error_message):
        await repository.get_bounded_recent_messages(
            conversation_id=conversation_id,
            message_limit=message_limit,
            character_limit=character_limit,
        )


@pytest.mark.asyncio
async def test_find_conversation_turn_by_agent_task_id_ignores_malformed_metadata(repository):
    conversation_id = await repository.create_conversation("system")
    await repository.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content="",
        metadata={"conversation_turn": {"route": "invalid"}},
    )
    matched_message_id = await repository.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content="",
        metadata={
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "running",
                "agent_task_id": "task-1",
                "terminal_outcome": None,
            }
        },
    )

    match = await repository.find_conversation_turn_by_agent_task_id("task-1")

    assert match is not None
    assert match["conversation_id"] == conversation_id
    assert match["assistant_message_id"] == matched_message_id


def test_parse_conversation_turn_metadata_rejects_malformed_legacy_values():
    assert parse_conversation_turn_metadata({"conversation_turn": {"route": "direct"}}) is None
    assert parse_conversation_turn_metadata(
        {
            "conversation_turn": {
                "route": "direct",
                "lifecycle": "running",
                "agent_task_id": 1,
                "terminal_outcome": None,
            }
        }
    ) is None
    assert parse_conversation_turn_metadata(
        {
            "conversation_turn": {
                "route": ["agent_task"],
                "lifecycle": "running",
                "agent_task_id": None,
                "terminal_outcome": None,
            }
        }
    ) is None


def test_parse_conversation_turn_metadata_maps_legacy_agent_routes():
    for legacy_route in ("contextual_agent", "delegated_agent"):
        parsed = parse_conversation_turn_metadata(
            {
                "conversation_turn": {
                    "route": legacy_route,
                    "lifecycle": "completed",
                    "agent_task_id": "task-1",
                    "terminal_outcome": "Agent task completed.",
                }
            }
        )

        assert parsed is not None
        assert parsed.route is ConversationTurnRoute.AGENT_TASK


def test_parse_conversation_turn_metadata_defaults_legacy_narration_to_pending():
    parsed = parse_conversation_turn_metadata(
        {
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "completed",
                "agent_task_id": "task-1",
                "terminal_outcome": "Agent task completed.",
            }
        }
    )

    assert parsed is not None
    assert parsed.user_message_id is None
    assert parsed.narration.lifecycle is ConversationTurnNarrationLifecycle.PENDING
    assert parsed.narration.attempt_count == 0


def test_parse_conversation_turn_metadata_rejects_invalid_narration_shape():
    assert parse_conversation_turn_metadata(
        {
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "running",
                "agent_task_id": "task-1",
                "terminal_outcome": None,
                "user_message_id": "user-1",
                "narration": [],
            }
        }
    ) is None


@pytest.mark.asyncio
async def test_get_conversation_agent_narration_context_returns_durable_inputs(repository):
    conversation_id = await repository.create_conversation()
    pair = await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Summarize the completed work.",
        user_metadata={"request_id": "request-1"},
        assistant_metadata=build_conversation_turn_placeholder_metadata(
            ConversationTurnRoute.AGENT_TASK,
        ),
        assistant_model_id="selected-model",
    )
    await repository.merge_message_metadata(
        pair.assistant_message_id,
        {
            "conversation_turn": {
                "agent_task_id": "task-1",
                "user_message_id": pair.user_message_id,
            }
        },
    )

    context = await repository.get_conversation_agent_narration_context("task-1")

    assert context is not None
    assert context.conversation_id == conversation_id
    assert context.user_message_id == pair.user_message_id
    assert context.user_content == "Summarize the completed work."
    assert context.user_metadata == {"request_id": "request-1"}
    assert context.assistant_message_id == pair.assistant_message_id
    assert context.assistant_model_id == "selected-model"
    assert context.assistant_metadata["conversation_turn"]["agent_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_get_conversation_agent_narration_context_rejects_missing_or_mismatched_owner(repository):
    conversation_id = await repository.create_conversation()
    assistant_message_id = await repository.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content="",
        metadata={
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "completed",
                "agent_task_id": "task-1",
                "terminal_outcome": "Agent task completed.",
                "user_message_id": None,
                "narration": {"lifecycle": "ready"},
            }
        },
    )

    assert await repository.get_conversation_agent_narration_context("task-1") is None

    await repository.merge_message_metadata(
        assistant_message_id,
        {"conversation_turn": {"user_message_id": assistant_message_id}},
    )

    assert await repository.get_conversation_agent_narration_context("task-1") is None


@pytest.mark.parametrize(
    ("raw_narration", "expected_lifecycle", "expected_attempt_count"),
    [
        ({"lifecycle": "narrating"}, ConversationTurnNarrationLifecycle.NARRATING, 0),
        ({"lifecycle": "retrying", "attempt_count": 1}, ConversationTurnNarrationLifecycle.RETRYING, 1),
        ({"lifecycle": "completed", "attempt_count": 2}, ConversationTurnNarrationLifecycle.COMPLETED, 2),
        ({"lifecycle": "failed", "attempt_count": 3}, ConversationTurnNarrationLifecycle.FAILED, 3),
    ],
)
def test_parse_conversation_turn_metadata_accepts_new_narration_lifecycles(
    raw_narration, expected_lifecycle, expected_attempt_count
):
    parsed = parse_conversation_turn_metadata(
        {
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "completed",
                "agent_task_id": "task-1",
                "terminal_outcome": "Agent task completed.",
                "user_message_id": "user-1",
                "narration": raw_narration,
            }
        }
    )

    assert parsed is not None
    assert parsed.narration.lifecycle is expected_lifecycle
    assert parsed.narration.attempt_count == expected_attempt_count


@pytest.mark.parametrize(
    "raw_attempt_count",
    [-1, 4, "1", 1.5, True],
)
def test_parse_conversation_turn_metadata_rejects_invalid_attempt_count(raw_attempt_count):
    assert parse_conversation_turn_metadata(
        {
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "completed",
                "agent_task_id": "task-1",
                "terminal_outcome": "Agent task completed.",
                "user_message_id": "user-1",
                "narration": {"lifecycle": "ready", "attempt_count": raw_attempt_count},
            }
        }
    ) is None


@pytest.mark.asyncio
async def test_list_recoverable_conversation_agent_narrations_filters_correctly(repository):
    conversation_id = await repository.create_conversation()

    async def make_turn(*, agent_task_id, lifecycle, narration_lifecycle, route="agent_task"):
        pair = await repository.create_message_pair(
            conversation_id=conversation_id,
            user_content="Request",
            user_metadata=None,
            assistant_metadata=build_conversation_turn_placeholder_metadata(
                ConversationTurnRoute.AGENT_TASK,
            ),
            assistant_model_id=None,
        )
        await repository.merge_message_metadata(
            pair.assistant_message_id,
            {
                "conversation_turn": {
                    "route": route,
                    "lifecycle": lifecycle,
                    "agent_task_id": agent_task_id,
                    "user_message_id": pair.user_message_id,
                    "narration": {"lifecycle": narration_lifecycle},
                }
            },
        )
        return pair.assistant_message_id

    ready_id = await make_turn(agent_task_id="task-ready", lifecycle="completed", narration_lifecycle="ready")
    narrating_id = await make_turn(agent_task_id="task-narrating", lifecycle="failed", narration_lifecycle="narrating")
    retrying_id = await make_turn(agent_task_id="task-retrying", lifecycle="cancelled", narration_lifecycle="retrying")
    await make_turn(agent_task_id="task-pending", lifecycle="running", narration_lifecycle="pending")
    await make_turn(agent_task_id="task-completed", lifecycle="completed", narration_lifecycle="completed")
    await make_turn(agent_task_id="task-failed", lifecycle="completed", narration_lifecycle="failed")
    await make_turn(agent_task_id="task-nonterminal-ready", lifecycle="running", narration_lifecycle="ready")

    candidates = await repository.list_recoverable_conversation_agent_narrations()
    by_task = {candidate.agent_task_id: candidate for candidate in candidates}

    assert set(by_task) == {"task-ready", "task-narrating", "task-retrying"}
    assert by_task["task-ready"].assistant_message_id == ready_id
    assert by_task["task-narrating"].assistant_message_id == narrating_id
    assert by_task["task-retrying"].assistant_message_id == retrying_id


@pytest.mark.asyncio
async def test_get_conversation_summary_returns_metadata_without_messages(repository):
    conversation_id = await repository.create_conversation()
    pair = await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="Hello",
        user_metadata=None,
        assistant_metadata={},
    )
    await repository.merge_message_metadata(pair.user_message_id, {"probe": True})

    summary = await repository.get_conversation_summary(conversation_id)

    assert summary is not None
    assert summary["id"] == conversation_id
    assert summary["message_count"] >= 1
    assert "messages" not in summary
    assert "title" in summary
    assert "is_active" in summary


@pytest.mark.asyncio
async def test_get_conversation_summary_returns_none_for_missing_conversation(repository):
    summary = await repository.get_conversation_summary("conv-does-not-exist")

    assert summary is None


@pytest.mark.asyncio
async def test_admit_and_create_message_pair_rejects_active_turn(repository):
    conversation_id = await repository.create_conversation()
    active_metadata = build_conversation_turn_placeholder_metadata(ConversationTurnRoute.AGENT_TASK)
    await repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="first",
        user_metadata=None,
        assistant_metadata=active_metadata,
    )

    with pytest.raises(ConversationTurnAdmissionConflict):
        await repository.admit_and_create_message_pair(
            conversation_id=conversation_id,
            user_content="second",
            user_metadata=None,
            assistant_metadata=active_metadata,
        )

    persisted = await repository.get_conversation_with_messages(conversation_id)
    assert persisted["message_count"] == 2


@pytest.mark.asyncio
async def test_concurrent_admission_allows_only_one_pair(repository):
    conversation_id = await repository.create_conversation()
    metadata = build_conversation_turn_placeholder_metadata(ConversationTurnRoute.DIRECT)

    async def _attempt(label: str):
        return await repository.admit_and_create_message_pair(
            conversation_id=conversation_id,
            user_content=label,
            user_metadata=None,
            assistant_metadata=metadata,
        )

    results = await asyncio.gather(
        _attempt("alpha"),
        _attempt("beta"),
        return_exceptions=True,
    )
    successes = [result for result in results if not isinstance(result, Exception)]
    conflicts = [result for result in results if isinstance(result, ConversationTurnAdmissionConflict)]

    assert len(successes) == 1
    assert len(conflicts) == 1
    persisted = await repository.get_conversation_with_messages(conversation_id)
    assert persisted["message_count"] == 2
