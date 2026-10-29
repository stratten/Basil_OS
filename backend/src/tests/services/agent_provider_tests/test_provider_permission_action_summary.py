"""Unit tests for `normalize_permission_action_summary` (Package 4B.2)."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_permission_action_summary import (
    InvalidPermissionActionSummaryError,
    normalize_permission_action_summary,
)

_VALID_OPTIONS = [
    {"optionId": "allow-once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject-once", "name": "Reject once", "kind": "reject_once"},
]


def test_normalizes_a_valid_action_summary_with_description_and_subject() -> None:
    summary = normalize_permission_action_summary(
        title="Run this command?",
        description="The provider wants to run a shell command.",
        options=_VALID_OPTIONS,
        subject={"type": "command", "command": "ls", "cwd": "/tmp"},
    )
    assert summary["title"] == "Run this command?"
    assert summary["description"] == "The provider wants to run a shell command."
    assert summary["options"] == _VALID_OPTIONS
    assert summary["subject"] == {"type": "command", "command": "ls", "cwd": "/tmp"}


def test_normalizes_a_valid_action_summary_with_no_description_or_subject() -> None:
    summary = normalize_permission_action_summary(
        title="Run this command?", description=None, options=_VALID_OPTIONS, subject=None
    )
    assert summary["description"] is None
    assert summary["subject"] is None


def test_rejects_a_blank_title() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="   ", description=None, options=_VALID_OPTIONS, subject=None
        )


def test_rejects_an_overlong_title() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="x" * 600, description=None, options=_VALID_OPTIONS, subject=None
        )


def test_rejects_a_non_string_description() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?", description=123, options=_VALID_OPTIONS, subject=None
        )


def test_rejects_an_overlong_description() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?", description="x" * 3000, options=_VALID_OPTIONS, subject=None
        )


def test_rejects_empty_options() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?", description=None, options=[], subject=None
        )


def test_rejects_options_with_duplicate_ids() -> None:
    duplicate_options = [
        {"optionId": "allow-once", "name": "Allow once", "kind": "allow_once"},
        {"optionId": "allow-once", "name": "Allow again", "kind": "allow_always"},
    ]
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?", description=None, options=duplicate_options, subject=None
        )


def test_rejects_a_command_subject_with_a_relative_cwd() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?",
            description=None,
            options=_VALID_OPTIONS,
            subject={"type": "command", "command": "ls", "cwd": "relative/path"},
        )


def test_rejects_an_oversized_forward_compatible_subject() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?",
            description=None,
            options=_VALID_OPTIONS,
            subject={"type": "future_subject_kind", "payload": "x" * 20_000},
        )


def test_rejects_a_subject_that_cannot_be_json_serialized() -> None:
    with pytest.raises(InvalidPermissionActionSummaryError):
        normalize_permission_action_summary(
            title="Run?",
            description=None,
            options=_VALID_OPTIONS,
            subject={"type": "future_subject_kind", "payload": object()},
        )


def test_tolerates_an_unrecognized_subject_type() -> None:
    summary = normalize_permission_action_summary(
        title="Run?",
        description=None,
        options=_VALID_OPTIONS,
        subject={"type": "future_subject_kind", "anything": "goes"},
    )
    assert summary["subject"] == {"type": "future_subject_kind", "anything": "goes"}
