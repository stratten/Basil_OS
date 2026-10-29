"""The setup agent is steered toward the calendar app Paprika can actually use, and knows when a task is revising itself."""

from __future__ import annotations

import pytest

import api.main  # noqa: F401  (loads the route and service modules in their supported order)
from api.services.setup_assistant import calendar_app_discovery
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT


def _patch_apps(monkeypatch, installed: set[str], running: set[str]) -> None:
    monkeypatch.setattr(
        calendar_app_discovery,
        "_is_installed",
        lambda definition: definition.name in installed,
    )

    async def fake_running(process_name: str) -> bool:
        return process_name in running

    monkeypatch.setattr(calendar_app_discovery, "_is_running", fake_running)


@pytest.mark.asyncio
async def test_outlook_running_does_not_hide_apple_calendar_and_is_marked_limited(monkeypatch) -> None:
    _patch_apps(monkeypatch, installed={"Calendar", "Microsoft Outlook"}, running={"Microsoft Outlook"})

    response = await calendar_app_discovery.collect_calendar_app_facts()

    by_name = {fact.value: fact for fact in response.facts}
    assert set(by_name) == {"Calendar", "Microsoft Outlook"}
    assert by_name["Calendar"].metadata["scripting_reliability"] == "high"
    assert by_name["Calendar"].metadata["is_running"] == "false"
    assert by_name["Microsoft Outlook"].metadata["scripting_reliability"] == "limited"
    assert by_name["Microsoft Outlook"].metadata["is_running"] == "true"
    assert "recurring series once" in by_name["Microsoft Outlook"].metadata["guidance"]
    assert all(fact.metadata["role"] == "calendar_app" for fact in response.facts)


@pytest.mark.asyncio
async def test_apps_that_are_not_installed_are_not_reported(monkeypatch) -> None:
    _patch_apps(monkeypatch, installed={"Calendar"}, running=set())

    response = await calendar_app_discovery.collect_calendar_app_facts()

    assert [fact.value for fact in response.facts] == ["Calendar"]


@pytest.mark.asyncio
async def test_no_calendar_apps_gives_an_empty_result(monkeypatch) -> None:
    _patch_apps(monkeypatch, installed=set(), running=set())

    response = await calendar_app_discovery.collect_calendar_app_facts()

    assert response.facts == []


def test_the_setup_agent_has_a_calendar_discovery_tool_that_returns_the_facts() -> None:
    import asyncio

    from api.services.setup_assistant.agent_graph.setup_agent_tooling.tool_registry import (
        create_setup_agent_tools_for_factory,
    )

    class Factory:
        async def discover_setup_calendar_apps(self):
            return {"facts": [{"value": "Calendar"}]}

        def __getattr__(self, name):
            async def unused(*args, **kwargs):
                return None

            return unused

    tool = next(tool for tool in create_setup_agent_tools_for_factory(Factory()) if tool.name == "discover_calendar_apps")

    assert asyncio.run(tool.ainvoke({})) == {"facts": [{"value": "Calendar"}]}
    assert "before proposing any task that reads or changes the user's calendar" in tool.description.lower()


def test_the_factory_method_delegates_to_the_discovery_service() -> None:
    import asyncio

    from api.services.setup_assistant.agent_graph.setup_agent_tooling import discovery_tools

    class Service:
        async def collect_calendar_app_facts(self):
            from api.core.utc_time import utc_now_naive
            from api.routes.setup_assistant.models import SetupDiscoveryResponse

            return SetupDiscoveryResponse(facts=[], collected_at=utc_now_naive())

    class Factory:
        discovery_service = Service()

    result = asyncio.run(discovery_tools.discover_setup_calendar_apps(Factory()))

    assert result["facts"] == []


def test_prompt_steers_calendar_tasks_to_apple_calendar_and_away_from_outlook_schedule_reads() -> None:
    assert "call `discover_calendar_apps`" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "A running mail app is not a reason to use its calendar" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "Apple Calendar is the dependable choice" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "Never use a schedule-reading task on Outlook as a first Paprika demo" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "Dill's reply drafting already supports Outlook" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT


def test_prompt_tells_the_agent_what_to_say_when_a_task_is_revising_itself() -> None:
    assert "A launched Paprika task can revise its own work" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "they can wait for it or move on to another setup item in the meantime" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
    assert "do not propose a workaround while the revision is still running" in SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
