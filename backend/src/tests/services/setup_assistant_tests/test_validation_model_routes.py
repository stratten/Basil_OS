"""Tests for the validation-only local model chooser and copy route in the Setup Assistant."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

LARGE_ID = "Qwen-qwen36-35b-a3b-mlx-4bit"
SMALL_ID = "Qwen-qwen35-9b-mlx-4bit"
ROUTES = "api.routes.setup_assistant.model_access_routes"
VALIDATION_ROUTES = "api.routes.setup_assistant.validation_model_routes"

LOCAL_MODELS = {
    LARGE_ID: {"capabilities": ["reasoning"], "display_name": "Large model", "size": "20GB"},
    SMALL_ID: {"capabilities": ["reasoning"], "display_name": "Small model", "size": "5.6GB"},
}


@pytest.fixture(autouse=True)
def clear_auth_token():
    from api.core.services import model_service

    model_service.clear_auth_access_token()
    yield
    model_service.clear_auth_access_token()


def _local_option(query: str = ""):
    response = client.get(f"/setup-assistant/model-access/options{query}")
    assert response.status_code == 200
    return next(option for option in response.json()["options"] if option["mode"] == "local")


def _patched_registry():
    return (
        patch(f"{ROUTES}.get_local_reasoning_models", return_value=LOCAL_MODELS),
        patch(f"{ROUTES}._eligible_local_model_ids", return_value=[]),
        patch(f"{ROUTES}._default_local_model_id", return_value=LARGE_ID),
    )


def _validation_profile(tmp_path):
    return SimpleNamespace(copy_source_models_root=tmp_path)


def test_normal_build_shows_no_chooser_and_ignores_a_requested_model():
    registry, eligible, default = _patched_registry()
    with registry, eligible, default:
        option = _local_option(f"?local_model_id={SMALL_ID}")

    assert option["local_model_choices"] == []
    assert option["can_copy_from_normal_basil"] is False
    assert option["local_model_id"] == LARGE_ID


def test_validation_session_lists_the_chooser_with_the_smaller_model(tmp_path):
    registry, eligible, default = _patched_registry()
    with registry, eligible, default, patch(f"{VALIDATION_ROUTES}.validation_profile_or_none", return_value=_validation_profile(tmp_path)):
        option = _local_option()

    choices = {choice["model_id"]: choice for choice in option["local_model_choices"]}
    assert set(choices) == {LARGE_ID, SMALL_ID}
    assert choices[SMALL_ID]["display_name"] == "Small model"
    assert choices[SMALL_ID]["size_description"] == "5.6GB"
    assert choices[SMALL_ID]["model_type"] == "Qwen"
    assert choices[SMALL_ID]["variant"] == "qwen35-9b-mlx-4bit"
    assert option["local_model_id"] == LARGE_ID


def test_validation_session_honors_a_requested_model_and_ignores_an_unknown_one(tmp_path):
    registry, eligible, default = _patched_registry()
    with registry, eligible, default, patch(f"{VALIDATION_ROUTES}.validation_profile_or_none", return_value=_validation_profile(tmp_path)):
        chosen = _local_option(f"?local_model_id={SMALL_ID}")
        unknown = _local_option("?local_model_id=Not-a-listed-model")

    assert chosen["local_model_id"] == SMALL_ID
    assert chosen["display_name"] == "Small model"
    assert chosen["local_model_variant"] == "qwen35-9b-mlx-4bit"
    assert unknown["local_model_id"] == LARGE_ID


def test_copy_is_offered_only_when_the_normal_basil_holds_the_model(tmp_path):
    registry, eligible, default = _patched_registry()
    with registry, eligible, default, patch(
        f"{VALIDATION_ROUTES}.validation_profile_or_none", return_value=_validation_profile(tmp_path)
    ), patch(f"{VALIDATION_ROUTES}.source_has_model", side_effect=lambda model_id, *_: model_id == SMALL_ID):
        large = _local_option()
        small = _local_option(f"?local_model_id={SMALL_ID}")

    assert large["can_copy_from_normal_basil"] is False
    assert small["can_copy_from_normal_basil"] is True
    assert {c["model_id"]: c["can_copy_from_normal_basil"] for c in small["local_model_choices"]} == {
        LARGE_ID: False,
        SMALL_ID: True,
    }


def test_copy_route_is_not_found_outside_a_validation_session():
    response = client.post(
        "/setup-assistant/model-access/validation/copy-model",
        json={"model_type": "Qwen", "variant": "qwen35-9b-mlx-4bit"},
    )

    assert response.status_code == 404


def test_copy_route_rejects_a_model_the_normal_basil_does_not_have(tmp_path):
    with patch(f"{VALIDATION_ROUTES}.validation_profile_or_none", return_value=_validation_profile(tmp_path)), patch(
        f"{VALIDATION_ROUTES}.is_in_registry", return_value=True
    ), patch(f"{VALIDATION_ROUTES}.source_has_model", return_value=False):
        response = client.post(
            "/setup-assistant/model-access/validation/copy-model",
            json={"model_type": "Qwen", "variant": "qwen35-9b-mlx-4bit"},
        )

    assert response.status_code == 404
    assert "does not have a complete copy" in response.json()["detail"]


def test_copy_route_starts_a_copy_entry_through_the_download_manager(tmp_path):
    started = {}

    class FakeManager:
        async def start(self, model_type, variant, copy_source_root=None):
            started.update(model_type=model_type, variant=variant, copy_source_root=copy_source_root)
            return SimpleNamespace(model_id=f"{model_type}-{variant}", status="queued")

    with patch(f"{VALIDATION_ROUTES}.validation_profile_or_none", return_value=_validation_profile(tmp_path)), patch(
        f"{VALIDATION_ROUTES}.is_in_registry", return_value=True
    ), patch(f"{VALIDATION_ROUTES}.source_has_model", return_value=True), patch(
        f"{VALIDATION_ROUTES}._get_download_manager", return_value=FakeManager()
    ):
        response = client.post(
            "/setup-assistant/model-access/validation/copy-model",
            json={"model_type": "Qwen", "variant": "qwen35-9b-mlx-4bit"},
        )

    assert response.status_code == 200
    assert response.json() == {"model_id": SMALL_ID, "status": "queued"}
    assert started == {"model_type": "Qwen", "variant": "qwen35-9b-mlx-4bit", "copy_source_root": tmp_path}


@pytest.fixture
def starter_progress_client():
    """A client whose progress route sees no installed models and an idle download manager."""
    from api.routes.onboarding import get_model_service

    app.dependency_overrides[get_model_service] = lambda: SimpleNamespace(is_model_downloaded=lambda *_: False)
    had_manager = hasattr(app.state, "download_manager")
    previous_manager = getattr(app.state, "download_manager", None)
    app.state.download_manager = SimpleNamespace(get_by_pair=lambda *_: None)
    yield client
    app.dependency_overrides.pop(get_model_service, None)
    if had_manager:
        app.state.download_manager = previous_manager
    else:
        del app.state.download_manager


def test_starter_download_progress_names_every_model_and_never_offers_copy_in_a_normal_build(starter_progress_client):
    response = starter_progress_client.get("/onboarding/download-progress")

    assert response.status_code == 200
    records = response.json()["models"]
    assert records
    for model_id, record in records.items():
        assert record["display_name"]
        assert record["display_name"] != model_id
        assert record["can_copy_from_normal_basil"] is False


def test_starter_download_progress_offers_copy_for_models_the_normal_basil_holds(starter_progress_client, tmp_path):
    with patch(f"{VALIDATION_ROUTES}.validation_profile_or_none", return_value=_validation_profile(tmp_path)), patch(
        f"{VALIDATION_ROUTES}.source_has_model", return_value=True
    ):
        response = starter_progress_client.get("/onboarding/download-progress")

    assert response.status_code == 200
    assert all(record["can_copy_from_normal_basil"] is True for record in response.json()["models"].values())
