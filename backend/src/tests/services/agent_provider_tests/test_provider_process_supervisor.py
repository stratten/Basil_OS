"""Focused coverage for managed local external ACP runtime supervision (Package 2B)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pytest

from api.services.agent_providers.acp.session_client import AcpClientProtocolError
from api.services.agent_providers.profiles.launch_validation import (
    ValidatedProviderLaunchRequest,
)
from api.services.agent_providers.runtime.process_supervisor import (
    ProviderLaunchOutcomeStatus,
    ProviderProcessSupervisor,
    ProviderProcessSupervisorError,
)


SOURCE_ROOT = Path(__file__).resolve().parents[3]

CLIENT_INFO = {"name": "Basil", "version": "0.1.0"}
CLIENT_CAPABILITIES = {}


def _fixture_argv(mode: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "api.services.agent_providers.testing.process_fixture",
        "--fixture-mode",
        mode,
    )


def _session_fixture_argv(mode: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "api.services.agent_providers.testing.acp_session_fixture",
        "--fixture-mode",
        mode,
    )


def _validated_request(
    *,
    launch_argv: tuple[str, ...],
    resolved_workspace_root: str,
    environment_allowlist: tuple[str, ...] = ("PYTHONPATH",),
    authentication_method_id: str | None = None,
) -> ValidatedProviderLaunchRequest:
    return ValidatedProviderLaunchRequest(
        provider_profile_id="fixture-profile",
        display_name="Fixture Provider",
        launch_argv=launch_argv,
        environment_allowlist=environment_allowlist,
        authentication_method_id=authentication_method_id,
        workspace_grant_id="fixture-grant",
        resolved_workspace_root=resolved_workspace_root,
        capability_state="unverified",
    )


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture(autouse=True)
def _source_root_on_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_ROOT))


@pytest.mark.asyncio
async def test_launch_returns_running_outcome_and_a_full_session_completes_cleanly(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("clean_exit"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    assert outcome.runtime_version == "2.0.0-fixture"
    assert outcome.agent_capabilities == {}
    assert outcome.pid == supervisor.pid
    assert outcome.pid is not None

    session = await supervisor.create_session()
    assert session.session_id == "fixture-process-session"

    prompt_result = await supervisor.send_prompt(
        session_id=session.session_id, prompt=[{"type": "text", "text": "hello"}]
    )
    assert prompt_result == {}

    final_outcome = await supervisor.wait_for_exit()
    assert final_outcome.status == ProviderLaunchOutcomeStatus.COMPLETED
    assert final_outcome.exit_code == 0
    assert final_outcome.runtime_version == "2.0.0-fixture"
    assert final_outcome.agent_capabilities == {}
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_launch_authenticates_with_an_advertised_method_before_creating_a_session(
    tmp_path,
) -> None:
    supervisor = ProviderProcessSupervisor(
        _validated_request(
            launch_argv=_session_fixture_argv("auth_success"),
            resolved_workspace_root=str(tmp_path),
            authentication_method_id="api-key",
        ),
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
    )

    launch_outcome = await supervisor.launch()
    assert launch_outcome.status is ProviderLaunchOutcomeStatus.RUNNING
    assert launch_outcome.pid is not None
    session = await supervisor.create_session()
    assert session.session_id == "fixture-session-1"

    completed_outcome = await supervisor.wait_for_exit()

    assert completed_outcome.status is ProviderLaunchOutcomeStatus.COMPLETED
    assert not _pid_is_alive(launch_outcome.pid)


@pytest.mark.asyncio
async def test_launch_fails_authentication_before_session_creation_when_method_is_unadvertised(
    tmp_path,
) -> None:
    supervisor = ProviderProcessSupervisor(
        _validated_request(
            launch_argv=_session_fixture_argv("auth_unadvertised_method"),
            resolved_workspace_root=str(tmp_path),
            authentication_method_id="api-key",
        ),
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
    )

    outcome = await supervisor.launch()

    assert outcome.status is ProviderLaunchOutcomeStatus.AUTHENTICATION_FAILED
    assert outcome.pid is not None
    assert "not advertised" in (outcome.diagnostic_message or "")
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_launch_closes_the_process_after_a_remote_authentication_rejection(tmp_path) -> None:
    supervisor = ProviderProcessSupervisor(
        _validated_request(
            launch_argv=_session_fixture_argv("auth_remote_rejection"),
            resolved_workspace_root=str(tmp_path),
            authentication_method_id="api-key",
        ),
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
    )

    outcome = await supervisor.launch()

    assert outcome.status is ProviderLaunchOutcomeStatus.AUTHENTICATION_FAILED
    assert outcome.pid is not None
    assert outcome.diagnostic_message == "AcpRemoteRequestError: Authentication required"
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_complete_turn_terminates_a_persistent_runtime_after_prompt_response(
    tmp_path,
) -> None:
    supervisor = ProviderProcessSupervisor(
        _validated_request(
            launch_argv=_fixture_argv("persistent_after_prompt"),
            resolved_workspace_root=str(tmp_path),
        ),
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
    )

    launch_outcome = await supervisor.launch()
    assert launch_outcome.status is ProviderLaunchOutcomeStatus.RUNNING
    assert launch_outcome.pid is not None
    session = await supervisor.create_session()
    assert await supervisor.send_prompt(
        session_id=session.session_id,
        prompt=[{"type": "text", "text": "read only"}],
    ) == {}

    completed_outcome = await supervisor.complete_turn()

    assert completed_outcome.status is ProviderLaunchOutcomeStatus.COMPLETED
    assert not _pid_is_alive(launch_outcome.pid)


@pytest.mark.asyncio
async def test_launch_preserves_negotiated_v1_protocol_version(tmp_path) -> None:
    supervisor = ProviderProcessSupervisor(
        _validated_request(
            launch_argv=_fixture_argv("v1_clean_exit"),
            resolved_workspace_root=str(tmp_path),
        ),
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
    )

    launch_outcome = await supervisor.launch()
    assert launch_outcome.status is ProviderLaunchOutcomeStatus.RUNNING
    assert launch_outcome.protocol_version == 1
    session = await supervisor.create_session()
    assert await supervisor.send_prompt(
        session_id=session.session_id,
        prompt=[{"type": "text", "text": "read only"}],
    ) == {"stopReason": "end_turn"}
    completed_outcome = await supervisor.wait_for_exit()
    assert completed_outcome.status is ProviderLaunchOutcomeStatus.COMPLETED
    assert completed_outcome.protocol_version == 1


@pytest.mark.asyncio
async def test_launch_classifies_missing_executable_as_executable_not_found(tmp_path) -> None:
    request = _validated_request(
        launch_argv=("/nonexistent/basil-acp-2b-test-binary",),
        resolved_workspace_root=str(tmp_path),
        environment_allowlist=(),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.EXECUTABLE_NOT_FOUND
    assert outcome.pid is None
    assert outcome.diagnostic_message


@pytest.mark.asyncio
async def test_launch_classifies_immediate_process_exit_before_initialize_as_startup_failed(
    tmp_path,
) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("startup_crash"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.STARTUP_FAILED
    assert outcome.exit_code == 17
    assert "simulated startup crash" in (outcome.diagnostic_message or "")
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_create_session_classifies_malformed_message_from_a_still_alive_process_as_protocol_failed(
    tmp_path,
) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("protocol_violation_after_initialize"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING

    with pytest.raises(AcpClientProtocolError):
        await supervisor.create_session()

    assert supervisor.last_outcome is not None
    assert supervisor.last_outcome.status == ProviderLaunchOutcomeStatus.PROTOCOL_FAILED
    assert not _pid_is_alive(supervisor.pid)


@pytest.mark.asyncio
async def test_send_prompt_classifies_process_exit_after_running_as_crashed(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("crash_after_session"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    session = await supervisor.create_session()

    with pytest.raises(AcpClientProtocolError):
        await supervisor.send_prompt(
            session_id=session.session_id, prompt=[{"type": "text", "text": "go"}]
        )

    assert supervisor.last_outcome is not None
    assert supervisor.last_outcome.status == ProviderLaunchOutcomeStatus.CRASHED
    assert supervisor.last_outcome.exit_code == 1
    assert not _pid_is_alive(supervisor.pid)


@pytest.mark.asyncio
async def test_wait_for_exit_classifies_protocol_violation_after_prompt_as_failed(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("protocol_violation_after_prompt"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    session = await supervisor.create_session()
    await supervisor.send_prompt(
        session_id=session.session_id, prompt=[{"type": "text", "text": "go"}]
    )

    final_outcome = await supervisor.wait_for_exit()

    assert final_outcome.status == ProviderLaunchOutcomeStatus.PROTOCOL_FAILED
    assert final_outcome.exit_code == 0
    assert not _pid_is_alive(supervisor.pid)


@pytest.mark.asyncio
async def test_launch_classifies_a_hung_process_as_timed_out_and_terminates_it(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("hang_before_initialize"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request,
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
        request_timeout_seconds=1.0,
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.TIMED_OUT
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_cancelling_an_inflight_launch_terminates_its_process_group(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("hang_before_initialize"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request,
        client_info=CLIENT_INFO,
        client_capabilities=CLIENT_CAPABILITIES,
        request_timeout_seconds=30.0,
    )

    launch_task = asyncio.create_task(supervisor.launch())
    assert await _wait_until(lambda: supervisor.pid is not None)
    process_pid = supervisor.pid
    assert process_pid is not None

    launch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await launch_task

    assert supervisor.last_outcome is not None
    assert supervisor.last_outcome.status == ProviderLaunchOutcomeStatus.CANCELLED
    assert not _pid_is_alive(process_pid)


@pytest.mark.asyncio
async def test_environment_allowlist_only_admits_allowlisted_variables_plus_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASIL_ACP_TEST_ALLOWED", "visible-value")
    monkeypatch.setenv("BASIL_ACP_TEST_FORBIDDEN", "secret-value")
    expected_path = os.environ.get("PATH")

    request = _validated_request(
        launch_argv=_fixture_argv("environment_probe"),
        resolved_workspace_root=str(tmp_path),
        environment_allowlist=("PYTHONPATH", "BASIL_ACP_TEST_ALLOWED"),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    assert outcome.agent_capabilities == {
        "observedEnv": {
            "BASIL_ACP_TEST_ALLOWED": "visible-value",
            "BASIL_ACP_TEST_FORBIDDEN": None,
            "PATH": expected_path,
        },
        "workingDirectory": str(tmp_path),
    }

    session = await supervisor.create_session()
    await supervisor.send_prompt(session_id=session.session_id, prompt=[{"type": "text", "text": "hi"}])
    final_outcome = await supervisor.wait_for_exit()
    assert final_outcome.status == ProviderLaunchOutcomeStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancel_terminates_the_entire_process_group_including_a_grandchild(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child_pid_file = tmp_path / "grandchild.pid"
    monkeypatch.setenv("BASIL_ACP_TEST_CHILD_PID_FILE", str(child_pid_file))
    request = _validated_request(
        launch_argv=_fixture_argv("spawns_child_and_hangs"),
        resolved_workspace_root=str(tmp_path),
        environment_allowlist=("PYTHONPATH", "BASIL_ACP_TEST_CHILD_PID_FILE"),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    await supervisor.create_session()

    assert await _wait_until(child_pid_file.exists)
    grandchild_pid = int(child_pid_file.read_text().strip())
    assert _pid_is_alive(grandchild_pid)
    assert os.getpgid(outcome.pid) == outcome.pid

    cancel_outcome = await supervisor.cancel()
    assert cancel_outcome.status == ProviderLaunchOutcomeStatus.CANCELLED

    assert await _wait_until(lambda: not _pid_is_alive(grandchild_pid))
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_cancel_escalates_to_kill_when_the_child_ignores_sigterm(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("ignores_sigterm"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    await supervisor.create_session()

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    cancel_outcome = await supervisor.cancel()
    elapsed = loop.time() - started_at

    assert cancel_outcome.status == ProviderLaunchOutcomeStatus.CANCELLED
    assert 0.9 <= elapsed < 5.0
    assert not _pid_is_alive(outcome.pid)


@pytest.mark.asyncio
async def test_operations_before_running_or_after_terminal_outcome_are_rejected(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("clean_exit"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    with pytest.raises(ProviderProcessSupervisorError):
        await supervisor.create_session()

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING

    with pytest.raises(ProviderProcessSupervisorError):
        await supervisor.launch()

    session = await supervisor.create_session()
    await supervisor.send_prompt(session_id=session.session_id, prompt=[{"type": "text", "text": "hi"}])
    await supervisor.wait_for_exit()

    with pytest.raises(ProviderProcessSupervisorError):
        await supervisor.create_session()
    with pytest.raises(ProviderProcessSupervisorError):
        await supervisor.cancel()


@pytest.mark.asyncio
async def test_process_group_leader_matches_reported_pid(tmp_path) -> None:
    request = _validated_request(
        launch_argv=_fixture_argv("clean_exit"),
        resolved_workspace_root=str(tmp_path),
    )
    supervisor = ProviderProcessSupervisor(
        request, client_info=CLIENT_INFO, client_capabilities=CLIENT_CAPABILITIES
    )

    outcome = await supervisor.launch()
    assert outcome.status == ProviderLaunchOutcomeStatus.RUNNING
    assert os.getpgid(outcome.pid) == outcome.pid

    session = await supervisor.create_session()
    await supervisor.send_prompt(session_id=session.session_id, prompt=[{"type": "text", "text": "hi"}])
    await supervisor.wait_for_exit()
