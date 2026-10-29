"""Minimal macOS Contacts lookup provider for generation context."""

from __future__ import annotations

import logging
import platform
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional, Sequence

from .contact_context import normalize_email_address

logger = logging.getLogger(__name__)


class MacContactsAuthorizationStatus(str, Enum):
    """Authorization state for macOS Contacts access."""

    UNAVAILABLE = "unavailable"
    NOT_DETERMINED = "not_determined"
    RESTRICTED = "restricted"
    DENIED = "denied"
    AUTHORIZED = "authorized"
    LIMITED = "limited"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MacContactsStatus:
    """Passive Contacts provider status for UI and generation gating."""

    available: bool
    authorization_status: MacContactsAuthorizationStatus
    detail: Optional[str] = None

    @property
    def can_lookup(self) -> bool:
        return self.available and self.authorization_status in {
            MacContactsAuthorizationStatus.AUTHORIZED,
            MacContactsAuthorizationStatus.LIMITED,
        }


@dataclass(frozen=True)
class MacContactIdentity:
    """Minimal deterministic identity data resolved from Contacts."""

    email_addresses: List[str] = field(default_factory=list)
    display_name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    organization_name: Optional[str] = None
    job_title: Optional[str] = None

    @property
    def primary_email(self) -> Optional[str]:
        return self.email_addresses[0] if self.email_addresses else None


