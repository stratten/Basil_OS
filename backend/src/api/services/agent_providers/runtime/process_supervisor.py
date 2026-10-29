"""Managed local external ACP runtime supervision.

This module launches a validated attended provider profile's command as a
subprocess, attaches it to `AcpSessionClient` for negotiated ACP v1/v2 protocol handling,
and owns that subprocess's lifetime as a process group: it applies the
profile's environment allowlist, captures the agent-reported runtime version,
distinguishes executable-not-found, startup failure, protocol failure, crash,
timeout, and clean-exit outcomes, and guarantees no descendant process
survives any terminal path. It never persists a provider run, never creates
an Agent Task, never shows a provider chooser, and never injects MCP server
configuration; it only runs the deterministic adapter fixture in this
package.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import logging
import os
from typing import Any, Awaitable, Callable, Mapping, Sequence

from api.services.agent_providers.acp.session_client import (
    AcpClientError,
    AcpClientProtocolError,
    AcpClientTimeoutError,
    AcpRemoteRequestError,
    AcpSessionClient,
    AcpSessionHandle,
)
from api.services.agent_providers.profiles.launch_validation import (
    ValidatedProviderLaunchRequest,
)


DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
MAX_DIAGNOSTIC_MESSAGE_BYTES = 4_096
_SPONTANEOUS_EXIT_GRACE_SECONDS = 0.5
PROMPT_INACTIVITY_TIMEOUT_SECONDS = 600.0
PROMPT_TOOL_CALL_INACTIVITY_TIMEOUT_SECONDS = 1800.0
PROMPT_MAX_TURN_SECONDS = 21600.0
logger = logging.getLogger(__name__)


class ProviderProcessSupervisorError(RuntimeError):
    """An operation was attempted in a state the supervisor does not support."""


class ProviderLaunchOutcomeStatus(str, Enum):
    """The terminal or in-progress classification of one supervised launch."""

    RUNNING = "running"
    EXECUTABLE_NOT_FOUND = "executable_not_found"
    STARTUP_FAILED = "startup_failed"
    PROTOCOL_FAILED = "protocol_failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    TIMED_OUT = "timed_out"
    CRASHED = "crashed"
    COMPLETED = "completed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class ProviderLaunchOutcome:
    """A structured, caller-persistable classification of a supervised launch.

    This object never writes to any repository. It is returned so a later
    package can decide how to persist it against a specific provider run.
    """

    status: ProviderLaunchOutcomeStatus
    provider_profile_id: str
    display_name: str
    runtime_version: str | None
    agent_capabilities: dict[str, Any] | None
    diagnostic_message: str | None
    exit_code: int | None
    pid: int | None
    protocol_version: int | None = None


def _build_child_environment(environment_allowlist: Sequence[str]) -> dict[str, str]:
    """Build the child process environment from scratch out of the parent environment.

    Only variable names present in `environment_allowlist` are copied from the
    parent environment. `PATH` is always copied through if it is set in the
    parent environment, regardless of the allowlist, so a `launch_argv` entry
    expressed as a bare command name (for example `"npx"`) keeps resolving
    through normal executable-search semantics. This is a settled Package 2B
    decision and must not be re-litigated during execution.
    """

    child_env: dict[str, str] = {}
    for name in environment_allowlist:
        if name == "PATH":
            continue
        value = os.environ.get(name)
        if value is not None:
            child_env[name] = value
    parent_path = os.environ.get("PATH")
    if parent_path is not None:
        child_env["PATH"] = parent_path
    return child_env


def _truncate_diagnostic(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_DIAGNOSTIC_MESSAGE_BYTES:
        return text
    return encoded[:MAX_DIAGNOSTIC_MESSAGE_BYTES].decode("utf-8", errors="replace") + "...[truncated]"


class ProviderProcessSupervisor:
    """Launch, attach to, and own the lifetime of one local external ACP process."""

    def __init__(
        self,
        validated_request: ValidatedProviderLaunchRequest,
        *,
        client_info: Mapping[str, str],
        client_capabilities: Mapping[str, Any],
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        prompt_inactivity_timeout_seconds: float = PROMPT_INACTIVITY_TIMEOUT_SECONDS,
        prompt_tool_call_inactivity_timeout_seconds: float = PROMPT_TOOL_CALL_INACTIVITY_TIMEOUT_SECONDS,
        prompt_max_turn_seconds: float = PROMPT_MAX_TURN_SECONDS,
    ) -> None:
        self._validated_request = validated_request
        self._prompt_inactivity_timeout_seconds = float(prompt_inactivity_timeout_seconds)
        self._prompt_tool_call_inactivity_timeout_seconds = float(prompt_tool_call_inactivity_timeout_seconds)
        self._prompt_max_turn_seconds = float(prompt_max_turn_seconds)
        self._client_info = dict(client_info)
        self._client_capabilities = dict(client_capabilities)
        child_env = _build_child_environment(validated_request.environment_allowlist)
        self._client = AcpSessionClient(
            validated_request.launch_argv,
            cwd=validated_request.resolved_workspace_root,
            env=child_env,
            start_new_session=True,
            request_timeout_seconds=request_timeout_seconds,
        )
        self._has_launched = False
        self._outcome: ProviderLaunchOutcome | None = None
        self._runtime_version: str | None = None
        self._agent_capabilities: dict[str, Any] | None = None
        self._protocol_version: int | None = None

    @property
    def pid(self) -> int | None:
        """Return the launched process's id, or its last known id after it exits."""

        return self._client.pid

    @property
    def last_outcome(self) -> ProviderLaunchOutcome | None:
        """Return the most recently recorded outcome, or None before `launch()`."""

        return self._outcome

    @property
    def client(self) -> AcpSessionClient:
        """Return the attached ACP session client for advanced/diagnostic use only.

        Prefer `create_session()`/`send_prompt()` on this supervisor over
        calling the client directly, so outcome classification stays accurate.
        """

        return self._client

    def register_notification_handler(
        self,
        method: str,
        handler: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        """Register an ACP notification handler while retaining process supervision."""
        self._client.register_notification_handler(method, handler)

    def register_request_handler(
        self,
        method: str,
        handler: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]],
    ) -> None:
        """Register an ACP incoming-request handler while retaining process supervision."""
        self._client.register_request_handler(method, handler)

    async def launch(self) -> ProviderLaunchOutcome:
        """Start the process, initialize it, and classify the outcome.

        May be called exactly once. Always leaves the process group terminated
        before returning any outcome other than `RUNNING`.
        """

        if self._has_launched:
            raise ProviderProcessSupervisorError("launch() was already called")
        self._has_launched = True

        try:
            await self._client.start()
        except (FileNotFoundError, PermissionError) as exc:
            self._outcome = self._build_outcome(
                ProviderLaunchOutcomeStatus.EXECUTABLE_NOT_FOUND,
                diagnostic_message=_truncate_diagnostic(repr(exc)),
            )
            return self._outcome

        try:
            initialize_result = await self._client.initialize(
                client_capabilities=self._client_capabilities,
                client_info=self._client_info,
            )
        except (AcpClientError, OSError) as exc:
            return await self._classify_and_seal_client_error(exc)
        except asyncio.CancelledError:
            await self._cancel_and_close()
            raise

        self._runtime_version = (
            initialize_result.agent_info.get("version")
            if initialize_result.agent_info is not None
            else None
        )
        self._agent_capabilities = initialize_result.agent_capabilities
        self._protocol_version = initialize_result.protocol_version
        if self._validated_request.authentication_method_id is not None:
            try:
                await self._client.authenticate(
                    method_id=self._validated_request.authentication_method_id,
                    advertised_methods=initialize_result.auth_methods,
                )
            except (
                AcpRemoteRequestError,
                AcpClientProtocolError,
                AcpClientTimeoutError,
            ) as exc:
                await self._close_client()
                self._outcome = self._build_outcome(
                    ProviderLaunchOutcomeStatus.AUTHENTICATION_FAILED,
                    diagnostic_message=_truncate_diagnostic(
                        f"{type(exc).__name__}: {exc}"
                    ),
                    exit_code=self._client.exit_code,
                )
                return self._outcome
            except asyncio.CancelledError:
                await self._close_client()
                self._outcome = self._build_outcome(
                    ProviderLaunchOutcomeStatus.AUTHENTICATION_FAILED,
                    diagnostic_message="CancelledError: authentication exchange canceled",
                    exit_code=self._client.exit_code,
                )
                raise
        self._outcome = self._build_outcome(
            ProviderLaunchOutcomeStatus.RUNNING,
        )
        return self._outcome

    async def create_session(self) -> AcpSessionHandle:
        """Create the single ACP session for this launch. No MCP servers are configured."""

        self._require_running()
        try:
            return await self._client.create_session(
                cwd=self._validated_request.resolved_workspace_root
            )
        except (AcpClientError, OSError) as exc:
            await self._classify_and_seal_client_error(exc)
            raise
        except asyncio.CancelledError:
            await self._cancel_and_close()
            raise

    async def send_prompt(
        self, *, session_id: str, prompt: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        """Send one prompt turn through the attached client."""

        self._require_running()
        try:
            return await self._client.send_prompt(
                session_id=session_id,
                prompt=prompt,
                inactivity_timeout_seconds=self._prompt_inactivity_timeout_seconds,
                tool_call_inactivity_timeout_seconds=self._prompt_tool_call_inactivity_timeout_seconds,
                max_turn_seconds=self._prompt_max_turn_seconds,
            )
        except (AcpClientError, OSError) as exc:
            await self._classify_and_seal_client_error(exc)
            raise
        except asyncio.CancelledError:
            await self._cancel_and_close()
            raise

    async def complete_turn(self) -> ProviderLaunchOutcome:
        """Close a persistent runtime after its prompt response completes the turn."""

        self._require_running()
        if await self._client.wait_for_exit_within(_SPONTANEOUS_EXIT_GRACE_SECONDS):
            try:
                exit_code = await self._client.wait_for_exit()
            except (AcpClientError, OSError) as exc:
                return await self._classify_and_seal_client_error(exc)
            await self._close_client()
            status = (
                ProviderLaunchOutcomeStatus.COMPLETED
                if exit_code == 0
                else ProviderLaunchOutcomeStatus.CRASHED
            )
            self._outcome = self._build_outcome(
                status,
                exit_code=self._client.exit_code,
            )
            return self._outcome
        await self._close_client()
        self._outcome = self._build_outcome(
            ProviderLaunchOutcomeStatus.COMPLETED,
            exit_code=self._client.exit_code,
        )
        return self._outcome

    def mark_turn_idle(self) -> ProviderLaunchOutcome:
        """Keep the supervised session alive after one normal ACP prompt turn.

        A normal ``session/prompt`` response only proves that the current turn
        is idle. The delegated-agent controller decides whether to issue a
        follow-up or to close the process after durable outcome settlement.
        """

        self._require_running()
        return self._build_outcome(ProviderLaunchOutcomeStatus.RUNNING)

    async def wait_for_exit(self) -> ProviderLaunchOutcome:
        """Wait for the process to exit on its own and classify clean exit vs. crash.

        Must only be called while the current outcome is `RUNNING`.
        """

        self._require_running()
        try:
            exit_code = await self._client.wait_for_exit()
        except (AcpClientError, OSError) as exc:
            return await self._classify_and_seal_client_error(exc)
        except asyncio.CancelledError:
            await self._cancel_and_close()
            raise
        await self._close_client()
        status = (
            ProviderLaunchOutcomeStatus.COMPLETED
            if exit_code == 0
            else ProviderLaunchOutcomeStatus.CRASHED
        )
        self._outcome = self._build_outcome(status, exit_code=self._client.exit_code)
        return self._outcome

    async def cancel(self) -> ProviderLaunchOutcome:
        """Terminate the entire process group and report a CANCELED outcome.

        Only valid while the current outcome is `RUNNING`. Guarantees no
        descendant process remains once this returns.
        """

        self._require_running()
        await self._cancel_and_close()
        return self._outcome

    async def _classify_and_seal_client_error(
        self, exc: AcpClientError | OSError
    ) -> ProviderLaunchOutcome:
        already_running = (
            self._outcome is not None
            and self._outcome.status == ProviderLaunchOutcomeStatus.RUNNING
        )
        if isinstance(exc, AcpClientTimeoutError):
            status = ProviderLaunchOutcomeStatus.TIMED_OUT
        elif isinstance(exc, AcpClientProtocolError):
            exited = await self._client.wait_for_exit_within(_SPONTANEOUS_EXIT_GRACE_SECONDS)
            if not exited or self._client.exit_code == 0:
                status = ProviderLaunchOutcomeStatus.PROTOCOL_FAILED
            else:
                status = (
                    ProviderLaunchOutcomeStatus.CRASHED
                    if already_running
                    else ProviderLaunchOutcomeStatus.STARTUP_FAILED
                )
        elif await self._client.wait_for_exit_within(_SPONTANEOUS_EXIT_GRACE_SECONDS):
            status = (
                ProviderLaunchOutcomeStatus.CRASHED
                if already_running
                else ProviderLaunchOutcomeStatus.STARTUP_FAILED
            )
        else:
            status = ProviderLaunchOutcomeStatus.PROTOCOL_FAILED
        diagnostic = _truncate_diagnostic(f"{exc}; stderr={self._client.stderr_text}")
        await self._close_client()
        self._outcome = self._build_outcome(
            status, diagnostic_message=diagnostic, exit_code=self._client.exit_code
        )
        return self._outcome

    async def _cancel_and_close(self) -> None:
        await self._close_client()
        self._outcome = self._build_outcome(
            ProviderLaunchOutcomeStatus.CANCELED, exit_code=self._client.exit_code
        )

    async def _close_client(self) -> None:
        close_task = asyncio.create_task(self._client.close())
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await asyncio.shield(close_task)
            raise

    def _require_running(self) -> None:
        if self._outcome is None or self._outcome.status != ProviderLaunchOutcomeStatus.RUNNING:
            raise ProviderProcessSupervisorError(
                "this operation requires a RUNNING launch outcome"
            )

    def _build_outcome(
        self,
        status: ProviderLaunchOutcomeStatus,
        *,
        diagnostic_message: str | None = None,
        exit_code: int | None = None,
    ) -> ProviderLaunchOutcome:
        return ProviderLaunchOutcome(
            status=status,
            provider_profile_id=self._validated_request.provider_profile_id,
            display_name=self._validated_request.display_name,
            runtime_version=self._runtime_version,
            agent_capabilities=self._agent_capabilities,
            diagnostic_message=diagnostic_message,
            exit_code=exit_code,
            pid=self._client.pid,
            protocol_version=self._protocol_version,
        )


async def finalize_interrupted_provider_runs(
    *,
    provider_run_repository: Any,
    provider_interaction_repository: Any,
) -> int:
    """Reconcile provider runs a backend restart left in an active status.

    For each affected run, atomically supersede its pending provider-interaction
    and provider-permission rows (there is no live delivery future to resolve
    after a restart) and transition the run itself to its Package 4C.1 settled
    status. Each transition uses the run's own last-known revision, so the
    existing optimistic-concurrency check already fences out any late write
    against a stale revision. A per-row failure is logged and skipped so one bad
    row cannot block reconciliation of the rest, and the whole function is safe
    to call repeatedly: a run already outside the active-status set is left
    untouched.

    Returns the number of provider runs this call finalized.
    """
    interruption_status_map = {
        "created": "failed",
        "running": "interrupted",
        "waiting_user_input": "interrupted",
        "waiting_permission": "interrupted",
        "canceling": "interrupted",
    }
    interruption_reason_template = (
        "Backend restarted while the provider run was {status!r}; the prior run was not resumed."
    )
    active_runs = await provider_run_repository.list_active_runs()
    finalized = 0
    for run in active_runs:
        run_id = str(run["id"])
        current_status = str(run["status"])
        target_status = interruption_status_map.get(current_status)
        if target_status is None:
            logger.warning(
                "Startup: provider run %s has unreconcilable active status %r; skipping",
                run_id,
                current_status,
            )
            continue
        try:
            await provider_run_repository.finalize_interrupted_run(
                provider_run_id=run_id,
                expected_revision=int(run["revision"]),
                next_status=target_status,
                terminal_reason=interruption_reason_template.format(status=current_status),
            )
            finalized += 1
        except Exception:
            logger.error(
                "Startup: failed to finalize interrupted provider run %s (%s -> %s)",
                run_id,
                current_status,
                target_status,
                exc_info=True,
            )
    return finalized
