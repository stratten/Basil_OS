from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.delegation.acp_session_controller import (
    AcpDelegatedSessionController,
)
from api.services.agent_providers.acp.protocol import AcpClientProtocolError
from api.services.agent_providers.runtime.process_supervisor import ProviderLaunchOutcomeStatus


class _SuccessfulSupervisor:
    def __init__(self) -> None:
        self.mark_turn_idle_calls = 0

    async def send_prompt(self, **_kwargs):
        return {"stopReason": "end_turn"}

    def mark_turn_idle(self) -> None:
        self.mark_turn_idle_calls += 1


class _FailingSupervisor:
    def __init__(self) -> None:
        self.mark_turn_idle_calls = 0

    async def send_prompt(self, **_kwargs):
        raise AcpClientProtocolError("peer emitted a JSON-RPC line exceeding the stream limit")

    def mark_turn_idle(self) -> None:
        self.mark_turn_idle_calls += 1


class _CancelingSupervisor:
    def __init__(self) -> None:
        self.mark_turn_idle_calls = 0

    async def send_prompt(self, **_kwargs):
        raise asyncio.CancelledError()

    def mark_turn_idle(self) -> None:
        self.mark_turn_idle_calls += 1


@pytest.mark.asyncio
async def test_send_follow_up_marks_idle_after_successful_prompt() -> None:
    supervisor = _SuccessfulSupervisor()
    controller = AcpDelegatedSessionController()
    controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=supervisor,
        session_id="provider-session",
    )

    response = await controller.send_follow_up(
        delegated_agent_run_id="delegated-run",
        instruction="Perform the bounded task.",
    )

    assert response == {"stopReason": "end_turn"}
    assert supervisor.mark_turn_idle_calls == 1
    assert controller.describe("delegated-run")["in_flight"] is False


@pytest.mark.asyncio
async def test_send_follow_up_preserves_prompt_failure_without_idle_transition() -> None:
    supervisor = _FailingSupervisor()
    controller = AcpDelegatedSessionController()
    controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=supervisor,
        session_id="provider-session",
    )

    with pytest.raises(AcpClientProtocolError, match="exceeding the stream limit"):
        await controller.send_follow_up(
            delegated_agent_run_id="delegated-run",
            instruction="Perform the bounded task.",
        )

    assert supervisor.mark_turn_idle_calls == 0
    assert controller.describe("delegated-run")["in_flight"] is False


@pytest.mark.asyncio
async def test_send_follow_up_preserves_cancellation_without_idle_transition() -> None:
    supervisor = _CancelingSupervisor()
    controller = AcpDelegatedSessionController()
    controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=supervisor,
        session_id="provider-session",
    )

    with pytest.raises(asyncio.CancelledError):
        await controller.send_follow_up(
            delegated_agent_run_id="delegated-run",
            instruction="Perform the bounded task.",
        )

    assert supervisor.mark_turn_idle_calls == 0
    assert controller.describe("delegated-run")["in_flight"] is False


@pytest.mark.asyncio
async def test_cancel_releases_a_session_after_its_supervisor_already_timed_out() -> None:
    class _TerminalSupervisor:
        last_outcome = SimpleNamespace(status=ProviderLaunchOutcomeStatus.TIMED_OUT)

        async def cancel(self) -> None:
            raise AssertionError("a terminal supervisor must not be canceled again")

    controller = AcpDelegatedSessionController()
    controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=_TerminalSupervisor(),
        session_id="provider-session",
    )

    await controller.cancel(delegated_agent_run_id="delegated-run")

    assert controller.contains("delegated-run") is False
