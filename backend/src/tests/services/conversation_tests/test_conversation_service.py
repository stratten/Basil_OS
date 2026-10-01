import asyncio
import pytest
import pytest_asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch
from datetime import datetime

from api.services.conversation.conversation_service import ConversationService
from api.services.conversation.conversation_models import (
    Message,
    MessageRole,
    Conversation,
    ConversationError,
    ModelNotAvailableError,
    ConversationResponse
)
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.models.base_model import BaseAIModel
from api.core.models.model_types import ModelCapability
from api.core.knowledge.sqlite.conversation_repository import ConversationMessagePair
from api.services.conversation.conversation_summary_contract import TURN_SUMMARY_METADATA_KEY, exchange_fingerprint
from api.services.conversation.conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    ConversationTurnLifecycle,
    ConversationTurnRoute,
)


@pytest.fixture
def mock_model_service():
    """Create a mock model service for testing."""
    mock_service = MagicMock()
    mock_model = AsyncMock()
    
    # Configure the mock model to return a valid response
    mock_model.chat_completion.return_value = {
        "content": "This is a test response",
        "metadata": {"model": "test-model"}
    }
    
    # Configure the model service to return the mock model
    mock_service.load_model = AsyncMock(return_value=mock_model)
    mock_service.get_installed_models.return_value = {
        "test-model": {
            "variants": {
                "default": {
                    "name": "Test Model",
                    "capabilities": ["reasoning"],
                    "path": "/path/to/model"
                }
            }
        }
    }
    
    return mock_service


@pytest_asyncio.fixture
async def conversation_service(mock_model_service, tmp_path):
    """Create a Conversation service and drain its owned background tasks."""
    sqlite_service = SQLiteKnowledgeService(tmp_path / "conversation-tests.db")
    service = ConversationService(
        model_service=mock_model_service,
        development_mode=True,
        sqlite_knowledge_service=sqlite_service,
    )
    try:
        yield service
    finally:
        await service.shutdown_background_tasks()


@pytest.mark.asyncio
async def test_create_conversation(conversation_service):
    """Test creating a new conversation."""
    # Create a conversation without a system message
    conversation = await conversation_service.create_conversation()
    
    # Verify the conversation was created correctly
    assert conversation.id is not None
    assert len(conversation.messages) == 0
    assert await conversation_service.get_conversation(conversation.id) is not None
    
    # Create a conversation with a system message
    system_message = "This is a system message"
    conversation = await conversation_service.create_conversation(system_message)
    
    # Verify the conversation was created correctly
    assert conversation.id is not None
    assert len(conversation.messages) == 1
    assert conversation.messages[0].role == MessageRole.SYSTEM
    assert conversation.messages[0].content == system_message
    assert await conversation_service.get_conversation(conversation.id) is not None


@pytest.mark.asyncio
async def test_get_conversation(conversation_service):
    """Test retrieving a conversation."""
    # Create a conversation
    conversation = await conversation_service.create_conversation()
    
    # Retrieve the conversation
    retrieved = await conversation_service.get_conversation(conversation.id)
    
    # Verify the conversation was retrieved correctly
    assert retrieved is not None
    assert retrieved.id == conversation.id
    
    # Try to retrieve a non-existent conversation
    non_existent = await conversation_service.get_conversation(str(uuid.uuid4()))
    assert non_existent is None


@pytest.mark.asyncio
async def test_add_message(conversation_service):
    """Test adding a message to a conversation."""
    # Create a conversation
    conversation = await conversation_service.create_conversation()
    
    # Add a user message
    message_content = "This is a user message"
    message = await conversation_service.add_message(
        conversation.id,
        "user",
        message_content
    )
    
    # Verify the message was added correctly
    assert message.id is not None
    assert message.content == message_content
    assert message.role == MessageRole.USER
    
    # Verify the message was added to the conversation
    conversation = await conversation_service.get_conversation(conversation.id)
    assert len(conversation.messages) == 1
    assert conversation.messages[0].id == message.id
    
    # Try to add a message to a non-existent conversation
    with pytest.raises(ConversationError):
        await conversation_service.add_message(
            "non-existent-id",
            "user",
            "This message should fail"
        )


