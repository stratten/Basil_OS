"""The parts of the tree-sitter-bash tree the shell checks rely on. If a grammar upgrade changes one of them, this file fails before any command is misjudged."""

from __future__ import annotations

import pytest

from api.services.agent_processing.tools.safety.shell_syntax.parsing import iter_nodes, parse_shell


def _nodes(text: str, kind: str):
    parsed = parse_shell(text)
    return parsed, [node for node in iter_nodes(parsed.root) if node.type == kind]


def _only(text: str, kind: str):
    parsed, nodes = _nodes(text, kind)
    assert len(nodes) == 1, f"{text!r} has {len(nodes)} {kind} nodes"
    return parsed, nodes[0]


def test_a_command_has_a_name_field_and_argument_fields() -> None:
    parsed, command = _only("ls -la /tmp", "command")

    assert parsed.has_error is False
    assert command.child_by_field_name("name").type == "command_name"
    assert [parsed.text(argument) for argument in command.children_by_field_name("argument")] == ["-la", "/tmp"]


def test_the_two_substitution_forms_are_told_apart_by_their_opening_text() -> None:
    parsed, dollar = _only("echo $(ls)", "command_substitution")
    assert parsed.text(dollar).startswith("$(")

    parsed, backtick = _only("echo `ls`", "command_substitution")
    assert parsed.text(backtick).startswith("`")


def test_the_direction_of_a_process_substitution_is_in_its_opening_text() -> None:
    parsed, reading = _only("cat <(ls)", "process_substitution")
    assert parsed.text(reading).startswith("<(")

    parsed, writing = _only("ls >(cat)", "process_substitution")
    assert parsed.text(writing).startswith(">(")


@pytest.mark.parametrize(
    ("command", "operator", "destination"),
    [
        ("ls > out", ">", "out"),
        ("ls >> out", ">>", "out"),
        ("ls >| out", ">|", "out"),
        ("ls 2>&1", ">&", "1"),
        ("ls >&2", ">&", "2"),
        ("ls >& out", ">&", "out"),
        ("ls &> /dev/null", "&>", "/dev/null"),
        ("ls 2>/dev/null", ">", "/dev/null"),
        ("cat < notes.txt", "<", "notes.txt"),
    ],
)
def test_a_redirect_exposes_its_operator_and_destination(command: str, operator: str, destination: str) -> None:
    parsed, redirect = _only(command, "file_redirect")

    assert "".join(parsed.text(child) for child in redirect.children if not child.is_named) == operator
    assert parsed.text(redirect.child_by_field_name("destination")) == destination


@pytest.mark.parametrize(("command", "opening"), [("[ -f a ]", "["), ("[[ -f a ]]", "[[")])
def test_a_bracket_test_reports_its_opening_token(command: str, opening: str) -> None:
    parsed, test = _only(command, "test_command")

    assert parsed.text(test.children[0]) == opening


def test_a_for_loop_exposes_its_variable_values_and_body() -> None:
    parsed, loop = _only("for f in a b; do echo $f; done", "for_statement")

    assert parsed.text(loop.child_by_field_name("variable")) == "f"
    assert [parsed.text(value) for value in loop.children_by_field_name("value")] == ["a", "b"]
    assert loop.child_by_field_name("body").type == "do_group"


def test_a_variable_set_for_one_command_is_a_child_of_that_command() -> None:
    _parsed, command = _only("A=1 ls", "command")

    assert any(child.type == "variable_assignment" for child in command.named_children)


def test_a_bare_assignment_is_its_own_statement() -> None:
    parsed = parse_shell("A=1")

    assert parsed.root.named_children[0].type == "variable_assignment"


def test_an_escaped_parenthesis_is_an_ordinary_word() -> None:
    parsed, command = _only("find . \\( -name a \\) -print", "command")

    assert parsed.has_error is False
    assert [parsed.text(argument) for argument in command.children_by_field_name("argument")] == [".", "\\(", "-name", "a", "\\)", "-print"]


@pytest.mark.parametrize("command", ["ls (", "echo $(ls", "if true; then", "echo 'unterminated"])
def test_a_malformed_command_reports_an_error(command: str) -> None:
    assert parse_shell(command).has_error is True


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "find . -type f ! -newermt 2025-01-01",
        "echo FILES $(find . -maxdepth 1 -type f | wc -l)",
        "cd ~/Downloads; ls",
        "[ -f a ] && ls",
        "ls -1 | grep -iE '\\.(dmg|pkg|zip)$' | head -20",
        "diff <(ls a) <(ls b)",
        "echo hi # comment",
        "for f in *.txt; do echo $f; done",
        "if test -f a; then echo yes; else echo no; fi",
        "cd data 2>/dev/null || exit 1; ls",
        "bash -lc 'ls -la'",
        "echo \"$(ls | grep ')')\"",
    ],
)
def test_ordinary_agent_commands_parse_without_error(command: str) -> None:
    assert parse_shell(command).has_error is False


def test_a_here_document_body_exposes_its_substitution() -> None:
    _parsed, substitutions = _nodes("cat <<EOF\n$(rm x)\nEOF\n", "command_substitution")

    assert len(substitutions) == 1


def test_the_two_variable_expansion_forms_are_told_apart() -> None:
    _parsed, simple = _nodes("echo $x", "simple_expansion")
    assert len(simple) == 1

    parsed, braced = _only("echo ${y}", "expansion")
    assert parsed.text(braced) == "${y}"


def test_quoted_and_bare_pieces_of_one_word_are_one_concatenation() -> None:
    _parsed, command = _only('echo -"delete"', "command")
    arguments = command.children_by_field_name("argument")

    assert len(arguments) == 1
    assert arguments[0].type == "concatenation"


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("ls | wc -l", "pipeline"),
        ("ls && ls", "list"),
        ("! ls", "negated_command"),
        ("(ls)", "subshell"),
        ("{ ls; }", "compound_statement"),
        ("while test -f a; do sleep 1; done", "while_statement"),
        ("if test -f a; then ls; fi", "if_statement"),
        ("echo hi # note", "comment"),
        ("ls > out", "redirected_statement"),
        ("cat <<EOF\nhi\nEOF\n", "heredoc_redirect"),
        ("cat <<< hi", "herestring_redirect"),
        ("f() { ls; }", "function_definition"),
        ("case x in a) ls;; esac", "case_statement"),
        ("export A=1", "declaration_command"),
        ("echo $((1+2))", "arithmetic_expansion"),
    ],
)
def test_the_statement_nodes_the_walker_names_have_the_expected_type(command: str, kind: str) -> None:
    _parsed, nodes = _nodes(command, kind)

    assert nodes, f"{command!r} has no {kind} node"
