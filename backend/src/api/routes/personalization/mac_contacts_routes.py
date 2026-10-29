"""macOS Contacts endpoints for local personalization context."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.core.knowledge.personalization.mac_contacts_provider import (
    MacContactIdentity,
    MacContactsStatus,
    mac_contacts_provider,
)
from api.core.preferences.preferences_io import load_preferences


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/personalization/contacts/mac", tags=["personalization"])


class MacContactsStatusResponse(BaseModel):
    """Status payload for the backend macOS Contacts provider."""

    available: bool
    preference_enabled: bool
    authorization_status: str
    can_lookup: bool
    detail: Optional[str] = None


class MacContactIdentityResponse(BaseModel):
    """Minimal deterministic Contacts identity data."""

    email_addresses: List[str]
    display_name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    organization_name: Optional[str] = None
    job_title: Optional[str] = None


class MacContactsLookupResponse(BaseModel):
    """Read-only contact lookup response."""

    found: bool
    contact: Optional[MacContactIdentityResponse] = None


@router.get("/status", response_model=MacContactsStatusResponse)
async def get_mac_contacts_status() -> MacContactsStatusResponse:
    """Return passive provider status without prompting for Contacts access."""
    status = mac_contacts_provider.status()
    return _status_response(status)


@router.post("/request-access", response_model=MacContactsStatusResponse)
async def request_mac_contacts_access() -> MacContactsStatusResponse:
    """Prompt for Contacts permission after explicit user action in Settings."""
    status = mac_contacts_provider.request_access()
    return _status_response(status)


@router.get("/lookup", response_model=MacContactsLookupResponse)
async def lookup_mac_contact(
    email: str = Query(..., min_length=3),
) -> MacContactsLookupResponse:
    """Resolve a single contact by email without creating Basil contact rows."""
    preferences = load_preferences()
    if not preferences.behavior.allow_mac_contacts_for_generation:
        raise HTTPException(
            status_code=403,
            detail="Mac Contacts generation access is disabled in behavior settings.",
        )

    status = mac_contacts_provider.status()
    if not status.can_lookup:
        return MacContactsLookupResponse(found=False)

    identity = mac_contacts_provider.lookup_by_email(email)
    if not identity:
        return MacContactsLookupResponse(found=False)
    return MacContactsLookupResponse(
        found=True,
        contact=_identity_response(identity),
    )


def _status_response(status: MacContactsStatus) -> MacContactsStatusResponse:
    preferences = load_preferences()
    return MacContactsStatusResponse(
        available=status.available,
        preference_enabled=preferences.behavior.allow_mac_contacts_for_generation,
        authorization_status=status.authorization_status.value,
        can_lookup=status.can_lookup and preferences.behavior.allow_mac_contacts_for_generation,
        detail=status.detail,
    )


def _identity_response(identity: MacContactIdentity) -> MacContactIdentityResponse:
    return MacContactIdentityResponse(
        email_addresses=identity.email_addresses,
        display_name=identity.display_name,
        given_name=identity.given_name,
        family_name=identity.family_name,
        organization_name=identity.organization_name,
        job_title=identity.job_title,
    )
