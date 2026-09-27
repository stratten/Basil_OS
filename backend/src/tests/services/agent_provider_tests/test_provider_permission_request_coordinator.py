"""Unit coverage for ProviderPermissionRequestCoordinator's fail-closed contract (Package 4B.1)."""

from __future__ import annotations

import logging

import pytest

from api.services.agent_providers.acp.session_client import AcpRequestError
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_permission_request_coordinator import (
    ProviderPermissionRequestCoordinator,
)


def _make_coordinator(
    *, protocol_version: int = 2,
) -> ProviderPermissionRequestCoordinator:
    coordinator = ProviderPermissionRequestCoordinator(
        provider_run_id="run-1",
        logger=logging.getLogger("test-permission-coordinator"),
        protocol_version=protocol_version,
    )
    coordinator.bind_session("session-1")
    return coordinator


def _reject_option(option_id: str = "reject-once") -> dict:
    return {"optionId": option_id, "name": "Reject", "kind": "reject_once"}


def _allow_option(option_id: str = "allow-once") -> dict:
    return {"optionId": option_id, "name": "Allow", "kind": "allow_once"}


@pytest.mark.asyncio
async def test_v1_permission_request_selects_the_offered_reject_option() -> None:
    result = await _make_coordinator(protocol_version=1).handle_request_permission(
        {
            "sessionId": "session-1",
            "toolCall": {"toolCallId": "call-1", "title": "Read README"},
            "options": [_reject_option()],
        }
    )
    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}


@pytest.mark.asyncio
async def test_v1_permission_request_without_tool_call_is_invalid_params() -> None:
    with pytest.raises(AcpRequestError) as exc_info:
        await _make_coordinator(protocol_version=1).handle_request_permission(
            {"sessionId": "session-1", "options": [_reject_option()]}
        )
    assert exc_info.value.code == -32602


@pytest.mark.asyncio
async def test_handle_request_permission_selects_the_reject_once_option() -> None:
    coordinator = _make_coordinator()

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Run this command?",
            "options": [_allow_option(), _reject_option()],
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}


@pytest.mark.asyncio
async def test_handle_request_permission_prefers_reject_once_over_reject_always() -> None:
    coordinator = _make_coordinator()

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Run this command?",
            "options": [
                {"optionId": "reject-always", "name": "Always reject", "kind": "reject_always"},
                _reject_option("reject-once"),
            ],
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}


@pytest.mark.asyncio
async def test_handle_request_permission_falls_back_to_reject_always() -> None:
    coordinator = _make_coordinator()

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Run this command?",
            "options": [
                _allow_option(),
                {"optionId": "reject-always", "name": "Always reject", "kind": "reject_always"},
            ],
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-always"}}


@pytest.mark.asyncio
async def test_handle_request_permission_declines_with_a_protocol_error_when_no_reject_option_exists() -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission(
            {"sessionId": "session-1", "title": "Continue with elevated permissions?", "options": [_allow_option()]}
        )
    assert excinfo.value.code == -32601


@pytest.mark.asyncio
async def test_handle_request_permission_tolerates_an_unrecognized_subject_type() -> None:
    coordinator = _make_coordinator()

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Continue?",
            "options": [_reject_option()],
            "subject": {"type": "_future_subject", "someField": "value"},
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}


@pytest.mark.asyncio
async def test_handle_request_permission_accepts_a_valid_tool_call_subject() -> None:
    coordinator = _make_coordinator()

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Approve this tool call?",
            "options": [_reject_option()],
            "subject": {
                "type": "tool_call",
                "toolCall": {
                    "toolCallId": "call-1",
                    "kind": "execute",
                    "status": "pending",
                    "title": "Run the test suite",
                },
            },
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}


@pytest.mark.asyncio
async def test_handle_request_permission_accepts_a_valid_command_subject() -> None:
    coordinator = _make_coordinator()

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Run this command?",
            "options": [_reject_option()],
            "subject": {"type": "command", "command": "pytest", "cwd": "/workspace/project"},
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}


@pytest.mark.asyncio
async def test_handle_request_permission_rejects_a_command_subject_with_a_relative_cwd() -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission(
            {
                "sessionId": "session-1",
                "title": "Run this command?",
                "options": [_reject_option()],
                "subject": {"type": "command", "command": "pytest", "cwd": "relative/path"},
            }
        )
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_request_permission_rejects_a_tool_call_subject_missing_tool_call_id() -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission(
            {
                "sessionId": "session-1",
                "title": "Approve this tool call?",
                "options": [_reject_option()],
                "subject": {"type": "tool_call", "toolCall": {}},
            }
        )
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_request_permission_rejects_a_mismatched_session_id() -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission(
            {"sessionId": "some-other-session", "title": "Approve?", "options": [_reject_option()]}
        )
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_request_permission_rejects_a_missing_title() -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission({"sessionId": "session-1", "options": [_reject_option()]})
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"title": "x" * 513, "options": [_reject_option()]},
        {"title": "Approve?", "description": "x" * 2_049, "options": [_reject_option()]},
        {
            "title": "Approve?",
            "options": [_reject_option("x" * 257)],
        },
        {
            "title": "Approve?",
            "options": [_reject_option()],
            "subject": {"type": "command", "command": "x" * 4_097, "cwd": "/workspace"},
        },
    ],
)
async def test_handle_request_permission_rejects_overlong_provider_controlled_fields(params: dict) -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission({"sessionId": "session-1", **params})
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_request_permission_does_not_log_provider_controlled_text(caplog) -> None:
    coordinator = _make_coordinator()
    provider_title = "sensitive provider title"
    provider_option_id = "sensitive-provider-option-id"

    with caplog.at_level(logging.INFO):
        result = await coordinator.handle_request_permission(
            {
                "sessionId": "session-1",
                "title": provider_title,
                "options": [_reject_option(provider_option_id)],
            }
        )

    assert result == {"outcome": {"outcome": "selected", "optionId": provider_option_id}}
    assert provider_title not in caplog.text
    assert provider_option_id not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        [],
        None,
        "not-a-list",
        [{"optionId": "x", "name": "Reject", "kind": "reject_once", "extra": "field"}],
        [{"optionId": "", "name": "Reject", "kind": "reject_once"}],
        [{"optionId": "dup", "name": "Allow", "kind": "allow_once"}, {"optionId": "dup", "name": "Reject", "kind": "reject_once"}],
        [{"optionId": f"option-{i}", "name": "Reject", "kind": "reject_once"} for i in range(21)],
    ],
)
async def test_handle_request_permission_rejects_malformed_options(options) -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission(
            {"sessionId": "session-1", "title": "Approve?", "options": options}
        )
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_request_permission_rejects_params_that_are_not_an_object() -> None:
    coordinator = _make_coordinator()

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_request_permission("not-an-object")
    assert excinfo.value.code == -32602


def test_bind_session_rejects_a_second_different_session_id() -> None:
    coordinator = ProviderPermissionRequestCoordinator()
    coordinator.bind_session("session-1")

    with pytest.raises(ValueError):
        coordinator.bind_session("session-2")


def test_bind_session_is_idempotent_for_the_same_session_id() -> None:
    coordinator = ProviderPermissionRequestCoordinator()
    coordinator.bind_session("session-1")
    coordinator.bind_session("session-1")
