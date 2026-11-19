"""The outline shows what a large stored result contains, and paths read one part of it."""

import json

import pytest

from api.services.agent_processing.tools.internal_basil_tools.stored_result.shape import (
    PathError,
    describe_node,
    outline_text,
    parse_path,
    resolve_path,
    select_node,
)


def _request_document(steps: int = 300) -> dict:
    return {
        "ok": True,
        "result": {
            "structured": {
                "request": {
                    "requestNumber": "REQ-2026-0677",
                    "status": "completed",
                    "investigation": {"steps": [{"stepNumber": number, "command": f"cmd {number}", "result": {"stdout": "o" * 5_000}} for number in range(steps)]},
                },
                "latestRun": {"runNumber": 3},
            }
        },
    }


def test_paths_split_into_keys_and_array_positions():
    assert parse_path("a[1].b") == ["a", 1, "b"]
    assert parse_path("a..b[0]") == ["a", "b", 0]
    assert parse_path("") == []
    assert parse_path(None) == []
    assert parse_path("  result.items[2]  ") == ["result", "items", 2]


@pytest.mark.parametrize("bad", ["a]", "a[x]", "[", "a[1"])
def test_a_malformed_path_is_refused_with_an_example(bad):
    with pytest.raises(PathError) as raised:
        parse_path(bad)
    assert "such as" in str(raised.value)


def test_the_outline_of_the_whole_result_points_at_the_large_part():
    raw = json.dumps(_request_document())

    outline = outline_text(raw)

    assert outline["type"] == "object"
    assert outline["largest"][0]["key"] == "result"
    deeper = outline_text(raw, "result.structured.request")
    assert deeper["largest"][0]["key"] == "investigation"
    assert deeper["path"] == "result.structured.request"


def test_the_outline_of_an_array_reports_length_item_keys_and_the_largest_items():
    raw = json.dumps(_request_document(steps=300))

    outline = outline_text(raw, "result.structured.request.investigation.steps")

    assert outline["type"] == "array"
    assert outline["length"] == 300
    assert outline["first_item_keys"] == ["stepNumber", "command", "result"]
    assert outline["item_types"] == ["object"]
    assert len(outline["largest_items"]) == 10


def test_a_path_reads_one_item():
    raw = json.dumps(_request_document())

    assert select_node(raw, "result.structured.request.investigation.steps[3].command") == "cmd 3"
    assert select_node(raw, "") == json.loads(raw)


def test_a_missing_key_lists_the_keys_that_exist():
    data = {"a": 1, "b": 2}

    with pytest.raises(PathError) as raised:
        resolve_path(data, parse_path("c"))

    assert "no key 'c'" in str(raised.value)
    assert "a, b" in str(raised.value)


def test_array_mistakes_are_explained():
    data = {"items": [1, 2], "name": "x"}

    with pytest.raises(PathError, match="2 items, so \\[5\\] does not exist"):
        resolve_path(data, parse_path("items[5]"))
    with pytest.raises(PathError, match="array of 2 items; use \\[n\\]"):
        resolve_path(data, parse_path("items.first"))
    with pytest.raises(PathError, match="is not an array"):
        resolve_path(data, parse_path("name[0]"))
    with pytest.raises(PathError, match="single value"):
        resolve_path(data, parse_path("name.first"))


def test_a_plain_text_result_has_no_paths_but_can_be_outlined_and_read_whole():
    text = "line one\nline two\nline three"

    assert select_node(text, "") == text
    assert outline_text(text) == {"type": "string", "chars": len(text), "lines": 3, "path": ""}
    with pytest.raises(PathError, match="plain text"):
        select_node(text, "a.b")


def test_the_outline_stays_small_for_a_huge_object():
    node = {f"key{number}": "v" * (number + 1) for number in range(500)}

    outline = describe_node(node)

    assert len(outline["largest"]) == 40
    assert outline["omitted_keys"] == 460
    assert outline["largest"][0]["key"] == "key499"
    assert len(json.dumps(outline)) < 6_000


def test_scalars_and_empty_containers_are_described():
    assert describe_node(None) == {"type": "null", "value": None}
    assert describe_node(True) == {"type": "boolean", "value": True}
    assert describe_node(7)["type"] == "number"
    assert describe_node([])["length"] == 0
    assert describe_node({})["keys"] == 0
