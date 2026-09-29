"""Pipeline for ``POST /assistant-sessions/save-sample/{session_id}``.

Saves a AssistantSession (or a user-edited variant of it) as a writing
sample for personalization, and -- when the suggestion was generated in an
email context -- additionally:

  * Detects the trailing email signature and stores it (or bumps an
    existing signature's occurrence count) via
    ``_detect_and_store_signature``.
  * Tracks the recipient as a contact and bumps their interaction count
    via ``_track_recipient``.

These two helpers stay private to this module because their behaviour
(regex patterns, contact-extraction rules) is tightly coupled to the
save-sample endpoint and not reused elsewhere.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException

from .assistant_session_models import SaveSampleResponse
from ..assistant_session_service import AssistantSessionService
from api.core.knowledge.personalization.contact_context import (
    normalize_email_address,
    parse_email_participant,
)
from api.core.knowledge.personalization.session_sample_context import (
    map_session_context_type,
    resolve_session_recipient,
)

logger = logging.getLogger(__name__)


async def save_assistant_session_as_sample(
    session_id: str,
    request_body: Optional[dict],
    service: AssistantSessionService,
) -> SaveSampleResponse:
    """Save a AssistantSession as a writing sample for personalization.

    Called when the user explicitly clicks "Save as Sample". Captures the
    suggestion for future use in personalising email/document generation.

    Optional request body:
        - content: str -- Custom content to save (overrides session
                          suggestion if provided)
    """
    try:
        logger.info(f"📝 [ROUTER] Saving AssistantSession as sample for session: {session_id}")

        session = service.sessions.get(session_id)
        if not session:
            logger.warning(f"📝 [ROUTER] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found or expired")

        if request_body and "content" in request_body and request_body["content"]:
            suggestion_output = request_body["content"]
            logger.info(f"📝 [ROUTER] Using custom edited content ({len(suggestion_output)} chars)")
        else:
            suggestion_output = session.get("suggestion")
            if not suggestion_output:
                logger.warning(f"📝 [ROUTER] No suggestion in session: {session_id}")
                raise HTTPException(status_code=400, detail="No suggestion available to save")
            logger.info(f"📝 [ROUTER] Using original session content ({len(suggestion_output)} chars)")

        context_type = session.get("context_type", "generic")
        metadata = session.get("metadata", {})

        from api.core.knowledge.personalization_service import PersonalizationService
        from api.core.knowledge.personalization_models import SourceType, ContextType
        personalization = PersonalizationService()

        recipient, recipient_name = resolve_session_recipient(context_type, metadata)
        enum_context_type = map_session_context_type(context_type) or ContextType.DOCUMENT
        existing_contact = None
        if recipient:
            existing_contact = await personalization.get_contact_by_email(recipient)

        sample = await personalization.add_writing_sample(
            content=suggestion_output,
            source_type=SourceType.ASSISTANT_SESSION_ACCEPTED,
            context_type=enum_context_type,
            recipient=recipient,
            subject=metadata.get("subject"),
            relationship_type=existing_contact.relationship_type if existing_contact else None,
            assistant_output_id=session.get("persisted_assistant_output_id"),
        )

        logger.info(f"📝 [ROUTER] Saved writing sample: id='{sample.id}' context='{context_type}'")

        signature_detected = False
        if context_type in ["email_reply", "email_compose", "email_generic"]:
            signature_detected = await _detect_and_store_signature(
                suggestion_output,
                personalization
            )
            if signature_detected:
                logger.info(f"📝 [ROUTER] Detected and stored email signature")

        contact_tracked = False
        if context_type in ["email_reply", "email_compose", "email_generic"] and recipient:
            contact_tracked = await _track_recipient(
                recipient,
                recipient_name,
                metadata,
                personalization
            )
            if contact_tracked:
                logger.info(f"📝 [ROUTER] Tracked recipient: {recipient}")

        return SaveSampleResponse(
            status="saved",
            sample_id=sample.id,
            context_type=context_type,
            signature_detected=signature_detected,
            contact_tracked=contact_tracked,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROUTER] Failed to save AssistantSession as sample: {e}", exc_info=True)
        # Don't fail the user's workflow - return error but don't raise.
        return SaveSampleResponse(
            status="error",
            error=str(e),
            message="Failed to save sample, but your suggestion is still available",
        )


async def _detect_and_store_signature(
    content: str,
    personalization,
) -> bool:
    """Detect email signature patterns and store them.

    Args:
        content: Email content to scan for signatures
        personalization: PersonalizationService instance

    Returns:
        True if signature detected and stored, False otherwise
    """
    signature_patterns = [
        (r"\n\s*Best\s*,?\s*\n(.*?)$", "Best,"),
        (r"\n\s*Regards?\s*,?\s*\n(.*?)$", "Regards,"),
        (r"\n\s*Sincerely\s*,?\s*\n(.*?)$", "Sincerely,"),
        (r"\n\s*Thanks?\s*,?\s*\n(.*?)$", "Thanks,"),
        (r"\n--\s*\n(.*?)$", "--")
    ]

    for pattern, closing_type in signature_patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            signature_start = match.start()
            signature_text = content[signature_start:].strip()

            # Skip if too long (likely not a signature).
            if len(signature_text) > 300:
                continue

            try:
                existing = await personalization.get_signature_by_text(signature_text)
                if existing:
                    await personalization.update_signature_occurrence(existing.id)
                    logger.info(f"📝 Updated existing signature occurrence: {existing.id}")
                else:
                    from api.core.knowledge.personalization_models import UserSignatureCreate
                    signature_create = UserSignatureCreate(
                        signature_text=signature_text,
                        context="work",  # Default context
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        occurrence_count=1,
                        confidence=1.0,
                    )
                    await personalization.add_user_signature(signature_create)
                    logger.info(f"📝 Created new signature with closing: {closing_type}")

                return True
            except Exception as e:
                logger.error(f"📝 Error storing signature: {e}")
                return False

    return False


async def _track_recipient(
    recipient: str,
    recipient_name: Optional[str],
    metadata: Dict[str, Any],
    personalization,
) -> bool:
    """Track email recipient for relationship building.

    Args:
        recipient: Email recipient string (may include name)
        metadata: Email metadata from enhancement result
        personalization: PersonalizationService instance

    Returns:
        True if contact tracked, False otherwise
    """
    try:
        email = normalize_email_address(recipient)
        if not email:
            return False

        # Extract name (if format is "Name <email>").
        parsed_recipient = parse_email_participant(recipient)
        name = recipient_name or (parsed_recipient.display_name if parsed_recipient else None)

        # Promotion point: an explicit save is a strong user signal, so a
        # high-confidence screen-derived observation may fill missing identity
        # fields when creating this learned contact. Observations never assert a
        # relationship; only name/company are promoted, and only on creation.
        company = await _observed_identity_for_promotion(email, personalization)
        if company is not None:
            name = name or company.get("display_name")

        contact = await personalization.get_or_create_contact(
            contact_email=email,
            contact_name=name,
            contact_company=company.get("organization_name") if company else None,
        )

        await personalization.update_contact_interaction(email)
        logger.info(f"📝 Tracked contact interaction: {email} (ID: {contact.id})")

        return True
    except Exception as e:
        logger.error(f"📝 Error tracking recipient: {e}", exc_info=True)
        return False


async def _observed_identity_for_promotion(
    email: str,
    personalization,
) -> Optional[Dict[str, Any]]:
    """Return high-confidence observed identity fields for promotion, if any.

    Best-effort: returns ``{"display_name", "organization_name"}`` from the
    strongest screen-derived observation for ``email``, or ``None``. Never
    raises; promotion is a convenience layered on the explicit save action and
    must not break it.
    """
    try:
        from api.core.knowledge.personalization_service import (
            OBSERVATION_GENERATION_MIN_CONFIDENCE,
        )

        observation = await personalization.contact_observations.get_best_observation_for_email(
            email,
            min_confidence=OBSERVATION_GENERATION_MIN_CONFIDENCE,
        )
        if not observation:
            return None
        return {
            "display_name": observation.display_name,
            "organization_name": observation.organization_name,
        }
    except Exception as exc:
        logger.debug("Observation promotion lookup failed for %s: %s", email, exc)
        return None
