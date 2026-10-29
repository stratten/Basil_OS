"""Deleting a custom model removes the key Basil generated for it, and only that key."""

from unittest.mock import AsyncMock

import pytest

from api.routes.model_routes import custom_routes


@pytest.fixture
def key_writer(monkeypatch):
    writer = AsyncMock(return_value=True)
    monkeypatch.setattr(custom_routes, "aset_api_key", writer)
    return writer


def use_models(monkeypatch, models: dict) -> None:
    monkeypatch.setattr(custom_routes, "get_custom_models", lambda: models)


@pytest.mark.asyncio
async def test_a_generated_key_nobody_else_uses_is_removed(monkeypatch, key_writer):
    use_models(monkeypatch, {"other": {"api_key_name": "custom_other"}})

    await custom_routes._release_unused_api_key({"requires_auth": True, "api_key_name": "custom_gone"})

    key_writer.assert_awaited_once_with("custom_gone", "")


@pytest.mark.asyncio
async def test_a_key_still_used_by_another_custom_model_is_kept(monkeypatch, key_writer):
    use_models(monkeypatch, {"other": {"api_key_name": "custom_shared"}})

    await custom_routes._release_unused_api_key({"requires_auth": True, "api_key_name": "custom_shared"})

    key_writer.assert_not_awaited()


@pytest.mark.parametrize("name", ["openai", "anthropic", "deepgram", "my-own-name", "", None])
@pytest.mark.asyncio
async def test_a_key_that_is_not_generated_for_one_model_is_never_removed(monkeypatch, key_writer, name):
    use_models(monkeypatch, {})

    await custom_routes._release_unused_api_key({"requires_auth": True, "api_key_name": name})

    key_writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failure_to_remove_the_key_does_not_fail_the_delete(monkeypatch, key_writer):
    use_models(monkeypatch, {})
    key_writer.side_effect = RuntimeError("The Basil app is not connected.")

    await custom_routes._release_unused_api_key({"requires_auth": True, "api_key_name": "custom_gone"})

    key_writer.assert_awaited_once()
