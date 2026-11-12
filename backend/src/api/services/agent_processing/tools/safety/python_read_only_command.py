"""Recognize a command that does nothing but run a read-only Python one-liner.

The approval service receives the shell service's echo of the argv it is about to run, which is each argument passed through ``shlex.quote`` and joined by
spaces. That echo is reversible, so this module splits it back into the real argv and requires the re-quoted argv to equal the text it was given. A string
that only looks like such an echo (``python3 -c "x">file``, or one with a trailing comment) fails that round trip and is refused, because the shell would
read it differently from the way it is read here.

Two shapes are accepted, and nothing else around them:

- ``python3 [-I|-B|-E|-s|-u]... -c <script>``, started directly.
- ``bash -lc '<inner>'`` (also ``-c``; ``sh`` and ``zsh``), where ``<inner>`` is exactly the first shape with the script in one quoted word. The shell reads ``<inner>``
  itself, so its single-quote and double-quote rules are applied here by hand, and a ``$`` or backtick inside the script (which the shell would expand) refuses it.

Python puts the working directory first on the module search path for ``-c``, so a file such as ``json.py`` in the working directory would run in place of the
standard library. The ``-I`` flag prevents that. Without it, the command is accepted only when the working directory holds no file or package that shares a
name with a standard-library module.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from typing import List, Optional, Tuple

from .applescript_read_only_classifier import ReadOnlyVerdict
from .python_read_only_classifier import classify_python_read_only

# A shell is named bare (found on the user's PATH) or by its fixed system path. A path into the workspace could be a program the agent wrote.
SHELL_WRAPPER_NAMES = frozenset({"bash", "sh", "zsh", "/bin/bash", "/bin/sh", "/bin/zsh", "/usr/bin/bash", "/usr/bin/zsh"})
SHELL_COMMAND_FLAGS = frozenset({"-c", "-lc"})
ABSOLUTE_PYTHON_PATHS = frozenset({"/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"})
SAFE_PYTHON_FLAGS = frozenset({"-I", "-B", "-E", "-s", "-u"})
MAX_COMMAND_CHARACTERS = 20000
MAX_WORKING_DIRECTORY_ENTRIES = 5000
IMPORTABLE_SUFFIXES = (".py", ".pyc", ".so", ".pyd")

_PYTHON_NAME = re.compile(r"^python(3(\.\d+)?)?$")
_INNER_COMMAND = re.compile(
    r"""^\s*(?P<executable>\S+)(?P<flags>(?:\s+-[A-Za-z])*)\s+-c\s+"""
    r"""(?:'(?P<single>[^']*)'|"(?P<double>(?:[^"\\$`]|\\["\\]|\\[^"\\$`\n])*)")\s*$""",
    re.DOTALL,
)


def _no(reason: str) -> ReadOnlyVerdict:
    return ReadOnlyVerdict(False, reason)


def _is_python_executable(executable: str) -> bool:
    return executable in ABSOLUTE_PYTHON_PATHS or bool(_PYTHON_NAME.match(executable))


def _unescape_double_quoted(body: str) -> str:
    """Apply the shell's double-quote rule for the only escapes the pattern lets through: a backslash before a quote or a backslash."""
    return re.sub(r'\\(["\\])', r"\1", body)


def _script_from_direct_argv(argv: List[str]) -> Optional[Tuple[str, List[str]]]:
    if len(argv) < 3 or not _is_python_executable(argv[0]) or argv[-2] != "-c":
        return None
    flags = argv[1:-2]
    if any(flag not in SAFE_PYTHON_FLAGS for flag in flags):
        return None
    return argv[-1], flags


def _script_from_inner_command(inner: str) -> Optional[Tuple[str, List[str]]]:
    if len(inner) > MAX_COMMAND_CHARACTERS:
        return None
    match = _INNER_COMMAND.match(inner)
    if not match or not _is_python_executable(match.group("executable")):
        return None
    flags = match.group("flags").split()
    if any(flag not in SAFE_PYTHON_FLAGS for flag in flags):
        return None
    if match.group("single") is not None:
        return match.group("single"), flags
    return _unescape_double_quoted(match.group("double")), flags


def _split_echoed_argv(command: str) -> Optional[List[str]]:
    """Recover the real argv from the shell service's echo, or None when the text is not exactly such an echo."""
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND_CHARACTERS:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv or " ".join(shlex.quote(argument) for argument in argv) != command:
        return None
    return argv


def _working_directory_can_shadow_standard_library(working_directory: Optional[str]) -> Optional[str]:
    """Return why the working directory could replace a standard-library module, or None when it cannot."""
    standard_names = getattr(sys, "stdlib_module_names", None)
    if not standard_names:
        return "this Python cannot list its standard-library names"
    if not working_directory or not os.path.isdir(working_directory):
        return "the working directory is unknown"
    try:
        with os.scandir(working_directory) as entries:
            for count, entry in enumerate(entries):
                if count >= MAX_WORKING_DIRECTORY_ENTRIES:
                    return "the working directory has too many entries to check"
                stem = entry.name.split(".")[0]
                if stem not in standard_names:
                    continue
                if entry.is_dir():
                    if os.path.isfile(os.path.join(entry.path, "__init__.py")):
                        return f"the working directory holds a package named '{stem}'"
                elif entry.name.endswith(IMPORTABLE_SUFFIXES) or ".cpython-" in entry.name:
                    return f"the working directory holds a file named '{entry.name}'"
    except OSError:
        return "the working directory cannot be read"
    return None


def classify_python_command_read_only(command: str, *, working_directory: Optional[str], has_env_overrides: bool = False) -> ReadOnlyVerdict:
    """Return whether ``command`` is a Python one-liner that provably only reads data."""
    argv = _split_echoed_argv(command)
    if argv is None:
        return _no("the command is not a plain argument list")
    if has_env_overrides:
        return _no("the command sets environment variables, which can change which modules Python loads")

    found: Optional[Tuple[str, List[str]]] = None
    if argv[0] in SHELL_WRAPPER_NAMES:
        if len(argv) == 3 and argv[1] in SHELL_COMMAND_FLAGS:
            found = _script_from_inner_command(argv[2])
    else:
        found = _script_from_direct_argv(argv)
    if found is None:
        return _no("the command is not a single python3 -c one-liner")

    script, flags = found
    verdict = classify_python_read_only(script)
    if not verdict.is_read_only:
        return verdict
    if "-I" not in flags:
        shadow_reason = _working_directory_can_shadow_standard_library(working_directory)
        if shadow_reason:
            return _no(f"Python could load a module from the working directory instead of its own, because {shadow_reason}")
    return verdict


__all__ = ["classify_python_command_read_only"]
