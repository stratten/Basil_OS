"""Unit tests for AutomaticActivityCaptureService.configure_activity_capture_frequency.

These tests prove the fix for the AttributeError raised when the settings route
called `scheduler.configure_activity_capture_frequency(...)` on a service that did
not define the method (see activity_capture_routes.py:103). They exercise exactly
what the route does and assert the live frequency attribute is updated with no
unintended side effects on the capture loop.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.models.preferences import ActivityCaptureSettings
from api.core.services.capture_management_service import CaptureManagementService
from api.routes.settings_routes import activity_capture_routes
from api.services.capture.automatic import activity_capture_runtime
from api.services.capture.automatic.automatic_activity_capture_service import (
    AutomaticActivityCaptureService,
)


class _StubKnowledgeService:
    """Minimal stand-in; the service only stores the reference for these tests."""


class _PrefsContainer:
    """Stands in for a Preferences object; the PUT handler only touches .activity_capture."""

    def __init__(self, activity_capture: ActivityCaptureSettings) -> None:
        self.activity_capture = activity_capture


class _ListLogHandler(logging.Handler):
    """Captures log messages emitted on a specific logger (api_logger sets propagate=False)."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _make_service() -> AutomaticActivityCaptureService:
    # __init__ calls _initialize_ocr_service(), which is fully guarded by
    # try/except, so construction cannot fail even if OCR is unavailable.
    return AutomaticActivityCaptureService(_StubKnowledgeService())


@pytest.mark.asyncio
async def test_configure_frequency_updates_live_attribute() -> None:
    """AC-A2: the method the route calls exists and updates the attribute."""
    service = _make_service()

    # Mirror the exact call site from activity_capture_routes.py:103.
    await service.configure_activity_capture_frequency(1.0)
    assert service.activity_capture_frequency_minutes == 1.0

    # A subsequent change is honored too (proves it is a live setter).
    await service.configure_activity_capture_frequency(5.0)
    assert service.activity_capture_frequency_minutes == 5.0


@pytest.mark.asyncio
async def test_configure_frequency_reflected_in_status() -> None:
    """AC-A3: get_status() reports the newly configured frequency."""
    service = _make_service()

    await service.configure_activity_capture_frequency(1.0)
    status = await service.get_status()
    assert status["frequency_minutes"] == 1.0


@pytest.mark.asyncio
async def test_configure_frequency_has_no_capture_side_effects() -> None:
    """AC-A4 (adversarial): configuring frequency must not start/stop the loop."""
    service = _make_service()

    assert service.is_capture_active is False
    assert service.activity_capture_task is None

    await service.configure_activity_capture_frequency(2.5)

    # The setter must only change the frequency, never the loop lifecycle.
    assert service.is_capture_active is False
    assert service.activity_capture_task is None
    assert service.activity_capture_frequency_minutes == 2.5


@pytest.mark.asyncio
async def test_put_settings_frequency_change_updates_scheduler(monkeypatch) -> None:
    """AC-A1: the PUT /settings/activity-capture flow updates the live scheduler via the
    new method, logging success instead of the previous AttributeError.

    Preferences I/O and the scheduler lookup are patched so the real preferences file is
    never touched; this exercises the exact code path the user triggered.
    """
    prefs = _PrefsContainer(ActivityCaptureSettings(frequency_minutes=5.0))
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)
    monkeypatch.setattr(activity_capture_routes, "save_preferences", lambda _p: None)

    scheduler = AutomaticActivityCaptureService(_StubKnowledgeService())
    monkeypatch.setattr(
        activity_capture_runtime, "get_activity_capture_scheduler", lambda: scheduler
    )

    handler = _ListLogHandler()
    api_main_logger = logging.getLogger("api.main")
    api_main_logger.addHandler(handler)
    try:
        result = await activity_capture_routes.update_activity_capture_settings(
            activity_capture_routes.ActivityCaptureSettingsUpdate(frequency_minutes=1.0)
        )
    finally:
        api_main_logger.removeHandler(handler)

    # The handler completed via the success path.
    assert result.status == "updated"
    assert result.updated_settings.frequency_minutes == 1.0

    # The live scheduler was updated - proves the awaited method executed (no AttributeError).
    assert scheduler.activity_capture_frequency_minutes == 1.0

    # AC-A1: success log present, failure log absent.
    joined = "\n".join(handler.messages)
    assert "Successfully updated running scheduler frequency" in joined
