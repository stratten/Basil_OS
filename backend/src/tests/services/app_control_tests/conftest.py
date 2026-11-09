"""Shared fixtures: preferences held in memory, a temporary journal, and a scripted approval manager."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import pytest

from api.core.models.preferences import Preferences
from api.core.preferences import preferences_io
from api.services.app_control.engine import AppControlEngine
from api.services.app_control.entries import build_default_registry
from api.services.app_control.journal import ChangeJournal


class MemoryPreferences:
    """Stands in for the preferences file; every load returns a fresh copy, like reading the file."""

    def __init__(self) -> None:
        self.current = Preferences()
        self.saves = 0

    def load(self) -> Preferences:
        return copy.deepcopy(self.current)

    def save(self, preferences: Preferences) -> None:
        self.current = copy.deepcopy(preferences)
        self.saves += 1


class ScriptedApprovals:
    """Answers approval requests from a script instead of waiting on a person."""

    def __init__(self, outcome: str = "approved") -> None:
        self.outcome = outcome
        self.requests: List[Any] = []
        self.before_answer: Optional[Any] = None

    async def request(self, request: Any) -> str:
        self.requests.append(request)
        if self.before_answer is not None:
            self.before_answer()
        return self.outcome


@pytest.fixture
def memory_preferences(monkeypatch) -> MemoryPreferences:
    store = MemoryPreferences()
    monkeypatch.setattr(preferences_io, "load_preferences", store.load)
    monkeypatch.setattr(preferences_io, "save_preferences", store.save)
    return store


@pytest.fixture
def approvals() -> ScriptedApprovals:
    return ScriptedApprovals()


@pytest.fixture
def published() -> List[str]:
    return []


@pytest.fixture
def announced() -> List[List[str]]:
    return []


@pytest.fixture
def engine(memory_preferences, approvals, published, announced, tmp_path) -> AppControlEngine:
    async def record(preferences: Any) -> None:
        published.append(preferences.ui.preferred_font)

    return AppControlEngine(
        registry=build_default_registry(),
        journal=ChangeJournal(tmp_path / "journal.json"),
        approval_manager=approvals,  # type: ignore[arg-type]
        publishers={"appearance": record},
        change_notifier=lambda keys: _announce(announced, keys),
    )


async def _announce(announced: List[List[str]], keys: List[str]) -> None:
    announced.append(list(keys))