@pytest.mark.asyncio
async def test_send_message(conversation_service):
    """Test sending a message and getting a response."""
    # Create a conversation
    conversation = await conversation_service.create_conversation()
    
    # Send a message
    message_content = "This is a test message"
    response = await conversation_service.send_message(conversation.id, message_content)
    
    # Verify the response
    assert response.conversation_id == conversation.id
    assert response.message.role == MessageRole.ASSISTANT
    assert response.message.content == "This is a test response"
    assert "model" in response.metadata
    
    # Verify the conversation state
    conversation = await conversation_service.get_conversation(conversation.id)
    assert len(conversation.messages) == 2
    assert conversation.messages[0].role == MessageRole.USER
    assert conversation.messages[0].content == message_content
    assert conversation.messages[1].role == MessageRole.ASSISTANT
    assert conversation.messages[1].content == "This is a test response"
    
    # Try to send a message to a non-existent conversation
    with pytest.raises(ConversationError):
        await conversation_service.send_message(str(uuid.uuid4()), "This message should fail")


@pytest.mark.asyncio
async def test_send_message_model_not_available(conversation_service, mock_model_service):
    """Test sending a message when no model is available."""
    # Configure the model service to return None
    mock_model_service.load_model.return_value = None
    
    # Create a conversation
    conversation = await conversation_service.create_conversation()
    
    # Try to send a message
    with pytest.raises(ModelNotAvailableError):
        await conversation_service.send_message(conversation.id, "This message should fail")
    
    # Verify the conversation state (should have the user message but no assistant message)
    conversation = await conversation_service.get_conversation(conversation.id)
    assert len(conversation.messages) == 2  # User message + error message
    assert conversation.messages[0].role == MessageRole.USER
    assert conversation.messages[1].role == MessageRole.ERROR


@pytest.mark.asyncio
async def test_send_message_model_error(conversation_service, mock_model_service):
    """Test sending a message when the model raises an error."""
    # Get the mock model
    mock_model = await mock_model_service.load_model()
    
    # Configure the mock model to raise an exception
    mock_model.chat_completion.side_effect = Exception("Model error")
    
    # Create a conversation
    conversation = await conversation_service.create_conversation()
    
    # Send a message (should not raise an exception but return an error message)
    response = await conversation_service.send_message(conversation.id, "This message should cause an error")
    
    # Verify the response
    assert response.conversation_id == conversation.id
    assert response.message.role == MessageRole.ERROR
    assert "Error:" in response.message.content
    
    # Verify the conversation state
    conversation = await conversation_service.get_conversation(conversation.id)
    assert len(conversation.messages) == 2
    assert conversation.messages[0].role == MessageRole.USER
    assert conversation.messages[1].role == MessageRole.ERROR


@pytest.mark.asyncio
async def test_clear_conversation(conversation_service):
    """Test clearing a conversation."""
    # Create a conversation with a system message
    system_message = "This is a system message"
    conversation = await conversation_service.create_conversation(system_message)
    
    # Add a user message
    await conversation_service.add_message(
        conversation.id,
        "user",
        "This is a user message"
    )
    
    # Add an assistant message
    await conversation_service.add_message(
        conversation.id,
        "assistant",
        "This is an assistant message"
    )
    
    # Verify the conversation has 3 messages
    conversation = await conversation_service.get_conversation(conversation.id)
    assert len(conversation.messages) == 3
    
    # Clear the conversation
    success = await conversation_service.clear_conversation(conversation.id)
    assert success
    
    # Verify the conversation now only has the system message
    conversation = await conversation_service.get_conversation(conversation.id)
    assert len(conversation.messages) == 1
    assert conversation.messages[0].role == MessageRole.SYSTEM
    
    # Try to clear a non-existent conversation
    success = await conversation_service.clear_conversation(str(uuid.uuid4()))
    assert not success


@pytest.mark.asyncio
async def test_delete_conversation(conversation_service):
    """Test deleting a conversation."""
    # Create a conversation
    conversation = await conversation_service.create_conversation()
    
    # Verify the conversation exists
    assert await conversation_service.get_conversation(conversation.id) is not None
    
    # Delete the conversation
    success = await conversation_service.delete_conversation(conversation.id)
    assert success
    
    # Verify the conversation no longer exists
    assert await conversation_service.get_conversation(conversation.id) is None
    
    # Try to delete a non-existent conversation
    success = await conversation_service.delete_conversation(str(uuid.uuid4()))
    assert not success


