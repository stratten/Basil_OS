"""Direct unit coverage for agent_task_to_work_attempt's outcome/severity projection."""

from types import SimpleNamespace

from api.services.todos.records import agent_task_to_work_attempt


def _agent_task(**overrides):
    defaults = dict(
        id="task-1",
        title="Draft the follow-up emails",
        status="completed",
        timestamp=None,
        result_data={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_true_success_maps_to_success_severity_with_no_partial_label():
    attempt = agent_task_to_work_attempt(_agent_task(status="completed", result_data={"message": "Done."}))

    assert attempt.status == "completed"
    assert attempt.outcome is None
    assert attempt.result_severity == "success"
    assert attempt.result_summary == "Done."


def test_partial_outcome_is_distinguished_from_a_true_failure_despite_shared_failed_status():
    result_data = {
        "finalizer_result": {"result_payload": {"outcome": "partial"}},
        "message": "Drafted 3 of 5 requested emails; two recipients had no address on file.",
    }
    attempt = agent_task_to_work_attempt(_agent_task(status="failed", result_data=result_data))

    assert attempt.status == "failed"
    assert attempt.outcome == "partial"
    assert attempt.result_severity == "warning"
    assert "Drafted 3 of 5" in attempt.result_summary


def test_true_failure_still_reports_error_severity():
    result_data = {
        "finalizer_result": {"result_payload": {"outcome": "failure"}},
        "error": "Provider timed out after 3 attempts.",
    }
    attempt = agent_task_to_work_attempt(_agent_task(status="failed", result_data=result_data))

    assert attempt.outcome == "failure"
    assert attempt.result_severity == "error"
    assert attempt.result_summary == "Provider timed out after 3 attempts."


def test_missing_result_data_falls_back_to_status_derived_severity_without_raising():
    attempt = agent_task_to_work_attempt(_agent_task(status="canceled", result_data=None))

    assert attempt.outcome is None
    assert attempt.result_severity == "neutral"
