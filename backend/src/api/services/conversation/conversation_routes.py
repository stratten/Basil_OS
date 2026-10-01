"""API routes for conversation functionality."""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field
import uuid

from . import (
    ConversationService,
    Message,
    MessageRole,
    Conversation,
    ConversationError,
    ModelNotAvailableError,
    ConversationResponse
)
from ...core.models.responses import StatusResponse
from .conversation_timestamps import utc_iso_timestamp


router = APIRouter(prefix="/conversation", tags=["conversation"])


def _get_sqlite_knowledge_service():
    """Lazy-imports the singleton getter to avoid a module-load-time import
    cycle: `dependencies.py` imports `services.conversation` (this package's
    `__init__.py`, which imports this module for `router`), so importing
    `dependencies` at this module's top level would import `dependencies`
    before it finishes initializing. Defined as its own callable (rather than
    inlined at each call site) so tests can override it via
    `app.dependency_overrides`."""
    from ...dependencies import get_sqlite_knowledge_service

    return get_sqlite_knowledge_service()


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    system_message: Optional[str] = None


class CreateConversationResponse(BaseModel):
    """Response for creating a new conversation."""
    conversation_id: str
    system_message: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class MessageResponse(BaseModel):
    """Response containing a message."""
    id: str
    content: str
    role: str
    timestamp: str
    model_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationHistoryResponse(BaseModel):
    """Response containing conversation history."""
    conversation_id: str
    messages: List[MessageResponse]
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationAgentStatusSummary(BaseModel):
    """The single most-relevant Agent Task status for one Conversation,
    projected from `AgentTaskQueries.list_latest_agent_task_status_by_origins`.
    Deliberately duplicated from `TodoAgentStatusSummary` (same shape) rather
    than imported, so the conversation module has no dependency on the
    To-Do module."""
    agent_task_id: str
    status: str
    result_severity: Optional[str] = None
    is_active: bool
    updated_at: str


class ConversationListItem(BaseModel):
    """Response model for a conversation list item."""
    id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str
    message_count: int
    last_message_preview: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    agent_status: Optional[ConversationAgentStatusSummary] = None


class ConversationPageResponse(BaseModel):
    """Cursor-paginated conversation summaries for the WebKit sidebar."""
    conversations: List[ConversationListItem]
    has_more: bool
    next_cursor: Optional[str] = None


class UpdateTitleRequest(BaseModel):
    """Request to update conversation title."""
    title: str


class UpdateTitleResponse(BaseModel):
    """Response for updating conversation title."""
    status: str
    message: str
    conversation_id: str
    title: str


# Define a function to get the conversation service dependency
def get_conversation_service():
    """Get the conversation service dependency."""
    # Import here to avoid circular imports
    from ...dependencies import get_conversation_service as get_service
    return get_service()


@router.post("/create", response_model=CreateConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    conversation_service: ConversationService = Depends(get_conversation_service)
):
    """Create a new conversation."""
    conversation = await conversation_service.create_conversation(request.system_message)
    
    return CreateConversationResponse(
        conversation_id=conversation.id,
        system_message=request.system_message
    )


@router.post("/{conversation_id}/send", response_model=MessageResponse)
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    conversation_service: ConversationService = Depends(get_conversation_service)
):
    """Send a message in a conversation and get a response."""
    try:
        response = await conversation_service.send_message(conversation_id, request.content)
        
        # Convert to response model
        return MessageResponse(
            id=response.message.id,
            content=response.message.content,
            role=response.message.role.value,
            timestamp=utc_iso_timestamp(response.message.timestamp),
            model_id=response.message.model_id,
            metadata=response.metadata
        )
    except ConversationError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotAvailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")


@router.get("/page", response_model=ConversationPageResponse)
async def list_conversation_page(
    query: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    conversation_service: ConversationService = Depends(get_conversation_service),
    sqlite_service=Depends(_get_sqlite_knowledge_service),
):
    """Return one cursor-paginated conversation-summary page."""
    try:
        page = await conversation_service.list_conversation_page(
            query=query,
            cursor=cursor,
            limit=limit,
        )
        conversation_ids = [conversation["id"] for conversation in page["conversations"]]
        agent_status_by_id = await sqlite_service.list_latest_agent_task_status_by_origins(
            "conversation", conversation_ids,
        )
        return ConversationPageResponse(
            conversations=[
                ConversationListItem(
                    id=conversation["id"],
                    title=conversation.get("title") or "New Conversation",
                    created_at=utc_iso_timestamp(conversation["created_at"]),
                    updated_at=utc_iso_timestamp(conversation["updated_at"]),
                    message_count=conversation["message_count"],
                    last_message_preview=conversation.get("last_message_preview"),
                    metadata=conversation.get("metadata", {}),
                    agent_status=(
                        ConversationAgentStatusSummary(**agent_status_by_id[conversation["id"]])
                        if conversation["id"] in agent_status_by_id
                        else None
                    ),
                )
                for conversation in page["conversations"]
            ],
            has_more=page["has_more"],
            next_cursor=page["next_cursor"],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing conversation page: {str(error)}",
        ) from error


