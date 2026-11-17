"""Blocked programs and dangerous patterns are found by what a command runs, wherever it runs it: after a separator, inside a substitution, a condition, a loop, a quoted name, or a nested shell wrapper."""

from __future__ import annotations

import shlex
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor
from api.services.agent_processing.tools.safety.shell_syntax import command_matches_pattern, find_blocked_command


def _nested(script: str, depth: int) -> str:
    for _ in range(depth):
        script = "bash -c " + shlex.quote(script)
    return script


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        ("rm x", "rm"),
        ("ls; rm x", "rm"),
        ("ls && rm x", "rm"),
        ("echo $(rm x)", "rm"),
        ("echo `rm x`", "rm"),
        ('ls "$(rm x)"', "rm"),
        ("if true; then rm x; fi", "rm"),
        ("for f in a; do rm $f; done", "rm"),
        ("diff <(rm x) b", "rm"),
        ("cat <<EOF\n$(rm x)\nEOF\n", "rm"),
        ('bash -lc "rm x"', "rm"),
        ("bash -lc 'ls; rm x'", "rm"),
        ("dash -c 'rm x'", "rm"),
        ("/bin/rm x", "rm"),
        ("RM x", "rm"),
        ("A=1 rm x", "rm"),
        ('"rm" x', "rm"),
        ("'rm' x", "rm"),
        ("r\\m x", "rm"),
        ('"bash" -c "rm x"', "rm"),
        ("sudo ls", "sudo"),
        ("ls 'a b'; sudo x", "sudo"),
        ("ls ( rm x", "rm"),
        (_nested("rm x", 5), "rm"),
    ],
)
def test_a_blocked_program_is_found_wherever_the_command_runs_it(command: str, blocked: str) -> None:
    assert find_blocked_command(command) == blocked


@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "echo rm",
        "grep rm file.txt",
        "cat dd",
        "ls -la ~/Downloads/rm.txt",
        "git status",
        "mv 'MD BCBA Information.csv' x",
        _nested("ls", 5),
    ],
)
def test_a_command_that_runs_no_blocked_program_is_not_blocked(command: str) -> None:
    assert find_blocked_command(command) is None


def test_the_blocked_message_keeps_its_format() -> None:
    assert RiskAssessor().check_blocked_commands("RM x") == (
        True,
        "Command 'rm' is blocked for security reasons and cannot be executed",
    )


def test_a_command_with_nothing_blocked_returns_no_reason() -> None:
    assert RiskAssessor().check_blocked_commands("ls -la") == (False, None)


@pytest.mark.parametrize(
    ("pattern", "command", "expected"),
    [
        ("format", "mv 'MD BCBA Information.csv' x", False),
        ("format", "format /dev/disk1", True),
        ("rm -rf /", 'rm -rf "/"', True),
        ("rm -rf /", "ls; rm -rf /", True),
        ("rm -rf /", "bash -c 'rm -rf /'", True),
        ("rm -rf /", "RM -RF /", True),
        ("rm -rf /", "ls ( rm -rf /", True),
        ("rm -rf /", _nested("rm -rf /", 5), True),
        ("rm -rf /", "rm -rf /tmp/x", False),
        ("sudo rm", "echo sudo rm", True),
        ("dd if=", "dd if=/dev/zero of=x", True),
        ("dd if=", "echo dd if=x", False),
        ("chmod 777", "chmod 777 x", True),
        ("rm", "ls rm.txt", False),
        (":(){ :|:& };:", ":(){ :|:& };:", True),
        ("", "ls", False),
    ],
)
def test_a_dangerous_pattern_matches_the_commands_a_string_runs(pattern: str, command: str, expected: bool) -> None:
    assert command_matches_pattern(command, pattern) is expected


def test_the_dangerous_pattern_check_reports_the_first_matching_pattern() -> None:
    settings = SimpleNamespace(dangerous_patterns=["chown root", "chmod 777"])

    assert RiskAssessor().check_dangerous_patterns("ls; chmod 777 x", settings) == (
        True,
        "Command contains dangerous pattern: chmod 777",
    )


def test_the_dangerous_pattern_check_reports_a_blocked_program_before_any_pattern() -> None:
    settings = SimpleNamespace(dangerous_patterns=["chmod 777"])

    allowed, reason = RiskAssessor().check_dangerous_patterns("ls; sudo ls", settings)

    assert allowed is True
    assert "blocked for security reasons" in reason


def test_a_safe_command_matches_no_pattern() -> None:
    settings = SimpleNamespace(dangerous_patterns=["chmod 777", "rm -rf /"])

    assert RiskAssessor().check_dangerous_patterns("ls -la", settings) == (False, None)


@pytest.mark.parametrize(
    ("command", "high_risk"),
    [("ls", False), ("pkill x", True), ("bash -lc 'kill 1'", True), ("bash -lc 'ls'", False)],
)
def test_a_shell_wrapper_is_rated_by_the_command_inside_it(command: str, high_risk: bool) -> None:
    assert RiskAssessor().is_high_risk(command) is high_risk
