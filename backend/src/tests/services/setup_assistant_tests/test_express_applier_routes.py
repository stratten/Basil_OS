"""Express setup apply and receipt: what gets started and written, what is skipped, and how failures are reported."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.core.models.model_download.disk_space import InsufficientDiskSpaceError
from api.core.models.preferences import Preferences
from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, get_backend_credential_store
from api.main import app
from api.routes.setup_assistant import express_routes
from api.services.setup_assistant.express.applier import ExpressApplier, LiveSettingsWriter
from api.services.setup_assistant.express.catalog import (
    CAPTURE_ACTIVITY,
    DETECT_MEETINGS,
    DOWNLOAD_THINKING,
    DOWNLOAD_VOICE_FAST,
    DOWNLOAD_VOICE_QUALITY,
    HOTKEYS,
    LEARN_MEMORY,
    LEARN_SKILLS,
    VOICE_LISTENER,
)
from api.services.setup_assistant.express.models import DeviceSummary, ExpressApplyRequest
from api.services.setup_assistant.express.planner import ExpressEnvironment, ExpressPlanner

THINKING_ID = "Qwen-qwen35-9b-q4km"
REGISTRY = {THINKING_ID: {"size": "5.6GB", "display_name": "Qwen 3.5 9B"}}


def _starters():
    return [
        {"model_type": "OpenAI", "variant": "whisper-tiny.en", "priority": 1, "description": "Fast English transcription (151MB)"},
        {
            "model_type": "NVIDIA",
            "variant": "parakeet-tdt-0.6b-v3-quantized",
            "priority": 2,
            "description": "High-quality multilingual transcription (670MB)",
        },
        {"model_type": "Qwen", "variant": "qwen35-9b-q4km", "priority": 3, "description": "Reasoning model for suggestions (5.6GB)"},
    ]


def _environment(*, installed=(), free=100.0, preferences=None) -> ExpressEnvironment:
    async def reachable() -> bool:
        return True

    return ExpressEnvironment(
        read_device=lambda: DeviceSummary(
            total_ram_gb=16,
            memory_tier="standard",
            chip_label="Apple M2",
            is_apple_silicon=True,
            free_disk_gb=free,
            summary="Apple M2, 16 GB of memory",
        ),
        starter_models=_starters,
        is_installed=lambda model_type, variant: f"{model_type}-{variant}" in installed,
        model_info=REGISTRY.get,
        can_reach_download_host=reachable,
        load_preferences=lambda: preferences if preferences is not None else Preferences(),
    )


class _Manager:
    def __init__(self, status="queued", error=None):
        self.started = []
        self._status = status
        self._error = error

    async def start(self, model_type, variant):
        self.started.append((model_type, variant))
        if self._error is not None:
            raise self._error
        return SimpleNamespace(status=self._status)


class _Writer:
    def __init__(self, fail_on_key=None):
        self.applied = []
        self._fail_on_key = fail_on_key

    async def apply(self, section, updates):
        if self._fail_on_key and self._fail_on_key in updates:
            raise RuntimeError("secret internal detail")
        self.applied.append((section, dict(updates)))


def _applier(manager, writer, **environment):
    return ExpressApplier(ExpressPlanner(_environment(**environment)), manager, writer)


def _by_id(result):
    return {item.id: item for item in result.results}


@pytest.mark.asyncio
async def test_cautious_starts_the_three_downloads_in_order_and_writes_the_two_learning_settings():
    manager, writer = _Manager(), _Writer()
    request = ExpressApplyRequest(
        comfort="cautious",
        selected_item_ids=[HOTKEYS, LEARN_SKILLS, LEARN_MEMORY, DOWNLOAD_VOICE_QUALITY, DOWNLOAD_VOICE_FAST, DOWNLOAD_THINKING],
    )

    result = await _applier(manager, writer).apply(request)

    assert manager.started == [("Qwen", "qwen35-9b-q4km"), ("OpenAI", "whisper-tiny.en"), ("NVIDIA", "parakeet-tdt-0.6b-v3-quantized")]
    assert writer.applied == [
        ("memory_intelligence", {"memory_after_task_enabled": True}),
        ("memory_intelligence", {"skill_after_task_enabled": True}),
    ]
    assert [item.outcome for item in result.results] == ["started", "started", "started", "applied", "applied"]
    assert HOTKEYS not in _by_id(result)
    assert result.thinking_model_id == THINKING_ID


@pytest.mark.asyncio
async def test_all_in_writes_the_launch_settings_and_says_when_they_start():
    writer = _Writer()
    request = ExpressApplyRequest(comfort="all_in", selected_item_ids=[CAPTURE_ACTIVITY, DETECT_MEETINGS, VOICE_LISTENER])

    result = await _applier(_Manager(), writer).apply(request)

    assert writer.applied == [
        ("activity_capture", {"enabled": True, "start_at_startup": True}),
        ("meeting_detection", {"enabled": True, "start_at_startup": True, "mode": "prompt"}),
        ("behavior", {"enable_voice_listener_at_startup": True}),
    ]
    for item in result.results:
        assert item.outcome == "applied"
        assert item.message.endswith("It starts the next time Basil launches.")


@pytest.mark.asyncio
async def test_balanced_reveals_capture_and_meetings_without_starting_them_at_launch():
    writer = _Writer()
    request = ExpressApplyRequest(comfort="balanced", selected_item_ids=[CAPTURE_ACTIVITY, DETECT_MEETINGS])

    result = await _applier(_Manager(), writer).apply(request)

    assert writer.applied == [
        ("activity_capture", {"enabled": True, "start_at_startup": False}),
        ("meeting_detection", {"enabled": True, "start_at_startup": False, "mode": "prompt"}),
    ]
    assert _by_id(result)[CAPTURE_ACTIVITY].message == "Activity Capture is on."


@pytest.mark.asyncio
async def test_an_item_the_person_unticked_is_not_applied():
    manager, writer = _Manager(), _Writer()
    request = ExpressApplyRequest(comfort="all_in", selected_item_ids=[DOWNLOAD_THINKING, CAPTURE_ACTIVITY, DETECT_MEETINGS])

    await _applier(manager, writer).apply(request)

    assert manager.started == [("Qwen", "qwen35-9b-q4km")]
    assert [section for section, _ in writer.applied] == ["activity_capture", "meeting_detection"]


@pytest.mark.asyncio
async def test_an_id_that_is_not_part_of_the_plan_is_rejected_before_anything_runs():
    manager, writer = _Manager(), _Writer()
    request = ExpressApplyRequest(comfort="cautious", selected_item_ids=[DOWNLOAD_THINKING, VOICE_LISTENER])

    with pytest.raises(ValueError, match="voice_listener"):
        await _applier(manager, writer).apply(request)

    assert manager.started == [] and writer.applied == []


@pytest.mark.asyncio
async def test_the_hotkey_item_is_left_to_the_app():
    manager, writer = _Manager(), _Writer()

    result = await _applier(manager, writer).apply(ExpressApplyRequest(comfort="cautious", selected_item_ids=[HOTKEYS]))

    assert result.results == [] and manager.started == [] and writer.applied == []


@pytest.mark.asyncio
async def test_an_installed_model_is_skipped_and_its_route_can_still_be_selected():
    manager = _Manager()

    result = await _applier(manager, _Writer(), installed=(THINKING_ID,)).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[DOWNLOAD_THINKING])
    )

    assert manager.started == []
    assert _by_id(result)[DOWNLOAD_THINKING].outcome == "skipped"
    assert result.thinking_model_id == THINKING_ID


@pytest.mark.asyncio
async def test_a_download_the_disk_cannot_hold_is_skipped_with_the_reason_and_gives_no_route():
    manager = _Manager()

    result = await _applier(manager, _Writer(), free=8.0).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[DOWNLOAD_THINKING, DOWNLOAD_VOICE_FAST])
    )

    assert manager.started == [("OpenAI", "whisper-tiny.en")]
    skipped = _by_id(result)[DOWNLOAD_THINKING]
    assert skipped.outcome == "skipped" and "Not enough free disk space" in skipped.message
    assert result.thinking_model_id is None


@pytest.mark.asyncio
async def test_a_setting_that_is_already_on_is_skipped_not_rewritten():
    preferences = Preferences()
    preferences.memory_intelligence.memory_after_task_enabled = True
    writer = _Writer()

    result = await _applier(_Manager(), writer, preferences=preferences).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[LEARN_MEMORY])
    )

    assert writer.applied == []
    assert _by_id(result)[LEARN_MEMORY].outcome == "skipped"


@pytest.mark.asyncio
async def test_the_download_managers_own_disk_refusal_is_reported_as_failed_in_its_words():
    error = InsufficientDiskSpaceError(THINKING_ID, "Qwen 3.5 9B", 13.2, 9.0)

    result = await _applier(_Manager(error=error), _Writer()).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[DOWNLOAD_THINKING])
    )

    item = _by_id(result)[DOWNLOAD_THINKING]
    assert item.outcome == "failed" and item.message == str(error)


@pytest.mark.asyncio
async def test_an_unexpected_download_error_is_reported_plainly_without_the_internal_text():
    result = await _applier(_Manager(error=RuntimeError("secret internal detail")), _Writer()).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[DOWNLOAD_VOICE_FAST])
    )

    item = _by_id(result)[DOWNLOAD_VOICE_FAST]
    assert item.outcome == "failed"
    assert "secret" not in item.message
    assert "Settings, Capabilities, Models" in item.message


@pytest.mark.asyncio
async def test_a_status_the_manager_does_not_expect_is_a_failure():
    result = await _applier(_Manager(status="failed"), _Writer()).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[DOWNLOAD_VOICE_FAST])
    )

    assert _by_id(result)[DOWNLOAD_VOICE_FAST].outcome == "failed"


@pytest.mark.asyncio
async def test_one_setting_failing_does_not_stop_the_others_and_hides_the_internal_text():
    writer = _Writer(fail_on_key="skill_after_task_enabled")

    result = await _applier(_Manager(), writer).apply(
        ExpressApplyRequest(comfort="cautious", selected_item_ids=[LEARN_MEMORY, LEARN_SKILLS])
    )

    outcomes = _by_id(result)
    assert outcomes[LEARN_MEMORY].outcome == "applied"
    assert outcomes[LEARN_SKILLS].outcome == "failed"
    assert "secret" not in outcomes[LEARN_SKILLS].message
    assert outcomes[LEARN_SKILLS].message == "I couldn't turn on Reusable workflows. You can turn it on in Settings, Capabilities, Automation & Agents, Skills."


@pytest.mark.asyncio
async def test_the_live_writer_refuses_a_setting_express_does_not_own():
    writer = LiveSettingsWriter()

    with pytest.raises(ValueError):
        await writer.apply("ambient_suggestions", {"enabled": True})
    with pytest.raises(ValueError):
        await writer.apply("behavior", {"enable_monitoring_at_startup": False})


@pytest.mark.asyncio
async def test_the_live_writer_saves_behavior_and_memory_settings_to_preferences(monkeypatch):
    from api.core.preferences import preferences_io

    preferences = Preferences()
    saved = []
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: preferences)
    monkeypatch.setattr(preferences_io, "save_preferences", lambda value: saved.append(value))

    writer = LiveSettingsWriter()
    await writer.apply("behavior", {"enable_voice_listener_at_startup": True})
    await writer.apply("memory_intelligence", {"memory_after_task_enabled": True})

    assert preferences.behavior.enable_voice_listener_at_startup is True
    assert preferences.memory_intelligence.memory_after_task_enabled is True
    assert saved == [preferences, preferences]


@pytest.mark.asyncio
async def test_the_live_writer_sends_capture_and_meeting_settings_through_the_settings_routes(monkeypatch):
    from api.routes.settings_routes import activity_capture_routes, meeting_detection_routes
    from api.services import activity_capture_broadcast

    capture_calls, meeting_calls, broadcasts = [], [], []

    async def fake_capture(update):
        capture_calls.append(update.model_dump(exclude_unset=True))

    async def fake_meeting(update):
        meeting_calls.append(update.model_dump(exclude_unset=True))

    async def fake_broadcast():
        broadcasts.append(True)

    monkeypatch.setattr(activity_capture_routes, "update_activity_capture_settings", fake_capture)
    monkeypatch.setattr(meeting_detection_routes, "update_meeting_detection_settings", fake_meeting)
    monkeypatch.setattr(activity_capture_broadcast, "broadcast_activity_capture_updated", fake_broadcast)

    writer = LiveSettingsWriter()
    await writer.apply("activity_capture", {"enabled": True, "start_at_startup": False})
    await writer.apply("meeting_detection", {"enabled": True, "start_at_startup": True, "mode": "prompt"})

    assert capture_calls == [{"enabled": True, "start_at_startup": False}]
    assert meeting_calls == [{"enabled": True, "start_at_startup": True, "mode": "prompt"}]
    assert broadcasts == [True]


@pytest.fixture
def express_client(monkeypatch):
    writer = _Writer()
    manager = _Manager()
    preferences = Preferences()
    preferences.behavior.enable_voice_listener_at_startup = True
    monkeypatch.setattr(express_routes, "_environment_for", lambda model_service: _environment(preferences=preferences))
    monkeypatch.setattr(
        express_routes, "ExpressApplier", lambda planner, download_manager: ExpressApplier(planner, download_manager, writer)
    )
    monkeypatch.setattr(app.state, "download_manager", manager, raising=False)
    webview_token = get_backend_credential_store().current().webview_token
    return SimpleNamespace(client=TestClient(app, headers={BACKEND_TOKEN_HEADER: webview_token}), writer=writer, manager=manager)


def test_the_plan_route_answers_for_the_setup_webview_and_changes_nothing(express_client):
    response = express_client.client.get("/setup-assistant/express/plan?comfort=all_in")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]][-1] == HOTKEYS
    assert body["thinking_model_available"] is True
    assert body["device"]["summary"] == "Apple M2, 16 GB of memory"
    assert express_client.manager.started == [] and express_client.writer.applied == []


def test_the_plan_route_rejects_a_comfort_level_that_does_not_exist(express_client):
    assert express_client.client.get("/setup-assistant/express/plan?comfort=reckless").status_code == 422


def test_the_apply_route_starts_and_writes_what_was_selected(express_client):
    response = express_client.client.post(
        "/setup-assistant/express/apply",
        json={"comfort": "cautious", "selected_item_ids": [DOWNLOAD_THINKING, LEARN_MEMORY]},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["outcome"] for item in body["results"]] == ["started", "applied"]
    assert body["thinking_model_id"] == THINKING_ID
    assert express_client.manager.started == [("Qwen", "qwen35-9b-q4km")]
    assert express_client.writer.applied == [("memory_intelligence", {"memory_after_task_enabled": True})]


def test_the_apply_route_rejects_an_unknown_item_with_a_plain_message(express_client):
    response = express_client.client.post(
        "/setup-assistant/express/apply", json={"comfort": "cautious", "selected_item_ids": ["turn_everything_on"]}
    )

    assert response.status_code == 400
    assert "turn_everything_on" in response.json()["detail"]


def test_the_apply_route_says_so_when_downloads_are_not_ready_yet(express_client, monkeypatch):
    monkeypatch.setattr(app.state, "download_manager", None, raising=False)

    response = express_client.client.post(
        "/setup-assistant/express/apply", json={"comfort": "cautious", "selected_item_ids": [LEARN_MEMORY]}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Downloads are not ready yet. Try again in a moment."
    assert express_client.writer.applied == []


def test_the_receipt_route_reads_the_current_settings(express_client):
    response = express_client.client.get("/setup-assistant/express/receipt")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[VOICE_LISTENER]["state"] == "on"
    assert items[CAPTURE_ACTIVITY]["state"] == "off"
    assert items[DOWNLOAD_THINKING]["state"] == "off"
    assert items[HOTKEYS]["state"] == "on"
