"""Email participant parsing helpers for relationship-aware personalization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional


EMAIL_ADDRESS_PATTERN = re.compile(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
HEADER_PATTERN_TEMPLATE = r"^\s*{header}\s*:\s*([^\n\r]*)"


class EmailInteractionKind(str, Enum):
    """The email interaction mode that determines the primary participant."""

    REPLY = "reply"
    COMPOSE = "compose"
    GENERIC = "generic"


@dataclass(frozen=True)
class EmailParticipant:
    """Normalized participant identity extracted from an email surface."""

    email: str
    display_name: Optional[str] = None
    source_header: Optional[str] = None

    @property
    def label(self) -> str:
        if self.display_name:
            return f"{self.display_name} <{self.email}>"
        return self.email


@dataclass(frozen=True)
class EmailParticipantContext:
    """Primary and secondary participants extracted from email context."""

    interaction_kind: EmailInteractionKind
    primary: Optional[EmailParticipant] = None
    from_participants: List[EmailParticipant] = field(default_factory=list)
    to_participants: List[EmailParticipant] = field(default_factory=list)
    cc_participants: List[EmailParticipant] = field(default_factory=list)
    bcc_participants: List[EmailParticipant] = field(default_factory=list)
    subject: Optional[str] = None

    def to_metadata(self) -> Dict[str, object]:
        """Return a JSON-safe metadata payload for Assistant Session storage."""
        metadata: Dict[str, object] = {
            "email_type": self.interaction_kind.value,
            "participants": {
                "from": [participant.label for participant in self.from_participants],
                "to": [participant.label for participant in self.to_participants],
                "cc": [participant.label for participant in self.cc_participants],
                "bcc": [participant.label for participant in self.bcc_participants],
            },
        }
        if self.subject:
            metadata["subject"] = self.subject
        if self.primary:
            metadata["primary_participant"] = self.primary.label
            metadata["primary_participant_email"] = self.primary.email
            if self.primary.display_name:
                metadata["primary_participant_name"] = self.primary.display_name

        # Preserve legacy keys used by save-sample code and older clients.
        if self.from_participants:
            metadata["sender"] = self.from_participants[0].label
            metadata["sender_email"] = self.from_participants[0].email
        if self.to_participants:
            metadata["recipient"] = self.to_participants[0].label
            metadata["recipient_email"] = self.to_participants[0].email
        return metadata


def normalize_email_address(value: Optional[str]) -> Optional[str]:
    """Return a lower-cased email address from a display string or address."""
    if not value:
        return None
    match = EMAIL_ADDRESS_PATTERN.search(value)
    if not match:
        return None
    return match.group(0).strip().lower()


def parse_email_participant(value: str, source_header: Optional[str] = None) -> Optional[EmailParticipant]:
    """Parse a single display-name/address value into an EmailParticipant."""
    email = normalize_email_address(value)
    if not email:
        return None

    display_name = _extract_display_name(value, email)
    return EmailParticipant(
        email=email,
        display_name=display_name,
        source_header=source_header,
    )


def parse_email_participant_list(value: Optional[str], source_header: Optional[str] = None) -> List[EmailParticipant]:
    """Parse comma/semicolon-separated email participants."""
    if not value:
        return []

    participants: List[EmailParticipant] = []
    for raw_part in _split_participant_values(value):
        participant = parse_email_participant(raw_part, source_header=source_header)
        if participant and participant.email not in {existing.email for existing in participants}:
            participants.append(participant)
    return participants


def extract_email_participant_context(
    content: str,
    interaction_kind: EmailInteractionKind,
) -> EmailParticipantContext:
    """Extract normalized participant context from OCR or email-thread text."""
    from_participants = parse_email_participant_list(
        _extract_header_value(content, "From"),
        source_header="From",
    )
    to_participants = parse_email_participant_list(
        _extract_header_value(content, "To"),
        source_header="To",
    )
    cc_participants = parse_email_participant_list(
        _extract_header_value(content, "Cc"),
        source_header="Cc",
    )
    bcc_participants = parse_email_participant_list(
        _extract_header_value(content, "Bcc"),
        source_header="Bcc",
    )

    primary: Optional[EmailParticipant] = None
    if interaction_kind == EmailInteractionKind.REPLY and from_participants:
        primary = from_participants[0]
    elif interaction_kind == EmailInteractionKind.COMPOSE and to_participants:
        primary = to_participants[0]
    elif from_participants:
        primary = from_participants[0]
    elif to_participants:
        primary = to_participants[0]

    return EmailParticipantContext(
        interaction_kind=interaction_kind,
        primary=primary,
        from_participants=from_participants,
        to_participants=to_participants,
        cc_participants=cc_participants,
        bcc_participants=bcc_participants,
        subject=_extract_header_value(content, "Subject"),
    )


def _extract_header_value(content: str, header: str) -> Optional[str]:
    pattern = HEADER_PATTERN_TEMPLATE.format(header=re.escape(header))
    match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _split_participant_values(value: str) -> Iterable[str]:
    parts = re.split(r"[,;](?![^<]*>)", value)
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            yield cleaned


def _extract_display_name(value: str, email: str) -> Optional[str]:
    cleaned = value.strip()
    if "<" in cleaned:
        cleaned = cleaned.split("<", 1)[0].strip()
    else:
        cleaned = EMAIL_ADDRESS_PATTERN.sub("", cleaned).strip()
    cleaned = cleaned.strip("\"' ")
    return cleaned or None
