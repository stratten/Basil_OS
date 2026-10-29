"""How a scheduled run reads the result of the agent task it started.

A scheduled run is an ordinary agent task started by a different mechanism, so it has no statuses or outcomes of its own: the agent task's status and its finalizer outcome are the single source of truth. This module reads them the same way the web UI does (``deriveRunPhase`` in ``web-components/shared/runPhase.ts``): a task persisted as ``failed`` whose finalizer outcome is ``partial`` is a partial result, not a failure, and a result whose outcome verification is still ``pending`` is not final yet.

Pure functions only; no database or event access, so callers in the run executor, the run-history route, and the active-runs route share one reading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL = "partial"
OUTCOME_FAILED = "failed"

VERIFICATION_PENDING = "pending"

_VERIFIABLE_STATUSES = frozenset({"completed", "failed"})


@dataclass(frozen=True)
class TaskResultReading:
    """What a scheduled run needs to know about its agent task's result."""

    task_status: Optional[str]
    # ``success`` | ``partial`` | ``failed``; only meaningful once ``is_final`` is true and the task reached completed or failed.
    outcome: str
    # ``pending`` while the background outcome check has not finished; ``resolved`` afterwards; None for tasks that never set it.
    verification_status: Optional[str]
    # The finalizer's own explanation, for example ``Partial result: ...``.
    message: Optional[str]

    @property
    def is_final(self) -> bool:
        """False while a completed or failed result is still waiting for its background outcome check."""
        return not (self.task_status in _VERIFIABLE_STATUSES and self.verification_status == VERIFICATION_PENDING)


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _settled_outcome(task_status: Optional[str], raw_outcome: Any) -> str:
    from api.services.agent_processing.lifecycle.finalization.evaluation import normalize_outcome

    if isinstance(raw_outcome, str) and raw_outcome.strip().lower() == "completed_with_warnings":
        return OUTCOME_PARTIAL
    has_outcome = isinstance(raw_outcome, str) and bool(raw_outcome.strip())
    normalized = normalize_outcome(raw_outcome) if has_outcome else None
    if normalized == "partial":
        return OUTCOME_PARTIAL
    if task_status == "failed" or normalized == "failure":
        return OUTCOME_FAILED
    return OUTCOME_SUCCESS


def read_task_result_fields(task_status: Optional[str], result_data: Any) -> Dict[str, Optional[str]]:
    """The fields a surface needs to draw a run exactly as it draws any agent task, from a joined status and result_data."""
    reading = read_task_result({"status": task_status, "result_data": result_data})
    if reading.task_status is None:
        return {"agent_task_status": None, "outcome": None, "verification_status": None}
    return {
        "agent_task_status": task_status,
        "outcome": reading.outcome,
        "verification_status": reading.verification_status,
    }


def with_task_result_fields(run_row: Dict[str, Any]) -> Dict[str, Any]:
    """A run row from the repository with its raw ``agent_task_result_data`` replaced by the outcome fields a surface draws from."""
    return {
        **{key: value for key, value in run_row.items() if key != "agent_task_result_data"},
        **read_task_result_fields(run_row.get("agent_task_status"), run_row.get("agent_task_result_data")),
    }


def read_task_result(agent_task_data: Optional[Dict[str, Any]]) -> TaskResultReading:
    """Read a persisted agent task row (``status`` plus ``result_data``) the way the UI does."""
    data = agent_task_data or {}
    status = data.get("status")
    task_status = status.strip().lower() if isinstance(status, str) and status.strip() else None
    result_data = _as_dict(data.get("result_data"))
    finalizer = _as_dict(result_data.get("finalizer_result"))
    payload = _as_dict(finalizer.get("result_payload"))
    verification = payload.get("verification_status")
    message = result_data.get("error") or result_data.get("message")
    return TaskResultReading(
        task_status=task_status,
        outcome=_settled_outcome(task_status, finalizer.get("outcome")),
        verification_status=verification if isinstance(verification, str) else None,
        message=message if isinstance(message, str) and message.strip() else None,
    )
