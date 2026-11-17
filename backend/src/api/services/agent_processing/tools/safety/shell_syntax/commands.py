"""Finding the commands inside a shell string and reading their names and arguments.

Every `command` node counts, wherever it sits: at the top level, in a pipeline, in an `if` condition, in a loop body, in a subshell, in `$(...)` or backticks, inside a double-quoted string, in a process substitution, or in the quoted script of a shell wrapper such as `bash -lc '...'`. A wrapper script is parsed again and its commands join the list, down to the nesting limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional

from tree_sitter import Node

from ..command_words import SHELL_WRAPPERS, wrapper_command_flag_index
from . import command_policy as policy
from .parsing import ParsedShell, iter_nodes, parse_shell
from .words import literal_text, script_text

# Splits text the grammar could not read into candidate words. Whitespace, operators, quotes, and expansion punctuation all separate words, so a blocked name next to any of them is still seen.
LOOSE_WORD_SPLIT = re.compile(r"[\s;&|()<>`$\\'\"{}]+")


@dataclass(frozen=True)
class WrapperScript:
    """The script argument of a shell wrapper, and how many arguments follow it."""

    node: Node
    extra_arguments: int


@dataclass
class ShellCommands:
    """What a command string runs. `argvs` holds one list per command (the name as written, then each argument as its literal value, or as its source text when the shell computes it). `fallback_words` holds loose words from any text that could not be parsed, and is empty when everything parsed."""

    argvs: List[List[str]] = field(default_factory=list)
    fallback_words: List[str] = field(default_factory=list)


def iter_commands(parsed: ParsedShell) -> Iterator[Node]:
    return (node for node in iter_nodes(parsed.root) if node.type == 'command')


def literal_command_name(parsed: ParsedShell, command_node: Node) -> Optional[str]:
    """The command's name when it is one bare word, or None when it is quoted, computed, or missing."""
    name_node = command_node.child_by_field_name('name')
    if name_node is None:
        return None
    children = name_node.named_children
    if len(children) != 1 or children[0].type != 'word':
        return None
    return literal_text(parsed, children[0])


def decoded_command_name(parsed: ParsedShell, command_node: Node) -> Optional[str]:
    """The program name with its quoting removed (`"rm"`, `'rm'`, and `r\m` all run `rm`), or None when the shell computes it or the command has no name. The read-only check does not use this: it refuses a quoted name outright through `literal_command_name`."""
    name_node = command_node.child_by_field_name('name')
    if name_node is None:
        return None
    children = name_node.named_children
    if len(children) != 1:
        return None
    return literal_text(parsed, children[0])


def literal_argv(parsed: ParsedShell, command_node: Node) -> List[str]:
    """The command as a list of words, or an empty list when it has no name."""
    name_node = command_node.child_by_field_name('name')
    if name_node is None:
        return []
    name = decoded_command_name(parsed, command_node)
    argv = [name if name is not None else parsed.text(name_node)]
    for argument in command_node.children_by_field_name('argument'):
        value = literal_text(parsed, argument)
        argv.append(value if value is not None else parsed.text(argument))
    return argv


def find_wrapper_script(parsed: ParsedShell, command_node: Node) -> Optional[WrapperScript]:
    """The script argument of `bash -lc '...'` and the other shells in SHELL_WRAPPERS, or None when the command is not such a wrapper or is not given a script."""
    name = decoded_command_name(parsed, command_node)
    if name is None or name.split('/')[-1].lower() not in SHELL_WRAPPERS:
        return None
    arguments = command_node.children_by_field_name('argument')
    words = [name] + [literal_text(parsed, argument) or '\0' for argument in arguments]
    flag_index = wrapper_command_flag_index(words)
    if flag_index is None or flag_index >= len(arguments):
        return None
    return WrapperScript(node=arguments[flag_index], extra_arguments=len(arguments) - flag_index - 1)


def collect_commands(text: str, depth: int = 0) -> ShellCommands:
    """Every command in `text`, with wrapper scripts followed down to the nesting limit. Text that cannot be parsed, a wrapper script that cannot be rebuilt, and a wrapper nested past the limit all contribute loose words, so a blocked name inside them is still found."""
    parsed = parse_shell(text)
    found = ShellCommands()
    if parsed.has_error:
        found.fallback_words.extend(word for word in LOOSE_WORD_SPLIT.split(text) if word)
    for node in iter_commands(parsed):
        argv = literal_argv(parsed, node)
        if not argv:
            continue
        found.argvs.append(argv)
        wrapper = find_wrapper_script(parsed, node)
        if wrapper is None:
            continue
        script = script_text(parsed, wrapper.node, lambda _child: True)
        if script is None:
            found.fallback_words.extend(word for word in LOOSE_WORD_SPLIT.split(parsed.text(wrapper.node)) if word)
            continue
        if depth >= policy.MAX_NESTING_DEPTH:
            found.fallback_words.extend(word for word in LOOSE_WORD_SPLIT.split(script) if word)
            continue
        inner = collect_commands(script, depth + 1)
        found.argvs.extend(inner.argvs)
        found.fallback_words.extend(inner.fallback_words)
    return found


