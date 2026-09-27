"""Unit coverage for the shared model-JSON-decision parser (agent_json_decision.py).

Both skill selection and the fast-lane intent gate depend on
``parse_json_object_response`` raising (never returning a non-dict) on any
malformed model output, so their ``except (TypeError, json.JSONDecodeError)``
fallback paths are guaranteed to catch every failure mode instead of a bare
non-dict payload reaching a downstream ``.get(...)`` call as an unhandled
AttributeError.
"""

from __future__ import annotations

import json

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_json_decision import (
    parse_json_object_response,
)


def test_parses_plain_json_object():
    payload = parse_json_object_response('{"slug": "x", "reason": "y"}')
    assert payload == {"slug": "x", "reason": "y"}


def test_parses_fenced_json_object():
    payload = parse_json_object_response('```json\n{"slug": "x"}\n```')
    assert payload == {"slug": "x"}


def test_parses_json_object_embedded_in_prose():
    payload = parse_json_object_response('Sure, here it is: {"slug": "x"} -- hope that helps!')
    assert payload == {"slug": "x"}


@pytest.mark.parametrize(
    "response_text",
    [
        "null",
        "true",
        '"just a string"',
        "42",
        "[1, 2, 3]",
        '[{"slug": "x"}]',
    ],
)
def test_rejects_syntactically_valid_json_that_is_not_an_object(response_text):
    """A model can emit valid JSON that isn't an object; callers' fallback
    paths depend on this raising rather than returning the non-dict value."""
    with pytest.raises(json.JSONDecodeError):
        parse_json_object_response(response_text)


def test_rejects_empty_response():
    with pytest.raises(json.JSONDecodeError):
        parse_json_object_response("")


def test_rejects_none_response():
    with pytest.raises(json.JSONDecodeError):
        parse_json_object_response(None)


def test_rejects_prose_with_no_json_object_at_all():
    with pytest.raises(json.JSONDecodeError):
        parse_json_object_response("not json at all")
