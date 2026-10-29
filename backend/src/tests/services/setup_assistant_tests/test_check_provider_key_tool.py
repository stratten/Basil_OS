"""The check_provider_key setup tool reports a diagnosis and never exposes the key."""

import json
from unittest.mock import patch

import pytest

from api.core.services import api_key_validation
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.agent_graph.setup_agent_tooling import provider_key_tools
from api.services.setup_assistant.agent_graph.setup_agent_tooling.tool_registry import create_setup_agent_tools_for_factory

SECRET = "sk-proj-" + "Z" * 48


class _QuotaError(Exception):
    status_code = 429
    code = "insufficient_quota"


def _stored(provider_to_key: dict):
    return patch.object(provider_key_tools, "_stored_key_for", lambda provider: provider_to_key.get(provider, ""))


@pytest.mark.asyncio
async def test_a_missing_key_is_reported_without_a_provider_call():
    with _stored({}), patch.object(api_key_validation, "call_provider_with_key") as call:
        result = json.loads(await provider_key_tools.check_provider_key(None, "openai"))

    assert result["category"] == "no_key"
    assert result["key_present"] is False
    call.assert_not_called()


@pytest.mark.asyncio
async def test_a_zero_credit_key_is_reported_as_no_credit_with_a_next_step():
    with _stored({"openai": SECRET}), patch.object(api_key_validation, "call_provider_with_key", side_effect=_QuotaError("insufficient_quota")):
        result = json.loads(await provider_key_tools.check_provider_key(None, "OpenAI"))

    assert result["category"] == "no_credit"
    assert result["usable"] is False
    assert "payment method" in result["next_step"]


@pytest.mark.asyncio
async def test_a_working_key_is_usable():
    with _stored({"anthropic": SECRET}), patch.object(api_key_validation, "call_provider_with_key"):
        result = json.loads(await provider_key_tools.check_provider_key(None, "anthropic"))

    assert (result["category"], result["usable"]) == ("valid", True)


@pytest.mark.asyncio
async def test_the_key_never_appears_in_the_result_even_when_the_provider_echoes_it():
    echoing = RuntimeError(f"Incorrect API key provided: {SECRET}")

    with _stored({"openai": SECRET}), patch.object(api_key_validation, "call_provider_with_key", side_effect=echoing):
        raw = await provider_key_tools.check_provider_key(None, "openai")

    assert SECRET not in raw
    assert SECRET[:16] not in raw
    assert json.loads(raw)["category"] == "invalid_key"


@pytest.mark.asyncio
async def test_an_unknown_provider_lists_the_supported_ones():
    result = json.loads(await provider_key_tools.check_provider_key(None, "mystery"))

    assert "supported_providers" in result


def test_the_tool_is_registered_and_the_prompt_names_it():
    class _Factory:
        def __getattr__(self, name):
            async def method(*args, **kwargs):
                return ""

            return method

    names = {tool.name for tool in create_setup_agent_tools_for_factory(_Factory())}

    assert "check_provider_key" in names
    assert "`check_provider_key(provider)`" in build_setup_agent_system_prompt()
