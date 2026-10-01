"""Runtime loop for mechanical meeting detection.

Deliberately mirrors the *shape* of ``ambient_suggestions.runtime`` (singleton,
``start``/``stop``/``apply_settings``/``run_once``, ``_run_loop`` on a cadence)
but shares nothing else: no LLM, no store, no record model, no capability list.
Each tick is a cheap probe of the client's meeting-app audio activity plus an
optional calendar read; detection policy (rising/falling edges, cooldown,
calendar gating, prompt-vs-auto-start) lives here in cross-platform Python.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import MeetingDetectionSettings
from api.core.preferences.preferences_io import load_preferences
from api.services.websocket_connection_manager import broadcast_json_text

from .audio_activity_bridge import request_swift_audio_probe
from .calendar_event_bridge import request_swift_calendar_probe

_runtime: Optional["MeetingDetectionRuntime"] = None

class MeetingDetectionRuntime:
    """Owns the mechanical meeting-detection probe loop."""

    def __init__(self) -> None:
        self.settings: MeetingDetectionSettings = load_preferences().meeting_detection
        self.task: Optional[asyncio.Task] = None
        self.logger = api_logger.getChild("meeting_detection_runtime")

        # Edge-detection state.
        self._active_bundle_ids: set[str] = set()
        self._missing_counts: Dict[str, int] = {}
        # bundle_id -> datetime a detection was last surfaced (cooldown gate).
        self._last_surfaced: Dict[str, datetime] = {}
        # calendar_event_id -> datetime a join prompt was last surfaced.
        self._surfaced_calendar_event_ids: Dict[str, datetime] = {}
        # calendar_event_id -> unix timestamp the backing event ends, for
        # backend-driven auto-dismiss of stale calendar-sourced join prompts.
        self._surfaced_calendar_event_end_times: Dict[str, float] = {}
        self._ignored_calendar_event_ids: set[str] = set()

        self.last_probe_time: Optional[datetime] = None
        self.last_status_message: Optional[str] = None
        self.next_probe_time: Optional[datetime] = None

    # MARK: - Lifecycle

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        if not self.settings.enabled:
            self.logger.info("Meeting detection disabled; runtime loop not started")
            return
        self.next_probe_time = datetime.now()
        self.task = asyncio.create_task(self._run_loop())
        self.logger.info("Meeting detection loop starting (poll=%.1fs, mode=%s)", self.settings.poll_seconds, self.settings.mode)

    async def stop(self) -> None:
        if not self.task:
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None
        self.next_probe_time = None
        # Reset edge state so a restart re-surfaces an in-progress call.
        self._active_bundle_ids.clear()
        self._missing_counts.clear()
        self._surfaced_calendar_event_ids.clear()
        self._surfaced_calendar_event_end_times.clear()
        self._ignored_calendar_event_ids.clear()
        self.logger.info("Meeting detection loop stopped")

    async def apply_settings(self, settings: MeetingDetectionSettings) -> None:
        self.settings = settings
        if not settings.enabled:
            await self.stop()

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    # MARK: - Detection

    async def run_once(self) -> None:
        """Probe the client once and apply calendar/audio detection policy."""
        self.last_probe_time = datetime.now()

        await self._expire_stale_calendar_prompts()

        joinable_events = await self._probe_calendar_events()
        await self._surface_joinable_calendar_events(joinable_events)

        probe = await request_swift_audio_probe(self.settings.excluded_bundle_ids)
        if not probe.get("success"):
            self.last_status_message = probe.get("message") or "Probe failed"
            self.logger.debug("Meeting probe unsuccessful: %s", self.last_status_message)
            return

        active_apps: List[dict] = probe.get("active_meeting_apps") or []
        calendar_event: Optional[dict] = probe.get("current_calendar_event")
        self.logger.debug("Audio probe returned %d active meeting app(s)", len(active_apps))

        # Filter out excluded apps by name.
        excluded = set(self.settings.excluded_app_names)
        active_apps = [a for a in active_apps if a.get("name") not in excluded]

        # Calendar gate: when required, only actionable calendar events with
        # call/join info qualify (suppresses generic calendar blocks).
        calendar_gated_out = (
            self.settings.require_calendar_match
            and (not calendar_event or calendar_event.get("has_call_info") is not True)
        )
        eligible_apps = [] if calendar_gated_out else active_apps

        eligible_ids = {a.get("bundle_id") for a in eligible_apps if a.get("bundle_id")}
        apps_by_id = {a.get("bundle_id"): a for a in eligible_apps if a.get("bundle_id")}

        rising = eligible_ids - self._active_bundle_ids
        still_active = eligible_ids & self._active_bundle_ids
        possibly_gone = self._active_bundle_ids - eligible_ids

        # Reset debounce for apps still producing audio.
        for bundle_id in still_active:
            self._missing_counts.pop(bundle_id, None)

        # Rising edges: surface (respecting cooldown).
        for bundle_id in rising:
            app = apps_by_id.get(bundle_id, {})
            if self._is_in_cooldown(bundle_id):
                self.last_status_message = f"Cooldown active for {app.get('name', bundle_id)}"
                self.logger.debug(self.last_status_message)
            else:
                await self._surface_detected(app, calendar_event)
                self._last_surfaced[bundle_id] = datetime.now()
            self._active_bundle_ids.add(bundle_id)
            self._missing_counts.pop(bundle_id, None)

        # Falling edges: debounce via the configured inactivity timeout, then
        # (if enabled) surface an end.
        end_ticks = self._end_debounce_ticks()
        for bundle_id in list(possibly_gone):
            count = self._missing_counts.get(bundle_id, 0) + 1
            self._missing_counts[bundle_id] = count
            if count >= end_ticks:
                self._active_bundle_ids.discard(bundle_id)
                self._missing_counts.pop(bundle_id, None)
                if self.settings.auto_end:
                    await self._surface_ended(bundle_id)

        if not self.last_status_message:
            self.last_status_message = f"{len(eligible_ids)} active meeting app(s)"

    async def _probe_calendar_events(self) -> List[dict]:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=self.settings.calendar_join_grace_minutes)
        window_end = now + timedelta(minutes=self.settings.calendar_join_lead_minutes)

        probe = await request_swift_calendar_probe(
            self._iso_timestamp(window_start),
            self._iso_timestamp(window_end),
        )
        if not probe.get("success"):
            self.logger.debug("Calendar probe unsuccessful: %s", probe.get("message") or "Probe failed")
            return []

        events: List[dict] = probe.get("joinable_events") or []
        self.logger.debug("Calendar probe returned %d joinable event(s)", len(events))
        if events:
            event_summaries = [
                {
                    "event_id": event.get("event_identifier"),
                    "title": event.get("title"),
                    "has_join_url": bool(event.get("join_url")),
                }
                for event in events
            ]
            self.logger.info("Joinable calendar events found: %s", event_summaries)
        return events

    async def _surface_joinable_calendar_events(self, events: List[dict]) -> None:
        for event in events:
            if event.get("has_call_info") is not True or not event.get("join_url"):
                continue

            event_id = event.get("event_identifier") or event.get("join_url") or event.get("title")
            if not event_id:
                self.logger.debug("Calendar event skipped because it had no stable identifier: %s", event.get("title"))
                continue

            if event_id in self._ignored_calendar_event_ids:
                self.logger.debug("Calendar event suppressed by user action: %s", event_id)
                continue

            if self._is_calendar_event_in_cooldown(event_id):
                self.logger.debug("Calendar event suppressed by cooldown: %s", event_id)
                continue

            await self._surface_calendar_detected(event, event_id)
            self._surfaced_calendar_event_ids[event_id] = datetime.now()
            end_ts = event.get("end_timestamp")
            if end_ts is not None:
                self._surfaced_calendar_event_end_times[event_id] = float(end_ts)

    async def _expire_stale_calendar_prompts(self) -> None:
        """Auto-dismiss calendar-sourced join prompts whose event has ended
        with no user action taken. Treated identically to a manual dismiss:
        the event is added to the ignored set (so it cannot resurface after
        cooldown) and a `meeting_prompt_expired` event tells any open client
        panel to hide. Audio-sourced prompts are out of scope here: they have
        no stable identifier to track and already have a better-suited
        end-of-life signal in the existing `auto_end`/`_surface_ended`
        falling-edge path.
        """
        now_ts = datetime.now(timezone.utc).timestamp()
        expired_ids = [
            event_id
            for event_id, end_ts in self._surfaced_calendar_event_end_times.items()
            if now_ts >= end_ts
        ]
        for event_id in expired_ids:
            self._surfaced_calendar_event_end_times.pop(event_id, None)
            if event_id in self._ignored_calendar_event_ids:
                continue
            self._ignored_calendar_event_ids.add(event_id)
            self.last_status_message = f"Calendar meeting prompt expired: {event_id}"
            self.logger.info(
                "Calendar meeting prompt auto-dismissed (end time passed): event_id=%s",
                event_id,
            )
            await broadcast_json_text(
                {"event_type": "meeting_prompt_expired", "calendar_event_id": event_id},
                log=self.logger,
            )

    def _is_in_cooldown(self, bundle_id: str) -> bool:
        last = self._last_surfaced.get(bundle_id)
        if not last:
            return False
        return datetime.now() - last < timedelta(minutes=self.settings.cooldown_minutes)

    def _is_calendar_event_in_cooldown(self, event_id: str) -> bool:
        last = self._surfaced_calendar_event_ids.get(event_id)
        if not last:
            return False
        return datetime.now() - last < timedelta(minutes=self.settings.cooldown_minutes)

    def ignore_calendar_event(self, event_id: str) -> None:
        self._ignored_calendar_event_ids.add(event_id)
        self.logger.info("Calendar event ignored by user action: %s", event_id)

    def _end_debounce_ticks(self) -> int:
        poll_seconds = max(self.settings.poll_seconds, 1.0)
        inactivity_seconds = max(self.settings.inactivity_timeout_minutes, 0.0) * 60
        return max(1, math.ceil(inactivity_seconds / poll_seconds))

    async def _surface_detected(self, app: dict, calendar_event: Optional[dict]) -> None:
        meeting = {
            "source": "audio",
            "app_name": app.get("name"),
            "window_title": app.get("window_title"),
            "bundle_id": app.get("bundle_id"),
            "pid": app.get("pid"),
            "mode": self.settings.mode,
            "detected_at": datetime.now().isoformat(),
            "calendar_title": (calendar_event or {}).get("title") if self.settings.use_calendar_enrichment else None,
            "calendar_name": (calendar_event or {}).get("calendar_name") if self.settings.use_calendar_enrichment else None,
            "calendar_attendees": (calendar_event or {}).get("attendees", []) if self.settings.use_calendar_enrichment else [],
            "calendar_join_url": (calendar_event or {}).get("join_url") if self.settings.use_calendar_enrichment else None,
            "calendar_has_call_info": (calendar_event or {}).get("has_call_info", False),
        }
        self.last_status_message = f"Detected meeting: {meeting['app_name']}"
        self.logger.info("Meeting detected: %s (mode=%s)", meeting["app_name"], self.settings.mode)
        await broadcast_json_text(
            {"event_type": "meeting_detected", "meeting": meeting},
            log=self.logger,
        )

    async def _surface_calendar_detected(self, event: dict, event_id: str) -> None:
        meeting = {
            "source": "calendar",
            "app_name": "Calendar",
            "bundle_id": "",
            "pid": None,
            "mode": self.settings.mode,
            "detected_at": datetime.now().isoformat(),
            "calendar_title": event.get("title"),
            "calendar_name": event.get("calendar_name"),
            "calendar_attendees": event.get("attendees", []),
            "calendar_join_url": event.get("join_url"),
            "calendar_has_call_info": True,
            "calendar_event_id": event_id,
        }
        self.last_status_message = f"Detected calendar meeting: {meeting['calendar_title'] or event_id}"
        self.logger.info(
            "Calendar meeting prompt broadcast: event_id=%s title=%s",
            event_id,
            meeting["calendar_title"],
        )
        await broadcast_json_text(
            {"event_type": "meeting_detected", "meeting": meeting},
            log=self.logger,
        )

    async def _surface_ended(self, bundle_id: str) -> None:
        self.last_status_message = f"Meeting ended: {bundle_id}"
        self.logger.info("Meeting ended: %s", bundle_id)
        await broadcast_json_text(
            {"event_type": "meeting_ended", "bundle_id": bundle_id},
            log=self.logger,
        )

    # MARK: - Status

    def get_status(self) -> dict:
        return {
            "initialized": True,
            "enabled": self.settings.enabled,
            "is_running": self.is_running(),
            "mode": self.settings.mode,
            "poll_seconds": self.settings.poll_seconds,
            "excluded_bundle_id_count": len(self.settings.excluded_bundle_ids),
            "inactivity_timeout_minutes": self.settings.inactivity_timeout_minutes,
            "calendar_join_lead_minutes": self.settings.calendar_join_lead_minutes,
            "calendar_join_grace_minutes": self.settings.calendar_join_grace_minutes,
            "use_calendar_enrichment": self.settings.use_calendar_enrichment,
            "require_calendar_match": self.settings.require_calendar_match,
            "auto_end": self.settings.auto_end,
            "active_bundle_ids": sorted(self._active_bundle_ids),
            "ignored_calendar_event_count": len(self._ignored_calendar_event_ids),
            "last_probe_time": self.last_probe_time.isoformat() if self.last_probe_time else None,
            "next_probe_time": self.next_probe_time.isoformat() if self.next_probe_time else None,
            "last_status_message": self.last_status_message,
        }

    @staticmethod
    def _iso_timestamp(value: datetime) -> str:
        return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # MARK: - Loop

    async def _run_loop(self) -> None:
        self.logger.info("Meeting detection loop started")
        try:
            while self.settings.enabled:
                self.last_status_message = None
                try:
                    await self.run_once()
                except Exception as exc:
                    self.logger.error("Meeting detection iteration failed: %s", exc, exc_info=True)
                interval_seconds = max(self.settings.poll_seconds, 1.0)
                self.next_probe_time = datetime.now() + timedelta(seconds=interval_seconds)
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            self.logger.info("Meeting detection loop canceled")
            raise


async def initialize_meeting_detection_runtime() -> None:
    global _runtime
    if _runtime is None:
        _runtime = MeetingDetectionRuntime()


async def cleanup_meeting_detection_runtime() -> None:
    global _runtime
    if _runtime is not None:
        await _runtime.stop()
    _runtime = None


def get_meeting_detection_runtime() -> Optional[MeetingDetectionRuntime]:
    return _runtime