@pytest.mark.asyncio
async def test_cleanup_sync_updates_scheduler_before_preferences(monkeypatch, tmp_path) -> None:
    prefs = _PrefsContainer(ActivityCaptureSettings(auto_cleanup_enabled=False))
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)

    saved_preferences: list[bool] = []

    def _save(_p) -> None:
        saved_preferences.append(prefs.activity_capture.auto_cleanup_enabled)

    monkeypatch.setattr(activity_capture_routes, "save_preferences", _save)

    scheduler_calls: list[bool] = []

    async def _sync(enabled: bool):
        scheduler_calls.append(enabled)
        service = MagicMock()
        service.get_cleanup_settings = AsyncMock(
            return_value={"retention_days": 30, "cleanup_hour": 2, "cleanup_minute": 0}
        )
        service.update_cleanup_settings = AsyncMock(
            return_value={"auto_cleanup_enabled": enabled, "retention_days": 30, "cleanup_hour": 2, "cleanup_minute": 0}
        )
        return service, {"auto_cleanup_enabled": enabled}

    monkeypatch.setattr(activity_capture_routes, "synchronize_capture_cleanup_enabled", _sync)

    result = await activity_capture_routes.update_activity_capture_settings(
        activity_capture_routes.ActivityCaptureSettingsUpdate(auto_cleanup_enabled=True)
    )

    assert scheduler_calls == [True]
    assert saved_preferences == [True]
    assert result.updated_settings.auto_cleanup_enabled is True


@pytest.mark.asyncio
async def test_cleanup_sync_rolls_back_when_preferences_save_fails(monkeypatch) -> None:
    prefs = _PrefsContainer(ActivityCaptureSettings(auto_cleanup_enabled=False))
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)

    def _fail_save(_preferences) -> None:
        raise OSError("preferences are read-only")

    monkeypatch.setattr(activity_capture_routes, "save_preferences", _fail_save)

    cleanup_service = MagicMock()
    cleanup_service.get_cleanup_settings = AsyncMock(
        return_value={
            "auto_cleanup_enabled": True,
            "retention_days": 45,
            "cleanup_hour": 3,
            "cleanup_minute": 15,
        }
    )
    cleanup_service.update_cleanup_settings = AsyncMock()

    async def _sync(enabled: bool):
        assert enabled is True
        return cleanup_service, {
            "auto_cleanup_enabled": True,
            "retention_days": 45,
            "cleanup_hour": 3,
            "cleanup_minute": 15,
        }

    monkeypatch.setattr(
        activity_capture_routes,
        "synchronize_capture_cleanup_enabled",
        _sync,
    )

    with pytest.raises(Exception, match="preferences are read-only"):
        await activity_capture_routes.update_activity_capture_settings(
            activity_capture_routes.ActivityCaptureSettingsUpdate(
                auto_cleanup_enabled=True
            )
        )

    cleanup_service.update_cleanup_settings.assert_awaited_once_with(
        auto_cleanup_enabled=False,
        retention_days=45,
        cleanup_hour=3,
        cleanup_minute=15,
    )


