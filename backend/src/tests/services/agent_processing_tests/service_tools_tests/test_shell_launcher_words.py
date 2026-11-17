"""A blocked program is still blocked when a launcher word starts it, and the approval card warns about the program the block found."""

import pytest

from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor
from api.services.agent_processing.tools.safety.shell_syntax import find_blocked_command
from api.services.agent_processing.tools.safety.shell_syntax.commands import launched_argv


@pytest.mark.parametrize(
    "command",
    [
        "env rm x",
        "nohup rm x",
        "xargs rm",
        "ls | xargs rm",
        "xargs -n 1 rm",
        "xargs -I {} rm {}",
        "find . -exec rm {} \\;",
        "find . -type f -execdir rm {} +",
        "env nohup rm x",
        "nice -n 10 rm x",
        "env -u HOME rm x",
        "env FOO=1 rm x",
        "timeout 5 rm x",
        "command rm x",
        "arch -arm64 rm x",
        "/usr/bin/env rm x",
        "ENV RM x",
        "env bash -c 'rm x'",
        "xargs sh -c 'rm \"$1\"' _",
        "find . -exec sh -c 'rm {}' \\;",
    ],
)
def test_a_blocked_program_started_through_a_launcher_is_found(command):
    assert find_blocked_command(command) == "rm"
    blocked, reason = RiskAssessor().check_blocked_commands(command)
    assert blocked is True and "'rm'" in reason


@pytest.mark.parametrize(
    "command",
    [
        "env",
        "env FOO=1 ls",
        "env | grep rm",
        "xargs echo rm",
        "xargs",
        "nohup ls",
        "command -v rm",
        "command -V rm",
        "find . -name rm",
        "find . -exec ls {} \\;",
        "nice -n 10 ls",
        "timeout 5 sleep 1",
        "echo rm",
        "ls rm",
    ],
)
def test_a_launcher_that_starts_nothing_blocked_is_left_alone(command):
    assert find_blocked_command(command) is None
    assert RiskAssessor().check_blocked_commands(command) == (False, None)


def test_the_launched_command_is_read_from_the_words_after_the_launcher_options():
    assert launched_argv(["env", "-u", "HOME", "FOO=1", "rm", "x"]) == ["rm", "x"]
    assert launched_argv(["timeout", "30s", "rm", "x"]) == ["rm", "x"]
    assert launched_argv(["nice", "-n", "10", "rm"]) == ["rm"]
    assert launched_argv(["xargs"]) is None
    assert launched_argv(["command", "-v", "rm"]) is None
    assert launched_argv(["ls", "rm"]) is None
    assert launched_argv(["find", ".", "-exec", "rm", "{}", ";"]) == ["rm", "{}", ";"]


def test_a_launcher_nested_past_the_limit_is_still_caught_through_loose_words():
    nested = "env bash -c 'env bash -c \"env bash -c \\\"env bash -c \\\\\\\"rm x\\\\\\\"\\\"\\\"'"
    assert find_blocked_command(nested) == "rm"


@pytest.mark.parametrize(
    "command,name",
    [
        ("rm x", "rm"),
        ("ls; rm x", "rm"),
        ("bash -lc 'rm x'", "rm"),
        ("env rm x", "rm"),
        ("xargs rm", "rm"),
        ("RM x", "rm"),
        ("sudo ls", "sudo"),
    ],
)
def test_the_approval_card_warns_about_the_program_the_block_found(command, name):
    metadata = RiskAssessor().get_risk_metadata(command)

    assert metadata["is_blocked"] is True
    assert metadata["warning_message"].startswith(f"The '{name}' command is blocked for security reasons")


@pytest.mark.parametrize("command", ["ls", "ls -la | sort", "env", "echo rm", "", "   "])
def test_the_approval_card_has_no_warning_for_a_command_that_runs_nothing_blocked(command):
    assert RiskAssessor().get_risk_metadata(command) == {}
