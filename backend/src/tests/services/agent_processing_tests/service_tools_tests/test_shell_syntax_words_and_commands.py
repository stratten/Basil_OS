"""Reading words and finding commands in a parsed shell string: decoded literal values, wrapper scripts, and the commands inside substitutions, loops, and nested wrappers."""

from __future__ import annotations

import shlex

import pytest

from api.services.agent_processing.tools.safety.shell_syntax.commands import (
    collect_commands,
    find_blocked_command,
    find_wrapper_script,
    inner_shell_script,
    iter_commands,
)
from api.services.agent_processing.tools.safety.shell_syntax.parsing import parse_shell
from api.services.agent_processing.tools.safety.shell_syntax.words import (
    SCRIPT_VALUE_PLACEHOLDER,
    has_unsafe_unquoted_text,
    literal_text,
    script_text,
    variable_name_of,
)


def _first_argument(command: str):
    parsed = parse_shell(command)
    node = next(iter_commands(parsed))
    return parsed, node.children_by_field_name("argument")[0]


def _nested(script: str, depth: int) -> str:
    for _ in range(depth):
        script = "bash -c " + shlex.quote(script)
    return script


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("echo plain", "plain"),
        ("echo 'a b'", "a b"),
        ('echo "a b"', "a b"),
        ("echo a\\ b", "a b"),
        ("echo \\-delete", "-delete"),
        ('echo -"delete"', "-delete"),
        ("echo -'del'ete", "-delete"),
        ('echo "a\\$b"', "a$b"),
        ('echo "a\\\\b"', "a\\b"),
        ('echo "a\\nb"', "a\\nb"),
        ("echo 'a\\b'", "a\\b"),
        ("echo 42", "42"),
    ],
)
def test_quoting_and_backslashes_are_removed_from_a_literal_value(command: str, expected: str) -> None:
    parsed, argument = _first_argument(command)

    assert literal_text(parsed, argument) == expected


@pytest.mark.parametrize(
    "command",
    ["echo $x", 'echo "a$x"', "echo $(ls)", "echo `ls`", "echo $'a'", "echo $((1+2))", "echo ${x}", "echo <(ls)", "echo a$x"],
)
def test_a_value_the_shell_computes_has_no_literal_text(command: str) -> None:
    parsed, argument = _first_argument(command)

    assert literal_text(parsed, argument) is None


@pytest.mark.parametrize(
    ("command", "unsafe"),
    [
        ("echo {-delete,x}", True),
        ("echo -d*", True),
        ("echo -?", True),
        ("echo *.txt", False),
        ("echo '-d*'", False),
        ("echo '{a,b}'", False),
        ("echo plain", False),
        ("echo -name", False),
    ],
)
def test_unquoted_braces_and_option_shaped_globs_are_flagged(command: str, unsafe: bool) -> None:
    parsed, argument = _first_argument(command)
    literal = literal_text(parsed, argument)

    assert (literal is None or has_unsafe_unquoted_text(parsed, argument, literal)) is unsafe


@pytest.mark.parametrize(
    ("text", "name"),
    [("$HOME", "HOME"), ("${HOME}", "HOME"), ("$x1", "x1"), ("${x:-y}", None), ("${x@P}", None), ("${x[0]}", None), ("$((1))", None), ("plain", None)],
)
def test_only_a_plain_variable_reference_has_a_variable_name(text: str, name: object) -> None:
    assert variable_name_of(text) == name


def test_a_double_quoted_script_with_a_trusted_variable_is_rebuilt_with_a_placeholder() -> None:
    parsed = parse_shell("bash -lc \"grep '$HOME' notes.txt\"")
    wrapper = find_wrapper_script(parsed, next(iter_commands(parsed)))

    text = script_text(parsed, wrapper.node, lambda child: parsed.text(child) == "$HOME")

    assert text == f"grep '{SCRIPT_VALUE_PLACEHOLDER}' notes.txt"


def test_a_double_quoted_script_with_an_expansion_nobody_trusts_is_not_rebuilt() -> None:
    parsed = parse_shell('bash -c "ls $X"')
    wrapper = find_wrapper_script(parsed, next(iter_commands(parsed)))

    assert script_text(parsed, wrapper.node, lambda _child: False) is None


def test_a_literal_script_is_returned_as_written() -> None:
    parsed = parse_shell('bash -c "ls -la"')
    wrapper = find_wrapper_script(parsed, next(iter_commands(parsed)))

    assert script_text(parsed, wrapper.node, lambda _child: False) == "ls -la"


@pytest.mark.parametrize(
    ("command", "extra"),
    [
        ("bash -lc 'ls'", 0),
        ("sh -c ls", 0),
        ("dash -c 'ls' a b", 2),
        ("bash -l -c 'ls'", 0),
        ("bash --norc -c 'ls'", 0),
    ],
)
def test_a_wrapper_script_and_the_arguments_after_it_are_found(command: str, extra: int) -> None:
    parsed = parse_shell(command)
    wrapper = find_wrapper_script(parsed, next(iter_commands(parsed)))

    assert wrapper is not None
    assert wrapper.extra_arguments == extra


@pytest.mark.parametrize("command", ["ls -c x", "bash script.sh", "bash -l", "bash -c", "bash $FLAG -c ls"])
def test_a_command_that_is_not_given_a_script_is_not_a_wrapper_invocation(command: str) -> None:
    parsed = parse_shell(command)

    assert find_wrapper_script(parsed, next(iter_commands(parsed))) is None


def test_commands_inside_substitutions_loops_and_conditions_are_all_collected() -> None:
    found = collect_commands("if test -f a; then for f in x; do echo $(ls); done; fi")

    assert sorted(argv[0] for argv in found.argvs) == ["echo", "ls", "test"]
    assert found.fallback_words == []


def test_a_wrapper_script_is_followed_into_its_commands() -> None:
    found = collect_commands("bash -lc 'ls; rm x'")

    assert sorted(argv[0] for argv in found.argvs) == ["bash", "ls", "rm"]


def test_a_command_in_a_double_quoted_substitution_is_collected() -> None:
    found = collect_commands('ls "$(rm x)"')

    assert "rm" in [argv[0] for argv in found.argvs]


def test_a_computed_argument_is_kept_as_its_source_text() -> None:
    found = collect_commands("dd if=$X of=out")

    assert found.argvs == [["dd", "if=$X", "of=out"]]


def test_an_unparseable_string_contributes_loose_words() -> None:
    found = collect_commands("ls ( rm x")

    assert "rm" in found.fallback_words


def test_a_wrapper_nested_past_the_limit_still_exposes_a_blocked_name() -> None:
    assert find_blocked_command(_nested("rm x", 5)) == "rm"
    assert find_blocked_command(_nested("ls", 5)) is None


def test_the_script_inside_a_single_wrapper_command_is_found() -> None:
    assert inner_shell_script("bash -lc 'ls -la'") == "ls -la"
    assert inner_shell_script("ls -la") == "ls -la"
    assert inner_shell_script("bash -lc 'ls'; rm x") == "bash -lc 'ls'; rm x"
    assert inner_shell_script("bash script.sh") == "bash script.sh"
