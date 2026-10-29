"""The finalizer evaluator must see the whole delivered response and must not invent a numbered-item shortfall."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.core.models.base_model import ModelCapability, ModelMetadata
from api.services.agent_processing.lifecycle.finalization.evaluation import (
    MAX_DELIVERED_RESPONSE_CHARS,
    _resolve_max_output_chars,
    build_evaluation_prompt,
)
from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import _detect_explicit_numbered_coverage


def _metadata(*, parameters=None, context_window=None) -> ModelMetadata:
    fields = {
        "name": "model",
        "version": "1",
        "source": "test",
        "capabilities": {ModelCapability.REASONING},
        "description": "test model",
        "parameters": parameters or {},
        "requirements": {},
        "memory_requirements": "0MB",
    }
    if context_window is not None:
        fields["context_window"] = context_window
    return ModelMetadata(**fields)


class _ModelWithoutContextField:
    """Shaped like the Claude and OpenAI models: a window attribute and metadata that leaves `context_window` at its default."""

    def __init__(self, max_context_length=None, parameters=None):
        if max_context_length is not None:
            self.max_context_length = max_context_length
        self._parameters = parameters or {}

    def get_metadata(self):
        return _metadata(parameters=self._parameters)


# --- how much of the response the evaluator is given ---------------------------------------------


def test_a_model_that_leaves_the_metadata_window_at_its_default_is_not_capped_at_three_thousand_characters():
    assert _metadata().context_window == 2048

    assert _resolve_max_output_chars(_ModelWithoutContextField(max_context_length=200000)) == MAX_DELIVERED_RESPONSE_CHARS


def test_the_window_listed_in_the_metadata_parameters_is_used_when_the_model_has_no_attribute():
    model = _ModelWithoutContextField(parameters={"context_window": 200000})

    assert _resolve_max_output_chars(model) == MAX_DELIVERED_RESPONSE_CHARS


def test_a_small_real_window_still_limits_the_response_shown():
    assert _resolve_max_output_chars(_ModelWithoutContextField(max_context_length=8000)) == 12000


def test_the_metadata_field_is_the_last_resort():
    model = SimpleNamespace(get_metadata=lambda: _metadata(context_window=8000))

    assert _resolve_max_output_chars(model) == 12000


def test_a_model_that_reports_nothing_gets_the_full_allowance():
    assert _resolve_max_output_chars(SimpleNamespace()) == MAX_DELIVERED_RESPONSE_CHARS


def test_a_model_whose_metadata_fails_still_gets_the_full_allowance():
    def broken():
        raise RuntimeError("metadata unavailable")

    assert _resolve_max_output_chars(SimpleNamespace(get_metadata=broken)) == MAX_DELIVERED_RESPONSE_CHARS


def test_the_floor_keeps_a_tiny_window_from_hiding_the_response():
    assert _resolve_max_output_chars(_ModelWithoutContextField(max_context_length=100)) == 2000


def _prompt(output: str, max_output_chars: int) -> str:
    return build_evaluation_prompt(
        original_prompt="Review my five most recent emails.",
        self_assessment=None,
        full_agent_output=output,
        max_output_chars=max_output_chars,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )


def test_a_response_that_fits_is_given_whole_with_no_clip_notice():
    prompt = _prompt("The whole response.", 5000)

    assert "The whole response." in prompt
    assert "NOT PART OF THE RESPONSE" not in prompt


def test_a_clipped_response_is_labeled_so_the_cut_is_not_read_as_the_response_ending():
    output = "A" * 300 + "Also ch" + "B" * 700

    prompt = _prompt(output, 307)

    assert "Also ch" in prompt
    assert "B" * 10 not in prompt
    assert "continues for 700 more characters" in prompt
    assert "do not judge the response as ending mid-sentence" in prompt


# --- the numbered-item count check -----------------------------------------------------------------

BOLD_RESPONSE = "\n".join(f"**{number}. Email {number}**\n- **Action:** Do it." for number in range(1, 6))


def test_a_reference_to_one_numbered_email_is_not_a_request_for_that_many_items():
    prompt = "Redeliver the full review. Finish email 4's Reason line. Add the missing email 5 section with a brief summary."

    assert _detect_explicit_numbered_coverage(prompt, BOLD_RESPONSE) == (None, 0)


@pytest.mark.parametrize(
    "prompt",
    [
        "Add the missing item 3 draft.",
        "Fix section 2 sections of the report.",
        "Rewrite number 4 emails again.",
        "Check #5 items please.",
    ],
)
def test_other_position_references_are_not_counts(prompt):
    assert _detect_explicit_numbered_coverage(prompt, "") == (None, 0)


def test_a_real_count_is_still_detected_and_counted_from_plain_headings():
    content = "1. First\n2. Second\n3. Third\n"

    assert _detect_explicit_numbered_coverage("Write 3 emails for the launch.", content) == (3, 3)


def test_a_real_count_is_still_incomplete_when_items_are_missing():
    assert _detect_explicit_numbered_coverage("Write all 5 drafts.", "1. First\n2. Second\n") == (5, 2)


def test_a_count_after_an_earlier_position_reference_is_still_found():
    prompt = "Fix email 2 and then write 4 sections."

    assert _detect_explicit_numbered_coverage(prompt, "") == (4, 0)


def test_items_set_in_bold_are_counted():
    assert _detect_explicit_numbered_coverage("Draft 5 emails.", BOLD_RESPONSE) == (5, 5)


def test_items_in_markdown_headings_and_bold_headings_are_counted():
    assert _detect_explicit_numbered_coverage("Draft 2 emails.", "## 1. One\n## **2. Two**\n") == (2, 2)


def test_list_entries_with_bold_numbers_are_counted():
    assert _detect_explicit_numbered_coverage("Draft 2 emails.", "- **1. One**\n- **2. Two**\n") == (2, 2)


def test_numbers_in_prose_are_not_counted_as_items():
    assert _detect_explicit_numbered_coverage("Draft 3 emails.", "I wrote 1. a note and 2. another inline.\n") == (3, 0)


def test_a_prompt_without_a_count_is_not_checked():
    assert _detect_explicit_numbered_coverage("Review my five most recent emails.", BOLD_RESPONSE) == (None, 0)
