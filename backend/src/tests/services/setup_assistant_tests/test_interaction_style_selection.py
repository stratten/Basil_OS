"""The last setup preferences step offers selectable statements about how the user likes to work with an assistant."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.setup_assistant.agent_graph.agenda_catalog import SETUP_AGENDA_CATALOG
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.interaction_style_catalog import (
    INTERACTION_STYLE_GROUPS,
    resolve_interaction_style,
)

client = TestClient(app)
STYLE_URL = "/setup-assistant/interaction-style"


def test_catalog_has_unique_ids_and_a_single_choice_group_for_exclusive_questions():
    group_ids = [group.id for group in INTERACTION_STYLE_GROUPS]
    assert len(group_ids) == len(set(group_ids))
    for group in INTERACTION_STYLE_GROUPS:
        option_ids = [option.id for option in group.options]
        assert len(option_ids) == len(set(option_ids))
        assert all(option.label and option.instruction for option in group.options)
    assert {group.id: group.multiple for group in INTERACTION_STYLE_GROUPS} == {
        "length": False,
        "format": True,
        "checkins": False,
        "tone": False,
    }


def test_resolve_returns_instructions_in_catalog_order():
    instructions = resolve_interaction_style({"format": ["tables", "bullets"], "length": ["short"]})

    assert instructions == [
        "Lead with the answer in one or two sentences and keep replies short.",
        "Use bullet lists for anything with more than three items.",
        "Use a table when comparing options side by side.",
    ]


def test_resolve_accepts_an_empty_selection():
    assert resolve_interaction_style({}) == []
    assert resolve_interaction_style({"length": []}) == []


@pytest.mark.parametrize(
    "selections",
    [
        {"mood": ["happy"]},
        {"length": ["enormous"]},
        {"length": ["short", "thorough"]},
        {"format": ["bullets", "bullets"]},
    ],
)
def test_resolve_rejects_unknown_or_conflicting_choices(selections):
    with pytest.raises(ValueError):
        resolve_interaction_style(selections)


def test_get_serves_the_catalog_without_the_saved_instructions():
    response = client.get(STYLE_URL)

    assert response.status_code == 200
    groups = response.json()["groups"]
    assert [group["id"] for group in groups] == ["length", "format", "checkins", "tone"]
    assert groups[1]["multiple"] is True
    assert all(set(option) == {"id", "label"} for group in groups for option in group["options"])


def test_post_saves_the_chosen_instructions_as_bullets():
    with patch("api.routes.setup_assistant.interaction_style_routes.save_interaction_preferences", new=AsyncMock()) as save:
        response = client.post(STYLE_URL, json={"selections": {"length": ["short"], "tone": ["direct"]}})

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert len(body["instructions"]) == 2
    save.assert_awaited_once_with("\n".join(f"- {instruction}" for instruction in body["instructions"]))


def test_post_with_nothing_chosen_never_overwrites_existing_preferences():
    with patch("api.routes.setup_assistant.interaction_style_routes.save_interaction_preferences", new=AsyncMock()) as save:
        response = client.post(STYLE_URL, json={"selections": {}})

    assert response.status_code == 200
    assert response.json() == {"saved": False, "instructions": []}
    save.assert_not_awaited()


def test_post_rejects_an_invalid_choice_without_saving():
    with patch("api.routes.setup_assistant.interaction_style_routes.save_interaction_preferences", new=AsyncMock()) as save:
        response = client.post(STYLE_URL, json={"selections": {"length": ["short", "thorough"]}})

    assert response.status_code == 422
    save.assert_not_awaited()


def test_post_reports_a_save_that_the_profile_cannot_hold():
    failing = AsyncMock(side_effect=ValueError("Interaction preferences are too long"))
    with patch("api.routes.setup_assistant.interaction_style_routes.save_interaction_preferences", new=failing):
        response = client.post(STYLE_URL, json={"selections": {"length": ["short"]}})

    assert response.status_code == 422
    assert "too long" in response.json()["detail"]


def test_prompt_tells_the_agent_to_follow_the_chosen_style_and_not_re_ask_it():
    prompt = build_setup_agent_system_prompt()

    assert "`interaction_style`" in prompt
    assert "never ask those questions again" in prompt
    assert "Include every instruction from `interaction_style` in the bullets" in prompt


def test_interview_agenda_item_no_longer_asks_for_length_or_format():
    item = next(item for item in SETUP_AGENDA_CATALOG if item.id == "learn_interaction_preferences")

    assert "do not ask those again" in item.intent
    assert "short answer, bullets, prose, tables" not in item.intent