@pytest.mark.asyncio
async def test_send_message_with_api_models(conversation_service, mock_model_service):
    """Test sending a message with an API reasoning model."""
    conversation = await conversation_service.create_conversation("You are a helpful assistant.")
    conversation_id = conversation.id

    api_model = AsyncMock()
    api_model.chat_completion.return_value = {
        "content": "This is a response from Claude API",
        "metadata": {"model": "claude-3-5-sonnet-20240620"},
    }
    conversation_service._get_model_for_task = AsyncMock(return_value=api_model)

    response = await conversation_service.send_message(conversation_id, "Hello, API model!")

    conversation_service._get_model_for_task.assert_awaited_once_with(
        [ModelCapability.REASONING],
        None,
    )
    assert response.message.content == "This is a response from Claude API"
    assert response.metadata["model"] == "claude-3-5-sonnet-20240620"

    persisted = await conversation_service.get_conversation(conversation_id)
    assert persisted is not None
    assert [message.role for message in persisted.messages] == [
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert persisted.messages[1].content == "Hello, API model!"
    assert persisted.messages[2].content == "This is a response from Claude API"


@pytest.mark.asyncio
async def test_send_message_with_openai_api_models(conversation_service, mock_model_service):
    """Test sending a message with an OpenAI reasoning model."""
    conversation = await conversation_service.create_conversation("You are a helpful assistant.")
    conversation_id = conversation.id

    api_model = AsyncMock()
    api_model.chat_completion.return_value = {
        "content": "This is a response from OpenAI API",
        "metadata": {"model": "gpt-4o-2024-05-13"},
    }
    conversation_service._get_model_for_task = AsyncMock(return_value=api_model)

    response = await conversation_service.send_message(
        conversation_id,
        "Hello, OpenAI API model!",
    )

    assert response.message.content == "This is a response from OpenAI API"
    assert response.metadata["model"] == "gpt-4o-2024-05-13"

    persisted = await conversation_service.get_conversation(conversation_id)
    assert persisted is not None
    assert persisted.messages[1].content == "Hello, OpenAI API model!"
    assert persisted.messages[2].content == "This is a response from OpenAI API"


@pytest.mark.asyncio
async def test_send_message_api_fallback_to_local(conversation_service, mock_model_service):
    """Test sending a message after the caller selects a fallback model."""
    conversation = await conversation_service.create_conversation("You are a helpful assistant.")
    conversation_id = conversation.id

    local_model = AsyncMock()
    local_model.chat_completion.return_value = {
        "content": "This is a response from local model",
        "metadata": {"model": "test-model"},
    }
    conversation_service._get_model_for_task = AsyncMock(return_value=local_model)

    response = await conversation_service.send_message(
        conversation_id,
        "Hello, with fallback!",
    )

    assert response.message.content == "This is a response from local model"
    persisted = await conversation_service.get_conversation(conversation_id)
    assert persisted is not None
    assert persisted.messages[2].content == "This is a response from local model"


@pytest.mark.asyncio
async def test_send_message_retries_local_fallback_on_unreachable_model(conversation_service, mock_model_service):
    """When the preferred model is completely unreachable on the first attempt,
    send_message retries once with the designated local fallback model and tags
    the response metadata with which model actually answered."""
    conversation = await conversation_service.create_conversation("You are a helpful assistant.")
    conversation_id = conversation.id

    primary_model = AsyncMock()
    primary_model.chat_completion.side_effect = ConnectionError(
        "nodename nor servname provided, or not known"
    )
    conversation_service._get_model_for_task = AsyncMock(return_value=primary_model)

    fallback_model = AsyncMock()
    fallback_model.model_name = "local-fallback-model"
    fallback_model.chat_completion.return_value = {
        "content": "This is a response from the local fallback model",
        "metadata": {"model": "local-fallback-model"},
    }
    conversation_service.model_usage_service.get_designated_local_fallback_model = AsyncMock(
        return_value=fallback_model
    )

    response = await conversation_service.send_message(
        conversation_id,
        "Hello, preferred model is unreachable!",
    )

    assert response.message.content == "This is a response from the local fallback model"
    assert response.metadata["answered_by_fallback_model"] == "local-fallback-model"
    fallback_model.chat_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_merges_message_metadata_and_file_paths(conversation_service):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.add_message = AsyncMock(return_value="user-1")

    with patch("api.services.conversation.conversation_service.DocumentProcessingService.build_file_metadata") as build_meta:
        build_meta.return_value = [{"path": "/tmp/a.txt"}]
        await conversation_service.send_message(
            conversation.id,
            "Hello",
            file_paths=["/tmp/a.txt"],
            message_metadata={
                "surface": "basil_board_home",
                "display_prompt_markdown": "**hello**",
            },
        )

    user_call = next(
        call for call in conversation_service.conversation_repository.add_message.await_args_list
        if call.kwargs.get("role") == "user"
    )
    metadata = user_call.kwargs["metadata"]
    assert metadata["surface"] == "basil_board_home"
    assert metadata["display_prompt_markdown"] == "**hello**"
    assert metadata["attached_files"] == [{"path": "/tmp/a.txt"}]


@pytest.mark.asyncio
async def test_send_message_streaming_creates_direct_pair_and_preserves_caller_metadata(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.admit_and_create_message_pair = AsyncMock(
        return_value=ConversationMessagePair(
            conversation_id=conversation.id,
            user_message_id="user-1",
            assistant_message_id="assistant-1",
        )
    )
    conversation_service.conversation_repository.merge_message_metadata = AsyncMock()
    conversation_service.conversation_repository.update_message = AsyncMock()
    model = AsyncMock()

    async def stream(_messages):
        yield "Hello"

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()
    caller_metadata = {
        "surface": "basil_board_chats",
        "request_id": "request-1",
        "display_markdown": "**Hello**",
    }

    with patch(
        "api.services.conversation.conversation_service."
        "DocumentProcessingService.build_file_metadata"
    ) as build_metadata:
        build_metadata.return_value = [{"path": "/tmp/a.txt"}]
        chunks = [
            chunk
            async for chunk in conversation_service.send_message_streaming(
                conversation.id,
                "Hello",
                model_id="model-1",
                file_paths=["/tmp/a.txt"],
                message_metadata=caller_metadata,
            )
        ]

    conversation_service.conversation_repository.admit_and_create_message_pair.assert_awaited_once_with(
        conversation_id=conversation.id,
        user_content="Hello",
        user_metadata={
            "surface": "basil_board_chats",
            "request_id": "request-1",
            "display_markdown": "**Hello**",
            "attached_files": [{"path": "/tmp/a.txt"}],
        },
        assistant_metadata={
            CONVERSATION_TURN_METADATA_KEY: {
                "route": ConversationTurnRoute.DIRECT.value,
                "lifecycle": ConversationTurnLifecycle.PENDING.value,
                "agent_task_id": None,
                "terminal_outcome": None,
                "user_message_id": None,
                "narration": {"lifecycle": "pending", "attempt_count": 0},
            }
        },
        assistant_model_id="model-1",
    )
    assert caller_metadata == {
        "surface": "basil_board_chats",
        "request_id": "request-1",
        "display_markdown": "**Hello**",
    }
    assert conversation_service.conversation_repository.merge_message_metadata.await_args_list == [
        call(
            "assistant-1",
            {CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "running"}},
        ),
        call(
            "assistant-1",
            {CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "completed"}},
        ),
    ]
    conversation_service.conversation_repository.update_message.assert_awaited_once_with(
        message_id="assistant-1",
        content="Hello",
        model_id=None,
    )
    assert chunks[-1]["is_final"] is True


