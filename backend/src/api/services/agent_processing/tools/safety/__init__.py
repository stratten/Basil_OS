"""
Command Execution Approval System

Provides secure command approval with risk assessment, whitelist management,
and interactive user prompts for agent-processing tools.
"""

from .execution_approval_service import ExecutionApprovalService
from .models import ExecutionApprovalDecision

__all__ = [
    'ExecutionApprovalService',
    'ExecutionApprovalDecision',
]
