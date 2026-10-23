"""Runtime loop for ambient suggestions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import AmbientSuggestionSettings
from api.core.preferences.preferences_io import load_preferences
from api.core.services.model_service import ModelService
from api.services.websocket_connection_manager import broadcast_json_text

from .capture_service import AmbientSuggestionCaptureService
from .evaluator import AmbientSuggestionEvaluator
from .history_context import AmbientSuggestionHistoryContextService
from .models import AmbientSuggestionRecord
from .store import AmbientSuggestionStore

_runtime: Optional["AmbientSuggestionRuntime"] = None


class AmbientSuggestionRuntime:
    """Owns the ambient suggestion capture/evaluation loop."""

    def __init__(
        self,
        model_service: ModelService,
        capture_service: Optional[AmbientSuggestionCaptureService] = None,
        evaluator: Optional[AmbientSuggestionEvaluator] = None,
        store: Optional[AmbientSuggestionStore] = None,
        history_context_service: Optional[AmbientSuggestionHistoryContextService] = None,
    ) -> None:
        self.model_service = model_service
        self.capture_service = capture_service or AmbientSuggestionCaptureService()
        self.evaluator = evaluator or AmbientSuggestionEvaluator(model_service)
        self.store = store or AmbientSuggestionStore()
        self.history_context_service = history_context_service or AmbientSuggestionHistoryContextService(store=self.store)
        self.settings = load_preferences().ambient_suggestions
        self.task: Optional[asyncio.Task] = None
        self.last_capture_time: Optional[datetime] = None
        self.last_status_message: Optional[str] = None
        self.is_evaluating = False
        self.evaluation_started_at: Optional[datetime] = None
        self.last_evaluation_completed_at: Optional[datetime] = None
        self.next_evaluation_time: Optional[datetime] = None
        self.logger = api_logger.getChild("ambient_suggestion_runtime")

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        if not self.settings.enabled:
            self.logger.info("Ambient suggestions disabled; runtime loop not started")
            return
        self.next_evaluation_time = datetime.now()
        self.task = asyncio.create_task(self._run_loop())
        await self.broadcast_status_changed("started")

    async def stop(self) -> None:
        if not self.task:
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None
        self.next_evaluation_time = None
        await self.broadcast_status_changed("stopped")

    async def apply_settings(self, settings: AmbientSuggestionSettings) -> None:
        was_running = self.is_running()
        self.settings = settings
        if not settings.enabled:
            await self.stop()
        elif was_running:
            await self.stop()
            await self.start()
        await self.broadcast_status_changed("settings_applied")

    async def run_once(self) -> Optional[AmbientSuggestionRecord]:
        self.is_evaluating = True
        self.evaluation_started_at = datetime.now()
        self.next_evaluation_time = None
        self.last_status_message = "Evaluating current context"
        await self.broadcast_status_changed("evaluation_started")
        try:
            context = await self.capture_service.capture_current_context()
            self.last_capture_time = datetime.now()

            if context.app_name in set(self.settings.excluded_app_names):
                self.last_status_message = f"Skipped excluded app: {context.app_name}"
                self.logger.info(self.last_status_message)
                return None

            recent_suggestions, recent_activity_spans = await self.history_context_service.build_history_context(
                context=context,
                cooldown_minutes=self.settings.cooldown_minutes,
            )
            payload = await self.evaluator.evaluate(
                context,
                model_id=self.settings.evaluation_model,
                minimum_confidence=self.settings.minimum_confidence,
                allowed_capabilities=self.settings.enabled_capabilities,
                recent_suggestions=recent_suggestions,
                recent_activity_spans=recent_activity_spans,
            )
            if not payload.should_suggest or not payload.capability:
                self.last_status_message = "Evaluated: no useful help found"
                return None
            if payload.capability not in self.settings.enabled_capabilities:
                self.last_status_message = f"Evaluated: {payload.capability} is disabled"
                return None
            if payload.confidence < self.settings.minimum_confidence:
                self.last_status_message = "Evaluated: below confidence threshold"
                return None
            if self.store.should_suppress(
                content_fingerprint=context.content_fingerprint,
                suggestion_type=payload.suggestion_type,
                capability=payload.capability,
                cooldown_minutes=self.settings.cooldown_minutes,
            ):
                self.last_status_message = "Evaluated: similar suggestion recently handled"
                return None

            suggestion = self.store.create_suggestion(
                app_name=context.app_name,
                window_title=context.window_title,
                content_fingerprint=context.content_fingerprint,
                source_identifier=context.structured_context.get("source_identifier"),
                payload=payload,
            )
            self.last_status_message = "Suggestion created"
            await self.broadcast_suggestion(suggestion)
            return suggestion
        finally:
            self.is_evaluating = False
            self.last_evaluation_completed_at = datetime.now()
            await self.broadcast_status_changed("evaluation_completed")

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    def get_status(self) -> dict:
        return {
            "initialized": True,
            "enabled": self.settings.enabled,
            "is_running": self.is_running(),
            "frequency_minutes": self.settings.frequency_minutes,
            "frequency_seconds": self.settings.frequency_seconds,
            "evaluation_model": self.settings.evaluation_model,
            "mode": self.settings.mode,
            "enabled_capabilities": self.settings.enabled_capabilities,
            "auto_execute_capabilities": self.settings.auto_execute_capabilities,
            "minimum_confidence": self.settings.minimum_confidence,
            "cooldown_minutes": self.settings.cooldown_minutes,
            "allow_cloud_evaluation": self.settings.allow_cloud_evaluation,
            "is_evaluating": self.is_evaluating,
            "evaluation_started_at": self.evaluation_started_at.isoformat() if self.evaluation_started_at else None,
            "last_evaluation_completed_at": self.last_evaluation_completed_at.isoformat() if self.last_evaluation_completed_at else None,
            "next_evaluation_time": self.next_evaluation_time.isoformat() if self.next_evaluation_time else None,
            "last_capture_time": self.last_capture_time.isoformat() if self.last_capture_time else None,
            "open_suggestions_count": len(self.store.list_open_suggestions()),
            "last_status_message": self.last_status_message,
        }

    async def broadcast_suggestion(self, suggestion: AmbientSuggestionRecord) -> None:
        await broadcast_json_text(
            {
                "event_type": "ambient_suggestion_created",
                "suggestion": suggestion.model_dump(mode="json"),
            },
            log=self.logger,
        )

    async def broadcast_suggestion_updated(self, suggestion: AmbientSuggestionRecord) -> None:
        await broadcast_json_text(
            {
                "event_type": "ambient_suggestion_updated",
                "suggestion": suggestion.model_dump(mode="json"),
            },
            log=self.logger,
        )

    async def broadcast_status_changed(self, reason: str) -> None:
        try:
            await broadcast_json_text(
                {
                    "event_type": "ambient_suggestion_status_changed",
                    "status": self.get_status(),
                    "reason": reason,
                },
                log=self.logger,
            )
        except Exception as exc:
            self.logger.warning("Failed to broadcast ambient suggestion status: %s", exc, exc_info=True)

    async def _run_loop(self) -> None:
        self.logger.info("Ambient suggestion loop started")
        try:
            while self.settings.enabled:
                try:
                    await self.run_once()
                except Exception as exc:
                    self.logger.error("Ambient suggestion loop iteration failed: %s", exc, exc_info=True)
                interval_seconds = max(self.settings.frequency_seconds, 1.0)
                self.next_evaluation_time = datetime.now() + timedelta(seconds=interval_seconds)
                await self.broadcast_status_changed("next_evaluation_scheduled")
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            self.logger.info("Ambient suggestion loop canceled")
            raise


async def initialize_ambient_suggestion_runtime(model_service: ModelService) -> None:
    global _runtime
    if _runtime is None:
        _runtime = AmbientSuggestionRuntime(model_service)


async def cleanup_ambient_suggestion_runtime() -> None:
    global _runtime
    if _runtime is not None:
        await _runtime.stop()
    _runtime = None


def get_ambient_suggestion_runtime() -> Optional[AmbientSuggestionRuntime]:
    return _runtime
