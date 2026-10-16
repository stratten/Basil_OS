"""Shared fixtures for the agent graph tests."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.agent_loop_nudges import CompletionNudgeMiddleware

_REAL_HANDOFF_CHECK_OWED = CompletionNudgeMiddleware._handoff_check_owed


@pytest.fixture(autouse=True)
def _handoff_check_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scripted models in these tests answer exactly once after their tool calls, so the one-shot handoff check (an extra model call) is off unless a test asks for it."""
    monkeypatch.setattr(CompletionNudgeMiddleware, "_handoff_check_owed", lambda self, steps: False)


@pytest.fixture
def handoff_check_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the real one-shot handoff check for a test that exercises it."""
    monkeypatch.setattr(CompletionNudgeMiddleware, "_handoff_check_owed", _REAL_HANDOFF_CHECK_OWED)
