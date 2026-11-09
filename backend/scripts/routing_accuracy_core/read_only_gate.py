"""Decide whether the check may approve a pending approval card on its own.

The only thing approved is a shell command or AppleScript that the backend's own classifiers prove read-only, so a case that needs a harmless read (listing a folder, reading a calendar) is not blocked by a card.
Everything else, including connector calls, settings changes, browser control, and anything the classifiers cannot prove, is left for the caller to score and deny.
The per-run approval mode stays "always prompt", so the owner's remembered whitelist and the workspace-scope shortcut never apply to a test run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Approving is a rare, bounded step. A case that keeps asking for more is not a simple read, so after this many the next card is treated as a blocking one.
MAX_AUTO_APPROVALS_PER_CASE = 8
_REFUSED_RISK_LEVELS = frozenset({"high", "critical"})

_assessor: Optional[Any] = None


@dataclass(frozen=True)
class GateDecision:
    approve: bool
    reason: str


def _risk_assessor() -> Any:
    global _assessor
    if _assessor is None:
        from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor

        _assessor = RiskAssessor()
    return _assessor


def judge_approval(approval: dict[str, Any]) -> GateDecision:
    """Return whether this pending approval may be approved. The reason is for the log line, never for scoring."""
    execution_type = str(approval.get("execution_type") or "")
    risk_level = str(approval.get("risk_level") or "").lower()
    if risk_level in _REFUSED_RISK_LEVELS:
        return GateDecision(False, f"risk level {risk_level}")
    assessor = _risk_assessor()
    if execution_type == "shell":
        command = str(approval.get("command") or "")
        if assessor.is_read_only_command(command):
            return GateDecision(True, "shell command classified read-only")
        return GateDecision(False, "shell command not proven read-only")
    if execution_type == "applescript":
        from api.services.agent_processing.tools.safety.applescript_read_only_classifier import classify_applescript_read_only

        script = str(approval.get("script_content") or approval.get("command") or "")
        verdict = classify_applescript_read_only(script, assessor.is_read_only_command)
        if verdict.is_read_only:
            return GateDecision(True, f"AppleScript classified read-only: {verdict.reason}")
        return GateDecision(False, "AppleScript not proven read-only")
    return GateDecision(False, f"{execution_type or 'unknown'} approvals are never approved by the check")
