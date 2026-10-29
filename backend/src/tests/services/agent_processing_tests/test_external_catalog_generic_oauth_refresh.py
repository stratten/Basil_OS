"""Tests for external_catalog's generic (non-Slack) OAuth refresh-and-retry."""

from types import SimpleNamespace

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    auth as external_catalog_auth,
)

_REFRESH_TARGET = "api.services.mcp_connectors.generic_oauth_token_refresh.refresh_generic_oauth_access_token"


def _record(**overrides):
    defaults = dict(id="conn-linear", server_url="https://mcp.linear.app/mcp")
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_non_auth_error_envelope_is_left_untouched():
    async def redo(_token):
        raise AssertionError("redo should not run for a non-auth error")

    result = await external_catalog_auth.try_generic_oauth_refresh_and_retry(
        record=_record(),
        envelope={"ok": False, "error": {"kind": "not_found", "message": "missing"}},
        redo=redo,
    )

    assert result is None


@pytest.mark.asyncio
async def test_successful_envelope_is_left_untouched():
    async def redo(_token):
        raise AssertionError("redo should not run for a successful envelope")

    result = await external_catalog_auth.try_generic_oauth_refresh_and_retry(
        record=_record(),
        envelope={"ok": True, "result": {}},
        redo=redo,
    )

    assert result is None


@pytest.mark.asyncio
async def test_refresh_unavailable_leaves_no_retry_result_for_the_caller(monkeypatch):
    """When refresh fails (Slack connection, no refresh token, provider
    rejects it), the caller keeps the original auth_expired envelope -
    no regression versus today's behavior."""

    async def fake_refresh(record, **kwargs):
        return None

    monkeypatch.setattr(_REFRESH_TARGET, fake_refresh)

    async def redo(_token):
        raise AssertionError("redo should not run when refresh fails")

    result = await external_catalog_auth.try_generic_oauth_refresh_and_retry(
        record=_record(),
        envelope={"ok": False, "error": {"kind": "auth_expired", "message": "stale"}},
        redo=redo,
    )

    assert result is None


@pytest.mark.asyncio
async def test_successful_refresh_retries_once_and_updates_the_run_scoped_cache(monkeypatch):
    async def fake_refresh(record, *, agent_task_id=None, cancel_event=None):
        assert record.id == "conn-linear"
        assert agent_task_id == "task-1"
        return "fresh-access-token"

    monkeypatch.setattr(_REFRESH_TARGET, fake_refresh)

    redo_calls = []

    async def redo(token):
        redo_calls.append(token)
        return {"ok": True, "result": {"tools": []}}

    token = set_current_agent_context({"agent_task_id": "task-1"})
    try:
        result = await external_catalog_auth.try_generic_oauth_refresh_and_retry(
            record=_record(),
            envelope={"ok": False, "error": {"kind": "auth_expired", "message": "stale"}},
            redo=redo,
        )
        cache = get_current_agent_context().get("mcp_token_cache")
    finally:
        reset_current_agent_context(token)

    assert redo_calls == ["fresh-access-token"]
    assert result == {"ok": True, "result": {"tools": []}}
    assert cache == {"conn-linear": "fresh-access-token"}


@pytest.mark.asyncio
async def test_retry_still_failing_invalidates_the_cache_again(monkeypatch):
    async def fake_refresh(record, **kwargs):
        return "fresh-access-token"

    monkeypatch.setattr(_REFRESH_TARGET, fake_refresh)

    async def redo(_token):
        return {"ok": False, "error": {"kind": "auth_expired", "message": "still stale"}}

    token = set_current_agent_context({"mcp_token_cache": {"conn-linear": "fresh-access-token"}})
    try:
        result = await external_catalog_auth.try_generic_oauth_refresh_and_retry(
            record=_record(),
            envelope={"ok": False, "error": {"kind": "auth_expired", "message": "stale"}},
            redo=redo,
        )
        cache = get_current_agent_context().get("mcp_token_cache")
    finally:
        reset_current_agent_context(token)

    assert result == {"ok": False, "error": {"kind": "auth_expired", "message": "still stale"}}
    assert "conn-linear" not in cache
