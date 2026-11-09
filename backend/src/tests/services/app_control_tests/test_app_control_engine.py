"""The engine: tiers, atomic batches, the contrast rule, rate limit, approval outcomes, drift after approval, and undo."""

import pytest

from api.services.app_control.engine import MAX_CHANGES_PER_CALL, RATE_LIMIT_CHANGES

PINK = "#FF69B4"


@pytest.mark.asyncio
async def test_a_cosmetic_change_applies_publishes_and_journals(engine, memory_preferences, published):
    result = await engine.apply([{"key": "appearance.primary_color", "value": PINK}], reason="user asked")
    assert result["ok"] and result["applied"] and not result["approved_by_user"]
    assert result["changes"][0]["after"] == PINK
    assert memory_preferences.current.ui.primary_color_red == pytest.approx(1.0)
    assert memory_preferences.saves == 1
    assert len(published) == 1
    assert engine.journal.get(result["change_id"])["reason"] == "user asked"


@pytest.mark.asyncio
async def test_a_cosmetic_change_never_asks_for_approval(engine, approvals):
    await engine.apply([{"key": "appearance.text_scale", "value": 1.25}])
    assert approvals.requests == []


@pytest.mark.asyncio
async def test_a_no_op_batch_changes_nothing(engine, memory_preferences):
    result = await engine.apply([{"key": "appearance.text_scale", "value": 1.0}])
    assert result["ok"] and result["applied"] is False
    assert memory_preferences.saves == 0
    assert engine.journal.recent(5) == []


@pytest.mark.asyncio
async def test_a_batch_with_one_bad_item_applies_nothing(engine, memory_preferences):
    result = await engine.apply(
        [
            {"key": "appearance.primary_color", "value": PINK},
            {"key": "appearance.text_scale", "value": 7},
        ]
    )
    assert not result["ok"]
    assert result["problems"][0]["key"] == "appearance.text_scale"
    assert memory_preferences.saves == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested",
    [None, [], "x", [{"key": "appearance.text_scale"}], [{"value": 1.0}], ["appearance.text_scale"], [{"key": 5, "value": 1}]],
)
async def test_malformed_requests_are_rejected(engine, requested):
    result = await engine.apply(requested)
    assert not result["ok"]


@pytest.mark.asyncio
async def test_unknown_duplicate_and_human_only_keys_are_rejected(engine, memory_preferences):
    unknown = await engine.apply([{"key": "appearance.nope", "value": 1}])
    assert "Unknown" in unknown["problems"][0]["problem"]
    duplicate = await engine.apply([{"key": "appearance.text_scale", "value": 1.1}, {"key": "appearance.text_scale", "value": 1.25}])
    assert "more than once" in duplicate["problems"][0]["problem"]
    human = await engine.apply([{"key": "security.command_approval", "value": "all"}])
    assert "cannot be changed by an agent" in human["problems"][0]["problem"]
    assert memory_preferences.saves == 0


@pytest.mark.asyncio
async def test_too_many_changes_in_one_call_are_rejected(engine):
    many = [{"key": "appearance.text_scale", "value": 1.1}] * (MAX_CHANGES_PER_CALL + 1)
    assert "Too many" in (await engine.apply(many))["error"]


@pytest.mark.asyncio
async def test_unreadable_text_is_rejected_but_a_matching_palette_is_accepted(engine, memory_preferences):
    bad = await engine.apply([{"key": "appearance.background_color", "value": "#FFFFFF"}])
    assert not bad["ok"] and "contrast" in bad["error"]
    assert memory_preferences.saves == 0
    good = await engine.apply(
        [
            {"key": "appearance.background_color", "value": "#FFFFFF"},
            {"key": "appearance.text_color", "value": "#000000"},
        ]
    )
    assert good["ok"] and good["applied"]


@pytest.mark.asyncio
async def test_a_behavioral_change_waits_for_approval_and_applies_when_approved(engine, approvals, memory_preferences):
    result = await engine.apply([{"key": "appearance.agent_task_chain_expansion", "value": "multiple"}], reason="compare turns")
    assert result["ok"] and result["approved_by_user"]
    request = approvals.requests[0]
    assert request.tier == "behavioral" and request.reason == "compare turns"
    assert request.changes[0]["before"] == "single" and request.changes[0]["after"] == "multiple"
    assert memory_preferences.current.ui.agent_task_chain_expansion == "multiple"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["denied", "timed_out", "unavailable"])
