import pytest
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

from api.services.conversation.conversation_routes import (
    router,
    get_conversation_service,
    _get_sqlite_knowledge_service,
    CreateConversationRequest,
    SendMessageRequest
)
from api.services.conversation.conversation_models import (
    Message,
    MessageRole,
    Conversation,
    ConversationError,
    ModelNotAvailableError,
    ConversationResponse
)


@pytest.fixture
def mock_conversation_service():
    """Create a mock conversation service for testing."""
    mock_service = MagicMock()
    
    # Mock create_conversation
    async def create_conversation_side_effect(system_message=None):
        conversation = Conversation(id="test-conversation-id")
        if system_message:
            conversation.messages.append(
                Message(
                    id="test-system-message-id",
                    content=system_message,
                    role=MessageRole.SYSTEM
                )
            )
        return conversation
    
    mock_service.create_conversation = AsyncMock(side_effect=create_conversation_side_effect)
    
    # Mock get_conversation
    async def get_conversation_side_effect(conversation_id):
        if conversation_id == "test-conversation-id":
            conversation = Conversation(id=conversation_id)
            conversation.messages = [
                Message(
                    id="test-user-message-id",
                    content="Test user message",
                    role=MessageRole.USER
                ),
                Message(
                    id="test-assistant-message-id",
                    content="Test assistant response",
                    role=MessageRole.ASSISTANT
                )
            ]
            return conversation
        return None
    
    mock_service.get_conversation = AsyncMock(side_effect=get_conversation_side_effect)
    
    # Mock send_message
    async def send_message_side_effect(conversation_id, content):
        if conversation_id != "test-conversation-id":
            raise ConversationError(f"Conversation {conversation_id} not found")
        
        message = Message(
            id="test-response-id",
            content="Test response",
            role=MessageRole.ASSISTANT
        )
        
        return ConversationResponse(
            message=message,
            conversation_id=conversation_id,
            metadata={"model": "test-model"}
        )
    
    mock_service.send_message = AsyncMock(side_effect=send_message_side_effect)
    
    # Mock clear_conversation
    async def clear_conversation_side_effect(conversation_id):
        return conversation_id == "test-conversation-id"
    
    mock_service.clear_conversation = AsyncMock(side_effect=clear_conversation_side_effect)
    
    # Mock delete_conversation
    async def delete_conversation_side_effect(conversation_id):
        return conversation_id == "test-conversation-id"
    
    mock_service.delete_conversation = AsyncMock(side_effect=delete_conversation_side_effect)

    mock_service.list_conversation_page = AsyncMock(
        return_value={
            "conversations": [
                {
                    "id": "conversation-1",
                    "title": "Paged conversation",
                    "created_at": "2026-08-02T10:00:00",
                    "updated_at": "2026-08-02T11:00:00",
                    "message_count": 2,
                    "last_message_preview": "Preview",
                }
            ],
            "has_more": True,
            "next_cursor": "cursor-1",
        }
    )
    
    return mock_service


@pytest.fixture
def mock_sqlite_service():
    """Create a mock SQLite knowledge service for the Agent-Task-status bulk lookup."""
    mock_service = MagicMock()
    mock_service.list_latest_agent_task_status_by_origins = AsyncMock(return_value={})
    return mock_service


@pytest.fixture
def test_app(mock_conversation_service, mock_sqlite_service):
    """Create a test FastAPI app with the conversation router."""
    app = FastAPI()
    
    # Override the get_conversation_service dependency
    def get_test_conversation_service():
        return mock_conversation_service
    
    app.dependency_overrides[get_conversation_service] = get_test_conversation_service
    app.dependency_overrides[_get_sqlite_knowledge_service] = lambda: mock_sqlite_service
    
    # Include the conversation router
    app.include_router(router)
    
    return app


@pytest.fixture
def test_client(test_app):
    """Create a test client for the FastAPI application."""
    return TestClient(test_app)


