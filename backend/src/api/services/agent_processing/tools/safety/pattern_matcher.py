"""
Pattern matching and security validation for command whitelist.
"""

import logging
import re
import shlex
from typing import List, Optional

from api.core.models.preferences import CommandPattern

from .command_words import effective_command, join_words, pattern_words
from .whitelist_eligibility import assess_whitelist_eligibility

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
        """Return the remembered pattern that covers ``command``, or None when the user has to be asked.

        ``command`` is the command exactly as it will run, never a shortened copy of it. A prefix or regex pattern only covers a plain command, or a shell wrapper around one plain command; anything that chains, pipes, redirects, or substitutes is only ever covered by an exact pattern for that same command.
        """
        for pattern in whitelist:
            if self.is_naked_wrapper(pattern.pattern):
                logger.warning(f"⚠️ Skipping naked wrapper pattern in whitelist: '{pattern.pattern}' (pattern_id: {pattern.id})")
                continue

            if self.is_never_rememberable(pattern.pattern):
                logger.warning(f"⚠️ Skipping whitelist pattern that can never be remembered: '{pattern.pattern}' (pattern_id: {pattern.id})")
                continue

            if self.matches_pattern(command, pattern):
                logger.debug(f"✅ Full command matched: '{command[:80]}' → pattern '{pattern.pattern}'")
                return pattern

        return None

    def covers_words(self, words: List[Optional[str]], whitelist: List[CommandPattern]) -> bool:
        """Whether a remembered prefix pattern covers one simple command, given as its name and arguments with None for any word the shell computes.

        This is how a command inside a script is judged on its own. Only prefix patterns count, because an exact or regex pattern describes a whole command string. Patterns the eligibility rule forbids are skipped quietly here, since ``check_whitelist`` already reports them. A computed word never equals a pattern word, so a pattern cannot match through one.
        """
        for pattern in whitelist:
            if pattern.pattern_type != 'prefix':
                continue
            if self.is_naked_wrapper(pattern.pattern) or self.is_never_rememberable(pattern.pattern):
                continue
            required = pattern_words(pattern.pattern)
            if required and words[:len(required)] == required:
                return True
        return False

    def matches_pattern(self, command: str, pattern: CommandPattern) -> bool:
        """Check if a command matches a specific pattern.

        A prefix pattern matches whole words: ``gh gist view`` covers ``gh gist view abc`` but not ``gh gist viewer`` and ``gh`` does not cover ``ghostscript``.
        """
        try:
            if pattern.pattern_type == 'exact':
                return command == pattern.pattern

            effective = effective_command(command)
            if effective.words is None:
                return False

            if pattern.pattern_type == 'prefix':
                required = pattern_words(pattern.pattern)
                return bool(required) and effective.words[:len(required)] == required

            if pattern.pattern_type == 'regex':
                return bool(re.match(pattern.pattern, join_words(effective.words)))

            logger.warning(f"Unknown pattern type: {pattern.pattern_type}")
            return False

        except Exception as e:
            logger.error(f"Error matching pattern '{pattern.pattern}': {e}")
            return False

    @staticmethod
    def is_never_rememberable(pattern: str) -> bool:
        """Check whether the shared eligibility rule forbids a stored pattern (interpreters, indirection, bare shells).

        Specificity is not enforced here: a stored single-word pattern keeps working and is only flagged as broad in settings.
        """
        return not assess_whitelist_eligibility(pattern, pattern, enforce_specificity=False).eligible

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