class MacContactsProvider:
    """Read-only wrapper around Contacts.framework through PyObjC."""

    def __init__(self) -> None:
        self._contacts_module = None
        self._import_error: Optional[Exception] = None

    def status(self) -> MacContactsStatus:
        """Return provider availability and authorization without prompting."""
        contacts = self._load_contacts_module()
        if contacts is None:
            return MacContactsStatus(
                available=False,
                authorization_status=MacContactsAuthorizationStatus.UNAVAILABLE,
                detail=self._unavailable_detail(),
            )

        try:
            raw_status = contacts.CNContactStore.authorizationStatusForEntityType_(
                contacts.CNEntityTypeContacts
            )
        except Exception as exc:
            logger.warning("Unable to read macOS Contacts authorization status: %s", exc)
            return MacContactsStatus(
                available=False,
                authorization_status=MacContactsAuthorizationStatus.UNAVAILABLE,
                detail=str(exc),
            )

        authorization_status = self._map_authorization_status(contacts, raw_status)
        return MacContactsStatus(
            available=authorization_status != MacContactsAuthorizationStatus.UNAVAILABLE,
            authorization_status=authorization_status,
        )

    def request_access(self) -> MacContactsStatus:
        """Prompt for Contacts access and return the resulting status."""
        contacts = self._load_contacts_module()
        if contacts is None:
            return self.status()

        completion_event = threading.Event()
        result = {"granted": False, "error": None}

        def completion_handler(granted, error) -> None:
            result["granted"] = bool(granted)
            result["error"] = error
            completion_event.set()

        try:
            store = contacts.CNContactStore.alloc().init()
            store.requestAccessForEntityType_completionHandler_(
                contacts.CNEntityTypeContacts,
                completion_handler,
            )
            completion_event.wait()
        except Exception as exc:
            logger.warning("Unable to request macOS Contacts access: %s", exc)
            return MacContactsStatus(
                available=True,
                authorization_status=MacContactsAuthorizationStatus.UNKNOWN,
                detail=str(exc),
            )

        if result["error"] is not None:
            logger.warning("macOS Contacts access request returned error: %s", result["error"])

        return self.status()

    def lookup_by_email(self, email: str) -> Optional[MacContactIdentity]:
        """Resolve one contact by email address without mutating Basil storage."""
        normalized_email = normalize_email_address(email)
        if not normalized_email or not self.status().can_lookup:
            return None

        contacts = self._load_contacts_module()
        if contacts is None:
            return None

        try:
            predicate = contacts.CNContact.predicateForContactsMatchingEmailAddress_(
                normalized_email
            )
            matches = self._contacts_matching_predicate(contacts, predicate)
        except Exception as exc:
            logger.warning("Unable to lookup macOS contact by email %s: %s", normalized_email, exc)
            return None

        return self._first_identity_with_email(matches, normalized_email)

    def search(self, query: str, limit: int = 5) -> List[MacContactIdentity]:
        """Bounded read-only search by contact name or email."""
        cleaned_query = query.strip()
        if not cleaned_query or limit <= 0 or not self.status().can_lookup:
            return []

        contacts = self._load_contacts_module()
        if contacts is None:
            return []

        normalized_email = normalize_email_address(cleaned_query)
        try:
            if normalized_email:
                identity = self.lookup_by_email(normalized_email)
                return [identity] if identity else []

            predicate = contacts.CNContact.predicateForContactsMatchingName_(cleaned_query)
            matches = self._contacts_matching_predicate(contacts, predicate)
        except Exception as exc:
            logger.warning("Unable to search macOS Contacts for %r: %s", cleaned_query, exc)
            return []

        identities: List[MacContactIdentity] = []
        for contact in matches:
            identity = self._identity_from_contact(contact)
            if identity and identity.primary_email:
                identities.append(identity)
            if len(identities) >= limit:
                break
        return identities

    def _load_contacts_module(self):
        if self._contacts_module is not None:
            return self._contacts_module

        if platform.system() != "Darwin":
            return None

        try:
            import Contacts  # type: ignore
        except Exception as exc:
            self._import_error = exc
            return None

        self._contacts_module = Contacts
        return Contacts

    def _unavailable_detail(self) -> str:
        if platform.system() != "Darwin":
            return "macOS Contacts are only available on Darwin platforms."
        if self._import_error is not None:
            return f"Contacts.framework import failed: {self._import_error}"
        return "Contacts.framework is unavailable."

    def _map_authorization_status(
        self,
        contacts,
        raw_status: int,
    ) -> MacContactsAuthorizationStatus:
        status_map = {
            getattr(contacts, "CNAuthorizationStatusNotDetermined", None): MacContactsAuthorizationStatus.NOT_DETERMINED,
            getattr(contacts, "CNAuthorizationStatusRestricted", None): MacContactsAuthorizationStatus.RESTRICTED,
            getattr(contacts, "CNAuthorizationStatusDenied", None): MacContactsAuthorizationStatus.DENIED,
            getattr(contacts, "CNAuthorizationStatusAuthorized", None): MacContactsAuthorizationStatus.AUTHORIZED,
            getattr(contacts, "CNAuthorizationStatusLimited", None): MacContactsAuthorizationStatus.LIMITED,
        }
        return status_map.get(raw_status, MacContactsAuthorizationStatus.UNKNOWN)

    def _contacts_matching_predicate(self, contacts, predicate) -> Sequence[object]:
        store = contacts.CNContactStore.alloc().init()
        result = store.unifiedContactsMatchingPredicate_keysToFetch_error_(
            predicate,
            self._keys_to_fetch(contacts),
            None,
        )
        if isinstance(result, tuple):
            contacts_result = result[0]
            error = result[1] if len(result) > 1 else None
            if error is not None:
                logger.warning("Contacts.framework returned lookup error: %s", error)
                return []
            return contacts_result or []
        return result or []

    def _keys_to_fetch(self, contacts) -> List[object]:
        return [
            contacts.CNContactGivenNameKey,
            contacts.CNContactFamilyNameKey,
            contacts.CNContactOrganizationNameKey,
            contacts.CNContactJobTitleKey,
            contacts.CNContactEmailAddressesKey,
        ]

    def _first_identity_with_email(
        self,
        contacts: Iterable[object],
        normalized_email: str,
    ) -> Optional[MacContactIdentity]:
        for contact in contacts:
            identity = self._identity_from_contact(contact)
            if identity and normalized_email in identity.email_addresses:
                return identity
        return None

    def _identity_from_contact(self, contact) -> Optional[MacContactIdentity]:
        email_addresses = self._email_addresses_from_contact(contact)
        if not email_addresses:
            return None

        given_name = self._clean_string(getattr(contact, "givenName", lambda: None)())
        family_name = self._clean_string(getattr(contact, "familyName", lambda: None)())
        organization_name = self._clean_string(
            getattr(contact, "organizationName", lambda: None)()
        )
        job_title = self._clean_string(getattr(contact, "jobTitle", lambda: None)())
        display_name = self._display_name(given_name, family_name, organization_name)

        return MacContactIdentity(
            email_addresses=email_addresses,
            display_name=display_name,
            given_name=given_name,
            family_name=family_name,
            organization_name=organization_name,
            job_title=job_title,
        )

    def _email_addresses_from_contact(self, contact) -> List[str]:
        raw_values = getattr(contact, "emailAddresses", lambda: [])()
        email_addresses: List[str] = []
        for labeled_value in raw_values:
            raw_email = labeled_value.value()
            normalized_email = normalize_email_address(str(raw_email))
            if normalized_email and normalized_email not in email_addresses:
                email_addresses.append(normalized_email)
        return email_addresses

    def _display_name(
        self,
        given_name: Optional[str],
        family_name: Optional[str],
        organization_name: Optional[str],
    ) -> Optional[str]:
        personal_name = " ".join(
            part for part in [given_name, family_name] if part
        ).strip()
        if personal_name:
            return personal_name
        return organization_name

    def _clean_string(self, value: object) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


mac_contacts_provider = MacContactsProvider()
