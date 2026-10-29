"""Conservative proof that an AppleScript only reads data and changes nothing.

A script is read-only only when every statement is one this module recognizes and positively understands. Anything it cannot parse, any application
outside a short list of read-oriented applications, any mutating verb, and any shell command that the shell classifier does not call read-only makes
the whole script "not read-only", which keeps the normal approval prompt. A false "not read-only" costs one approval click; a false "read-only" would
let a change run unasked, so every ambiguity resolves toward the prompt.

"Read-only" means no side effects: it cannot change files, settings, mail, calendar, or system state and cannot send anything. It does not mean
"harmless to read": macOS still asks the user for permission before an application shares private data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Set, Tuple

READ_ORIENTED_APPLICATIONS: frozenset[str] = frozenset(
    {
        "mail",
        "microsoft outlook",
        "calendar",
        "reminders",
        "notes",
        "contacts",
        "finder",
        "safari",
        "google chrome",
        "music",
        "messages",
    }
)

MUTATING_WORDS: frozenset[str] = frozenset(
    {
        "make", "new", "delete", "remove", "move", "duplicate", "copy", "send", "open", "activate", "launch", "quit", "close", "save", "print",
        "keystroke", "key", "click", "press", "perform", "select", "choose", "display", "say", "beep", "run", "load", "store", "write",
        "append", "import", "export", "reveal", "eject", "mount", "unmount", "empty", "restart", "shut", "sleep", "reply", "forward",
        "redirect", "compose", "add", "insert", "paste", "set", "do", "execute", "administrator", "privileges", "trash", "rename", "tag",
        "mark", "flag", "unflag", "archive", "dismiss", "snooze", "stop", "play", "pause", "login", "logout", "log_out", "post",
        "upload", "download", "install", "uninstall", "kill", "terminate", "clear", "reset", "update", "modify", "change", "edit", "create",
        "check", "get_url", "connect", "disconnect", "enable", "disable", "toggle", "apply",
    }
)

_STATEMENT_ENDERS = {"tell", "repeat", "if", "try", "timeout"}
_SIMPLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STRING_TOKEN = re.compile(r'"__STR(\d+)__"')
_SHELL_CALL = re.compile(r'do\s+shell\s+script\s+("__STR\d+__")(?!\s*[&\w])', re.IGNORECASE)


@dataclass(frozen=True)
class ReadOnlyVerdict:
    """The classifier's answer and, when it is False, the first reason, for logs and tests."""

    is_read_only: bool
    reason: str


def _no(reason: str) -> ReadOnlyVerdict:
    return ReadOnlyVerdict(False, reason)


def _mask_strings_and_comments(script: str) -> Optional[Tuple[List[str], List[str]]]:
    """Logical lines with every string literal replaced by a placeholder and comments removed; None when the text cannot be read reliably."""
    pieces: List[str] = []
    literals: List[str] = []
    index, length = 0, len(script)
    while index < length:
        char = script[index]
        if char == '"':
            cursor, buffer = index + 1, []
            while cursor < length:
                if script[cursor] == "\\" and cursor + 1 < length:
                    buffer.append(script[cursor:cursor + 2])
                    cursor += 2
                    continue
                if script[cursor] == '"':
                    break
                buffer.append(script[cursor])
                cursor += 1
            else:
                return None
            literals.append("".join(buffer))
            pieces.append(f'"__STR{len(literals) - 1}__"')
            index = cursor + 1
        elif script.startswith("(*", index):
            depth, cursor = 1, index + 2
            while cursor < length and depth:
                if script.startswith("(*", cursor):
                    depth, cursor = depth + 1, cursor + 2
                elif script.startswith("*)", cursor):
                    depth, cursor = depth - 1, cursor + 2
                else:
                    cursor += 1
            if depth:
                return None
            pieces.append(" ")
            index = cursor
        elif script.startswith("--", index) or char == "#":
            while index < length and script[index] != "\n":
                index += 1
        else:
            pieces.append(char)
            index += 1
    text = re.sub(r"¬[ \t]*\n", " ", "".join(pieces))
    if "«" in text or "»" in text:
        return None
    lines = [line.strip() for line in text.split("\n")]
    return [line for line in lines if line], literals


def _unescape(literal: str) -> str:
    return re.sub(r"\\(.)", lambda match: {"n": "\n", "t": "\t", "r": "\r"}.get(match.group(1), match.group(1)), literal)


