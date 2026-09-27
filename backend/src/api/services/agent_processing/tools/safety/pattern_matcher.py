"""
Pattern matching and security validation for command whitelist.
"""

import logging
import re
import shlex
from typing import List, Optional

from api.core.models.preferences import CommandPattern

logger = logging.getLogger(__name__)


class PatternMatcher:
    """
    Handles pattern matching for whitelist entries and security validation.

    Supports multiple pattern types (exact, prefix, regex) and includes
    security checks to prevent dangerous naked wrapper patterns.
    """

    SHELL_WRAPPERS = {'bash', 'sh', 'zsh', 'fish', 'dash', 'ksh'}

    def check_whitelist(
        self,
        command: str,
        whitelist: List[CommandPattern]
    ) -> Optional[CommandPattern]:
        """Check if command matches any whitelisted pattern."""
        for pattern in whitelist:
            if self.is_naked_wrapper(pattern.pattern):
                logger.warning(f"⚠️ Skipping naked wrapper pattern in whitelist: '{pattern.pattern}' (pattern_id: {pattern.id})")
                continue

            if self.matches_pattern(command, pattern):
                logger.debug(f"✅ Full command matched: '{command[:80]}' → pattern '{pattern.pattern}'")
                return pattern

        inner_match = self._check_inner_command_whitelist(command, whitelist)
        if inner_match:
            return inner_match

        return None

    def _check_inner_command_whitelist(
        self,
        command: str,
        whitelist: List[CommandPattern]
    ) -> Optional[CommandPattern]:
        """Check if the inner command of a shell wrapper is whitelisted."""
        try:
            tokens = shlex.split(command)
            if tokens:
                base_cmd = tokens[0]

                if base_cmd in self.SHELL_WRAPPERS and len(tokens) >= 2:
                    for i in range(1, len(tokens)):
                        token = tokens[i]
                        if token.startswith('-') and 'c' in token:
                            if i + 1 < len(tokens):
                                inner_command = tokens[i + 1]
                                logger.debug(f"🔍 Checking inner command for whitelist: '{inner_command[:80]}'")

                                for pattern in whitelist:
                                    if self.is_naked_wrapper(pattern.pattern):
                                        continue

                                    if self.matches_pattern(inner_command, pattern):
                                        logger.info(f"✅ Inner command matched whitelist: '{inner_command[:80]}' → pattern '{pattern.pattern}'")
                                        return pattern
                            break
        except Exception as e:
            logger.debug(f"Failed to check inner command against whitelist: {e}")

        return None

    def matches_pattern(self, command: str, pattern: CommandPattern) -> bool:
        """Check if a command matches a specific pattern."""
        try:
            if pattern.pattern_type == 'exact':
                return command == pattern.pattern

            if pattern.pattern_type == 'prefix':
                return command.startswith(pattern.pattern)

            if pattern.pattern_type == 'regex':
                return bool(re.match(pattern.pattern, command))

            logger.warning(f"Unknown pattern type: {pattern.pattern_type}")
            return False

        except Exception as e:
            logger.error(f"Error matching pattern '{pattern.pattern}': {e}")
            return False

    def is_naked_wrapper(self, pattern: str) -> bool:
        """Check if a pattern is just a shell wrapper with no actual command."""
        try:
            tokens = shlex.split(pattern)
            if not tokens:
                return False

            base_cmd = tokens[0]

            if base_cmd not in self.SHELL_WRAPPERS:
                return False

            has_c_flag = False
            has_command_after_c = False

            for i in range(1, len(tokens)):
                token = tokens[i]

                if token.startswith('-') and 'c' in token:
                    has_c_flag = True
                    if i + 1 < len(tokens):
                        has_command_after_c = True
                    break
                if token.startswith('-'):
                    continue
                return False

            if has_c_flag and not has_command_after_c:
                logger.warning(f"🚨 SECURITY: Detected naked shell wrapper pattern: '{pattern}'")
                return True

            if len(tokens) == 1:
                logger.warning(f"🚨 SECURITY: Detected bare shell wrapper: '{pattern}'")
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking for naked wrapper: {e}")
            return True
