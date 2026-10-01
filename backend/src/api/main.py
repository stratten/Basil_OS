from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import argparse
import os
import json
import platform
import sys
import logging
from pathlib import Path
import aiofiles
import asyncio
import signal

# Bundled-mode detection. Set to "true" by the PyInstaller launcher
# (`build/scripts/start_backend.sh`) so the same module can serve
# both dev (`uvicorn api.main:app`) and bundled (`python -m api.main`)
# entry points. Gates the `/shutdown` exit strategy and feeds the
# `bundled_mode` field on `/health` so the Swift client (and any curl
# smoke test) can confirm which environment it's talking to.
IS_BUNDLED = os.getenv('BASIL_BUNDLED', 'false').lower() == 'true'

# Parsed CLI args — populated only when this module is executed via
# `python -m api.main` (see `__main__` block at EOF). Stays `None` under
# `uvicorn api.main:app`, in which case `startup_event`'s port-file
# cascade falls through to the `APP_SUPPORT_DIR` / `settings.BASE_DIR`
# branches. Read via `globals().get('cli_args')` to mirror the
# basil_api.py pattern this is replacing.
cli_args = None

from .core.config.api_settings import settings
from .core.logging.api_logger import api_logger, setup_api_logger, redirect_stdio_to_logger
from .core.models.preferences import Preferences
from .core.runtime.validation_profile import (
    ValidationRuntimeProfile,
    is_validation_runtime,
)
from .core.models.model_manager import ModelManager
from .core.models.model_types import ModelCapability
from .core.models.model_downloader import ModelDownloader
from .routes.registry import register_application_routers
from .settings import get_models_dir
from .dependencies import get_model_service, get_sqlite_knowledge_service
from .core.security.backend_credentials import prepare_backend_credentials_for_startup
from .core.security.backend_request_guard import BackendRequestGuardMiddleware, resolve_loopback_bind_host
from .services.ios_pairing.bonjour_broadcaster import BonjourBroadcaster

# Import for Voice Listener
from api.services.wake_word import WakeWordService

# Configure logging first
logger = setup_api_logger(
    "api.main",
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)

# --- Redirect stdio to logger ---
# Call this very early. Pass the already configured api_logger (which is named "api.main")
# All print() statements from here on (if desktop logging is enabled) will go through api_logger.
redirect_stdio_to_logger(api_logger)
# --- End Redirect stdio ---

validation_runtime_profile = (
    ValidationRuntimeProfile.from_environment()
    if is_validation_runtime()
    else None
)

# --- Startup Status File Handling ---
STATUS_FILE_DIR = Path.home() / ".basil" / "runtime"
STATUS_FILE_PATH = STATUS_FILE_DIR / "app_startup_status.txt"

async def _update_startup_status_file(message: str):
    try:
        os.makedirs(STATUS_FILE_DIR, exist_ok=True)
        async with aiofiles.open(STATUS_FILE_PATH, mode="w", encoding="utf-8") as f:
            await f.write(message)
        logger.info(f"[STARTUP_SELF_STATUS] Updated status file to: '{message}'")
    except Exception as e:
        logger.error(f"[STARTUP_SELF_STATUS] Error writing status file {STATUS_FILE_PATH}: {e}")
# --- End Startup Status File Handling ---

# Global model infrastructure (initialized in startup)
model_manager = None
model_downloader = None
bonjour_broadcaster = BonjourBroadcaster(logger)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    debug=settings.DEBUG
)

# Starlette runs the last-added middleware outermost; registering the guard first keeps CORS outermost so guard rejections still carry CORS headers.
app.add_middleware(BackendRequestGuardMiddleware)
# Basil's bundled web views load from file:// and therefore send Origin: null.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_application_routers(app, logger)
if is_validation_runtime():
    from .routes.validation_routes import router as validation_router

    app.include_router(validation_router)

async def scan_models(models_dir: Path) -> None:
    """Scan for available models and log their status."""
    logger.info("Scanning for available models...")
    
    # Get all available models from downloader
    available_configs = model_downloader.get_available_models()
    for model_type, model_info in available_configs.items():
        for variant, config in model_info["variants"].items():
            # Capabilities are now strings directly from registry
            capabilities = config.get('capabilities', [])
    
    # Get installed models
    installed_models = model_downloader.get_installed_models()
    if installed_models:
        logger.info("Installed models:")
        for model_type, model_info in installed_models.items():
            logger.info(f"  {model_type}:")
            for variant, status in model_info["variants"].items():
                capabilities = status.get("capabilities", [])
                path = status.get("path", "Unknown location")
                logger.info(f"    - {variant}: {status.get('name', 'Unknown')} ({', '.join(capabilities)})")
                logger.info(f"      Location: {path}")
    else:
        logger.warning("No models currently installed")
    
    logger.info(f"Models directory: {models_dir}")
    
    # Check model directory structure
    if not models_dir.exists():
        logger.warning("Models directory does not exist yet")

