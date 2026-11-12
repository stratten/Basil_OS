"""Applies an express plan: starts the selected downloads and writes the selected settings, reporting each item plainly."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from api.core.logging.api_logger import api_logger
from api.core.models.model_download.disk_space import InsufficientDiskSpaceError

from .catalog import CATALOG, DOWNLOAD_THINKING, EXPRESS_SETTING_PATHS, settings_for
from .models import ComfortLevel, ExpressApplyRequest, ExpressApplyResult, ExpressItem, ExpressItemResult
from .planner import ExpressPlanner
from .receipt import WHERE_TO_CHANGE

_LAUNCH_KEYS = ("start_at_startup", "enable_voice_listener_at_startup")


class SettingsWriter(Protocol):
    async def apply(self, section: str, updates: Dict[str, Any]) -> None: ...


class LiveSettingsWriter:
    """Writes express settings through the same code the app's Settings screens use."""

    async def apply(self, section: str, updates: Dict[str, Any]) -> None:
        for key in updates:
            if f"{section}.{key}" not in EXPRESS_SETTING_PATHS:
                raise ValueError(f"Express setup may not change {section}.{key}.")
        if section == "activity_capture":
            from api.routes.settings_routes.activity_capture_routes import update_activity_capture_settings
            from api.services.activity_capture_broadcast import broadcast_activity_capture_updated
            from api.services.setup_assistant.action_execution_service import validate_activity_capture_settings_payload

            await update_activity_capture_settings(validate_activity_capture_settings_payload(updates))
            await broadcast_activity_capture_updated()
        elif section == "meeting_detection":
            from api.routes.settings_routes.meeting_detection_routes import (
                MeetingDetectionSettingsUpdate,
                update_meeting_detection_settings,
            )

            await update_meeting_detection_settings(MeetingDetectionSettingsUpdate(**updates))
        else:
            self._write_preferences(section, updates)

    @staticmethod
    def _write_preferences(section: str, updates: Dict[str, Any]) -> None:
        from api.core.preferences.preferences_io import load_preferences, save_preferences

        preferences = load_preferences()
        section_obj = getattr(preferences, section)
        for key, value in updates.items():
            if not hasattr(section_obj, key):
                raise ValueError(f"Setting {section}.{key} does not exist.")
            setattr(section_obj, key, value)
        save_preferences(preferences)


def _applied_message(item: ExpressItem, comfort: ComfortLevel) -> str:
    starts_at_launch = any(
        value is True and key in _LAUNCH_KEYS
        for updates in settings_for(item.id, comfort).values()
        for key, value in updates.items()
    )
    message = f"{item.title} is on."
    if starts_at_launch:
        message += " It starts the next time Basil launches."
    return message


class ExpressApplier:
    def __init__(self, planner: ExpressPlanner, download_manager: Any, writer: Optional[SettingsWriter] = None) -> None:
        self._planner = planner
        self._download_manager = download_manager
        self._writer: SettingsWriter = writer or LiveSettingsWriter()

    async def apply(self, request: ExpressApplyRequest) -> ExpressApplyResult:
        plan = await self._planner.build_plan(request.comfort)
        items_by_id = {item.id: item for item in plan.items}
        unknown = [item_id for item_id in request.selected_item_ids if item_id not in items_by_id]
        if unknown:
            raise ValueError(f"These items are not part of this setup: {', '.join(unknown)}.")

        wanted = set(request.selected_item_ids)
        results_by_id: Dict[str, ExpressItemResult] = {}
        # The download manager runs one download at a time in the order they start, so the thinking model, which is by far the largest, starts last. The two small voice models then finish in minutes instead of waiting behind a download that can take an hour. The results below still follow catalog order, which is also the order the screen and the receipt list the items in.
        for entry in sorted(CATALOG, key=lambda candidate: candidate.id == DOWNLOAD_THINKING):
            if entry.id not in wanted or entry.native:
                continue
            item = items_by_id[entry.id]
            if item.already_done:
                results_by_id[item.id] = ExpressItemResult(id=item.id, outcome="skipped", message=f"{item.title} is already on.")
            elif item.unavailable_reason:
                results_by_id[item.id] = ExpressItemResult(id=item.id, outcome="skipped", message=item.unavailable_reason)
            elif entry.group == "downloads":
                results_by_id[item.id] = await self._start_download(item)
            else:
                results_by_id[item.id] = await self._write_settings(item, request.comfort)
        results: List[ExpressItemResult] = [results_by_id[entry.id] for entry in CATALOG if entry.id in results_by_id]

        thinking = items_by_id.get(DOWNLOAD_THINKING)
        thinking_ready = thinking is not None and (thinking.already_done or (thinking.selected and DOWNLOAD_THINKING in wanted))
        thinking_id = thinking.model_id if thinking_ready else None
        return ExpressApplyResult(comfort=request.comfort, results=results, thinking_model_id=thinking_id)

    async def _start_download(self, item: ExpressItem) -> ExpressItemResult:
        model_type, _, variant = (item.model_id or "").partition("-")
        try:
            entry = await self._download_manager.start(model_type, variant)
        except InsufficientDiskSpaceError as exc:
            return ExpressItemResult(id=item.id, outcome="failed", message=str(exc))
        except Exception:
            api_logger.error(f"[Express] Could not start download {item.model_id}", exc_info=True)
            return ExpressItemResult(
                id=item.id, outcome="failed", message=f"I couldn't start this download. You can start it from {WHERE_TO_CHANGE[item.id]}."
            )
        if entry.status in {"queued", "downloading"}:
            return ExpressItemResult(id=item.id, outcome="started", message=f"{item.title} is downloading.")
        if entry.status == "skipped_installed":
            return ExpressItemResult(id=item.id, outcome="skipped", message=f"{item.title} is already on this Mac.")
        return ExpressItemResult(
            id=item.id, outcome="failed", message=f"I couldn't start this download. You can start it from {WHERE_TO_CHANGE[item.id]}."
        )

    async def _write_settings(self, item: ExpressItem, comfort: ComfortLevel) -> ExpressItemResult:
        try:
            for section, updates in settings_for(item.id, comfort).items():
                await self._writer.apply(section, updates)
        except Exception:
            api_logger.error(f"[Express] Could not apply {item.id}", exc_info=True)
            return ExpressItemResult(
                id=item.id, outcome="failed", message=f"I couldn't turn on {item.title}. You can turn it on in {WHERE_TO_CHANGE[item.id]}."
            )
        return ExpressItemResult(id=item.id, outcome="applied", message=_applied_message(item, comfort))
