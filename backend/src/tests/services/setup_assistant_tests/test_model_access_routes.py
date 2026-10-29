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


def test_options_reports_basil_cloud_unavailable_without_token_once_the_account_is_checked():
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value=None),
    ):
        response = client.get("/setup-assistant/model-access/options?check_account=true")

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
        "api.routes.setup_assistant.model_access_routes.aset_api_key",
        new_callable=AsyncMock,
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
        "api.routes.setup_assistant.model_access_routes.aset_api_key",
        new_callable=AsyncMock,
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


def _local_models_fixture():
    return {
        "Qwen-qwen35-9b-q4km": {
            "capabilities": ["reasoning"],
            "recommended_for_onboarding": True,
            "display_name": "Qwen3.5-9B",
            "size": "5.68GB",
        }
    }


def _local_option(downloaded: bool):
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value=_local_models_fixture(),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.get_model_service"
    ) as get_model_service:
        get_model_service.return_value.is_model_downloaded.return_value = downloaded
        response = client.get("/setup-assistant/model-access/options")
        called_with = get_model_service.return_value.is_model_downloaded.call_args

    assert response.status_code == 200
    option = next(item for item in response.json()["options"] if item["mode"] == "local")
    return option, called_with


def test_options_reports_local_not_downloaded_as_downloadable_but_unavailable():
    option, called_with = _local_option(downloaded=False)

    assert option["available"] is False
    assert option["downloaded"] is False
    assert option["unavailable_reason"] == "Not downloaded yet."
    assert option["local_model_id"] == "Qwen-qwen35-9b-q4km"
    assert option["local_model_type"] == "Qwen"
    assert option["local_model_variant"] == "qwen35-9b-q4km"
    assert option["download_size_description"] == "5.68GB"
    assert option["display_name"] == "Qwen3.5-9B"
    assert called_with.args == ("Qwen", "qwen35-9b-q4km")


def test_options_reports_local_downloaded_as_available():
    option, _ = _local_option(downloaded=True)

    assert option["available"] is True
    assert option["downloaded"] is True
    assert option["unavailable_reason"] is None


def test_options_without_local_model_leaves_download_fields_empty():
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value={},
    ):
        response = client.get("/setup-assistant/model-access/options")

    option = next(item for item in response.json()["options"] if item["mode"] == "local")
    assert option["downloaded"] is None
    assert option["local_model_type"] is None
    assert option["local_model_variant"] is None


def test_options_marks_basil_cloud_as_requiring_sign_in_without_token_once_the_account_is_checked():
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value=None),
    ):
        response = client.get("/setup-assistant/model-access/options?check_account=true")

    option = next(
        item for item in response.json()["options"] if item["mode"] == "basil_cloud"
    )
    assert option["requires_sign_in"] is True
    assert option["available"] is False
    assert option["requires_account_check"] is False


def test_options_does_not_require_sign_in_when_signed_in_but_ineligible():
    from api.core.services import model_service

    model_service.set_auth_access_token("token-123")
    with patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new=AsyncMock(
            return_value=BasilCloudEligibility(
                eligible=False, reason="no_credits", message="Out of credits."
            )
        ),
    ):
        response = client.get("/setup-assistant/model-access/options")

    option = next(
        item for item in response.json()["options"] if item["mode"] == "basil_cloud"
    )
    assert option["requires_sign_in"] is False
    assert option["available"] is False
    assert option["unavailable_reason"] == "Out of credits."


def _two_local_models_fixture():
    return {
        "Other-vendor-8b-q4": {
            "capabilities": ["reasoning"],
            "recommended_for_onboarding": False,
            "display_name": "Vendor 8B",
            "size": "4.9GB",
        },
        "Qwen-qwen35-9b-q4km": {
            "capabilities": ["reasoning"],
            "recommended_for_onboarding": True,
            "display_name": "Qwen3.5-9B",
            "size": "5.68GB",
        },
    }


def _downloaded_only(*downloaded_ids):
    def is_model_downloaded(model_type, variant):
        return f"{model_type}-{variant}" in downloaded_ids

    return is_model_downloaded


