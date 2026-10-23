"""Incremental parser for completed elements of the root ``items`` array."""

import json

from api.services.whisper_live_core.post_processing.meeting_analysis_item_stream import (
    IncrementalItemsParser,
)

_PAYLOAD = {
    "items": [
        {"task": "Send {the} budget", "context": 'He said "go" [now]', "timestamp": 1, "tags": ["a", {"b": [1, 2]}]},
        {"task": "Café ☕ plan", "context": "back\\slash \\\" quote", "timestamp": 2},
    ]
}


def _feed_in_pieces(text: str, size: int):
    parser = IncrementalItemsParser()
    emitted = []
    for start in range(0, len(text), size):
        emitted.extend(parser.feed(text[start : start + size]))
    return emitted


def test_one_shot_feed_emits_each_element_as_valid_json():
    text = json.dumps(_PAYLOAD)

    emitted = IncrementalItemsParser().feed(text)

    assert [json.loads(element) for element in emitted] == _PAYLOAD["items"]


def test_any_split_point_produces_the_same_elements():
    text = json.dumps(_PAYLOAD)
    expected = IncrementalItemsParser().feed(text)

    for size in (1, 2, 3, 7, 13, 50):
        assert _feed_in_pieces(text, size) == expected


def test_elements_are_emitted_as_soon_as_they_close_not_at_the_end():
    text = json.dumps(_PAYLOAD)
    first_end = text.index('"timestamp": 1') + len('"timestamp": 1, "tags": ["a", {"b": [1, 2]}]}')
    parser = IncrementalItemsParser()

    early = parser.feed(text[:first_end])
    late = parser.feed(text[first_end:])

    assert len(early) == 1
    assert len(late) == 1


def test_a_truncated_stream_emits_only_closed_elements():
    text = json.dumps(_PAYLOAD)
    truncated = text[: text.rindex('"timestamp"')]

    emitted = IncrementalItemsParser().feed(truncated)

    assert len(emitted) == 1
    assert json.loads(emitted[0])["timestamp"] == 1


def test_only_the_items_array_is_read():
    text = json.dumps(
        {
            "other": [{"x": 1}],
            "items": [{"task": "real"}],
            "after": [{"y": 2}],
            "meta": {"items": [{"task": "nested decoy"}]},
        }
    )

    emitted = IncrementalItemsParser().feed(text)

    assert [json.loads(element) for element in emitted] == [{"task": "real"}]


def test_missing_or_empty_items_emit_nothing():
    assert IncrementalItemsParser().feed('{"markdown": "text"}') == []
    assert IncrementalItemsParser().feed('{"items": []}') == []
    assert IncrementalItemsParser().feed("") == []
    assert IncrementalItemsParser().feed("not json at all") == []


def test_a_string_value_equal_to_items_does_not_open_the_array():
    text = '{"note": "items", "other": [{"x": 1}]}'

    assert IncrementalItemsParser().feed(text) == []


def test_non_object_elements_are_ignored_and_parsing_continues():
    text = '{"items": ["loose", {"task": "kept"}, 5]}'

    emitted = IncrementalItemsParser().feed(text)

    assert [json.loads(element) for element in emitted] == [{"task": "kept"}]


def test_escape_sequences_split_across_deltas_do_not_confuse_the_parser():
    text = '{"items": [{"task": "a \\" b } c"}]}'

    emitted = _feed_in_pieces(text, 1)

    assert [json.loads(element) for element in emitted] == [{"task": 'a " b } c'}]
