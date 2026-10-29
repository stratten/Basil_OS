import pytest

from api.services.conversation.conversation_agent_activity_contract import (
    MAX_CONVERSATION_AGENT_ACTIVITY_ARTIFACTS,
    MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS,
    build_conversation_agent_activity_payload,
)


def summary(overrides: dict | None = None) -> dict:
    value = {
        "agent_task_id": "task-1",
        "lifecycle": "processing",
        "latest_activity": "Writing the requested report.",
        "workflow": {"completed_steps": 1, "total_steps": 3},
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "display_name": "report.md",
                "local_path": "/private/fixture/report.md",
                "artifact_kind": "file",
                "operation": "write",
                "lifecycle": "ready",
                "preview": {"capability": "supported", "kind": "markdown"},
                "verification": {"status": "verified", "summary": "Written successfully."},
                "source_timeline_entry_id": "timeline-1",
            }
        ],
        "artifact_count": 1,
        "verification_status": "resolved",
        "requires_user_attention": False,
    }
    if overrides:
        value.update(overrides)
    return value


def payload(source_summary: dict) -> dict:
    return build_conversation_agent_activity_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        summary=source_summary,
    )


def test_activity_payload_selects_compact_fields_without_local_file_authority() -> None:
    assert payload(summary()) == {
        "event_type": "conversation_agent_activity",
        "conversation_id": "conversation-1",
        "placeholder_message_id": "assistant-1",
        "agent_task_id": "task-1",
        "summary": {
            "agent_task_id": "task-1",
            "lifecycle": "processing",
            "latest_activity": "Writing the requested report.",
            "workflow": {"completed_steps": 1, "total_steps": 3},
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "display_name": "report.md",
                    "artifact_kind": "file",
                    "lifecycle": "ready",
                    "verification": {"status": "verified"},
                }
            ],
            "artifact_count": 1,
            "verification_status": "resolved",
            "requires_user_attention": False,
        },
    }


def test_activity_payload_bounds_visible_text_without_changing_identifier_correlation() -> None:
    source_summary = summary(
        {
            "latest_activity": "a" * (MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS + 1),
            "artifacts": [
                {
                    **summary()["artifacts"][0],
                    "display_name": "b" * (MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS + 1),
                }
            ],
        }
    )

    result = payload(source_summary)

    assert result["summary"]["latest_activity"] == "a" * MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS
    assert result["summary"]["artifacts"][0]["artifact_id"] == "artifact-1"
    assert result["summary"]["artifacts"][0]["display_name"] == "b" * MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS


@pytest.mark.parametrize(
    "lifecycle",
    (
        "capturing",
        "routing",
        "routed",
        "processing",
        "awaiting_provider_delegation",
        "awaiting_delegated_agents",
        "awaiting_user_input",
        "paused",
        "waiting_user_input",
        "needs_clarification",
        "clarification_added",
        "completed",
        "failed",
        "canceled",
    ),
)
def test_activity_payload_accepts_supported_task_lifecycles_and_empty_workflow(lifecycle: str) -> None:
    result = payload(summary({"lifecycle": lifecycle, "workflow": {}}))

    assert result["summary"]["lifecycle"] == lifecycle
    assert result["summary"]["workflow"] == {}


@pytest.mark.parametrize(
    ("kwargs", "source_summary", "message"),
    [
        ({"conversation_id": ""}, summary(), "conversation_id must be a non-empty string"),
        ({"placeholder_message_id": ""}, summary(), "placeholder_message_id must be a non-empty string"),
        ({"agent_task_id": "other-task"}, summary(), "summary.agent_task_id must match agent_task_id"),
    ],
)
def test_activity_payload_rejects_invalid_or_cross_linked_identifiers(
    kwargs: dict,
    source_summary: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_conversation_agent_activity_payload(
            conversation_id=kwargs.get("conversation_id", "conversation-1"),
            placeholder_message_id=kwargs.get("placeholder_message_id", "assistant-1"),
            agent_task_id=kwargs.get("agent_task_id", "task-1"),
            summary=source_summary,
        )


@pytest.mark.parametrize(
    ("source_summary", "message"),
    [
        (summary({"workflow": {"completed_steps": 2, "total_steps": 1}}), "completed_steps cannot exceed total_steps"),
        (summary({"workflow": {"completed_steps": 1}}), "summary.workflow must provide both step counts"),
        (summary({"artifact_count": True}), "summary.artifact_count must be a non-negative integer"),
        (summary({"requires_user_attention": "yes"}), "summary.requires_user_attention must be a boolean"),
        (summary({"verification_status": "verified"}), "summary.verification_status is not supported"),
    ],
)
def test_activity_payload_rejects_malformed_summary_fields(source_summary: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        payload(source_summary)


def test_activity_payload_rejects_an_over_limit_or_malformed_artifact_list() -> None:
    artifact = summary()["artifacts"][0]
    over_limit_summary = summary(
        {
            "artifacts": [artifact] * (MAX_CONVERSATION_AGENT_ACTIVITY_ARTIFACTS + 1),
            "artifact_count": MAX_CONVERSATION_AGENT_ACTIVITY_ARTIFACTS + 1,
        }
    )
    malformed_artifact_summary = summary(
        {
            "artifacts": [{**artifact, "verification": {"status": "not-a-status"}}],
        }
    )

    with pytest.raises(ValueError, match="summary.artifacts exceeds the artifact limit"):
        payload(over_limit_summary)
    with pytest.raises(ValueError, match=r"summary.artifacts\[\].verification.status is not supported"):
        payload(malformed_artifact_summary)


def test_activity_payload_rejects_count_smaller_than_the_emitted_artifact_list() -> None:
    with pytest.raises(ValueError, match="summary.artifact_count cannot be less than emitted artifacts"):
        payload(summary({"artifact_count": 0}))
