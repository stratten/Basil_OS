"""Tests for approval-gated local web preview server launcher."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher import (
    LocalPreviewServerLauncher,
)
from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_session_registry import (
    LocalPreviewSessionRegistry,
)
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_LOOPBACK_LISTENER_SCRIPT = (
    "import socket, sys\n"
    "listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
    "listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "listener.bind(('127.0.0.1', int(sys.argv[1])))\n"
    "listener.listen()\n"
    "while True:\n"
    "    connection, _ = listener.accept()\n"
    "    connection.close()\n"
)


def _loopback_listener_args(port: int) -> list[str]:
    # http.server resolves the host name before listen(), which can stall past the readiness window on CI runners.
    return ["-c", _LOOPBACK_LISTENER_SCRIPT, str(port)]


def _assert_running(session) -> None:
    assert session.status == "running", (
        f"last_error={session.last_error!r}; stdout={session.stdout_tail!r}; stderr={session.stderr_tail!r}"
    )


@pytest.fixture
def registry() -> LocalPreviewSessionRegistry:
    return LocalPreviewSessionRegistry()


@pytest.fixture
def launcher(
    registry: LocalPreviewSessionRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> LocalPreviewServerLauncher:
    monkeypatch.setattr(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.home_root",
        lambda: tmp_path,
    )
    return LocalPreviewServerLauncher(registry)


@pytest.fixture
def allowed_cwd(tmp_path: Path) -> Path:
    """Working directory under the isolated home fixture, satisfying the cwd allowlist."""
    path = tmp_path / "local_preview_tests"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.asyncio
async def test_start_session_denied_returns_denied_status(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    denied_outcome = ExecutionApprovalOutcome(approved=False, status="user_denied", reason="User denied.")

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(return_value=denied_outcome)
        session = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-1",
            command="python3",
            args=["-m", "http.server", "8080"],
            cwd=str(allowed_cwd),
            port=8080,
        )

    assert session.status == "denied"
    assert registry.get_process(session.session_id) is None


@pytest.mark.asyncio
async def test_start_session_rejects_cwd_outside_allowlist(
    launcher: LocalPreviewServerLauncher,
) -> None:
    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock()
        session = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-1",
            command="python3",
            args=["-m", "http.server", "8080"],
            cwd="/etc",
            port=8080,
        )

    assert session.status == "error"
    approval_cls.return_value.request_approval_with_outcome.assert_not_called()


@pytest.mark.asyncio
async def test_start_session_rejects_non_loopback_host_without_requesting_approval(
    launcher: LocalPreviewServerLauncher,
    allowed_cwd: Path,
) -> None:
    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        session = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-1",
            command="python3",
            args=["-m", "http.server", "8080"],
            cwd=str(allowed_cwd),
            host="0.0.0.0",
            port=8080,
        )

    assert session.status == "error"
    assert session.last_error == "Local preview servers must use 127.0.0.1."
    approval_cls.return_value.request_approval_with_outcome.assert_not_called()


@pytest.mark.asyncio
async def test_start_session_running_flips_status_after_port_listens(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    port = _free_port()
    approved_outcome = ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(return_value=approved_outcome)
        session = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-1",
            command=sys.executable,
            args=_loopback_listener_args(port),
            cwd=str(allowed_cwd),
            port=port,
        )

    _assert_running(session)
    process = registry.get_process(session.session_id)
    assert process is not None

    stopped = await launcher.stop_session(session.session_id)
    assert stopped is not None
    assert stopped.status == "stopped"
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_start_timeout_terminates_process_and_reports_error(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    approved_outcome = ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")
    launcher._wait_until_listening = AsyncMock(return_value=False)

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(return_value=approved_outcome)
        session = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-timeout",
            command=sys.executable,
            args=["-c", "import time; time.sleep(60)"],
            cwd=str(allowed_cwd),
            port=_free_port(),
        )

    assert session.status == "error"
    assert "did not start listening" in (session.last_error or "")
    assert registry.get_process(session.session_id) is None


@pytest.mark.asyncio
async def test_stop_all_sessions_terminates_every_active_session(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    port_a = _free_port()
    port_b = _free_port()
    approved_outcome = ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(return_value=approved_outcome)
        session_a = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-a",
            command=sys.executable,
            args=_loopback_listener_args(port_a),
            cwd=str(allowed_cwd),
            port=port_a,
        )
        session_b = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-b",
            command=sys.executable,
            args=_loopback_listener_args(port_b),
            cwd=str(allowed_cwd),
            port=port_b,
        )

    _assert_running(session_a)
    _assert_running(session_b)

    await launcher.stop_all_sessions()

    assert registry.get(session_a.session_id).status == "stopped"
    assert registry.get(session_b.session_id).status == "stopped"


@pytest.mark.asyncio
async def test_second_session_for_same_artifact_stops_first(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    port_a = _free_port()
    port_b = _free_port()
    approved_outcome = ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(return_value=approved_outcome)
        first = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-a1",
            command=sys.executable,
            args=_loopback_listener_args(port_a),
            cwd=str(allowed_cwd),
            port=port_a,
        )
        first_process = registry.get_process(first.session_id)
        assert first_process is not None

        second = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-a1",
            command=sys.executable,
            args=_loopback_listener_args(port_b),
            cwd=str(allowed_cwd),
            port=port_b,
        )

    assert registry.get_active_session_id_for_artifact("task-1", "artifact-a1") == second.session_id
    assert registry.get(first.session_id).status == "stopped"
    assert first_process.returncode is not None


@pytest.mark.asyncio
async def test_denied_replacement_preserves_existing_artifact_session(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    port = _free_port()
    replacement_port = _free_port()
    approved_outcome = ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")
    denied_outcome = ExecutionApprovalOutcome(approved=False, status="user_denied", reason="User denied.")

    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(
            side_effect=[approved_outcome, denied_outcome]
        )
        first = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-a1",
            command=sys.executable,
            args=_loopback_listener_args(port),
            cwd=str(allowed_cwd),
            port=port,
        )
        first_process = registry.get_process(first.session_id)
        second = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="artifact-a1",
            command=sys.executable,
            args=_loopback_listener_args(replacement_port),
            cwd=str(allowed_cwd),
            port=replacement_port,
        )

    _assert_running(first)
    assert second.status == "denied"
    assert first_process is not None and first_process.returncode is None
    assert registry.get_active_session_id_for_artifact("task-1", "artifact-a1") == first.session_id

    await launcher.stop_session(first.session_id)


@pytest.mark.asyncio
async def test_two_tasks_can_share_an_artifact_id_without_replacing_each_other(launcher, registry, allowed_cwd):
    port_a = _free_port()
    port_b = _free_port()
    with patch(
        "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
    ) as approval_cls:
        approval_cls.return_value.request_approval_with_outcome = AsyncMock(
            return_value=ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")
        )
        first = await launcher.start_session(
            agent_task_id="task-1",
            artifact_id="shared-artifact",
            command=sys.executable,
            args=_loopback_listener_args(port_a),
            cwd=str(allowed_cwd),
            port=port_a,
        )
        second = await launcher.start_session(
            agent_task_id="task-2",
            artifact_id="shared-artifact",
            command=sys.executable,
            args=_loopback_listener_args(port_b),
            cwd=str(allowed_cwd),
            port=port_b,
        )

    _assert_running(first)
    _assert_running(second)
    assert first.session_id != second.session_id
    assert registry.get_active_session_id_for_artifact("task-1", "shared-artifact") == first.session_id
    assert registry.get_active_session_id_for_artifact("task-2", "shared-artifact") == second.session_id

    await launcher.stop_session(first.session_id)
    await launcher.stop_session(second.session_id)


@pytest.mark.asyncio
async def test_start_session_refuses_a_port_that_is_already_listening(
    launcher: LocalPreviewServerLauncher,
    registry: LocalPreviewSessionRegistry,
    allowed_cwd: Path,
) -> None:
    approved_outcome = ExecutionApprovalOutcome(approved=True, status="approved", reason="Approved.")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupant:
        occupant.bind(("127.0.0.1", 0))
        occupant.listen()
        port = occupant.getsockname()[1]
        with patch(
            "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.ExecutionApprovalService"
        ) as approval_cls, patch(
            "api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_server_launcher.asyncio.create_subprocess_exec"
        ) as spawn:
            approval_cls.return_value.request_approval_with_outcome = AsyncMock(return_value=approved_outcome)
            session = await launcher.start_session(
                agent_task_id="task-1",
                artifact_id="artifact-occupied",
                command=sys.executable,
                args=_loopback_listener_args(port),
                cwd=str(allowed_cwd),
                port=port,
            )

    assert session.status == "error"
    assert session.last_error == f"Port {port} on 127.0.0.1 is already in use by another process."
    spawn.assert_not_called()
    assert registry.get_process(session.session_id) is None
