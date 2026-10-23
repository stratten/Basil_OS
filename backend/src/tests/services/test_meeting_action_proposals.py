from datetime import datetime

from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    AnalysisMode,
    MeetingAnalysisResult,
)
from api.services.whisper_live_core.post_processing.meeting_analyzer import MeetingAnalyzer


def test_suggested_action_proposals_get_backend_ids_and_defaults() -> None:
    analyzer = MeetingAnalyzer("meeting-action-proposal-test")

    proposals = analyzer._build_action_proposals([
        {
            "source_action_item_indexes": [0],
            "source_action_item_index": 0,
            "source_task": "Follow up with Alex about the launch checklist.",
            "source_context": "Speaker 1: I'll follow up with Alex about the launch checklist.",
            "source_timestamp": 42.0,
            "source_speaker": "Speaker 1",
            "suggested_agent_task": "Draft a follow-up email to Alex about the launch checklist.",
            "capability_type": "email_draft",
            "confidence": 1.2,
            "why_basil_can_help": "Basil can draft the follow-up from the meeting context.",
            "missing_information": ["Alex email address"],
            "disposition": "todo_candidate",
            "execution_mode": "agent_assisted",
        }
    ])

    assert len(proposals) == 1
    assert proposals[0].id
    assert proposals[0].confidence == 1.0
    assert proposals[0].workspace_source == "meeting_analysis"
    assert proposals[0].execution_status == "proposed"
    assert proposals[0].requires_user_confirmation is True
    assert proposals[0].source_action_item_indexes == [0]
    assert proposals[0].execution_mode == "agent_assisted"


def test_meeting_analysis_result_serializes_suggested_actions() -> None:
    analyzer = MeetingAnalyzer("meeting-action-proposal-test")
    proposals = analyzer._build_action_proposals([
        {
            "source_task": "Create a reminder to review the proposal.",
            "suggested_agent_task": "Create a reminder to review the proposal tomorrow.",
            "capability_type": "reminder",
            "confidence": 0.8,
            "why_basil_can_help": "Basil can create reminder-style follow-up tasks.",
            "disposition": "todo_candidate",
        }
    ])

    result = MeetingAnalysisResult(
        meeting_id="meeting-action-proposal-test",
        analyzed_at=datetime.utcnow(),
        model_used="test-model",
        modes_analyzed=[AnalysisMode.SUGGESTED_ACTIONS.value],
        suggested_actions=proposals,
        transcript_duration=120.0,
        speaker_count=2,
        processing_time=1.0,
    )

    serialized = result.to_dict()

    assert AnalysisMode.SUGGESTED_ACTIONS.value in result.get_completed_modes()
    assert serialized["suggested_actions"][0]["workspace_source"] == "meeting_analysis"
    assert serialized["suggested_actions"][0]["suggested_agent_task"].startswith("Create a reminder")
    assert serialized["suggested_actions"][0]["execution_mode"] == "agent_assisted"


def test_build_action_proposals_discards_resolved_and_non_actionable_drafts() -> None:
    analyzer = MeetingAnalyzer("meeting-action-proposal-test")
    proposals = analyzer._build_action_proposals(
        [
            {
                "source_task": "Open follow-up",
                "suggested_agent_task": "Document the remaining steps.",
                "capability_type": "todo",
                "confidence": 0.8,
                "why_basil_can_help": "This needs to remain visible.",
                "disposition": "todo_candidate",
            },
            {
                "source_task": "Completed follow-up",
                "suggested_agent_task": "No further work is needed.",
                "capability_type": "todo",
                "confidence": 0.8,
                "why_basil_can_help": "This work is complete.",
                "disposition": "completed_or_resolved",
            },
            {
                "source_task": "Informational note",
                "suggested_agent_task": "No action is available.",
                "capability_type": "todo",
                "confidence": 0.8,
                "why_basil_can_help": "This is not actionable.",
                "disposition": "non_actionable",
            },
        ]
    )

    assert [proposal.source_task for proposal in proposals] == ["Open follow-up"]


def test_build_action_proposals_preserves_grouped_source_indexes_in_stable_order() -> None:
    analyzer = MeetingAnalyzer("meeting-action-proposal-test")
    draft = {
        "source_action_item_indexes": [4, 2, 4, 7],
        "source_task": "Complete the Commission automation guardrails.",
        "suggested_agent_task": "1. Confirm relationship deletion.\n2. Handle field transfers.",
        "capability_type": "automation",
        "confidence": 0.9,
        "why_basil_can_help": "This is one cohesive system change.",
        "disposition": "todo_candidate",
        "execution_mode": "agent_assisted",
    }

    first = analyzer._build_action_proposals([draft])[0]
    second = analyzer._build_action_proposals([draft])[0]

    assert first.source_action_item_indexes == [4, 2, 7]
    assert first.source_action_item_index == 4
    assert first.id == second.id