@router.get("/agent-status")
async def get_conversation_agent_statuses(
    ids: str = Query(default=""),
    sqlite_service=Depends(_get_sqlite_knowledge_service),
):
    conversation_ids = [conversation_id for conversation_id in ids.split(",") if conversation_id]
    statuses = await sqlite_service.list_latest_agent_task_status_by_origins("conversation", conversation_ids)
    return {conversation_id: statuses.get(conversation_id) for conversation_id in conversation_ids}


@router.get("/list", response_model=List[ConversationListItem])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    conversation_service: ConversationService = Depends(get_conversation_service)
):
    """List recent conversations ordered by last update.
    
    Args:
        limit: Maximum number of conversations to return (default 50)
        offset: Pagination offset (default 0)
        conversation_service: Conversation service dependency
        
    Returns:
        List of conversation summaries with metadata
    """
    try:
        conversations = await conversation_service.list_conversations(limit=limit, offset=offset)
        
        # Convert to response models
        return [
            ConversationListItem(
                id=conv["id"],
                title=conv["title"],
                created_at=utc_iso_timestamp(conv["created_at"]),
                updated_at=utc_iso_timestamp(conv["updated_at"]),
                message_count=conv["message_count"],
                last_message_preview=conv.get("last_message_preview"),
                metadata=conv.get("metadata", {})
            )
            for conv in conversations
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing conversations: {str(e)}")


@router.get("/search", response_model=List[ConversationListItem])
async def search_conversations(
    query: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    conversation_service: ConversationService = Depends(get_conversation_service)
):
    """Search conversations by title or message content.
    
    Args:
        query: Text to search for in conversation titles and message content
        days: Only search within the last N days
        limit: Maximum number of conversations to return (default 50)
        offset: Pagination offset (default 0)
        conversation_service: Conversation service dependency
        
    Returns:
        List of matching conversation summaries with metadata
    """
    from datetime import datetime, timedelta
    
    try:
        # Calculate start_date if days filter is specified
        start_date = None
        if days:
            start_date = datetime.now() - timedelta(days=days)
        
        conversations = await conversation_service.search_conversations(
            query=query,
            start_date=start_date,
            limit=limit,
            offset=offset
        )
        
        # Convert to response models
        return [
            ConversationListItem(
                id=conv["id"],
                title=conv.get("title") or "New Conversation",
                created_at=utc_iso_timestamp(conv["created_at"]),
                updated_at=utc_iso_timestamp(conv["updated_at"]),
                message_count=conv.get("message_count", 0),
                last_message_preview=conv.get("last_message_preview"),
                metadata=conv.get("metadata", {})
            )
            for conv in conversations
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching conversations: {str(e)}")


@router.get("/{conversation_id}", response_model=ConversationHistoryResponse)
async def get_conversation(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service)
):
    """Get conversation history."""
    conversation = await conversation_service.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
    
    # Convert messages to response format
    messages = []
    for msg in conversation.messages:
        messages.append(MessageResponse(
            id=msg.id,
            content=msg.content,
            role=msg.role.value,
            timestamp=utc_iso_timestamp(msg.timestamp),
            model_id=msg.model_id,
            metadata=msg.metadata
        ))
    
    return ConversationHistoryResponse(
        conversation_id=conversation.id,
        messages=messages,
        created_at=utc_iso_timestamp(conversation.created_at),
        updated_at=utc_iso_timestamp(conversation.updated_at),
        metadata=conversation.metadata
    )


@router.delete("/{conversation_id}/clear", response_model=StatusResponse)
async def clear_conversation(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service)
) -> StatusResponse:
    """Clear all messages from a conversation."""
    success = await conversation_service.clear_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
    
    return StatusResponse(status="success", message="Conversation cleared")


@router.delete("/{conversation_id}", response_model=StatusResponse)
async def delete_conversation(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service)
) -> StatusResponse:
    """Delete a conversation."""
    success = await conversation_service.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
    
    return StatusResponse(status="success", message="Conversation deleted")


@router.put("/{conversation_id}/title", response_model=UpdateTitleResponse)
async def update_conversation_title(
    conversation_id: str,
    request: UpdateTitleRequest,
    conversation_service: ConversationService = Depends(get_conversation_service)
) -> UpdateTitleResponse:
    """Update conversation title.
    
    Args:
        conversation_id: ID of the conversation to update
        request: Request body with new title
        conversation_service: Conversation service dependency
        
    Returns:
        Success confirmation
    """
    try:
        success = await conversation_service.update_conversation_title(
            conversation_id=conversation_id,
            title=request.title
        )
        if not success:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        
        return UpdateTitleResponse(
            status="success",
            message="Title updated",
            conversation_id=conversation_id,
            title=request.title
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating conversation title: {str(e)}") 