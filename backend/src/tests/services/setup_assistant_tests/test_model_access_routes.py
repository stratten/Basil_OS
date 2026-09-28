"""Tests for the Setup Assistant's backend-confirmed model-access gate."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.core.services.model_access_policy import BasilCloudEligibility
from api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_auth_token():
    from api.core.services import model_service

    model_service.clear_auth_access_token()
    yield
    model_service.clear_auth_access_token()


def test_options_reports_local_unavailable_when_no_local_model():
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value={},
    ):
        response = client.get("/setup-assistant/model-access/options")

    assert response.status_code == 200
    local_option = next(
        option for option in response.json()["options"] if option["mode"] == "local"
    )
    assert local_option["available"] is False
    assert "No reasoning-capable local model" in local_option["unavailable_reason"]


def test_options_reports_basil_cloud_unavailable_without_token():
    response = client.get("/setup-assistant/model-access/options")

    assert response.status_code == 200
    basil_cloud_option = next(
        option
        for option in response.json()["options"]
        if option["mode"] == "basil_cloud"
    )
    assert basil_cloud_option["available"] is False
    assert "Sign in to Basil Cloud" in basil_cloud_option["unavailable_reason"]


def test_select_local_fails_when_model_not_downloaded():
    local_models = {
        "llama-8b": {
            "capabilities": ["reasoning"],
            "recommended_for_onboarding": True,
            "display_name": "Llama 8B",
        }
    }
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value=local_models,
    ), patch(
        "api.routes.setup_assistant.model_access_routes.get_model_service"
    ) as get_model_service:
        get_model_service.return_value.is_model_downloaded.return_value = False
        response = client.post(
            "/setup-assistant/model-access/select",
            json={"mode": "local"},
        )

    assert response.status_code == 400
    assert "not downloaded" in response.json()["detail"]


def test_select_provider_key_fails_without_key_or_input():
    with patch(
        "api.routes.setup_assistant.model_access_routes.has_user_key",
        return_value=False,
    ):
        response = client.post(
            "/setup-assistant/model-access/select",
            json={"mode": "provider_key", "provider": "anthropic"},
        )

    assert response.status_code == 400
    assert "No anthropic key" in response.json()["detail"]


def test_select_provider_key_rejects_a_key_that_fails_live_validation():
    with patch(
        "api.routes.setup_assistant.model_access_routes.validate_provider_api_key",
        return_value=(False, "Invalid API key"),
    ) as validate_provider_api_key, patch(
        "api.routes.setup_assistant.model_access_routes.set_api_key"
    ) as set_api_key:
        response = client.post(
            "/setup-assistant/model-access/select",
            json={
                "mode": "provider_key",
                "provider": "anthropic",
                "provider_api_key": "sk-ant-not-real",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid API key"
    validate_provider_api_key.assert_called_once_with("anthropic", "sk-ant-not-real")
    set_api_key.assert_not_called()


def test_select_provider_key_saves_key_and_returns_resolved_access():
    model_config = {
        "provider": "anthropic",
        "location": "cloud",
        "display_name": "Claude Sonnet",
        "openrouter_id": "anthropic/claude-sonnet",
        "capabilities": ["reasoning"],
    }
    with patch(
        "api.routes.setup_assistant.model_access_routes.validate_provider_api_key",
        return_value=(True, None),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.set_api_key",
        return_value=True,
    ) as set_api_key, patch(
        "api.routes.setup_assistant.model_access_routes.get_model",
        return_value=model_config,
    ), patch(
        "api.routes.setup_assistant.model_access_routes._save_access_preference"
    ):
        response = client.post(
            "/setup-assistant/model-access/select",
            json={
                "mode": "provider_key",
                "provider": "anthropic",
                "model_id": "claude-sonnet",
                "provider_api_key": "test-key",
            },
        )

    assert response.status_code == 200
    assert response.json()["access"]["resolved"] is True
    assert response.json()["access"]["provider"] == "anthropic"
    set_api_key.assert_called_once_with("anthropic", "test-key")


def test_select_provider_key_reuses_an_already_validated_saved_key_without_revalidating():
    model_config = {
        "provider": "anthropic",
        "location": "cloud",
        "display_name": "Claude Sonnet",
        "openrouter_id": "anthropic/claude-sonnet",
        "capabilities": ["reasoning"],
    }
    with patch(
        "api.routes.setup_assistant.model_access_routes.has_user_key",
        return_value=True,
    ), patch(
        "api.routes.setup_assistant.model_access_routes.validate_provider_api_key"
    ) as validate_provider_api_key, patch(
        "api.routes.setup_assistant.model_access_routes.get_model",
        return_value=model_config,
    ), patch(
        "api.routes.setup_assistant.model_access_routes._save_access_preference"
    ):
        response = client.post(
            "/setup-assistant/model-access/select",
            json={
                "mode": "provider_key",
                "provider": "anthropic",
                "model_id": "claude-sonnet",
            },
        )

    assert response.status_code == 200
    assert response.json()["access"]["resolved"] is True
    validate_provider_api_key.assert_not_called()


def test_select_basil_cloud_fails_without_token():
    response = client.post(
        "/setup-assistant/model-access/select",
        json={"mode": "basil_cloud"},
    )

    assert response.status_code == 401


def test_select_basil_cloud_fails_when_ineligible():
    from api.core.services import model_service

    model_service.set_auth_access_token("token-abc")
    with patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new_callable=AsyncMock,
        return_value=BasilCloudEligibility(
            eligible=False,
            reason="no_payment_method",
            message="No payment method on file.",
        ),
    ):
        response = client.post(
            "/setup-assistant/model-access/select",
            json={"mode": "basil_cloud"},
        )

    assert response.status_code == 402
    assert response.json()["detail"] == "No payment method on file."


def test_select_basil_cloud_succeeds_when_eligible():
    from api.core.services import model_service

    model_service.set_auth_access_token("token-abc")
    cloud_models = {
        "claude-sonnet": {
            "provider": "anthropic",
            "display_name": "Claude Sonnet",
            "openrouter_id": "anthropic/claude-sonnet",
            "used_by_setup_agent": True,
            "supports_openrouter_proxy": True,
        }
    }
    with patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new_callable=AsyncMock,
        return_value=BasilCloudEligibility(eligible=True),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.CLOUD_REASONING_MODELS",
        cloud_models,
    ), patch(
        "api.routes.setup_assistant.model_access_routes._save_access_preference"
    ):
        response = client.post(
            "/setup-assistant/model-access/select",
            json={"mode": "basil_cloud"},
        )

    assert response.status_code == 200
    assert response.json()["access"]["mode"] == "basil_cloud"
    assert response.json()["access"]["model_id"] == "claude-sonnet"
    assert response.json()["access"]["resolved"] is True
