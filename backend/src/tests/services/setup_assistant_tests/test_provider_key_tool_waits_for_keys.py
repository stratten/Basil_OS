"""The setup assistant's key check waits for the app's Keychain keys before it decides a key is missing."""

import json
from unittest.mock import AsyncMock

import pytest

from api.services.setup_assistant.agent_graph.setup_agent_tooling import provider_key_tools


@pytest.mark.asyncio
async def test_the_check_waits_for_the_apps_keys_before_reading_the_stored_key(monkeypatch):
    waiter = AsyncMock(return_value=True)
    monkeypatch.setattr("config.api_keys.await_provider_keys_ready", waiter)
    monkeypatch.setattr(provider_key_tools, "_stored_key_for", lambda provider: "")

    payload = json.loads(await provider_key_tools.check_provider_key(None, "openai"))

    waiter.assert_awaited_once()
    assert payload["category"] == "no_key"