@app.on_event("startup")
async def startup_event():
    """Initialize application state and log system information."""
    try:
        await _update_startup_status_file("Initializing backend...")
        try:
            credential_store = prepare_backend_credentials_for_startup()
            logger.info(f"🔐 Backend credentials ready at {credential_store.path}")
        except OSError as credential_error:
            logger.error(f"🚨 Backend credentials could not be prepared: {credential_error}", exc_info=True)
        logger.info("🔄 Startup event: beginning initialization")
        global model_manager, model_downloader

        # Reconcile the meeting transcript search index with on-disk meetings so
        # pre-existing recordings are searchable. Best-effort and offloaded to a
        # thread (synchronous disk + SQLite I/O); the indexer swallows its own
        # errors, and the extra guard keeps startup resilient regardless.
        try:
            import asyncio
            from .services.meetings import meeting_search_indexer
            await asyncio.to_thread(meeting_search_indexer.backfill_all)
        except Exception as e:
            logger.warning(f"Startup: meeting transcript search backfill failed: {e}")
        
        # Initialize Voice Listener Service
        # This service manages its own components like WakeWordDetector and AudioCapturer
        try:
            # Initialize model service FIRST so we have an LLM service for agent_tasks
            logger.info("Startup: Initializing model service for agent_task routing...")
            from .dependencies import get_model_service
            model_service = get_model_service()
            model_manager = model_service.model_manager
            model_downloader = model_service.model_downloader
            
            logger.info("Startup: Initializing VoiceListenerService...")
            
            # Gather existing Basil services for agent-task processing integration
            basil_services = {}
            try:
                # Import services that exist in the application
                from .services.capture.manual.capture_handler import CaptureHandler
                from .services.ocr.ocr_service import OCRService
                from .services.conversation.conversation_service import ConversationService
                from .services.assistant_sessions.assistant_session_service import AssistantSessionService
                from .services.window_capture.window_capture_service import WindowCaptureService
                from .services.transcription.backends.huggingface_service import HuggingFaceTranscriptionService
                
                # Use the model service that was just initialized above
                try: 
                    basil_services['window_capture'] = WindowCaptureService(model_manager, None)
                    logger.info("Startup: WindowCaptureService initialized for agent_tasks")
                except Exception as e: 
                    logger.warning(f"Startup: Could not initialize WindowCaptureService: {e}")
                try: 
                    basil_services['ocr'] = OCRService()
                    logger.info("Startup: OCRService initialized for agent_tasks")
                except Exception as e: 
                    logger.warning(f"Startup: Could not initialize OCRService: {e}")
                try: 
                    # Use the dependency injection function to get properly initialized service
                    from .dependencies import get_conversation_service
                    basil_services['conversation'] = get_conversation_service()
                    logger.info("Startup: ConversationService initialized for agent_tasks")
                except Exception as e: 
                    logger.warning(f"Startup: Could not initialize ConversationService: {e}")
                try: 
                    basil_services['assistant_session'] = AssistantSessionService()
                    logger.info("Startup: AssistantSessionService initialized for agent_tasks")
                except Exception as e: 
                    logger.warning(f"Startup: Could not initialize AssistantSessionService: {e}")
                try: 
                    basil_services['knowledge'] = get_sqlite_knowledge_service()
                    logger.info("Startup: SQLiteKnowledgeService initialized for agent_tasks")
                except Exception as e: 
                    logger.warning(f"Startup: Could not initialize SQLiteKnowledgeService: {e}")
                try: 
                    basil_services['capture_handler'] = CaptureHandler(model_manager)
                    logger.info("Startup: CaptureHandler initialized for agent_tasks")
                except Exception as e: 
                    logger.warning(f"Startup: Could not initialize CaptureHandler: {e}")
                logger.info(f"Startup: Initialized {len(basil_services)} Basil services for agent_task processing")
            except ImportError as e: 
                logger.warning(f"Startup: Could not import some Basil services for agent_tasks: {e}")
            
            # LLM service for agent-task routing (using the initialized model_manager)
            llm_service = model_manager
            if llm_service:
                logger.info("Startup: LLM service (model_manager) available for agent_task routing")
            else:
                logger.warning("Startup: Model manager (for LLM service) not available, agent_tasks may use mock routing")

            # Initialize Transcription Service for Voice Listener
            transcription_service_instance = None
            try:
                from .services.transcription.backends.huggingface_service import HuggingFaceTranscriptionService
                logger.info("Startup: Initializing HuggingFaceTranscriptionService for agent_tasks...")
                transcription_service_instance = HuggingFaceTranscriptionService()
                logger.info("Startup: HuggingFaceTranscriptionService instantiated (model will load lazily when needed).")
                # NOTE: Removed explicit model pre-loading here to implement lazy loading
                # Model will be loaded when first transcription request is made
                #
                # Parakeet selection is detected here for visibility only -- the
                # actual ParakeetTranscriptionService is constructed lazily by
                # `resolve_transcription_service()` / `get_transcription_service()`
                # on the first transcription request. We keep the HF instance
                # around as the fallback for any code path that reaches
                # `voice_listener_service.transcription_service` directly.
                try:
                    from .core.models.preferences import Preferences
                    from .core.models.models_registry import get_parakeet_transcription_models
                    _prefs = Preferences.load()
                    _selected = _prefs.models.transcription_model
                    _parakeet_models = get_parakeet_transcription_models()
                    if any(
                        cfg.get("display_name") == _selected or mid == _selected
                        for mid, cfg in _parakeet_models.items()
                    ):
                        logger.info(
                            f"Startup: Parakeet transcription model selected ('{_selected}') -- "
                            "Parakeet ONNX service will be built on first transcription request."
                        )
                except Exception as _parakeet_check_err:
                    logger.debug(
                        f"Startup: Parakeet selection check skipped: {_parakeet_check_err}"
                    )
            except Exception as e:
                logger.error(f"Startup: Critical error initializing HuggingFaceTranscriptionService: {e}", exc_info=True)

            # Update AssistantSession service to use shared transcription service
            if 'assistant_session' in basil_services and transcription_service_instance:
                try:
                    from .services.assistant_sessions.assistant_session_service import AssistantSessionService
                    basil_services['assistant_session'] = AssistantSessionService(
                        transcription_service=transcription_service_instance
                    )
                    logger.info("Startup: AssistantSessionService updated to use shared transcription service")
                except Exception as e:
                    logger.warning(f"Startup: Could not update AssistantSessionService with shared transcription: {e}")

            # Initialize VoiceListenerService with all dependencies
            logger.info("Startup: Initializing VoiceListenerService with all dependencies...")
            logger.info("🔍 MAIN_DEBUG: About to call VoiceListenerService constructor")
            logger.info(f"🔍 MAIN_DEBUG: WakeWordService class: {WakeWordService}")
            logger.info(f"🔍 MAIN_DEBUG: WakeWordService module: {WakeWordService.__module__}")
            
            # Get shared SQLite service for chain context building
            sqlite_service = get_sqlite_knowledge_service()

            try:
                from .services.agent_providers.runtime.process_supervisor import (
                    finalize_interrupted_provider_runs,
                )

                finalized_run_count = await finalize_interrupted_provider_runs(
                    provider_run_repository=sqlite_service.provider_run_repository,
                    provider_interaction_repository=sqlite_service.provider_interaction_repository,
                )
                if finalized_run_count:
                    logger.info(
                        "Startup: Finalized %s interrupted provider run(s)",
                        finalized_run_count,
                    )
            except Exception as error:
                logger.error(
                    "Startup: Failed to reconcile interrupted provider runs: %s",
                    error,
                    exc_info=True,
                )

            try:
                interrupted_count = await sqlite_service.agent_task_service.mark_interrupted_active_agent_tasks()
                if interrupted_count:
                    logger.info(
                        "Startup: Marked %s previously active agent task(s) as interrupted",
                        interrupted_count,
                    )
            except Exception as error:
                logger.error(
                    "Startup: Failed to reconcile interrupted agent tasks: %s",
                    error,
                    exc_info=True,
                )

            wake_word_service = WakeWordService(
                llm_service=llm_service,
                basil_services=basil_services,
                transcription_service=transcription_service_instance,
                db_service=sqlite_service
            )
            
            logger.info("🔍 MAIN_DEBUG: WakeWordService constructor completed")
            logger.info(f"🔍 MAIN_DEBUG: Instance created: {wake_word_service}")
            logger.info(f"🔍 MAIN_DEBUG: Instance type: {type(wake_word_service)}")
            
            app.state.wake_word_service = wake_word_service
            app.state.agent_task_submission_service = wake_word_service.agent_task_submission_service
            try:
                reconciled_delegation_count = await (
                    wake_word_service.agent_task_orchestrator.provider_delegation_result_bridge.reconcile_startup()
                )
                if reconciled_delegation_count:
                    logger.info(
                        "Startup: Reconciled %s delegated provider parent workflow(s)",
                        reconciled_delegation_count,
                    )
            except Exception as error:
                logger.error(
                    "Startup: Failed to reconcile delegated provider parent workflows: %s",
                    error,
                    exc_info=True,
                )
            logger.info("Startup: wake-word and agent-task submission services initialized and stored in app.state")

            if validation_runtime_profile is not None:
                from .services.validation.fixture_service import ValidationFixtureService

                fixture_service = ValidationFixtureService(
                    validation_runtime_profile,
                    sqlite_service,
                )
                await fixture_service.seed()
                app.state.validation_fixture_service = fixture_service
                logger.info("Startup: validation task fixtures seeded")

            # Initialize scheduled agent task runtime (missed-run recovery + enqueue active jobs).
            # Runs on the in-process asyncio runner now; no separate Huey worker involved.
            if validation_runtime_profile is None:
                try:
                    from .services.scheduled_agent_tasks import initialize_scheduled_agent_task_runtime

                    scheduled_init = await initialize_scheduled_agent_task_runtime()
                    logger.info(f"Startup: Scheduled agent task runtime initialized: {scheduled_init}")
                except Exception as scheduled_err:
                    logger.error(f"Startup: Failed to initialize scheduled agent task runtime: {scheduled_err}", exc_info=True)

                try:
                    from .services.agent_follow_ups import start_agent_follow_up_scheduler

                    follow_up_db = get_sqlite_knowledge_service()
                    follow_up_init = await start_agent_follow_up_scheduler(
                        repository=follow_up_db.agent_task_follow_up_repository,
                        chain_reader=follow_up_db,
                        submission_service=app.state.agent_task_submission_service,
                    )
                    logger.info(f"Startup: Agent follow-up scheduler started: {follow_up_init}")
                except Exception as follow_up_err:
                    logger.error(f"Startup: Failed to start agent follow-up scheduler: {follow_up_err}", exc_info=True)

            try:
                from .dependencies import get_todo_service
                from .services.todos.agent_task_bridge import (
                    TodoAgentTaskBridge,
                    ensure_todo_agent_task_callback_registered,
                    recover_todo_agent_task_attempts,
                    set_todo_agent_task_bridge,
                )

                todo_service = get_todo_service()
                app.state.todo_service = todo_service
                set_todo_agent_task_bridge(
                    TodoAgentTaskBridge(
                        todo_service=todo_service,
                        agent_task_service=get_sqlite_knowledge_service(),
                        agent_task_submission_service=app.state.agent_task_submission_service,
                    )
                )
                ensure_todo_agent_task_callback_registered(get_sqlite_knowledge_service())
                await recover_todo_agent_task_attempts(todo_service)
                logger.info("Startup: To-Do Agent Task bridge initialized")
            except Exception as todo_err:
                logger.error(
                    "Startup: Failed to initialize To-Do Agent Task bridge: %s",
                    todo_err,
                    exc_info=True,
                )

            try:
                from .services.conversation.conversation_agent_turn_lifecycle import (
                    ensure_conversation_agent_turn_callback_registered,
                )
                from .services.conversation.conversation_agent_narration_service import (
                    recover_conversation_agent_narrations,
                )

                ensure_conversation_agent_turn_callback_registered()
                logger.info("Startup: Conversation AgentTask lifecycle projection callback initialized")
                recovered_narration_count = await recover_conversation_agent_narrations()
                logger.info(
                    "Startup: Resumed %s interrupted Conversation Agent Task narration(s)",
                    recovered_narration_count,
                )
            except Exception as conversation_turn_callback_err:
                logger.error(
                    "Startup: Failed to initialize Conversation AgentTask lifecycle projection callback: %s",
                    conversation_turn_callback_err,
                    exc_info=True,
                )

            # Set the event loop reference for agent_task processing
            try:
                current_loop = asyncio.get_running_loop()
                app.state.wake_word_service.set_event_loop(current_loop)
                logger.info("Startup: Event loop reference set for agent_task processing")
            except Exception as e:
                logger.error(f"Startup: Failed to set event loop for voice listener service: {e}")
            
            # Validation keeps the real service graph for manual workflows but
            # never starts the persistent listener from copied preferences.
            if validation_runtime_profile is None:
                logger.info("Startup: Updating VoiceListenerService state from settings...")
                app.state.wake_word_service.update_listener_state_from_settings()
                logger.info("Startup: VoiceListenerService state updated.")
            else:
                logger.info("Startup: Voice listener startup disabled for validation runtime")
            
            # Log voice listener capabilities
            voice_status = app.state.wake_word_service.get_status()
            logger.info(f"Startup: Voice listener status - enabled: {voice_status.get('voice_listener_enabled')}, "
                       f"agent task processor ready: {voice_status.get('agent_task_processor_ready')}")
            
        except Exception as e:
            logger.error(f"🚨 Startup: Failed to initialize VoiceListenerService: {e}", exc_info=True)
            app.state.wake_word_service = None
            app.state.agent_task_submission_service = None
            await _update_startup_status_file(f"Error initializing voice listener: {str(e)[:50]}...")
        
        # Initialize Automatic Activity Services
        logger.info("Startup: Initializing Automatic Activity Services...")
        try:
            from .services.capture.automatic.activity_capture_runtime import initialize_automatic_activity_services
            from .dependencies import get_model_service, get_image_processor, get_knowledge_service
            
            # Get required dependencies for automatic activity services
            knowledge_service = get_knowledge_service()
            model_service = get_model_service()
            image_processor = get_image_processor()
            
            if validation_runtime_profile is None:
                await initialize_automatic_activity_services(knowledge_service, model_service, image_processor)
                logger.info("Startup: Automatic Activity Services initialized successfully")
            else:
                logger.info("Startup: Automatic Activity Services disabled for validation runtime")
        except Exception as e:
            logger.error(f"Startup: Failed to initialize Automatic Activity Services: {e}", exc_info=True)

        # Initialize Ambient Suggestion runtime
        logger.info("Startup: Initializing Ambient Suggestion runtime...")
        try:
            from .services.ambient_suggestions.runtime import initialize_ambient_suggestion_runtime
            from .dependencies import get_model_service

            if validation_runtime_profile is None:
                await initialize_ambient_suggestion_runtime(get_model_service())
                logger.info("Startup: Ambient Suggestion runtime initialized successfully")
            else:
                logger.info("Startup: Ambient Suggestion runtime disabled for validation runtime")
        except Exception as e:
            logger.error(f"Startup: Failed to initialize Ambient Suggestion runtime: {e}", exc_info=True)

        # Initialize Meeting Detection runtime (initialized, not auto-started;
        # the user manually initiates it like Proactive Suggestions).
        logger.info("Startup: Initializing Meeting Detection runtime...")
        try:
            from .services.meeting_detection.runtime import initialize_meeting_detection_runtime
            if validation_runtime_profile is None:
                await initialize_meeting_detection_runtime()
                logger.info("Startup: Meeting Detection runtime initialized successfully")
            else:
                logger.info("Startup: Meeting Detection runtime disabled for validation runtime")
        except Exception as e:
            logger.error(f"Startup: Failed to initialize Meeting Detection runtime: {e}", exc_info=True)
        
        # Log system information
        logger.info(f"Startup: Application '{settings.APP_NAME}' version {settings.API_VERSION}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Platform: {platform.platform()}")
        logger.info(f"Debug mode: {settings.DEBUG}")
        logger.info("Startup: Completed basic environment logging")
        
        await _update_startup_status_file("Initializing AI services...")
        # Model infrastructure already initialized above for agent_tasks
        logger.info("Startup: Model service already initialized for agent_task processing")
        
        await _update_startup_status_file("Loading preferences...")
        models_dir = get_models_dir()
        logger.info(f"Startup: Using models directory: {models_dir}")
        try:
            from .services.maintenance import (
                cleanup_legacy_memvid_data,
                prune_redundant_embedding_artifacts,
            )

            if validation_runtime_profile is None:
                embedding_cleanup = prune_redundant_embedding_artifacts(models_dir)
                legacy_memvid_cleanup = cleanup_legacy_memvid_data(delete=True)
                logger.info(
                    "Startup: storage cleanup complete: embedding=%s legacy_memvid=%s",
                    embedding_cleanup,
                    legacy_memvid_cleanup,
                )
            else:
                logger.info("Startup: shared-model cleanup disabled for validation runtime")
        except Exception as cleanup_exc:
            logger.warning("Startup: storage cleanup skipped: %s", cleanup_exc)
        
        # Explicitly retrieve and log hotkey settings for debugging
        logger.info("Startup: Loading preferences via load_preferences()")
        try:
            from .core.preferences.preferences_io import load_preferences
            logger.info("Startup: Beginning preferences load and hotkey logging")
            preferences = load_preferences()
            hotkey_settings = preferences.hotkeys
            logger.info(f"Startup: Preferences loaded, hotkey settings type: {type(hotkey_settings)}")
            
            # Log raw hotkey settings without accessing specific attributes
            logger.info(f"Raw hotkey settings data: {hotkey_settings}")
            if isinstance(hotkey_settings, dict):
                logger.info(f"Settings is a dictionary with keys: {list(hotkey_settings.keys())}")
            elif hasattr(hotkey_settings, "__dict__"):
                logger.info(f"Settings is an object with attributes: {vars(hotkey_settings)}")
            else:
                logger.info(f"Settings type: {type(hotkey_settings)}")
            
            logger.info("Hotkey settings successfully retrieved at startup")
            logger.info("========================================")
            
            # Initialize API models if they're enabled in preferences
            if preferences.models.use_api_models:
                logger.info("[API] API models are enabled in preferences, initializing providers...")
                from .core.preferences.preferences_io import save_preferences
                from config.api_keys import has_api_key
                
                # Logic similar to toggle_api_models but without changing the preference value
                if not (preferences.models.anthropic_enabled or preferences.models.openai_enabled):
                    # Enable Anthropic by default if we have a key
                    if has_api_key("anthropic"):
                        preferences.models.anthropic_enabled = True
                        logger.info("[API] Automatically enabling Anthropic provider at startup")
                    
                    # Enable OpenAI by default if we have a key
                    if has_api_key("openai"):
                        preferences.models.openai_enabled = True
                        logger.info("[API] Automatically enabling OpenAI provider at startup")
                    
                    # If providers were enabled, save the updated preferences
                    if preferences.models.anthropic_enabled or preferences.models.openai_enabled:
                        save_preferences(preferences)
                        logger.info("[API] Updated provider settings saved")
                
                # Log the final API model state
                logger.info(f"[API] API models enabled: {preferences.models.use_api_models}")
                logger.info(f"[API] Anthropic enabled: {preferences.models.anthropic_enabled}")
                logger.info(f"[API] OpenAI enabled: {preferences.models.openai_enabled}")
                
        except Exception as e:
            logger.error(f"Failed to retrieve settings at startup: {str(e)}", exc_info=True)
        
        logger.info("Startup: Completed preferences logging, about to scan models")
        
        # Log loaded preferences for model configuration
        await _update_startup_status_file("Configuring models...")
        logger.info("[API] Loaded model configuration:")
        logger.info(f"  Vision model: {preferences.models.vision_model}")
        logger.info(f"  Language model: {preferences.models.language_model}")
        logger.info(f"  Reasoning model: {preferences.models.reasoning_model}")
        logger.info(f"  Model persistence: {preferences.models.persistence_duration_display}")
        
        # Scan for available models
        logger.info("Startup: Beginning scan_models()")
        await _update_startup_status_file("Scanning available models...")
        await scan_models(models_dir)
        logger.info("Startup: Completed scan_models()")
        
        await _update_startup_status_file("Finalizing setup...")
        # Write port information to file. Priority cascade (highest first):
        #   1. `--port-file <path>` CLI arg (set when launched via
        #      `python -m api.main`; this is what the bundled launcher
        #      passes via `start_backend.sh`).
        #   2. `$APP_SUPPORT_DIR/server_port` (the bundled launcher exports
        #      `APP_SUPPORT_DIR` so the Swift client can locate the file
        #      from `~/Library/Application Support/Basil/...`).
        #   3. Legacy `settings.BASE_DIR/.server_port` (dev fallback;
        #      `dev.sh` reads `../.server_port` relative to its
        #      own cwd, which resolves to the same path).
        # The actual port value prefers the CLI override (when nonzero) over
        # `settings.PORT` so `--port 0` (dynamic) and `--port N` both work.
        logger.info("Startup: Writing server port to file")
        current_cli_args = globals().get('cli_args')
        actual_port_to_write = (
            current_cli_args.port
            if current_cli_args and getattr(current_cli_args, 'port', 0) != 0
            else settings.PORT
        )

        if validation_runtime_profile is not None:
            port_file_path = validation_runtime_profile.session_root / "backend.port"
            port_file_path.write_text(str(actual_port_to_write))
            logger.info(f"Startup: validation server port written to {port_file_path}")
        elif current_cli_args and getattr(current_cli_args, 'port_file', None):
            port_file_path = Path(current_cli_args.port_file)
            port_file_path.parent.mkdir(parents=True, exist_ok=True)
            port_file_path.write_text(str(actual_port_to_write))
            logger.info(f"Startup: Server port {actual_port_to_write} written to {port_file_path}")
        else:
            app_support_dir = os.environ.get("APP_SUPPORT_DIR")
            if app_support_dir:
                port_file_path = Path(app_support_dir) / "server_port"
                try:
                    Path(app_support_dir).mkdir(parents=True, exist_ok=True)
                    port_file_path.write_text(str(actual_port_to_write))
                    logger.info(f"Startup: --port-file not provided. Wrote to {port_file_path} (APP_SUPPORT_DIR)")
                except Exception as port_write_exc:
                    logger.error(f"Startup: Failed writing port to APP_SUPPORT_DIR ({app_support_dir}): {port_write_exc}")
            else:
                base_dir_for_fallback = (
                    settings.BASE_DIR
                    if hasattr(settings, 'BASE_DIR')
                    else Path(__file__).resolve().parent.parent
                )
                legacy_port_file = base_dir_for_fallback / ".server_port"
                legacy_port_file.write_text(str(actual_port_to_write))
                logger.warning(f"Startup: --port-file not provided and APP_SUPPORT_DIR missing. Fallback port file at {legacy_port_file}")

        logger.info(f"Startup: Server listening on {settings.HOST}:{actual_port_to_write}")
        if validation_runtime_profile is None and settings.BONJOUR_BROADCAST:
            bonjour_broadcaster.start(port=actual_port_to_write)

        # Any transcription rows that were still ``pending`` when the
        # previous process exited (crash, forced quit, OS restart) are
        # now orphaned -- nothing is transcribing them. Flip them to
        # ``failed`` so the UI surfaces a Retry button instead of
        # showing an eternal "Transcribing…" state.
        try:
            from .services.transcription.processing.transcription_lifecycle import (
                sweep_stale_pending_rows,
            )
            await sweep_stale_pending_rows()
        except Exception as sweep_exc:
            logger.warning(f"Startup: transcription pending-row sweep failed: {sweep_exc}")

        # In-process replacements for the deleted Huey layer. Both are owned
        # by the FastAPI app and live on `app.state` so routes
        # (`routes/model_routes/predefined_routes.py`, `routes/onboarding.py`) and the capture
        # management service can reach them via `request.app.state.*`.
        try:
            from .core.services.model_download_manager import DownloadManager
            from .services.maintenance import (
                CaptureCleanupScheduler,
                register_capture_cleanup_scheduler,
                cleanup_huey_orphans,
            )
            from .services.memory.intelligence_scheduler import get_memory_intelligence_scheduler

            # One-shot Huey-era leftover purge before any new state is built.
            # Idempotent + best-effort; never raises. Use the canonical model
            # directory helper so cleanup, downloads, and runtime loading agree.
            if validation_runtime_profile is None:
                try:
                    cleanup_huey_orphans(models_dir=get_models_dir())
                except Exception as orphan_exc:
                    logger.debug(f"Startup: orphan cleanup skipped: {orphan_exc}")

            app.state.download_manager = DownloadManager(
                model_downloader=model_service.model_downloader
            )
            app.state.capture_cleanup_scheduler = CaptureCleanupScheduler()
            register_capture_cleanup_scheduler(app.state.capture_cleanup_scheduler)
            if validation_runtime_profile is None:
                await app.state.capture_cleanup_scheduler.start()
            app.state.memory_intelligence_scheduler = get_memory_intelligence_scheduler()
            if validation_runtime_profile is None:
                await app.state.memory_intelligence_scheduler.start()
            from .services.zettel.scheduler import get_zettel_scheduler
            from .services.zettel.narrative_scheduler import (
                get_zettel_narrative_scheduler,
            )

            app.state.zettel_scheduler = get_zettel_scheduler()
            if validation_runtime_profile is None:
                await app.state.zettel_scheduler.start()
            app.state.zettel_narrative_scheduler = get_zettel_narrative_scheduler()
            if validation_runtime_profile is None:
                await app.state.zettel_narrative_scheduler.start()
            from .services.retrieval.index_runtime import get_retrieval_index_runtime

            app.state.retrieval_index_runtime = get_retrieval_index_runtime()
            if validation_runtime_profile is None:
                await app.state.retrieval_index_runtime.start()
            logger.info(
                "Startup: DownloadManager + CaptureCleanupScheduler + MemoryIntelligenceScheduler attached to app.state"
            )
        except Exception as svc_exc:
            logger.error(
                f"Startup: failed to initialize download/maintenance services: {svc_exc}",
                exc_info=True,
            )

        await _update_startup_status_file("Launching interface...")
    except Exception as e:
        logger.error(f"🚨 Startup event error: {e}", exc_info=True)
        await _update_startup_status_file(f"Error during startup: {str(e)[:100]}...")

