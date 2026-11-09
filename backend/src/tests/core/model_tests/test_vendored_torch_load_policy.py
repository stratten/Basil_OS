"""Vendored checkpoint loaders must state weights_only explicitly.

Torch 2.6 changed the default of ``weights_only`` to True, which makes pyannote
and diart checkpoints fail to load and sends the loaders into their dummy-model
fallbacks. These call sites therefore pass ``weights_only=False`` on purpose.
"""

import ast
from pathlib import Path

import api

VENDOR_ROOT = Path(api.__file__).resolve().parent / "vendor"

LOADER_FILES = [
    VENDOR_ROOT / "pyannote" / "audio" / "core" / "model.py",
    VENDOR_ROOT / "diart" / "diart-main" / "src" / "diart" / "models.py",
]


def _torch_load_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "load"
            and isinstance(func.value, ast.Name)
            and func.value.id == "torch"
        ):
            yield node


def test_loader_files_exist():
    for path in LOADER_FILES:
        assert path.is_file(), path


def test_every_torch_load_call_sets_weights_only_false():
    total_calls = 0
    for path in LOADER_FILES:
        for call in _torch_load_calls(path):
            total_calls += 1
            keywords = {kw.arg: kw.value for kw in call.keywords}
            assert "weights_only" in keywords, f"{path.name}:{call.lineno} omits weights_only"
            value = keywords["weights_only"]
            assert isinstance(value, ast.Constant) and value.value is False, (
                f"{path.name}:{call.lineno} must pass weights_only=False"
            )
    assert total_calls == 3