@pytest.mark.parametrize(
    "system_message", 
    [None, "This is a system message"]
)
def test_create_conversation(test_client, system_message):
    """Test the create conversation endpoint."""
    request_data = {}
    if system_message:
        request_data["system_message"] = system_message
        
    response = test_client.post(
        "/conversation/create",
        json=request_data
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "test-conversation-id"
    if system_message:
        assert data["system_message"] == system_message
    else:
        assert data["system_message"] is None


def test_get_conversation(test_client):
    """Test the get conversation endpoint."""
    # Test getting an existing conversation
    response = test_client.get("/conversation/test-conversation-id")
    
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "test-conversation-id"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"
    
    # Test getting a non-existent conversation
    response = test_client.get("/conversation/non-existent-id")
    
    assert response.status_code == 404


def test_send_message(test_client):
    """Test the send message endpoint."""
    # Test sending a message to an existing conversation
    response = test_client.post(
        "/conversation/test-conversation-id/send",
        json={"content": "Test message"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-response-id"
    assert data["content"] == "Test response"
    assert data["role"] == "assistant"
    
    # Test sending a message to a non-existent conversation
    response = test_client.post(
        "/conversation/non-existent-id/send",
        json={"content": "Test message"}
    )
    
    assert response.status_code == 404


def test_clear_conversation(test_client):
    """Test the clear conversation endpoint."""
    # Test clearing an existing conversation
    response = test_client.delete("/conversation/test-conversation-id/clear")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    # Test clearing a non-existent conversation
    response = test_client.delete("/conversation/non-existent-id/clear")
    
    assert response.status_code == 404


def test_delete_conversation(test_client):
    """Test the delete conversation endpoint."""
    # Test deleting an existing conversation
    response = test_client.delete("/conversation/test-conversation-id")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    # Test deleting a non-existent conversation
    response = test_client.delete("/conversation/non-existent-id")
    
    assert response.status_code == 404


def test_list_conversation_page_returns_cursor_contract(test_client, mock_conversation_service):
    response = test_client.get(
        "/conversation/page?query=planning&cursor=cursor-0&limit=30"
    )

    assert response.status_code == 200
    assert response.json() == {
        "conversations": [
            {
                "id": "conversation-1",
                "title": "Paged conversation",
                "created_at": "2026-08-02T10:00:00Z",
                "updated_at": "2026-08-02T11:00:00Z",
                "message_count": 2,
                "last_message_preview": "Preview",
                "metadata": {},
                "agent_status": None,
            }
        ],
        "has_more": True,
        "next_cursor": "cursor-1",
    }
    mock_conversation_service.list_conversation_page.assert_awaited_once_with(
        query="planning",
        cursor="cursor-0",
        limit=30,
    )


def test_list_conversation_page_includes_agent_status_from_bulk_lookup(
    test_client, mock_sqlite_service,
):
    mock_sqlite_service.list_latest_agent_task_status_by_origins.return_value = {
        "conversation-1": {
            "agent_task_id": "agent-task-1",
            "status": "processing",
            "result_severity": None,
            "is_active": True,
            "updated_at": "2026-08-02T11:00:00",
        }
    }

    response = test_client.get("/conversation/page")

    assert response.status_code == 200
    matching = response.json()["conversations"][0]
    assert matching["agent_status"] == {
        "agent_task_id": "agent-task-1",
        "status": "processing",
        "result_severity": None,
        "is_active": True,
        "updated_at": "2026-08-02T11:00:00",
    }
    mock_sqlite_service.list_latest_agent_task_status_by_origins.assert_awaited_once_with(
        "conversation", ["conversation-1"],
    )


def test_conversation_agent_status_endpoint_omits_nothing_for_unknown_ids(
    test_client, mock_sqlite_service,
):
    mock_sqlite_service.list_latest_agent_task_status_by_origins.return_value = {}

    response = test_client.get("/conversation/agent-status?ids=nonexistent-1,nonexistent-2")

    assert response.status_code == 200
    assert response.json() == {"nonexistent-1": None, "nonexistent-2": None}
    mock_sqlite_service.list_latest_agent_task_status_by_origins.assert_awaited_once_with(
        "conversation", ["nonexistent-1", "nonexistent-2"],
    )


def test_list_conversation_page_rejects_invalid_cursor(test_client, mock_conversation_service):
    mock_conversation_service.list_conversation_page.side_effect = ValueError(
        "Invalid conversation page cursor"
    )

    response = test_client.get("/conversation/page?cursor=broken")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid conversation page cursor"}


def test_list_conversation_page_validates_limit(test_client):
    response = test_client.get("/conversation/page?limit=0")

    assert response.status_code == 422


def test_conversation_history_serializes_naive_utc_with_z_suffix(test_client, mock_conversation_service):
    from datetime import datetime

    conversation = Conversation(
        id="utc-conversation",
        created_at=datetime(2026, 9, 30, 12, 27, 0),
        updated_at=datetime(2026, 9, 30, 12, 28, 0),
    )
    conversation.messages = [
        Message(
            id="utc-user-message",
            content="Hello",
            role=MessageRole.USER,
            timestamp=datetime(2026, 9, 30, 12, 27, 5, 250000),
        )
    ]
    mock_conversation_service.get_conversation = AsyncMock(return_value=conversation)

    response = test_client.get("/conversation/utc-conversation")

    assert response.status_code == 200
    data = response.json()
    assert data["created_at"] == "2026-09-30T12:27:00Z"
    assert data["updated_at"] == "2026-09-30T12:28:00Z"
    assert data["messages"][0]["timestamp"] == "2026-09-30T12:27:05.250000Z"


def test_conversation_page_normalizes_space_separated_sqlite_text(test_client, mock_conversation_service):
    mock_conversation_service.list_conversation_page = AsyncMock(
        return_value={
            "conversations": [
                {
                    "id": "conversation-sqlite",
                    "title": "SQLite text",
                    "created_at": "2026-09-30 12:27:00",
                    "updated_at": "2026-09-30 12:28:00",
                    "message_count": 1,
                    "last_message_preview": "Hi",
                }
            ],
            "has_more": False,
            "next_cursor": None,
        }
    )

    response = test_client.get("/conversation/page")

    assert response.status_code == 200
    item = response.json()["conversations"][0]
    assert item["created_at"] == "2026-09-30T12:27:00Z"
    assert item["updated_at"] == "2026-09-30T12:28:00Z"