def _words(expression: str) -> Set[str]:
    return {word.lower() for word in _WORD.findall(_STRING_TOKEN.sub(" ", expression))}


def _expression_reason(expression: str) -> Optional[str]:
    """Why an expression is not read-only (a mutating verb appears in it), or None when it contains none."""
    offending = sorted(_words(expression) & MUTATING_WORDS)
    return f"uses the verb or word '{offending[0]}'" if offending else None


def _looks_like_private_variable(name: str) -> bool:
    """camelCase, underscored, or digit-bearing names are user variables; plain lowercase or ALLCAPS words are usually application properties."""
    if not _SIMPLE_NAME.match(name) or name.lower() in MUTATING_WORDS:
        return False
    has_inner_upper = any(char.isupper() for char in name[1:]) and any(char.islower() for char in name)
    return has_inner_upper or "_" in name or any(char.isdigit() for char in name)


class _Classifier:
    def __init__(self, literals: List[str], shell_is_read_only: Callable[[str], bool]) -> None:
        self.literals = literals
        self.shell_is_read_only = shell_is_read_only
        self.blocks: List[str] = []
        self.known_locals: Set[str] = set()

    def _tell_depth(self) -> int:
        return sum(1 for block in self.blocks if block == "tell")

    def _literal_for(self, token: str) -> Optional[str]:
        match = _STRING_TOKEN.fullmatch(token.strip())
        return _unescape(self.literals[int(match.group(1))]) if match else None

    def _shell_reason(self, statement: str) -> Tuple[str, Optional[str]]:
        """Replace an allowed ``do shell script "<literal>"`` with a neutral token, or report why it is not allowed."""
        if not re.search(r"\bdo\s+shell\s+script\b", statement, re.IGNORECASE):
            return statement, None
        match = _SHELL_CALL.search(statement)
        if not match or len(re.findall(r"\bdo\s+shell\s+script\b", statement, re.IGNORECASE)) != 1:
            return statement, "runs a shell command that is not a single literal string"
        command = self._literal_for(match.group(1))
        if not command or not self.shell_is_read_only(command):
            return statement, "runs a shell command that is not provably read-only"
        return statement[: match.start()] + "shellresult" + statement[match.end():], None

    def classify_line(self, line: str) -> Optional[str]:
        """None when the line is read-only; otherwise the reason it is not."""
        lowered = line.lower()
        tokens = lowered.split()
        head = tokens[0]

        if head == "end":
            expected = tokens[1] if len(tokens) > 1 else ""
            if expected not in _STATEMENT_ENDERS or not self.blocks or self.blocks[-1] != expected:
                return "has an unmatched or unknown 'end'"
            self.blocks.pop()
            return None
        if head == "try" and len(tokens) == 1:
            self.blocks.append("try")
            return None
        if lowered.startswith("on error"):
            if not self.blocks or self.blocks[-1] != "try":
                return "has 'on error' outside a try block"
            self.known_locals.update(word for word in _WORD.findall(line[len("on error"):]) if word.lower() not in {"number", "from", "to", "partial", "result"})
            return None
        if head == "else":
            if not self.blocks or self.blocks[-1] != "if":
                return "has 'else' outside an if block"
            rest = line[4:].strip()
            if rest.lower().startswith("if "):
                return self._condition_reason(rest[3:])
            return None if not rest else "has unexpected text after 'else'"
        if head == "if":
            return self._classify_if(line)
        if head == "repeat":
            return self._classify_repeat(line)
        if head == "tell":
            return self._classify_tell(line)
        if head == "with" and lowered.startswith("with timeout"):
            self.blocks.append("timeout")
            return _expression_reason(line[len("with timeout"):])
        if head == "do" and lowered.startswith("do shell script"):
            return self._shell_check_and_scan(line)
        if head in {"get", "count", "exists", "return", "log", "delay"}:
            if head == "log" and lowered.startswith("log out"):
                return "logs out"
            return self._shell_check_and_scan(line[len(head):])
        if head in {"local", "global"}:
            self.known_locals.update(_WORD.findall(line[len(head):]))
            return None
        if head == "set":
            return self._classify_set(line)
        return f"has a statement starting with '{head}' that is not recognized as read-only"

    def _shell_check_and_scan(self, expression: str) -> Optional[str]:
        expression, shell_problem = self._shell_reason(expression)
        return shell_problem or _expression_reason(expression)

    def _condition_reason(self, condition: str) -> Optional[str]:
        condition = re.sub(r"\bthen\b\s*$", "", condition.strip(), flags=re.IGNORECASE)
        return self._shell_check_and_scan(condition)

    def _classify_if(self, line: str) -> Optional[str]:
        body = line[2:].strip()
        match = re.match(r"^(.*?)\bthen\b\s*(.*)$", body, re.IGNORECASE)
        if not match:
            return "has an 'if' without 'then'"
        condition, remainder = match.group(1), match.group(2).strip()
        reason = self._shell_check_and_scan(condition)
        if reason:
            return reason
        if remainder:
            return self.classify_line(remainder)
        self.blocks.append("if")
        return None

    def _classify_repeat(self, line: str) -> Optional[str]:
        rest = line[len("repeat"):].strip()
        lowered = rest.lower()
        with_match = re.match(r"^with\s+([A-Za-z_][A-Za-z0-9_]*)\s+(in|from)\s+(.*)$", rest, re.IGNORECASE)
        if with_match:
            self.known_locals.add(with_match.group(1))
            self.blocks.append("repeat")
            return self._shell_check_and_scan(with_match.group(3))
        if lowered == "" or re.fullmatch(r"(while|until)\s+.+|\S+\s+times?", lowered):
            self.blocks.append("repeat")
            return self._shell_check_and_scan(rest)
        return "has a 'repeat' form that is not recognized"

    def _classify_tell(self, line: str) -> Optional[str]:
        body = line[len("tell"):].strip()
        match = re.match(r'^(application\s+"__STR(\d+)__")\s*(?:to\s+(.*))?$', body, re.IGNORECASE)
        if not match:
            return "tells something other than a named application"
        application = _unescape(self.literals[int(match.group(2))]).strip().lower()
        if application not in READ_ORIENTED_APPLICATIONS:
            return f"talks to '{application}', which is not on the read-oriented application list"
        inline = match.group(3)
        self.blocks.append("tell")
        if not inline:
            return None
        depth_with_tell = len(self.blocks)
        reason = self.classify_line(inline)
        if reason is None and len(self.blocks) != depth_with_tell:
            reason = "has an inline 'tell' that opens a block"
        del self.blocks[depth_with_tell - 1:]
        return reason

    def _classify_set(self, line: str) -> Optional[str]:
        match = re.match(r"^set\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+(.+)$", line, re.IGNORECASE)
        if not match:
            return "sets something other than a plain variable"
        name, expression = match.group(1), match.group(2)
        in_tell = self._tell_depth() > 0
        if in_tell and name not in self.known_locals and not _looks_like_private_variable(name):
            return f"sets '{name}' inside an application block, where it could be an application property"
        if not in_tell and name.lower() in MUTATING_WORDS:
            return f"sets '{name}', which is also a command word"
        reason = self._shell_check_and_scan(expression)
        if reason:
            return reason
        self.known_locals.add(name)
        return None

    def finish(self) -> Optional[str]:
        return "has an unclosed block" if self.blocks else None


