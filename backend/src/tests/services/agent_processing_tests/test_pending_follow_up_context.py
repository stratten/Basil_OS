"""The outcome evaluator is told about durable follow-up checks that already cover pending work."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.finalization.pending_follow_up_context import (
    MAX_INSTRUCTIONS_CHARS,
    MAX_LISTED_FOLLOW_UPS,
    pending_follow_up_context,
    render_pending_follow_up_context,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)


class _Repository:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error
        self.requested_roots = []

    async def list_for_root(self, root_task_id):
        self.requested_roots.append(root_task_id)
        if self.error:
            raise self.error
        return self.rows


def _row(status="scheduled", instructions="Check the run.", due_at="2026-10-12T15:00:00+00:00"):
    return {"status": status, "instructions": instructions, "due_at": due_at}


def test_only_scheduled_rows_are_rendered():
    block = render_pending_follow_up_context(
        [_row(), _row(status="canceled", instructions="old"), _row(status="missed", instructions="gone")]
    )
    assert "Check the run." in block
    assert "old" not in block and "gone" not in block
    assert "2026-10-12T15:00:00+00:00" in block


def test_no_pending_rows_yields_no_block():
    assert render_pending_follow_up_context([]) is None
    assert render_pending_follow_up_context([_row(status="submitted"), _row(status="canceled")]) is None


def test_long_instructions_and_many_rows_are_bounded():
    rows = [_row(instructions="x" * 5000) for _ in range(MAX_LISTED_FOLLOW_UPS + 3)]
    block = render_pending_follow_up_context(rows)
    assert block.count("- due ") == MAX_LISTED_FOLLOW_UPS
    assert "x" * (MAX_INSTRUCTIONS_CHARS + 1) not in block


@pytest.mark.asyncio
async def test_context_uses_the_chain_root_from_the_running_context():
    repository = _Repository([_row()])
    token = set_current_agent_context({"root_task_id": "root-1"})
    try:
        block = await pending_follow_up_context("task-9", repository_provider=lambda: repository)
    finally:
        reset_current_agent_context(token)
    assert repository.requested_roots == ["root-1"]
    assert "Check the run." in block


@pytest.mark.asyncio
async def test_context_falls_back_to_the_task_id_without_a_running_context():
    repository = _Repository([])
    assert await pending_follow_up_context("task-9", repository_provider=lambda: repository) is None
    assert repository.requested_roots == ["task-9"]


@pytest.mark.asyncio
async def test_repository_failure_never_raises_and_yields_no_block():
    repository = _Repository(error=RuntimeError("database locked"))
    assert await pending_follow_up_context("task-9", repository_provider=lambda: repository) is None


@pytest.mark.asyncio
async def test_missing_task_identity_yields_no_block():
    assert await pending_follow_up_context(None, repository_provider=lambda: _Repository()) is None
