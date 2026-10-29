"""Authoritative policy for Basil Cloud model access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from ..logging.api_logger import api_logger
from ...services.auth_service_endpoint import AUTH_SERVICE_URL


@dataclass(frozen=True)
class BasilCloudEligibility:
    """The Auth Service's current decision for a Basil Cloud account."""

    eligible: bool
    reason: Optional[str] = None
    message: Optional[str] = None


async def check_basil_cloud_eligibility(access_token: str) -> BasilCloudEligibility:
    """Decide Basil Cloud eligibility from the Auth Service billing status, failing closed on errors.

    The rule mirrors what the Auth Service proxy enforces for signed-in accounts that pay by card: a payment method on file, an active subscription, and spending under any limit. The proxy stays authoritative on every request. Free credit granted to an account is not reported by the billing status route, so an account that has only free credit is not treated as eligible here.
    """

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{AUTH_SERVICE_URL}/billing/status",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        api_logger.error("Basil Cloud billing status check failed: %s", exc)
        return BasilCloudEligibility(
            eligible=False,
            reason="entitlement_check_failed",
            message="Could not reach Basil Cloud to confirm eligibility. Please try again.",
        )

    if response.status_code == 401:
        return BasilCloudEligibility(
            eligible=False,
            reason="unauthenticated",
            message="Please sign in again.",
        )
    if response.status_code >= 400:
        return BasilCloudEligibility(
            eligible=False,
            reason="entitlement_check_failed",
            message=f"Basil Cloud entitlement check failed ({response.status_code}).",
        )

    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return BasilCloudEligibility(
            eligible=False,
            reason="entitlement_check_failed",
            message="Basil Cloud returned an invalid entitlement response.",
        )

    if not body.get("has_payment_method"):
        return BasilCloudEligibility(
            eligible=False,
            reason="payment_method_required",
            message="Add a payment method to use Basil Cloud.",
        )

    subscription_status = body.get("subscription_status")
    if subscription_status != "active":
        return BasilCloudEligibility(
            eligible=False,
            reason="subscription_inactive",
            message=f"Your Basil Cloud subscription is {subscription_status or 'not active'}. Update your payment method to continue.",
        )

    threshold_status = body.get("threshold_status")
    if isinstance(threshold_status, dict) and threshold_status.get("is_exceeded"):
        return BasilCloudEligibility(
            eligible=False,
            reason="usage_threshold_exceeded",
            message="You have reached your Basil Cloud spending limit.",
        )

    return BasilCloudEligibility(eligible=True, reason="active_subscription")
