"""The installed-apps signal reads names only, and the setup agent's local-server and offer guidance names no specific app."""

from __future__ import annotations

from pathlib import Path

import pytest

import api.main  # noqa: F401  (loads the route and service modules in their supported order)
from api.services.setup_assistant import installed_apps_discovery
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT
from api.services.setup_assistant.agent_graph.setup_agent_tooling.tool_registry import create_setup_agent_tools_for_factory


def _make_apps(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).mkdir()


@pytest.mark.asyncio
async def test_only_app_bundle_names_are_listed_sorted_and_deduplicated_across_folders(tmp_path) -> None:
    system_apps = tmp_path / "Applications"
    user_apps = tmp_path / "User Applications"
    _make_apps(system_apps, ["Zeta.app", "alpha.app", "Notes.txt", ".Hidden.app"])
    _make_apps(user_apps, ["Alpha.app", "Beta.app"])

    response = await installed_apps_discovery.collect_installed_app_facts([system_apps, user_apps, tmp_path / "missing"])

    assert len(response.facts) == 1
    fact = response.facts[0]
    assert fact.metadata["role"] == "installed_apps"
    assert fact.metadata["app_names"] == "alpha; Beta; Zeta"
    assert fact.value == "3"


@pytest.mark.asyncio
async def test_a_very_long_list_is_capped_and_says_how_many_exist(tmp_path) -> None:
    _make_apps(tmp_path, [f"App{index:04d}.app" for index in range(installed_apps_discovery.MAX_LISTED_APPS + 25)])

    fact = (await installed_apps_discovery.collect_installed_app_facts([tmp_path])).facts[0]

    assert fact.metadata["listed_count"] == str(installed_apps_discovery.MAX_LISTED_APPS)
    assert fact.metadata["total_count"] == str(installed_apps_discovery.MAX_LISTED_APPS + 25)
    assert len(fact.metadata["app_names"].split("; ")) == installed_apps_discovery.MAX_LISTED_APPS


@pytest.mark.asyncio
async def test_no_installed_apps_yields_no_fact(tmp_path) -> None:
    assert (await installed_apps_discovery.collect_installed_app_facts([tmp_path])).facts == []


def test_the_agent_can_call_the_installed_apps_tool() -> None:
    class Factory:
        def __getattr__(self, name):
            async def _unused(*args, **kwargs):
                return {}

            return _unused

    names = {tool.name for tool in create_setup_agent_tools_for_factory(Factory())}
    assert "discover_installed_apps" in names


def test_the_prompt_guides_local_servers_and_offers_without_naming_any_app() -> None:
    prompt = SETUP_AGENT_LANGCHAIN_SYSTEM_PROMPT

    assert "register_local_mcp_server" in prompt
    assert "discover_installed_apps" in prompt
    assert "never promise a capability, a connector, or a workflow that does not exist" in prompt
    assert "whatsapp" not in prompt.lower()