def classify_applescript_read_only(script: str, shell_is_read_only: Callable[[str], bool]) -> ReadOnlyVerdict:
    """Return whether ``script`` provably only reads data.

    ``shell_is_read_only`` judges the literal command of each ``do shell script "..."`` (the caller passes the shell risk assessor's check).
    """
    if not isinstance(script, str) or not script.strip():
        return _no("the script is empty")
    masked = _mask_strings_and_comments(script)
    if masked is None:
        return _no("the script has an unterminated string, comment, or raw event code")
    lines, literals = masked
    if not lines:
        return _no("the script has no statements")

    classifier = _Classifier(literals, shell_is_read_only)
    for line in lines:
        reason = classifier.classify_line(line)
        if reason:
            return _no(f"the line '{_unmask(line, literals)[:80]}' {reason}")
    unfinished = classifier.finish()
    return _no(f"the script {unfinished}") if unfinished else ReadOnlyVerdict(True, "every statement is a recognized read-only form")


def _unmask(line: str, literals: List[str]) -> str:
    return _STRING_TOKEN.sub(lambda match: f'"{literals[int(match.group(1))]}"', line)


__all__ = [
    "MUTATING_WORDS",
    "READ_ORIENTED_APPLICATIONS",
    "ReadOnlyVerdict",
    "classify_applescript_read_only",
]
