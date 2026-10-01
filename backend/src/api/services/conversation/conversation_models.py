"""Models for the conversation service."""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from .conversation_timestamps import utc_now_naive


class MessageRole(str, Enum):
    """Roles for conversation messages."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"


class Message(BaseModel):
    """A message in a conversation."""
    id: str
    content: str
    role: MessageRole
    timestamp: datetime = Field(default_factory=utc_now_naive)
    model_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    """A conversation between a user and the assistant."""
    id: str
    messages: List[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now_naive)
    updated_at: datetime = Field(default_factory=utc_now_naive)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationError(Exception):
    """Base exception for conversation service errors."""
    pass


class ModelNotAvailableError(ConversationError):
    """Exception raised when no suitable model is available."""

    def __init__(
        self,
        message: str,
        *,
        conversation_id: Optional[str] = None,
        user_message_id: Optional[str] = None,
        error_message_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id
        self.user_message_id = user_message_id
        self.error_message_id = error_message_id


class ConversationResponse(BaseModel):
    """Response from the conversation service."""
    message: Message
    conversation_id: str
    user_message_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict) 