"""Decide whether a shell command stays inside one task's workspace and uses only file-handling programs.

This is an approval policy, not a sandbox. It accepts a command only when it fully understands it, so anything unfamiliar falls through to the normal approval path. Paths are checked after symbolic links are resolved. The shell syntax accepted is deliberately tiny, because every extra feature is another way for a path to hide.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

SHELL_NAMES = frozenset({"bash", "sh", "zsh"})
_SHELL_COMMAND_FLAGS = frozenset({"-c", "-lc"})
_REJECTED_ANYWHERE = frozenset("\n\r\x00`$\\")
_REJECTED_UNQUOTED = frozenset("*?[]{}~!#;()")
_NUMERIC_FLAG = re.compile(r"^-\d+$")
_PAGE_RANGE = re.compile(r"^[rz]?\d*(-[rz]?\d*)?(,[rz]?\d*(-[rz]?\d*)?)*(:odd|:even)?$")
_QPDF_ROTATE = re.compile(r"^--rotate=[+-]?\d+(:[0-9a-z,-]*)?$")
_QPDF_PLAIN_FLAGS = frozenset({"--empty", "--linearize", "--decrypt", "--qdf", "--warning-exit-0", "--check", "--show-npages"})
_QPDF_CHOICES = {
    "--compress-streams": frozenset({"y", "n"}),
    "--object-streams": frozenset({"generate", "disable", "preserve"}),
}

Token = Tuple[str, bool]
Segment = Tuple[List[str], List[Tuple[str, str]]]


@dataclass(frozen=True)
class ScopeVerdict:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class CommandSpec:
    """The options one program may use. A value that names a path is checked like any other path."""

    flags: FrozenSet[str] = frozenset()
    value_flags: FrozenSet[str] = frozenset()
    path_value_flags: FrozenSet[str] = frozenset()
    pattern_flags: FrozenSet[str] = frozenset()
    pattern_positionals: int = 0
    min_paths: int = 0
    max_paths: Optional[int] = None
    numeric_flag: bool = False
    single_dash_words: bool = False
    dash_is_stdio: bool = False


def _letters(letters: str) -> FrozenSet[str]:
    return frozenset(f"-{letter}" for letter in letters)


SPECS: Dict[str, CommandSpec] = {
    "cat": CommandSpec(flags=_letters("nbsvet")),
    "head": CommandSpec(flags=_letters("q"), value_flags=frozenset({"-n", "-c"}), numeric_flag=True),
    "tail": CommandSpec(flags=_letters("q"), value_flags=frozenset({"-n", "-c"}), numeric_flag=True),
    "wc": CommandSpec(flags=_letters("lwcm")),
    "ls": CommandSpec(flags=_letters("lahAtSrRdF1")),
    "grep": CommandSpec(
        flags=_letters("ivnclLowxEFrhHqsIa"),
        value_flags=frozenset({"-m", "-A", "-B", "-C", "--include", "--exclude"}),
        path_value_flags=frozenset({"-f"}),
        pattern_flags=frozenset({"-e", "-f"}),
        pattern_positionals=1,
    ),
    "cut": CommandSpec(flags=_letters("s"), value_flags=frozenset({"-d", "-f", "-c", "-b"})),
    "sort": CommandSpec(flags=_letters("nrufbhVsgM"), value_flags=frozenset({"-k", "-t"}), path_value_flags=frozenset({"-o"})),
    "uniq": CommandSpec(flags=_letters("cdui"), max_paths=2),
    "mkdir": CommandSpec(flags=_letters("p"), min_paths=1),
    "touch": CommandSpec(min_paths=1),
    "cp": CommandSpec(flags=_letters("rRpnfv"), min_paths=2),
    "mv": CommandSpec(flags=_letters("nfv"), min_paths=2),
    "pdftotext": CommandSpec(
        flags=frozenset({"-layout", "-raw", "-nopgbrk", "-table", "-q"}),
        value_flags=frozenset({"-f", "-l", "-enc", "-eol", "-opw", "-upw"}),
        min_paths=1,
        max_paths=2,
        single_dash_words=True,
        dash_is_stdio=True,
    ),
    "pdfinfo": CommandSpec(
        flags=frozenset({"-isodates", "-rawdates", "-box", "-meta"}),
        value_flags=frozenset({"-f", "-l", "-opw", "-upw"}),
        min_paths=1,
        max_paths=1,
        single_dash_words=True,
    ),
}
PROGRAMS = frozenset(SPECS) | frozenset({"qpdf"})


def tokenize(line: str) -> Optional[List[Token]]:
    """Split one shell line into (text, is_operator) tokens, or None when it uses anything outside the accepted syntax."""
    if any(char in _REJECTED_ANYWHERE for char in line):
        return None
    tokens: List[Token] = []
    word: List[str] = []
    in_word = False
    quote: Optional[str] = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote is not None:
            if char == quote:
                quote = None
            else:
                word.append(char)
            index += 1
            continue
        if char in "'\"":
            quote = char
            in_word = True
            index += 1
            continue
        if char.isspace():
            if in_word:
                tokens.append(("".join(word), False))
                word, in_word = [], False
            index += 1
            continue
        if char in "|&<>":
            if in_word:
                tokens.append(("".join(word), False))
                word, in_word = [], False
            pair = line[index:index + 2]
            if pair in ("&&", ">>"):
                tokens.append((pair, True))
                index += 2
                continue
            if char in "|<>":
                tokens.append((char, True))
                index += 1
                continue
            return None
        if char in _REJECTED_UNQUOTED:
            return None
        word.append(char)
        in_word = True
        index += 1
    if quote is not None:
        return None
    if in_word:
        tokens.append(("".join(word), False))
    return tokens


def split_segments(tokens: Sequence[Token]) -> Optional[List[Segment]]:
    """Group tokens into commands separated by | or &&, each with its redirections, or None when the structure is malformed."""
    segments: List[Segment] = []
    words: List[str] = []
    redirects: List[Tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        text, is_operator = tokens[index]
        if not is_operator:
            words.append(text)
            index += 1
            continue
        if text in ("|", "&&"):
            if not words:
                return None
            segments.append((words, redirects))
            words, redirects = [], []
            index += 1
            continue
        if index + 1 >= len(tokens) or tokens[index + 1][1]:
            return None
        redirects.append((text, tokens[index + 1][0]))
        index += 2
    if not words:
        return None
    segments.append((words, redirects))
    return segments


def _option_paths(spec: CommandSpec, args: Sequence[str]) -> Optional[List[str]]:
    """The path arguments of one command, or None when it uses an option or shape the spec does not allow."""
    paths: List[str] = []
    positionals: List[str] = []
    pattern_given = False
    options_done = False
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if options_done or arg == "-" or not arg.startswith("-"):
            positionals.append(arg)
            continue
        if arg == "--":
            options_done = True
            continue
        if arg.startswith("--"):
            name, equals, attached = arg.partition("=")
            if name in spec.flags and not equals:
                continue
            kind = "value" if name in spec.value_flags else "path" if name in spec.path_value_flags else None
            if kind is None:
                return None
            if equals:
                value = attached
            elif index < len(args):
                value = args[index]
                index += 1
            else:
                return None
            if kind == "path":
                paths.append(value)
            continue
        if spec.numeric_flag and _NUMERIC_FLAG.match(arg):
            continue
        if spec.single_dash_words or len(arg) == 2:
            if arg in spec.flags:
                continue
            kind = "value" if arg in spec.value_flags else "path" if arg in spec.path_value_flags else "pattern" if arg in spec.pattern_flags else None
            if kind is None or index >= len(args):
                return None
            value = args[index]
            index += 1
            if arg in spec.pattern_flags:
                pattern_given = True
            if kind == "path":
                paths.append(value)
            continue
        if all(f"-{letter}" in spec.flags for letter in arg[1:]):
            continue
        return None
    skipped = 0 if pattern_given else spec.pattern_positionals
    if len(positionals) < skipped:
        return None
    operands = positionals[skipped:]
    if len(operands) < spec.min_paths:
        return None
    if spec.max_paths is not None and len(operands) > spec.max_paths:
        return None
    for value in operands:
        if value == "-" and spec.dash_is_stdio:
            continue
        paths.append(value)
    return paths


def _qpdf_paths(args: Sequence[str]) -> Optional[List[str]]:
    """The path arguments of one qpdf command, or None when it uses an option outside the short list."""
    paths: List[str] = []
    in_pages = False
    for arg in args:
        if in_pages:
            if arg == "--":
                in_pages = False
            elif arg.startswith("-"):
                return None
            elif not (arg and _PAGE_RANGE.match(arg)):
                paths.append(arg)
            continue
        if arg == "--pages":
            in_pages = True
        elif arg in _QPDF_PLAIN_FLAGS or arg.startswith("--password=") or _QPDF_ROTATE.match(arg):
            continue
        elif arg.startswith("--") and "=" in arg and arg.split("=", 1)[0] in _QPDF_CHOICES:
            name, value = arg.split("=", 1)
            if value not in _QPDF_CHOICES[name]:
                return None
        elif arg.startswith("-"):
            return None
        else:
            paths.append(arg)
    return None if in_pages else paths


def _paths_for(program: str, args: Sequence[str]) -> Optional[List[str]]:
    if program == "qpdf":
        return _qpdf_paths(args)
    spec = SPECS.get(program)
    return None if spec is None else _option_paths(spec, args)


def _real(path: Any) -> Optional[Path]:
    try:
        return Path(os.path.realpath(os.fspath(path)))
    except (OSError, TypeError, ValueError):
        return None


def _contains(root: Path, path: Path) -> bool:
    return path == root or root in path.parents


def _is_inside(text: str, working_dir: Path, workspace: Path) -> bool:
    if "\x00" in text:
        return False
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = working_dir / candidate
    resolved = _real(candidate)
    return resolved is not None and _contains(workspace, resolved)


def _segments(argv: List[str]) -> Optional[List[Segment]]:
    if argv[0] not in SHELL_NAMES:
        return [(argv, [])]
    if len(argv) != 3 or argv[1] not in _SHELL_COMMAND_FLAGS:
        return None
    tokens = tokenize(argv[2])
    return None if tokens is None else split_segments(tokens)


def _deny(reason: str) -> ScopeVerdict:
    return ScopeVerdict(False, reason)


def judge_workspace_command(
    argv: Any,
    *,
    workspace: Any,
    cwd: Any,
    has_env_overrides: bool = False,
) -> ScopeVerdict:
    """Allow a command only when it is file-handling work wholly inside the task workspace."""
    if has_env_overrides:
        return _deny("The command sets environment variables.")
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(part, str) for part in argv):
        return _deny("The command is not a list of words.")
    if not workspace or not cwd:
        return _deny("There is no task workspace to check against.")
    workspace_root = _real(workspace)
    working_dir = _real(cwd)
    if workspace_root is None or working_dir is None or not _contains(workspace_root, working_dir):
        return _deny("The working directory is outside the task workspace.")
    segments = _segments(list(argv))
    if segments is None:
        return _deny("The command uses shell syntax outside the accepted subset.")
    for words, redirects in segments:
        program = words[0]
        if program not in PROGRAMS:
            return _deny(f"{program!r} is not on the workspace list.")
        paths = _paths_for(program, words[1:])
        if paths is None:
            return _deny(f"{program!r} is used with an option or shape outside the accepted subset.")
        for target in [*paths, *(target for _, target in redirects)]:
            if not _is_inside(target, working_dir, workspace_root):
                return _deny(f"{target!r} is outside the task workspace.")
    return ScopeVerdict(True, "File-handling commands inside this task's workspace do not need approval")
