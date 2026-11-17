"""Express setup plans: what each comfort level does on a given Mac, what blocks it, and what the receipt reads back."""

from __future__ import annotations

import pytest

from api.core.models.preferences import Preferences
from api.services.app_control.classification import POLICIES
from api.services.setup_assistant.express.catalog import (
    CAPTURE_ACTIVITY,
    DETECT_MEETINGS,
    DOWNLOAD_THINKING,
    DOWNLOAD_VOICE_FAST,
    DOWNLOAD_VOICE_QUALITY,
    EXPRESS_SETTING_PATHS,
    HOTKEYS,
    LEARN_MEMORY,
    LEARN_SKILLS,
    VOICE_LISTENER,
)
from api.services.setup_assistant.express.models import DeviceSummary
from api.services.setup_assistant.express.planner import (
    NETWORK_MESSAGE,
    NO_THINKING_NOTE,
    ExpressEnvironment,
    ExpressPlanner,
)
from api.services.setup_assistant.express.receipt import build_receipt

THINKING_ID = "Qwen-qwen35-9b-q4km"
FAST_ID = "OpenAI-whisper-tiny.en"
QUALITY_ID = "NVIDIA-parakeet-tdt-0.6b-v3-quantized"

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


class _Environment:
    """A fake Mac. `probes` counts how many times the network was tested."""

    def __init__(self, *, installed=(), free=100.0, tier="standard", reachable=True, preferences=None):
        self.probes = 0
        self._reachable = reachable
        self.environment = ExpressEnvironment(
            read_device=lambda: DeviceSummary(
                total_ram_gb=16,
                memory_tier=tier,
                chip_label="Apple M2",
                is_apple_silicon=True,
                free_disk_gb=free,
                summary="Apple M2, 16 GB of memory",
            ),
            starter_models=_starters,
            is_installed=lambda model_type, variant: f"{model_type}-{variant}" in installed,
            model_info=REGISTRY.get,
            can_reach_download_host=self._reach,
            load_preferences=lambda: preferences if preferences is not None else Preferences(),
        )

    async def _reach(self) -> bool:
        self.probes += 1
        return self._reachable


async def _plan(comfort, **kwargs):
    fake = _Environment(**kwargs)
    return await ExpressPlanner(fake.environment).build_plan(comfort), fake


def _ids(plan):
    return [item.id for item in plan.items]


def _item(plan, item_id):
    return next(item for item in plan.items if item.id == item_id)


@pytest.mark.asyncio
async def test_cautious_lists_the_downloads_the_learning_toggles_and_the_hotkey_check_only():
    plan, _ = await _plan("cautious")

    assert _ids(plan) == [DOWNLOAD_THINKING, DOWNLOAD_VOICE_FAST, DOWNLOAD_VOICE_QUALITY, LEARN_MEMORY, LEARN_SKILLS, HOTKEYS]


@pytest.mark.asyncio
async def test_balanced_adds_capture_and_meeting_detection_but_not_the_voice_listener():
    plan, _ = await _plan("balanced")

    assert _ids(plan) == [
        DOWNLOAD_THINKING, DOWNLOAD_VOICE_FAST, DOWNLOAD_VOICE_QUALITY, LEARN_MEMORY, LEARN_SKILLS, CAPTURE_ACTIVITY, DETECT_MEETINGS, HOTKEYS,
    ]


@pytest.mark.asyncio
async def test_all_in_adds_the_voice_listener_and_never_proactive_suggestions():
    plan, _ = await _plan("all_in")

    assert _ids(plan) == [
        DOWNLOAD_THINKING, DOWNLOAD_VOICE_FAST, DOWNLOAD_VOICE_QUALITY, LEARN_MEMORY, LEARN_SKILLS, CAPTURE_ACTIVITY, DETECT_MEETINGS, VOICE_LISTENER, HOTKEYS,
    ]
    assert not any("suggest" in item.id and item.group == "background" for item in plan.items)


@pytest.mark.asyncio
async def test_the_voice_listener_is_offered_at_all_in_but_starts_unticked():
    plan, _ = await _plan("all_in")

    voice = _item(plan, VOICE_LISTENER)
    assert voice.selected is True
    assert voice.default_ticked is False
    assert voice.caution is not None and "sounds that are not you" in voice.caution
    assert [item.id for item in plan.items if not item.default_ticked] == [VOICE_LISTENER]


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["cautious", "balanced"])
async def test_every_item_starts_ticked_below_the_all_in_level(level):
    plan, _ = await _plan(level)

    assert all(item.default_ticked for item in plan.items)


