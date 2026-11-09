"""The progress text shown while a local model reads its prompt."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import reading_prompt_message


@pytest.mark.parametrize(
    ("prompt_tokens", "phase_seconds", "expected"),
    [
        (None, None, "Local model is reading the prompt…"),
        (0, 0.4, "Local model is reading the prompt…"),
        (62_400, 194.0, "Local model is reading the prompt (about 62k tokens, 3m 14s so far)…"),
        (850, 12.0, "Local model is reading the prompt (about 850 tokens, 12s so far)…"),
        (None, 65.0, "Local model is reading the prompt (1m 05s so far)…"),
        (4_000, 0.5, "Local model is reading the prompt (about 4k tokens)…"),
    ],
)
def test_reading_prompt_message(prompt_tokens, phase_seconds, expected):
    assert reading_prompt_message(prompt_tokens, phase_seconds) == expected
