"""The setup prompt tells the agent what a sidebar click means and keeps the sidebar's "Working now" and "Your turn" labels honest."""

from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt


def _prompt() -> str:
    return build_setup_agent_system_prompt()


def test_a_sidebar_click_is_treated_as_the_users_choice():
    prompt = _prompt()

    assert 'Let\'s do "<title>" next.' in prompt
    assert "Treat it as their choice, not a suggestion" in prompt
    assert "mark_agenda_item(id, 'in_progress')" in prompt


def test_the_agent_does_not_leave_an_item_in_progress_after_moving_on():
    prompt = _prompt()

    assert "as \"Working now\" while you are mid-turn" in prompt
    assert "never leave an item `in_progress` after you have moved on from it" in prompt
    assert "Keep at most one item `in_progress`" in prompt


def test_reshaping_the_list_is_said_out_loud():
    prompt = _prompt()

    assert "say so in one short sentence" in prompt
