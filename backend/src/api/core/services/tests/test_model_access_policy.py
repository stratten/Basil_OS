"""Unit tests for the fail-closed Basil Cloud eligibility policy, which reads the Auth Service billing status."""

import httpx
import pytest
import respx

from api.core.services.model_access_policy import check_basil_cloud_eligibility
from api.services.auth_service_endpoint import AUTH_SERVICE_URL

STATUS_URL = f"{AUTH_SERVICE_URL}/billing/status"


def _status(**overrides):
    body = {
        "subscription_status": "active",
        "has_payment_method": True,
        "stripe_customer_id": "cus_123",
        "current_period_usage_usd": 1.5,
        "threshold_status": {
            "has_threshold": False,
            "threshold_usd": None,
            "current_usage_usd": 1.5,
            "is_exceeded": False,
        },
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
@respx.mock
async def test_active_account_with_payment_method_is_eligible():
    route = respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=_status()))

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is True
    assert result.reason == "active_subscription"
    assert route.calls.last.request.headers["authorization"] == "Bearer token-123"


@pytest.mark.asyncio
@respx.mock
async def test_missing_payment_method_is_not_eligible_and_says_how_to_fix_it():
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=_status(has_payment_method=False))
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "payment_method_required"
    assert "payment method" in (result.message or "")


@pytest.mark.asyncio
@respx.mock
async def test_inactive_subscription_names_the_status():
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json=_status(subscription_status="suspended"))
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "subscription_inactive"
    assert "suspended" in (result.message or "")


@pytest.mark.asyncio
@respx.mock
async def test_exceeded_spending_limit_is_not_eligible():
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(
            200,
            json=_status(
                threshold_status={
                    "has_threshold": True,
                    "threshold_usd": 5.0,
                    "current_usage_usd": 5.2,
                    "is_exceeded": True,
                }
            ),
        )
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "usage_threshold_exceeded"


@pytest.mark.asyncio
@respx.mock
async def test_unauthenticated_token_returns_eligible_false():
    respx.get(STATUS_URL).mock(return_value=httpx.Response(401))

    result = await check_basil_cloud_eligibility("expired-token")

    assert result.eligible is False
    assert result.reason == "unauthenticated"


@pytest.mark.asyncio
@respx.mock
async def test_server_error_fails_closed_with_the_status_code():
    respx.get(STATUS_URL).mock(return_value=httpx.Response(404))

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "entitlement_check_failed"
    assert "404" in (result.message or "")


@pytest.mark.asyncio
@respx.mock
async def test_network_failure_fails_closed():
    respx.get(STATUS_URL).mock(side_effect=httpx.ConnectTimeout("unavailable"))

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "entitlement_check_failed"


@pytest.mark.asyncio
@respx.mock
async def test_invalid_success_payload_fails_closed():
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, content=b"not-json"))

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "entitlement_check_failed"


@pytest.mark.asyncio
@respx.mock
async def test_json_that_is_not_an_object_fails_closed():
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=["unexpected"]))

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "entitlement_check_failed"
