"""Tests for the proof that a Python script only reads data."""

from __future__ import annotations

import pytest

from api.services.agent_processing.tools.safety.python_read_only_classifier import (
    MAX_SCRIPT_CHARACTERS,
    classify_python_read_only,
)

READ_ONLY_SCRIPTS = [
    pytest.param("print(1 + 2)", id="arithmetic"),
    pytest.param("import json;d=json.load(open('.tool_results/r-1.txt'));print(d['status'])", id="json-load-open-literal-path"),
    pytest.param("import json\nwith open('a.json') as f:\n    d = json.load(f)\nfor k, v in d.items():\n    print(k, v)", id="with-open-for-loop"),
    pytest.param("import json;d=json.load(open('a.json'));[print(r['id'], (r.get('x') or {}).get('m', '')[:10]) for r in d]", id="list-comprehension-with-get"),
    pytest.param("import re;print(re.findall(r'\\d+', open('a.txt', 'r').read()))", id="re-findall-on-read"),
    pytest.param("import sys;print(sys.argv[1:])", id="sys-argv"),
    pytest.param("import sys;sys.stdout.write('hello\\n')", id="stdout-write"),
    pytest.param("from collections import Counter;print(Counter('abca').most_common(2))", id="counter"),
    pytest.param("import math;print(math.floor(2.5) + math.sqrt(16))", id="math"),
    pytest.param("import json as j;print(j.dumps({'a': [1, 2]}, indent=2))", id="aliased-import"),
    pytest.param("rows = [l.strip().split(',') for l in open('a.csv', encoding='utf-8')]\nprint(len(rows))", id="open-with-encoding-keyword"),
    pytest.param("x = {}\nx['a'] = 1\nx['a'] += 1\nprint(f'{x[\"a\"]:>4}')", id="local-dict-update-and-fstring"),
    pytest.param("print(sorted({'b': 2, 'a': 1}.items(), key=len, reverse=True))", id="sorted-with-keywords"),
    pytest.param("print(open('a.txt', mode='rb').read()[:4])", id="open-mode-keyword"),
]

