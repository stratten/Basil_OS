"""
Risk assessment for shell commands.

Evaluates command risk levels and checks for dangerous patterns.
"""

import logging
import re
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
        'df', 'du', 'ps', 'top', 'env', 'printenv', 'history',
        # Text and path helpers. `sort -o` and `uniq <in> <out>` write a file, and _segment_has_unsafe_arguments refuses those forms.
        'sort', 'uniq', 'cut', 'tr', 'diff', 'jq', 'shasum', 'basename', 'dirname', 'realpath', 'readlink',
        # Facts about the machine and its processes.
        'uname', 'sw_vers', 'hostname', 'id', 'uptime', 'lsof', 'pgrep',
        # Shell builtins that change nothing outside the shell, and the loop and conditional words that only frame other commands.
        'cd', 'test', 'sleep', 'printf', 'for', 'done', 'fi',
    }

    # Read-only only in one form, which _segment_has_unsafe_arguments enforces. They stay out of READ_ONLY_COMMANDS so assess_risk_level does not rate `sed -i` or `defaults write` as low risk.
    CONDITIONALLY_READ_ONLY_COMMANDS = {'sed', 'git', 'defaults'}
    READ_ONLY_SUBCOMMANDS = {
        'git': {'status', 'log', 'diff'},
        'defaults': {'read', 'read-type', 'domains', 'find'},
    }
    # `sed -n` with one literal print script (`5p`, `1,20p`, `$p`, `/text/p`). Any other script can write a file (`w`) or run a command (`e`).
    SED_PRINT_SCRIPT = re.compile(r'^((\d+|\$)(,(\d+|\$))?|/[A-Za-z0-9 _.:-]*/)p$')
    # `uniq <input> <output>` writes the second file and `hostname <name>` sets the name, so these take no more positional arguments than this.
    MAX_POSITIONAL_ARGUMENTS = {'uniq': 1, 'hostname': 0}

    SHELL_WRAPPERS = {'bash', 'sh', 'zsh', 'ksh', 'fish'}
    SHELL_CONTROL_OPERATORS = {'|', '||', '|&', '&&', '&', ';', ';;', '(', ')'}
    # Words that open a segment without being its command: in `if test -f x; then ls; fi` the commands are `test` and `ls`.
    COMMAND_PREFIX_WORDS = {'if', 'elif', 'while', 'until', 'then', 'else', 'do', '!'}
    PUNCTUATION_CHARACTERS = frozenset('();<>|&')
    REDIRECTION_OPERATORS = {'>', '>>', '2>', '2>>', '&>', '&>>', '>|'}
    # Output redirections that write no file: to /dev/null (checked against the next token), or onto another descriptor.
    NULL_REDIRECTION_TARGET = '/dev/null'
    UNSPLIT_HARMLESS_REDIRECTIONS = {'2>&1', '1>&2', '>&1', '>&2', '>/dev/null', '2>/dev/null', '&>/dev/null', '>>/dev/null', '2>>/dev/null'}
    FIND_MUTATING_PREDICATES = {'-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprint0', '-fprintf', '-fls'}
    # Stand-ins for an escaped parenthesis while a command is tokenized: letters only, so the tokenizer keeps each one inside its word, and never a command word or an operator.
    ESCAPED_OPEN_PARENTHESIS = 'basilescapedopenparenthesis'
    ESCAPED_CLOSE_PARENTHESIS = 'basilescapedcloseparenthesis'
    # Flags that turn an otherwise read-only command into one that changes state. `env` has no entry here: it is read-only only when run on its own (see _segment_has_unsafe_arguments).
    MUTATING_ARGUMENTS = {
        'history': {'-c', '-d', '-a', '-n', '-r', '-w', '-s', '-p'},
        'date': {'-s', '--set'},
        'file': {'-C', '--compile'},
        'sort': {'-o', '--output', '--compress-program'},
        'hostname': {'-F', '--file'},
        'git': {'--output', '--ext-diff'},
    }

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
        command_parts = self._split_command(self._unwrap_shell_command(command))
        if not command_parts:
            return False, None

        # Every command in a chain counts, not only the first: `ls x; rm -rf y` is blocked for the `rm`.
        for base_command in self._extract_command_names(command_parts):
            if base_command in self.BLOCKED_COMMANDS:
                logger.warning(f"🚫 [BLOCKED_CHECK] Command '{base_command}' is in the inherent blacklist")
                return True, f"Command '{base_command}' is blocked for security reasons and cannot be executed"

        return False, None

    def is_high_risk(self, command: str) -> bool:
        """Whether the command, or the command inside a shell wrapper, is rated high or critical risk."""
        inner = self._unwrap_shell_command(command)
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

        if self._has_unsafe_arguments(command_parts):
            return False

        command_names = self._extract_command_names(command_parts)
        if not command_names:
            return False

        return all(
            command_name in self.READ_ONLY_COMMANDS or command_name in self.CONDITIONALLY_READ_ONLY_COMMANDS
            for command_name in command_names
        )

    def _has_unsafe_arguments(self, command_parts: list) -> bool:
        """Whether any piped or chained command is read-only by name but unsafe by its arguments."""
        segment: list = []
        for token in [*command_parts, ';']:
            if self._is_separator(token):
                if segment and self._segment_has_unsafe_arguments(segment):
                    return True
                segment = []
            else:
                segment.append(token)
        return False

    def _segment_has_unsafe_arguments(self, segment: list) -> bool:
        segment = self._without_prefix_words(segment)
        if not segment:
            return False
        name = segment[0].split('/')[-1]
        arguments = self._without_redirections(segment[1:])
        if name == 'find' and any(argument in self.FIND_MUTATING_PREDICATES for argument in arguments):
            # A `find` behind `cd x &&`, a pipe, or a loop is still a `find`: `-delete` and `-exec` act the same wherever it appears.
            return True
        if name == 'env':
            # `env` alone prints the environment. Anything after it is a command it runs, an assignment that feeds one, or a flag that changes how it runs.
            return bool(arguments)
        allowed_subcommands = self.READ_ONLY_SUBCOMMANDS.get(name)
        if allowed_subcommands is not None and (not arguments or arguments[0] not in allowed_subcommands):
            # The subcommand has to come first: `git -c core.pager=<command> log` would run that command.
            return True
        if name == 'sed' and not self._is_print_only_sed(arguments):
            return True
        maximum = self.MAX_POSITIONAL_ARGUMENTS.get(name)
        if maximum is not None and sum(1 for argument in arguments if not argument.startswith('-')) > maximum:
            return True
        forbidden = self.MUTATING_ARGUMENTS.get(name)
        if not forbidden:
            return False
        short_letters = {flag[1] for flag in forbidden if len(flag) == 2}
        long_flags = {flag for flag in forbidden if flag.startswith('--')}
        for argument in arguments:
            if argument in forbidden:
                return True
            if argument.startswith('--'):
                # GNU tools accept any unambiguous prefix, so `--out` means `--output`, and `--output=file` carries its value.
                flag_name = argument.split('=', 1)[0]
                if len(flag_name) > 2 and any(flag.startswith(flag_name) for flag in long_flags):
                    return True
            # Short flags can be combined, so `-us` carries `-s`.
            elif argument.startswith('-') and short_letters.intersection(argument[1:]):
                return True
        return False

    def _is_print_only_sed(self, arguments: list) -> bool:
        """Whether the arguments are `-n`, one literal print script, and then only file names."""
        if len(arguments) < 2 or arguments[0] != '-n' or not self.SED_PRINT_SCRIPT.match(arguments[1]):
            return False
        return not any(argument.startswith('-') and argument != '-' for argument in arguments[2:])

    def _without_prefix_words(self, segment: list) -> list:
        """Drop the leading `if`, `then`, `do`, and similar words so the command is first."""
        index = 0
        while index < len(segment) and segment[index] in self.COMMAND_PREFIX_WORDS:
            index += 1
        return segment[index:]

    def _without_redirections(self, arguments: list) -> list:
        """Remove redirections, with their targets and any descriptor number in front, so `2>&1` does not count as an argument."""
        kept: list = []
        index = 0
        while index < len(arguments):
            token = arguments[index]
            following_is_redirection = index + 1 < len(arguments) and self._is_redirection(arguments[index + 1])
            if self._is_redirection(token):
                index += 2
            elif token.isdigit() and following_is_redirection:
                index += 1
            else:
                kept.append(token)
                index += 1
        return kept

    def _is_redirection(self, token: str) -> bool:
        if not token or not set(token) <= self.PUNCTUATION_CHARACTERS:
            return False
        return '<' in token or '>' in token

    def _is_separator(self, token: str) -> bool:
        """Whether the token ends one command and starts the next.

        Adjacent operators reach us as one token (`;(`, `|(`, `<(`), and the command after one is still a command, so a token made only of operator characters counts when it holds any that can start one.
        """
        if token in self.SHELL_CONTROL_OPERATORS:
            return True
        return bool(token) and set(token) <= self.PUNCTUATION_CHARACTERS and '>' not in token and any(character in token for character in '();|&')

    def _split_command(self, command: str) -> list:
        """Split a shell command while preserving quoted inner commands.

        Operators are split off even when written without spaces (``ls x;rm y``, ``a&&b``, ``echo hi>f``), and line breaks and backticks count as separators, so a chained command cannot hide behind the first one.
        """
        prepared = self._protect_escaped_parentheses(command).replace('\r', '\n').replace('\n', ' ; ').replace('`', ' ( ')
        try:
            lexer = shlex.shlex(prepared, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            return command.split()
        return [token.replace(self.ESCAPED_OPEN_PARENTHESIS, '\\(').replace(self.ESCAPED_CLOSE_PARENTHESIS, '\\)') for token in tokens]

    def _protect_escaped_parentheses(self, command: str) -> str:
        """Turn an unquoted ``\\(`` or ``\\)`` into a plain word, because the shell reads it as a literal parenthesis and not as an operator.

        ``find . \\( -name a -o -name b \\) -print`` groups its tests with them. Left alone, the tokenizer would read each one as a subshell boundary and take ``-name`` for the start of a new command.
        """
        protected: list = []
        quote = ''
        index = 0
        while index < len(command):
            character = command[index]
            following = command[index + 1] if index + 1 < len(command) else ''
            if quote == "'":
                if character == "'":
                    quote = ''
            elif character == '\\' and following:
                if not quote and following in '()':
                    protected.append(self.ESCAPED_OPEN_PARENTHESIS if following == '(' else self.ESCAPED_CLOSE_PARENTHESIS)
                else:
                    protected.append(character + following)
                index += 2
                continue
            elif quote == '"':
                if character == '"':
                    quote = ''
            elif character in ('"', "'"):
                quote = character
            protected.append(character)
            index += 1
        return ''.join(protected)

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
        for index, token in enumerate(command_parts):
            if self._is_output_redirection(token):
                following = command_parts[index + 1] if index + 1 < len(command_parts) else ''
                if not self._is_harmless_redirection(token, following):
                    return True

        if command_parts and command_parts[0].split('/')[-1] == 'find':
            return any(token in self.FIND_MUTATING_PREDICATES for token in command_parts)

        return False

    def _is_output_redirection(self, token: str) -> bool:
        if token in self.REDIRECTION_OPERATORS or token.startswith(('>', '2>', '&>')):
            return True
        return '>' in token and set(token) <= self.PUNCTUATION_CHARACTERS

    def _is_harmless_redirection(self, token: str, following: str) -> bool:
        """Whether the output redirection writes no file: it goes to /dev/null, or onto another descriptor."""
        if token in self.UNSPLIT_HARMLESS_REDIRECTIONS:
            return True
        if token in self.REDIRECTION_OPERATORS and following == self.NULL_REDIRECTION_TARGET:
            return True
        return token == '>&' and (following.isdigit() or following == '-')

    def _extract_command_names(self, command_parts: list) -> list:
        """Return commands at the start of each piped/chained segment."""
        command_names = []
        expect_command = True

        for token in command_parts:
            if self._is_separator(token):
                expect_command = True
                continue

            if expect_command and token in self.COMMAND_PREFIX_WORDS:
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
