"""Run-details metadata appended by compose_summary; parsed by the AgentTaskResult web view (resultContentUtils.splitRunDetails)."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.finalization.summary_payload import compose_summary


def test_reports_tool_call_total_without_a_success_ratio():
    summary = compose_summary(
        success=True,
        app_context="Mail",
        files=[],
        steps_completed=12,
        steps_total=14,
        content_messages=["Here is the review."],
    )

    assert summary.endswith("• Active app at request: Mail\n\n• Tool calls: 14")
    assert "Steps:" not in summary
    assert "12" not in summary


def test_omits_tool_calls_when_no_tools_ran():
    summary = compose_summary(
        success=True,
        app_context=None,
        files=[],
        steps_completed=0,
        steps_total=0,
        content_messages=["Plain answer."],
    )

    assert "Tool calls" not in summary
