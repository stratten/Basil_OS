"""A command that is read-only by name must not be read-only when its arguments make it run another command or change state."""

from __future__ import annotations

import shlex

import pytest

from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor


@pytest.mark.parametrize(
    "command",
    [
        "env rm -rf /tmp/x",
        "env touch /tmp/x",
        "env curl -o /tmp/x https://example.com",
        "env -i sh -c 'rm /tmp/x'",
        "env FOO=1 ls",
        "ls | env touch /tmp/x",
        "bash -lc 'env touch /tmp/x'",
        "history -c",
        "history -w",
        "history -d 5",
        "date -s 2020-01-01",
        "date --set 2020-01-01",
        "date -us 2020-01-01",
        "file -C -m x",
        "file -bC x",
        "find . -fprint /tmp/x",
        "find . -fprintf /tmp/x '%p'",
        "find . -fls /tmp/x",
    ],
)
def test_a_read_only_command_with_state_changing_arguments_is_not_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "env",
        "ls | env",
        "history",
        "history 20",
        "date",
        "date -u",
        "date +%s",
        "date -u +%Y-%m-%dT%H:%M:%SZ",
        "date -jf %s 1700000000",
        "file notes.txt",
        "file -b --mime-type notes.txt",
        "find . -name '*.txt'",
        "ls -la",
        "cat notes.txt | head -5",
        "bash -lc 'ls -la'",
        "stat -f %z notes.txt",
    ],
)
def test_ordinary_reads_are_still_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "sort -o out in",
        "sort -ro out in",
        "sort --output=out in",
        "sort --out out in",
        "sort --compress-program=sh in",
        "uniq in out",
        "hostname newname",
        "hostname -F /tmp/x",
        "sed -n 'w out' in",
        "sed -n '1,5p;w out' in",
        "sed -n '1e rm x' in",
        "sed -n -i '1p' in",
        "sed -n '1p' in -i",
        "sed -i 's/a/b/' in",
        "sed 's/a/b/w out' in",
        "sed 's/a/b/e' in",
        "git push",
        "git commit -m x",
        "git -c core.pager='rm x' log",
        "git log --output=out",
        "git diff --out=out",
        "git diff --ext-diff",
        "git",
        "defaults write com.example key 1",
        "defaults delete com.example",
        "defaults",
    ],
)
def test_newly_allowed_commands_are_not_read_only_in_their_writing_forms(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "sort notes.txt | uniq -c | sort -rn | head -5",
        "cut -d, -f1 data.csv",
        "echo abc | tr a-z A-Z",
        "uname -a",
        "sw_vers",
        "pgrep -fl basil",
        "test -f notes.txt",
        "sleep 1",
        "printf '%s\\n' hello",
        "basename /a/b.txt",
        "dirname /a/b.txt",
        "realpath .",
        "readlink -f link",
        "diff a.txt b.txt",
        "jq . data.json",
        "shasum -a 256 notes.txt",
        "hostname",
        "hostname -s",
        "id -un",
        "uptime",
        "lsof -i :8000",
        "cd /tmp && ls",
        "sed -n '1,20p' notes.txt",
        "sed -n '$p' notes.txt",
        "sed -n '/needle/p' notes.txt",
        "sed 's/a/b/' notes.txt",
        "git status",
        "git log --oneline -5",
        "git diff --stat",
        "defaults read com.apple.dock",
        "defaults read-type com.apple.dock tilesize",
    ],
)
def test_newly_allowed_commands_are_read_only_in_their_reading_forms(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "ls 2>/dev/null",
        "ls 2>&1",
        "ls -la /tmp 2>&1 | head",
        "cat notes.txt > /dev/null",
        "ls &>/dev/null",
        "ls >&2",
        "uniq -c 2>&1",
        "ls 2>/dev/null | wc -l",
        "bash -lc 'ls 2>/dev/null'",
    ],
)
def test_redirects_that_write_no_file_do_not_make_a_command_unsafe(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "ls > out",
        "ls 2> err.txt",
        "ls >> out",
        "ls &> out",
        "ls >& out",
        "ls >|out",
        "ls 2>&1 > out",
        "ls 2>/dev/null/../x",
        "cat notes.txt >(rm x)",
        "ls > /dev/null > out",
    ],
)
def test_redirects_that_write_a_file_still_make_a_command_unsafe(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "for f in *.txt; do echo $f; done",
        "for f in a b; do cat $f | head -2; done",
        "if test -f a; then echo yes; else echo no; fi",
        "while test -f a; do sleep 1; done",
    ],
)
def test_loops_and_conditionals_around_read_only_commands_are_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "echo hi |(rm x)",
        "echo hi;(rm x)",
        "ls &&(rm x)",
        "cat <(rm x)",
        "for f in a b; do rm $f; done",
        "if test -f a; then rm a; fi",
        "while test -f a; do touch a; done",
        "for f in a; do echo $f; done > out",
        "test -f a && rm a",
        "cd /tmp && rm x",
        "sleep 1; kill 1",
    ],
)
def test_a_command_hidden_behind_an_operator_or_a_keyword_is_still_classified(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    ["echo hi;(rm x)", "echo hi |(rm x)", "ls &&(rm x)", "cat <(rm x)", "for f in a; do rm $f; done", "if test -f a; then rm a; fi"],
)
def test_a_blocked_command_is_found_behind_an_operator_or_a_keyword(command: str) -> None:
    blocked, _reason = RiskAssessor().check_blocked_commands(command)

    assert blocked is True