@pytest.mark.asyncio
async def test_the_effect_text_for_capture_and_meetings_changes_with_the_level():
    balanced, _ = await _plan("balanced")
    all_in, _ = await _plan("all_in")

    assert "every time Basil launches" not in _item(balanced, CAPTURE_ACTIVITY).summary
    assert "every time Basil launches" in _item(all_in, CAPTURE_ACTIVITY).summary
    assert "does not start by itself" in _item(balanced, DETECT_MEETINGS).summary
    assert "every time Basil launches" in _item(all_in, DETECT_MEETINGS).summary
    assert "I still ask before I record anything" in _item(all_in, DETECT_MEETINGS).summary


@pytest.mark.asyncio
async def test_a_fresh_mac_selects_every_item_and_sizes_the_downloads():
    plan, _ = await _plan("all_in")

    assert all(item.selected for item in plan.items)
    assert plan.thinking_model_available is True
    assert [check.ok for check in plan.preflight] == [True, True]
    assert _item(plan, DOWNLOAD_THINKING).download_size_gb == pytest.approx(5.6)
    assert _item(plan, DOWNLOAD_THINKING).model_id == THINKING_ID
    assert _item(plan, DOWNLOAD_THINKING).model_name == "Qwen 3.5 9B"
    assert _item(plan, DOWNLOAD_VOICE_FAST).download_size_gb == pytest.approx(151 / 1024)
    assert _item(plan, DOWNLOAD_VOICE_QUALITY).download_size_gb == pytest.approx(670 / 1024)
    assert _item(plan, HOTKEYS).native is True


@pytest.mark.asyncio
async def test_an_installed_model_is_shown_as_done_and_not_selected():
    plan, _ = await _plan("cautious", installed=(THINKING_ID,))

    thinking = _item(plan, DOWNLOAD_THINKING)
    assert thinking.already_done is True
    assert thinking.selected is False
    assert plan.thinking_model_available is True


@pytest.mark.asyncio
async def test_a_setting_that_is_already_on_is_shown_as_done():
    preferences = Preferences()
    preferences.memory_intelligence.memory_after_task_enabled = True

    plan, _ = await _plan("cautious", preferences=preferences)

    assert _item(plan, LEARN_MEMORY).already_done is True
    assert _item(plan, LEARN_MEMORY).selected is False
    assert _item(plan, LEARN_SKILLS).selected is True


@pytest.mark.asyncio
async def test_express_never_asks_to_lower_a_launch_setting_but_does_raise_one():
    preferences = Preferences()
    preferences.activity_capture.enabled = True
    preferences.activity_capture.start_at_startup = True
    balanced, _ = await _plan("balanced", preferences=preferences)
    assert _item(balanced, CAPTURE_ACTIVITY).already_done is True

    preferences.activity_capture.start_at_startup = False
    all_in, _ = await _plan("all_in", preferences=preferences)
    assert _item(all_in, CAPTURE_ACTIVITY).already_done is False
    assert _item(all_in, CAPTURE_ACTIVITY).selected is True


@pytest.mark.asyncio
async def test_too_little_disk_blocks_the_thinking_model_and_says_how_much_to_free():
    plan, _ = await _plan("cautious", free=8.0)

    thinking = _item(plan, DOWNLOAD_THINKING)
    assert thinking.selected is False
    assert "Not enough free disk space" in thinking.unavailable_reason
    assert _item(plan, DOWNLOAD_VOICE_FAST).selected is True
    assert plan.thinking_model_available is False
    assert NO_THINKING_NOTE in plan.notes
    assert plan.preflight[0].id == "disk" and plan.preflight[0].ok is False


@pytest.mark.asyncio
async def test_the_thinking_model_gets_the_room_before_the_voice_models():
    plan, _ = await _plan("cautious", free=13.3)

    assert _item(plan, DOWNLOAD_THINKING).selected is True
    assert plan.preflight[0].ok is True


