"""
Risk assessment for shell commands.

Evaluates command risk levels and checks for dangerous patterns. Reading a command (is it read-only, does it run a blocked program, does it match a dangerous pattern) is done by the shell parser in the `shell_syntax` package, so a command is judged by what a shell would run and not by how its words happen to be split. This module keeps the interface the approval flow calls.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from api.core.models.preferences import ToolExecutionSettings

from . import shell_syntax
from .shell_syntax import command_policy as policy

logger = logging.getLogger(__name__)


class RiskAssessor:
    """
    Evaluates the security risk level of shell commands.

    Classifies commands into risk categories and identifies dangerous patterns.
    Includes an inherent blacklist of commands that are NEVER allowed.
    """

    BLOCKED_COMMANDS = policy.BLOCKED_COMMANDS
    READ_ONLY_COMMANDS = policy.READ_ONLY_COMMANDS
    MODIFYING_COMMANDS = policy.MODIFYING_COMMANDS
    HIGH_RISK_COMMANDS = policy.HIGH_RISK_COMMANDS

    def assess_risk_level(self, command: str) -> str:
        """Assess the risk level of a command."""
        command_parts = command.split()
        if not command_parts:
            return 'low'

        base_command = command_parts[0].split('/')[-1]

        if base_command in self.BLOCKED_COMMANDS:
            return 'critical'

        if base_command in self.HIGH_RISK_COMMANDS:
            return 'high'

        if base_command in self.MODIFYING_COMMANDS:
            if any(flag in command for flag in ['-rf', '-R -f', '--force', '--recursive']):
                return 'high'
            return 'medium'

        if base_command in self.READ_ONLY_COMMANDS:
            return 'low'

        if any(op in command for op in ['|', '>', '>>', '&&', '||', ';']):
            return 'medium'

        return 'medium'

    def check_blocked_commands(self, command: str) -> Tuple[bool, Optional[str]]:
        """Check if command uses any inherently blocked commands, wherever in the command it appears."""
        # Every command counts, not only the first: `ls x; rm -rf y`, `echo $(rm y)`, `if rm y; then ls; fi`, and `bash -c 'rm y'` are all blocked for the `rm`.
        blocked_name = shell_syntax.find_blocked_command(command)
        if blocked_name is None:
            return False, None

        logger.warning(f"🚫 [BLOCKED_CHECK] Command '{blocked_name}' is in the inherent blacklist")
        return True, f"Command '{blocked_name}' is blocked for security reasons and cannot be executed"

    def is_high_risk(self, command: str) -> bool:
        """Whether the command, or the command inside a shell wrapper, is rated high or critical risk."""
        inner = shell_syntax.inner_shell_script(command)
        return any(self.assess_risk_level(text) in ('high', 'critical') for text in (command, inner))

    def check_dangerous_patterns(
        self,
        command: str,
        settings: ToolExecutionSettings
    ) -> Tuple[bool, Optional[str]]:
        """Check if command matches any dangerous patterns."""
        is_blocked, block_reason = self.check_blocked_commands(command)
        if is_blocked:
            return True, block_reason

        for pattern in settings.dangerous_patterns:
            if self._dangerous_pattern_matches(command, pattern):
                return True, f"Command contains dangerous pattern: {pattern}"

        return False, None

    def _dangerous_pattern_matches(self, command: str, pattern: str) -> bool:
        """Match dangerous patterns against the commands a string runs, not filename substrings."""
        return shell_syntax.command_matches_pattern(command, pattern)

    def is_read_only_command(self, command: str) -> bool:
        """Check if command is read-only: every command in it is on the read-only list with arguments that cannot change anything, and nothing in it writes."""
        verdict = shell_syntax.classify_read_only(command)
        if not verdict.is_read_only:
            logger.info(f"🔍 [READ_ONLY_CHECK] Not read-only: {verdict.reason}")
        return verdict.is_read_only

    def get_risk_metadata(self, command: str) -> Dict[str, Any]:
        """Get detailed risk metadata for a command."""
        if not command.strip():
            return {}

        metadata: Dict[str, Any] = {}

        # The blocked program can be anywhere in the string (`ls; rm x`, `bash -lc 'rm x'`, `env rm x`), so the card warns about the same program the block itself found, not only the first word.
        blocked_name = shell_syntax.find_blocked_command(command)
        if blocked_name is not None:
            metadata['is_blocked'] = True
            metadata['warning_message'] = (
                f"The '{blocked_name}' command is blocked for security reasons and cannot be executed. "
                f"This is an inherent safety restriction."
            )
            logger.warning(f"🚫 [RISK_METADATA] Command '{blocked_name}' is blocked")

        return metadata
