"""Tests for recognizing a command that only runs a read-only Python one-liner."""

from __future__ import annotations

import shlex
import shutil
import subprocess

import pytest

from api.services.agent_processing.tools.safety.python_read_only_command import (
    _unescape_double_quoted,
    classify_python_command_read_only,
)

SCRIPT = (
    "import json;d=json.load(open('.tool_results/r-d9440e33.txt'));"
    "[print('===',r['requestNumber'],r['status'],r.get('updatedAt','')[:10],'\\n',"
    "((r.get('pauseState') or {}).get('message') or str(r.get('latestActivitySummary')))[:1500]) for r in d]"
)


def _echo(*argv: str) -> str:
    """What the shell service passes to the approval service: each argument quoted and joined by spaces."""
    return " ".join(shlex.quote(part) for part in argv)


def _double_quoted(script: str) -> str:
    return '"' + script.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _inner(script: str, flags: str = "") -> str:
    return f"python3 {flags + ' ' if flags else ''}-c {_double_quoted(script)}"


@pytest.fixture
def clean_directory(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\n")
    return str(tmp_path)


def _verdict(command, directory, **kwargs):
    return classify_python_command_read_only(command, working_directory=directory, **kwargs)


def test_the_screenshot_command_is_recognized(clean_directory):
    command = _echo("bash", "-lc", _inner(SCRIPT))
    assert "'\"'\"'" in command
    assert _verdict(command, clean_directory).is_read_only


@pytest.mark.parametrize("shell", ["bash", "sh", "zsh", "/bin/bash", "/bin/zsh"])
@pytest.mark.parametrize("flag", ["-c", "-lc"])
def test_shell_wrapper_forms_are_recognized(shell, flag, clean_directory):
    assert _verdict(_echo(shell, flag, _inner("print(1)")), clean_directory).is_read_only


@pytest.mark.parametrize("executable", ["python3", "python", "python3.12", "/usr/bin/python3", "/opt/homebrew/bin/python3"])
def test_direct_python_forms_are_recognized(executable, clean_directory):
    assert _verdict(_echo(executable, "-c", "print(1)"), clean_directory).is_read_only


def test_single_quoted_script_inside_a_shell_wrapper_is_recognized(clean_directory):
    assert _verdict(_echo("bash", "-lc", "python3 -c 'print(\"hi\")'"), clean_directory).is_read_only


def test_a_script_with_newlines_and_indentation_is_recognized(clean_directory):
    script = "import json\nwith open('a.json') as f:\n    d = json.load(f)\nfor k in d:\n    print(k)"
    assert _verdict(_echo("python3", "-c", script), clean_directory).is_read_only
    assert _verdict(_echo("bash", "-lc", _inner(script)), clean_directory).is_read_only


@pytest.mark.parametrize(
    "command",
    [
        pytest.param('python3 -c "print(1)" # trailing comment', id="comment-after-script"),
        pytest.param('python3 -c "print(1)">out.txt', id="redirect-without-space"),
        pytest.param('python3 -c "print(1)" > out.txt', id="redirect-with-space"),
        pytest.param('python3 -c "print(1)" ; rm -rf x', id="second-command"),
        pytest.param('python3 -c "print(1)"|cat', id="pipe"),
        pytest.param('python3 -c "print(1)" && ls', id="and-list"),
        pytest.param("python3 -c 'print(1)' 2>&1", id="stderr-redirect"),
        pytest.param('python3 -c print(1)', id="unquoted-script"),
        pytest.param("python3   -c   'print(1)'", id="extra-spaces"),
        pytest.param("python3 -c 'print(1)\n", id="trailing-newline"),
        pytest.param("python3 -c 'unterminated", id="unbalanced-quote"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
    ],
)
def test_text_that_is_not_an_exact_argument_list_keeps_the_prompt(command, clean_directory):
    verdict = _verdict(command, clean_directory)
    assert not verdict.is_read_only
    assert verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(_echo("python3", "-c", "print(1)", "extra"), id="extra-argument"),
        pytest.param(_echo("python3", "-m", "json.tool"), id="module-mode"),
        pytest.param(_echo("python3", "script.py"), id="script-file"),
        pytest.param(_echo("python3", "-c", "print(1)", "-c", "print(2)"), id="two-scripts"),
        pytest.param(_echo("python3", "-W", "error", "-c", "print(1)"), id="warning-flag"),
        pytest.param(_echo("python3", "-X", "importtime", "-c", "print(1)"), id="x-option"),
        pytest.param(_echo("python3", "-i", "-c", "print(1)"), id="interactive-flag"),
        pytest.param(_echo("./python3", "-c", "print(1)"), id="workspace-python"),
        pytest.param(_echo("/tmp/venv/bin/python3", "-c", "print(1)"), id="other-absolute-python"),
        pytest.param(_echo("./bash", "-lc", _inner("print(1)")), id="workspace-shell"),
        pytest.param(_echo("env", "python3", "-c", "print(1)"), id="env-wrapper"),
        pytest.param(_echo("bash", "-c", "cd x && " + _inner("print(1)")), id="cd-then-python"),
        pytest.param(_echo("bash", "-c", _inner("print(1)") + " | cat"), id="piped-inside-shell"),
        pytest.param(_echo("bash", "-c", _inner("print(1)") + "; rm -rf x"), id="second-command-inside-shell"),
        pytest.param(_echo("bash", "-c", _inner("print(1)") + " > out.txt"), id="redirect-inside-shell"),
        pytest.param(_echo("bash", "-c", "PYTHONPATH=/tmp " + _inner("print(1)")), id="environment-prefix-inside-shell"),
        pytest.param(_echo("bash", "-c", _inner("print('$(id)')")), id="command-substitution-inside-shell"),
        pytest.param(_echo("bash", "-c", _inner("print('`id`')")), id="backtick-inside-shell"),
        pytest.param(_echo("bash", "-c", _inner("print('$HOME')")), id="variable-inside-shell"),
        pytest.param(_echo("bash", "-c", "python3 -c \"print('a\\\nb')\""), id="backslash-newline-inside-shell"),
        pytest.param(_echo("bash", "-c", "python3 -c 'print(1)'x"), id="text-glued-after-quote"),
        pytest.param(_echo("bash", "-c", "python3 -c 'print(1)' 'print(2)'"), id="second-word-inside-shell"),
        pytest.param(_echo("bash", "-c", "python3 -c \"print(1)\"*"), id="glob-glued-after-quote"),
        pytest.param(_echo("bash", "-x", "-c", _inner("print(1)")), id="shell-with-extra-flag"),
        pytest.param(_echo("bash", "-lc"), id="shell-without-script"),
        pytest.param(_echo("bash", "-lc", "ls"), id="shell-running-something-else"),
    ],
)
def test_other_command_shapes_keep_the_prompt(command, clean_directory):
    verdict = _verdict(command, clean_directory)
    assert not verdict.is_read_only
    assert verdict.reason


