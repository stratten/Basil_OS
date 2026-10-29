"""Tests for the shared JSON and atomic text helpers."""

import json
import os
from pathlib import Path

import pytest

from api.core import atomic_text
from api.core.atomic_text import atomic_write_text
from api.core.json_helpers import (
    canonical_json,
    json_loads_or_empty,
    load_json_array,
    load_json_object,
)


class SampleError(RuntimeError):
    """Stand-in for a repository persistence error."""


# ---- json_loads_or_empty ----

@pytest.mark.parametrize("value", [None, "", "not json", "{", "[1, 2"])
def test_json_loads_or_empty_returns_empty_mapping_for_missing_or_malformed_input(value) -> None:
    assert json_loads_or_empty(value) == {}


def test_json_loads_or_empty_returns_parsed_value_unchanged() -> None:
    assert json_loads_or_empty('{"a": [1, 2]}') == {"a": [1, 2]}
    assert json_loads_or_empty("[1, 2]") == [1, 2]
    assert json_loads_or_empty("0") == 0


# ---- canonical_json ----

def test_canonical_json_sorts_keys_and_is_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == '{"a":[1,{"c":3,"d":2}],"b":1}'


def test_canonical_json_keeps_non_ascii_text_unescaped() -> None:
    assert canonical_json({"name": "caf\u00e9 \u2603"}) == '{"name":"caf\u00e9 \u2603"}'


# ---- load_json_array / load_json_object ----

@pytest.mark.parametrize("loader", [load_json_array, load_json_object])
def test_loaders_report_a_missing_value_with_the_callers_error_type(loader) -> None:
    for raw in (None, 5, b"[]"):
        with pytest.raises(SampleError, match="things is missing"):
            loader(raw, "things", SampleError)


@pytest.mark.parametrize("loader", [load_json_array, load_json_object])
def test_loaders_chain_the_parse_failure_as_the_cause(loader) -> None:
    with pytest.raises(SampleError, match="things contains invalid JSON") as caught:
        loader("{not json", "things", SampleError)
    assert isinstance(caught.value.__cause__, json.JSONDecodeError)


def test_load_json_array_accepts_arrays_only() -> None:
    assert load_json_array("[1, 2]", "things", SampleError) == [1, 2]
    with pytest.raises(SampleError, match="things must contain a JSON array"):
        load_json_array('{"a": 1}', "things", SampleError)


def test_load_json_object_accepts_objects_only_and_returns_a_dict() -> None:
    assert load_json_object('{"a": 1}', "things", SampleError) == {"a": 1}
    with pytest.raises(SampleError, match="things must contain a JSON object"):
        load_json_object("[1]", "things", SampleError)


# ---- atomic_write_text ----

def test_atomic_write_text_writes_utf8_content_and_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "memory.md"
    atomic_write_text(target, "caf\u00e9 \u2603\n")
    assert target.read_text(encoding="utf-8") == "caf\u00e9 \u2603\n"


def test_atomic_write_text_replaces_prior_content_and_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "memory.md"
    atomic_write_text(target, "old")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["memory.md"]


def test_atomic_write_text_preserves_prior_file_when_the_replace_fails(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "memory.md"
    atomic_write_text(target, "good")

    def failing_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(atomic_text.os, "replace", failing_replace)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "partial")
    monkeypatch.setattr(atomic_text.os, "replace", os.replace)

    assert target.read_text(encoding="utf-8") == "good"
    assert [p.name for p in tmp_path.iterdir()] == ["memory.md"]
