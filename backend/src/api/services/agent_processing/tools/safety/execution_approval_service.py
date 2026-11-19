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

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import ExecutionApprovalMode, CommandPattern
from api.core.security.protected_runtime_paths import (
    PROTECTED_RUNTIME_REFUSAL,
    log_protected_runtime_refusal,
    references_protected_runtime_path,
)
from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

from .command_safety_judge import UNSURE, judge_command_safety
from .models import ExecutionApprovalDecision, ExecutionApprovalOutcome
from .risk_assessment import RiskAssessor
from .python_read_only_command import classify_python_command_read_only
from .shell_syntax import classify_read_only
from .workspace_scope import judge_workspace_command
from .task_auto_approve import is_task_auto_approve_enabled
from .command_generalization import CommandGeneralizer
from .pattern_matcher import PatternMatcher
from .whitelist_eligibility import CONNECTED_TOOL_ASK_REASON, is_connected_tool_command
from .whitelist_manager import WhitelistManager
from .interactive_approval import InteractiveApprovalManager
from .explanation_gate import (
    EXPLANATION_REQUIRED_MESSAGE,
    EXPLANATION_REQUIRED_STATUS,
    should_request_explanation,
)

logger = logging.getLogger(__name__)
# Module loggers are not wired to the desktop debug log, so each decision goes through a child of the main API logger. That is how a day's auto-approvals can be reviewed afterward.
decision_logger = api_logger.getChild("command_approval")
MAX_LOGGED_COMMAND_CHARS = 200


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
        """Evaluate whether a command needs approval before execution, and record the verdict in the debug log."""
        decision = await self._evaluate_command(command, context)
        try:
            outcome = "blocked" if decision.is_blocked else ("asks" if decision.needs_approval else "auto-approved")
            # A connected tool's arguments can hold message text and addresses, so only its name is recorded.
            shown = str(command).split("(", 1)[0] if is_connected_tool_command(command) else " ".join(str(command).split())
            if len(shown) > MAX_LOGGED_COMMAND_CHARS:
                shown = f"{shown[:MAX_LOGGED_COMMAND_CHARS]}…"
            decision_logger.info("Command %s (risk=%s, reason=%s): %s", outcome, decision.risk_level, decision.reason, shown)
        except Exception:  # a logging problem must never change the verdict
            pass
        return decision

    async def _evaluate_command(
        self,
        command: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionApprovalDecision:
        try:
            if references_protected_runtime_path(command):
                log_protected_runtime_refusal("command evaluation")
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason=PROTECTED_RUNTIME_REFUSAL,
                    risk_level='critical',
                    is_blocked=True,
                    block_reason=PROTECTED_RUNTIME_REFUSAL,
                )
            from .approval_override import resolve_tool_execution_settings
            settings = resolve_tool_execution_settings(context)

            if (context or {}).get("require_explicit_approval") is True:
                # Trust-granting actions (such as connecting an external service) are never skipped by "always approve", read-only auto-approval, or a remembered pattern.
                return ExecutionApprovalDecision(
                    needs_approval=True,
                    reason="This action always needs the user's explicit approval",
                    risk_level='high',
                )

            if self.task_auto_approve_may_apply(command, context) and is_task_auto_approve_enabled(self.task_root_id(context)):
                # The user turned on auto-approve for this task. It overrides Safe Execution Mode, Always Prompt, and the whitelist, but the dangerous-pattern block above everything else still holds, and so do the exclusions in task_auto_approve_may_apply.
                if settings.block_dangerous_patterns:
                    blocked, block_reason = self.risk_assessor.check_dangerous_patterns(command, settings)
                    if blocked:
                        logger.warning(f"Command blocked (auto-approve on, dangerous pattern): {command}")
                        return ExecutionApprovalDecision(
                            needs_approval=False,
                            reason=block_reason,
                            risk_level='critical',
                            is_blocked=True,
                            block_reason=block_reason
                        )
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason="Auto-approve is on for this task",
                    risk_level=self.risk_assessor.assess_risk_level(command)
                )

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

            scope = (context or {}).get("workspace_scope")
            if isinstance(scope, dict):
                verdict = judge_workspace_command(
                    scope.get("argv"),
                    workspace=scope.get("workspace"),
                    cwd=scope.get("cwd"),
                    has_env_overrides=bool(scope.get("has_env_overrides")),
                )
                if verdict.allowed:
                    logger.debug(f"Command auto-approved (inside the task workspace): {command}")
                    return ExecutionApprovalDecision(
                        needs_approval=False,
                        reason=verdict.reason,
                        risk_level='low'
                    )

            if settings.auto_approve_read_only and self.risk_assessor.is_read_only_command(command):
                logger.debug(f"Command auto-approved (read-only): {command}")
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason="Read-only command auto-approved",
                    risk_level='low'
                )

            if settings.auto_approve_read_only:
                # A Python one-liner is judged by its parsed script, not by its command name, and needs the working directory to rule out a module that shadows the standard library.
                python_scope = scope if isinstance(scope, dict) else {}
                python_verdict = classify_python_command_read_only(
                    command,
                    working_directory=python_scope.get("cwd"),
                    has_env_overrides=bool(python_scope.get("has_env_overrides")),
                )
                if python_verdict.is_read_only:
                    logger.debug(f"Command auto-approved (read-only Python script): {command}")
                    return ExecutionApprovalDecision(
                        needs_approval=False,
                        reason="Read-only Python script auto-approved",
                        risk_level='low'
                    )

            logger.info(f"🔍 Checking whitelist for command: '{command}' (whitelist has {len(settings.whitelisted_commands)} patterns)")

            # The raw command is matched, word by word: a shortened copy would make every `gh ...` command look like `gh`.
            # An AppleScript is reviewed every time (see assess_whitelist_eligibility), and its remembered text is only the agent's description of it. An entry saved before that rule, such as the prefix "AppleScript:", must not approve a different script.
            scripts_are_reviewed = (context or {}).get("execution_type") == "applescript"
            matched_pattern = None if scripts_are_reviewed else self.pattern_matcher.check_whitelist(command, settings.whitelisted_commands)
            if matched_pattern:
                if self.risk_assessor.is_high_risk(command):
                    logger.info(f"⚠️ High-risk command matched '{matched_pattern.pattern}'; asking again")
                    return ExecutionApprovalDecision(
                        needs_approval=True,
                        reason=f"This matches the remembered pattern '{matched_pattern.pattern}', but the command is high risk, so it needs your approval again",
                        risk_level='high',
                    )
                logger.info(f"✅ Command matched whitelist pattern: '{matched_pattern.pattern}' (type: {matched_pattern.pattern_type})")
                return ExecutionApprovalDecision(
                    needs_approval=False,
                    reason=f"Matched whitelisted pattern: {matched_pattern.description or matched_pattern.pattern}",
                    risk_level=matched_pattern.risk_level,
                    matched_pattern=matched_pattern
                )

            if settings.auto_approve_read_only and not scripts_are_reviewed and not is_connected_tool_command(command):
                # A script is judged one command at a time: it runs unasked when every command in it is read-only or one the user has already remembered, because then nothing in it is new to the user. The remembered patterns are only ever for plain commands, so a script of several commands could never match one as a whole.
                remembered_verdict = classify_read_only(
                    command,
                    remembered=lambda words: self.pattern_matcher.covers_words(words, settings.whitelisted_commands),
                )
                if remembered_verdict.is_read_only and not self.risk_assessor.is_high_risk(command):
                    logger.info(f"✅ Every command in the script is read-only or remembered: '{command[:120]}'")
                    return ExecutionApprovalDecision(
                        needs_approval=False,
                        reason="Every command in it is read-only or one you already approved and remembered",
                        risk_level=risk_level
                    )

            judge_note = ""
            if settings.model_judges_command_safety and not scripts_are_reviewed and not is_connected_tool_command(command):
                # Opt-in. A separate model reviews the command alone (no conversation, no explanation from the agent). Only a confident "reads only" skips the prompt; a high-risk command is never decided by the model, and anything else, including a failure of the model itself, asks as it always did.
                if not self.risk_assessor.is_high_risk(command):
                    judgment = await judge_command_safety(command, cwd=(context or {}).get("cwd"))
                    logger.info(
                        f"[AgentTelemetry] command-judge verdict={judgment.verdict} confidence={judgment.confidence:.2f} "
                        f"seconds={judgment.seconds:.2f} model={judgment.model_name or 'none'} reason={judgment.reason!r} command={command[:160]!r}"
                    )
                    if judgment.approves:
                        return ExecutionApprovalDecision(
                            needs_approval=False,
                            reason=f"A separate model check found that this only reads: {judgment.reason}",
                            risk_level=risk_level
                        )
                    if judgment.verdict != UNSURE:
                        judge_note = f"A separate model check says it may change something: {judgment.reason}"
                    else:
                        judge_note = f"A separate model check was not sure: {judgment.reason}"

            logger.info("❌ Command did not match any whitelist pattern")
            logger.debug(f"Command requires approval (not whitelisted): {command}")
            # A connected tool is never matched against the whitelist; it reaches here because its policy is Always ask.
            if is_connected_tool_command(command):
                reason = CONNECTED_TOOL_ASK_REASON
            else:
                reason = "Command not in whitelist"
                if settings.auto_approve_read_only:
                    # The read-only check already ran and said why it refused, so the card says that instead of leaving the reader to guess which part of the command asked.
                    refusal = classify_read_only(command)
                    if not refusal.is_read_only:
                        reason = f"Needs your approval because {refusal.reason}, and no remembered approval covers it"
            if judge_note:
                reason = f"{reason}. {judge_note}"
            return ExecutionApprovalDecision(
                needs_approval=True,
                reason=reason,
                risk_level=risk_level
            )

        except Exception as e:
            logger.error(f"Error evaluating command approval: {e}", exc_info=True)
            return ExecutionApprovalDecision(
                needs_approval=True,
                reason=f"Error during evaluation: {str(e)}",
                risk_level='high'
            )

    @staticmethod
    def task_root_id(context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """The chain root an approval belongs to: the caller's context first, then the running agent's context, so every caller is covered without each one naming it."""
        run_context = get_current_agent_context() or {}
        supplied = context or {}
        for candidate in (
            supplied.get("root_task_id"),
            run_context.get("root_task_id"),
            supplied.get("agent_task_id"),
            run_context.get("agent_task_id"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    @staticmethod
    def task_auto_approve_may_apply(command: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Whether a task's auto-approve switch may approve this request when it is on.

        A trust-granting action (marked require_explicit_approval) and a connected tool, which has its own always-ask policy, are never covered. Settings changes, requests for typed input, and sensitive browser fills do not pass through this service at all, so they keep asking whatever the switch says.
        """
        if (context or {}).get("require_explicit_approval") is True:
            return False
        return not is_connected_tool_command(command)

    async def approve_waiting_for_task(self, root_task_id: str) -> int:
        """Approve the cards this task is already waiting on, which the switch would have approved. Returns how many were approved."""
        from .interactive_approval import InteractiveApprovalManager

        approved = 0
        for approval_id in InteractiveApprovalManager.auto_approvable_pending_ids(root_task_id):
            try:
                await self.handle_approval_response(approval_id, True, False, "exact")
                approved += 1
            except Exception as error:  # a card the user just answered, or one retired meanwhile, is simply skipped
                logger.info("Skipped approving waiting card %s for task %s: %s", approval_id, root_task_id, error)
        return approved

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
            # Counted here rather than in evaluate_command so the read-only /evaluate route never inflates usage.
            if decision.matched_pattern is not None:
                await self.update_pattern_usage(decision.matched_pattern.id)
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

        if should_request_explanation(command, context or {}):
            logger.info("Asking the agent to explain a command before prompting the user: %s", command[:120])
            return ExecutionApprovalOutcome(
                approved=False,
                pattern_type=EXPLANATION_REQUIRED_STATUS,
                status=EXPLANATION_REQUIRED_STATUS,
                reason=EXPLANATION_REQUIRED_MESSAGE,
                decision=decision,
            )

        note_sink: Dict[str, str] = {}
        approved, remember, pattern_type = await self.interactive_manager.request_approval(
            command,
            decision,
            context or {},
            note_sink=note_sink,
            auto_approve_root=self.task_root_id(context) if self.task_auto_approve_may_apply(command, context) else None,
        )
        user_note = note_sink.get("user_note", "")
        if approved:
            return ExecutionApprovalOutcome(
                approved=True,
                remember=remember,
                pattern_type=pattern_type,
                status="approved",
                reason="User approved command execution.",
                decision=decision,
                user_note=user_note,
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
            user_note=user_note,
        )

    async def add_to_whitelist(
        self,
        command: str,
        pattern_type: str = 'exact',
        description: str = '',
        risk_level: str = 'low',
        record_initial_use: bool = False,
        *,
        pattern: Optional[str] = None,
        proposed_pattern: Optional[str] = None,
    ) -> CommandPattern:
        """Add a command to the whitelist.

        ``pattern`` stores exactly that text with the given type (a pattern the user typed, or one already chosen for an approval card). ``proposed_pattern`` is the agent's suggestion for a remembered approval, validated against ``command`` before it is used.
        """
        return await self.whitelist_manager.add_to_whitelist(
            command,
            pattern_type,
            description,
            risk_level,
            record_initial_use=record_initial_use,
            pattern=pattern,
            proposed_pattern=proposed_pattern,
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
        user_note: str | None = None,
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
                user_note=user_note,
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
                user_note=user_note,
            )