def test_options_make_local_available_with_any_downloaded_model_instead_of_the_default():
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value=_two_local_models_fixture(),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.get_model_service"
    ) as get_model_service:
        get_model_service.return_value.is_model_downloaded.side_effect = _downloaded_only(
            "Other-vendor-8b-q4"
        )
        response = client.get("/setup-assistant/model-access/options")

    option = next(item for item in response.json()["options"] if item["mode"] == "local")
    assert option["available"] is True
    assert option["downloaded"] is True
    assert option["local_model_id"] == "Other-vendor-8b-q4"
    assert option["display_name"] == "Vendor 8B"
    assert option["unavailable_reason"] is None


def test_options_prefer_the_onboarding_default_when_several_models_are_downloaded():
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value=_two_local_models_fixture(),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.get_model_service"
    ) as get_model_service:
        get_model_service.return_value.is_model_downloaded.side_effect = _downloaded_only(
            "Other-vendor-8b-q4", "Qwen-qwen35-9b-q4km"
        )
        response = client.get("/setup-assistant/model-access/options")

    option = next(item for item in response.json()["options"] if item["mode"] == "local")
    assert option["available"] is True
    assert option["local_model_id"] == "Qwen-qwen35-9b-q4km"


def test_options_recommend_the_default_download_only_when_no_model_is_downloaded():
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value=_two_local_models_fixture(),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.get_model_service"
    ) as get_model_service:
        get_model_service.return_value.is_model_downloaded.side_effect = _downloaded_only()
        response = client.get("/setup-assistant/model-access/options")

    option = next(item for item in response.json()["options"] if item["mode"] == "local")
    assert option["available"] is False
    assert option["downloaded"] is False
    assert option["local_model_id"] == "Qwen-qwen35-9b-q4km"
    assert option["local_model_type"] == "Qwen"
    assert option["local_model_variant"] == "qwen35-9b-q4km"
    assert option["download_size_description"] == "5.68GB"


def test_select_local_without_an_id_uses_a_downloaded_model_even_if_it_is_not_the_default():
    with patch(
        "api.routes.setup_assistant.model_access_routes.get_local_reasoning_models",
        return_value=_two_local_models_fixture(),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.get_model_service"
    ) as get_model_service, patch(
        "api.routes.setup_assistant.model_access_routes._save_access_preference"
    ):
        get_model_service.return_value.is_model_downloaded.side_effect = _downloaded_only(
            "Other-vendor-8b-q4"
        )
        response = client.post("/setup-assistant/model-access/select", json={"mode": "local"})

    assert response.status_code == 200
    assert response.json()["access"]["local_model_id"] == "Other-vendor-8b-q4"
    assert response.json()["access"]["resolved"] is True


def _basil_cloud_option(response):
    return next(
        item for item in response.json()["options"] if item["mode"] == "basil_cloud"
    )


def test_options_never_ask_the_app_for_the_account_unless_the_user_chose_basil_cloud():
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value="token-from-app"),
    ) as request_token, patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new=AsyncMock(return_value=BasilCloudEligibility(eligible=True)),
    ) as check_eligibility:
        response = client.get("/setup-assistant/model-access/options")

    option = _basil_cloud_option(response)
    assert option["available"] is True
    assert option["requires_account_check"] is True
    assert option["requires_sign_in"] is False
    assert option["unavailable_reason"] is None
    request_token.assert_not_awaited()
    check_eligibility.assert_not_awaited()


def test_options_ask_the_app_for_the_account_token_when_the_user_chose_basil_cloud():
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value="token-from-app"),
    ) as request_token, patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new=AsyncMock(return_value=BasilCloudEligibility(eligible=True)),
    ) as check_eligibility:
        response = client.get("/setup-assistant/model-access/options?check_account=true")

    option = _basil_cloud_option(response)
    assert option["available"] is True
    assert option["requires_sign_in"] is False
    assert option["requires_account_check"] is False
    request_token.assert_awaited_once()
    assert request_token.await_args.kwargs["timeout_seconds"] == 10.0
    check_eligibility.assert_awaited_once_with("token-from-app")


