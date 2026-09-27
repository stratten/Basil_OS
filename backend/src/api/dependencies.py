from functools import lru_cache
from pathlib import Path
from fastapi import WebSocket, HTTPException, Request

# Use the get_model_service from the model_service module directly
from .core.services.model_service import get_model_service, ModelService
from .core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from .core.config.api_settings import settings
from .core.knowledge.query.activity_query_processor import ActivityQueryProcessor
from .core.knowledge.query.query_intent_handler import QueryIntentHandler
from .core.llm import LLMService
from .services.conversation import ConversationService
from .services.model_usage_service import ModelUsageService
from .core.services.file_storage_service import StorageService
from .core.runtime.hardware_capability_service import HardwareCapabilityService


# This local get_model_service function is now redundant if we import the one from model_service.py
# We will rely on the imported one.
# @lru_cache()
# def get_model_service() -> ModelService:
#     """Get or create the model service singleton."""
#     # The ModelService module owns canonical model-directory resolution.
#     service = ModelService(get_models_dir())
#     service.initialize()  # Ensure the service is initialized
#     return service

@lru_cache()
def get_knowledge_service() -> SQLiteKnowledgeService:
    """Compatibility alias for the canonical SQLite knowledge service."""
    return get_sqlite_knowledge_service()

@lru_cache()
def get_sqlite_knowledge_service() -> SQLiteKnowledgeService:
    """Get or create the SQLite knowledge service singleton.
    
    This service provides direct access to the SQLite database for storing
    and retrieving activities, agent_tasks, transcriptions, and other data.
    Using a singleton ensures only one instance manages database connections
    and avoids threading conflicts during concurrent access.
    """
    return SQLiteKnowledgeService()

@lru_cache()
def get_model_usage_service() -> ModelUsageService:
    """Get or create the model usage service singleton.
    
    This service centralizes model selection logic and provides a consistent
    interface for selecting the best model for various tasks.
    """
    model_service = get_model_service()
    return ModelUsageService(model_service)

@lru_cache()
def get_hardware_capability_service() -> HardwareCapabilityService:
    """Get or create the shared hardware capability service."""
    return HardwareCapabilityService()

@lru_cache()
def get_query_intent_handler() -> QueryIntentHandler:
    """Get or create the query intent handler singleton.
    
    This handler processes natural language queries about user activities
    and returns structured results.
    """
    # Get the knowledge service
    knowledge_service = get_knowledge_service()
    
    # Create the activity query processor
    query_processor = ActivityQueryProcessor(knowledge_base=knowledge_service)
    
    # Get the model service for direct access to models
    model_service = get_model_service()
    
    # Get the model usage service for centralized model selection
    model_usage_service = get_model_usage_service()
    
    # Create and return the query intent handler with model services
    return QueryIntentHandler(
        query_processor=query_processor,
        model_service=model_service,  # Keep for backward compatibility
        model_usage_service=model_usage_service  # Add model_usage_service for improved model selection
    )

@lru_cache()
def get_conversation_service() -> ConversationService:
    """Get or create the conversation service singleton.
    
    This service handles unstructured conversations with reasoning models.
    """
    # Get the model service
    model_service = get_model_service()
    
    # Get the model usage service
    model_usage_service = get_model_usage_service()
    
    # Get the shared SQLite service for unified database access
    sqlite_knowledge_service = get_sqlite_knowledge_service()
    
    # Create and return the conversation service
    return ConversationService(
        model_service=model_service,
        development_mode=settings.DEBUG,  # Use DEBUG instead of DEVELOPMENT_MODE
        model_usage_service=model_usage_service,  # Pass model_usage_service for improved model selection
        sqlite_knowledge_service=sqlite_knowledge_service  # Pass shared SQLite service for unified database access
    )