@pytest.mark.asyncio
async def test_send_message_streaming_persists_terminal_error_on_direct_placeholder(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.admit_and_create_message_pair = AsyncMock(
        return_value=ConversationMessagePair(
            conversation_id=conversation.id,
            user_message_id="user-1",
            assistant_message_id="assistant-1",
        )
    )
    conversation_service.conversation_repository.merge_message_metadata = AsyncMock()
    conversation_service.conversation_repository.update_message = AsyncMock()
    conversation_service._auto_title_conversation = AsyncMock()
    model = AsyncMock()

    async def failing_stream(_messages):
        raise RuntimeError("model failed")
        yield

    model.chat_completion_streaming = failing_stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)

    chunks = [
        chunk
        async for chunk in conversation_service.send_message_streaming(
            conversation.id,
            "Hello",
        )
    ]

    conversation_service.conversation_repository.update_message.assert_awaited_once_with(
        message_id="assistant-1",
        content="Error: model failed",
    )
    assert conversation_service.conversation_repository.merge_message_metadata.await_args_list == [
        call(
            "assistant-1",
            {CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "running"}},
        ),
        call(
            "assistant-1",
            {
                CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "failed"},
                "error": True,
            },
        ),
    ]
    assert chunks == [{
        "token": "Error: model failed",
        "message_id": "assistant-1",
        "conversation_id": conversation.id,
        "error": True,
        "is_final": True,
    }]