def test_a_script_that_could_write_keeps_the_prompt_in_both_shapes(clean_directory):
    script = "open('x', 'w').write('1')"
    assert not _verdict(_echo("python3", "-c", script), clean_directory).is_read_only
    assert not _verdict(_echo("bash", "-lc", _inner(script)), clean_directory).is_read_only


def test_environment_overrides_keep_the_prompt(clean_directory):
    command = _echo("python3", "-c", "print(1)")
    assert _verdict(command, clean_directory).is_read_only
    assert not _verdict(command, clean_directory, has_env_overrides=True).is_read_only


@pytest.mark.parametrize("shadow", ["json.py", "re.py", "enum.py", "sys.py", "json.cpython-312-darwin.so", "json.pyc"])
def test_a_working_directory_file_that_shadows_the_standard_library_keeps_the_prompt(shadow, tmp_path):
    (tmp_path / shadow).write_text("")
    command = _echo("python3", "-c", "import json;print(json.dumps(1))")
    verdict = _verdict(command, str(tmp_path))
    assert not verdict.is_read_only
    assert "working directory" in verdict.reason


def test_a_shadowing_package_keeps_the_prompt_but_a_plain_folder_does_not(tmp_path):
    command = _echo("python3", "-c", "print(1)")
    (tmp_path / "json").mkdir()
    assert _verdict(command, str(tmp_path)).is_read_only
    (tmp_path / "json" / "__init__.py").write_text("")
    assert not _verdict(command, str(tmp_path)).is_read_only


def test_files_that_cannot_shadow_the_standard_library_are_fine(tmp_path):
    for name in ["helper.py", "report.json", "notes.txt", "data.csv", "json_export.py"]:
        (tmp_path / name).write_text("")
    assert _verdict(_echo("python3", "-c", "print(1)"), str(tmp_path)).is_read_only


def test_the_isolated_flag_makes_the_working_directory_irrelevant(tmp_path):
    (tmp_path / "json.py").write_text("")
    assert _verdict(_echo("python3", "-I", "-c", "print(1)"), str(tmp_path)).is_read_only
    assert _verdict(_echo("python3", "-I", "-c", "print(1)"), None).is_read_only


@pytest.mark.parametrize("directory", [None, "", "/nonexistent/folder/for/this/test"])
def test_an_unknown_working_directory_keeps_the_prompt_without_the_isolated_flag(directory):
    verdict = _verdict(_echo("python3", "-c", "print(1)"), directory)
    assert not verdict.is_read_only
    assert "working directory" in verdict.reason


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize(
    "script",
    [
        "print('a' + \"b\")",
        "print('a\\nb')",
        "print('back\\\\slash')",
        "print('tab\\there')",
        "print(\"quote: \\\" done\")",
        "x = {'k': \"v\"}\nprint(x['k'])",
        "print('percent % and ! bang')",
        "print('x'); print('y')",
    ],
)
def test_the_quote_rules_applied_by_hand_match_what_bash_does(script):
    """The classifier judges the script it computes from the shell's quoting; this proves that text is the one bash hands to Python."""
    body = _double_quoted(script)[1:-1]
    printed = subprocess.run(["bash", "-c", f'printf %s "{body}"'], capture_output=True, text=True, check=True).stdout
    assert _unescape_double_quoted(body) == printed == script
