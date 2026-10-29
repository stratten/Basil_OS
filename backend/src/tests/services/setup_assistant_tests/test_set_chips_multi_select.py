"""set_chips can mark a chip row as multi-select so non-exclusive answers can be combined."""

import asyncio

from api.routes.setup_assistant.models import SetupAgentEventKind
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.agent_graph.setup_agent_tooling import presentation_tools
from api.services.setup_assistant.agent_graph.setup_agent_tooling.schemas import (
    SetupSetChipsInput,
    SetupSuggestionChipInput,
)


class _Factory:
    def __init__(self):
        self.events = []

    async def event_emitter(self, event):
        self.events.append(event)


def _chips():
    return [
        SetupSuggestionChipInput(id="wordy", label="Too wordy", message="They are too wordy."),
        SetupSuggestionChipInput(id="confirm", label="Too many confirmations", message="They ask too often."),
    ]


def _emit(**kwargs):
    factory = _Factory()
    asyncio.run(presentation_tools.set_setup_suggestion_chips(factory, _chips(), **kwargs))
    assert len(factory.events) == 1
    assert factory.events[0].kind == SetupAgentEventKind.chips_set
    return factory.events[0].payload


def test_chips_are_single_select_by_default():
    payload = _emit()

    assert payload["multi_select"] is False
    assert [chip["id"] for chip in payload["chips"]] == ["wordy", "confirm"]


def test_multi_select_is_carried_on_the_event_payload():
    payload = _emit(multi_select=True)

    assert payload["multi_select"] is True
    assert all(chip["preliminary_status_message"] for chip in payload["chips"])


def test_the_tool_schema_exposes_multi_select_and_defaults_it_off():
    assert SetupSetChipsInput(chips=[]).multi_select is False
    assert SetupSetChipsInput(chips=[], multi_select=True).multi_select is True
    assert "multi_select" in SetupSetChipsInput.model_json_schema()["properties"]


def test_the_prompt_tells_the_agent_to_use_multi_select_for_non_exclusive_questions():
    prompt = build_setup_agent_system_prompt()

    assert "`multi_select=true`" in prompt
    assert "too wordy and too many confirmation requests can both be true" in prompt


def test_prompt_points_to_the_panel_field_instead_of_the_main_message_box() -> None:
    from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
        SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT,
    )

    assert "Something else?" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "never tell the user to type their own answer in the main message box" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT


def test_prompt_asks_about_other_services_without_overpromising_connection_setup() -> None:
    from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
        SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT,
    )

    assert "which other apps, services, or platforms they use regularly" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "start_connection_auth" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "never guess or reconstruct an address from memory" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "never ask them to type a password, token, or API key into the chat" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "only say the service is connected when it appears as connected" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT


def test_prompt_separates_read_only_auto_approval_from_the_approval_question() -> None:
    from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
        SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT,
    )

    assert "Never put read-only auto-approval among those chips" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "separate, yes or no follow-up in a new turn" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