@pytest.mark.asyncio
async def test_send_message_without_metadata_or_files_persists_none_metadata(conversation_service):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.add_message = AsyncMock(return_value="user-1")

    await conversation_service.send_message(conversation.id, "Hello")

    user_call = next(
        call for call in conversation_service.conversation_repository.add_message.await_args_list
        if call.kwargs.get("role") == "user"
    )
    metadata = user_call.kwargs["metadata"]
    assert metadata is None


@pytest.mark.asyncio
async def test_send_message_streaming_persistence_callback_follows_running_direct_pair(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.admit_and_create_message_pair = AsyncMock(
        return_value=ConversationMessagePair(
            conversation_id=conversation.id,
            user_message_id="user-1",
            assistant_message_id="assistant-1",
        )
    )
    conversation_service.conversation_repository.merge_message_metadata = AsyncMock()
    conversation_service.conversation_repository.update_message = AsyncMock()
    conversation_service._auto_title_conversation = AsyncMock()
    model = AsyncMock()

    async def stream(_messages):
        yield "Hello"

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    callback_calls = []

    def persistence_ready(user_message_id, assistant_message_id):
        callback_calls.append((user_message_id, assistant_message_id))
        assert conversation_service.conversation_repository.merge_message_metadata.await_args_list == [
            call(
                "assistant-1",
                {CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "running"}},
            )
        ]
        conversation_service._get_model_for_task.assert_not_awaited()

    async for _chunk in conversation_service.send_message_streaming(
        conversation.id,
        "Hello",
        on_persistence_ready=persistence_ready,
    ):
        pass

    assert callback_calls == [("user-1", "assistant-1")]
    assert conversation_service._get_model_for_task.await_count == 1


@pytest.mark.asyncio
async def test_send_message_streaming_cancellation_after_tokens_persists_partial_direct_turn(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.admit_and_create_message_pair = AsyncMock(
        return_value=ConversationMessagePair(
            conversation_id=conversation.id,
            user_message_id="user-1",
            assistant_message_id="assistant-1",
        )
    )
    conversation_service.conversation_repository.merge_message_metadata = AsyncMock()
    conversation_service.conversation_repository.update_message = AsyncMock()
    conversation_service._auto_title_conversation = AsyncMock()
    model = AsyncMock()

    async def stream(_messages):
        yield "Partial "
        yield "<think>secret</think>"
        raise asyncio.CancelledError()

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)

    with pytest.raises(asyncio.CancelledError):
        async for _chunk in conversation_service.send_message_streaming(conversation.id, "Hello"):
            pass

    conversation_service.conversation_repository.update_message.assert_awaited_once_with(
        message_id="assistant-1",
        content="Partial",
    )
    assert conversation_service.conversation_repository.merge_message_metadata.await_args_list[-1] == call(
        "assistant-1",
        {
            CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "canceled"},
            "canceled": True,
            "thinking": "secret",
        },
    )


