"""The onboarding prompt asks before suggesting, interviews like an assistant, and leans on general admin examples."""

import re

from api.services.setup_assistant.agent_graph.agenda_catalog import SETUP_AGENDA_CATALOG
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.context_catalog_service import SetupAssistantContextCatalogService


def _prompt() -> str:
    return build_setup_agent_system_prompt()


def test_paprika_examples_are_general_admin_tasks_not_project_tools():
    prompt = _prompt()

    assert "Have Paprika triage open PRs" not in prompt
    assert "GitHub PR sweep" not in prompt
    assert "Find recent GitHub PRs" not in prompt
    assert "using your GitHub and Linear connections" not in prompt
    for general_example in ("calendar event", "folder", "email"):
        assert general_example in prompt


def test_the_prompt_asks_what_the_user_wants_help_with_before_proposing_a_task():
    prompt = _prompt()

    assert "Ask first, then suggest" in prompt
    assert "what they would most like help with" in prompt


def test_every_agenda_id_named_in_the_prompt_exists_in_the_catalog():
    catalog_ids = {item.id for item in SETUP_AGENDA_CATALOG}
    named_ids = set(re.findall(r"`((?:learn|choose|literacy|setup_local|capture|confirm|connect)_[a-z_]+)`", _prompt()))

    assert named_ids, "the prompt should name agenda ids"
    assert named_ids <= catalog_ids, sorted(named_ids - catalog_ids)


def test_interview_agenda_items_exist_and_are_conversational():
    items = {item.id: item for item in SETUP_AGENDA_CATALOG}

    assert items["learn_interaction_preferences"].kind == "conversational"
    assert items["learn_help_priorities"].kind == "conversational"
    prompt = _prompt()
    assert "`learn_interaction_preferences`" in prompt
    assert "`learn_help_priorities`" in prompt
    assert "frustrates them most" in prompt
    assert "always run by them" in prompt


def test_the_interview_saves_answers_through_the_profile_tool_and_that_tool_is_registered():
    prompt = _prompt()
    tools = {tool.name for tool in SetupAssistantContextCatalogService().build_available_tools()}

    assert 'mutation_tool_name="save_profile_updates"' in prompt
    assert "interaction_preferences" in prompt
    assert "save_profile_updates" in tools


def test_prompt_explains_the_setup_change_resolved_observation():
    prompt = _prompt()

    assert "kind: setup_change_resolved" in prompt
    assert "never claim a `failed` change" in prompt
