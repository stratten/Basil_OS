"""A failing setup tool must come back to the agent as a recoverable result, not abort the turn."""

import asyncio

import pytest

from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
    build_setup_agent_system_prompt,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling.tool_registry import (
    create_setup_agent_tools_for_factory,
)

MAIL_ERROR = 'Mail got an error: Can\u2019t get mailbox "sent". (-1728)'


class FailingFactory:
    """Every tool method raises, except the ones a test overrides."""

    def __getattr__(self, name):
        async def raises(*args, **kwargs):
            raise RuntimeError(MAIL_ERROR)

        return raises


def tool_named(factory, name):
    return next(tool for tool in create_setup_agent_tools_for_factory(factory) if tool.name == name)


def test_a_raising_tool_returns_a_corrective_result_instead_of_raising():
    tool = tool_named(FailingFactory(), "discover_writing_sample_candidates")

    result = asyncio.run(tool.ainvoke({}))

    assert "`discover_writing_sample_candidates` tool failed" in result
    assert MAIL_ERROR in result
    assert "Never claim the failed step succeeded" in result


def test_a_healthy_tool_result_is_returned_unchanged():
    class HealthyFactory(FailingFactory):
        async def discover_setup_connections(self):
            return {"facts": ["connection-a"]}

    tool = tool_named(HealthyFactory(), "discover_connections")

    assert asyncio.run(tool.ainvoke({})) == {"facts": ["connection-a"]}


def test_cancellation_still_propagates_through_the_recovery_wrapper():
    class CancelingFactory(FailingFactory):
        async def discover_setup_connections(self):
            raise asyncio.CancelledError()

    tool = tool_named(CancelingFactory(), "discover_connections")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tool.ainvoke({}))


def test_system_prompt_tells_the_agent_to_recover_from_tool_failures():
    assert "Recover when a tool fails" in build_setup_agent_system_prompt()