async def test_an_unapproved_change_applies_nothing_and_is_not_journaled(engine, approvals, memory_preferences, outcome):
    approvals.outcome = outcome
    result = await engine.apply(
        [
            {"key": "appearance.agent_task_chain_expansion", "value": "multiple"},
            {"key": "appearance.primary_color", "value": PINK},
        ]
    )
    assert not result["ok"] and result["outcome"] == outcome
    assert memory_preferences.saves == 0
    assert engine.journal.recent(5) == []


@pytest.mark.asyncio
async def test_a_setting_that_changes_while_the_user_decides_is_not_overwritten(engine, approvals, memory_preferences):
    def user_changes_it_meanwhile():
        memory_preferences.current.ui.agent_task_chain_expansion = "multiple"

    approvals.before_answer = user_changes_it_meanwhile
    result = await engine.apply([{"key": "appearance.agent_task_chain_expansion", "value": "multiple"}, {"key": "appearance.text_scale", "value": 1.25}])
    # The behavioral item now already matches, so it drops out as a no-op at plan time only if read earlier; it was read earlier as "single", so this must be reported as stale.
    assert not result["ok"] and result["outcome"] == "stale"
    assert memory_preferences.saves == 0


@pytest.mark.asyncio
async def test_the_rate_limit_blocks_a_flood(engine):
    for index in range(RATE_LIMIT_CHANGES):
        engine.journal.record(agent_task_id=None, reason="", approved_by_user=False, changes=[{"key": f"k{index}"}])
    result = await engine.apply([{"key": "appearance.text_scale", "value": 1.25}])
    assert not result["ok"] and "Too many setting changes" in result["error"]


@pytest.mark.asyncio
async def test_undo_restores_the_exact_original_floats_and_republishes(engine, memory_preferences, published):
    original = memory_preferences.current.ui.primary_color_green
    applied = await engine.apply([{"key": "appearance.primary_color", "value": PINK}])
    undone = await engine.undo()
    assert undone["ok"] and undone["undone"] == applied["change_id"]
    assert memory_preferences.current.ui.primary_color_green == original
    assert len(published) == 2
    assert engine.journal.get(applied["change_id"])["undone"] is True


@pytest.mark.asyncio
async def test_undo_refuses_after_the_setting_changed_again(engine, memory_preferences):
    await engine.apply([{"key": "appearance.text_scale", "value": 1.25}])
    memory_preferences.current.ui.text_scale = 1.4
    refused = await engine.undo()
    assert not refused["ok"] and "changed since" in refused["error"]
    assert memory_preferences.current.ui.text_scale == 1.4


@pytest.mark.asyncio
async def test_undo_with_nothing_to_undo_or_twice_is_refused(engine):
    assert not (await engine.undo())["ok"]
    applied = await engine.apply([{"key": "appearance.text_scale", "value": 1.25}])
    assert (await engine.undo(applied["change_id"]))["ok"]
    assert "already undone" in (await engine.undo(applied["change_id"]))["error"]
    assert not (await engine.undo("chg-missing"))["ok"]


@pytest.mark.asyncio
async def test_undo_needs_no_approval_even_for_a_behavioral_change(engine, approvals, memory_preferences):
    await engine.apply([{"key": "appearance.agent_task_chain_expansion", "value": "multiple"}])
    asked = len(approvals.requests)
    assert (await engine.undo())["ok"]
    assert len(approvals.requests) == asked
    assert memory_preferences.current.ui.agent_task_chain_expansion == "single"


def test_list_and_get_never_reveal_a_human_only_value(engine):
    listing = engine.list_entries("approval")
    by_key = {item["key"]: item for item in listing["settings"]}
    assert "current" not in by_key["security.command_approval"]
    assert by_key["security.command_approval"]["changeable"] is False
    listing = engine.list_entries("")
    by_key = {item["key"]: item for item in listing["settings"]}
    assert by_key["appearance.primary_color"]["current"].startswith("#")
    assert by_key["appearance.agent_task_chain_expansion"]["needs_approval"] is True
    assert engine.get_entries(["appearance.nope"])["ok"] is False
    assert engine.list_entries("font")["count"] == 1