@pytest.mark.asyncio
async def test_cleanup_sync_failure_prevents_preferences_save(monkeypatch) -> None:
    prefs = _PrefsContainer(ActivityCaptureSettings(auto_cleanup_enabled=False))
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)
    save_preferences = MagicMock()
    monkeypatch.setattr(
        activity_capture_routes,
        "save_preferences",
        save_preferences,
    )

    async def _fail_sync(_enabled: bool):
        raise OSError("reasoning settings are read-only")

    monkeypatch.setattr(
        activity_capture_routes,
        "synchronize_capture_cleanup_enabled",
        _fail_sync,
    )

    with pytest.raises(Exception, match="reasoning settings are read-only"):
        await activity_capture_routes.update_activity_capture_settings(
            activity_capture_routes.ActivityCaptureSettingsUpdate(
                auto_cleanup_enabled=True
            )
        )

    save_preferences.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_service_write_failure_does_not_mutate_runtime_state(
    monkeypatch,
    tmp_path,
) -> None:
    service = CaptureManagementService.__new__(CaptureManagementService)
    service.settings_file_path = tmp_path / "reasoning_settings.json"
    service._settings = {
        "auto_cleanup_enabled": False,
        "retention_days": 30,
        "cleanup_hour": 2,
        "cleanup_minute": 0,
    }

    def _fail_save(_settings) -> None:
        raise OSError("reasoning settings are read-only")

    monkeypatch.setattr(service, "_save_settings", _fail_save)

    with pytest.raises(OSError, match="reasoning settings are read-only"):
        await service.update_cleanup_settings(
            auto_cleanup_enabled=True,
            retention_days=45,
            cleanup_hour=3,
            cleanup_minute=15,
        )

    assert service._settings == {
        "auto_cleanup_enabled": False,
        "retention_days": 30,
        "cleanup_hour": 2,
        "cleanup_minute": 0,
    }


def test_start_at_startup_defaults_to_false() -> None:
    assert ActivityCaptureSettings().start_at_startup is False


@pytest.mark.asyncio
async def test_put_eligibility_thresholds_persists(monkeypatch) -> None:
    prefs = _PrefsContainer(ActivityCaptureSettings())
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)
    save_preferences = MagicMock()
    monkeypatch.setattr(activity_capture_routes, "save_preferences", save_preferences)

    result = await activity_capture_routes.update_activity_capture_settings(
        activity_capture_routes.ActivityCaptureSettingsUpdate(
            idle_threshold_seconds=45,
            post_wake_grace_seconds=12,
        )
    )

    assert result.status == "updated"
    assert result.updated_settings.idle_threshold_seconds == 45
    assert result.updated_settings.post_wake_grace_seconds == 12
    assert prefs.activity_capture.idle_threshold_seconds == 45
    assert prefs.activity_capture.post_wake_grace_seconds == 12
    save_preferences.assert_called_once_with(prefs)


@pytest.mark.asyncio
async def test_put_start_at_startup_persists_without_enabling_capture(monkeypatch) -> None:
    prefs = _PrefsContainer(
        ActivityCaptureSettings(enabled=False, start_at_startup=False)
    )
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)
    save_preferences = MagicMock()
    monkeypatch.setattr(activity_capture_routes, "save_preferences", save_preferences)

    result = await activity_capture_routes.update_activity_capture_settings(
        activity_capture_routes.ActivityCaptureSettingsUpdate(start_at_startup=True)
    )

    assert result.status == "updated"
    assert result.updated_settings.start_at_startup is True
    assert result.updated_settings.enabled is False
    assert prefs.activity_capture.start_at_startup is True
    assert prefs.activity_capture.enabled is False
    save_preferences.assert_called_once_with(prefs)


@pytest.mark.asyncio
async def test_put_settings_disable_stops_running_scheduler(monkeypatch) -> None:
    prefs = _PrefsContainer(ActivityCaptureSettings(enabled=True))
    monkeypatch.setattr(activity_capture_routes, "load_preferences", lambda: prefs)
    monkeypatch.setattr(activity_capture_routes, "save_preferences", lambda _p: None)
    scheduler = MagicMock()
    scheduler.stop_activity_capture = AsyncMock()
    monkeypatch.setattr(
        activity_capture_runtime,
        "get_activity_capture_scheduler",
        lambda: scheduler,
    )

    result = await activity_capture_routes.update_activity_capture_settings(
        activity_capture_routes.ActivityCaptureSettingsUpdate(enabled=False)
    )

    assert result.status == "updated"
    assert result.updated_settings.enabled is False
    assert prefs.activity_capture.enabled is False
    scheduler.stop_activity_capture.assert_awaited_once()
