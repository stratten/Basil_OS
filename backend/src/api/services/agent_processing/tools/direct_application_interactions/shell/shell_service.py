import asyncio
import logging
import os
import re
import shlex
import signal
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.services.agent_processing.shared.agent_runtime_context import (
    AGENT_RUN_STARTED_AT_KEY,
    get_current_agent_context,
)
from api.services.agent_processing.lifecycle.execution_graph.tool_run_watchdog import record_tool_progress
from api.core.security.protected_runtime_paths import (
    PROTECTED_RUNTIME_REFUSAL,
    is_protected_runtime_path,
    log_protected_runtime_refusal,
    references_protected_runtime_path,
)
from api.services.agent_processing.tools.safety import ExecutionApprovalService
from .shell_execution_result import build_approval_failure_result, build_shell_result
from .shell_file_artifacts import (
    prepare_file_operations,
    serialize_file_operation_declarations,
    verify_file_operations,
)
from .shell_material_operation_receipts import attach_shell_material_operation_receipts
from api.services.agent_processing.shared.workflow_budget_pause import pause_workflow_budget
from .command_input_broker import CommandInputBroker
from .shell_process_runner import (
    MAX_INPUT_RELAYS,
    NON_INTERACTIVE_ENV_DEFAULTS,
    CommandInputReply,
    InputRequester,
    ShellRunOutcome,
    run_shell_process,
)
from ..shared.agent_task_workspace import resolve_agent_task_workspace
from ..shared.cwd_allowlist import detect_repo_root, home_root, resolve_and_validate_cwd

logger = logging.getLogger(__name__)

_INPUT_STOP_GUIDANCE: Dict[str, str] = {
    "input_required": (
        "Nobody was available to answer it. Re-run the command non-interactively "
        "(for example --yes, -y, --no-input, or a supported flag or file for credentials)."
    ),
    "input_canceled": "The user declined to answer. Do not retry the same interactive command; ask the user how to proceed.",
    "input_timeout": "The user did not answer in time. Ask the user before retrying.",
    "input_limit": f"The command asked for input more than {MAX_INPUT_RELAYS} times. Re-run it non-interactively.",
}


