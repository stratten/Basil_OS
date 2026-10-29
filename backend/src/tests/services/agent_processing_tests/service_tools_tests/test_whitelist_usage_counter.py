"""Tests that whitelist patterns record their uses, including the approval that created them."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from api.core.models.preferences import CommandPattern, ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService


class _PreferenceStore:
    def __init__(self, patterns: list[CommandPattern]) -> None:
        self.preferences = SimpleNamespace(
            tool_execution=ToolExecutionSettings(
                approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
                whitelisted_commands=patterns,
                auto_approve_read_only=False,
                safe_execution_mode=False,
            )
        )
        self.saves = 0

    def load(self) -> SimpleNamespace:
        return self.preferences

    def save(self, preferences: SimpleNamespace) -> None:
        self.preferences = preferences
        self.saves += 1

    @property
    def patterns(self) -> list[CommandPattern]:
        return self.preferences.tool_execution.whitelisted_commands


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _PreferenceStore:
    preference_store = _PreferenceStore(
        [CommandPattern(id="du-pattern", pattern="du", pattern_type="prefix", description="disk usage")]
    )
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", preference_store.load)
    monkeypatch.setattr("api.core.preferences.preferences_io.save_preferences", preference_store.save)
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.approval_override.load_preferences", preference_store.load
    )
    return preference_store


def _pattern(store: _PreferenceStore, pattern_id: str) -> CommandPattern:
    return next(pattern for pattern in store.patterns if pattern.id == pattern_id)


@pytest.mark.asyncio
async def test_whitelisted_execution_increments_the_matched_pattern(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    first = await service.request_approval_with_outcome("du -sh /tmp")
    second = await service.request_approval_with_outcome("du -sh /var")

    assert first.approved and second.approved
    assert first.decision.matched_pattern.id == "du-pattern"
    pattern = _pattern(store, "du-pattern")
    assert pattern.use_count == 2
    assert isinstance(pattern.last_used, datetime)


@pytest.mark.asyncio
async def test_evaluating_a_command_without_running_it_does_not_count(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    decision = await service.evaluate_command("du -sh /tmp")

    assert decision.matched_pattern is not None
    assert _pattern(store, "du-pattern").use_count == 0
    assert store.saves == 0


@pytest.mark.asyncio
async def test_commands_needing_approval_do_not_count_against_any_pattern(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    outcome = await service.request_approval_with_outcome("cargo build")

    assert outcome.approved is False
    assert _pattern(store, "du-pattern").use_count == 0


@pytest.mark.asyncio
async def test_remembered_approval_starts_the_new_pattern_at_one_use(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    pattern = await service.add_to_whitelist("cargo build --release", pattern_type="prefix", record_initial_use=True)

    assert pattern.use_count == 1
    assert pattern.last_used == pattern.added_date


@pytest.mark.asyncio
async def test_manually_added_pattern_starts_at_zero_uses(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    pattern = await service.add_to_whitelist("cargo build --release", pattern_type="prefix")

    assert pattern.use_count == 0
    assert pattern.last_used is None


@pytest.mark.asyncio
async def test_duplicate_remembered_approval_does_not_double_count(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    created = await service.add_to_whitelist("cargo build --release", pattern_type="prefix", record_initial_use=True)
    duplicate = await service.add_to_whitelist("cargo build --release", pattern_type="prefix", record_initial_use=True)

    assert duplicate.id == created.id
    assert _pattern(store, created.id).use_count == 1


@pytest.mark.asyncio
async def test_usage_for_an_unknown_pattern_saves_nothing(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()

    await service.update_pattern_usage("missing-pattern")

    assert store.saves == 0
    assert _pattern(store, "du-pattern").use_count == 0
