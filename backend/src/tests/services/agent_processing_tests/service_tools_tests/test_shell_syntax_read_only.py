"""What the parse-tree read-only check accepts and refuses, including the forms a word-splitting tokenizer could not see: quoting, escapes, substitutions, redirections, loops, wrappers, and size limits."""

from __future__ import annotations

import shlex

import pytest

from api.services.agent_processing.tools.safety.shell_syntax import read_only as read_only_module
from api.services.agent_processing.tools.safety.shell_syntax.read_only import classify_read_only


def _nested(script: str, depth: int) -> str:
    for _ in range(depth):
        script = "bash -c " + shlex.quote(script)
    return script


READ_ONLY_COMMANDS = [
    "ls -la",
    "ls | wc -l",
    "cd ~/Downloads && ls -1 | head -20",
    'echo "$(ls | wc -l) files"',
    "find . -type f ! -newermt 2025-01-01 | wc -l",
    "ls -1 | grep -iE '\\.(dmg|pkg|zip)$' | head -20",
    "for f in a b; do echo $f; done",
    "if test -f a; then echo yes; else echo no; fi",
    "[ -f notes.txt ] && cat notes.txt",
    "command -v jq >/dev/null 2>&1 && echo yes",
    "diff <(ls a) <(ls b)",
    "bash -lc 'ls -la'",
    "bash -lc \"grep '$HOME' notes.txt\"",
    'find "$HOME/Downloads" -name x',
    "/bin/ls -la",
    "/usr/bin/find . -name x",
    "echo a # delete everything",
    # A variable kept for later is data, not a write.
    "f=$(ls | head -1); echo $f",
    'count=$(ls | wc -l); echo "$count files"',
    "n=3; ls | head -$n",
    "dirs=(a b); ls $dirs",
    "a=x; b=$a; echo $b",
    "name=$(date); cat notes.txt",
    "find . \\( -name a \\) -print",
    "echo '\\(' \"\\(\" x",
    "sed -n '1,20p' notes.txt",
    "sed -n '40,78p;96,112p' notes.txt",
    "sed -n '1p;$p;/Transcript/p' notes.txt",
    "sed 's/old/new/' notes.txt",
    "md5 -r *",
    "ls -la; md5 -r * | sort; grep -c '^## Transcript' *",
    "md5sum a b | cut -d' ' -f1",
    "sha256sum notes.txt",
    "shasum -a 256 notes.txt",
    "cksum notes.txt",
    "git status",
    "git log --oneline",
    "cd data 2>/dev/null || exit 1; ls",
    "ls\nls -la",
    "env",
    "echo $HOME",
    "echo ${HOME}",
    "echo '$(rm x)'",
    "echo $(echo $(echo $(ls)))",
    "cat 'café ☕.txt'",
    "echo 'é☕' \"$(date)\"",
    "ls 2>/dev/null",
    "ls &>/dev/null",
]


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_a_command_that_only_reads_is_read_only(command: str) -> None:
    verdict = classify_read_only(command)

    assert verdict.is_read_only is True, verdict.reason