@app.on_event("shutdown")
async def shutdown_event():
    """Perform cleanup tasks on application shutdown."""
    logger.info("💤 Shutdown event: beginning cleanup")
    try:
        from .dependencies import _local_preview_registry as _preview_registry_snapshot
        from .services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher import (
            LocalPreviewServerLauncher,
        )

        if _preview_registry_snapshot is not None:
            await LocalPreviewServerLauncher(_preview_registry_snapshot).stop_all_sessions()
        logger.info("Shutdown: Local web preview sessions terminated")
    except Exception as exc:
        logger.error("Shutdown: Error terminating local web preview sessions: %s", exc, exc_info=True)
    try:
        from .dependencies import get_conversation_service

        await get_conversation_service().shutdown_background_tasks()
        logger.info("Shutdown: Conversation background tasks drained")
    except Exception as exc:
        logger.error("Shutdown: Error draining Conversation background tasks: %s", exc, exc_info=True)
    try:
        from .services.todos.agent_task_bridge import (
            shutdown_todo_agent_task_finalizers,
        )

        await shutdown_todo_agent_task_finalizers()
        logger.info("Shutdown: To-Do Agent Task finalizers drained")
    except Exception as exc:
        logger.error(
            "Shutdown: Error draining To-Do Agent Task finalizers: %s",
            exc,
            exc_info=True,
        )
    if settings.BONJOUR_BROADCAST:
        bonjour_broadcaster.stop()
    
    # Stop wake-word/audio lifecycle service
    if hasattr(app.state, 'wake_word_service') and app.state.wake_word_service is not None:
        try:
            logger.info("Shutdown: Stopping wake-word service...")
            
            # Cancel any active agent-task capture tasks
            if hasattr(app.state.wake_word_service, '_agent_task_capture_task') and app.state.wake_word_service._agent_task_capture_task:
                app.state.wake_word_service._agent_task_capture_task.cancel()
                logger.info("Shutdown: wake-word agent-task capture task canceled.")
            
            # Stop the listener
            app.state.wake_word_service.stop_listening()
            logger.info("Shutdown: wake-word service stopped.")
        except Exception as e:
            logger.error(f"🚨 Shutdown: Error stopping wake-word service: {e}", exc_info=True)
    
    # Cleanup Automatic Activity Services
    logger.info("Shutdown: Cleaning up Automatic Activity Services...")
    try:
        from .services.capture.automatic.activity_capture_runtime import cleanup_automatic_activity_services
        await cleanup_automatic_activity_services()
        logger.info("Shutdown: Automatic Activity Services cleaned up successfully.")
    except Exception as e:
        logger.error(f"🚨 Shutdown: Error cleaning up Automatic Activity Services: {e}", exc_info=True)

    # Cleanup Ambient Suggestion runtime
    logger.info("Shutdown: Cleaning up Ambient Suggestion runtime...")
    try:
        from .services.ambient_suggestions.runtime import cleanup_ambient_suggestion_runtime
        await cleanup_ambient_suggestion_runtime()
        logger.info("Shutdown: Ambient Suggestion runtime cleaned up successfully.")
    except Exception as e:
        logger.error(f"🚨 Shutdown: Error cleaning up Ambient Suggestion runtime: {e}", exc_info=True)

    # Cleanup Meeting Detection runtime
    logger.info("Shutdown: Cleaning up Meeting Detection runtime...")
    try:
        from .services.meeting_detection.runtime import cleanup_meeting_detection_runtime
        await cleanup_meeting_detection_runtime()
        logger.info("Shutdown: Meeting Detection runtime cleaned up successfully.")
    except Exception as e:
        logger.error(f"🚨 Shutdown: Error cleaning up Meeting Detection runtime: {e}", exc_info=True)

    # Cancel any in-flight scheduled-agent-task timers so they don't log
    # spurious CancelledError noise on shutdown. Persistence is in SQLite,
    # not in these in-memory tasks, so canceling them is safe — recovery
    # on the next startup will re-install timers from the database.
    try:
        from .services.scheduled_agent_tasks import (
            get_async_scheduled_agent_task_runner,
            shutdown_scheduled_agent_task_runtime,
        )

        # Stop the wall-clock reconciler first so it doesn't tick mid-
        # shutdown and re-arm a timer we're about to cancel. Then drop
        # the per-task asyncio timers themselves.
        await shutdown_scheduled_agent_task_runtime()
        get_async_scheduled_agent_task_runner().cancel_all()
        logger.info("Shutdown: AsyncScheduledAgentTaskRunner canceled all in-flight tasks")
    except Exception as e:
        logger.error(f"🚨 Shutdown: Error canceling scheduled-agent-task runner: {e}", exc_info=True)

    try:
        from .services.agent_follow_ups import stop_agent_follow_up_scheduler

        await stop_agent_follow_up_scheduler()
        logger.info("Shutdown: Agent follow-up scheduler stopped")
    except Exception as e:
        logger.error(f"🚨 Shutdown: Error stopping agent follow-up scheduler: {e}", exc_info=True)

    # Stop the in-process model download manager. Each in-flight DownloadEntry
    # has its asyncio.Event.set() and its background asyncio.Task .cancel()'d;
    # the manager awaits the gather() so partial-download HF cache state is
    # consistent on the next launch (snapshot_download(resume_download=True)
    # picks up where it left off). Replaces the prior Huey worker SIGTERM/
    # SIGKILL dance + PID-file scrubbing.
    download_manager = getattr(app.state, "download_manager", None)
    if download_manager is not None:
        try:
            await download_manager.shutdown()
            logger.info("Shutdown: DownloadManager drained")
        except Exception as e:
            logger.error(f"🚨 Shutdown: DownloadManager.shutdown failed: {e}", exc_info=True)

    # Stop the asyncio capture-cleanup scheduler. Replaces the Huey periodic
    # task `reasoning_capture_cleanup_task`; persistence (next-run time,
    # enabled flag) lives in `reasoning_settings.json`, so canceling the
    # in-flight task is safe — startup re-reads the config and re-arms.
    capture_cleanup_scheduler = getattr(app.state, "capture_cleanup_scheduler", None)
    if capture_cleanup_scheduler is not None:
        try:
            await capture_cleanup_scheduler.stop()
            logger.info("Shutdown: CaptureCleanupScheduler stopped")
        except Exception as e:
            logger.error(f"🚨 Shutdown: CaptureCleanupScheduler.stop failed: {e}", exc_info=True)
        finally:
            from .services.maintenance import register_capture_cleanup_scheduler

            register_capture_cleanup_scheduler(None)

    memory_intelligence_scheduler = getattr(app.state, "memory_intelligence_scheduler", None)
    if memory_intelligence_scheduler is not None:
        try:
            await memory_intelligence_scheduler.stop()
            logger.info("Shutdown: MemoryIntelligenceScheduler stopped")
        except Exception as e:
            logger.error(f"🚨 Shutdown: MemoryIntelligenceScheduler.stop failed: {e}", exc_info=True)

    zettel_scheduler = getattr(app.state, "zettel_scheduler", None)
    if zettel_scheduler is not None:
        try:
            await zettel_scheduler.stop()
            logger.info("Shutdown: ZettelScheduler stopped")
        except Exception as e:
            logger.error(f"🚨 Shutdown: ZettelScheduler.stop failed: {e}", exc_info=True)

    zettel_narrative_scheduler = getattr(app.state, "zettel_narrative_scheduler", None)
    if zettel_narrative_scheduler is not None:
        try:
            await zettel_narrative_scheduler.stop()
            logger.info("Shutdown: ZettelNarrativeScheduler stopped")
        except Exception as e:
            logger.error(f"🚨 Shutdown: ZettelNarrativeScheduler.stop failed: {e}", exc_info=True)

    retrieval_index_runtime = getattr(app.state, "retrieval_index_runtime", None)
    if retrieval_index_runtime is not None:
        try:
            await retrieval_index_runtime.stop()
            logger.info("Shutdown: RetrievalIndexRuntime stopped")
        except Exception as e:
            logger.error(f"🚨 Shutdown: RetrievalIndexRuntime.stop failed: {e}", exc_info=True)

    try:
        from .core.models.reasoning.llama_cpp_model import shutdown_cached_llama_cpp_models

        shutdown_cached_llama_cpp_models()
        logger.info("Shutdown: cached llama.cpp models closed")
    except Exception as e:
        logger.error(f"🚨 Shutdown: Error closing cached llama.cpp models: {e}", exc_info=True)

    # Remove transient state files. Port file removal lets the next launch
    # claim a fresh port without confusing the Swift client into reading a
    # stale value mid-startup. The startup status file has the same lifecycle.
    cleanup_files = [
        Path("../.server_port"),
        settings.BASE_DIR / ".server_port",
        STATUS_FILE_PATH,
    ]
    for file_path in cleanup_files:
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"🗑️ Removed state file: {file_path}")
        except Exception as e:
            logger.error(f"❌ Error removing state file {file_path}: {e}", exc_info=True)

    logger.info("✅ Shutdown event completed.")

