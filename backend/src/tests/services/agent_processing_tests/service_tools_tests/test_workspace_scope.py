"""Tests for the checker that decides whether a command stays inside the task workspace."""

from __future__ import annotations

import os

import pytest

from api.services.agent_processing.tools.safety.workspace_scope import (
    judge_workspace_command,
    split_segments,
    tokenize,
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("alpha\n")
    return root


@pytest.fixture
def outside(tmp_path):
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "secret.txt").write_text("secret\n")
    return folder


def _judge(argv, workspace, cwd=None, env=False):
    return judge_workspace_command(argv, workspace=workspace, cwd=cwd or workspace, has_env_overrides=env)


ALLOWED = [
    ["cat", "a.txt"],
    ["cat", "-n", "a.txt", "sub/b.txt"],
    ["head", "-n", "5", "a.txt"],
    ["head", "-5", "a.txt"],
    ["tail", "-n", "+5", "a.txt"],
    ["tail", "-c", "200", "a.txt"],
    ["wc", "-l", "a.txt"],
    ["wc", "-l"],
    ["ls"],
    ["ls", "-la", "sub"],
    ["grep", "-n", "foo", "a.txt", "sub/b.txt"],
    ["grep", "-rn", "foo", "."],
    ["grep", "-e", "foo", "-e", "bar", "a.txt"],
    ["grep", "--include=*.txt", "-r", "foo", "."],
    ["cut", "-d", ",", "-f", "1", "a.csv"],
    ["sort", "-n", "a.txt"],
    ["sort", "-o", "out.txt", "a.txt"],
    ["uniq", "-c", "a.txt"],
    ["mkdir", "-p", "x/y"],
    ["touch", "new.txt"],
    ["cp", "a.txt", "b.txt"],
    ["cp", "-r", "sub", "sub2"],
    ["mv", "a.txt", "c.txt"],
    ["pdftotext", "-layout", "in.pdf", "out.txt"],
    ["pdftotext", "-f", "1", "-l", "3", "in.pdf", "-"],
    ["pdfinfo", "in.pdf"],
    ["qpdf", "in.pdf", "out.pdf"],
    ["qpdf", "--password=pw", "--decrypt", "in.pdf", "out.pdf"],
    ["qpdf", "--empty", "--pages", "a.pdf", "1-3", "b.pdf", "z", "--", "out.pdf"],
    ["bash", "-lc", "cat a.txt | head -n 3 > out.txt"],
    ["bash", "-c", "grep 'a|b' a.txt"],
    ["zsh", "-lc", 'grep "two words" a.txt'],
    ["sh", "-c", "wc -l < a.txt"],
    ["bash", "-lc", "cat a.txt && wc -l a.txt"],
    ["bash", "-lc", "grep '&&' a.txt"],
]

DENIED = [
    ["cat", "../other/a.txt"],
    ["cat", "/etc/hosts"],
    ["cat", "-f", "a.txt"],
    ["tail", "-f", "a.txt"],
    ["head", "a.txt", "-n"],
    ["grep", "-R", "foo", "."],
    ["grep", "-f", "/etc/passwd", "a.txt"],
    ["grep"],
    ["sort", "-o", "/tmp/escape.txt", "a.txt"],
    ["sort", "--compress-program=sh", "a.txt"],
    ["sort", "-T", "/tmp", "a.txt"],
    ["cp", "a.txt"],
    ["cp", "a.txt", "../b.txt"],
    ["cp", "-r", "sub", "/tmp/sub"],
    ["mv", "a.txt", "/tmp/a.txt"],
    ["mkdir", "-p"],
    ["touch"],
    ["uniq", "a", "b", "c"],
    ["pdftotext", "-f", "1", "-l", "3", "in.pdf", "/tmp/o.txt"],
    ["pdfinfo", "in.pdf", "extra.pdf"],
    ["pdfinfo", "-bogus", "in.pdf"],
    ["qpdf", "--job-json-file=/etc/x", "a.pdf"],
    ["qpdf", "--empty", "--pages", "a.pdf", "1-3", "--", "/tmp/out.pdf"],
    ["qpdf", "--empty", "--pages", "a.pdf"],
    ["qpdf", "--object-streams=bogus", "a.pdf", "b.pdf"],
    ["python3", "script.py"],
    ["node", "script.js"],
    ["rm", "a.txt"],
    ["sed", "-i", "s/a/b/", "a.txt"],
    ["awk", "{print}", "a.txt"],
    ["find", ".", "-delete"],
    ["rg", "foo"],
    ["jq", "-n", "env"],
    ["env"],
    ["echo", "hi"],
    ["curl", "https://example.com"],
    ["./cat", "a.txt"],
    ["/bin/cat", "a.txt"],
    ["bash", "script.sh"],
    ["bash", "-lc", "cat a.txt", "extra"],
    ["bash", "-lc", "cat a.txt > ../out.txt"],
    ["bash", "-lc", "cat a.txt; rm a.txt"],
    ["bash", "-lc", "cat a.txt || true"],
    ["bash", "-lc", "cat a.txt &"],
    ["bash", "-lc", "cat a.txt 2>&1"],
    ["bash", "-lc", "cat <<EOF"],
    ["bash", "-lc", "cat $(whoami)"],
    ["bash", "-lc", "cat `whoami`"],
    ["bash", "-lc", "cat $HOME/a.txt"],
    ["bash", "-lc", "cat ~/a.txt"],
    ["bash", "-lc", "ls *.txt"],
    ["bash", "-lc", "grep 'a$' a.txt"],
    ["bash", "-lc", "cat a.txt\nrm a.txt"],
    ["bash", "-lc", "cat a.txt > "],
    ["bash", "-lc", "cat 'unterminated"],
    ["bash", "-lc", "python3 x.py | cat"],
    ["bash", "-lc", "cat a.txt | python3"],
    ["bash", "-lc", "(cat a.txt)"],
]