NOT_READ_ONLY_COMMANDS = [
    # Commands that change things.
    "rm x",
    "mkdir x",
    "ls; rm x",
    "ls && rm x",
    "ls || rm x",
    "ls | rm x",
    "ls & rm x",
    "ls # note\nrm x",
    'echo "ls" ; rm x',
    "if true; then rm x; fi",
    "for f in a; do rm $f; done",
    "while true; do rm x; done",
    "! rm x",
    "(rm x)",
    "{ rm x; }",
    # Writes.
    "ls > out.txt",
    "ls >> out.txt",
    "ls &> out.txt",
    "ls 2> out.txt",
    "ls >| out.txt",
    "ls >(cat)",
    "cat <<EOF\nhi\nEOF\n",
    "cat <<< hi",
    # Substitutions and expansions.
    "echo $(rm x)",
    "echo $(echo $(rm x))",
    "echo $(echo $(echo $(echo $(ls))))",
    "echo `date`",
    "ls $(date)",
    "ls `date`",
    'ls "$(date)"',
    "echo $((1+2))",
    "echo ${x:-y}",
    "diff <(rm x) b",
    "for f in $(ls); do echo $f; done",
    # Shell constructs that are not on the list.
    "A=1 ls",
    "f=1 ls",
    "A=1",
    "export A=1",
    "export f=1; ls",
    # An assignment is allowed only to a plain lowercase scratch variable, and only with a value that is itself read-only.
    "PATH=/tmp/evil:$PATH; ls",
    "HOME=/tmp; ls",
    "IFS=x; ls",
    "LD_PRELOAD=/tmp/x.so; ls",
    "PAGER=/tmp/evil; git log",
    "Foo=1; ls",
    "path=(/tmp/evil); ls",
    "fpath=/tmp/evil; ls",
    "http_proxy=http://x; ls",
    "a[0]=1; ls",
    "f=$(rm x); ls",
    "f=$(touch x); ls",
    "f=`date`; ls",
    "f=$((1+2)); ls",
    "f=${x:-y}; ls",
    # What a stored value is later used for is still checked where it is used.
    "f=ls; $f -la",
    "f=-delete; find . $f",
    "f=x; bash -c \"ls $f\"",
    "f=1; echo hi > $f",
    "f() { ls; }",
    "case x in a) ls;; esac",
    "[[ -f a ]]",
    "[ $(rm x) ]",
    # Program names.
    "./ls",
    "/tmp/ls",
    "'ls'",
    '"ls" -la',
    "$X -la",
    # Arguments that change what a command does.
    "find . -delete",
    "find . -exec rm {} \\;",
    "find . -name x $FLAG",
    "find . {-delete,x}",
    "find . -d*",
    'find . -"del"ete',
    "find . -'delete'",
    "find . \\-delete",
    "find . -`echo delete`",
    "sed -i s/a/b/ f",
    "sed 's/a/b/w out' f",
    "sed -n '1w out' f",
    "sed -n '1p;2w out' f",
    "sed -n '1p;e ls' f",
    "sed -n '1p;;2p' f",
    "sed -n '1p;' f",
    "sed -n '1p 2p' f",
    "sed -n '1,2p;3,4d' f",
    "sort -o out f",
    "sort --out=out f",
    "uniq a b",
    "hostname x",
    "git -c core.pager=x log",
    "git push",
    "defaults write a b c",
    "command rm x",
    "env rm x",
    # Wrappers.
    "bash script.sh",
    "bash -c 'rm x'",
    'bash -c "ls $X"',
    "bash -lc 'ls' extra",
    "bash -c",
    # Input the checker cannot read completely.
    "",
    "   ",
    "# only a comment",
    "ls (",
    "ls 'unterminated",
    "echo $(ls",
    "echo é $(rm x)",
]


@pytest.mark.parametrize("command", NOT_READ_ONLY_COMMANDS)
def test_a_command_that_could_change_something_is_not_read_only(command: str) -> None:
    assert classify_read_only(command).is_read_only is False


def test_a_variable_assignment_inside_a_wrapper_is_read_only_when_everything_in_it_is() -> None:
    script = "f=$(ls -d ~/.basil/*/ 2>/dev/null | head -0); find / -name 'r-4d51d2a1*' -not -path '*/proc/*' 2>/dev/null | head -3"
    assert classify_read_only("bash -lc " + shlex.quote(script)).is_read_only


def test_a_variable_assignment_inside_a_wrapper_is_refused_when_its_value_is_not() -> None:
    script = "f=$(rm x); ls"
    assert not classify_read_only("bash -lc " + shlex.quote(script)).is_read_only


def test_the_reason_names_a_variable_the_shell_reads() -> None:
    verdict = classify_read_only("path=(/tmp/evil); ls")
    assert not verdict.is_read_only
    assert "'path'" in verdict.reason


def test_three_nested_wrappers_pass_and_a_fourth_is_refused() -> None:
    assert classify_read_only(_nested("ls", 3)).is_read_only is True
    assert classify_read_only(_nested("ls", 4)).is_read_only is False


def test_a_wrapper_that_hides_a_change_in_its_innermost_script_is_refused() -> None:
    assert classify_read_only(_nested("rm x", 2)).is_read_only is False


def test_a_very_long_command_is_refused_without_parsing_it() -> None:
    verdict = classify_read_only("ls " + "a" * 20_001)

    assert verdict.is_read_only is False
    assert "too long" in verdict.reason


def test_a_command_with_thousands_of_parts_is_refused_as_too_large() -> None:
    verdict = classify_read_only("ls; " * 3000)

    assert verdict.is_read_only is False
    assert "too large" in verdict.reason


def test_the_reason_names_the_command_that_is_not_on_the_list() -> None:
    assert "'rm'" in classify_read_only("rm x").reason


def test_the_reason_names_an_output_redirection() -> None:
    assert "redirects output" in classify_read_only("ls > out").reason


def test_a_failure_inside_the_check_means_not_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_command: str):
        raise RuntimeError("parser failure")

    monkeypatch.setattr(read_only_module, "parse_shell", explode)

    verdict = classify_read_only("ls")

    assert verdict.is_read_only is False
    assert "RuntimeError" in verdict.reason
