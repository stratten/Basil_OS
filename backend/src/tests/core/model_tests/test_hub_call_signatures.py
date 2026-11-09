"""Every keyword Basil passes to the Hugging Face Hub download functions must be a real parameter of the installed version."""

import ast
import inspect
from pathlib import Path

import huggingface_hub
import pytest

import api

API_ROOT = Path(api.__file__).resolve().parent
VENDOR_ROOT = API_ROOT / "vendor"
HUB_FUNCTIONS = ("snapshot_download", "hf_hub_download")
DEPRECATED_KEYWORDS = {"resume_download", "local_dir_use_symlinks", "use_auth_token"}


def _called_hub_function(call: ast.Call):
    func = call.func
    if isinstance(func, ast.Name) and func.id in HUB_FUNCTIONS:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in HUB_FUNCTIONS:
        return func.attr
    return None


def _hub_calls():
    for path in sorted(API_ROOT.rglob("*.py")):
        if VENDOR_ROOT in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _called_hub_function(node)
                if name is not None:
                    yield path, node, name


def test_basil_calls_hub_download_functions_somewhere():
    assert len(list(_hub_calls())) >= 5


@pytest.mark.parametrize("function_name", HUB_FUNCTIONS)
def test_installed_hub_exposes_the_function(function_name):
    assert callable(getattr(huggingface_hub, function_name))


def test_every_keyword_is_a_real_parameter_and_none_is_deprecated():
    problems = []
    for path, call, name in _hub_calls():
        parameters = inspect.signature(getattr(huggingface_hub, name)).parameters
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            if keyword.arg in DEPRECATED_KEYWORDS:
                problems.append(f"{path.name}:{call.lineno} {name}({keyword.arg}=...) is deprecated")
            elif keyword.arg not in parameters:
                problems.append(f"{path.name}:{call.lineno} {name}({keyword.arg}=...) is not a parameter")
    assert not problems, "\n".join(problems)
