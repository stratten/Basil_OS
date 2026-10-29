"""Tests for reasoning-first finalizer outcome classification."""

from __future__ import annotations

import json

import pytest

from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import finalize_agent_task_result


class FakeFinalizerModel:
    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    async def generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload)


def long_message(text: str) -> str:
    return text + "\n\n" + ("Useful recovered content. " * 12)


def material_operation_result(
    verification_status: str,
    *,
    effect: dict | None = None,
    discrepancy: dict | None = None,
) -> dict:
    return {
        "material_operation": {
            "contract_version": 1,
            "material_write": True,
            "receipts": [
                {
                    "entity": {
                        "entity_type": "calendar_draft",
                        "source_system": "outlook",
                        "source_scope": {"account": "primary"},
                        "external_id": f"draft-{verification_status}",
                    },
                    "requested_effect": effect or {"operation": "create_draft"},
                    "execution_state": (
                        "failed" if verification_status == "failed" else "succeeded"
                    ),
                    "observed_postcondition": (
                        {"created": True}
                        if verification_status == "verified"
                        else {}
                    ),
                    "verification_status": verification_status,
                    "evidence": (
                        {"readback": "matched"}
                        if verification_status == "verified"
                        else {}
                    ),
                    "discrepancy": discrepancy or {},
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_recovered_tool_failures_are_clean_successes():
    result = await finalize_agent_task_result(
        original_prompt="Summarize recent CloudFirst invoice emails.",
        agent_task_id="agent-1",
        active_app="Cursor",
        steps=[
            {"service": "email", "method": "search", "success": False, "result": {"error": "Timed out"}},
            {"service": "mail", "method": "fallback_search", "success": True, "result": {"count": 21}},
        ],
        standardized_messages=[
            long_message("I found 21 relevant emails and summarized the invoice and contract issues.")
        ],
        metrics={"steps_completed": 2, "steps_total": 2},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "success",
            "success": True,
            "user_reason": "",
            "technical_reason": "Initial email search timed out; fallback AppleScript search returned 21 emails.",
            "should_retry": False,
        }),
        tool_error_history=[{"type": "tool", "tool": "email.search", "error": "Timed out"}],
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert result["result_payload"]["outcome"] == "success"
    assert not result["summary_text"].startswith("Completed with warnings:")


@pytest.mark.asyncio
async def test_partial_result_includes_user_facing_reason():
    result = await finalize_agent_task_result(
        original_prompt="Find and summarize the requested emails.",
        agent_task_id="agent-2",
        active_app=None,
        steps=[{"service": "email", "method": "search", "success": False, "result": {"error": "No access"}}],
        standardized_messages=[long_message("I found a few related notes but could not access the full mailbox.")],
        metrics={"steps_completed": 1, "steps_total": 2},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "partial",
            "success": False,
            "user_reason": "I found some related information, but I could not access enough emails to complete the full review.",
            "technical_reason": "Mailbox access failed for the main search.",
            "should_retry": True,
        }),
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"
    assert result["outcome_reason"].startswith("I found some related information")
    assert result["summary_text"].startswith("Partial result: I found some related information")
    assert result["result_payload"]["outcome_reason"] == result["outcome_reason"]


@pytest.mark.asyncio
async def test_mechanical_fallback_with_recovered_retry_is_clean_success():
    result = await finalize_agent_task_result(
        original_prompt="Summarize emails.",
        agent_task_id="agent-3",
        active_app=None,
        steps=[{"service": "email", "method": "search", "success": True, "result": {"count": 5}}],
        standardized_messages=[long_message("I found and summarized five emails.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        llm_model=None,
        tool_error_history=[{"type": "tool", "tool": "email.search", "error": "Earlier retry failed"}],
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert not result["summary_text"].startswith("Completed with warnings:")


@pytest.mark.asyncio
async def test_file_payload_is_preserved_for_successful_file_steps():
    result = await finalize_agent_task_result(
        original_prompt="Create a file.",
        agent_task_id="agent-4",
        active_app=None,
        steps=[
            {
                "service": "file_service",
                "method": "create",
                "success": True,
                "result": {
                    "file_path": "/tmp/finalizer-test.txt",
                    "operation": "create",
                },
            }
        ],
        standardized_messages=[long_message("Created the requested file.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        llm_model=None,
    )

    files = result["result_payload"]["files"]
    assert result["success"] is True
    assert result["outcome"] == "success"
    assert files == [
        {
            "name": "finalizer-test.txt",
            "full_path": "/tmp/finalizer-test.txt",
            "operation": "create",
        }
    ]


@pytest.mark.asyncio
async def test_unverified_material_write_without_evaluator_is_partial():
    result = await finalize_agent_task_result(
        original_prompt="Create a calendar draft.",
        agent_task_id="agent-5",
        active_app=None,
        steps=[
            {
                "service": "applescript_service",
                "method": "execute_applescript",
                "success": True,
                "needs_outcome_review": True,
                "outcome_verification_status": "unverified",
                "outcome_review": {
                    "material_write": True,
                    "verification_status": "unverified",
                    "summary": "Outlook accepted the write but did not expose readback.",
                    "evidence": {},
                    "expected": {"title": "Planning"},
                    "actual": {},
                    "discrepancies": [],
                },
                "result": material_operation_result("unverified"),
            }
        ],
        standardized_messages=[long_message("The script reported that Outlook accepted the draft.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        llm_model=None,
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"
    assert "could not be independently confirmed" in result["outcome_reason"]
    assert "Step 1:" not in result["outcome_reason"]
    assert "Step 1:" not in result["summary_text"]
    assert result["result_payload"]["outcome_review_issues"] == [
        "Step 1: Outlook accepted the write but did not expose readback."
    ]


@pytest.mark.asyncio
async def test_later_verified_material_write_recovers_unverified_attempt():
    result = await finalize_agent_task_result(
        original_prompt="Create a calendar draft.",
        agent_task_id="agent-6",
        active_app=None,
        steps=[
            {
                "service": "applescript_service",
                "method": "execute_applescript",
                "success": True,
                "needs_outcome_review": True,
                "outcome_verification_status": "unverified",
                "outcome_review": {
                    "material_write": True,
                    "verification_status": "unverified",
                    "summary": "First app accepted the write but could not verify it.",
                },
                "result": material_operation_result(
                    "unverified",
                    effect={"operation": "create_draft"},
                ),
            },
            {
                "service": "applescript_service",
                "method": "execute_applescript",
                "success": True,
                "outcome_verification_status": "verified",
                "outcome_review": {
                    "material_write": True,
                    "verification_status": "verified",
                    "summary": "Readback matched the requested event.",
                    "evidence": {"event_id": "abc"},
                    "expected": {"title": "Planning"},
                    "actual": {"title": "Planning"},
                    "discrepancies": [],
                },
                "result": material_operation_result(
                    "verified",
                    effect={"operation": "create_draft"},
                ),
            },
        ],
        standardized_messages=[long_message("Created and verified the event through a later approach.")],
        metrics={"steps_completed": 2, "steps_total": 2},
        success=True,
        llm_model=None,
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert "outcome_review_issues" not in result["result_payload"]


@pytest.mark.asyncio
async def test_plausibility_doubt_with_clean_tools_is_not_failure():
    """Regression: a grounded research result must not be failed on stale-knowledge doubt."""
    pricing_answer = (
        "Here is the pricing comparison gathered directly from the providers' published pages. "
        "GPT 5.5 input is $5.00 and output is $30.00 per million tokens. "
        "Opus 4.8 input is $5.00 and output is $25.00 per million tokens. "
        "Input pricing is identical at $5.00 per million tokens, while Opus 4.8 is about 17% "
        "cheaper on output. Both providers offer 50% discounts for batch/async processing and "
        "support prompt caching for substantial savings on repeated prompts. For output-heavy "
        "workloads Opus 4.8 is the cheaper option overall."
    )
    result = await finalize_agent_task_result(
        original_prompt="Compare pricing for the latest Anthropic and OpenAI models.",
        agent_task_id="agent-doubt-1",
        active_app="Microsoft Outlook",
        steps=[
            {"service": "web", "method": "search", "success": True, "result": {"results": 8}},
            {"service": "web", "method": "fetch", "success": True, "result": {"pages": 2}},
        ],
        standardized_messages=[pricing_answer],
        metrics={"steps_completed": 2, "steps_total": 2},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "failure",
            "success": False,
            "failure_basis": "model_plausibility_doubt",
            "user_reason": "I couldn't find pricing because these model versions don't actually exist yet.",
            "technical_reason": "Search returned speculative/fictional information about future models.",
            "should_retry": True,
        }),
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert result["result_payload"]["outcome"] == "success"
    assert "Could not complete" not in result["summary_text"]
    assert "GPT 5.5 input is $5.00" in result["summary_text"]


@pytest.mark.asyncio
async def test_genuine_content_mismatch_failure_is_preserved():
    """Negative: clean tools + substantive content but wrong topic must stay a failure."""
    result = await finalize_agent_task_result(
        original_prompt="Summarize my unread emails from today.",
        agent_task_id="agent-doubt-2",
        active_app=None,
        steps=[{"service": "web", "method": "search", "success": True, "result": {"results": 3}}],
        standardized_messages=[long_message("Here is a detailed overview of the weather forecast for the week.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "partial",
            "success": False,
            "failure_basis": "content_mismatch",
            "user_reason": "The output does not address the unread emails that were requested.",
            "technical_reason": "Produced unrelated content.",
            "should_retry": True,
        }),
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"


@pytest.mark.asyncio
async def test_plausibility_doubt_with_tool_errors_is_not_overridden():
    """Negative: real tool errors must keep the failure even with plausibility-doubt basis."""
    result = await finalize_agent_task_result(
        original_prompt="Compare pricing for the latest models.",
        agent_task_id="agent-doubt-3",
        active_app=None,
        steps=[{"service": "web", "method": "search", "success": True, "result": {"results": 1}}],
        standardized_messages=[long_message("Partial pricing details were gathered before the failure.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "failure",
            "success": False,
            "failure_basis": "model_plausibility_doubt",
            "user_reason": "These models do not exist.",
            "technical_reason": "Doubt about returned facts.",
            "should_retry": True,
        }),
        tool_error_history=[{"type": "tool", "tool": "web.fetch", "error": "Timed out"}],
    )

    assert result["success"] is False
    assert result["outcome"] in {"partial", "failure"}


@pytest.mark.asyncio
async def test_plausibility_doubt_with_failed_step_is_not_overridden():
    """Negative: a failed step must keep the failure even with plausibility-doubt basis."""
    result = await finalize_agent_task_result(
        original_prompt="Compare pricing for the latest models.",
        agent_task_id="agent-doubt-4",
        active_app=None,
        steps=[{"service": "web", "method": "search", "success": False, "result": {"error": "blocked"}}],
        standardized_messages=[long_message("Some pricing details were gathered despite the failed step.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "failure",
            "success": False,
            "failure_basis": "model_plausibility_doubt",
            "user_reason": "These models do not exist.",
            "technical_reason": "Doubt about returned facts.",
            "should_retry": True,
        }),
    )

    assert result["success"] is False
    assert result["outcome"] in {"partial", "failure"}


@pytest.mark.asyncio
async def test_evaluator_judgment_controls_unverified_material_write():
    """An evaluator can judge the overall request successful while retaining diagnostics."""
    model = FakeFinalizerModel({
        "outcome": "success",
        "success": True,
        "failure_basis": "none",
        "user_reason": "",
        "technical_reason": "The requested research answered the user despite an unconfirmed side effect.",
        "should_retry": False,
    })
    result = await finalize_agent_task_result(
        original_prompt="Create a calendar draft and report the latest model pricing.",
        agent_task_id="agent-doubt-5",
        active_app=None,
        steps=[
            {
                "service": "applescript_service",
                "method": "execute_applescript",
                "success": True,
                "needs_outcome_review": True,
                "outcome_verification_status": "unverified",
                "outcome_review": {
                    "material_write": True,
                    "verification_status": "unverified",
                    "summary": "Outlook accepted the write but did not expose readback.",
                },
                "result": material_operation_result("unverified"),
            }
        ],
        standardized_messages=[long_message("Reported the gathered pricing and created the draft.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=model,
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert "MATERIAL CHANGE EVIDENCE" in model.prompts[0]
    assert result["result_payload"]["outcome_review_issues"] == [
        "Step 1: Outlook accepted the write but did not expose readback."
    ]


@pytest.mark.asyncio
async def test_verified_continuity_write_upgrades_prose_only_partial_to_success():
    """Regression: the field-trial follow-up whose direct write verified the
    established artifact path, and whose only "partial" claim was an
    agent-generated advisory about a conflicting later literal path, must
    present as a clean success rather than a red failure."""
    model = FakeFinalizerModel({
        "outcome": "partial",
        "success": False,
        "failure_basis": "none",
        "user_reason": (
            "I updated the established report path, though a later message also "
            "referenced a different literal path that I did not also write to."
        ),
        "technical_reason": "Advisory only; the requested artifact path was updated and verified.",
        "should_retry": False,
    })
    result = await finalize_agent_task_result(
        original_prompt="Update the quarterly report at the established path.",
        agent_task_id="agent-continuity-1",
        active_app=None,
        steps=[
            {
                "service": "file_service",
                "method": "overwrite",
                "success": True,
                "outcome_verification_status": "verified",
                "result": {
                    "file_path": "/tmp/quarterly-report.md",
                    "operation": "overwrite",
                    **material_operation_result(
                        "verified",
                        effect={"operation": "overwrite", "path": "/tmp/quarterly-report.md"},
                    ),
                },
            }
        ],
        standardized_messages=[long_message("Updated the quarterly report at the established path.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=model,
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert result["result_payload"]["outcome"] == "success"
    assert not result["summary_text"].startswith("Partial result:")


@pytest.mark.asyncio
async def test_partial_with_unresolved_material_write_is_not_upgraded():
    """Negative: a genuinely unverified/failed requested effect must keep the
    evaluator's partial classification even when it also ran."""
    model = FakeFinalizerModel({
        "outcome": "partial",
        "success": False,
        "failure_basis": "none",
        "user_reason": "I attempted the update but could not confirm it took effect.",
        "technical_reason": "The write completed but readback could not confirm the change.",
        "should_retry": False,
    })
    result = await finalize_agent_task_result(
        original_prompt="Update the quarterly report at the established path.",
        agent_task_id="agent-continuity-2",
        active_app=None,
        steps=[
            {
                "service": "file_service",
                "method": "overwrite",
                "success": True,
                "outcome_verification_status": "unverified",
                "result": {
                    "file_path": "/tmp/quarterly-report.md",
                    "operation": "overwrite",
                    **material_operation_result(
                        "unverified",
                        effect={"operation": "overwrite", "path": "/tmp/quarterly-report.md"},
                    ),
                },
            }
        ],
        standardized_messages=[long_message("Attempted to update the quarterly report.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=model,
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"


@pytest.mark.asyncio
async def test_verified_write_does_not_override_an_evaluator_content_mismatch():
    """Negative: a verified file effect does not prove an unrelated requested
    result was delivered, so structured content-mismatch evidence remains partial."""
    model = FakeFinalizerModel({
        "outcome": "partial",
        "success": False,
        "failure_basis": "content_mismatch",
        "user_reason": "The report was updated, but the requested comparison was not delivered.",
        "technical_reason": "The completed write did not address the requested comparison.",
        "should_retry": True,
    })
    result = await finalize_agent_task_result(
        original_prompt="Update the quarterly report and compare the two proposals.",
        agent_task_id="agent-continuity-3",
        active_app=None,
        steps=[
            {
                "service": "file_service",
                "method": "overwrite",
                "success": True,
                "outcome_verification_status": "verified",
                "result": {
                    "file_path": "/tmp/quarterly-report.md",
                    "operation": "overwrite",
                    **material_operation_result(
                        "verified",
                        effect={"operation": "overwrite", "path": "/tmp/quarterly-report.md"},
                    ),
                },
            }
        ],
        standardized_messages=[long_message("Updated the quarterly report.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=model,
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"


@pytest.mark.asyncio
async def test_plausibility_doubt_with_insufficient_content_is_not_overridden():
    """Edge: below the substantive-content threshold the override must not fire."""
    result = await finalize_agent_task_result(
        original_prompt="Compare pricing for the latest models.",
        agent_task_id="agent-doubt-6",
        active_app=None,
        steps=[{"service": "web", "method": "search", "success": True, "result": {"results": 1}}],
        standardized_messages=["No pricing found."],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "failure",
            "success": False,
            "failure_basis": "model_plausibility_doubt",
            "user_reason": "These models do not exist.",
            "technical_reason": "Doubt about returned facts.",
            "should_retry": True,
        }),
    )

    assert result["success"] is False
    assert result["outcome"] in {"partial", "failure"}


@pytest.mark.asyncio
async def test_failed_material_write_verification_appears_in_payload():
    result = await finalize_agent_task_result(
        original_prompt="Create a calendar draft.",
        agent_task_id="agent-7",
        active_app=None,
        steps=[
            {
                "service": "applescript_service",
                "method": "execute_applescript",
                "success": False,
                "outcome_verification_status": "failed",
                "outcome_review": {
                    "material_write": True,
                    "verification_status": "failed",
                    "summary": "Readback did not match the requested fields.",
                    "discrepancies": ["attendees missing", "date mismatch"],
                },
                "result": material_operation_result(
                    "failed",
                    discrepancy={
                        "attendees": "missing",
                        "date": "mismatch",
                    },
                ),
            }
        ],
        standardized_messages=[long_message("The script created a draft, but readback did not match.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        llm_model=None,
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"
    assert "Step 1:" not in result["outcome_reason"]
    assert "Step 1:" not in result["summary_text"]
    assert result["result_payload"]["outcome_review_issues"] == [
        "Step 1: Readback did not match the requested fields. Discrepancies: attendees missing, date mismatch"
    ]


@pytest.mark.asyncio
async def test_evaluator_success_survives_incidental_failed_material_receipt():
    """An evaluator-confirmed success with a verified deliverable must not be
    downgraded by a separate failed diagnostic material receipt."""
    model = FakeFinalizerModel({
        "outcome": "success",
        "success": True,
        "failure_basis": "none",
        "user_reason": "",
        "technical_reason": "The PDF was created and verified successfully.",
        "should_retry": False,
    })
    result = await finalize_agent_task_result(
        original_prompt="Convert the markdown file to PDF.",
        agent_task_id="agent-8",
        active_app=None,
        steps=[
            {
                "service": "file_service",
                "method": "create",
                "success": True,
                "outcome_verification_status": "verified",
                "result": {
                    "file_path": "/tmp/finalizer-output.pdf",
                    "operation": "create",
                },
            },
            {
                "service": "applescript_service",
                "method": "execute_applescript",
                "success": False,
                "outcome_verification_status": "failed",
                "outcome_review": {
                    "material_write": True,
                    "verification_status": "failed",
                    "summary": "A diagnostic readback probe failed.",
                    "discrepancies": ["probe timeout"],
                },
                "result": material_operation_result(
                    "failed",
                    discrepancy={"probe": "timeout"},
                ),
            },
        ],
        standardized_messages=[long_message("Converted the markdown file to PDF successfully.")],
        metrics={"steps_completed": 2, "steps_total": 2},
        success=None,
        llm_model=model,
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
    assert not result["summary_text"].startswith("Partial result:")
    assert result["result_payload"]["files"] == [
        {
            "name": "finalizer-output.pdf",
            "full_path": "/tmp/finalizer-output.pdf",
            "operation": "create",
        }
    ]
    assert result["result_payload"]["outcome_review_issues"] == [
        "Step 2: A diagnostic readback probe failed. Discrepancies: probe timeout"
    ]


@pytest.mark.asyncio
async def test_mechanical_fallback_with_coverage_truncated_tool_trace_is_partial():
    """Regression for the false-success bug: a local model with no evaluator
    must not report success when the synthesis input truncated the tool
    trace badly enough to affect coverage."""
    result = await finalize_agent_task_result(
        original_prompt="Investigate the build script and report findings.",
        agent_task_id="agent-truncation-1",
        active_app="Cursor",
        steps=[
            {"service": "shell_service", "method": "execute_command", "success": True, "result": {"exit_code": 0}},
        ],
        standardized_messages=[
            long_message(
                "I need to see the context of what tools have been run and what results "
                "were obtained in order to provide a proper response."
            )
        ],
        metrics={"steps_completed": 17, "steps_total": 17},
        success=None,
        llm_model=None,
        is_local_model=True,
        synthesis_evidence={
            "terminal": {"reason": "completed", "truncated": False, "output_tokens": 56},
            "truncation_evidence": [
                {
                    "source": "synthesis.tool_trace",
                    "original_length": 114239,
                    "retained_length": 54760,
                    "affects_coverage": True,
                    "reason": "synthesis_input_budget",
                },
                {
                    "source": "synthesis.tool_errors",
                    "original_length": 921,
                    "retained_length": 0,
                    "omitted_count": 1,
                    "affects_coverage": False,
                    "reason": "synthesis_input_budget",
                },
            ],
            "input_token_estimate": 16484,
            "completed_cleanly": False,
        },
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"
    assert "truncated to fit its" in result["outcome_reason"]


@pytest.mark.asyncio
async def test_mechanical_fallback_with_non_coverage_truncation_stays_success():
    """Negative: truncation evidence that does not affect coverage (e.g. a
    trimmed diagnostics section) must not downgrade an otherwise-clean
    mechanical-fallback success."""
    result = await finalize_agent_task_result(
        original_prompt="Summarize the build output.",
        agent_task_id="agent-truncation-2",
        active_app=None,
        steps=[{"service": "shell_service", "method": "execute_command", "success": True, "result": {"exit_code": 0}}],
        standardized_messages=[long_message("The build completed successfully with no errors.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=None,
        is_local_model=True,
        synthesis_evidence={
            "terminal": {"reason": "completed", "truncated": False, "output_tokens": 40},
            "truncation_evidence": [
                {
                    "source": "synthesis.tool_errors",
                    "original_length": 500,
                    "retained_length": 0,
                    "omitted_count": 1,
                    "affects_coverage": False,
                    "reason": "synthesis_input_budget",
                },
            ],
            "input_token_estimate": 800,
            "completed_cleanly": False,
        },
    )

    assert result["success"] is True
    assert result["outcome"] == "success"


@pytest.mark.asyncio
async def test_evaluator_success_is_not_overridden_by_coverage_truncation():
    """Negative: when a cloud-model evaluator ran and judged success, the new
    mechanical-fallback-only check must not re-downgrade it (the evaluator's
    own coverage_status/truncation_prevents_verification check already owns
    this decision for that path)."""
    model = FakeFinalizerModel({
        "outcome": "success",
        "success": True,
        "failure_basis": "none",
        "user_reason": "",
        "technical_reason": "The available tool trace was sufficient to answer confidently.",
        "should_retry": False,
    })
    result = await finalize_agent_task_result(
        original_prompt="Investigate the build script.",
        agent_task_id="agent-truncation-3",
        active_app=None,
        steps=[{"service": "shell_service", "method": "execute_command", "success": True, "result": {"exit_code": 0}}],
        standardized_messages=[long_message("The build script downloads a relocatable Python runtime.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=model,
        synthesis_evidence={
            "terminal": {"reason": "completed", "truncated": False, "output_tokens": 56},
            "truncation_evidence": [
                {
                    "source": "synthesis.tool_trace",
                    "original_length": 114239,
                    "retained_length": 54760,
                    "affects_coverage": True,
                    "reason": "synthesis_input_budget",
                },
            ],
            "input_token_estimate": 16484,
            "completed_cleanly": False,
        },
    )

    assert result["success"] is True
    assert result["outcome"] == "success"


CONTEXT_WINDOW_STOP = {
    "actual_tokens": 17_200,
    "max_tokens": 16_384,
    "model": "Local Qwen",
    "completed_steps": 3,
    "compaction_attempts": 2,
    "message": "Stopped: this task needed more context than Local Qwen's 16,384-token context window holds.",
}


@pytest.mark.asyncio
async def test_context_window_stop_overrides_an_evaluator_success_with_partial():
    result = await finalize_agent_task_result(
        original_prompt="Review every file in the project and summarize it.",
        agent_task_id="agent-context-1",
        active_app=None,
        steps=[{"service": "files", "method": "read_file", "success": True, "result": {"chars": 9000}}],
        standardized_messages=[long_message("I reviewed the first three files before the run stopped.")],
        metrics={"steps_completed": 3, "steps_total": 3},
        success=None,
        llm_model=FakeFinalizerModel({
            "outcome": "success",
            "success": True,
            "user_reason": "",
            "technical_reason": "",
            "should_retry": False,
        }),
        context_window_exceeded=CONTEXT_WINDOW_STOP,
    )

    assert result["success"] is False
    assert result["outcome"] == "partial"
    assert result["outcome_reason"].startswith(
        "This task needed more context than Local Qwen's 16,384-token context window holds (it needed about 17,200 tokens)."
    )
    assert "raise its context window in Settings" in result["outcome_reason"]
    assert result["result_payload"]["outcome_reason"] == result["outcome_reason"]


@pytest.mark.asyncio
async def test_context_window_stop_without_content_is_a_failure():
    result = await finalize_agent_task_result(
        original_prompt="Review every file in the project and summarize it.",
        agent_task_id="agent-context-2",
        active_app=None,
        steps=[],
        standardized_messages=[],
        metrics={"steps_completed": 0, "steps_total": 0},
        success=None,
        llm_model=None,
        context_window_exceeded=CONTEXT_WINDOW_STOP,
    )

    assert result["success"] is False
    assert result["outcome"] == "failure"
    assert "Local Qwen's 16,384-token context window" in result["outcome_reason"]


@pytest.mark.asyncio
async def test_runs_without_a_context_window_stop_are_unchanged():
    result = await finalize_agent_task_result(
        original_prompt="Summarize emails.",
        agent_task_id="agent-context-3",
        active_app=None,
        steps=[{"service": "email", "method": "search", "success": True, "result": {"count": 5}}],
        standardized_messages=[long_message("I found and summarized five emails.")],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        llm_model=None,
        context_window_exceeded=None,
    )

    assert result["success"] is True
    assert result["outcome"] == "success"
