"""
Command Approval Service - Main Orchestrator

Coordinates command approval functionality by delegating to specialized modules:
- Risk assessment
- Command generalization
- Pattern matching
- Whitelist management
- Interactive approval

This service provides the main public API for command approval.
"""

import logging
from typing import Dict, Any, Optional, Tuple

from api.core.models.preferences import ExecutionApprovalMode, CommandPattern

from .models import ExecutionApprovalDecision, ExecutionApprovalOutcome
from .risk_assessment import RiskAssessor
from .command_generalization import CommandGeneralizer
from .pattern_matcher import PatternMatcher
from .whitelist_manager import WhitelistManager
from .interactive_approval import InteractiveApprovalManager

logger = logging.getLogger(__name__)


class ExecutionApprovalService:
    """
    Main orchestrator for command approval functionality.

    Composes specialized modules to provide a complete command approval system
    with risk assessment, whitelist management, and interactive user approval.
    """

    def __init__(self, websocket_manager=None):
        self.risk_assessor = RiskAssessor()
        self.generalizer = CommandGeneralizer()
        self.pattern_matcher = PatternMatcher()
        self.whitelist_manager = WhitelistManager(self.generalizer, self.pattern_matcher)

        self.interactive_manager = None
        if websocket_manager:
            self.interactive_manager = InteractiveApprovalManager(websocket_manager, self.generalizer)

        logger.info(f"ExecutionApprovalService initialized (interactive_mode={websocket_manager is not None})")

    async def evaluate_command(
        self,
        command: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionApprovalDecision:
        """Evaluate whether a command needs approval before execution."""
        try:
            from .approval_override import resolve_tool_execution_settings
            settings = resolve_tool_execution_settings(context)

            if settings.safe_execution_mode:
                if settings.block_dangerous_patterns:
                    blocked, block_reason = self.risk_assessor.check_dangerous_patterns(command, settings)
                    if blocked:
                        logger.warning(f"Command blocked (safe mode + dangerous pattern): {command}")
                        return ExecutionApprovalDecision(
                            needs_approval=False,
                            reason=block_reason,
                            risk_level='critical',
                            is_blocked=True,
                            block_reason=block_reason
                        )
                return ExecutionApprovalDecision(
                    needs_approval=True,
                    reason="Safe execution mode: all command execution requires explicit approval",
                    risk_level=self.risk_assessor.assess_risk_level(command)
                )

            if settings.block_dangerous_patterns:
                blocked, block_reason = self.risk_assessor.check_dangerous_patterns(command, settings)
                if blocked:
                    logger.warning(f"Command blocked due to dangerous pattern: {command}")
                    return ExecutionApprovalDecision(
                        needs_approval=False,
                        reason=block_reason,
                        risk_level='critical',
                        is_blocked=True,
                        block_reason=block_reason
                    )

            risk_level = self.risk_assessor.assess_risk_level(command)

            approval_mode = settings.approval_mode

            if approval_mode == ExecutionApprovalMode.ALWAYS_APPROVE:
                logger.debug(f"Command auto-approved (ALWAYS_APPROVE mode): {command}")
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason="Always approve mode enabled",
                    risk_level=risk_level
                )

            if approval_mode == ExecutionApprovalMode.ALWAYS_PROMPT:
                logger.debug(f"Command requires approval (ALWAYS_PROMPT mode): {command}")
                return ExecutionApprovalDecision(
                    needs_approval=True,
                    reason="Always prompt mode enabled",
                    risk_level=risk_level
                )

            if settings.auto_approve_read_only and self.risk_assessor.is_read_only_command(command):
                logger.debug(f"Command auto-approved (read-only): {command}")
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason="Read-only command auto-approved",
                    risk_level='low'
                )

            generalized_command = self.generalizer.generalize_command(command)
            logger.info(f"🔍 Checking whitelist for command: '{command}' (whitelist has {len(settings.whitelisted_commands)} patterns)")
            if generalized_command != command:
                logger.info(f"🔧 Generalized command for whitelist matching: '{generalized_command}'")

            matched_pattern = self.pattern_matcher.check_whitelist(generalized_command, settings.whitelisted_commands)
            if matched_pattern:
                logger.info(f"✅ Command matched whitelist pattern: '{matched_pattern.pattern}' (type: {matched_pattern.pattern_type})")
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason=f"Matched whitelisted pattern: {matched_pattern.description or matched_pattern.pattern}",
                    risk_level=matched_pattern.risk_level,
                    matched_pattern=matched_pattern
                )

            logger.info("❌ Command did not match any whitelist pattern")
            logger.debug(f"Command requires approval (not whitelisted): {command}")
            return ExecutionApprovalDecision(
                needs_approval=True,
                reason="Command not in whitelist",
                risk_level=risk_level
            )

        except Exception as e:
            logger.error(f"Error evaluating command approval: {e}", exc_info=True)
            return ExecutionApprovalDecision(
                needs_approval=True,
                reason=f"Error during evaluation: {str(e)}",
                risk_level='high'
            )

    async def request_approval(
        self,
        command: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, bool, str]:
        """Request user approval for a command via WebSocket and wait for response."""
        outcome = await self.request_approval_with_outcome(command, context)
        return outcome.as_legacy_tuple()

    async def request_approval_with_outcome(
        self,
        command: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionApprovalOutcome:
        """Request approval and preserve why execution can or cannot proceed."""
        decision = await self.evaluate_command(command, context)

        if decision.is_blocked:
            logger.warning(f"Command blocked, no approval possible: {command}")
            return ExecutionApprovalOutcome(
                approved=False,
                status="policy_blocked",
                reason=decision.block_reason or decision.reason,
                decision=decision,
            )

        if not decision.needs_approval:
            logger.debug(f"Command auto-approved: {command}")
            return ExecutionApprovalOutcome(
                approved=True,
                status="approved",
                reason=decision.reason,
                decision=decision,
            )

        if not self.interactive_manager:
            logger.warning(f"Command needs approval but no WebSocket available: {command}")
            return ExecutionApprovalOutcome(
                approved=False,
                status="approval_unavailable",
                reason="Command requires approval but no interactive WebSocket approval channel is available.",
                decision=decision,
            )

        approved, remember, pattern_type = await self.interactive_manager.request_approval(command, decision, context or {})
        if approved:
            return ExecutionApprovalOutcome(
                approved=True,
                remember=remember,
                pattern_type=pattern_type,
                status="approved",
                reason="User approved command execution.",
                decision=decision,
            )
        if pattern_type == "timeout_retry_hint":
            return ExecutionApprovalOutcome(
                approved=False,
                pattern_type=pattern_type,
                status="approval_timed_out",
                reason="Command approval timed out; user did not respond in time. Consider trying an alternative approach.",
                decision=decision,
            )
        if pattern_type == "timeout_denied":
            return ExecutionApprovalOutcome(
                approved=False,
                pattern_type=pattern_type,
                status="approval_timed_out",
                reason="Command approval timed out; user did not respond in time. The command was not executed.",
                decision=decision,
            )
        return ExecutionApprovalOutcome(
            approved=False,
            remember=remember,
            pattern_type=pattern_type,
            status="user_denied",
            reason="Command execution was denied by user.",
            decision=decision,
        )

    async def add_to_whitelist(
        self,
        command: str,
        pattern_type: str = 'exact',
        description: str = '',
        risk_level: str = 'low'
    ) -> CommandPattern:
        """Add a command to the whitelist."""
        return await self.whitelist_manager.add_to_whitelist(
            command, pattern_type, description, risk_level
        )

    async def update_whitelist_pattern(
        self,
        pattern_id: str,
        command: str,
        pattern_type: str = 'exact',
        description: str = ''
    ) -> Optional[CommandPattern]:
        """Update an existing whitelist pattern."""
        return await self.whitelist_manager.update_whitelist_pattern(
            pattern_id, command, pattern_type, description
        )

    async def remove_from_whitelist(self, pattern_id: str) -> bool:
        """Remove a pattern from the whitelist."""
        return await self.whitelist_manager.remove_from_whitelist(pattern_id)

    async def update_pattern_usage(self, pattern_id: str) -> None:
        """Update usage statistics for a whitelisted pattern."""
        await self.whitelist_manager.update_pattern_usage(pattern_id)

    async def handle_approval_response(
        self,
        approval_id: str,
        approved: bool,
        remember: bool = False,
        pattern_type: str = 'exact',
        *,
        agent_task_id: str | None = None,
        expected_revision: int | None = None,
    ) -> None:
        """Process user's approval response from frontend."""
        if self.interactive_manager:
            await self.interactive_manager.handle_approval_response(
                approval_id,
                approved,
                remember,
                pattern_type,
                agent_task_id=agent_task_id,
                expected_revision=expected_revision,
            )
        else:
            logger.info(f"Calling InteractiveApprovalManager class method directly for approval_id={approval_id}")

            from .interactive_approval import InteractiveApprovalManager
            from .command_generalization import CommandGeneralizer

            temp_manager = InteractiveApprovalManager(
                websocket_manager=None,
                generalizer=CommandGeneralizer()
            )
            await temp_manager.handle_approval_response(
                approval_id,
                approved,
                remember,
                pattern_type,
                agent_task_id=agent_task_id,
                expected_revision=expected_revision,
            )
