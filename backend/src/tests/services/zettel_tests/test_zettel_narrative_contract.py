"""Contract tests for the narrative JSON body.

Fixtures are abridged from real rows in the live zettel table, so these assert
against observed model behavior rather than imagined behavior. The reply must
carry a JSON body matching NarrativePayload; reasoning around it is discarded
and a reply without a conforming body fails the entry.
"""

import pytest

from api.services.zettel.narrative.synthesizer import (
    NarrativePayload,
    SynthesisError,
    _extract_payload,
    _model_label,
    _parse,
)

# Real shape: a valid object, then chain-of-thought, then a second object. The
# old greedy \{.*\} spanned first-brace to last-brace and failed to decode.
JSON_THEN_REASONING = (
    '{"narrative": "You emphasized the importance of carefully examining '
    'references and dependencies to avoid errors.", "is_open": false, '
    '"open_note": null}\n'
    "Okay, let me tackle this query step by step. The user wants a JSON "
    "object summarizing a transcription from their activity log.\n\n"
    'Final answer: {"narrative": "something else", "is_open": false}'
)

# Real shape: pure reasoning, no JSON anywhere.
REASONING_ONLY = (
    "Okay, let me tackle this. The user wants a summary of the transcription "
    "item. The header says it's a completed task with status succeeded.\n\n"
    "So the narrative should explain that the user is asking if the original "
    "format can be kept. But wait, does the transcription indicate any "
    "ongoing tasks?"
)

CLEAN_JSON = (
    '{"narrative": "You tested saving a file in Sublime Text using Whisper '
    'transcription, confirming the text saved as intended.", '
    '"is_open": false, "open_note": null}'
)


def test_extracts_first_object_despite_trailing_reasoning():
    payload = _extract_payload(JSON_THEN_REASONING)
    assert payload is not None
    assert payload["narrative"].startswith("You emphasized the importance")
    assert "Okay, let me" not in payload["narrative"]


def test_parse_recovers_narrative_from_contaminated_reply():
    result = _parse(JSON_THEN_REASONING, "Qwen-qwen3-8b-instruct-q4km")
    assert result.narrative.startswith("You emphasized the importance")
    assert result.model_name == "Qwen-qwen3-8b-instruct-q4km"


def test_parse_clean_json():
    result = _parse(CLEAN_JSON, "m")
    assert result.narrative.startswith("You tested saving a file")


def test_parse_raises_rather_than_persisting_reasoning():
    with pytest.raises(SynthesisError):
        _parse(REASONING_ONLY, "m")


def test_parse_raises_when_narrative_key_missing():
    with pytest.raises(SynthesisError):
        _parse('{"is_open": false, "open_note": null}', "m")


def test_parse_raises_when_narrative_is_blank():
    with pytest.raises(SynthesisError):
        _parse('{"narrative": "   ", "is_open": false}', "m")


def test_markdown_fenced_object_parses():
    raw = (
        "```json\n"
        '{"narrative": "You archived three stale branches.", "is_open": false}\n'
        "```"
    )
    result = _parse(raw, "m")
    assert result.narrative == "You archived three stale branches."


def test_legacy_lifecycle_fields_are_ignored():
    raw = (
        '{"narrative": "You started a migration.", "is_open": true, '
        '"open_note": "  Two tables remain.  "}'
    )
    result = _parse(raw, "m")
    assert result.narrative == "You started a migration."


def test_unicode_prose_survives_extraction():
    """Guards the decision not to route this through robust_json_loads.

    That helper strips characters outside ASCII 32-126, which turns
    "30-40" written with an en dash into "3040" - silent data corruption.
    """
    raw = (
        "Okay, let me think.\n\n"
        '{"narrative": "You reviewed Ben\u2019s draft \u2014 a 30\u201340 page '
        'brief \u2014 and flagged \u00e9lan issues.", "is_open": false}'
    )
    result = _parse(raw, "m")
    assert "Ben\u2019s" in result.narrative
    assert "\u2014" in result.narrative
    assert "30\u201340" in result.narrative
    assert "\u00e9lan" in result.narrative


def test_non_dict_json_is_rejected():
    with pytest.raises(SynthesisError):
        _parse('["not", "an", "object"]', "m")


def test_model_label_prefers_model_name():
    class _Named:
        model_name = "canonical-id"
        name = "other"

    assert _model_label(_Named()) == "canonical-id"


def test_model_label_falls_back_to_name():
    class _OnlyName:
        name = "fallback-name"

    assert _model_label(_OnlyName()) == "fallback-name"


def test_model_label_falls_back_to_class_name():
    """LlamaCppModel exposes neither attribute, which is why the column was NULL."""

    class LlamaCppModel:
        pass

    assert _model_label(LlamaCppModel()) == "LlamaCppModel"


def test_payload_defaults_are_safe():
    payload = NarrativePayload()
    assert payload.narrative == ""
