"""A whole command line sent as ``command`` is recovered into a runnable argv before approval and execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from api.services.agent_processing.tools.direct_application_interactions.shell.shell_command_line_recovery import (
    recover_command_line,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import (
    ShellService,
)


def test_plain_command_line_is_split_into_executable_and_args():
    assert recover_command_line("git status --short", None) == ("git", ["status", "--short"])


def test_quoted_argument_with_spaces_stays_one_argument():
    assert recover_command_line("ls -l 'My Dir'", None) == ("ls", ["-l", "My Dir"])


@pytest.mark.parametrize(
    "line",
    [
        "find /tmp -type f 2>/dev/null | wc -l",
        "ls /tmp && echo done",
        "echo one; echo two",
        "sort < /tmp/in.txt",
    ],
)
def test_line_with_shell_operators_runs_through_bash(line: str):
    assert recover_command_line(line, None) == ("bash", ["-lc", line])


def test_unbalanced_quote_runs_through_bash_instead_of_raising():
    line = 'echo "unterminated'
    assert recover_command_line(line, None) == ("bash", ["-lc", line])


def test_bash_lc_with_a_quoted_pipeline_is_split_without_double_wrapping():
    assert recover_command_line('bash -lc "echo hi | cat"', None) == ("bash", ["-lc", "echo hi | cat"])


def test_calls_that_already_use_args_are_unchanged():
    assert recover_command_line("find", ["/tmp", "-type", "f"]) == ("find", ["/tmp", "-type", "f"])
    assert recover_command_line("bash", ["-lc", "echo hi | cat"]) == ("bash", ["-lc", "echo hi | cat"])


def test_bare_executable_name_and_empty_command_are_unchanged():
    assert recover_command_line("ls", None) == ("ls", None)
    assert recover_command_line("", None) == ("", None)
    assert recover_command_line("   ", None) == ("   ", None)


def test_existing_path_containing_spaces_is_not_split(tmp_path: Path):
    executable = tmp_path / "my tool"
    executable.write_text("#!/bin/sh\n")
    assert recover_command_line(str(executable), None) == (str(executable), None)


def test_whole_pipeline_in_command_now_succeeds_end_to_end(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.txt").write_text("c")

    service = ShellService()
    service._home_root = tmp_path.resolve()
    result = asyncio.run(
        service.execute_command(
            f"find {tmp_path.resolve()} -type f 2>/dev/null | wc -l",
            cwd=str(tmp_path),
            skip_approval_check=True,
        )
    )

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "3"
    assert result["command_echo"].startswith("bash -lc ")
