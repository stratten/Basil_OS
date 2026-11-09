"""The stored_result tool is registered as a core tool so it is on the surface the moment a result is stored."""

from types import SimpleNamespace

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import register_optional_tools
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import CORE_TOOL_NAMES


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def _registered():
    tools, tool_map, warnings = [], {}, []
    factory = SimpleNamespace(
        logger=_Logger(),
        profile=None,
        current_agent_task_id="turn-1",
        current_root_task_id="root-1",
        agent_task_submission_service=SimpleNamespace(),
    )
    register_optional_tools(factory, tools, tool_map, warnings)
    return tools, tool_map, warnings


def test_the_registry_registers_the_tool_without_warnings():
    tools, tool_map, warnings = _registered()

    assert tool_map["stored_result.read"].name == "stored_result"
    assert any(tool.name == "stored_result" for tool in tools)
    assert not any("stored result" in warning for warning in warnings)


def test_it_is_a_core_tool_beside_the_checklist():
    assert "stored_result" in CORE_TOOL_NAMES
    assert "checklist" in CORE_TOOL_NAMES
