"""The app_settings tool is registered, loadable as a family, and not a core tool."""

import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import register_optional_tools
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
    CORE_TOOL_NAMES,
    get_family_definitions,
)
from api.services.agent_processing.tools.internal_basil_tools import app_settings_tool
from api.routes.registry import build_ordered_application_routers


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def test_the_registry_registers_the_tool_without_warnings():
    tools, tool_map, warnings = [], {}, []
    factory = SimpleNamespace(
        logger=_Logger(),
        profile=None,
        current_agent_task_id="turn-1",
        current_root_task_id="root-1",
        agent_task_submission_service=SimpleNamespace(),
    )
    register_optional_tools(factory, tools, tool_map, warnings)
    assert tool_map["app_settings.manage"].name == "app_settings"
    assert not any("app settings" in warning for warning in warnings)


def test_it_is_a_loadable_family_and_not_core():
    assert "app_settings" not in CORE_TOOL_NAMES
    families = {family.name: family for family in get_family_definitions()}
    assert families["app_settings"].tool_names == ("app_settings",)


def test_the_resolve_route_is_mounted():
    from api.routes.app_control_routes import router

    assert router in build_ordered_application_routers()


@pytest.mark.asyncio
async def test_the_tool_lists_sets_and_undoes_through_the_engine(engine, memory_preferences, monkeypatch):
    monkeypatch.setattr(app_settings_tool, "get_app_control_engine", lambda: engine)
    listing = json.loads(await app_settings_tool._app_settings_impl("list", query="primary"))
    assert listing["settings"][0]["key"] == "appearance.primary_color"
    changes = [app_settings_tool.AppSettingsChange(key="appearance.primary_color", value="#FF69B4")]
    done = json.loads(await app_settings_tool._app_settings_impl("set", changes=changes, reason="pink please"))
    assert done["ok"] and done["applied"]
    assert json.loads(await app_settings_tool._app_settings_impl("undo"))["ok"]
    assert not json.loads(await app_settings_tool._app_settings_impl("get"))["ok"]
    assert not json.loads(await app_settings_tool._app_settings_impl("set"))["ok"]


@pytest.mark.asyncio
async def test_an_unexpected_failure_is_reported_without_a_traceback(monkeypatch):
    class Broken:
        def list_entries(self, query):
            raise RuntimeError("boom")

    monkeypatch.setattr(app_settings_tool, "get_app_control_engine", lambda: Broken())
    result = json.loads(await app_settings_tool._app_settings_impl("list"))
    assert result["ok"] is False and "boom" not in result["error"]
