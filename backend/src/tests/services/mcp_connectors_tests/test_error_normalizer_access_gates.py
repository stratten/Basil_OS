"""Tests for classifying a server's access-not-enabled failures as final, user-actionable denials."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.mcp_connectors import error_normalizer as normalizer

GOOGLE_PREVIEW_ERROR = (
    "Access to this tool requires that your Google Cloud project (66955964643) is enrolled in the Google Workspace Developer Preview Program."
)


def _failed_result(text: str):
    return SimpleNamespace(isError=True, content=[SimpleNamespace(text=text)], structuredContent=None)


def test_a_developer_preview_gate_is_a_final_permission_denial_with_an_action():
    envelope = normalizer.normalize_call_tool_result(_failed_result(GOOGLE_PREVIEW_ERROR))

    error = envelope["error"]
    assert envelope["ok"] is False
    assert error["kind"] == "permission_denied"
    assert error["retryable"] is False
    assert "Developer Preview Program" in error["user_action_required"]
    assert "66955964643" in error["message"]


@pytest.mark.parametrize("text", ["The project is not enrolled in the beta.", "Your project is enrolled in nothing yet."])
def test_other_enrollment_gates_are_also_final(text):
    error = normalizer.normalize_call_tool_result(_failed_result(text))["error"]

    assert error["kind"] == "permission_denied"
    assert error["retryable"] is False


def test_an_unrecognized_failure_is_still_a_retryable_server_error():
    error = normalizer.normalize_call_tool_result(_failed_result("Backend exploded."))["error"]

    assert error["kind"] == "server_error"
    assert error["retryable"] is True


def test_a_signed_out_failure_still_asks_for_a_reconnect():
    error = normalizer.normalize_call_tool_result(_failed_result("Token expired, unauthorized."))["error"]

    assert error["kind"] == "auth_expired"


VALIDATION_WINDOW_ERROR = (
    "Validation window is not open or has expired. The window only lasts a couple of minutes and is not kept across restarts. "
    "This request is currently ready_for_final_review."
)


@pytest.mark.parametrize(
    "text",
    [
        VALIDATION_WINDOW_ERROR,
        "The approval card has expired",
        "Invalid approval token supplied",
        "author field is required",
        "Not authorized to approve this item",
        "token has expired for this checkout session",
        "Request 4010 failed",
    ],
)
def test_a_business_failure_that_merely_contains_an_auth_word_is_not_a_credential_failure(text):
    envelope = normalizer.normalize_call_tool_result(_failed_result(text))

    assert envelope["error"]["kind"] != "auth_expired"
    assert envelope["error"]["message"] == text


@pytest.mark.parametrize(
    "text",
    ["Unauthorized", "HTTP 401 from upstream", "The access token expired", "invalid_token", "Authentication failed", "Authentication required", "OAuth token is invalid"],
)
def test_a_message_that_says_the_credentials_were_rejected_is_a_credential_failure(text):
    envelope = normalizer.normalize_call_tool_result(_failed_result(text))

    assert envelope["error"]["kind"] == "auth_expired"
    assert envelope["error"]["user_action_required"] == "Reconnect this server in Settings → Connections."


def test_a_kind_guessed_from_message_text_is_tagged_so_it_is_never_recorded_as_a_dead_connection():
    guessed = normalizer.normalize_call_tool_result(_failed_result("Unauthorized"))["error"]["raw"]
    assert guessed["source"] == normalizer.SOURCE_TOOL_TEXT

