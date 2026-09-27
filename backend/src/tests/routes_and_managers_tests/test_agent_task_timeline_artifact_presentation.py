from api.routes.agent_tasks.projections.artifact_presentation import (
    build_agent_task_presentation_summary,
    normalize_file_entry,
)


def direct_write_entry(
    *,
    lifecycle: str = "verified",
    artifact_id: str = "file-0123456789abcdef01234567",
) -> dict:
    entry_id = f"artifact_{artifact_id}"
    return {
        "id": entry_id,
        "type": "artifact",
        "metadata": {
            "event_type": "agent_task_artifact",
            "raw_detail": True,
            "artifact": {
                "artifact_id": artifact_id,
                "display_name": "report.md",
                "local_path": "/private/fixture/report.md",
                "artifact_kind": "file",
                "operation": "create",
                "lifecycle": lifecycle,
                "preview": {"capability": "unknown"},
                "verification": {
                    "status": lifecycle,
                    "summary": "Selected verification evidence.",
                },
                "source_timeline_entry_id": entry_id,
                "source_step_id": "step-1",
                "content": "must not reach a summary",
                "command": "must not reach a summary",
                "receipt": {"digest": "must not reach a summary"},
            },
        },
    }


def test_summary_projects_only_a_valid_persisted_direct_write_artifact() -> None:
    persisted_entry = direct_write_entry()
    persisted_entry["metadata"]["artifact"]["review"] = {
        "revision": 2,
        "revision_count": 2,
        "kind": "markdown",
        "snapshot_status": "available",
    }
    summary = build_agent_task_presentation_summary(
        agent_task_id="task-1",
        lifecycle="processing",
        result_data={},
        execution_timeline=[persisted_entry],
        files=[],
    )

    assert summary["artifact_count"] == 1
    assert summary["verification_status"] == "resolved"
    assert summary["artifacts"] == [{
        "artifact_id": "file-0123456789abcdef01234567",
        "display_name": "report.md",
        "local_path": "/private/fixture/report.md",
        "artifact_kind": "file",
        "operation": "create",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": "Selected verification evidence.",
        },
        "source_timeline_entry_id": "artifact_file-0123456789abcdef01234567",
        "source_step_id": "step-1",
        "review": {
            "revision": 2,
            "revision_count": 2,
            "kind": "markdown",
            "snapshot_status": "available",
        },
    }]
    serialized = str(summary)
    assert "must not reach a summary" not in serialized
    assert "digest" not in serialized


def test_summary_merges_timeline_verification_into_a_matching_finalizer_artifact() -> None:
    finalizer_file = normalize_file_entry({
        "artifact_id": "finalizer-report",
        "name": "final-report.md",
        "full_path": "/private/fixture/report.md",
        "operation": "write",
        "kind": "file",
    })

    summary = build_agent_task_presentation_summary(
        agent_task_id="task-1",
        lifecycle="processing",
        result_data={},
        execution_timeline=[direct_write_entry()],
        files=[finalizer_file],
    )

    assert summary["artifact_count"] == 1
    assert summary["artifacts"] == [{
        "artifact_id": "finalizer-report",
        "display_name": "final-report.md",
        "local_path": "/private/fixture/report.md",
        "artifact_kind": "file",
        "operation": "write",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": "Selected verification evidence.",
        },
        "source_timeline_entry_id": "artifact_file-0123456789abcdef01234567",
        "source_step_id": "step-1",
    }]


def test_summary_ignores_malformed_or_uncorrelated_timeline_artifacts() -> None:
    malformed = direct_write_entry()
    malformed["metadata"]["artifact"]["source_timeline_entry_id"] = "different-entry"

    summary = build_agent_task_presentation_summary(
        agent_task_id="task-1",
        lifecycle="processing",
        result_data={},
        execution_timeline=[malformed],
        files=[],
    )

    assert summary["artifacts"] == []
    assert summary["artifact_count"] == 0
    assert summary["verification_status"] == "unknown"
