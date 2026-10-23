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
    """Return the Auth Service entitlement decision, failing closed on errors."""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{AUTH_SERVICE_URL}/billing/entitlement",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        api_logger.error("Basil Cloud entitlement check failed: %s", exc)
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
        return BasilCloudEligibility(
            eligible=False,
            reason="entitlement_check_failed",
            message="Basil Cloud returned an invalid entitlement response.",
        )

    return BasilCloudEligibility(
        eligible=bool(body.get("eligible", False)),
        reason=body.get("reason"),
        message=body.get("message"),
    )
