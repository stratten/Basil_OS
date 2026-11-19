"""Proof, from the parsed syntax tree, that a shell command only reads.

A command is read-only only when every node of its syntax tree is a shape this module understands and every command in it is on the read-only list with arguments that cannot change anything. The walk never guesses from word boundaries: quoting, escapes, substitutions, redirections, loops, and wrapper scripts arrive from the parser as typed nodes. Whatever the walk does not recognize refuses the whole command, which keeps the normal approval prompt.

What the walk accepts:
- Commands joined by `;`, newlines, `&&`, `||`, `&`, and pipes, in `( ... )` and `{ ...; }` groups, behind `!`, and in `if`, `while`, and `for` statements whose parts are themselves accepted.
- A command by a bare name on the read-only list, or by an absolute path in a system folder. A program named by any other path, a quoted or computed name, and a variable set for one command (`A=1 ls`) are refused.
- A plain variable assigned on its own statement (`f=$(ls | head -1)`, `count=3`): the name must be lowercase and not one a shell reads for itself, and the value must be plain text, a plain variable, or a `$(...)` whose body is itself read-only. Nothing is written, and the value cannot become an option (a computed argument of `find`, `sed`, or `git` is refused where it is used) or a command (a computed command name is refused). A variable set for one command (`A=1 ls`), `export`, and any other name are refused.
- `$(...)` only as an argument of `echo` or `printf`, with a body that is itself read-only. Backticks, `$((...))`, and any expansion other than a plain variable are refused.
- `<(...)` with a read-only body. `>(...)` is refused.
- Redirections that write nothing: to `/dev/null`, onto another descriptor (`2>&1`), and input from a file. Every other output redirection, here-document, and here-string is refused.
- `[ ... ]` tests with no substitution inside. `[[ ... ]]` is refused because its operators can evaluate text as code.
- Shell wrappers (`bash -lc '...'`) whose one script argument can be rebuilt as plain text, with that script checked in full.
- When the caller passes `remembered`, a command that is not on the read-only list but that the user has already approved and remembered as a pattern. The command is judged on its own, wherever it sits in the script, so a script made only of read-only commands and remembered commands needs no new approval. Its name and the words the pattern requires must be plain text; the rest of its arguments get the same checks as any other argument (a substitution or an expansion other than a plain variable is refused), and its redirections and surroundings are checked like every other command's.

For `find`, `sed`, `git`, `defaults`, `env`, `date`, `file`, `history`, `sort`, `hostname`, `uniq`, and `command`, whose safety depends on the value of an argument, every argument must be plain text the parser can read (see command_policy.ARGUMENT_POLICY_COMMANDS), because a value the shell computes could be an option that changes what the command does.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Tuple

from tree_sitter import Node

from ..applescript_read_only_classifier import ReadOnlyVerdict
from ..command_words import SHELL_WRAPPERS
from . import command_policy as policy
from .commands import find_wrapper_script, literal_command_name
from .parsing import ParsedShell, iter_nodes, parse_shell
from .words import has_unsafe_unquoted_text, literal_text, script_text, variable_name_of

logger = logging.getLogger(__name__)

MAX_COMMAND_CHARACTERS = 20_000
MAX_SYNTAX_NODES = 5_000

# The one variable whose value may be folded into the script a wrapper is given (`bash -lc "grep '$HOME' x"`). It is set by the system and no read-only command can change it.
_TRUSTED_SCRIPT_VARIABLES = frozenset({'HOME'})
# The one computed argument a policy-bearing command may take: a path under the home folder, such as `find "$HOME/Downloads" -name x`. It starts with `$HOME`, so it can never itself be an option.
_HOME_PATH_ARGUMENT = re.compile(r'^"?\$\{?HOME\}?(?:/[A-Za-z0-9_./@+ -]*)?"?$')

# The names a script may assign for its own use: lowercase, so never one of the uppercase variables the shell and programs read (`PATH`, `HOME`, `IFS`, `BASH_ENV`, `LD_PRELOAD`, `PAGER`, `GIT_*`).
_SCRATCH_VARIABLE_NAME = re.compile(r'^[a-z][a-z0-9_]*$')
# The lowercase names some shells read for themselves, which are therefore not scratch variables: zsh ties `path` to `PATH`, `fpath` and `module_path` to where it loads code, `prompt` and `psvar` to what it runs when it draws a prompt, `argv` to the arguments, and bash and zsh read `histchars` and `auto_resume`. A name ending in `_proxy` is the lowercase form of a variable programs use to pick where to connect.
_SHELL_SPECIAL_LOWERCASE_VARIABLES = frozenset({
    'aliases', 'argv', 'auto_resume', 'cdpath', 'commands', 'fignore', 'fpath', 'functions', 'histchars', 'histfile',
    'mail', 'mailpath', 'manpath', 'module_path', 'options', 'path', 'prompt', 'psvar', 'watch',
})

# Nodes whose named children are all statements the walk checks in turn.
_STATEMENT_CONTAINERS = frozenset({
    'program', 'list', 'pipeline', 'subshell', 'compound_statement', 'do_group',
    'if_statement', 'elif_clause', 'else_clause', 'while_statement', 'negated_command',
})
_REDIRECT_TYPES = frozenset({'file_redirect', 'heredoc_redirect', 'herestring_redirect'})
_OUTPUT_OPERATORS = frozenset({'>', '>>', '>|', '&>', '&>>', '>&'})


class _Refusal(Exception):
    """Raised with the reason a command is not provably read-only."""


def _key(node: Node) -> Tuple[int, int, str]:
    return (node.start_byte, node.end_byte, node.type)


# Answers whether the user has remembered an approval that covers a command. It receives the command's name and its arguments as plain text, with None in place of any word the shell computes.
RememberedCommand = Callable[[List[Optional[str]]], bool]


class _Checker:
    def __init__(self, remembered: Optional[RememberedCommand] = None) -> None:
        self._remembered = remembered

    def check_script(self, text: str, depth: int) -> None:
        """Check one shell script. `depth` counts the substitutions and wrapper scripts already entered."""
        if len(text) > MAX_COMMAND_CHARACTERS:
            raise _Refusal('it is too long to check')
        parsed = parse_shell(text)
        if parsed.has_error:
            raise _Refusal('it is not shell syntax the checker can read completely')
        if parsed.root.descendant_count > MAX_SYNTAX_NODES:
            raise _Refusal('it is too large to check')
        if not any(node.type in ('command', 'test_command') for node in iter_nodes(parsed.root)):
            raise _Refusal('it runs no command')
        self._statement(parsed, parsed.root, depth)

    def _statement(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        kind = node.type
        if kind == 'comment':
            return
        if kind in _STATEMENT_CONTAINERS:
            for child in node.named_children:
                self._statement(parsed, child, depth)
            return
        if kind == 'command':
            self._command(parsed, node, depth)
            return
        if kind == 'redirected_statement':
            for child in node.named_children:
                if child.type in _REDIRECT_TYPES:
                    self._redirect(parsed, child, depth)
                else:
                    self._statement(parsed, child, depth)
            return
        if kind == 'for_statement':
            self._for_loop(parsed, node, depth)
            return
        if kind == 'variable_assignment':
            self._assignment(parsed, node, depth)
            return
        if kind == 'test_command':
            self._bracket_test(parsed, node)
            return
        raise _Refusal(f'it uses {kind.replace("_", " ")}, which is not on the read-only list')

    def _assignment(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        """Accept `name=value` for a scratch variable. Storing text changes nothing on disk; what could do harm is a name the shell or a program reads, or a value computed by something that is not itself read-only, and both are refused here. Where the variable is later used is checked by the walk at that use."""
        name_node = node.child_by_field_name('name')
        if name_node is None or name_node.type != 'variable_name':
            raise _Refusal('it assigns to something other than a plain variable name')
        name = parsed.text(name_node)
        if not _SCRATCH_VARIABLE_NAME.match(name) or name in _SHELL_SPECIAL_LOWERCASE_VARIABLES or name.endswith('_proxy'):
            raise _Refusal(f"it sets '{name}', a variable the shell or a program may read")
        value = node.child_by_field_name('value')
        known = {_key(name_node)}
        if value is not None:
            known.add(_key(value))
            # The value is stored, not run, so a substitution in it is allowed when its body is itself read-only.
            self._check_dynamic(parsed, value, True, depth)
        for child in node.named_children:
            if _key(child) not in known and child.type != 'comment':
                raise _Refusal('an assignment has a part the checker does not recognize')

    def _for_loop(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        body = node.child_by_field_name('body')
        if body is None:
            raise _Refusal('a loop has no body')
        known = {_key(body)}
        variable = node.child_by_field_name('variable')
        if variable is not None:
            known.add(_key(variable))
        for value in node.children_by_field_name('value'):
            known.add(_key(value))
            # The list a loop walks is data. A substitution in it is refused because it is not an argument of echo or printf.
            self._check_dynamic(parsed, value, False, depth)
        for child in node.named_children:
            if _key(child) not in known and child.type != 'comment':
                raise _Refusal('a loop has a part the checker does not recognize')
        self._statement(parsed, body, depth)

    def _command(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        name_node = node.child_by_field_name('name')
        if name_node is None:
            raise _Refusal('a command has no name')
        arguments = node.children_by_field_name('argument')
        known = {_key(name_node)} | {_key(argument) for argument in arguments}
        for child in node.named_children:
            if _key(child) in known or child.type == 'comment':
                continue
            if child.type in _REDIRECT_TYPES:
                self._redirect(parsed, child, depth)
            else:
                raise _Refusal('it sets a variable for one command or hides a command inside another')
        name = literal_command_name(parsed, node)
        if name is None:
            raise _Refusal('the name of a command it runs is quoted or computed')
        base = self._program_name(name)
        if base in SHELL_WRAPPERS:
            self._wrapper(parsed, node, depth)
            return
        if base not in policy.READ_ONLY_COMMANDS and base not in policy.CONDITIONALLY_READ_ONLY_COMMANDS:
            if self._is_remembered(parsed, name, arguments, depth):
                return
            raise _Refusal(f"'{base}' is not on the read-only list")
        prints_only = base in policy.PRINT_ONLY_COMMANDS
        argument_policy = base in policy.ARGUMENT_POLICY_COMMANDS
        values = [self._argument(parsed, argument, base, prints_only, argument_policy, depth) for argument in arguments]
        if argument_policy and policy.violates_argument_policy(base, values):
            raise _Refusal(f"the arguments of '{base}' can change something")

    def _is_remembered(self, parsed: ParsedShell, name: str, arguments: List[Node], depth: int) -> bool:
        """Whether the user has remembered an approval that covers this command. The caller's answer only counts when the words it matched are plain text, and every argument still gets the ordinary argument check, so a computed value or a substitution refuses the command here as it would anywhere else."""
        if self._remembered is None:
            return False
        words: List[Optional[str]] = [name] + [literal_text(parsed, argument) for argument in arguments]
        if not self._remembered(words):
            return False
        for argument in arguments:
            self._argument(parsed, argument, name, False, False, depth)
        return True

    def _program_name(self, name: str) -> str:
        """The program a command name runs: a bare name as written, or the last part of an absolute path in a system folder."""
        if '/' not in name:
            return name
        directory, _separator, base = name.rpartition('/')
        if directory not in policy.SYSTEM_COMMAND_DIRECTORIES:
            raise _Refusal(f"it runs a program by the path '{name}'")
        return base

    def _wrapper(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        found = find_wrapper_script(parsed, node)
        if found is None:
            raise _Refusal('a shell is started without a script the checker can read')
        if found.extra_arguments:
            raise _Refusal('a shell is given arguments after its script')
        if depth >= policy.MAX_NESTING_DEPTH:
            raise _Refusal('shell commands are nested too deeply')
        text = script_text(parsed, found.node, lambda child: self._is_trusted_variable(parsed, child))
        if text is None:
            raise _Refusal('the script given to a shell is computed')
        self.check_script(text, depth + 1)

    def _is_trusted_variable(self, parsed: ParsedShell, node: Node) -> bool:
        return node.type in ('simple_expansion', 'expansion') and variable_name_of(parsed.text(node)) in _TRUSTED_SCRIPT_VARIABLES

    def _argument(self, parsed: ParsedShell, node: Node, base: str, prints_only: bool, argument_policy: bool, depth: int) -> str:
        """Check one argument and return its plain-text value (an empty string for a computed one, which only commands without an argument policy may take)."""
        literal = literal_text(parsed, node)
        if literal is not None:
            if argument_policy and has_unsafe_unquoted_text(parsed, node, literal):
                raise _Refusal(f"an unquoted brace or glob in an argument of '{base}' could expand into an option")
            return literal
        self._check_dynamic(parsed, node, prints_only, depth)
        if not argument_policy:
            return ''
        raw = parsed.text(node)
        if _HOME_PATH_ARGUMENT.match(raw):
            return raw
        raise _Refusal(f"an argument of '{base}' is computed by the shell and could be an option")

    def _check_dynamic(self, parsed: ParsedShell, node: Node, prints_only: bool, depth: int) -> None:
        """Check every part of an argument the shell computes. Plain variables pass; substitutions are followed into their bodies; everything else computed is refused."""
        stack = [node]
        while stack:
            current = stack.pop()
            kind = current.type
            if kind == 'command_substitution':
                self._substitution(parsed, current, prints_only, depth)
            elif kind == 'process_substitution':
                self._process_substitution(parsed, current, depth)
            elif kind == 'expansion':
                if variable_name_of(parsed.text(current)) is None:
                    raise _Refusal('it uses a shell expansion other than a plain variable')
            elif kind == 'arithmetic_expansion':
                raise _Refusal('it uses arithmetic expansion')
            else:
                stack.extend(current.named_children)

    def _substitution(self, parsed: ParsedShell, node: Node, prints_only: bool, depth: int) -> None:
        if not prints_only:
            raise _Refusal('a command substitution is an argument of a command that acts on its output')
        if parsed.text(node).startswith('`'):
            raise _Refusal('it uses a backtick command substitution')
        if depth >= policy.MAX_NESTING_DEPTH:
            raise _Refusal('command substitutions are nested too deeply')
        for child in node.named_children:
            self._statement(parsed, child, depth + 1)

    def _process_substitution(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        if not parsed.text(node).startswith('<('):
            raise _Refusal('it feeds a command through >(...)')
        if depth >= policy.MAX_NESTING_DEPTH:
            raise _Refusal('process substitutions are nested too deeply')
        for child in node.named_children:
            self._statement(parsed, child, depth + 1)

    def _redirect(self, parsed: ParsedShell, node: Node, depth: int) -> None:
        if node.type != 'file_redirect':
            raise _Refusal('it uses a here-document or here-string')
        operator = ''.join(parsed.text(child) for child in node.children if not child.is_named)
        destination = node.child_by_field_name('destination')
        if destination is None:
            raise _Refusal('a redirection has no target')
        target = literal_text(parsed, destination)
        if operator == '<':
            self._check_dynamic(parsed, destination, False, depth)
            return
        if operator in ('<&', '>&') and target is not None and (target.isdigit() or target == '-'):
            return
        if operator in _OUTPUT_OPERATORS and target == policy.NULL_REDIRECTION_TARGET:
            return
        raise _Refusal('it redirects output to a file')

    def _bracket_test(self, parsed: ParsedShell, node: Node) -> None:
        opening = parsed.text(node.children[0]) if node.children else ''
        if opening != '[':
            raise _Refusal('it uses [[ ... ]], whose operators can evaluate text as code')
        for piece in iter_nodes(node):
            if piece.type in ('command_substitution', 'process_substitution', 'arithmetic_expansion'):
                raise _Refusal('a test contains a substitution or arithmetic')
            if piece.type == 'expansion' and variable_name_of(parsed.text(piece)) is None:
                raise _Refusal('a test contains an expansion other than a plain variable')


def classify_read_only(command: str, remembered: Optional[RememberedCommand] = None) -> ReadOnlyVerdict:
    """Whether `command` only reads, and the first reason when it does not. Any failure of the walk itself counts as not read-only. With `remembered`, a command the user has already approved and remembered also counts, so the verdict then means that nothing in the command is new to the user."""
    try:
        _Checker(remembered).check_script(command, 0)
    except _Refusal as refusal:
        return ReadOnlyVerdict(False, str(refusal))
    except RecursionError:
        return ReadOnlyVerdict(False, 'it is nested too deeply to check')
    except Exception as error:
        logger.exception('Read-only shell check failed; treating the command as not read-only')
        return ReadOnlyVerdict(False, f'the checker failed ({type(error).__name__})')
    return ReadOnlyVerdict(True, 'every command in it is read-only')