@pytest.mark.asyncio
async def test_send_message_streaming_cancellation_before_first_token_persists_empty_direct_turn(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service.conversation_repository.admit_and_create_message_pair = AsyncMock(
        return_value=ConversationMessagePair(
            conversation_id=conversation.id,
            user_message_id="user-1",
            assistant_message_id="assistant-1",
        )
    )
    conversation_service.conversation_repository.merge_message_metadata = AsyncMock()
    conversation_service.conversation_repository.update_message = AsyncMock()
    conversation_service._auto_title_conversation = AsyncMock()
    model = AsyncMock()

    async def stream(_messages):
        raise asyncio.CancelledError()
        yield

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)

    with pytest.raises(asyncio.CancelledError):
        async for _chunk in conversation_service.send_message_streaming(conversation.id, "Hello"):
            pass

    conversation_service.conversation_repository.update_message.assert_awaited_once_with(
        message_id="assistant-1",
        content="",
    )
    assert conversation_service.conversation_repository.merge_message_metadata.await_args_list[-1] == call(
        "assistant-1",
        {
            CONVERSATION_TURN_METADATA_KEY: {"lifecycle": "canceled"},
            "canceled": True,
        },
    )


@pytest.mark.asyncio
async def test_send_message_streaming_callback_cancellation_persists_direct_placeholder(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service._auto_title_conversation = AsyncMock()
    model = AsyncMock()

    async def get_model(*_args, **_kwargs):
        await asyncio.sleep(0)
        return model

    conversation_service._get_model_for_task = get_model

    def persistence_ready(_user_message_id, _assistant_message_id):
        current_task = asyncio.current_task()
        assert current_task is not None
        current_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        async for _chunk in conversation_service.send_message_streaming(
            conversation.id,
            "Hello",
            on_persistence_ready=persistence_ready,
        ):
            pass

    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(
        conversation.id,
    )
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert persisted["messages"][1]["content"] == ""
    assert persisted["messages"][1]["metadata"][CONVERSATION_TURN_METADATA_KEY] == {
        "route": "direct",
        "lifecycle": "canceled",
        "agent_task_id": None,
        "terminal_outcome": None,
        "user_message_id": persisted["messages"][0]["id"],
        "narration": {"lifecycle": "pending", "attempt_count": 0},
    }
    assert persisted["messages"][1]["metadata"]["canceled"] is True
    model.chat_completion_streaming.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_streaming_cancellation_during_pair_persistence_marks_placeholder_canceled(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    conversation_service._auto_title_conversation = AsyncMock()
    pair_persisted = asyncio.Event()
    release_pair = asyncio.Event()
    original_admit_pair = conversation_service.conversation_repository.admit_and_create_message_pair

    async def admit_pair_then_wait(*args, **kwargs):
        pair = await original_admit_pair(*args, **kwargs)
        pair_persisted.set()
        await release_pair.wait()
        return pair

    conversation_service.conversation_repository.admit_and_create_message_pair = admit_pair_then_wait

    async def consume_stream():
        async for _chunk in conversation_service.send_message_streaming(conversation.id, "Hello"):
            pass

    streaming_task = asyncio.create_task(consume_stream())
    await asyncio.wait_for(pair_persisted.wait(), timeout=1)
    streaming_task.cancel()
    release_pair.set()

    with pytest.raises(asyncio.CancelledError):
        await streaming_task

    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(
        conversation.id,
    )
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert persisted["messages"][1]["content"] == ""
    assert persisted["messages"][1]["metadata"][CONVERSATION_TURN_METADATA_KEY]["lifecycle"] == (
        ConversationTurnLifecycle.CANCELED.value
    )
    assert persisted["messages"][1]["metadata"]["canceled"] is True


@pytest.mark.asyncio
async def test_direct_streaming_creates_one_durable_pair_without_duplicate_assistant_messages(
    conversation_service,
):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()

    async def stream(_messages):
        yield "Direct response"

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()

    chunks = [
        chunk
        async for chunk in conversation_service.send_message_streaming(
            conversation.id,
            "Direct request",
            model_id="model-1",
        )
    ]

    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(
        conversation.id,
    )
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert persisted["messages"][0]["content"] == "Direct request"
    assert persisted["messages"][1]["content"] == "Direct response"
    assert persisted["messages"][1]["model_id"] == "model-1"
    assert persisted["messages"][1]["metadata"][CONVERSATION_TURN_METADATA_KEY] == {
        "route": "direct",
        "lifecycle": "completed",
        "agent_task_id": None,
        "terminal_outcome": None,
        "user_message_id": persisted["messages"][0]["id"],
        "narration": {"lifecycle": "pending", "attempt_count": 0},
    }
    assert chunks[-1]["message_id"] == persisted["messages"][1]["id"]


@pytest.mark.asyncio
async def test_direct_streaming_records_local_fallback_as_answering_model(conversation_service):
    conversation = await conversation_service.create_conversation()
    primary_model = AsyncMock()

    async def unreachable_stream(_messages):
        raise ConnectionError("nodename nor servname provided, or not known")
        yield ""

    primary_model.chat_completion_streaming = unreachable_stream
    conversation_service._get_model_for_task = AsyncMock(return_value=primary_model)
    conversation_service._auto_title_conversation = AsyncMock()

    fallback_model = AsyncMock()
    fallback_model.model_name = "local-fallback-model"

    async def fallback_stream(_messages):
        yield "Fallback response"

    fallback_model.chat_completion_streaming = fallback_stream
    conversation_service.model_usage_service.get_designated_local_fallback_model = AsyncMock(
        return_value=fallback_model
    )

    chunks = [
        chunk
        async for chunk in conversation_service.send_message_streaming(
            conversation.id,
            "Direct request",
            model_id="cloud-model",
        )
    ]

    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(
        conversation.id,
    )
    assistant = persisted["messages"][1]
    assert assistant["content"] == "Fallback response"
    assert assistant["model_id"] == "local-fallback-model"
    assert assistant["metadata"]["answered_by_fallback_model"] == "local-fallback-model"
    assert chunks[-1]["metadata"]["answered_by_fallback_model"] == "local-fallback-model"


@pytest.mark.asyncio
async def test_direct_streaming_completion_requests_turn_summaries(conversation_service):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()

    async def stream(_messages):
        yield "Direct response"

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()
    conversation_service.turn_summarizer = MagicMock()

    chunks = [
        chunk
        async for chunk in conversation_service.send_message_streaming(
            conversation.id,
            "Direct request",
            model_id="model-1",
        )
    ]

    conversation_service.turn_summarizer.request_pass.assert_called_once_with(conversation.id)
    assert chunks[-1]["is_final"] is True


@pytest.mark.asyncio
async def test_failed_streaming_turn_does_not_request_turn_summaries(conversation_service):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()

    async def failing_stream(_messages):
        raise RuntimeError("model failed")
        yield

    model.chat_completion_streaming = failing_stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()
    conversation_service.turn_summarizer = MagicMock()

    chunks = [
        chunk
        async for chunk in conversation_service.send_message_streaming(conversation.id, "Hello")
    ]

    conversation_service.turn_summarizer.request_pass.assert_not_called()
    assert chunks[-1]["error"] is True


@pytest.mark.asyncio
async def test_send_message_requests_turn_summaries_only_after_a_reply(conversation_service):
    conversation = await conversation_service.create_conversation()
    conversation_service.turn_summarizer = MagicMock()

    await conversation_service.send_message(conversation.id, "Hello")
    conversation_service.turn_summarizer.request_pass.assert_called_once_with(conversation.id)

    failing_model = AsyncMock()
    failing_model.chat_completion.side_effect = RuntimeError("model failed")
    conversation_service._get_model_for_task = AsyncMock(return_value=failing_model)
    conversation_service.turn_summarizer.request_pass.reset_mock()

    await conversation_service.send_message(conversation.id, "Again")
    conversation_service.turn_summarizer.request_pass.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_fits_context_with_conversation_metadata_and_file_content(conversation_service):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()

    async def stream(_messages):
        yield "Done"

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()
    conversation_service.turn_summarizer = MagicMock()
    conversation_service.document_processor.detect_provider = MagicMock(return_value="local")
    conversation_service.document_processor.process_files_for_model = AsyncMock(
        return_value={"method": "text_prepend", "content": "File text\n\nHello"}
    )
    fitted = [{"role": "system", "content": "s"}, {"role": "user", "content": "File text\n\nHello"}]

    with patch(
        "api.services.conversation.conversation_service.build_fitted_conversation_messages",
        return_value=fitted,
    ) as build_fitted, patch(
        "api.services.conversation.conversation_service.DocumentProcessingService.build_file_metadata",
        return_value=[{"path": "/tmp/a.txt"}],
    ):
        _ = [
            chunk
            async for chunk in conversation_service.send_message_streaming(
                conversation.id,
                "Hello",
                model_id="model-1",
                file_paths=["/tmp/a.txt"],
            )
        ]

    kwargs = build_fitted.call_args.kwargs
    assert kwargs["llm_model"] is model
    assert kwargs["requested_model_id"] == "model-1"
    assert kwargs["conversation_metadata"] == {}
    assert kwargs["newest_content_override"] == "File text\n\nHello"
    assert build_fitted.call_args.args[0][-1].content == "Hello"


@pytest.mark.asyncio
async def test_active_summary_model_accepts_only_loaded_model_instances(conversation_service, mock_model_service):
    mock_model_service.get_ready_model_if_active.return_value = MagicMock()
    assert conversation_service._get_active_summary_model("model-1") is None

    ready_model = MagicMock(spec=BaseAIModel)
    mock_model_service.get_ready_model_if_active.return_value = ready_model
    assert conversation_service._get_active_summary_model("model-1") is ready_model


@pytest.mark.asyncio
async def test_streaming_withholds_inline_note_and_stores_it_as_turn_summary(conversation_service):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()

    async def stream(_messages):
        for token in ["Hello there.", "\n<basil", "_note>Greeting exchange.</basil", "_note>"]:
            yield token

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()
    conversation_service.turn_summarizer = MagicMock()

    chunks = [
        chunk
        async for chunk in conversation_service.send_message_streaming(conversation.id, "Direct request", model_id="model-1")
    ]

    streamed = "".join(chunk["token"] for chunk in chunks if not chunk.get("is_final"))
    assert streamed == "Hello there.\n"
    assert all("basil" not in chunk["token"] for chunk in chunks)
    assert TURN_SUMMARY_METADATA_KEY not in chunks[-1]["metadata"]
    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(conversation.id)
    assistant = persisted["messages"][1]
    assert assistant["content"] == "Hello there."
    summary = assistant["metadata"][TURN_SUMMARY_METADATA_KEY]
    assert summary["status"] == "completed"
    assert summary["text"] == "Greeting exchange."
    assert summary["model_id"] == "model-1"
    assert summary["source_fingerprint"] == exchange_fingerprint("Direct request", "Hello there.")
    assert assistant["metadata"][CONVERSATION_TURN_METADATA_KEY]["lifecycle"] == "completed"


@pytest.mark.asyncio
async def test_streaming_with_unclosed_note_stores_reply_without_summary(conversation_service):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()

    async def stream(_messages):
        yield "Answer"
        yield "<basil_note>cut off"

    model.chat_completion_streaming = stream
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service._auto_title_conversation = AsyncMock()
    conversation_service.turn_summarizer = MagicMock()

    _ = [chunk async for chunk in conversation_service.send_message_streaming(conversation.id, "Q", model_id="model-1")]

    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(conversation.id)
    assistant = persisted["messages"][1]
    assert assistant["content"] == "Answer"
    assert TURN_SUMMARY_METADATA_KEY not in assistant["metadata"]
    conversation_service.turn_summarizer.request_pass.assert_called_once_with(conversation.id)


@pytest.mark.asyncio
async def test_send_message_strips_inline_note_and_stores_it_as_turn_summary(conversation_service):
    conversation = await conversation_service.create_conversation()
    model = AsyncMock()
    model.chat_completion.return_value = {"content": "Reply.\n<basil_note>Note.</basil_note>", "metadata": {}}
    conversation_service._get_model_for_task = AsyncMock(return_value=model)
    conversation_service.turn_summarizer = MagicMock()

    response = await conversation_service.send_message(conversation.id, "Hello", model_id="model-1")

    assert response.message.content == "Reply."
    persisted = await conversation_service.conversation_repository.get_conversation_with_messages(conversation.id)
    assistant = persisted["messages"][-1]
    assert assistant["content"] == "Reply."
    summary = assistant["metadata"][TURN_SUMMARY_METADATA_KEY]
    assert summary["text"] == "Note."
    assert summary["source_fingerprint"] == exchange_fingerprint("Hello", "Reply.")