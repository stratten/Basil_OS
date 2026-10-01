from api.services.agent_processing.lifecycle.execution_graph.activity_progress_callback import (
    ActivityProgressCallbackHandler,
)
from api.services.agent_processing.lifecycle.runtime.agent_timeline_contract import (
    attach_progress_metadata,
    build_timeline_event,
    normalize_timeline_entry,
)
from api.services.agent_processing.lifecycle.runtime.workflow_status_notifier import (
    WorkflowStatusNotifier,
)


def test_normalize_timeline_entry_preserves_legacy_fields_and_sanitizes_title():
    legacy = {
        "type": "custom_event",
        "legacy_payload": {"nested": object()},
        "summary": "unsafe\nprogress",
    }

    entry = normalize_timeline_entry(
        legacy,
        phase="routing",
        state="started",
        source="unit_test",
        correlation_id="run-1",
    )

    assert entry["id"]
    assert entry["timestamp"]
    assert entry["title"] == "unsafe progress"
    assert entry["legacy_payload"]["nested"].startswith("<object object")
    assert entry["phase"] == "routing"
    assert entry["correlation_id"] == "run-1"


def test_notifier_adds_complete_timeline_entry_without_removing_legacy_payload():
    notifier = WorkflowStatusNotifier(agent_task_id="task-1")
    message = {
        "event_type": "dynamic_step_added",
        "description": "Read\nprivate input",
        "status": "in_progress",
        "step_id": "step-1",
        "legacy_field": "still-present",
    }

    notifier._prepare_frontend_notification(message)

    assert message["legacy_field"] == "still-present"
    assert message["timeline_entry"]["id"]
    assert message["timeline_entry"]["title"] == "Read private input"
    assert message["timeline_entry"]["correlation_id"] == "step-1"


def test_normalize_mirrors_phase_state_title_into_progress_metadata():
    entry = normalize_timeline_entry(
        {"summary": "Reading screen context"},
        phase="routing",
        state="started",
        title="Reading screen context",
    )

    assert entry["metadata"]["progress_phase"] == "routing"
    assert entry["metadata"]["progress_status"] == "started"
    assert entry["metadata"]["progress_step"] == "Reading screen context"


def test_normalize_does_not_overwrite_caller_supplied_progress_metadata():
    entry = normalize_timeline_entry(
        {
            "summary": "Searching data",
            "metadata": {
                "progress_step": "Explicit step",
                "progress_phase": "execution",
                "progress_current": 2,
                "progress_total": 8,
            },
        },
        phase="routing",
        state="in_progress",
    )

    # Caller-supplied values win over the canonical mirror.
    assert entry["metadata"]["progress_step"] == "Explicit step"
    assert entry["metadata"]["progress_phase"] == "execution"
    # Count fields are preserved untouched.
    assert entry["metadata"]["progress_current"] == 2
    assert entry["metadata"]["progress_total"] == 8
    # The state mirror still lands because the caller did not supply one.
    assert entry["metadata"]["progress_status"] == "in_progress"


def test_normalize_skips_progress_metadata_for_raw_detail_entries():
    entry = normalize_timeline_entry(
        {
            "summary": "Ran shell command",
            "detail_kind": "tool_result",
            "metadata": {"raw_detail": True},
        },
        phase="execution",
        state="completed",
    )

    assert entry["metadata"]["raw_detail"] is True
    assert "progress_phase" not in entry["metadata"]
    assert "progress_step" not in entry["metadata"]
    assert "progress_status" not in entry["metadata"]


def test_attach_progress_metadata_returns_early_for_raw_detail():
    metadata = {"raw_detail": True}
    result = attach_progress_metadata(metadata, phase="execution", state="completed", step="Ran tool")

    assert result is metadata
    assert result == {"raw_detail": True}


def test_build_timeline_event_carries_progress_metadata_mirror():
    event = build_timeline_event(
        {"summary": "Analyzing request"},
        phase="routing",
        state="started",
    )

    assert event["timeline_entry"]["metadata"]["progress_phase"] == "routing"
    assert event["timeline_entry"]["metadata"]["progress_step"] == "Analyzing request"
    # The legacy top-level mirror on the event is retained.
    assert event["metadata"]["progress_phase"] == "routing"