class ShellService:
    """Secure, non-interactive shell execution service.

    Provides a single method `execute_command` that executes a command with
    strict timeouts, output caps, and working-directory allowlisting.
    Returns a structured dict suitable for tool wrapping.
    """

    def __init__(self, websocket_manager=None) -> None:
        self._initialized: bool = False
        self._default_timeout_s: int = 20
        self._max_timeout_s: int = 60
        self._default_output_cap: int = 1_000_000  # 1 MB per stream
        # Resolve repo root (directory that contains a 'src' folder)
        self._repo_root: Path = detect_repo_root()
        self._home_root: Path = home_root()
        
        # Command approval integration - created lazily when needed
        self._approval_service: Optional[ExecutionApprovalService] = None
        self._websocket_manager = websocket_manager
        # Set per-request by the coordinator so approval broadcasts can route to the right agent
        self._agent_task_id: Optional[str] = None

    async def initialize(self) -> bool:
        self._initialized = True
        return True

    def get_service_capabilities(self) -> Dict[str, Any]:
        slim_doc = (
            "Run a non-interactive shell command. command is the executable "
            "(e.g. 'mdfind', 'git', 'rg'); for pipelines / shell features "
            "use command='bash' with args=['-lc', '<your one-liner>']. "
            "Output is captured with byte caps and there is a hard "
            "timeout (<=60s). Some commands trigger user approval; treat "
            "an approval_blocked / approval_decision='denied' response as "
            "final. Do NOT use shell to reimplement native macOS app work "
            "(timers, reminders, calendar events, alarms) - use "
            "applescript_service for those. If a command stops at a prompt, "
            "Basil relays it to the user; prefer non-interactive flags "
            "(--yes, -y, --no-input) so commands never need to ask."
        )
        return {
            "methods": {
                "execute_command": {
                    "signature": (
                        "execute_command("
                        "command: str, args: List[str] = None, cwd: str = None, "
                        "env_overrides: Dict[str,str] = None, timeout_s: int = None, "
                        "max_output_bytes: int = None, file_operations: List[Dict[str,str]] = None) -> Dict"
                    ),
                    "doc": "Run a non-interactive shell command. Output is captured and size-limited. Commands may require user approval.",
                    "slim_doc": slim_doc,
                    "parameters": {
                        "command": {"type": "str", "required": True, "description": "Executable to run (e.g., bash)."},
                        "args": {"type": "list", "required": False, "description": "Argument vector."},
                        "cwd": {"type": "str", "required": False, "description": "Working directory (allowlist enforced). Omit to use this task's scratch workspace."},
                        "env_overrides": {"type": "dict", "required": False, "description": "Explicit environment overrides (allowlisted)."},
                        "timeout_s": {"type": "int", "required": False, "description": "Hard timeout in seconds (≤60)."},
                        "max_output_bytes": {"type": "int", "required": False, "description": "Per-stream output cap (bytes)."},
                        "file_operations": {
                            "type": "list",
                            "required": False,
                            "description": "Declared filesystem changes. Each item requires operation and absolute path; copy, move, and rename also require source_path. Use record for a file an earlier command in this task already wrote without a declaration.",
                        },
                    },
                    "returns": "Dict {success, stdout, stderr, exit_code, duration_ms, cwd, command_echo, approval_required?, approval_blocked?, approval_decision?}",
                }
            },
            "description": "Secure shell execution service for non-interactive CLI tasks with command approval",
            "features": ["timeout", "output_caps", "cwd_allowlist", "env_allowlist", "execution_approval", "risk_assessment"],
            "execution_principles": [
                "Do not use shell to reimplement functionality available in native macOS apps (timers, reminders, calendar events, alarms). Use AppleScript to delegate to those apps instead.",
                "Commands may require user approval based on risk level and whitelist settings.",
            ],
        }

    async def execute_command(
        self,
        command: str,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        timeout_s: Optional[int] = None,
        max_output_bytes: Optional[int] = None,
        file_operations: Optional[List[Dict[str, str]]] = None,
        skip_approval_check: bool = False,
    ) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()

        argv = [command] + (args or [])
        full_command = self._echo_argv(argv)
        shell_execution_id = str(uuid.uuid4())
        agent_task_id = get_current_agent_context().get("agent_task_id") or self._agent_task_id
        try:
            declared_file_operations = prepare_file_operations(
                file_operations,
                (self._home_root, self._repo_root),
                recorded_after=self._agent_run_started_at(),
            )
        except ValueError as exc:
            return build_shell_result(
                success=False,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                duration_ms=0,
                cwd=cwd or "",
                command_echo=self._redact_secrets(full_command),
                error_type="file_artifact_declaration_invalid",
            )
        unchecked_file_declarations = serialize_file_operation_declarations(
            declared_file_operations,
            verification_status="not_checked",
        )
        if self._is_bare_interactive_shell(command, args):
            logger.warning("Rejected bare interactive shell command: %s", full_command)
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    "Refusing to run a bare interactive shell. Provide explicit arguments, "
                    'for example command="bash" with args=["-lc", "<command>"].'
                ),
                "exit_code": -1,
                "duration_ms": 0,
                "cwd": cwd or "",
                "command_echo": self._redact_secrets(full_command),
            }
        
        env_override_values = [str(value) for value in (env_overrides or {}).values()]
        if references_protected_runtime_path(full_command, cwd, *env_override_values) or (
            cwd is not None and is_protected_runtime_path(cwd)
        ):
            log_protected_runtime_refusal("shell command")
            return {
                "success": False,
                "stdout": "",
                "stderr": PROTECTED_RUNTIME_REFUSAL,
                "exit_code": -1,
                "duration_ms": 0,
                "cwd": cwd or "",
                "command_echo": self._redact_secrets(full_command),
            }

        # Command approval check (if enabled)
        # Create approval service lazily with WebSocket support
        if not skip_approval_check:
            if self._approval_service is None:
                self._approval_service = ExecutionApprovalService(websocket_manager=self._websocket_manager)
            
        if not skip_approval_check and self._approval_service:
            try:
                # Request approval - returns immediately so modal can close
                # Actual execution happens after approval is recorded
                approval_context: Dict[str, Any] = {
                    "cwd": cwd,
                    "source": "shell_service",
                    "description": f"Execute shell command: {command}",
                }
                if unchecked_file_declarations:
                    approval_context["file_operations"] = unchecked_file_declarations
                if isinstance(agent_task_id, str) and agent_task_id.strip():
                    approval_context["agent_task_id"] = agent_task_id
                record_tool_progress(
                    agent_task_id=agent_task_id,
                    tool_name="shell_service_execute_command",
                    status="approval_waiting",
                    progress_kind="approval_requested",
                    command_echo=self._redact_secrets(full_command),
                    shell_execution_id=shell_execution_id,
                )
                approval_outcome = await self._approval_service.request_approval_with_outcome(
                    full_command,
                    context=approval_context,
                )
                
                # If user denied or approval failed, return error
                if not approval_outcome.approved:
                    logger.warning(
                        "Command approval did not allow execution: status=%s reason=%s command=%s",
                        approval_outcome.status,
                        approval_outcome.reason,
                        full_command,
                    )
                    record_tool_progress(
                        agent_task_id=agent_task_id,
                        tool_name="shell_service_execute_command",
                        status="returned",
                        progress_kind=approval_outcome.status,
                        command_echo=self._redact_secrets(full_command),
                        shell_execution_id=shell_execution_id,
                        approval_status=approval_outcome.status,
                    )
                    return attach_shell_material_operation_receipts(build_approval_failure_result(
                        cwd=cwd,
                        command_echo=self._redact_secrets(full_command),
                        outcome=approval_outcome,
                        file_artifact_declarations=unchecked_file_declarations,
                    ), declared_file_operations)
                
                # If user approved and wants to remember, add to whitelist
                if approval_outcome.remember:
                    try:
                        await self._approval_service.add_to_whitelist(
                            full_command,
                            pattern_type=approval_outcome.pattern_type,
                            description="User-approved shell command",
                            record_initial_use=True,
                        )
                        logger.info(f"Added command to whitelist: {full_command} (type: {approval_outcome.pattern_type})")
                    except Exception as e:
                        logger.warning(f"Failed to add command to whitelist: {e}")
                
                # Command approved but not executed yet (no callback or auto-approved)
                # Continue with normal execution below
                logger.info(f"Command approved for execution: {full_command}")
                record_tool_progress(
                    agent_task_id=agent_task_id,
                    tool_name="shell_service_execute_command",
                    status="service_running",
                    progress_kind="approval_granted",
                    command_echo=self._redact_secrets(full_command),
                    shell_execution_id=shell_execution_id,
                    approval_status=approval_outcome.status,
                )
                
            except Exception as e:
                logger.error(f"Error during command approval check: {e}", exc_info=True)
                # Fail secure: treat as needs approval
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Command approval check failed: {str(e)}",
                    "exit_code": -1,
                    "duration_ms": 0,
                    "cwd": cwd or "",
                    "command_echo": self._redact_secrets(full_command),
                    "approval_required": True,
                    "approval_blocked": False,
                    "approval_decision": {
                        "risk_level": "high",
                        "reason": "Approval check error",
                        "needs_approval": True
                    }
                }
        
        safe_cwd, cwd_error = self._resolve_and_validate_cwd(cwd)
        if cwd_error:
            return {
                "success": False,
                "stdout": "",
                "stderr": cwd_error,
                "exit_code": -1,
                "duration_ms": 0,
                "cwd": cwd or "",
                "command_echo": self._redact_secrets(self._echo_argv(argv)),
            }

        try:
            declared_file_operations = prepare_file_operations(
                file_operations,
                (self._home_root, self._repo_root),
                recorded_after=self._agent_run_started_at(),
            )
        except ValueError as exc:
            return build_shell_result(
                success=False,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                duration_ms=0,
                cwd=str(safe_cwd) if safe_cwd else "",
                command_echo=self._redact_secrets(self._echo_argv(argv)),
                error_type="file_artifact_declaration_invalid",
            )

        # Timeouts and caps
        eff_timeout = self._clamp_timeout(timeout_s)
        eff_cap = max_output_bytes if (isinstance(max_output_bytes, int) and max_output_bytes > 0) else self._default_output_cap

        # Environment handling – allow explicit overrides only
        env = os.environ.copy()
        env.update(NON_INTERACTIVE_ENV_DEFAULTS)
        if env_overrides:
            for k, v in env_overrides.items():
                if isinstance(k, str) and isinstance(v, str):
                    env[k] = v

        command_echo = self._redact_secrets(self._echo_argv(argv))

        def _record_process_started(pid: int) -> None:
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name="shell_service_execute_command",
                status="service_running",
                progress_kind="process_started",
                command_echo=command_echo,
                shell_execution_id=shell_execution_id,
                pid=pid,
                timeout_seconds=float(eff_timeout),
            )

        start = time.time()
        try:
            # Use non-interactive exec (no shell=True). If user needs shell features, they must pass
            # command="bash" and args=["-lc", "actual command"] explicitly.
            run = await run_shell_process(
                argv,
                cwd=str(safe_cwd) if safe_cwd else None,
                env=env,
                timeout_seconds=float(eff_timeout),
                input_requester=self._build_input_requester(
                    agent_task_id=agent_task_id,
                    shell_execution_id=shell_execution_id,
                    command_echo=command_echo,
                ),
                on_started=_record_process_started,
            )

            # Enforce output caps
            stdout, stdout_truncated = self._decode_capped_output(run.stdout_bytes, eff_cap)
            stderr, stderr_truncated = self._decode_capped_output(run.stderr_bytes, eff_cap)
            if run.timed_out or run.input_status:
                return self._build_stopped_result(
                    run=run,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                    eff_timeout=eff_timeout,
                    cwd=str(safe_cwd) if safe_cwd else "",
                    command_echo=command_echo,
                    agent_task_id=agent_task_id,
                    shell_execution_id=shell_execution_id,
                )
            exit_code = run.exit_code
            duration_ms = run.duration_ms
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name="shell_service_execute_command",
                status="returned",
                progress_kind="process_exited",
                command_echo=command_echo,
                shell_execution_id=shell_execution_id,
                pid=run.pid,
                exit_code=exit_code,
                duration_ms=duration_ms,
                stdout_bytes=len(run.stdout_bytes),
                stderr_bytes=len(run.stderr_bytes),
            )
            file_artifacts: List[Dict[str, str]] = []
            file_artifact_errors: List[str] = []
            if exit_code == 0 and declared_file_operations:
                file_artifacts, file_artifact_errors = verify_file_operations(declared_file_operations)

            return self._attach_run_details(attach_shell_material_operation_receipts(build_shell_result(
                success=exit_code == 0 and not file_artifact_errors,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
                cwd=str(safe_cwd) if safe_cwd else "",
                command_echo=self._redact_secrets(self._echo_argv(argv)),
                error_type=(
                    "file_artifact_verification_failed"
                    if file_artifact_errors
                    else None if exit_code == 0 else "nonzero_exit"
                ),
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                execution_success=exit_code == 0,
                file_artifacts=file_artifacts,
                file_artifact_errors=file_artifact_errors,
                file_artifact_declarations=serialize_file_operation_declarations(
                    declared_file_operations,
                    verification_status="verified" if not file_artifact_errors and exit_code == 0 else "not_checked",
                ),
            ), declared_file_operations), run)

        except FileNotFoundError:
            duration_ms = int((time.time() - start) * 1000)
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name="shell_service_execute_command",
                status="returned",
                progress_kind="executable_not_found",
                command_echo=self._redact_secrets(self._echo_argv(argv)),
                shell_execution_id=shell_execution_id,
                duration_ms=duration_ms,
            )
            return build_shell_result(
                success=False,
                stdout="",
                stderr=f"Executable not found: {shlex.quote(command)}",
                exit_code=-1,
                duration_ms=duration_ms,
                cwd=str(safe_cwd) if safe_cwd else "",
                command_echo=self._redact_secrets(self._echo_argv(argv)),
                error_type="executable_not_found",
            )

    # ---------------------------
    # Internal helpers
    # ---------------------------
    def _build_input_requester(
        self,
        *,
        agent_task_id: Optional[str],
        shell_execution_id: str,
        command_echo: str,
    ) -> Optional[InputRequester]:
        if not (isinstance(agent_task_id, str) and agent_task_id.strip()) or self._websocket_manager is None:
            return None
        websocket_manager = self._websocket_manager

        async def _request(prompt: str, secret: bool) -> CommandInputReply:
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name="shell_service_execute_command",
                status="input_waiting",
                progress_kind="input_requested",
                command_echo=command_echo,
                shell_execution_id=shell_execution_id,
            )
            try:
                with pause_workflow_budget("command_input"):
                    return await CommandInputBroker.request_input(
                        agent_task_id=agent_task_id,
                        prompt=self._redact_secrets(prompt),
                        secret=secret,
                        command_echo=command_echo,
                        websocket_manager=websocket_manager,
                    )
            finally:
                record_tool_progress(
                    agent_task_id=agent_task_id,
                    tool_name="shell_service_execute_command",
                    status="service_running",
                    progress_kind="input_resolved",
                    command_echo=command_echo,
                    shell_execution_id=shell_execution_id,
                )

        return _request

    def _attach_run_details(self, result: Dict[str, Any], run: ShellRunOutcome) -> Dict[str, Any]:
        if run.input_exchanges:
            result["input_exchanges"] = [
                {
                    "prompt": self._redact_secrets(str(exchange.get("prompt") or "")),
                    "secret": bool(exchange.get("secret")),
                    "status": exchange.get("status"),
                }
                for exchange in run.input_exchanges
            ]
            result["input_wait_ms"] = run.input_wait_ms
        if run.input_status:
            result["input_status"] = run.input_status
            result["input_prompt"] = self._redact_secrets(run.pending_prompt or "")
        if run.timeout_clock:
            result["timeout_clock"] = run.timeout_clock
        if run.terminal_output.strip():
            result["terminal_output"] = self._redact_secrets(run.terminal_output)
        return result

    def _build_stopped_result(
        self,
        *,
        run: ShellRunOutcome,
        stdout: str,
        stderr: str,
        stdout_truncated: bool,
        stderr_truncated: bool,
        eff_timeout: int,
        cwd: str,
        command_echo: str,
        agent_task_id: Optional[str],
        shell_execution_id: str,
    ) -> Dict[str, Any]:
        partial_output = bool(run.stdout_bytes or run.stderr_bytes)
        if run.timed_out:
            reason = f"Command timed out after {eff_timeout}s"
            if run.timeout_clock == "wall_clock":
                reason += " (wall-clock bound reached; the Mac may have slept while it ran)"
            if partial_output:
                reason += ". Output above is partial."
            error_type = "timeout"
            progress_kind = "process_timed_out"
        else:
            prompt = self._redact_secrets(run.pending_prompt or "")
            guidance = _INPUT_STOP_GUIDANCE.get(run.input_status or "", _INPUT_STOP_GUIDANCE["input_required"])
            reason = f"Command stopped while waiting for input ({prompt!r}). {guidance}"
            error_type = run.input_status or "input_required"
            progress_kind = "process_stopped_for_input"
        combined_stderr = f"{stderr.rstrip()}\n{reason}" if stderr.strip() else reason
        record_tool_progress(
            agent_task_id=agent_task_id,
            tool_name="shell_service_execute_command",
            status="returned",
            progress_kind=progress_kind,
            command_echo=command_echo,
            shell_execution_id=shell_execution_id,
            pid=run.pid,
            duration_ms=run.duration_ms,
        )
        result = build_shell_result(
            success=False,
            stdout=stdout,
            stderr=combined_stderr,
            exit_code=-1,
            duration_ms=run.duration_ms,
            cwd=cwd,
            command_echo=command_echo,
            error_type=error_type,
            timed_out=run.timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
        result["partial_output"] = partial_output
        return self._attach_run_details(result, run)

    def _resolve_and_validate_cwd(self, cwd: Optional[str]) -> (Optional[Path], Optional[str]):
        if not cwd:
            default_workspace = self._default_task_workspace()
            if default_workspace is not None:
                return default_workspace, None
            return None, None
        return resolve_and_validate_cwd(cwd, allowed_roots=(self._home_root, self._repo_root))

    def _agent_run_started_at(self) -> Optional[float]:
        started_at = get_current_agent_context().get(AGENT_RUN_STARTED_AT_KEY)
        return float(started_at) if isinstance(started_at, (int, float)) else None

    def _default_task_workspace(self) -> Optional[Path]:
        """Return the current agent task's scratch workspace, if one is running.

        Falls back to None (today's behavior: inherit the backend process's
        own cwd) when there's no agent task in flight, e.g. direct unit-test
        construction of ShellService with no runtime context.
        """
        context = get_current_agent_context()
        task_id = (
            context.get("root_task_id")
            or context.get("agent_task_id")
            or self._agent_task_id
        )
        if not isinstance(task_id, str) or not task_id.strip():
            return None
        try:
            return resolve_agent_task_workspace(task_id)
        except OSError:
            logger.warning("Could not create agent task workspace for task_id=%s", task_id, exc_info=True)
            return None

    @staticmethod
    def _is_bare_interactive_shell(command: str, args: Optional[List[str]]) -> bool:
        shell_name = Path(command).name.lower() if command else ""
        return shell_name in {"bash", "sh", "zsh"} and not args

    def _clamp_timeout(self, t: Optional[int]) -> int:
        if not isinstance(t, int) or t <= 0:
            return self._default_timeout_s
        return min(t, self._max_timeout_s)

    async def _terminate_timed_out_process(self, proc: asyncio.subprocess.Process) -> None:
        """Terminate a still-running child process (SIGTERM, then SIGKILL).

        Shared by the timeout and cancellation paths, so the message is neutral;
        each caller logs its own timeout/cancel context.
        """
        if proc.returncode is not None:
            return

        logger.warning("Terminating command process group for PID %s", proc.pid)
        try:
            process_group_id = os.getpgid(proc.pid)
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            return
        wait_task = asyncio.create_task(proc.wait())
        deadline = asyncio.get_running_loop().time() + 0.5
        while self._process_group_exists(process_group_id):
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.01)
        if self._process_group_exists(process_group_id):
            logger.warning("Command process group for PID %s did not terminate; killing", proc.pid)
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await wait_task
        try:
            await proc.communicate()
        except (ProcessLookupError, RuntimeError):
            pass

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @staticmethod
    def _decode_capped_output(output_bytes: Optional[bytes], cap: int) -> tuple[str, bool]:
        raw_output = output_bytes or b""
        truncated = len(raw_output) > cap
        decoded = raw_output[:cap].decode("utf-8", errors="replace")
        if truncated:
            decoded += (
                f"\n\n[Output truncated by Basil shell cap: returned first {cap} bytes "
                f"of {len(raw_output)} bytes. Do not treat this output as exhaustive.]"
            )
        return decoded, truncated

    @staticmethod
    def _echo_argv(argv: List[str]) -> str:
        return " ".join(shlex.quote(a) for a in argv)

    @staticmethod
    def _redact_secrets(text: str) -> str:
        if not text:
            return text
        # Simple patterns: sk- keys, api_key=..., bearer tokens
        patterns = [
            r"sk-[A-Za-z0-9]{10,}",
            r"(?i)api_key=[^\s]+",
            r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]+",
        ]
        redacted = text
        for pat in patterns:
            redacted = re.sub(pat, "[REDACTED]", redacted)
        return redacted