@pytest.mark.asyncio
async def test_a_failing_publisher_does_not_lose_a_saved_change(memory_preferences, approvals, tmp_path):
    from api.services.app_control.engine import AppControlEngine
    from api.services.app_control.entries import build_default_registry
    from api.services.app_control.journal import ChangeJournal

    async def broken(_preferences):
        raise RuntimeError("socket gone")

    engine = AppControlEngine(
        registry=build_default_registry(),
        journal=ChangeJournal(tmp_path / "j.json"),
        approval_manager=approvals,
        publishers={"appearance": broken},
        change_notifier=None,
    )
    result = await engine.apply([{"key": "appearance.text_scale", "value": 1.25}])
    assert result["ok"] and memory_preferences.current.ui.text_scale == 1.25


@pytest.mark.asyncio
async def test_a_privacy_setting_asks_and_runs_its_apply_hook(memory_preferences, approvals, tmp_path):
    from api.services.app_control.engine import AppControlEngine
    from api.services.app_control.entries import build_default_registry
    from api.services.app_control.journal import ChangeJournal

    ran = []

    async def hook(preferences):
        ran.append(preferences.meeting_detection.enabled)

    engine = AppControlEngine(
        registry=build_default_registry(),
        journal=ChangeJournal(tmp_path / "j.json"),
        approval_manager=approvals,
        publishers={"meeting_detection": hook},
        change_notifier=None,
    )
    result = await engine.apply([{"key": "meeting_detection.enabled", "value": True}], reason="user asked")
    assert result["ok"] and approvals.requests[0].tier == "privacy"
    assert ran == [True] and memory_preferences.current.meeting_detection.enabled is True
    assert (await engine.undo())["ok"]
    assert ran == [True, False] and memory_preferences.current.meeting_detection.enabled is False


@pytest.mark.asyncio
async def test_an_enum_setting_is_stored_and_restored_as_its_enum(engine, memory_preferences):
    from api.core.models.preferences import BrowserPreferredUserBrowser

    await engine.apply([{"key": "browser_automation.preferred_user_browser", "value": "safari"}])
    assert memory_preferences.current.browser_automation.preferred_user_browser is BrowserPreferredUserBrowser.SAFARI
    assert (await engine.undo())["ok"]
    assert memory_preferences.current.browser_automation.preferred_user_browser is BrowserPreferredUserBrowser.SYSTEM_DEFAULT


@pytest.mark.asyncio
async def test_a_human_only_schema_setting_is_refused_with_where_to_change_it(engine, memory_preferences):
    result = await engine.apply([{"key": "tool_execution.auto_approve_read_only", "value": True}])
    assert not result["ok"]
    assert "cannot be changed by an agent" in result["problems"][0]["problem"]
    assert "Permissions" in result["problems"][0]["problem"]
    assert memory_preferences.saves == 0


def test_an_unqualified_list_shows_only_changeable_settings_and_is_capped(engine):
    listing = engine.list_entries("")
    assert listing["truncated"] is True and len(listing["settings"]) == 40
    assert all(item["changeable"] for item in listing["settings"])
    searched = engine.list_entries("auto approve read only")
    assert [item["key"] for item in searched["settings"]] == ["tool_execution.auto_approve_read_only"]
    assert searched["settings"][0]["changeable"] is False and "current" not in searched["settings"][0]


@pytest.mark.asyncio
async def test_clients_are_told_which_keys_changed_on_apply_and_on_undo_but_not_on_refusals(engine, approvals, announced):
    await engine.apply([{"key": "appearance.text_scale", "value": 1.25}, {"key": "appearance.primary_color", "value": PINK}])
    assert announced == [["appearance.text_scale", "appearance.primary_color"]]
    await engine.undo()
    assert len(announced) == 2
    await engine.apply([{"key": "appearance.text_scale", "value": 1.0}])  # already the value after undo: a no-op
    approvals.outcome = "denied"
    await engine.apply([{"key": "appearance.agent_task_chain_expansion", "value": "multiple"}])
    await engine.apply([{"key": "appearance.nope", "value": 1}])
    assert len(announced) == 2


@pytest.mark.asyncio
async def test_a_failing_announcement_does_not_lose_a_saved_change(memory_preferences, approvals, tmp_path):
    from api.services.app_control.engine import AppControlEngine
    from api.services.app_control.entries import build_default_registry
    from api.services.app_control.journal import ChangeJournal

    async def broken(_keys):
        raise RuntimeError("no sockets")

    engine = AppControlEngine(
        registry=build_default_registry(),
        journal=ChangeJournal(tmp_path / "j.json"),
        approval_manager=approvals,
        publishers={},
        change_notifier=broken,
    )
    result = await engine.apply([{"key": "appearance.text_scale", "value": 1.25}])
    assert result["ok"] and memory_preferences.current.ui.text_scale == 1.25
