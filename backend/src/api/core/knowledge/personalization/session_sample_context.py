"""Map live-session context values onto writing-sample context types and recipients."""

from typing import Any, Dict, Optional, Tuple

from ..personalization_models import ContextType
from .contact_context import parse_email_participant


EDITABLE_SAMPLE_CONTEXT_TYPES = (
    ContextType.EMAIL_REPLY,
    ContextType.EMAIL_COMPOSE,
    ContextType.SOCIAL_MEDIA,
    ContextType.DOCUMENT,
)


def map_session_context_type(session_context_type: Optional[str]) -> Optional[ContextType]:
    """Return the writing-sample context for a session context string, or None when it is unknown."""
    if not session_context_type:
        return None
    value = session_context_type.strip().lower()
    if not value:
        return None
    if value.startswith("email_compose"):
        return ContextType.EMAIL_COMPOSE
    if value.startswith("email"):
        return ContextType.EMAIL_REPLY
    if value.startswith("social_media"):
        return ContextType.SOCIAL_MEDIA
    return ContextType.DOCUMENT


def resolve_session_recipient(
    session_context_type: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(recipient_email, recipient_name)`` for email sessions, otherwise ``(None, None)``."""
    if map_session_context_type(session_context_type) not in (ContextType.EMAIL_REPLY, ContextType.EMAIL_COMPOSE):
        return None, None
    metadata = metadata or {}
    recipient = (
        metadata.get("primary_participant_email")
        or metadata.get("sender_email")
        or metadata.get("recipient_email")
        or metadata.get("sender")
        or metadata.get("recipient")
    )
    recipient_name = metadata.get("primary_participant_name")
    parsed_recipient = parse_email_participant(str(recipient)) if recipient else None
    if parsed_recipient:
        recipient = parsed_recipient.email
        recipient_name = recipient_name or parsed_recipient.display_name
    return recipient, recipient_name
