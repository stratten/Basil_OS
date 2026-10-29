"""
Risk assessment for shell commands.

Evaluates command risk levels and checks for dangerous patterns.
"""

import logging
import shlex
from typing import Dict, Optional, Tuple, Any

from api.core.models.preferences import ToolExecutionSettings

logger = logging.getLogger(__name__)


class RiskAssessor:
    """
    Evaluates the security risk level of shell commands.

    Classifies commands into risk categories and identifies dangerous patterns.
    Includes an inherent blacklist of commands that are NEVER allowed.
    """

    BLOCKED_COMMANDS = {
        'rm', 'shred', 'wipe', 'srm',
        'dd', 'mkfs', 'fdisk', 'parted', 'diskutil',
        'shutdown', 'reboot', 'halt', 'poweroff', 'init',
        'sudo', 'su', 'doas',
        'umount', 'mount',
    }

    READ_ONLY_COMMANDS = {
        'ls', 'dir', 'cat', 'head', 'tail', 'grep', 'find', 'wc',
        'pwd', 'echo', 'date', 'whoami', 'which', 'file', 'stat',
        'df', 'du', 'ps', 'top', 'env', 'printenv', 'history'
    }

    SHELL_WRAPPERS = {'bash', 'sh', 'zsh', 'ksh', 'fish'}
    SHELL_CONTROL_OPERATORS = {'|', '||', '&&', ';'}
    REDIRECTION_OPERATORS = {'>', '>>', '2>', '2>>', '&>', '&>>', '>|'}
    FIND_MUTATING_PREDICATES = {'-delete', '-exec', '-execdir', '-ok', '-okdir'}

    MODIFYING_COMMANDS = {
        'mv', 'cp', 'mkdir', 'rmdir', 'touch', 'chmod', 'chown',
        'ln', 'tar', 'zip', 'unzip', 'git', 'curl', 'wget'
    }

    HIGH_RISK_COMMANDS = {
        'systemctl', 'service', 'kill', 'killall', 'pkill'
    }

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
        """Check if command uses any inherently blocked commands."""
        try:
            command_parts = shlex.split(command)
        except ValueError:
            command_parts = command.split()

        if not command_parts:
            return False, None

        base_command = command_parts[0].split('/')[-1]

        if base_command in ('bash', 'sh', 'zsh', 'ksh', 'fish') and len(command_parts) > 2:
            for i in range(1, len(command_parts)):
                token = command_parts[i]
                if token.startswith('-') and 'c' in token:
                    if i + 1 < len(command_parts):
                        inner_command = command_parts[i + 1]
                        try:
                            inner_parts = shlex.split(inner_command)
                        except ValueError:
                            inner_parts = inner_command.split()
                        if inner_parts:
                            base_command = inner_parts[0].split('/')[-1]
                            logger.info(f"🔍 [BLOCKED_CHECK] Detected shell wrapper, extracted base command: {base_command}")
                    break

        if base_command in self.BLOCKED_COMMANDS:
            logger.warning(f"🚫 [BLOCKED_CHECK] Command '{base_command}' is in the inherent blacklist")
            return True, f"Command '{base_command}' is blocked for security reasons and cannot be executed"

        return False, None

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
        """Match dangerous patterns against command syntax, not filename substrings."""
        normalized_pattern = (pattern or "").strip().lower()
        if not normalized_pattern:
            return False

        # Shell metacharacter patterns are intentionally literal because they are
        # not token-shaped commands and should still be blocked anywhere.
        if normalized_pattern in {":(){ :|:& };:"}:
            return normalized_pattern in command.lower()

        command_to_check = self._unwrap_shell_command(command)
        command_parts = self._split_command(command_to_check)
        if not command_parts:
            return False

        # Multi-token patterns such as "sudo rm", "rm -rf /", and "dd if="
        # are checked over token windows so ordinary filenames do not match.
        pattern_parts = self._split_command(normalized_pattern)
        lowered_parts = [str(part).lower() for part in command_parts]

        if len(pattern_parts) > 1:
            lowered_pattern = [str(part).lower() for part in pattern_parts]
            window_size = len(lowered_pattern)
            for index in range(0, len(lowered_parts) - window_size + 1):
                if lowered_parts[index:index + window_size] == lowered_pattern:
                    return True
            if normalized_pattern == "dd if=":
                return bool(lowered_parts and lowered_parts[0] == "dd" and any(part.startswith("if=") for part in lowered_parts[1:]))
            return False

        pattern_token = normalized_pattern
        command_names = self._extract_command_names(command_parts)
        if pattern_token in {name.lower() for name in command_names}:
            return True

        # Preserve blocking for command flags/forms that are not standalone
        # command names, without scanning quoted paths as raw text.
        if pattern_token.endswith("="):
            return any(part.lower().startswith(pattern_token) for part in command_parts)

        return False

    def is_read_only_command(self, command: str) -> bool:
        """Check if command is read-only."""
        command_to_check = self._unwrap_shell_command(command)
        command_parts = self._split_command(command_to_check)
        if not command_parts:
            return False

        if self._has_mutating_shell_syntax(command_parts):
            return False

        command_names = self._extract_command_names(command_parts)
        if not command_names:
            return False

        return all(command_name in self.READ_ONLY_COMMANDS for command_name in command_names)

    def _split_command(self, command: str) -> list:
        """Split a shell command while preserving quoted inner commands."""
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()

    def _unwrap_shell_command(self, command: str) -> str:
        """Extract the inner command from shell wrappers like bash -lc."""
        command_parts = self._split_command(command)
        if not command_parts:
            return command

        base_command = command_parts[0].split('/')[-1]
        if base_command not in self.SHELL_WRAPPERS or len(command_parts) <= 2:
            return command

        for index, token in enumerate(command_parts[1:], start=1):
            if token.startswith('-') and 'c' in token and index + 1 < len(command_parts):
                inner_command = command_parts[index + 1]
                logger.info(f"🔍 [READ_ONLY_CHECK] Detected shell wrapper, checking inner command: {inner_command[:80]}")
                return inner_command

        return command

    def _has_mutating_shell_syntax(self, command_parts: list) -> bool:
        """Reject shell syntax that can write or invoke mutating find actions."""
        for token in command_parts:
            if token in self.REDIRECTION_OPERATORS or token.startswith(('>', '2>', '&>')):
                return True

        if command_parts and command_parts[0].split('/')[-1] == 'find':
            return any(token in self.FIND_MUTATING_PREDICATES for token in command_parts)

        return False

    def _extract_command_names(self, command_parts: list) -> list:
        """Return commands at the start of each piped/chained segment."""
        command_names = []
        expect_command = True

        for token in command_parts:
            if token in self.SHELL_CONTROL_OPERATORS:
                expect_command = True
                continue

            if expect_command:
                command_names.append(token.split('/')[-1])
                expect_command = False

        return command_names

    def get_risk_metadata(self, command: str) -> Dict[str, Any]:
        """Get detailed risk metadata for a command."""
        try:
            command_parts = shlex.split(command)
        except ValueError:
            command_parts = command.split()

        if not command_parts:
            return {}

        base_command = command_parts[0].split('/')[-1]

        if base_command in ('bash', 'sh', 'zsh', 'ksh', 'fish') and len(command_parts) > 2:
            for i in range(1, len(command_parts)):
                token = command_parts[i]
                if token.startswith('-') and 'c' in token:
                    if i + 1 < len(command_parts):
                        inner_command = command_parts[i + 1]
                        try:
                            inner_parts = shlex.split(inner_command)
                        except ValueError:
                            inner_parts = inner_command.split()
                        if inner_parts:
                            base_command = inner_parts[0].split('/')[-1]
                            logger.info(f"🔍 [RISK_METADATA] Detected shell wrapper, extracted base command: {base_command}")
                    break

        metadata = {}

        if base_command in self.BLOCKED_COMMANDS:
            metadata['is_blocked'] = True
            metadata['warning_message'] = (
                f"The '{base_command}' command is blocked for security reasons and cannot be executed. "
                f"This is an inherent safety restriction."
            )
            logger.warning(f"🚫 [RISK_METADATA] Command '{base_command}' is blocked")

        return metadata