def test_notifier_persisted_progress_entries_carry_execution_phase(monkeypatch):
    import asyncio

    from api.services.agent_processing.lifecycle.runtime import (
        workflow_status_notifier as wsn,
    )

    captured: list = []

    async def _capture(agent_task_id, entry, replace_existing=False):
        captured.append(entry)

    monkeypatch.setattr(wsn, "persist_timeline_entry", _capture)

    notifier = WorkflowStatusNotifier(agent_task_id="task-progress")

    async def _run():
        await notifier.send_agent_progress_update("Reading inbox", details="scan")
        await notifier.send_dynamic_step_added("todo-1", "Draft reply")
        await notifier.send_dynamic_step_updated(
            "todo-1",
            "Draft reply",
            "completed",
            completion_message="Reply drafted",
            step_id="step-1",
        )
        await notifier.send_step_detail_update({"id": "d1", "summary": "raw tool output"})

    asyncio.run(_run())

    assert len(captured) == 4
    progress_entries, detail_entry = captured[:3], captured[3]

    # Persistence stamps phase="execution"; normalize then mirrors progress_*.
    for raw in progress_entries:
        normalized = normalize_timeline_entry(raw)
        assert normalized["metadata"]["progress_phase"] == "execution"
        assert normalized["metadata"]["progress_step"]

    # Tray details persist with raw_detail and are excluded from the progress mirror.
    detail_normalized = normalize_timeline_entry(detail_entry)
    assert detail_normalized["metadata"]["raw_detail"] is True
    assert "progress_phase" not in detail_normalized["metadata"]
    assert "progress_step" not in detail_normalized["metadata"]


def test_progress_callback_uses_static_safe_tool_descriptors():
    callback = ActivityProgressCallbackHandler.__new__(ActivityProgressCallbackHandler)

    title = callback._extract_rich_task_description(
        "shell_service_execute",
        {"path": "report\nwith-private-details.txt"},
    )

    assert title == "Running project command: report with-private-details.txt"


class _RecordingNotifier:
    def __init__(self):
        self.entries = []

    async def send_step_detail_update(self, entry):
        self.entries.append(entry)


def _tool_error_phase(error):
    import asyncio

    callback = ActivityProgressCallbackHandler.__new__(ActivityProgressCallbackHandler)
    callback.notifier = _RecordingNotifier()
    callback._activity_correlation_id = "agent_run_test"
    callback._step_ids_by_run = {}
    callback._tool_run_registry = None
    callback.logger = None
    asyncio.run(callback.on_tool_error(error))
    (entry,) = callback.notifier.entries
    return entry


def test_input_request_is_recorded_as_completed_tool_phase_not_failure():
    from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

    entry = _tool_error_phase(CheckpointRequest({"prompt": "Pick one"}))

    assert entry["metadata"]["progress_phase"] == "tool_execution"
    assert entry["metadata"]["progress_status"] == "completed"
    assert entry["metadata"]["progress_step"] == "Requested your input"
    assert entry["metadata"]["error"] is None


def test_real_tool_error_is_still_recorded_as_failed_tool_phase():
    entry = _tool_error_phase(RuntimeError("disk unavailable"))

    assert entry["metadata"]["progress_status"] == "failed"
    assert entry["metadata"]["progress_step"] == "Approved tool failed"
    assert entry["metadata"]["error"] == "disk unavailable"


def test_normalize_json_safely_copies_mapping_artifact_metadata():
    receipt_marker = object()
    unknown_marker = object()
    source_artifact = {
        "artifact_id": "artifact-1",
        "display_name": "report.md",
        "preview": {"capability": "supported", "kind": "markdown"},
        "verification": {"status": "verified", "receipt": receipt_marker},
        "unknown_producer_field": {"nested": unknown_marker},
    }

    entry = normalize_timeline_entry(
        {
            "summary": "Created report",
            "metadata": {"artifact": source_artifact},
        }
    )

    artifact = entry["metadata"]["artifact"]
    assert artifact is not source_artifact
    assert artifact["artifact_id"] == "artifact-1"
    assert artifact["display_name"] == "report.md"
    assert artifact["preview"] == {"capability": "supported", "kind": "markdown"}
    assert artifact["verification"]["status"] == "verified"
    assert artifact["verification"]["receipt"].startswith("<object object")
    assert artifact["unknown_producer_field"]["nested"].startswith("<object object")
    assert source_artifact["verification"]["receipt"] is receipt_marker
    assert source_artifact["unknown_producer_field"]["nested"] is unknown_marker


def test_normalize_retains_non_mapping_legacy_artifact_metadata():
    entry = normalize_timeline_entry(
        {
            "summary": "Legacy artifact event",
            "metadata": {"artifact": "legacy-opaque-artifact"},
        }
    )

    assert entry["metadata"]["artifact"] == "legacy-opaque-artifact"


def test_normalize_artifact_metadata_preserves_raw_detail_progress_opt_out():
    entry = normalize_timeline_entry(
        {
            "summary": "Raw artifact detail",
            "metadata": {
                "raw_detail": True,
                "artifact": {"artifact_id": "artifact-raw", "nested": object()},
            },
        },
        phase="execution",
        state="completed",
    )

    assert entry["metadata"]["artifact"]["artifact_id"] == "artifact-raw"
    assert entry["metadata"]["artifact"]["nested"].startswith("<object object")
    assert "progress_phase" not in entry["metadata"]
    assert "progress_step" not in entry["metadata"]
    assert "progress_status" not in entry["metadata"]