@pytest.mark.asyncio
async def test_an_unreadable_disk_does_not_block_and_the_check_says_so():
    plan, _ = await _plan("cautious", free=None)

    assert all(item.selected for item in plan.items)
    assert plan.preflight[0].ok is True
    assert "couldn't read" in plan.preflight[0].message


@pytest.mark.asyncio
async def test_no_network_blocks_every_pending_download_but_not_the_settings():
    plan, fake = await _plan("all_in", reachable=False)

    for item_id in (DOWNLOAD_THINKING, DOWNLOAD_VOICE_FAST, DOWNLOAD_VOICE_QUALITY):
        assert _item(plan, item_id).unavailable_reason == NETWORK_MESSAGE
        assert _item(plan, item_id).selected is False
    assert _item(plan, VOICE_LISTENER).selected is True
    assert plan.preflight[1].id == "network" and plan.preflight[1].ok is False
    assert fake.probes == 1


@pytest.mark.asyncio
async def test_the_network_is_not_tested_when_nothing_needs_downloading():
    plan, fake = await _plan("cautious", installed=(THINKING_ID, FAST_ID, QUALITY_ID), reachable=False)

    assert fake.probes == 0
    assert plan.preflight[1].ok is True
    assert plan.preflight[0].message == "Nothing needs downloading."


@pytest.mark.asyncio
async def test_a_low_memory_mac_is_told_why_the_model_is_smaller():
    plan, _ = await _plan("cautious", tier="low")

    assert any("less memory than most" in note for note in plan.notes)
    assert any("stays on this Mac" in note for note in plan.notes)


def test_express_writes_exactly_these_settings_and_each_is_in_the_app_control_registry():
    assert EXPRESS_SETTING_PATHS == {
        "memory_intelligence.memory_after_task_enabled",
        "memory_intelligence.skill_after_task_enabled",
        "activity_capture.enabled",
        "activity_capture.start_at_startup",
        "meeting_detection.enabled",
        "meeting_detection.start_at_startup",
        "meeting_detection.mode",
        "behavior.enable_voice_listener_at_startup",
    }
    for path in EXPRESS_SETTING_PATHS:
        assert path in POLICIES, f"{path} is written by express setup but is not in the app-control registry"


def _receipt(preferences, installed=()):
    fake = _Environment(installed=installed, preferences=preferences)
    return {item.id: item for item in build_receipt(ExpressPlanner(fake.environment).download_specs(), preferences).items}


def test_the_receipt_of_an_untouched_install_shows_everything_off_except_hotkeys():
    receipt = _receipt(Preferences())

    for item_id in (DOWNLOAD_THINKING, LEARN_MEMORY, LEARN_SKILLS, CAPTURE_ACTIVITY, DETECT_MEETINGS, VOICE_LISTENER):
        assert receipt[item_id].state == "off", item_id
    assert receipt[HOTKEYS].state == "on"
    assert receipt[DOWNLOAD_THINKING].detail == "Not on this Mac yet."
    assert receipt[HOTKEYS].where_to_change == "Settings, General, Hotkeys"
    assert receipt[CAPTURE_ACTIVITY].where_to_change == "Settings, General, Home"


def test_the_receipt_reads_real_state_for_every_item():
    preferences = Preferences()
    preferences.activity_capture.enabled = True
    preferences.meeting_detection.enabled = True
    preferences.meeting_detection.start_at_startup = True
    preferences.behavior.enable_voice_listener_at_startup = True
    preferences.behavior.enable_monitoring_at_startup = False
    preferences.memory_intelligence.skill_after_task_enabled = True

    receipt = _receipt(preferences, installed=(THINKING_ID,))

    assert receipt[DOWNLOAD_THINKING].state == "on"
    assert receipt[DOWNLOAD_THINKING].detail == "Qwen 3.5 9B is on this Mac."
    assert receipt[CAPTURE_ACTIVITY].state == "partial"
    assert receipt[CAPTURE_ACTIVITY].detail == "In the Basil menu. You start it yourself."
    assert receipt[DETECT_MEETINGS].state == "on"
    assert receipt[VOICE_LISTENER].state == "on"
    assert receipt[HOTKEYS].state == "off"
    assert receipt[HOTKEYS].detail == "Hotkeys are off."
    assert receipt[LEARN_SKILLS].state == "on"
    assert receipt[LEARN_MEMORY].state == "off"
