"""
Command pattern generalization.

Extracts reusable patterns from specific commands by removing file-specific arguments.
"""

import logging
import shlex

logger = logging.getLogger(__name__)


class CommandGeneralizer:
    """
    Generalizes commands to create reusable whitelist patterns.

    Removes file-specific arguments while preserving command structure and
    security-relevant flags. Handles shell wrappers intelligently.
    """

    SHELL_WRAPPERS = {'bash', 'sh', 'zsh', 'fish', 'dash', 'ksh'}

    COMMANDS_IGNORE_FLAGS = {
        'ls', 'dir',
        'cat', 'head', 'tail', 'less', 'more',
        'grep', 'egrep', 'fgrep',
        'find',
        'ps', 'top',
        'df', 'du',
        'wc',
        'echo', 'printf',
        'date',
        'env', 'printenv',
    }

    SUBCOMMANDS = {
        'docker': ['run', 'build', 'compose', 'exec', 'ps'],
        'git': ['clone', 'commit', 'push', 'pull', 'checkout', 'branch'],
        'npm': ['install', 'run', 'start', 'test', 'build'],
        'yarn': ['install', 'run', 'start', 'test'],
        'poetry': ['run', 'install', 'add', 'remove'],
        'cargo': ['run', 'build', 'test', 'check'],
        'kubectl': ['apply', 'get', 'describe', 'logs'],
    }

    def generalize_command(self, command: str) -> str:
        """Generalize a command using heuristics to separate command from arguments."""
        try:
            tokens = shlex.split(command)
            if not tokens:
                return command

            base_cmd = tokens[0]

            if base_cmd in self.SHELL_WRAPPERS and len(tokens) >= 2:
                return self._generalize_shell_wrapper(command, tokens, base_cmd)

            return self._generalize_regular_command(command, tokens, base_cmd)

        except Exception as e:
            logger.warning(f"Failed to generalize command, using base only: {e}")
            return command.split()[0] if command.split() else command

    def _generalize_shell_wrapper(self, command: str, tokens: list, base_cmd: str) -> str:
        """Generalize a shell wrapper command without creating naked-wrapper whitelists."""
        has_c_flag = False
        wrapper_parts = [base_cmd]
        inner_command_start = None

        for i in range(1, len(tokens)):
            token = tokens[i]
            if token.startswith('-') and 'c' in token:
                has_c_flag = True
                wrapper_parts.append(token)
                if i + 1 < len(tokens):
                    inner_command_start = i + 1
                break
            if token.startswith('-'):
                wrapper_parts.append(token)
            else:
                break

        if has_c_flag and inner_command_start is not None:
            inner_command = tokens[inner_command_start]
            logger.info(f"🔍 Detected shell wrapper: {' '.join(wrapper_parts)} with inner command: {inner_command[:80]}")

            try:
                inner_generalized = self.generalize_command(inner_command)
                result = ' '.join(wrapper_parts) + ' ' + inner_generalized
                logger.info(f"✅ Shell wrapper generalization: '{command[:80]}...' -> '{result}'")
                return result
            except Exception as e:
                logger.warning(f"⚠️ Failed to generalize inner command recursively: {e}")

                try:
                    inner_tokens = inner_command.split()
                    if inner_tokens:
                        base_inner_cmd = inner_tokens[0]
                        result = ' '.join(wrapper_parts) + ' ' + base_inner_cmd
                        logger.warning(f"⚠️ Fallback extraction (base command only): '{command[:80]}...' -> '{result}'")
                        return result
                    logger.error("🚨 Empty inner command in shell wrapper")
                    return ' '.join(wrapper_parts) + ' <unknown>'
                except Exception as fallback_error:
                    logger.error(f"🚨 Critical: Failed to extract any command from wrapper: {fallback_error}")
                    return ' '.join(wrapper_parts) + ' <parse_error>'

        return self._generalize_regular_command(command, tokens, base_cmd)

    def _generalize_regular_command(self, command: str, tokens: list, base_cmd: str) -> str:
        """Generalize a regular command by keeping security-relevant command shape."""
        result = [base_cmd]

        if base_cmd in self.COMMANDS_IGNORE_FLAGS:
            logger.info(f"Read-only command with display flags only: '{command[:80]}...' -> '{base_cmd}'")
            return base_cmd

        i = 1
        prev = base_cmd

        while i < min(len(tokens), 4):
            token = tokens[i]

            if self._is_argument(token, prev):
                break

            if token.startswith('-'):
                result.append(token)
                i += 1
                prev = token
                continue

            if len(result) <= 2 and base_cmd in self.SUBCOMMANDS:
                if token in self.SUBCOMMANDS[base_cmd]:
                    result.append(token)
                    i += 1
                    prev = token
                    continue

            break

        generalized = ' '.join(result)
        logger.info(f"Command generalization: '{command[:80]}...' -> '{generalized}'")
        return generalized

    @staticmethod
    def _is_argument(token: str, prev_token: str = None) -> bool:
        """Detect if a token is likely a file-specific argument."""
        if '/' in token or '\\' in token or token.startswith('~'):
            return True
        if '.' in token and len(token) > 2 and not token.startswith('.'):
            return True
        if token in ['>', '>>', '<', '|', '2>&1', '&>', '2>', '1>', '&>>']:
            return True
        if '=' in token and not token.startswith('-'):
            return True
        if token.startswith(('http://', 'https://', 'ftp://', 'ssh://', 'git://')):
            return True
        if prev_token in ['>', '>>', '<', '|', '2>&1', '&>', '2>', '1>', '&>>']:
            return True
        return False
