"""Each model failure kind must be classified so it gets the recovery that fits it."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    LocalModelContextWindowExceeded,
)
from api.services.agent_processing.lifecycle.execution_graph.model_error_policy import (
    CONTEXT_OVERFLOW,
    EMPTY_GENERATION,
    FATAL,
    TRANSIENT,
    TRANSIENT_EXHAUSTED,
    classify_model_error,
    overflow_chars_to_remove,
    overflow_token_summary,
)
from api.services.agent_processing.lifecycle.execution_graph.model_errors import TransientModelError


def test_local_overflow_keeps_exact_token_counts():
    classification = classify_model_error(LocalModelContextWindowExceeded(actual_tokens=40000, max_tokens=32768))
    assert (classification.kind, classification.actual_tokens, classification.max_tokens) == (CONTEXT_OVERFLOW, 40000, 32768)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("prompt is too long: 203619 tokens > 200000 maximum"), (203619, 200000)),
        (
            ValueError(
                'Auth service error (400): {"error": "This model\'s maximum context length is 128000 tokens. '
                'However, your messages resulted in 130500 tokens."}'
            ),
            (130500, 128000),
        ),
        (
            ValueError("The input token count (1200000) exceeds the maximum number of tokens allowed (1048576)."),
            (1200000, 1048576),
        ),
        (ValueError('Auth service error (400): {"code": "context_length_exceeded"}'), (None, None)),
    ],
)
def test_cloud_overflow_wordings_are_recognized(error, expected):
    classification = classify_model_error(error)
    assert classification.kind == CONTEXT_OVERFLOW
    assert (classification.actual_tokens, classification.max_tokens) == expected


def test_empty_generation_and_transient_kinds():
    assert classify_model_error(ValueError("No generation chunks were returned")).kind == EMPTY_GENERATION
    assert classify_model_error(TransientModelError("Auth service error (503): busy")).kind == TRANSIENT_EXHAUSTED
    assert classify_model_error(ConnectionError("reset")).kind == TRANSIENT
    assert classify_model_error(RuntimeError("Request timed out - please try again")).kind == TRANSIENT
    assert classify_model_error(RuntimeError("anthropic overloaded_error")).kind == TRANSIENT


def test_authentication_and_unknown_errors_are_fatal():
    assert classify_model_error(Exception("Invalid API key provided")).kind == FATAL
    assert classify_model_error(ValueError("Payment required - please add a payment method")).kind == FATAL


def test_overflow_trim_sizes():
    assert overflow_chars_to_remove("x" * 100, 40000, 32768) == (40000 - 32768 + 5000) * 4
    assert overflow_chars_to_remove("x" * 100_000, None, None) == 25_000
    assert overflow_chars_to_remove("short", None, None) == 4000
    assert overflow_token_summary(40000, 32768) == " (40,000 > 32,768 tokens)"
    assert overflow_token_summary(None, None) == ""
