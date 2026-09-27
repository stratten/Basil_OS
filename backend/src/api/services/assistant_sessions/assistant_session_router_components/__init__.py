"""Internal component modules for the AssistantSession HTTP router.

This package is an implementation detail of
``api.services.assistant_session.assistant_session_router``. Public consumers
of the AssistantSession feature should import ``router`` from
``api.services.assistant_session.assistant_session_router`` (the facade), not
from any module in this package.

The split exists so the facade stays narrow and each component has a single
responsibility:

* ``assistant_session_models``               -- Pydantic request/response models shared
                                     across the route families.
* ``assistant_session_state``                -- Process-singleton module-level state
                                     (``assistant_session_service_instance``,
                                     ``_assistant_output_history_service_instance``,
                                     ``model_unload_task``,
                                     ``active_ocr_tasks``) plus the
                                     dependency-injection providers used by
                                     FastAPI ``Depends(...)``.
* ``model_unload_scheduling``     -- Voice-listener-aware wrapper around
                                     ``schedule_model_unload`` for the
                                     transcription model lifecycle.
* ``start_session_pipeline``      -- OCR streaming generator for
                                     ``POST /start``.
* ``process_audio_pipeline``      -- Streaming + non-streaming orchestration
                                     for ``POST /process_audio``
                                     (transcription + LLM AssistantSession output +
                                     history persistence + model-unload
                                     scheduling).
* ``refinement_pipeline``         -- Streaming + non-streaming orchestration
                                     for ``POST /{session_id}/refine`` plus the
                                     session factory used by
                                     ``POST /rehydrate-from-history``.
* ``personalization_pipeline``    -- ``POST /save-sample`` orchestration
                                     plus signature-detection and
                                     contact-tracking helpers.
* ``route_session``               -- ``GET /ping``, ``POST /start``,
                                     ``DELETE /cancel/{session_id}``.
* ``route_assistant_session_input``              -- ``POST /process_audio/{session_id}``.
* ``route_refinement``            -- ``POST /{session_id}/refine``,
                                     ``POST /rehydrate-from-history/{assistant_output_id}``.
* ``route_personalization``       -- ``POST /save-sample/{session_id}``.

Each ``route_*`` module exposes a bare ``APIRouter()`` (no prefix) which the
facade aggregates under a single ``/assistant-sessions`` parent router.
"""
