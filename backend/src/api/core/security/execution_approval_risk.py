"""Backend-owned classification of approval changes that need an explicit native confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

RISK_CONFIRMATION_HEADER = "X-Basil-Risk-Confirmed"
RISK_CONFIRMATION_REQUIRED_STATUS = 428
RISK_CONFIRMATION_REQUIRED_CODE = "risk_confirmation_required"
_ALWAYS_APPROVE_MODE = "always_approve"
_BROAD_PATTERN_TYPES = frozenset({"prefix", "regex"})


@dataclass(frozen=True)
class RiskConfirmation:
    title: str
    message: str


def approval_settings_change_risk(
    *,
    requested_approval_mode: Optional[str],
    requested_block_dangerous_patterns: Optional[bool],
    requested_safe_execution_mode: Optional[bool],
    current_approval_mode: str,
    current_block_dangerous_patterns: bool,
    current_safe_execution_mode: bool,
) -> Optional[RiskConfirmation]:
    reasons: list[str] = []
    if requested_approval_mode == _ALWAYS_APPROVE_MODE and current_approval_mode != _ALWAYS_APPROVE_MODE:
        reasons.append("Basil will run every command the agent proposes without asking you first.")
    if requested_block_dangerous_patterns is False and current_block_dangerous_patterns:
        reasons.append("Commands that match known destructive patterns will no longer be blocked.")
    if requested_safe_execution_mode is False and current_safe_execution_mode:
        reasons.append("Safe execution mode will be turned off, so commands run without its additional restrictions.")
    if not reasons:
        return None
    return RiskConfirmation(title="Lower command-approval protection?", message="\n\n".join(reasons))


def added_whitelist_pattern_risk(pattern: str, pattern_type: str) -> RiskConfirmation:
    return RiskConfirmation(
        title="Allow this command without asking?",
        message=f"Commands matching the {pattern_type} pattern “{pattern}” will run without an approval prompt.",
    )


def updated_whitelist_pattern_risk(pattern: str, pattern_type: str) -> Optional[RiskConfirmation]:
    if pattern_type.lower() not in _BROAD_PATTERN_TYPES:
        return None
    return RiskConfirmation(
        title="Broaden this allowed command?",
        message=f"Commands matching the {pattern_type} pattern “{pattern}” will run without an approval prompt.",
    )


def is_risk_confirmed(request: Request) -> bool:
    return request.headers.get(RISK_CONFIRMATION_HEADER, "").strip().lower() == "true"


def require_risk_confirmation(request: Request, risk: Optional[RiskConfirmation]) -> None:
    if risk is None or is_risk_confirmed(request):
        return
    raise HTTPException(
        status_code=RISK_CONFIRMATION_REQUIRED_STATUS,
        detail={"code": RISK_CONFIRMATION_REQUIRED_CODE, "title": risk.title, "message": risk.message},
    )
