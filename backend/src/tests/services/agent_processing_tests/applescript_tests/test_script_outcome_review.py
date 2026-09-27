from dataclasses import asdict

import pytest

from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
    GenericAppleScriptService,
)
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.script_outcome_review import (
    build_outcome_review_error,
    detect_semantic_script_error,
    parse_script_outcome_review,
)


@pytest.mark.parametrize(
    "output",
    [
        "ERROR -1700: Can’t make missing value into type specifier.",
        "Error -10003: Microsoft Outlook got an error: Access not allowed.",
        "ERROR: Could not create event",
        "SCRIPT_ERROR: Handler failed",
        "MAIN_ERROR: Top-level failure",
        "VERIFY_ERROR: Created event did not match expected fields",
    ],
)
def test_semantic_script_error_detects_explicit_error_envelopes(output):
    assert detect_semantic_script_error(output) == output


def test_generic_service_semantic_error_uses_shared_detector():
    service = GenericAppleScriptService()

    assert service._semantic_applescript_error("ERROR -1700: coercion failed")


def test_result_json_verified_material_write_is_parsed_as_verified():
    review = parse_script_outcome_review(
        'Created event\nRESULT_JSON: {"material_write": true, "verification_status": "verified", '
        '"summary": "Readback matched", "evidence": {"event_id": "abc"}, '
        '"expected": {"title": "Planning"}, "actual": {"title": "Planning"}, "discrepancies": []}'
    )

    assert review.material_write is True
    assert review.verification_status == "verified"
    assert review.summary == "Readback matched"
    assert review.evidence["event_id"] == "abc"
    assert build_outcome_review_error(review) is None


def test_result_json_failed_material_write_returns_discrepancy_error():
    review = parse_script_outcome_review(
        'RESULT_JSON: {"material_write": true, "verification_status": "failed", '
        '"summary": "Readback did not match", "expected": {"attendees": 4}, '
        '"actual": {"attendees": 0}, "discrepancies": ["attendees missing"]}'
    )

    assert review.material_write is True
    assert review.verification_status == "failed"
    assert review.discrepancies == ["attendees missing"]
    assert build_outcome_review_error(review) == (
        "Script outcome verification failed: Readback did not match; discrepancies: attendees missing"
    )


def test_result_json_unverified_material_write_requests_outcome_review():
    review = parse_script_outcome_review(
        'RESULT_JSON: {"material_write": true, "verification_status": "unverified", '
        '"summary": "Outlook accepted the write but did not expose readback"}'
    )

    assert asdict(review)["material_write"] is True
    assert review.verification_status == "unverified"
    assert build_outcome_review_error(review) is None


def test_missing_result_json_is_not_reported_without_guessing_from_text():
    review = parse_script_outcome_review("SUCCESS: I created the calendar event.")

    assert review.material_write is False
    assert review.verification_status == "not_reported"
    assert review.summary == ""
