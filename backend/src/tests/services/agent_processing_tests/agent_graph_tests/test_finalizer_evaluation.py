"""Unit tests for the independent finalizer evaluation prompt and parsing."""

from __future__ import annotations

import json

from api.services.agent_processing.lifecycle.finalization.evaluation import (
    build_evaluation_prompt,
    parse_evaluation_response,
)


def test_parse_extracts_and_normalizes_failure_basis():
    parsed = parse_evaluation_response(json.dumps({
        "outcome": "failure",
        "success": False,
        "failure_basis": "Model-Plausibility Doubt",
        "user_reason": "These do not exist.",
        "technical_reason": "Doubt.",
        "should_retry": True,
    }))
    assert parsed.failure_basis == "model_plausibility_doubt"

    unknown = parse_evaluation_response(json.dumps({
        "outcome": "failure",
        "success": False,
        "failure_basis": "totally_made_up",
        "user_reason": "x",
        "technical_reason": "y",
        "should_retry": False,
    }))
    assert unknown.failure_basis == ""

    missing = parse_evaluation_response(json.dumps({
        "outcome": "failure",
        "success": False,
        "user_reason": "x",
        "technical_reason": "y",
        "should_retry": False,
    }))
    assert missing.failure_basis == ""


def test_parse_existing_fields_unchanged():
    parsed = parse_evaluation_response(json.dumps({
        "outcome": "partial",
        "success": False,
        "failure_basis": "content_missing",
        "user_reason": "Only found some of it.",
        "technical_reason": "Mailbox partially accessible.",
        "should_retry": True,
    }))
    assert parsed.outcome == "partial"
    assert parsed.success is False
    assert parsed.outcome_reason == "Only found some of it."
    assert parsed.technical_reason == "Mailbox partially accessible."
    assert parsed.should_retry is True


def test_parse_legacy_completed_with_warnings_as_success():
    parsed = parse_evaluation_response(json.dumps({
        "outcome": "completed_with_warnings",
        "success": True,
        "failure_basis": "none",
        "user_reason": "An earlier attempt failed before the verified fallback succeeded.",
        "technical_reason": "Recovered internally.",
        "should_retry": False,
    }))

    assert parsed.outcome == "success"
    assert parsed.success is True


def test_prompt_contains_ground_truth_directive():
    prompt = build_evaluation_prompt(
        original_prompt="Compare the latest model pricing.",
        self_assessment="Gathered pricing from provider pages.",
        full_agent_output="GPT 5.5 and Opus 4.8 pricing details.",
        max_output_chars=50000,
        steps=[{"service": "web", "method": "search", "success": True}],
        tool_error_history=None,
        evaluation_context=None,
    )
    assert "TOOL OUTPUT IS GROUND TRUTH" in prompt
    assert "local/app retrieval only" in prompt
    assert "model_plausibility_doubt" in prompt
    assert '"outcome": "success" | "partial" | "failure"' in prompt
    assert "outcome=completed_with_warnings" not in prompt
