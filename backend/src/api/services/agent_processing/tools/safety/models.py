"""
Data models for command approval system.
"""

from dataclasses import dataclass
from typing import Optional

from api.core.models.preferences import CommandPattern


@dataclass
class ExecutionApprovalDecision:
    """Result of command approval evaluation."""
    needs_approval: bool
    reason: str
    risk_level: str  # 'low', 'medium', 'high', 'critical'
    matched_pattern: Optional[CommandPattern] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None


@dataclass
class ExecutionApprovalOutcome:
    """Structured result from an approval request."""

    approved: bool
    remember: bool = False
    pattern_type: str = ""
    status: str = "approved"
    reason: str = ""
    decision: Optional[ExecutionApprovalDecision] = None

    def as_legacy_tuple(self) -> tuple[bool, bool, str]:
        """Return the legacy tuple shape used by older approval callers."""
        return (self.approved, self.remember, self.pattern_type)