def test_a_loop_around_a_harmless_command_is_not_blocked() -> None:
    assert RiskAssessor().check_blocked_commands("for f in a; do echo $f; done")[0] is False


@pytest.mark.parametrize("command", ["sed -i s/a/b/ notes.txt", "defaults write com.example key 1"])
def test_conditionally_read_only_commands_are_not_rated_low_risk_by_name(command: str) -> None:
    assert RiskAssessor().assess_risk_level(command) != "low"


# The command an agent wrote to find documents that mention a word: `find` groups its name tests with escaped parentheses, behind a `cd`, a pipe and a second search.
_GROUPED_FIND_SCRIPT = (
    "cd '/Users/someone/Projects/AI-Enabled Apps/Example' && "
    "find . -path '*/node_modules' -prune -o -path '*/.git' -prune -o "
    "\\( -iname '*.md' -o -iname '*.tsx' -o -iname '*.ts' -o -iname '*.html' \\) -print | head -80; "
    "grep -rIil 'apex' --include=*.md --include=*.tsx --exclude-dir=node_modules --exclude-dir=.git . | head -80"
)


@pytest.mark.parametrize(
    "command",
    [
        "find . \\( -name a -o -name b \\) -print",
        "find . -type f \\( -iname '*.md' -o -iname '*.ts' \\) | head -20",
        "find . ! \\( -name a \\) -print",
        "find . \\( -name a -o \\( -name b -o -name c \\) \\) -print",
        "cd /tmp && find . \\( -name a -o -name b \\) -print | head -5",
        "grep '\\(a\\)' notes.txt",
        "echo \\(hello\\)",
        _GROUPED_FIND_SCRIPT,
        "bash -lc " + shlex.quote(_GROUPED_FIND_SCRIPT),
    ],
)
def test_find_grouping_with_escaped_parentheses_is_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "cd /tmp && find . -name x -delete",
        "ls && find . -exec rm {} +",
        "ls | find . -name '*.log' -delete",
        "cd /tmp && find . -execdir rm {} ;",
        "cd /tmp && find . -ok rm {} ;",
        "cd /tmp && find . -fprint out",
        "for f in a; do find $f -delete; done",
        "if test -d a; then find a -delete; fi",
        "find . \\( -name a -o -name b \\) -delete",
        "cd /tmp && find . \\( -name a \\) -exec rm {} +",
        "bash -lc 'cd /tmp && find . -name x -delete'",
        "bash -lc " + shlex.quote(_GROUPED_FIND_SCRIPT + "; find . -name '*.log' -delete"),
    ],
)
def test_a_find_that_deletes_or_runs_commands_is_not_read_only_wherever_it_appears(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "ls \\(; rm x",
        "ls \\); rm x",
        "echo \\\\(rm x)",
        "echo \\\\(touch x)",
        "find . \\( -name a \\) -print; rm x",
        "find . \\( -name a \\) -print | (rm x)",
        "find . \\( -name a \\) > out",
        "cd /tmp && find . \\( -name a \\) -print && rm x",
    ],
)
def test_an_escaped_parenthesis_does_not_hide_a_command_that_changes_something(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    ["find . \\( -name a \\) -print; rm -rf x", "ls \\(; rm x", "echo \\\\(rm x)", "cd /tmp && find . \\( -name a \\) -print && rm x"],
)
def test_a_blocked_command_is_still_found_next_to_an_escaped_parenthesis(command: str) -> None:
    blocked, _reason = RiskAssessor().check_blocked_commands(command)

    assert blocked is True


def test_an_escaped_parenthesis_is_an_ordinary_argument_to_find() -> None:
    assert RiskAssessor().is_read_only_command("find . \\( -name a \\) -print") is True


def test_an_escaped_parenthesis_inside_quotes_is_left_to_the_quoting_rules() -> None:
    assert RiskAssessor().is_read_only_command("echo '\\(' \"\\(\" x") is True
