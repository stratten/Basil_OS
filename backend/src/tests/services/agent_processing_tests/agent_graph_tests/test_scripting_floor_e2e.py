"""E2E regression: specialized tool stuck -> scripting fallback floor.

Requires a configured email client, a reachable reasoning model, and real app
services. Opt-in via the ``e2e`` marker (``pytest -m e2e``).

Driven over HTTP against the already-running backend (like
tool_scenarios_live.py) rather than in-process via process_agent_task_direct.
The in-process form previously used here shares this test process's asyncio
event loop with the full agent-task pipeline it exercises (LLM calls,
fire-and-forget background tasks such as title generation); those
unawaited/lingering tasks kept the loop alive well past the test's own
assertions, so pytest-asyncio's teardown would hang indefinitely even after
the test had already passed. Going over HTTP means this test process only
ever does blocking `requests` calls and a read-only sqlite query -- nothing
it does can leave background work scheduled on its own event loop.
"""

import asyncio
import sys
from pathlib import Path

import pytest
import requests

_SCRIPTS_DIR = Path(__file__).resolve().parents[5] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from api.dependencies import get_sqlite_knowledge_service  # noqa: E402
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (  # noqa: E402
    EmailClientService,
)
from model_scenario_smoke_core.ledger_evidence import invoked_service_methods  # noqa: E402
from tool_scenarios_live import (  # noqa: E402
    BASE_URL,
    RAN_STATUSES,
    _health_check,
    _poll_until_terminal,
    _submit,
)

_HEADER_PROMPT = (
    "Inspect the raw headers of my most recent email and tell me whether the "
    "sender looks spoofed or like a phishing attempt."
)
_POLL_TIMEOUT_SECONDS = 240.0


@pytest.mark.e2e
@pytest.mark.manual
def test_scripting_floor_recovers_when_specialized_tool_cannot_read_headers():
    """Regression for the motivating arc: email tools do not expose raw headers,
    so the agent must fall back to scripting instead of declaring defeat."""
    clients = asyncio.run(EmailClientService().detect_email_clients())
    if not clients:
        pytest.skip("no email client configured")

    if not _health_check():
        pytest.skip(f"backend not reachable at {BASE_URL}; start it before running this e2e test")

    submission = _submit(_HEADER_PROMPT, model_id=None, approval_override={"approval_mode": "always_approve"})
    agent_task_id = submission.get("agent_task_id")
    assert agent_task_id, f"no agent_task_id in submission result: {submission}"

    final_status = _poll_until_terminal(agent_task_id, timeout_s=_POLL_TIMEOUT_SECONDS)
    status = final_status.get("status") or ("timeout" if final_status.get("_timed_out") else "unknown")
    assert status in RAN_STATUSES, (
        f"task did not run to completion within {_POLL_TIMEOUT_SECONDS:.0f}s: "
        f"status={status} detail={final_status}"
    )

    database_path = Path(get_sqlite_knowledge_service().db_path)
    invoked = invoked_service_methods(database_path, agent_task_id)
    scripting_invoked = any(
        str(service_name).startswith(("applescript", "shell"))
        for service_name, _method in invoked
    )
    email_used = any(
        str(service_name).startswith("email")
        for service_name, _method in invoked
    )
    specialized_success = email_used and status in {"completed", "completed_with_warnings"}

    assert scripting_invoked or specialized_success, (
        "regression: task completed without attempting scripting and without "
        f"a successful specialized email path. invoked={sorted(invoked)!r} status={status!r}"
    )
