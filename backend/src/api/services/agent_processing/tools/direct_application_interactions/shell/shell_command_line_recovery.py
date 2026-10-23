"""Repair the two ways a model misuses the shell tool's ``command`` field, before approval and execution and in the failure message."""

from __future__ import annotations

import os
import shlex
from typing import List, Optional

_SHELL_OPERATOR_CHARS = frozenset("|&;<>()")


def recover_command_line(command: str, args: Optional[List[str]]) -> tuple[str, Optional[List[str]]]:
    """Turn a whole command line passed as ``command`` into a runnable argv.

    Smaller models often send ``command="find /dir -type f | wc -l"`` with no ``args``. No executable has that name, so the call can only fail with "Executable not found" and the model retries the same call. When ``args`` is empty and ``command`` contains whitespace (and is not an existing path), the line is tokenized with shell quoting rules: a plain line becomes ``command`` plus ``args``, and a line with shell operators (pipes, redirects, ``&&``, ``;``) or unbalanced quotes becomes ``bash -lc <line>``. Approval, whitelist matching, and the command echo all see the recovered argv, so the user approves exactly what runs.
    """
    if args or not command or not any(char.isspace() for char in command.strip()):
        return command, args
    if os.path.exists(command):
        return command, args
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return "bash", ["-lc", command]
    if not tokens:
        return command, args
    if any(set(token) <= _SHELL_OPERATOR_CHARS for token in tokens):
        return "bash", ["-lc", command]
    return tokens[0], tokens[1:]


def executable_not_found_message(command: str) -> str:
    """Build the model-facing failure text for a ``command`` that is not an executable on this machine.

    States what was looked for and the exact next step, so a model does not have to infer the tool contract from a bare "not found". The recovery above handles whole command lines, so this normally means a program that is genuinely not installed or a misspelled name.
    """
    return (
        f"Executable not found: {shlex.quote(command)}. "
        "`command` must be a single program name or absolute path that exists on this Mac (for example 'find', 'git', 'rg'); "
        "put every argument in `args` as a JSON array of strings. "
        "For pipelines, redirects, '&&' or ';' use command='bash' with args=['-lc', '<the whole line>']. "
        "If the program may not be installed, check with command='bash' args=['-lc', 'command -v <name>'] "
        "or use a different tool. Do not repeat this exact call."
    )