def task_name(task: asyncio.Task) -> str:
    """Helper function to get a descriptive name for a task for logging."""
    try:
        # Try to get the coroutine's name
        return task.get_coro().__qualname__
    except Exception:
        # Fallback if the coroutine or its name isn't accessible
        return str(task)

# Response Models for health/shutdown endpoints
class HealthCheckResponse(BaseModel):
    """Response model for health check endpoint.

    Field shape mirrors the former `BundledHealthCheckResponse` in
    `basil_api.py` so the bundled and dev entry points return identical
    JSON. The Swift client (`AppDelegate_Backend.swift::isBackendHealthy`)
    only checks that the response parses as `[String: Any]` — extra fields
    are tolerated — but emitting the same shape from both paths keeps
    curl smoke tests and any future strict decoder honest.

    `download_manager` / `capture_cleanup_scheduler` replaced the legacy
    `huey_worker` / `huey_task_system` strings in step 1.4.10 of the
    Huey-removal plan; they expose at-a-glance status of the in-process
    services attached to `app.state` during startup.
    """
    status: str
    version: str
    debug_mode: bool
    port: int
    python_version: str
    platform: str
    download_manager: str
    capture_cleanup_scheduler: str
    memory_intelligence_scheduler: str
    zettel_scheduler: str
    zettel_narrative_scheduler: str
    bundled_mode: bool