def get_wake_word_service(request: Request = None, websocket: WebSocket = None):
    """
    Retrieve the wake-word/audio lifecycle service from application state.
    """
    context = request or websocket
    if context is None:
        raise HTTPException(status_code=500, detail="No request or WebSocket provided for dependency")
    service = getattr(context.app.state, "wake_word_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="WakeWordService not initialized")
    return service

def get_agent_task_submission_service(request: Request = None, websocket: WebSocket = None):
    """
    Retrieve the agent-processing submission service from application state.
    This is the direct owner for non-wake-word agent-task APIs.
    """
    context = request or websocket
    if context is None:
        raise HTTPException(status_code=500, detail="No request or WebSocket provided for dependency")
    service = getattr(context.app.state, "agent_task_submission_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="AgentTaskSubmissionService not initialized")
    return service

def get_managed_file_history_service_for_routes():
    """FastAPI dependency: the managed-history service for the review/restore routes.

    Routes always target a path a prior agent write already accepted as
    eligible, so a Path.home()-scoped writer is sufficient here; it never
    needs the backend-root write scope agent tool calls also get. Under the
    developer-local validation runtime, fixture documents intentionally live
    under the session's `fixtures/` directory, a sibling of the session's
    synthetic home (see `ValidationRuntimeProfile.fixtures_root` and
    `.session_home` in `core/runtime/validation_profile.py`), so restore
    would otherwise reject every validation fixture path as outside the
    allowed root. Add that fixtures root to the writer's allow-list only
    when the backend is actually running as a validation session.
    """
    from pathlib import Path as _Path

    from .core.runtime.validation_profile import (
        ValidationRuntimeProfile,
        is_validation_runtime,
    )
    from .services.agent_processing.tools.direct_application_interactions.file_system.text_file_write import (
        LocalTextFileWriter,
    )
    from .services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_wiring import (
        get_managed_file_history_service,
    )

    allowed_roots = [_Path.home()]
    if is_validation_runtime():
        allowed_roots.append(ValidationRuntimeProfile.from_environment().fixtures_root)

    return get_managed_file_history_service(text_writer=LocalTextFileWriter(allowed_roots))


_local_preview_registry = None


def get_local_preview_launcher(request: Request = None, websocket: WebSocket = None):
    """
    Retrieve the process-lifetime local web preview launcher, constructing it
    lazily against the current connection's AgentTaskSubmissionService so
    approval prompts route over the same WebSocket the shell-command
    approval modal already uses.
    """
    global _local_preview_registry
    from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_session_registry import (
        LocalPreviewSessionRegistry,
    )
    from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher import (
        LocalPreviewServerLauncher,
    )

    submission_service = get_agent_task_submission_service(request=request, websocket=websocket)
    if _local_preview_registry is None:
        _local_preview_registry = LocalPreviewSessionRegistry()
    return LocalPreviewServerLauncher(
        _local_preview_registry,
        websocket_manager=getattr(
            submission_service.agent_task_orchestrator,
            "websocket_manager",
            None,
        ),
    )

@lru_cache()
def get_todo_service():
    from .services.todos.repository import TodoRepository
    from .services.todos.service import TodoService

    sqlite_service = get_sqlite_knowledge_service()
    return TodoService(
        repository=TodoRepository(sqlite_service.db_path),
        agent_task_service=sqlite_service,
    )


def get_todo_workspace_turn_manager(request: Request = None, websocket: WebSocket = None):
    from .services.todos.workspace_turn_manager import TodoWorkspaceTurnManager

    agent_task_submission_service = get_agent_task_submission_service(request=request, websocket=websocket)
    return TodoWorkspaceTurnManager(
        todo_service=get_todo_service(),
        agent_task_submission_service=agent_task_submission_service,
    )


def get_conversation_turn_router(request: Request = None, websocket: WebSocket = None):
    """Build the public Conversation turn router for the current connection.

    Imports are local to avoid a circular import: conversation_agent_turn_lifecycle
    imports get_sqlite_knowledge_service from this module at top level.
    """
    from .core.models.preferences import Preferences
    from .services.conversation.conversation_agent_turn_lifecycle import (
        get_registered_conversation_agent_turn_lifecycle,
    )
    from .services.conversation.conversation_agent_turn_service import ConversationAgentTurnService
    from .services.conversation.conversation_route_selector import ConversationRouteSelector
    from .services.conversation.conversation_turn_router import ConversationTurnRouter

    agent_task_submission_service = get_agent_task_submission_service(request=request, websocket=websocket)
    conversation_service = get_conversation_service()
    model_usage_service = get_model_usage_service()
    agent_turn_service = ConversationAgentTurnService(
        repository=conversation_service.conversation_repository,
        submission_service=agent_task_submission_service,
        agent_task_service=get_sqlite_knowledge_service(),
        lifecycle=get_registered_conversation_agent_turn_lifecycle(),
    )
    route_selector = ConversationRouteSelector(
        model_usage_service=model_usage_service,
        configured_reasoning_model_id=Preferences.load().models.reasoning_model,
    )
    return ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=route_selector,
        agent_turn_service=agent_turn_service,
    )

def resolve_transcription_service():
    """Resolve the correct transcription service based on current user preferences.

    Checks whether API transcription is enabled and the selected model is a cloud
    model. Returns the OpenAI API service when appropriate, otherwise falls back
    to the shared local HuggingFace service from app.state.

    This function has no FastAPI context dependency so it can be called from
    websocket handlers, AssistantSession routes, or anywhere else.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        from .core.models.preferences import Preferences
        preferences = Preferences.load()
        selected_model = preferences.models.transcription_model

        if preferences.models.use_api_transcription_models:
            from .core.models.models_registry import get_cloud_transcription_models
            if selected_model in get_cloud_transcription_models():
                from .services.transcription.backends.openai_whisper_api_service import OpenAIWhisperAPITranscriptionService
                _logger.info(f"Resolving API transcription service for model: {selected_model}")
                return OpenAIWhisperAPITranscriptionService(model_id=selected_model)

        # Parakeet branch -- the user's selection (a display name from the
        # registry) is matched against the Parakeet handler set, then the
        # shared service from `app.state` is reused when present so the
        # ONNX sessions are loaded exactly once per process.
        from .core.models.models_registry import get_parakeet_transcription_models
        parakeet_models = get_parakeet_transcription_models()
        parakeet_match_id = None
        for model_id, cfg in parakeet_models.items():
            if cfg.get("display_name") == selected_model or model_id == selected_model:
                parakeet_match_id = model_id
                break
        if parakeet_match_id is not None:
            try:
                from .main import app as _app
                cached = getattr(_app.state, "parakeet_transcription_service", None)
                if cached is not None:
                    return cached
            except Exception:
                cached = None

            from .services.transcription.backends.parakeet_service import ParakeetTranscriptionService
            _logger.info(
                f"Resolving Parakeet transcription service for model: "
                f"{selected_model} ({parakeet_match_id})"
            )
            service = ParakeetTranscriptionService(model_id=parakeet_match_id)
            try:
                from .main import app as _app
                _app.state.parakeet_transcription_service = service
            except Exception:
                pass
            return service
    except Exception as e:
        _logger.warning(f"Could not check API transcription preferences, falling back to local: {e}")

    try:
        from .main import app
        wake_word_service = getattr(app.state, "wake_word_service", None)
        if wake_word_service and wake_word_service.transcription_service:
            return wake_word_service.transcription_service
    except Exception as e:
        _logger.warning(f"Could not access shared transcription service: {e}")

    from .services.transcription.backends.huggingface_service import HuggingFaceTranscriptionService
    _logger.warning("No shared transcription service found, creating new instance")
    return HuggingFaceTranscriptionService()


def get_transcription_service(request: Request = None, websocket: WebSocket = None):
    """FastAPI dependency wrapper around resolve_transcription_service().

    Kept for backwards compatibility with Depends() injection. Delegates
    to resolve_transcription_service() which checks preferences each call.
    """
    return resolve_transcription_service()

@lru_cache()
def get_image_processor():
    """Get or create the image processor singleton.
    
    This service handles image processing with OCR and AI analysis.
    """
    # Import ImageProcessor here to avoid circular imports
    from .services.image_processing.image_processing_service import ImageProcessor
    
    # Get required dependencies
    model_service = get_model_service()
    model_usage_service = get_model_usage_service()
    storage_service = StorageService(development_mode=settings.DEBUG)
    
    # Create and return the image processor
    return ImageProcessor(
        model_service=model_service,
        storage_service=storage_service,
        development_mode=settings.DEBUG,
        model_usage_service=model_usage_service
    ) 