def test_options_do_not_ask_the_app_when_the_backend_already_has_a_token():
    from api.core.services import model_service

    model_service.set_auth_access_token("token-123")
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value="unused"),
    ) as request_token, patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new=AsyncMock(return_value=BasilCloudEligibility(eligible=True)),
    ):
        response = client.get("/setup-assistant/model-access/options")

    assert _basil_cloud_option(response)["available"] is True
    request_token.assert_not_awaited()


def test_options_report_signed_out_only_when_the_app_has_no_token_either():
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value=None),
    ) as request_token:
        response = client.get("/setup-assistant/model-access/options?check_account=true")

    option = _basil_cloud_option(response)
    assert option["available"] is False
    assert option["requires_sign_in"] is True
    request_token.assert_awaited_once()


def test_select_basil_cloud_uses_the_token_the_app_supplies():
    with patch(
        "api.routes.setup_assistant.model_access_routes.request_auth_token_from_swift",
        new=AsyncMock(return_value="token-from-app"),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new=AsyncMock(return_value=BasilCloudEligibility(eligible=True)),
    ) as check_eligibility, patch(
        "api.routes.setup_assistant.model_access_routes._save_access_preference"
    ), patch(
        "api.routes.setup_assistant.model_access_routes.CLOUD_REASONING_MODELS",
        {
            "claude-sonnet": {
                "provider": "anthropic",
                "display_name": "Claude Sonnet",
                "openrouter_id": "anthropic/claude-sonnet",
                "used_by_setup_agent": True,
                "supports_openrouter_proxy": True,
            }
        },
    ):
        response = client.post(
            "/setup-assistant/model-access/select", json={"mode": "basil_cloud"}
        )

    assert response.status_code == 200
    check_eligibility.assert_awaited_once_with("token-from-app")


def _options_with_cloud_eligibility(eligibility):
    from api.core.services import model_service

    model_service.set_auth_access_token("token-123")
    with patch(
        "api.routes.setup_assistant.model_access_routes.check_basil_cloud_eligibility",
        new=AsyncMock(return_value=eligibility),
    ):
        response = client.get("/setup-assistant/model-access/options")
    return _basil_cloud_option(response)


def test_options_flag_a_missing_payment_method_so_setup_can_send_the_user_to_add_one():
    option = _options_with_cloud_eligibility(
        BasilCloudEligibility(
            eligible=False,
            reason="payment_method_required",
            message="Add a payment method to use Basil Cloud.",
        )
    )

    assert option["available"] is False
    assert option["requires_payment_method"] is True
    assert option["requires_sign_in"] is False
    assert option["unavailable_reason"] == "Add a payment method to use Basil Cloud."


def test_options_flag_an_expired_session_as_needing_sign_in():
    option = _options_with_cloud_eligibility(
        BasilCloudEligibility(
            eligible=False, reason="unauthenticated", message="Please sign in again."
        )
    )

    assert option["requires_sign_in"] is True
    assert option["requires_payment_method"] is False


def test_options_do_not_flag_account_actions_for_other_ineligibility_or_eligible_accounts():
    inactive = _options_with_cloud_eligibility(
        BasilCloudEligibility(eligible=False, reason="subscription_inactive", message="Inactive.")
    )
    eligible = _options_with_cloud_eligibility(BasilCloudEligibility(eligible=True))

    for option in (inactive, eligible):
        assert option["requires_sign_in"] is False
        assert option["requires_payment_method"] is False


def test_select_provider_key_reports_a_vault_that_cannot_be_saved_to():
    from config.credential_store import CredentialStoreUnavailableError

    with patch(
        "api.routes.setup_assistant.model_access_routes.validate_provider_api_key",
        return_value=(True, None),
    ), patch(
        "api.routes.setup_assistant.model_access_routes.aset_api_key",
        new_callable=AsyncMock,
        side_effect=CredentialStoreUnavailableError("Basil could not open its Keychain vault."),
    ):
        response = client.post(
            "/setup-assistant/model-access/select",
            json={"mode": "provider_key", "provider": "anthropic", "provider_api_key": "test-key"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Basil could not open its Keychain vault."
