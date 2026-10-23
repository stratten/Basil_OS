"""Tests for Activity Capture run-policy resolution."""

from api.services.capture.automatic.activity_processing_run_policy import (
    API_BACKLOG_ANALYSIS_CONCURRENCY,
    resolve_activity_processing_run_policy,
)


def test_manual_cloud_backlog_uses_fixed_parallelism(monkeypatch):
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda model_id: {"location": "cloud"} if model_id == "cloud-model" else None,
    )

    policy = resolve_activity_processing_run_policy(
        "cloud-model",
        is_manual_backlog_run=True,
    )

    assert policy.model_id == "cloud-model"
    assert policy.analysis_concurrency == API_BACKLOG_ANALYSIS_CONCURRENCY
    assert policy.processing_strategy == "api_parallel"


def test_scheduled_cloud_run_remains_sequential(monkeypatch):
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda model_id: {"location": "cloud"} if model_id == "cloud-model" else None,
    )

    policy = resolve_activity_processing_run_policy(
        "cloud-model",
        is_manual_backlog_run=False,
    )

    assert policy.analysis_concurrency == 1
    assert policy.processing_strategy == "sequential"


def test_manual_local_backlog_remains_sequential(monkeypatch):
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda model_id: {"location": "local"} if model_id == "local-model" else None,
    )

    policy = resolve_activity_processing_run_policy(
        "local-model",
        is_manual_backlog_run=True,
    )

    assert policy.analysis_concurrency == 1
    assert policy.processing_strategy == "sequential"


def test_unknown_manual_model_remains_sequential(monkeypatch):
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda _model_id: None,
    )
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.find_model_by_display_name",
        lambda _display_name: None,
    )

    policy = resolve_activity_processing_run_policy(
        "unknown-model",
        is_manual_backlog_run=True,
    )

    assert policy.model_id == "unknown-model"
    assert policy.analysis_concurrency == 1
    assert policy.processing_strategy == "sequential"


def test_legacy_display_name_resolves_before_cloud_policy(monkeypatch):
    def get_model(model_id):
        return {"location": "cloud"} if model_id == "canonical-cloud-model" else None

    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        get_model,
    )
    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.find_model_by_display_name",
        lambda display_name: (
            ("canonical-cloud-model", {"location": "cloud"})
            if display_name == "Cloud Display Name"
            else None
        ),
    )

    policy = resolve_activity_processing_run_policy(
        "Cloud Display Name",
        is_manual_backlog_run=True,
    )

    assert policy.model_id == "canonical-cloud-model"
    assert policy.analysis_concurrency == API_BACKLOG_ANALYSIS_CONCURRENCY