@pytest.mark.parametrize("argv", ALLOWED, ids=lambda argv: " ".join(argv))
def test_allowed_commands(argv, workspace):
    verdict = _judge(argv, workspace)

    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("argv", DENIED, ids=lambda argv: " ".join(argv) or "empty")
def test_denied_commands(argv, workspace):
    verdict = _judge(argv, workspace)

    assert not verdict.allowed
    assert verdict.reason


def test_an_absolute_path_inside_the_workspace_is_allowed(workspace):
    assert _judge(["cat", str(workspace / "a.txt")], workspace).allowed


def test_an_absolute_path_outside_the_workspace_is_denied(workspace, outside):
    verdict = _judge(["cat", str(outside / "secret.txt")], workspace)

    assert not verdict.allowed
    assert "outside the task workspace" in verdict.reason


def test_a_symbolic_link_out_of_the_workspace_is_denied(workspace, outside):
    os.symlink(outside, workspace / "link")

    assert not _judge(["cat", "link/secret.txt"], workspace).allowed
    assert not _judge(["cp", "a.txt", "link/copy.txt"], workspace).allowed
    assert not _judge(["bash", "-lc", "cat a.txt > link/copy.txt"], workspace).allowed
    assert not _judge(["bash", "-lc", "cat < link/secret.txt"], workspace).allowed


def test_a_symbolic_link_inside_the_workspace_is_allowed(workspace):
    os.symlink(workspace / "sub", workspace / "alias")

    assert _judge(["touch", "alias/new.txt"], workspace).allowed


def test_a_path_that_does_not_exist_yet_is_resolved_without_escaping(workspace):
    assert _judge(["touch", "new/../new2.txt"], workspace).allowed
    assert not _judge(["touch", "new/../../x.txt"], workspace).allowed


def test_a_null_byte_in_a_path_is_denied(workspace):
    assert not _judge(["cat", "a\x00b"], workspace).allowed


def test_a_working_directory_inside_the_workspace_resolves_relative_paths_from_there(workspace):
    assert _judge(["cat", "../a.txt"], workspace, cwd=workspace / "sub").allowed
    assert not _judge(["cat", "../../a.txt"], workspace, cwd=workspace / "sub").allowed


def test_a_working_directory_outside_the_workspace_is_denied(workspace, outside):
    verdict = _judge(["cat", "secret.txt"], workspace, cwd=outside)

    assert not verdict.allowed
    assert "working directory" in verdict.reason


def test_environment_overrides_disable_the_rule(workspace):
    verdict = _judge(["cat", "a.txt"], workspace, env=True)

    assert not verdict.allowed
    assert "environment" in verdict.reason


def test_a_missing_workspace_or_working_directory_is_denied(workspace):
    assert not judge_workspace_command(["cat", "a.txt"], workspace=None, cwd=workspace).allowed
    assert not judge_workspace_command(["cat", "a.txt"], workspace=workspace, cwd=None).allowed
    assert not judge_workspace_command(["cat", "a.txt"], workspace="", cwd="").allowed


@pytest.mark.parametrize("argv", [None, [], ["cat", 1], "cat a.txt", {"cat": "a.txt"}])
def test_a_malformed_command_is_denied(argv, workspace):
    assert not _judge(argv, workspace).allowed


def test_a_direct_command_has_no_shell_so_its_arguments_are_literal_names(workspace):
    assert _judge(["cat", "$HOME/secret"], workspace).allowed
    assert not _judge(["bash", "-lc", "cat $HOME/secret"], workspace).allowed


def test_tokenize_marks_unquoted_operators_and_keeps_quoted_ones_as_words():
    assert tokenize("grep 'a|b' f | wc -l") == [("grep", False), ("a|b", False), ("f", False), ("|", True), ("wc", False), ("-l", False)]
    assert tokenize("cat a >> b") == [("cat", False), ("a", False), (">>", True), ("b", False)]
    assert tokenize("cat ''") == [("cat", False), ("", False)]


@pytest.mark.parametrize("line", ["cat a; rm b", "cat a &", "cat a 2>&1", "cat $x", "cat `x`", "cat a\\b", "cat 'open", "ls *.c", "cat ~", "cat !x", "cat #x", "(cat a)", "cat {a,b}", "cat a\nb"])
def test_tokenize_rejects_syntax_outside_the_accepted_subset(line):
    assert tokenize(line) is None


def test_split_segments_groups_commands_and_redirections():
    tokens = tokenize("cat a | head -n 2 > out.txt && wc -l < out.txt")

    assert split_segments(tokens) == [
        (["cat", "a"], []),
        (["head", "-n", "2"], [(">", "out.txt")]),
        (["wc", "-l"], [("<", "out.txt")]),
    ]


@pytest.mark.parametrize("line", ["| cat a", "cat a |", "cat a | | wc", "cat a >", "cat a > > b", "> out"])
def test_split_segments_rejects_malformed_structure(line):
    tokens = tokenize(line)

    assert tokens is not None
    assert split_segments(tokens) is None
