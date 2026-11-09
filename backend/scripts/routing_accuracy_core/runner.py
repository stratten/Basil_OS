"""Drive one routing case against the running backend: submit, watch the ledger, stop at the routing decision, and score it.

Every task runs with approvals set to always prompt, so the model stops at the first command or script it wants to run.
A card the backend's classifiers prove read-only (see read_only_gate) is approved so the run can continue past a harmless read.
Any other pending approval card is scored as the model's call, then denied and the task canceled, so a wrong route cannot execute anything that is not provably a read.
Denying inside the run is deliberately not used: a denied command pushes the model into recovery routes (for example AppleScript wrapping the same shell command), which says nothing about its first choice.
For runs that never reach an approval, the task is canceled once the routing window is full, which keeps a cloud run cheap and stops a local model from carrying on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from .cases import RoutingCase
from .ledger_reader import read_receipts
from .read_only_gate import MAX_AUTO_APPROVALS_PER_CASE, judge_approval
from .route_tokens import (
    DEFAULT_WINDOW_SIZE,
    INCOMPLETE,
    Receipt,
    RoutingVerdict,
    receipt_from_pending_approval,
    score_route,
    substantive_window,
)

BASE_URL = "http://127.0.0.1:8000"
ACTIVE_STATUSES = frozenset({"routing", "processing", "planning", "queued", "executing", "running", "in_progress", "pending", "starting"})
# A task that ended this way never answered, so "no tools were used" says nothing about its routing. It is scored INCOMPLETE, not as an answer without tools.
ENDED_WITHOUT_ANSWER_STATUSES = frozenset({"canceled", "failed", "error"})
# A task stopped on an Input required card is not finished: it is waiting for the owner. The check must cancel it, or it stays open indefinitely.
WAITING_FOR_INPUT_STATUSES = frozenset({"awaiting_user_input"})
# The check normally denies the card within a second of seeing it. The timeout is only a backstop so a card from a task that did not stop expires by itself instead of waiting for the owner to approve it.
PAUSE_AT_APPROVAL_OVERRIDE: dict[str, Any] = {
    "approval_mode": "always_prompt",
    "timeout_behavior": "deny_on_timeout",
    "approval_timeout_seconds": 30,
}


class BackendClient:
    """The few agent-task endpoints the check needs. The token is read from the host credentials and never printed."""

    def __init__(self, token: Optional[str] = None, base_url: str = BASE_URL) -> None:
        if token is None:
            from api.core.security.backend_credentials import load_host_token

            token = load_host_token()
        self._token = token
        self._base_url = base_url

    def _headers(self) -> dict[str, str]:
        from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER

        return {BACKEND_TOKEN_HEADER: self._token}

    def healthy(self) -> bool:
        try:
            return requests.get(f"{self._base_url}/docs", headers=self._headers(), timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def submit(self, prompt: str, model_id: str, reference_paths: Optional[list[str]]) -> str:
        body: dict[str, Any] = {"agent_task": prompt, "model_id": model_id, "approval_policy_override": PAUSE_AT_APPROVAL_OVERRIDE}
        if reference_paths:
            body["reference_paths"] = reference_paths
        response = requests.post(f"{self._base_url}/api/v1/agent-tasks/process", json=body, headers=self._headers(), timeout=30)
        response.raise_for_status()
        task_id = response.json().get("agent_task_id")
        if not task_id:
            raise RuntimeError("the backend accepted the task but returned no agent_task_id")
        return str(task_id)

    def status(self, task_id: str) -> str:
        response = requests.get(f"{self._base_url}/api/v1/agent-tasks/{task_id}", headers=self._headers(), timeout=15)
        response.raise_for_status()
        return str(response.json().get("status") or "")

    def pending_approvals(self, task_id: str) -> list[dict[str, Any]]:
        response = requests.get(f"{self._base_url}/api/v1/agent-tasks/{task_id}/execution-approvals/pending", headers=self._headers(), timeout=15)
        response.raise_for_status()
        approvals = response.json().get("approvals")
        return [a for a in approvals if isinstance(a, dict)] if isinstance(approvals, list) else []

    def _decide(self, task_id: str, approval: dict[str, Any], approved: bool) -> None:
        # remember_choice is left at its default (false) so a decision made by the check never becomes a standing approval.
        body = {
            "approval_id": approval.get("approval_id"),
            "command": approval.get("command") or "",
            "approved": approved,
            "agent_task_id": task_id,
            "expected_revision": approval.get("revision"),
        }
        requests.post(f"{self._base_url}/api/v1/agent-tasks/approval/decide", json=body, headers=self._headers(), timeout=30).raise_for_status()

    def deny_approval(self, task_id: str, approval: dict[str, Any]) -> None:
        self._decide(task_id, approval, False)

    def approve_approval(self, task_id: str, approval: dict[str, Any]) -> None:
        self._decide(task_id, approval, True)

    def cancel(self, task_id: str) -> None:
        """Cancel the task. The route requires a JSON body, and a refusal must surface: an unchecked 422 once left every canceled task running."""
        response = requests.post(
            f"{self._base_url}/api/v1/agent-tasks/sessions/{task_id}/cancel", json={"reason": "routing accuracy check"}, headers=self._headers(), timeout=30
        )
        response.raise_for_status()

    def delete_task(self, task_id: str) -> None:
        """Delete one task through the app's own delete route (it cancels first). A task that is already gone counts as deleted."""
        response = requests.delete(f"{self._base_url}/api/v1/agent-tasks/{task_id}", params={"cascade": "false"}, headers=self._headers(), timeout=60)
        if response.status_code not in (200, 404):
            response.raise_for_status()

    def connection_id_by_name(self, friendly_name: str) -> Optional[str]:
        """Look a connected service up by its display name in the connection inventory. Only the id and name are read; no credential is involved."""
        response = requests.get(f"{self._base_url}/settings/connections", headers=self._headers(), timeout=15)
        response.raise_for_status()
        matches = [c for c in response.json().get("connections", []) if c.get("friendly_name") == friendly_name]
        return str(matches[0]["id"]) if len(matches) == 1 else None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    model_id: str
    task_id: str
    verdict: RoutingVerdict
    final_status: str
    seconds: float
    canceled_by_check: bool
    error: str = ""
    still_running: bool = False  # the task was still active after cancel and the settle wait, so the sweep must not start another case
    auto_approved: int = 0  # read-only cards the gate approved so the run could continue