class ShutdownResponse(BaseModel):
    """Response model for shutdown endpoint."""
    message: str

@app.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint."""
    try:
        dm = getattr(app.state, "download_manager", None)
        ccs = getattr(app.state, "capture_cleanup_scheduler", None)
        intelligence_scheduler = getattr(app.state, "memory_intelligence_scheduler", None)
        dm_status = "ready" if dm is not None else "not initialized"
        # `_task` is the asyncio.Task created in `CaptureCleanupScheduler.start()`;
        # checking `done()` distinguishes "running" from "crashed/exited".
        if ccs is None:
            ccs_status = "not initialized"
        else:
            task = getattr(ccs, "_task", None)
            ccs_status = "running" if (task is not None and not task.done()) else "stopped"
        # Both schedulers report the same LoopStatus shape, so the derivation
        # is shared rather than written out twice.
        def loop_status(scheduler) -> str:
            if scheduler is None:
                return "not initialized"
            state = scheduler.get_status()
            if state.last_error:
                return f"error: {state.last_error}"
            if state.is_running_now:
                return "running sweep"
            return "running" if state.is_running else "stopped"

        intelligence_status = loop_status(intelligence_scheduler)
        zettel_status = loop_status(getattr(app.state, "zettel_scheduler", None))
        zettel_narrative_status = loop_status(
            getattr(app.state, "zettel_narrative_scheduler", None)
        )

        return HealthCheckResponse(
            status="healthy",
            version=settings.API_VERSION,
            debug_mode=settings.DEBUG,
            port=settings.PORT,
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            download_manager=dm_status,
            capture_cleanup_scheduler=ccs_status,
            memory_intelligence_scheduler=intelligence_status,
            zettel_scheduler=zettel_status,
            zettel_narrative_scheduler=zettel_narrative_status,
            bundled_mode=IS_BUNDLED,
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/shutdown", response_model=ShutdownResponse)
async def shutdown() -> ShutdownResponse:
    """Initiates server shutdown.

    Bundled mode (PyInstaller frozen binary launched by
    `start_backend.sh`): hard-exits via `os._exit(0)` after a 0.1s
    `call_later` so the HTTP response gets flushed first. PyInstaller
    bundles run as a single process whose lifecycle the Swift client
    owns; SIGINT into uvicorn there can wedge on threading-only
    cleanup paths and leave an orphan python process behind, which the
    Phase 2 validation gate explicitly forbids.

    Dev mode: SIGINT to the current PID so uvicorn runs its full
    lifespan teardown (firing `shutdown_event`, draining
    `DownloadManager`, stopping `CaptureCleanupScheduler`, etc.).
    """
    logger.info(
        f"🛑 HTTP /shutdown endpoint called. Mode: {'bundled (os._exit)' if IS_BUNDLED else 'dev (SIGINT)'}"
    )

    if IS_BUNDLED:
        asyncio.get_event_loop().call_later(0.1, lambda: os._exit(0))
        return ShutdownResponse(message="Shutdown initiated. Application will terminate.")

    try:
        pid = os.getpid()
        os.kill(pid, signal.SIGINT)
        logger.info(f"✅ SIGINT sent to process {pid} to initiate graceful shutdown.")
        return ShutdownResponse(message="Shutdown initiated. Uvicorn will now perform graceful cleanup.")
    except Exception as e:
        logger.error(f"🚨 Error sending SIGINT to initiate shutdown: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error initiating shutdown: {str(e)}")

# Main execution block. Reachable via `python -m api.main ...` (the
# bundled launcher path after Phase 2.3) and `python backend/src/api/main.py`.
# Dev still launches via `uvicorn api.main:app` from `dev.sh`,
# in which case this block does NOT run and `cli_args` stays `None`.
if __name__ == "__main__":
    import uvicorn

    def _parse_and_set_global_args() -> None:
        """Mirror of `basil_api.py::_parse_and_set_global_args`.

        Sets the module-level `cli_args` global so `startup_event`'s
        port-file cascade can pick up `--port-file` / `--port` without
        threading them through FastAPI dependency injection.
        """
        default_host = settings.HOST
        default_port = settings.PORT
        default_log_level = getattr(settings, 'LOG_LEVEL', 'info').lower()
        default_workers = getattr(settings, 'UVICORN_WORKERS', 1)

        parser = argparse.ArgumentParser(description="Basil Backend API Server")
        parser.add_argument("--host", type=str, default=default_host, help="Host to bind")
        parser.add_argument("--port", type=int, default=default_port, help="Port to bind (0 for dynamic)")
        parser.add_argument("--port-file", type=str, default=None, help="File to write the actual listening port to")
        parser.add_argument(
            "--log-level",
            type=str,
            default=default_log_level,
            choices=['debug', 'info', 'warning', 'error', 'critical'],
            help="Logging level for Uvicorn",
        )
        parser.add_argument("--workers", type=int, default=default_workers, help="Number of Uvicorn workers")

        globals()['cli_args'] = parser.parse_args()

    _parse_and_set_global_args()

    main_cli_args = globals().get('cli_args')
    selected_host = resolve_loopback_bind_host(
        main_cli_args.host if main_cli_args else settings.HOST,
        allow_lan_bind=settings.ALLOW_LAN_BIND,
    )
    selected_port = main_cli_args.port if main_cli_args else settings.PORT
    selected_log_level = (
        main_cli_args.log_level.lower()
        if main_cli_args
        else getattr(settings, 'LOG_LEVEL', 'info').lower()
    )

    logger.info(
        f"__main__: launching uvicorn on host={selected_host}, port={selected_port}, "
        f"log_level={selected_log_level}, bundled={IS_BUNDLED}"
    )
    # ws_ping_interval/ws_ping_timeout default to 20s each. The live-transcription
    # event loop can be briefly busy (model acquisition, CPU inference), and a
    # missed pong under the 20s default closes the socket with a 1011 keepalive
    # timeout mid-meeting. Widen the window so a short stall does not drop a live
    # socket, while still reaping genuinely dead connections.
    uvicorn.run(
        app,
        host=selected_host,
        port=selected_port,
        log_level=selected_log_level,
        ws_ping_interval=30,
        ws_ping_timeout=60,
    )