NOT_READ_ONLY_SCRIPTS = [
    pytest.param("open('x', 'w').write('1')", id="open-write-mode"),
    pytest.param("open('x', 'a')", id="open-append-mode"),
    pytest.param("open('x', 'r+')", id="open-read-write-mode"),
    pytest.param("m = 'w'\nopen('x', m)", id="open-mode-from-variable"),
    pytest.param("open('x', 'r', 0)", id="open-with-buffering-positional"),
    pytest.param("open('x', opener=None)", id="open-with-opener"),
    pytest.param("o = open\no('x', 'w')", id="open-aliased-before-call"),
    pytest.param("print(open)", id="open-passed-around"),
    pytest.param("open = print", id="open-rebound"),
    pytest.param("import os\nos.remove('x')", id="import-os"),
    pytest.param("import subprocess", id="import-subprocess"),
    pytest.param("import shutil", id="import-shutil"),
    pytest.param("import socket", id="import-socket"),
    pytest.param("import urllib.request", id="import-urllib"),
    pytest.param("import pathlib;pathlib.Path('x').write_text('1')", id="import-pathlib"),
    pytest.param("from os import system", id="from-import-os"),
    pytest.param("from json import *", id="star-import"),
    pytest.param("from json import tool", id="from-import-unlisted-name"),
    pytest.param("from . import json", id="relative-import"),
    pytest.param("__import__('os').system('ls')", id="dunder-import"),
    pytest.param("exec('print(1)')", id="exec"),
    pytest.param("eval('1')", id="eval"),
    pytest.param("compile('1', 'f', 'eval')", id="compile"),
    pytest.param("getattr(__builtins__, 'open')", id="getattr"),
    pytest.param("globals()", id="globals"),
    pytest.param("vars()", id="vars"),
    pytest.param("input()", id="input"),
    pytest.param("breakpoint()", id="breakpoint"),
    pytest.param("().__class__.__mro__", id="dunder-attribute-chain"),
    pytest.param("print(''.__class__)", id="dunder-attribute"),
    pytest.param("x = 1\nx.__dict__", id="dunder-dict"),
    pytest.param("__builtins__", id="dunder-name"),
    pytest.param("import sys;sys.modules['os'].system('ls')", id="sys-modules"),
    pytest.param("import sys;sys.path.append('/tmp')", id="sys-path"),
    pytest.param("import sys;sys.stdout = None", id="assign-to-module-attribute"),
    pytest.param("import json;json.x = 1", id="assign-to-module-attribute-json"),
    pytest.param("import json\njson = 1", id="reuse-of-module-name"),
    pytest.param("import json\nfor json in []:\n    pass", id="module-name-as-loop-variable"),
    pytest.param("import json as j\nimport re as j", id="one-name-two-modules"),
    pytest.param("f = lambda: 1", id="lambda"),
    pytest.param("def f():\n    pass", id="function-definition"),
    pytest.param("class A:\n    pass", id="class-definition"),
    pytest.param("try:\n    pass\nexcept Exception:\n    pass", id="try-except"),
    pytest.param("while True:\n    pass", id="while-loop"),
    pytest.param("raise SystemExit", id="raise"),
    pytest.param("global x", id="global"),
    pytest.param("x = 1\ndel x", id="delete"),
    pytest.param("(x := 1)", id="walrus"),
    pytest.param("print(2 ** 10)", id="power"),
    pytest.param("print(1 << 40)", id="shift"),
    pytest.param("print(10 ** 9)", id="power-large"),
    pytest.param("print('a' * 5000000)", id="large-number-literal"),
    pytest.param("print(''.format(1))", id="format-method"),
    pytest.param("print(f(1))", id="undefined-function"),
    pytest.param("print(**{'sep': ''})", id="double-star-keyword"),
    pytest.param("(print)(1)(2)", id="call-of-call-result"),
    pytest.param("import json;json.load(open('a'))('x')", id="call-of-json-result"),
    pytest.param("x = [1]\nx.sort.__call__()", id="dunder-call"),
    pytest.param("import re;re.compile('a').scanner('x')", id="unlisted-method"),
    pytest.param("import re;re.purge()", id="unlisted-module-function"),
    pytest.param("import sys;sys.stdin.fileno()", id="unlisted-stream-method"),
    pytest.param("async def f():\n    pass", id="async-def"),
    pytest.param("print(1)\nyield 1", id="yield"),
    pytest.param("match 1:\n    case 1:\n        pass", id="match-statement"),
]


@pytest.mark.parametrize("script", READ_ONLY_SCRIPTS)
def test_read_only_scripts_are_recognized(script):
    verdict = classify_python_read_only(script)
    assert verdict.is_read_only, verdict.reason


@pytest.mark.parametrize("script", NOT_READ_ONLY_SCRIPTS)
def test_scripts_that_could_change_something_keep_the_prompt(script):
    verdict = classify_python_read_only(script)
    assert not verdict.is_read_only
    assert verdict.reason


@pytest.mark.parametrize(
    "script",
    [
        pytest.param("", id="empty"),
        pytest.param("   \n  ", id="blank"),
        pytest.param("print(", id="syntax-error"),
        pytest.param("print(1)\x00", id="null-byte"),
        pytest.param("x = " + "(" * 3000 + "1" + ")" * 3000, id="deeply-nested"),
        pytest.param("print(1)\n" * (MAX_SCRIPT_CHARACTERS // 8 + 10), id="too-long"),
    ],
)
def test_empty_malformed_or_oversized_scripts_keep_the_prompt(script):
    verdict = classify_python_read_only(script)
    assert not verdict.is_read_only
    assert verdict.reason


def test_non_string_input_keeps_the_prompt():
    assert not classify_python_read_only(None).is_read_only  # type: ignore[arg-type]
    assert not classify_python_read_only(b"print(1)").is_read_only  # type: ignore[arg-type]


def test_a_comment_cannot_hide_code_that_the_classifier_sees():
    verdict = classify_python_read_only("print(1)  # harmless\nimport os\nos.system('ls')")
    assert not verdict.is_read_only
    assert "os" in verdict.reason


def test_the_reason_names_the_first_problem():
    verdict = classify_python_read_only("import json\nopen('x', 'w')")
    assert not verdict.is_read_only
    assert "mode other than reading" in verdict.reason
