"""Active-time budgets: local models get four hours, cloud models keep twenty minutes."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph import execution_limits as limits


@pytest.fixture
def registry(monkeypatch):
    models = {"local-qwen": {"location": "local"}, "cloud-claude": {"location": "cloud"}}
    monkeypatch.setattr("api.core.models.models_registry.schema.get_model", lambda model_id: models.get(model_id))


def test_a_local_model_gets_the_four_hour_active_budget(registry):
    assert limits.agent_run_max_active_seconds("local-qwen") == 4 * 60 * 60


@pytest.mark.parametrize("model_id", ["cloud-claude", "unknown-model", "", None, 42])
def test_everything_else_keeps_the_twenty_minute_budget(registry, model_id):
    assert limits.agent_run_max_active_seconds(model_id) == 1200


def test_registry_failure_falls_back_to_the_cloud_budget(monkeypatch):
    def broken(_model_id):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr("api.core.models.models_registry.schema.get_model", broken)

    assert limits.agent_run_max_active_seconds("local-qwen") == 1200


def test_the_wall_clock_guard_outlasts_the_active_budget(registry):
    assert limits.workflow_wallclock_limit_seconds("cloud-claude") == 1500
    assert limits.workflow_wallclock_limit_seconds(None) == 1500
    local = limits.workflow_wallclock_limit_seconds("local-qwen")
    assert local > limits.agent_run_max_active_seconds("local-qwen")


def test_the_limit_message_names_minutes_or_hours():
    assert "20 minute(s)" in limits.active_time_limit_message(1200)
    assert "4 hour(s)" in limits.active_time_limit_message(4 * 60 * 60)
    assert "1.5 hour(s)" in limits.active_time_limit_message(5400)
    assert "not counted" in limits.active_time_limit_message(1200)
