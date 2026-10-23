"""Best-effort contact identity observation extraction for Activity Capture.

This orchestrates the contact-candidate layer described in the Activity Contact
Enrichment plan. It is intentionally separate from
``AutomaticActivityProcessingService`` so that the main OCR/AI pipeline stays
focused and under the file-size limit, and so this safety-sensitive step can be
tested in isolation.

The whole step is best-effort: it is gated behind an off-by-default preference
and must never raise into the caller. A failure here leaves the activity
processing status untouched (COMPLETED) — discovering candidate contacts is
strictly additive and never blocks the core pipeline.
"""

import logging
import time
from datetime import datetime
from typing import Any, Optional

from api.core.models.model_types import ModelCapability
from api.core.knowledge.personalization.contact_candidate_extractor import (
    ContactCandidateExtractor,
)
from api.core.knowledge.personalization.contact_observations_manager import (
    ContactObservationsManager,
)

logger = logging.getLogger(__name__)


class ActivityContactObservationProcessor:
    """Extract and persist contact identity observations from a processed activity."""

    def __init__(self, knowledge_service, image_processor):
        self.knowledge_service = knowledge_service
        self.image_processor = image_processor
        self.extractor = ContactCandidateExtractor()
        self.observations_manager = ContactObservationsManager(knowledge_service.db_path)

    async def process(
        self,
        activity,
        ai_analysis_result: dict,
        *,
        model_stage_semaphore=None,
        run_id: Optional[str] = None,
    ) -> int:
        """Run gated, best-effort observation extraction for one activity.

        Returns the number of observations recorded (0 if disabled, skipped, or
        on any failure). Never raises.
        """
        activity_id = str(getattr(activity, "id", "unknown"))

        def _log(event: str, duration_ms: int = 0, **metadata: Any) -> None:
            fields = {
                "run_id": run_id or "activity-processing-direct",
                "activity_id": activity_id,
                "duration_ms": duration_ms,
                **metadata,
            }
            safe_fields = {
                key: value
                for key, value in fields.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
            logger.info(
                "%s %s",
                event,
                " ".join(f"{key}={value}" for key, value in safe_fields.items()),
            )

        started_at = time.perf_counter()
        try:
            if not self._extraction_enabled():
                _log("contact_enrichment_skipped", reason="preference_disabled")
                return 0

            extracted_text = ai_analysis_result.get("extracted_text")
            if not extracted_text or not extracted_text.strip():
                _log("contact_enrichment_skipped", reason="no_extracted_text")
                return 0

            window_title = self._window_title(activity)
            entities = self._entities(ai_analysis_result)
            async def _extract_candidates():
                model_started_at = time.perf_counter()
                model = await self._maybe_load_reasoning_model()
                _log(
                    "contact_enrichment_model_acquisition_completed",
                    int((time.perf_counter() - model_started_at) * 1000),
                    model_available=model is not None,
                )
                extraction_started_at = time.perf_counter()
                candidates = await self.extractor.extract_candidates(
                    extracted_text=extracted_text,
                    app_name=getattr(activity, "app_name", None),
                    window_title=window_title,
                    entities=entities,
                    source_activity_id=getattr(activity, "id", None),
                    model=model,
                )
                _log(
                    "contact_enrichment_candidate_extraction_completed",
                    int((time.perf_counter() - extraction_started_at) * 1000),
                    candidate_count=len(candidates),
                )
                return candidates

            if model_stage_semaphore is None:
                candidates = await _extract_candidates()
            else:
                async with model_stage_semaphore:
                    candidates = await _extract_candidates()

            recorded = 0
            writes_started_at = time.perf_counter()
            for candidate in candidates:
                stored = await self.observations_manager.record_observation(candidate)
                if stored is not None:
                    recorded += 1
            _log(
                "contact_enrichment_observation_writes_completed",
                int((time.perf_counter() - writes_started_at) * 1000),
                recorded_count=recorded,
            )

            metadata_started_at = time.perf_counter()
            await self._store_observation_metadata(activity, recorded)
            _log(
                "contact_enrichment_metadata_storage_completed",
                int((time.perf_counter() - metadata_started_at) * 1000),
            )

            if recorded:
                logger.info(
                    "🪪 Recorded %d contact identity observation(s) for activity %s",
                    recorded,
                    getattr(activity, "id", "unknown"),
                )
            _log(
                "contact_enrichment_completed",
                int((time.perf_counter() - started_at) * 1000),
                enabled=True,
                candidate_count=len(candidates),
                recorded_count=recorded,
            )
            return recorded

        except Exception as exc:  # noqa: BLE001 - best-effort, never fatal
            _log(
                "contact_enrichment_failed",
                int((time.perf_counter() - started_at) * 1000),
                exception_type=type(exc).__name__,
            )
            logger.warning(
                "Contact observation extraction failed for activity %s (non-fatal, %s)",
                getattr(activity, "id", "unknown"),
                type(exc).__name__,
            )
            return 0

    def _extraction_enabled(self) -> bool:
        try:
            from api.core.preferences.preferences_io import load_preferences
            preferences = load_preferences()
            return bool(preferences.activity_capture.contact_candidate_extraction_enabled)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Could not read contact extraction preference (%s)",
                type(exc).__name__,
            )
            return False

    def _window_title(self, activity) -> Optional[str]:
        window_title = getattr(activity, "window_title", None)
        if window_title:
            return window_title
        metadata = getattr(activity, "metadata", None)
        if isinstance(metadata, dict):
            return metadata.get("window_title")
        return None

    def _entities(self, ai_analysis_result: dict):
        analysis = ai_analysis_result.get("analysis")
        entities = getattr(analysis, "entities", None)
        if isinstance(entities, list):
            return entities
        return None

    async def _maybe_load_reasoning_model(self) -> Optional[Any]:
        """Best-effort reasoning model for the agentic stage.

        The reasoning model was just used for AI analysis, so the model usage
        service typically returns the cached instance. If acquisition fails for
        any reason, the extractor falls back to deterministic candidates only.
        """
        try:
            from api.core.preferences.preferences_io import load_preferences
            processing_model = load_preferences().activity_capture.processing_model
            return await self.image_processor._get_model_for_task(
                {ModelCapability.REASONING},
                model_id=processing_model,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Reasoning model unavailable for contact extraction (%s)",
                type(exc).__name__,
            )
            return None

    async def _store_observation_metadata(self, activity, recorded: int) -> None:
        try:
            await self.knowledge_service.update_activity_metadata(
                activity_id=activity.id,
                metadata={
                    "contact_observation_count": recorded,
                    "contact_observation_processed_at": datetime.now().isoformat(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Could not store contact observation metadata for activity %s (%s)",
                getattr(activity, "id", "unknown"),
                type(exc).__name__,
            )
