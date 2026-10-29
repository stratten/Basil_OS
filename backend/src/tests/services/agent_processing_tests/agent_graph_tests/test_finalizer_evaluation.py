"""Unit tests for the independent finalizer evaluation prompt and parsing."""

from __future__ import annotations

import json

from api.services.agent_processing.lifecycle.finalization.evaluation import (
    build_evaluation_prompt,
    parse_evaluation_response,
)
from api.services.agent_processing.lifecycle.finalization.summary_payload import build_result_payload


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


def test_prompt_treats_established_nonexistence_in_research_as_success():
    prompt = build_evaluation_prompt(
        original_prompt="Find cat t-shirt shops near my hotel in Paris.",
        self_assessment="No dedicated cat t-shirt shop exists nearby; offered alternatives.",
        full_agent_output="A nearby cat cafe gift shop, streetwear stores, and online cat-tee retailers.",
        max_output_chars=50000,
        steps=[{"service": "web", "method": "search", "success": True}],
        tool_error_history=None,
        evaluation_context=None,
    )
    assert "RESEARCH THAT ESTABLISHES THE EXACT THING DOES NOT EXIST IS SUCCESS" in prompt
    assert "a finding about the world, not a residual gap" in prompt
    assert "This does not apply when the agent stopped early" in prompt


def test_prompt_carries_scheduled_follow_up_rule_and_block():
    from api.services.agent_processing.lifecycle.finalization.pending_follow_up_context import (
        render_pending_follow_up_context,
    )

    block = render_pending_follow_up_context(
        [{"status": "scheduled", "due_at": "2026-10-12T15:00:00+00:00", "instructions": "Check the delegated agent run."}]
    )
    prompt = build_evaluation_prompt(
        original_prompt="Complete this To-Do.",
        self_assessment="Started delegated work.",
        full_agent_output="The delegated agent is still working; I will check again at 3 PM.",
        max_output_chars=50000,
        steps=[{"service": "external", "method": "call_tool", "success": True}],
        tool_error_history=None,
        evaluation_context=block,
    )
    assert "FOLLOW-UP CHECKS ALREADY SCHEDULED" in prompt
    assert "Check the delegated agent run." in prompt
    assert "classify success when everything else was delivered" in prompt


def test_prompt_only_requests_a_revision_for_a_missing_requirement_or_unapplied_write():
    prompt = build_evaluation_prompt(
        original_prompt="Summarize the report.",
        self_assessment="Summarized.",
        full_agent_output="A clear summary of the report.",
        max_output_chars=50000,
        steps=[{"service": "files", "method": "read", "success": True}],
        tool_error_history=None,
        evaluation_context=None,
    )

    assert "a stated requirement of the request is missing" in prompt
    assert "Satisfactory output is success" in prompt
    assert "polish, style, wording, formatting, extra verification, optional improvements" in prompt
    assert "is not a gap: leave continuation_instructions empty" in prompt
    assert "an unverified side effect, or a required follow-up step" not in prompt


def _success(**extra):
    return {"outcome": "success", "success": True, "failure_basis": "none", "user_reason": "", "technical_reason": "ok", "should_retry": False, **extra}


def test_prompt_and_schema_describe_suggested_follow_ups():
    prompt = build_evaluation_prompt(
        original_prompt="Summarize my inbox.",
        self_assessment="Summarized.",
        full_agent_output="Three unread emails.",
        max_output_chars=50000,
        steps=[{"service": "mail", "method": "read", "success": True}],
        tool_error_history=None,
        evaluation_context=None,
    )

    assert "SUGGESTED FOLLOW-UPS" in prompt
    assert '"suggested_follow_ups"' in prompt


def test_parse_keeps_up_to_three_short_distinct_suggestions_on_success():
    parsed = parse_evaluation_response(json.dumps(_success(suggested_follow_ups=[
        "  Draft a reply to the first email ",
        "draft a reply to the first email",
        "Summarize the second email",
        "x" * 81,
        42,
        "",
        "Archive the newsletters",
        "Delete the spam",
    ])))

    assert parsed.suggested_follow_ups == ["Draft a reply to the first email", "Summarize the second email", "Archive the newsletters"]


def test_parse_drops_suggestions_unless_the_outcome_is_a_clean_success():
    partial = parse_evaluation_response(json.dumps({**_success(suggested_follow_ups=["Do more"]), "outcome": "partial", "success": False}))
    pending = parse_evaluation_response(json.dumps(_success(suggested_follow_ups=["Do more"], work_still_pending=True, pending_check_instructions="Check the build.")))

    assert partial.suggested_follow_ups == []
    assert pending.suggested_follow_ups == []


def test_parse_tolerates_missing_or_malformed_suggestions():
    assert parse_evaluation_response(json.dumps(_success())).suggested_follow_ups == []
    assert parse_evaluation_response(json.dumps(_success(suggested_follow_ups="Do more"))).suggested_follow_ups == []
    assert parse_evaluation_response(json.dumps(_success(suggested_follow_ups=None))).suggested_follow_ups == []


def _payload(outcome, suggestions):
    return build_result_payload(
        agent_task_id="task-1",
        active_app=None,
        files=[],
        steps_completed=1,
        steps_total=1,
        duration_ms=10,
        outcome=outcome,
        outcome_reason="",
        technical_reason="",
        suggested_follow_ups=suggestions,
    )


def test_result_payload_carries_suggestions_only_for_success_and_omits_the_key_otherwise():
    assert _payload("success", ["Draft a reply"])["suggested_follow_ups"] == ["Draft a reply"]
    assert "suggested_follow_ups" not in _payload("success", [])
    assert "suggested_follow_ups" not in _payload("success", None)
    assert "suggested_follow_ups" not in _payload("partial", ["Draft a reply"])
