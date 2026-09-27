"""Service for handling unstructured conversations with reasoning models."""

import asyncio
import logging
import uuid
from typing import Optional, Dict, Any, Set, List, Tuple, AsyncGenerator, Callable
from datetime import datetime

from ...core.models.model_types import ModelCapability
from ...core.models.base_model import BaseAIModel
from ...core.services.model_service import ModelService, ModelNotFoundError
from ...core.logging.api_logger import api_logger
from ...core.services.file_storage_service import StorageService
from ...core.knowledge.sqlite.conversation_repository import (
    ConversationRepository,
    ConversationTurnAdmissionConflict,
)
from ...core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from ...settings import Settings, get_settings
from ...core.models.preferences import Preferences
from ..model_usage_service import ModelUsageService
from .conversation_models import (
    Message, 
    MessageRole, 
    Conversation, 
    ConversationError,
    ModelNotAvailableError,
    ConversationResponse
)
from .document_processing_service import DocumentProcessingService
from .conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    ConversationTurnLifecycle,
    ConversationTurnRoute,
    build_conversation_turn_placeholder_metadata,
)


logger = logging.getLogger(__name__)


class ConversationService:
    """Service for handling unstructured conversations with reasoning models."""
    
    def __init__(
        self,
        model_service: ModelService,
        storage_service: Optional[StorageService] = None,
        development_mode: bool = True,
        settings: Optional[Settings] = None,
        model_usage_service: Optional[ModelUsageService] = None,
        conversation_repository: Optional[ConversationRepository] = None,
        sqlite_knowledge_service: Optional[SQLiteKnowledgeService] = None
    ) -> None:
        """Initialize conversation service.
        
        Args:
            model_service: Service for managing AI models
            storage_service: Optional storage service for managing files
            development_mode: If True, uses development paths
            settings: Optional settings instance for configuration
            model_usage_service: Optional model usage service for model selection
            conversation_repository: Optional conversation repository for persistence
            sqlite_knowledge_service: Optional SQLiteKnowledgeService for unified database access
        """
        self.model_service = model_service
        self.storage = storage_service or StorageService(development_mode)
        self.settings = settings or get_settings()
        
        # Initialize or store model usage service
        self.model_usage_service = model_usage_service or ModelUsageService(model_service)
        
        # Initialize SQLiteKnowledgeService for unified database access
        self.sqlite_knowledge_service = sqlite_knowledge_service
        
        # Initialize conversation repository for persistent storage
        if conversation_repository is not None:
            self.conversation_repository = conversation_repository
        else:
            # Create ConversationRepository with shared SQLite service if available
            self.conversation_repository = ConversationRepository(
                sqlite_service=self.sqlite_knowledge_service
            )
        
        # Document processing for file attachments
        self.document_processor = DocumentProcessingService()
        
        # Configure logging
        self.logger = api_logger.getChild("conversation_service")
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _schedule_background_task(
        self,
        coroutine: Any,
        task_name: str,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=task_name)
        self._background_tasks.add(task)

        def _finish(completed: asyncio.Task[None]) -> None:
            self._background_tasks.discard(completed)
            if completed.cancelled():
                return
            exception = completed.exception()
            if exception is not None:
                self.logger.warning("Conversation background task %s failed: %s", task_name, exception)

        task.add_done_callback(_finish)
        return task

    async def shutdown_background_tasks(self) -> None:
        tasks = tuple(task for task in self._background_tasks if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def _get_model_for_task(
        self, 
        capabilities: Set[ModelCapability] | list[ModelCapability],
        explicit_model_id: Optional[str] = None
    ) -> Optional[BaseAIModel]:
        """Get model for requested capabilities.
        
        Uses the ModelUsageService to select the appropriate model based on
        user preferences and explicit model ID if provided.
        
        Args:
            capabilities: Set or list of required model capabilities
            explicit_model_id: Optional specific model ID to use
            
        Returns:
            Model instance if available
        """
        return await self.model_usage_service.get_model_for_task(
            capabilities=capabilities,
            explicit_model_id=explicit_model_id
        )

    async def _auto_title_conversation(self, conversation_id: str, first_message: str) -> None:
        """Generate and set a title for a new conversation based on the first user message."""
        try:
            title = await self.generate_conversation_title(first_message)
            await self.update_conversation_title(conversation_id, title)
        except Exception as e:
            self.logger.warning(f"Failed to auto-title conversation {conversation_id}: {e}")

    async def create_conversation(self, system_message: Optional[str] = None) -> Conversation:
        """Create a new conversation.
        
        Args:
            system_message: Optional system message to initialize the conversation
            
        Returns:
            Newly created conversation
        """
        # Create conversation in database
        conversation_id = await self.conversation_repository.create_conversation(
            system_message=system_message
        )
        
        # Return conversation object
        conversation = Conversation(id=conversation_id)
        
        # Add system message if provided
        if system_message:
            system_msg = Message(
                id=str(uuid.uuid4()),
                content=system_message,
                role=MessageRole.SYSTEM
            )
            conversation.messages.append(system_msg)
        
        return conversation
    
    async def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Get a conversation by ID.
        
        Args:
            conversation_id: ID of the conversation to retrieve
            
        Returns:
            Conversation if found, None otherwise
        """
        # Get conversation from database
        conv_data = await self.conversation_repository.get_conversation_with_messages(conversation_id)
        if not conv_data:
            return None
        
        # Convert to Conversation object
        conversation = Conversation(
            id=conv_data["id"],
            created_at=datetime.fromisoformat(conv_data["created_at"]) if conv_data["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(conv_data["updated_at"]) if conv_data["updated_at"] else datetime.now(),
            metadata=conv_data.get("metadata", {})
        )
        
        # Legacy rows may have a system prompt only in the conversation
        # column; current rows persist that prompt as a system message too.
        # Materialize the column value only when it is absent from the
        # message sequence so callers never receive duplicate instructions.
        has_persisted_system_message = any(
            item["role"] == "system" for item in conv_data["messages"]
        )
        if conv_data.get("system_message") and not has_persisted_system_message:
            system_msg = Message(
                id=str(uuid.uuid4()),
                content=conv_data["system_message"],
                role=MessageRole.SYSTEM,
                timestamp=conversation.created_at,
                metadata={}
            )
            conversation.messages.append(system_msg)
        
        # Convert messages (skip assistant messages with empty content)
        for msg_data in conv_data["messages"]:
            # Skip assistant messages with empty content (incomplete streaming responses)
            if msg_data["role"] == "assistant" and not msg_data["content"].strip():
                logger.debug(f"Skipping empty assistant message: {msg_data['id']}")
                continue
            
            message = Message(
                id=msg_data["id"],
                content=msg_data["content"],
                role=MessageRole(msg_data["role"]),
                timestamp=datetime.fromisoformat(msg_data["timestamp"]) if msg_data["timestamp"] else datetime.now(),
                model_id=msg_data.get("model_id"),
                metadata=msg_data.get("metadata", {})
            )
            conversation.messages.append(message)
        
        return conversation
    
    async def add_message(self, conversation_id: str, role: str, content: str, model_id: Optional[str] = None) -> Message:
        """Add a message to a conversation.
        
        Args:
            conversation_id: ID of the conversation
            role: Message role (as string: 'user', 'assistant', 'system', 'error')
            content: Message content
            model_id: Optional model ID that generated the message
            
        Returns:
            Newly created message
            
        Raises:
            ConversationError: If conversation not found
        """
        # Check if conversation exists
        conversation = await self.get_conversation(conversation_id)
        if not conversation:
            raise ConversationError(f"Conversation {conversation_id} not found")
        
        # Convert string role to MessageRole enum
        message_role = MessageRole(role)
        
        # Add message to database
        message_id = await self.conversation_repository.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model_id=model_id
        )
        
        message = Message(
            id=message_id,
            content=content,
            role=message_role,
            model_id=model_id,
        )
        
        logger.info(f"[ADD_MESSAGE] Created message: id={message.id}, role={message.role}, content='{message.content[:50]}'")
        
        return message
    
    async def _call_model_with_fallback(
        self,
        model: BaseAIModel,
        formatted_messages: List[Dict[str, str]],
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Call chat_completion, retrying once against the local fallback model
        if the first attempt fails with a completely-unreachable error.

        Returns (response, fallback_model_id_used_or_None).
        """
        from ..model_usage_service import is_model_unreachable_error
        try:
            response = await model.chat_completion(formatted_messages)
            return response, None
        except Exception as first_error:
            if not is_model_unreachable_error(first_error):
                raise
            fallback_model = await self.model_usage_service.get_designated_local_fallback_model(
                {ModelCapability.REASONING}
            )
            if fallback_model is None:
                raise
            self.logger.warning(
                f"Preferred reasoning model unreachable ({first_error}); "
                f"retrying this turn once with local fallback model"
            )
            response = await fallback_model.chat_completion(formatted_messages)
            return response, fallback_model.model_name

    async def send_message(
        self,
        conversation_id: str,
        content: str,
        model_id: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        message_metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationResponse:
        """Send a user message and get a response.
        
        Args:
            conversation_id: ID of the conversation
            content: User message content
            model_id: Optional specific model ID to use for this message
            file_paths: Optional list of file paths attached to this message
            
        Returns:
            Response from the model
            
        Raises:
            ConversationError: If conversation not found
            ModelNotAvailableError: If no suitable model is available
        """
        conversation = await self.get_conversation(conversation_id)
        if not conversation:
            raise ConversationError(f"Conversation {conversation_id} not found")
        
        # Store file metadata and optional caller metadata on the user message
        user_metadata: Dict[str, Any] = dict(message_metadata or {})
        if file_paths:
            user_metadata["attached_files"] = DocumentProcessingService.build_file_metadata(file_paths)
        if not user_metadata:
            user_metadata = None
        
        user_message_id = await self.conversation_repository.add_message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            metadata=user_metadata
        )
        user_message = Message(id=user_message_id, content=content, role=MessageRole.USER)
        conversation.messages.append(user_message)
        
        if sum(1 for m in conversation.messages if m.role == MessageRole.USER) == 1:
            self._schedule_background_task(self._auto_title_conversation(conversation_id, content), f"conversation-auto-title-{conversation_id}")
        
        model = await self._get_model_for_task([ModelCapability.REASONING], model_id)
        if not model:
            error_message = await self.add_message(
                conversation_id,
                "error",
                "No suitable model available for conversation.",
            )
            raise ModelNotAvailableError(
                "No suitable model available for conversation",
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                error_message_id=error_message.id,
            )
        
        # Format conversation history
        formatted_messages = [{"role": msg.role.value, "content": msg.content} for msg in conversation.messages]
        
        try:
            # Process files if attached
            if file_paths:
                provider = self.document_processor.detect_provider(model)
                processed = await self.document_processor.process_files_for_model(file_paths, content, provider)
                
                if processed["method"] == "anthropic_files":
                    from ...core.models.reasoning.claude_model import ClaudeModel
                    if isinstance(model, ClaudeModel):
                        response_text = await model.generate_response_with_files(
                            prompt=processed["content"],
                            file_contents=processed["file_contents"]
                        )
                        assistant_message = await self.add_message(conversation_id, "assistant", response_text, model_id=model_id)
                        return ConversationResponse(
                            message=assistant_message,
                            conversation_id=conversation_id,
                            user_message_id=user_message_id,
                        )
                    else:
                        formatted_messages[-1]["content"] = processed["content"]
                elif processed["method"] == "multimodal":
                    formatted_messages[-1]["content"] = processed["content"]
                elif processed["method"] == "text_prepend":
                    formatted_messages[-1]["content"] = processed["content"]
            
            response, fallback_model_id = await self._call_model_with_fallback(model, formatted_messages)
            assistant_content = response.get("content", "") or "I'm sorry, I couldn't generate a response."

            response_metadata = dict(response.get("metadata", {}))
            if fallback_model_id:
                response_metadata["answered_by_fallback_model"] = fallback_model_id

            assistant_message = await self.add_message(
                conversation_id, "assistant", assistant_content,
                model_id=fallback_model_id or model_id,
            )
            return ConversationResponse(
                message=assistant_message,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                metadata=response_metadata,
            )
            
        except Exception as e:
            self.logger.exception(f"Error getting response from model: {e}")
            error_message = await self.add_message(conversation_id, "error", f"Error: {str(e)}")
            return ConversationResponse(
                message=error_message,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
            )
    
    async def send_message_streaming(
        self,
        conversation_id: str,
        content: str,
        model_id: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        message_metadata: Optional[Dict[str, Any]] = None,
        on_persistence_ready: Optional[Callable[[str, str], None]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Persist a direct turn before streaming its response into that placeholder."""
        conversation = await self.get_conversation(conversation_id)
        if not conversation:
            raise ConversationError(f"Conversation {conversation_id} not found")

        user_metadata: Dict[str, Any] = dict(message_metadata or {})
        if file_paths:
            user_metadata["attached_files"] = DocumentProcessingService.build_file_metadata(file_paths)
        if not user_metadata:
            user_metadata = None

        pair_task = asyncio.create_task(
            self.conversation_repository.admit_and_create_message_pair(
                conversation_id=conversation_id,
                user_content=content,
                user_metadata=user_metadata,
                assistant_metadata=build_conversation_turn_placeholder_metadata(
                    ConversationTurnRoute.DIRECT,
                ),
                assistant_model_id=model_id,
            )
        )
        try:
            pair = await asyncio.shield(pair_task)
        except ConversationTurnAdmissionConflict as exc:
            raise ConversationError(str(exc)) from exc
        except asyncio.CancelledError:
            pair = await pair_task
            await self.conversation_repository.update_message(
                message_id=pair.assistant_message_id,
                content="",
            )
            await self.conversation_repository.merge_message_metadata(
                pair.assistant_message_id,
                {
                    CONVERSATION_TURN_METADATA_KEY: {
                        "lifecycle": ConversationTurnLifecycle.CANCELLED.value,
                    },
                    "cancelled": True,
                },
            )
            raise
        user_message = Message(id=pair.user_message_id, content=content, role=MessageRole.USER)
        conversation.messages.append(user_message)

        if sum(1 for message in conversation.messages if message.role == MessageRole.USER) == 1:
            self._schedule_background_task(self._auto_title_conversation(conversation_id, content), f"conversation-auto-title-{conversation_id}")

        full_content = ""
        response_metadata: Dict[str, Any] = {}

        try:
            await self.conversation_repository.merge_message_metadata(
                pair.assistant_message_id,
                {
                    CONVERSATION_TURN_METADATA_KEY: {
                        "lifecycle": ConversationTurnLifecycle.RUNNING.value,
                    }
                },
            )
            if on_persistence_ready is not None:
                on_persistence_ready(pair.user_message_id, pair.assistant_message_id)

            model = await self._get_model_for_task(
                [ModelCapability.REASONING],
                explicit_model_id=model_id,
            )
            if not model:
                raise ModelNotAvailableError("No suitable model available for conversation")

            formatted_messages = [
                {"role": message.role.value, "content": message.content}
                for message in conversation.messages
            ]
            use_anthropic_file_streaming = False
            anthropic_file_contents = None

            if file_paths:
                provider = self.document_processor.detect_provider(model)
                processed = await self.document_processor.process_files_for_model(
                    file_paths,
                    content,
                    provider,
                )
                if processed["method"] == "anthropic_files":
                    from ...core.models.reasoning.claude_model import ClaudeModel

                    if isinstance(model, ClaudeModel):
                        use_anthropic_file_streaming = True
                        anthropic_file_contents = processed["file_contents"]
                    formatted_messages[-1]["content"] = processed["content"]
                elif processed["method"] in ("multimodal", "text_prepend"):
                    formatted_messages[-1]["content"] = processed["content"]

            from ..model_usage_service import is_model_unreachable_error

            active_model = model
            fallback_model_id: Optional[str] = None
            tokens_yielded = False
            while True:
                try:
                    if use_anthropic_file_streaming:
                        async for token in active_model.chat_completion_streaming_with_files(
                            messages=formatted_messages,
                            file_contents=anthropic_file_contents,
                        ):
                            tokens_yielded = True
                            full_content += token
                            yield {
                                "token": token,
                                "message_id": pair.assistant_message_id,
                                "conversation_id": conversation_id,
                            }
                    else:
                        async for token in active_model.chat_completion_streaming(formatted_messages):
                            tokens_yielded = True
                            full_content += token
                            yield {
                                "token": token,
                                "message_id": pair.assistant_message_id,
                                "conversation_id": conversation_id,
                            }
                    break
                except Exception as stream_error:
                    if tokens_yielded or not is_model_unreachable_error(stream_error):
                        raise
                    fallback_candidate = await self.model_usage_service.get_designated_local_fallback_model(
                        {ModelCapability.REASONING}
                    )
                    if fallback_candidate is None:
                        raise
                    self.logger.warning(
                        f"Preferred reasoning model unreachable ({stream_error}); "
                        f"retrying this turn once with local fallback model"
                    )
                    active_model = fallback_candidate
                    fallback_model_id = fallback_candidate.model_name
                    continue

            if fallback_model_id:
                response_metadata["answered_by_fallback_model"] = fallback_model_id

            import re

            content_without_thinking = re.sub(
                r"<think>.*?</think>",
                "",
                full_content,
                flags=re.DOTALL,
            ).strip()
            thinking_matches = re.findall(r"<think>(.*?)</think>", full_content, flags=re.DOTALL)
            if thinking_matches:
                response_metadata["thinking"] = "\n\n".join(thinking_matches)

            await self.conversation_repository.update_message(
                message_id=pair.assistant_message_id,
                content=content_without_thinking,
            )
            await self.conversation_repository.merge_message_metadata(
                pair.assistant_message_id,
                {
                    CONVERSATION_TURN_METADATA_KEY: {
                        "lifecycle": ConversationTurnLifecycle.COMPLETED.value,
                    },
                    **response_metadata,
                },
            )
            yield {
                "token": "",
                "message_id": pair.assistant_message_id,
                "conversation_id": conversation_id,
                "is_final": True,
                "metadata": response_metadata,
            }

        except asyncio.CancelledError:
            import re

            content_without_thinking = re.sub(
                r"<think>.*?</think>",
                "",
                full_content,
                flags=re.DOTALL,
            ).strip()
            thinking_matches = re.findall(r"<think>(.*?)</think>", full_content, flags=re.DOTALL)
            cancellation_metadata: Dict[str, Any] = {"cancelled": True}
            if thinking_matches:
                cancellation_metadata["thinking"] = "\n\n".join(thinking_matches)

            await self.conversation_repository.update_message(
                message_id=pair.assistant_message_id,
                content=content_without_thinking,
            )
            await self.conversation_repository.merge_message_metadata(
                pair.assistant_message_id,
                {
                    CONVERSATION_TURN_METADATA_KEY: {
                        "lifecycle": ConversationTurnLifecycle.CANCELLED.value,
                    },
                    **cancellation_metadata,
                },
            )
            raise

        except Exception as exc:
            self.logger.exception(f"Error getting streaming response from model: {exc}")
            error_content = f"Error: {str(exc)}"
            await self.conversation_repository.update_message(
                message_id=pair.assistant_message_id,
                content=error_content,
            )
            await self.conversation_repository.merge_message_metadata(
                pair.assistant_message_id,
                {
                    CONVERSATION_TURN_METADATA_KEY: {
                        "lifecycle": ConversationTurnLifecycle.FAILED.value,
                    },
                    "error": True,
                },
            )
            yield {
                "token": error_content,
                "message_id": pair.assistant_message_id,
                "conversation_id": conversation_id,
                "error": True,
                "is_final": True,
            }
    
    async def clear_conversation(self, conversation_id: str) -> bool:
        """Clear all messages from a conversation.
        
        Args:
            conversation_id: ID of the conversation
            
        Returns:
            True if successful, False otherwise
        """
        if not await self.get_conversation(conversation_id):
            return False
        return await self.conversation_repository.clear_conversation(
            conversation_id=conversation_id,
            keep_system_messages=True
        )
    
    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation.
        
        Args:
            conversation_id: ID of the conversation
            
        Returns:
            True if successful, False otherwise
        """
        if not await self.get_conversation(conversation_id):
            return False
        return await self.conversation_repository.delete_conversation(conversation_id)
    
    async def list_conversation_page(
        self,
        *,
        query: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> Dict[str, Any]:
        """Return one cursor-paginated conversation-summary page."""
        return await self.conversation_repository.list_conversation_page(
            query=query,
            limit=limit,
            cursor=cursor,
        )

    async def list_conversations(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List recent conversations ordered by last update.
        
        Args:
            limit: Maximum number of conversations to return (default 50)
            offset: Pagination offset (default 0)
            
        Returns:
            List of conversation summaries with metadata
        """
        conversations = await self.conversation_repository.list_conversations(
            limit=limit,
            offset=offset
        )
        
        # Enhance each conversation with additional metadata
        enhanced_conversations = []
        for conv in conversations:
            # Get message count and last message preview
            conv_with_messages = await self.conversation_repository.get_conversation_with_messages(conv["id"])
            messages = conv_with_messages.get("messages", []) if conv_with_messages else []
            
            last_message_preview = None
            if messages:
                # Get the last non-system message
                for msg in reversed(messages):
                    if msg["role"] != "system":
                        last_message_preview = msg["content"][:100]
                        if len(msg["content"]) > 100:
                            last_message_preview += "..."
                        break
            
            enhanced_conversations.append({
                "id": conv["id"],
                "title": conv.get("title") or "New Conversation",  # Handle None values
                "created_at": conv["created_at"],
                "updated_at": conv["updated_at"],
                "message_count": sum(1 for m in messages if m["role"] != "system"),
                "last_message_preview": last_message_preview,
                "metadata": conv.get("metadata", {})
            })
        
        return enhanced_conversations
    
    async def search_conversations(
        self,
        query: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Search for conversations by title or message content.
        
        Args:
            query: Text to search for in conversation titles and message content
            start_date: Start date for filtering
            end_date: End date for filtering
            limit: Maximum number of conversations to return (default 50)
            offset: Pagination offset (default 0)
            
        Returns:
            List of matching conversation summaries with metadata
        """
        return await self.conversation_repository.search_conversations(
            query=query,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
    
    async def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update conversation title.
        
        Args:
            conversation_id: ID of the conversation
            title: New title for the conversation
            
        Returns:
            True if successful, False otherwise
        """
        return await self.conversation_repository.update_conversation_title(
            conversation_id=conversation_id,
            title=title
        )
    
    async def generate_conversation_title(self, first_message: str) -> str:
        """Generate a concise title from the first user message.
        
        Args:
            first_message: The first user message in the conversation
            
        Returns:
            Generated title (truncated to 50 characters)
        """
        # Simple approach: truncate to first 50 chars
        # Future enhancement: Use LLM to generate better titles
        title = first_message.strip()[:50]
        if len(first_message) > 50:
            title += "..."
        return title 