def _is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def _is_open(status: str) -> bool:
    """True while a task is running or waiting on the owner, that is, until it has ended."""
    return status in ACTIVE_STATUSES or status in WAITING_FOR_INPUT_STATUSES


def _stop_task(client: BackendClient, task_id: str, approvals: list[dict[str, Any]]) -> None:
    """Deny every pending approval so nothing executes and no card is left open, then cancel the task. Each step is tried even if an earlier one fails."""
    for approval in approvals:
        try:
            client.deny_approval(task_id, approval)
        except Exception:  # noqa: BLE001 - the cancel below still has to run
            pass
    client.cancel(task_id)


def _release_read_only(client: BackendClient, task_id: str, pending: list[dict[str, Any]], released_ids: set[str]) -> list[dict[str, Any]]:
    """Approve each pending card the gate proves read-only, and return the cards that still block the run.

    A card approved on an earlier poll can still be listed until the backend clears it; it is skipped, neither approved again nor counted as blocking.
    """
    blocking: list[dict[str, Any]] = []
    for approval in pending:
        approval_id = str(approval.get("approval_id") or "")
        if approval_id in released_ids:
            continue
        if len(released_ids) < MAX_AUTO_APPROVALS_PER_CASE and judge_approval(approval).approve:
            client.approve_approval(task_id, approval)
            released_ids.add(approval_id)
        else:
            blocking.append(approval)
    return blocking


def run_case(
    client: BackendClient,
    case: RoutingCase,
    model_id: str,
    fixture_dir: Optional[Path],
    database_path: Path,
    window_size: int = DEFAULT_WINDOW_SIZE,
    case_timeout_s: float = 240.0,
    settle_timeout_s: float = 90.0,
    poll_interval_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> CaseResult:
    """Run one case and score it. Harness faults come back as an INCOMPLETE result with ``error`` set, never as a routing failure."""
    started = time.monotonic()
    prompt = case.render_prompt(str(fixture_dir) if fixture_dir else None)
    references = [str(fixture_dir)] if (case.attach_fixture and fixture_dir) else None
    task_id = ""
    approvals: list[dict[str, Any]] = []
    released_ids: set[str] = set()
    canceled = False
    try:
        task_id = client.submit(prompt, model_id, references)
        deadline = started + case_timeout_s
        finished = False
        status = ""
        scored: list[Receipt] = []
        while time.monotonic() < deadline:
            status = client.status(task_id)
            pending = client.pending_approvals(task_id)
            approvals = _release_read_only(client, task_id, pending, released_ids)
            scored = read_receipts(database_path, task_id) + [receipt_from_pending_approval(a) for a in approvals]
            finished = not pending and not _is_active(status)
            if approvals or finished or len(substantive_window(scored, window_size)) >= window_size:
                break
            sleep(poll_interval_s)
        decided_status = status
        if not finished or decided_status in WAITING_FOR_INPUT_STATUSES:
            _stop_task(client, task_id, approvals)
            canceled = True
            settle_deadline = time.monotonic() + settle_timeout_s
            while time.monotonic() < settle_deadline:
                status = client.status(task_id)
                if not _is_open(status):
                    break
                sleep(poll_interval_s)
        blocked = bool(approvals)
        window_full = len(substantive_window(scored, window_size)) >= window_size
        # The verdict uses the status the run reached, not the status after the check canceled it: a model that stopped to ask a question was not canceled by the model.
        answered = finished and decided_status not in ENDED_WITHOUT_ANSWER_STATUSES
        verdict = score_route(case.expectation, scored, run_finished=answered or window_full or blocked, window_size=window_size)
        return CaseResult(
            case.case_id, case.category, model_id, task_id, verdict, status, time.monotonic() - started, canceled,
            still_running=_is_open(status), auto_approved=len(released_ids),
        )
    except Exception as exc:  # noqa: BLE001 - any harness fault must surface as an error row, not abort the sweep
        if task_id and not canceled:
            try:
                _stop_task(client, task_id, approvals)
            except Exception:  # noqa: BLE001 - the original fault is what gets reported
                pass
        empty = RoutingVerdict(INCOMPLETE, "harness error", (), (), 0, 0)
        return CaseResult(case.case_id, case.category, model_id, task_id, empty, "", time.monotonic() - started, canceled, f"{type(exc).__name__}: {exc}")
