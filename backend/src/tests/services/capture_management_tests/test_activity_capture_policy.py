"""Tests for automatic activity-capture exclusion policy."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.models.preferences import ActivityCaptureSettings
from api.routes.settings_routes import activity_capture_routes
from api.services.capture.automatic import automatic_activity_capture_service
from api.services.capture.automatic.automatic_activity_capture_service import (
    AutomaticActivityCaptureService,
)
from api.services.capture.shared.activity_capture_status import ActivityCaptureStatus
from api.services.capture.shared.activity_capture_exclusion_policy import (
    normalize_excluded_bundle_ids,
)
from api.services.capture.shared import window_capture_bridge


class _StubKnowledgeService:
    def __init__(self) -> None:
        self.store_activity = AsyncMock()
        self.find_open_sequence_activity = AsyncMock()
        self.update_activity = AsyncMock()


class _PrefsContainer:
    def __init__(self, activity_capture: ActivityCaptureSettings) -> None:
        self.activity_capture = activity_capture


def test_normalize_excluded_bundle_ids_preserves_an_empty_list() -> None:
    assert normalize_excluded_bundle_ids([]) == []


def test_normalize_excluded_bundle_ids_deduplicates_case_insensitively() -> None:
    result = normalize_excluded_bundle_ids(
        ["COM.APPLE.TEXTEDIT", "com.apple.textedit", " com.apple.mail "]
    )
    assert result == ["COM.APPLE.TEXTEDIT", " com.apple.mail ".strip()]


@pytest.mark.asyncio
async def test_trigger_automatic_activity_capture_forwards_exclusions(monkeypatch) -> None:
    captured: dict = {}

    async def _fake_request(capture_reason: str = "agent_task", *, excluded_bundle_ids=None):
        captured["capture_reason"] = capture_reason
        captured["excluded_bundle_ids"] = excluded_bundle_ids
        return {"success": True}

    monkeypatch.setattr(window_capture_bridge, "request_swift_window_capture", _fake_request)
    await window_capture_bridge.trigger_automatic_activity_capture(["com.stratten.basil", "com.apple.TextEdit"])
    assert captured["capture_reason"] == "automatic activity capture"
    assert captured["excluded_bundle_ids"] == ["com.stratten.basil", "com.apple.TextEdit"]


@pytest.mark.asyncio
async def test_perform_capture_policy_skip_does_not_store_or_ocr(monkeypatch) -> None:
    service = AutomaticActivityCaptureService(_StubKnowledgeService())
    prefs = _PrefsContainer(ActivityCaptureSettings())
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: prefs,
    )

    async def _policy_skip(**_kwargs):
        return {
            "success": False,
            "policy_skipped": True,
            "app_name": "TextEdit",
            "bundle_id": "com.apple.TextEdit",
        }

    monkeypatch.setattr(
        "api.services.capture.shared.window_capture_bridge.trigger_automatic_activity_capture",
        _policy_skip,
    )
    service.ocr_service = MagicMock()

    result = await service._perform_capture()

    assert result is None
    assert service.skipped_capture_count == 1
    assert service.last_policy_decision == "TextEdit: excluded_app"
    service.knowledge_service.store_activity.assert_not_called()
    service.ocr_service.extract_text.assert_not_called()


@pytest.mark.asyncio
async def test_perform_capture_failure_still_returns_failed_record(monkeypatch) -> None:
    service = AutomaticActivityCaptureService(_StubKnowledgeService())
    prefs = _PrefsContainer(ActivityCaptureSettings())
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: prefs,
    )

    async def _failed_capture(**_kwargs):
        return {"success": False, "message": "timeout"}

    monkeypatch.setattr(
        "api.services.capture.shared.window_capture_bridge.trigger_automatic_activity_capture",
        _failed_capture,
    )

    result = await service._perform_capture()

    assert result is not None
    assert result.processing_status == ActivityCaptureStatus.FAILED
    service.knowledge_service.store_activity.assert_not_called()


@pytest.mark.asyncio
async def test_perform_capture_runs_immediate_ocr_off_the_event_loop(monkeypatch, tmp_path: Path) -> None:
    service = AutomaticActivityCaptureService(_StubKnowledgeService())
    screenshot = tmp_path / "capture.png"
    screenshot.write_bytes(b"capture")

    async def _successful_capture(**_kwargs):
        return {
            "success": True,
            "app_name": "TextEdit",
            "window_title": "Study notes",
            "image_path": str(screenshot),
        }

    monkeypatch.setattr(
        "api.services.capture.shared.window_capture_bridge.trigger_automatic_activity_capture",
        _successful_capture,
    )
    service.ocr_service = MagicMock()
    service.ocr_service.extract_text.return_value = SimpleNamespace(
        status="success",
        processed_text="OCR text",
    )
    to_thread = AsyncMock(return_value=service.ocr_service.extract_text.return_value)
    monkeypatch.setattr(automatic_activity_capture_service.asyncio, "to_thread", to_thread)

    result = await service._perform_capture()

    assert result is not None
    assert result.processing_status == ActivityCaptureStatus.OCR_COMPLETE
    to_thread.assert_awaited_once_with(service.ocr_service.extract_text, str(screenshot))


@pytest.mark.asyncio
async def test_perform_capture_compaction_skips_ocr_and_storage(monkeypatch, tmp_path: Path) -> None:
    service = AutomaticActivityCaptureService(_StubKnowledgeService())
    service.activity_capture_frequency_minutes = 0.5
    service.knowledge_service.find_open_sequence_activity.return_value = {
        "id": "existing",
        "timestamp": (datetime.now() - timedelta(seconds=30)).isoformat(),
        "last_observed_at": (datetime.now() - timedelta(seconds=30)).isoformat(),
        "duration": 30,
        "observation_count": 1,
        "content_fingerprint": "0000000000000000",
    }
    prefs = _PrefsContainer(ActivityCaptureSettings())
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: prefs,
    )
    screenshot = tmp_path / "redundant.png"
    screenshot.write_bytes(b"capture")

    async def _matching_capture(**_kwargs):
        return {
            "success": True,
            "app_name": "TextEdit",
            "window_title": "Study notes",
            "image_path": str(screenshot),
            "perceptual_hash": "0000000000000000",
        }

    monkeypatch.setattr(
        "api.services.capture.shared.window_capture_bridge.trigger_automatic_activity_capture",
        _matching_capture,
    )
    service.ocr_service = MagicMock()

    result = await service._perform_capture()

    assert result is None
    assert not screenshot.exists()
    service.ocr_service.extract_text.assert_not_called()
    service.knowledge_service.store_activity.assert_not_called()
    service.knowledge_service.update_activity.assert_awaited_once()


@pytest.mark.asyncio
async def test_put_settings_persists_normalized_exclusions(monkeypatch) -> None:
    saved: list[ActivityCaptureSettings] = []
    prefs = _PrefsContainer(ActivityCaptureSettings())
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)
    monkeypatch.setattr(
        activity_capture_routes,
        "save_preferences",
        lambda _p: saved.append(prefs.activity_capture),
    )

    result = await activity_capture_routes.update_activity_capture_settings(
        activity_capture_routes.ActivityCaptureSettingsUpdate(
            excluded_bundle_ids=["com.apple.TextEdit", "COM.APPLE.TEXTEDIT"]
        )
    )

    assert result.status == "updated"
    assert "com.stratten.basil" not in result.updated_settings.excluded_bundle_ids
    assert result.updated_settings.excluded_bundle_ids.count("com.apple.TextEdit") == 1


@pytest.mark.asyncio
async def test_perform_capture_starts_processing_for_realtime_mode(monkeypatch) -> None:
    service = AutomaticActivityCaptureService(_StubKnowledgeService())
    service.ocr_service = None
    prefs = _PrefsContainer(ActivityCaptureSettings(processing_mode="realtime"))
    processor = MagicMock()
    processor.process_pending_activities_now = AsyncMock(
        return_value={"success": True, "message": "Background processing started"}
    )

    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: prefs,
    )
    monkeypatch.setattr(
        "api.services.capture.shared.window_capture_bridge.trigger_automatic_activity_capture",
        AsyncMock(
            return_value={
                "success": True,
                "app_name": "TextEdit",
                "window_title": "Study notes",
                "image_path": "/tmp/capture.png",
            }
        ),
    )
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_capture_runtime.get_automatic_processing_service_instance",
        lambda: processor,
    )

    await service._perform_capture()

    processor.process_pending_activities_now.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_capture_leaves_scheduled_mode_for_processing_loop(monkeypatch) -> None:
    service = AutomaticActivityCaptureService(_StubKnowledgeService())
    service.ocr_service = None
    prefs = _PrefsContainer(ActivityCaptureSettings(processing_mode="scheduled"))
    processor = MagicMock()
    processor.process_pending_activities_now = AsyncMock()

    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: prefs,
    )
    monkeypatch.setattr(
        "api.services.capture.shared.window_capture_bridge.trigger_automatic_activity_capture",
        AsyncMock(
            return_value={
                "success": True,
                "app_name": "TextEdit",
                "window_title": "Study notes",
                "image_path": "/tmp/capture.png",
            }
        ),
    )
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_capture_runtime.get_automatic_processing_service_instance",
        lambda: processor,
    )

    await service._perform_capture()

    processor.process_pending_activities_now.assert_not_awaited()
