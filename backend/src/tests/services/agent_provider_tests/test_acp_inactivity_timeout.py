"""Inactivity-based timeouts for long ACP prompt turns."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.agent_providers.acp.protocol import AcpClientTimeoutError
from api.services.agent_providers.acp.session_transport import AcpSessionTransport
from api.services.agent_providers.profiles.launch_validation import ValidatedProviderLaunchRequest
from api.services.agent_providers.runtime.process_supervisor import (
    PROMPT_INACTIVITY_TIMEOUT_SECONDS,
    PROMPT_MAX_TURN_SECONDS,
    PROMPT_TOOL_CALL_INACTIVITY_TIMEOUT_SECONDS,
    ProviderLaunchOutcomeStatus,
    ProviderProcessSupervisor,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3]


def _transport(mode: str) -> AcpSessionTransport:
    return AcpSessionTransport(
        (sys.executable, "-m", "api.services.agent_providers.testing.acp_activity_fixture", "--fixture-mode", mode),
        cwd=str(SOURCE_ROOT),
        env=None,
        start_new_session=True,
        request_timeout_seconds=5.0,
    )


@pytest.fixture(autouse=True)
def _source_root_on_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_ROOT))


async def _prompt(transport: AcpSessionTransport, **limits):
    await transport.start()
    try:
        return await transport.send_request_with_inactivity_timeout(
            "session/prompt",
            {"sessionId": "fixture-session", "prompt": [{"type": "text", "text": "hi"}]},
            **limits,
        )
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_steady_activity_outlives_the_inactivity_limit() -> None:
    started = time.monotonic()
    response = await _prompt(_transport("steady_activity"), inactivity_timeout_seconds=0.5, max_total_seconds=10.0)
    assert response["result"] == {"stopReason": "end_turn"}
    assert time.monotonic() - started >= 1.0


@pytest.mark.asyncio
async def test_silence_times_out_quickly() -> None:
    started = time.monotonic()
    with pytest.raises(AcpClientTimeoutError, match="no ACP activity"):
        await _prompt(_transport("silent"), inactivity_timeout_seconds=0.4, max_total_seconds=10.0)
    assert time.monotonic() - started < 5.0


@pytest.mark.asyncio
async def test_open_tool_call_extends_the_silence_limit() -> None:
    response = await _prompt(
        _transport("open_tool_call_silence"),
        inactivity_timeout_seconds=0.3,
        tool_call_inactivity_timeout_seconds=3.0,
        max_total_seconds=10.0,
    )
    assert response["result"] == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_open_tool_call_silence_still_has_a_limit() -> None:
    with pytest.raises(AcpClientTimeoutError, match="no ACP activity"):
        await _prompt(
            _transport("open_tool_call_silence"),
            inactivity_timeout_seconds=0.3,
            tool_call_inactivity_timeout_seconds=0.3,
            max_total_seconds=10.0,
        )


@pytest.mark.asyncio
async def test_endless_activity_hits_the_absolute_turn_ceiling() -> None:
    with pytest.raises(AcpClientTimeoutError, match="maximum turn duration"):
        await _prompt(_transport("endless_activity"), inactivity_timeout_seconds=0.5, max_total_seconds=0.8)


@pytest.mark.asyncio
async def test_supervisor_sends_prompts_with_inactivity_limits(tmp_path) -> None:
    request = ValidatedProviderLaunchRequest(
        provider_profile_id="fixture-profile",
        display_name="Fixture Provider",
        launch_argv=(sys.executable, "-c", "pass"),
        environment_allowlist=("PYTHONPATH",),
        authentication_method_id=None,
        workspace_grant_id="fixture-grant",
        resolved_workspace_root=str(tmp_path),
        capability_state="unverified",
    )
    supervisor = ProviderProcessSupervisor(request, client_info={"name": "Basil", "version": "0.1.0"}, client_capabilities={})
    supervisor._outcome = SimpleNamespace(status=ProviderLaunchOutcomeStatus.RUNNING)
    fake_send_prompt = AsyncMock(return_value={"stopReason": "end_turn"})
    supervisor._client = SimpleNamespace(send_prompt=fake_send_prompt)

    await supervisor.send_prompt(session_id="s-1", prompt=[{"type": "text", "text": "hi"}])

    kwargs = fake_send_prompt.await_args.kwargs
    assert kwargs["inactivity_timeout_seconds"] == PROMPT_INACTIVITY_TIMEOUT_SECONDS
    assert kwargs["tool_call_inactivity_timeout_seconds"] == PROMPT_TOOL_CALL_INACTIVITY_TIMEOUT_SECONDS
    assert kwargs["max_turn_seconds"] == PROMPT_MAX_TURN_SECONDS
