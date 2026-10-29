"""Canonical result envelopes for shell command execution."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_shell_result(
    *,
    success: bool,
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_ms: int,
    cwd: str,
    command_echo: str,
    error_type: Optional[str] = None,
    timed_out: bool = False,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    execution_success: Optional[bool] = None,
    file_artifacts: Optional[List[Dict[str, str]]] = None,
    file_artifact_errors: Optional[List[str]] = None,
    file_artifact_declarations: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build the shared shell response without discarding artifact verification."""
    result: Dict[str, Any] = {
        "success": success,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "cwd": cwd,
        "command_echo": command_echo,
        "timed_out": timed_out,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    if execution_success is not None:
        result["execution_success"] = execution_success
    if error_type:
        result["error_type"] = error_type
    if file_artifacts is not None:
        result["file_artifacts"] = file_artifacts
    if file_artifact_errors:
        result["file_artifact_errors"] = file_artifact_errors
    if file_artifact_declarations is not None:
        result["file_artifact_declarations"] = file_artifact_declarations
    return result


def build_approval_failure_result(
    *,
    cwd: Optional[str],
    command_echo: str,
    outcome: Any,
    file_artifact_declarations: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build the established approval failure payload with unchecked declarations."""
    status = getattr(outcome, "status", "user_denied")
    reason = getattr(outcome, "reason", "") or "Command execution was not approved."
    stderr = reason
    if status == "policy_blocked":
        stderr = f"Command blocked by safety policy: {reason}"
    elif status == "user_denied":
        stderr = "Command execution was denied by user"

    result: Dict[str, Any] = {
        "success": False,
        "stdout": "",
        "stderr": stderr,
        "exit_code": -1,
        "duration_ms": 0,
        "cwd": cwd or "",
        "command_echo": command_echo,
        "approval_required": False,
        "approval_denied": status == "user_denied",
        "approval_blocked": status == "policy_blocked",
        "approval_timed_out": status == "approval_timed_out",
        "approval_unavailable": status == "approval_unavailable",
        "approval_status": status,
        "approval_block_reason": reason if status == "policy_blocked" else None,
        "approval_decision_reason": reason,
        "error_type": status,
    }
    if file_artifact_declarations is not None:
        result["file_artifact_declarations"] = file_artifact_declarations
    return result
