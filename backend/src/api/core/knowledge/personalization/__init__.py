"""Personalization utilities and helpers."""

from .writing_samples_manager import WritingSamplesManager
from .signatures_manager import SignaturesManager
from .communication_style_manager import CommunicationStyleManager
from .contacts_manager import ContactsManager
from .contact_observations_manager import ContactObservationsManager
from .contact_candidate_extractor import ContactCandidateExtractor
from .profile_manager import ProfileManager
from .style_analyzer import StyleAnalyzer
from .mac_contacts_provider import (
    MacContactIdentity,
    MacContactsAuthorizationStatus,
    MacContactsProvider,
    MacContactsStatus,
)
from .contact_context import (
    EmailInteractionKind,
    EmailParticipant,
    EmailParticipantContext,
    extract_email_participant_context,
    normalize_email_address,
    parse_email_participant,
    parse_email_participant_list,
)

__all__ = [
    "WritingSamplesManager",
    "SignaturesManager",
    "CommunicationStyleManager",
    "ContactsManager",
    "ContactObservationsManager",
    "ContactCandidateExtractor",
    "ProfileManager",
    "StyleAnalyzer",
    "MacContactIdentity",
    "MacContactsAuthorizationStatus",
    "MacContactsProvider",
    "MacContactsStatus",
    "EmailInteractionKind",
    "EmailParticipant",
    "EmailParticipantContext",
    "extract_email_participant_context",
    "normalize_email_address",
    "parse_email_participant",
    "parse_email_participant_list",
]

