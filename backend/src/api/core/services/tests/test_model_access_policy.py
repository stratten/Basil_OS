"""Unit tests for the fail-closed Basil Cloud entitlement policy."""

import httpx
import pytest
import respx

from api.core.services.model_access_policy import check_basil_cloud_eligibility
from api.services.auth_service_endpoint import AUTH_SERVICE_URL


@pytest.mark.asyncio
@respx.mock
async def test_eligible_account_returns_eligible_true():
    respx.get(f"{AUTH_SERVICE_URL}/billing/entitlement").mock(
        return_value=httpx.Response(
            200,
            json={"eligible": True, "reason": "active_subscription"},
        )
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is True
    assert result.reason == "active_subscription"


@pytest.mark.asyncio
@respx.mock
async def test_unauthenticated_token_returns_eligible_false():
    respx.get(f"{AUTH_SERVICE_URL}/billing/entitlement").mock(
        return_value=httpx.Response(401)
    )

    result = await check_basil_cloud_eligibility("expired-token")

    assert result.eligible is False
    assert result.reason == "unauthenticated"


@pytest.mark.asyncio
@respx.mock
async def test_network_failure_fails_closed():
    respx.get(f"{AUTH_SERVICE_URL}/billing/entitlement").mock(
        side_effect=httpx.ConnectTimeout("unavailable")
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "entitlement_check_failed"


@pytest.mark.asyncio
@respx.mock
async def test_ineligible_account_returns_reason_and_message():
    respx.get(f"{AUTH_SERVICE_URL}/billing/entitlement").mock(
        return_value=httpx.Response(
            200,
            json={
                "eligible": False,
                "reason": "no_payment_method",
                "message": "Please set up billing to use API models.",
            },
        )
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "no_payment_method"
    assert "billing" in (result.message or "")


@pytest.mark.asyncio
@respx.mock
async def test_invalid_success_payload_fails_closed():
    respx.get(f"{AUTH_SERVICE_URL}/billing/entitlement").mock(
        return_value=httpx.Response(200, content=b"not-json")
    )

    result = await check_basil_cloud_eligibility("token-123")

    assert result.eligible is False
    assert result.reason == "entitlement_check_failed"