# A bare duration such as `5`, `1.5` or `30s`, which `timeout` takes before the program it runs.
DURATION_WORD = re.compile(r'^\d+(\.\d+)?[smhd]?$')


def launched_argv(argv: List[str]) -> Optional[List[str]]:
    """The command that `argv` starts on its own behalf (`env rm x` starts `rm x`, `find . -exec rm {} ;` starts `rm {}`), or None when it starts nothing or the words do not say."""
    name = argv[0].split('/')[-1].lower()
    rest = argv[1:]
    if name == 'find':
        for index, word in enumerate(rest[:-1]):
            if word in policy.FIND_EXEC_PREDICATES:
                return rest[index + 1:]
        return None
    value_options = policy.LAUNCHER_COMMANDS.get(name)
    if value_options is None:
        return None
    duration_pending = name == 'timeout'
    index = 0
    while index < len(rest):
        word = rest[index]
        if word == '--':
            index += 1
        elif word.startswith('-') and len(word) > 1:
            if name == 'command' and word in policy.COMMAND_LOOKUP_FLAGS:
                return None
            index += 2 if word in value_options else 1
        elif name == 'env' and '=' in word:
            index += 1
        elif duration_pending and DURATION_WORD.match(word):
            duration_pending = False
            index += 1
        else:
            return rest[index:]
    return None


def expand_launched_commands(found: ShellCommands, depth: int = 0) -> ShellCommands:
    """`found` plus every command its launcher programs start, followed through chains such as `env nohup rm x` and through the script of a shell wrapper they start (`xargs sh -c '...'`), down to the nesting limit. Text a launched wrapper hides past the limit contributes loose words, as it does in `collect_commands`."""
    expanded = ShellCommands(argvs=list(found.argvs), fallback_words=list(found.fallback_words))
    pending = list(found.argvs)
    while pending:
        argv = pending.pop()
        launched = launched_argv(argv)
        if not launched:
            continue
        expanded.argvs.append(launched)
        pending.append(launched)
        if launched[0].split('/')[-1].lower() not in SHELL_WRAPPERS:
            continue
        flag_index = wrapper_command_flag_index(launched)
        if flag_index is None or flag_index + 1 >= len(launched):
            continue
        script = launched[flag_index + 1]
        if depth >= policy.MAX_NESTING_DEPTH:
            expanded.fallback_words.extend(word for word in LOOSE_WORD_SPLIT.split(script) if word)
            continue
        inner = expand_launched_commands(collect_commands(script, depth + 1), depth + 1)
        expanded.argvs.extend(inner.argvs)
        expanded.fallback_words.extend(inner.fallback_words)
    return expanded


def find_blocked_command(text: str) -> Optional[str]:
    """The lowercase name of the first blocked command anywhere in `text`, or None. Names compare in lowercase because the Mac file system is case-insensitive and `RM` runs `rm`. A blocked program started through a launcher (`env rm x`, `xargs rm`, `find . -exec rm {} ;`) counts the same as one run directly."""
    found = expand_launched_commands(collect_commands(text))
    for candidate in [argv[0] for argv in found.argvs] + found.fallback_words:
        base = candidate.split('/')[-1].lower()
        if base in policy.BLOCKED_COMMANDS:
            return base
    return None


def wrapper_script_text(parsed: ParsedShell, command_node: Node, replaceable: Callable[[Node], bool]) -> Optional[str]:
    """The text of a wrapper command's script, or None when it is not a wrapper or the script cannot be rebuilt."""
    wrapper = find_wrapper_script(parsed, command_node)
    if wrapper is None:
        return None
    return script_text(parsed, wrapper.node, replaceable)


def inner_shell_script(command: str) -> str:
    """The script inside `bash -lc '...'` when the whole command is one such wrapper, otherwise the command unchanged."""
    parsed = parse_shell(command)
    statements = [child for child in parsed.root.named_children if child.type != 'comment']
    if len(statements) != 1 or statements[0].type != 'command':
        return command
    script = wrapper_script_text(parsed, statements[0], lambda _child: True)
    return command if script is None else script
