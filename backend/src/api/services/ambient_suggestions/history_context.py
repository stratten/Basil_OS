"""Recent history packaging for ambient suggestion evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from api.core.logging.api_logger import api_logger

from .models import AmbientContextEnvelope, AmbientRecentActivitySpan, AmbientRecentSuggestionContext
from .store import AmbientSuggestionStore


class AmbientSuggestionHistoryContextService:
    """Build bounded, deterministic history context for the evaluator."""

    def __init__(
        self,
        *,
        store: AmbientSuggestionStore,
        knowledge_service: Optional[Any] = None,
        activity_lookback_minutes: float = 90.0,
        max_activity_captures: int = 12,
        max_recent_suggestions: int = 10,
        max_excerpt_chars_per_span: int = 700,
    ) -> None:
        self.store = store
        self.knowledge_service = knowledge_service
        self.activity_lookback_minutes = activity_lookback_minutes
        self.max_activity_captures = max_activity_captures
        self.max_recent_suggestions = max_recent_suggestions
        self.max_excerpt_chars_per_span = max_excerpt_chars_per_span
        self.logger = api_logger.getChild("ambient_suggestion_history_context")

    async def build_recent_suggestions(
        self,
        *,
        context: AmbientContextEnvelope,
        cooldown_minutes: float,
    ) -> list[AmbientRecentSuggestionContext]:
        return self.store.list_recent_suggestion_context(
            content_fingerprint=context.content_fingerprint,
            app_name=context.app_name,
            window_title=context.window_title,
            cooldown_minutes=cooldown_minutes,
            lookback_minutes=self.activity_lookback_minutes,
            limit=self.max_recent_suggestions,
        )

    async def build_recent_activity_spans(
        self,
        *,
        context: AmbientContextEnvelope,
    ) -> list[AmbientRecentActivitySpan]:
        knowledge_service = self._resolve_knowledge_service()
        if knowledge_service is None:
            return []

        now = datetime.now().astimezone()
        start = now - timedelta(minutes=self.activity_lookback_minutes)
        try:
            activities = await knowledge_service.search_activities(
                time_range={"start": start, "end": now},
                limit=self.max_activity_captures,
            )
        except Exception as exc:
            self.logger.warning("Failed to retrieve ambient history activities: %s", exc, exc_info=True)
            return []

        filtered = [
            activity
            for activity in activities
            if activity.id != context.capture_id
            and (activity.metadata or {}).get("capture_id") != context.capture_id
        ]
        ordered = sorted(filtered, key=lambda activity: activity.timestamp)
        return self._group_activity_spans(ordered)

    async def build_history_context(
        self,
        *,
        context: AmbientContextEnvelope,
        cooldown_minutes: float,
    ) -> tuple[list[AmbientRecentSuggestionContext], list[AmbientRecentActivitySpan]]:
        recent_suggestions = await self.build_recent_suggestions(
            context=context,
            cooldown_minutes=cooldown_minutes,
        )
        recent_activity_spans = await self.build_recent_activity_spans(context=context)
        return recent_suggestions, recent_activity_spans

    def _group_activity_spans(self, activities: list[Any]) -> list[AmbientRecentActivitySpan]:
        spans: list[AmbientRecentActivitySpan] = []
        current_items: list[Any] = []
        current_key: Optional[tuple[str, str]] = None

        for activity in activities:
            key = (activity.app_name or "Unknown", activity.window_title or "")
            if current_key is not None and key != current_key:
                spans.append(self._build_activity_span(current_items))
                current_items = []
            current_key = key
            current_items.append(activity)

        if current_items:
            spans.append(self._build_activity_span(current_items))
        return spans

    def _build_activity_span(self, activities: list[Any]) -> AmbientRecentActivitySpan:
        first = activities[0]
        last = activities[-1]
        excerpts: list[str] = []
        remaining_chars = self.max_excerpt_chars_per_span

        for activity in activities:
            excerpt = self._compact_excerpt(activity.extracted_text or "", remaining_chars)
            if not excerpt:
                continue
            excerpts.append(excerpt)
            remaining_chars -= len(excerpt)
            if remaining_chars <= 0:
                break

        return AmbientRecentActivitySpan(
            started_at=first.timestamp,
            ended_at=last.timestamp,
            app_name=first.app_name or "Unknown",
            window_title=first.window_title or "",
            capture_count=len(activities),
            activity_ids=[activity.id for activity in activities],
            text_excerpts=excerpts,
        )

    @staticmethod
    def _compact_excerpt(text: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        compacted = " ".join(text.split())
        return compacted[:max_chars]

    def _resolve_knowledge_service(self) -> Optional[Any]:
        if self.knowledge_service is not None:
            return self.knowledge_service
        try:
            from api.dependencies import get_sqlite_knowledge_service

            self.knowledge_service = get_sqlite_knowledge_service()
        except Exception as exc:
            self.logger.warning("Ambient history context could not access knowledge service: %s", exc)
            return None
        return self.knowledge_service
