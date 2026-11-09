"""The processing bubble's colors are a status signal: an agent may change them only when the user names the bubble, only on their own, and only after the user approves."""

import pytest

PALETTE = [
    {"key": "appearance.primary_color", "value": "#FF69B4"},
    {"key": "appearance.secondary_color", "value": "#FFB6D9"},
]
BUBBLE = {"key": "appearance.processing_color", "value": "#FF1493"}
ACCENT = {"key": "appearance.processing_accent_color", "value": "#FFD1E8"}


def _bubble_values(preferences):
    ui = preferences.current.ui
    return (ui.processing_color_red, ui.processing_color_green, ui.processing_color_blue)


@pytest.mark.asyncio
async def test_a_palette_change_cannot_carry_the_bubble_along(engine, approvals, memory_preferences, published, announced):
    before = _bubble_values(memory_preferences)
    result = await engine.apply(PALETTE + [BUBBLE], reason="You asked for a pink palette.")
    assert result["ok"] is False
    assert "on its own" in str(result) and "nothing else" in str(result)
    assert _bubble_values(memory_preferences) == before
    assert memory_preferences.current.ui.primary_color_red != 1.0, "no part of the refused batch was applied"
    assert approvals.requests == [] and published == [] and announced == []


@pytest.mark.asyncio
async def test_a_palette_change_without_the_bubble_leaves_the_bubble_alone(engine, memory_preferences):
    before = _bubble_values(memory_preferences)
    result = await engine.apply(PALETTE, reason="You asked for a pink palette.")
    assert result["ok"] is True
    assert _bubble_values(memory_preferences) == before


@pytest.mark.asyncio
async def test_the_bubble_changes_on_its_own_only_after_the_user_approves_and_the_card_shows_the_change(engine, approvals, memory_preferences):
    result = await engine.apply([BUBBLE], reason="You asked to change the processing bubble color.")
    assert result["ok"] is True
    assert len(approvals.requests) == 1
    assert _bubble_values(memory_preferences) != (0.486, 0.227, 0.929)
    assert "#FF1493" in str(approvals.requests[0].__dict__)


@pytest.mark.asyncio
async def test_a_declined_bubble_change_changes_nothing(engine, approvals, memory_preferences):
    approvals.outcome = "denied"
    before = _bubble_values(memory_preferences)
    result = await engine.apply([BUBBLE], reason="You asked to change the processing bubble color.")
    assert result["ok"] is False
    assert _bubble_values(memory_preferences) == before


@pytest.mark.asyncio
async def test_the_bubble_color_and_its_accent_may_be_changed_together(engine, approvals, memory_preferences):
    result = await engine.apply([BUBBLE, ACCENT], reason="You asked to change the processing bubble colors.")
    assert result["ok"] is True
    assert len(approvals.requests) == 1


@pytest.mark.asyncio
async def test_the_bubble_change_can_be_undone_without_asking_again(engine, approvals, memory_preferences):
    before = _bubble_values(memory_preferences)
    await engine.apply([BUBBLE], reason="You asked to change the processing bubble color.")
    approvals.requests.clear()
    undone = await engine.undo()
    assert undone["ok"] is True
    assert approvals.requests == []
    assert _bubble_values(memory_preferences) == pytest.approx(before, abs=1e-6)


def test_the_agent_is_told_when_it_may_touch_the_bubble(engine):
    listed = engine.list_entries("processing bubble")
    bubble = next(item for item in listed["settings"] if item["key"] == "appearance.processing_color")
    assert bubble["tier"] == "behavioral" and bubble["needs_approval"] is True and bubble["changeable"] is True
    assert "names the processing bubble" in bubble["description"]
    assert "leave it out" in bubble["description"]
