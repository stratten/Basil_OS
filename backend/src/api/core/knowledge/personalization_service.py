"""Service for managing user personalization data."""

import uuid
import json
import hashlib
import aiosqlite
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from .personalization_models import (
    UserProfile,
    CommunicationStyleProfile,
    StyleAttributes,
    WritingSample,
    ContactRelationship,
    UserSignature,
    PersonalizationInsight,
    PersonalizationContext,
    UserProfileCreate,
    ContextType,
    SourceType,
    RelationshipType,
    FormalityLevel,
    ToneType,
    InsightType
)
from .personalization.writing_samples_manager import WritingSamplesManager
from .personalization.signatures_manager import SignaturesManager
from .personalization.communication_style_manager import CommunicationStyleManager
from .personalization.contacts_manager import ContactsManager
from .personalization.contact_observations_manager import ContactObservationsManager
from .personalization.profile_manager import ProfileManager
from .personalization.contact_context import normalize_email_address
from .personalization.mac_contacts_provider import MacContactIdentity, mac_contacts_provider
from .sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
)
from ..preferences.preferences_io import load_preferences

logger = logging.getLogger(__name__)

# Minimum observation confidence required before a screen-derived candidate may
# enrich generation. Header-with-name and strong agentic candidates clear this
# bar; bare addresses and loose body matches deliberately do not.
OBSERVATION_GENERATION_MIN_CONFIDENCE = 0.7


class PersonalizationService:
    """Service for managing user personalization and learning."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize the personalization service.
        
        Args:
            db_path: Path to knowledge database. Defaults to ~/.basil/knowledge_base.db
        """
        if db_path is None:
            db_path = str(Path.home() / ".basil" / "knowledge_base.db")
        self.db_path = db_path
        self.writing_samples = WritingSamplesManager(db_path)
        self.signatures = SignaturesManager(db_path)
        self.communication_styles = CommunicationStyleManager(db_path)
        self.contacts = ContactsManager(db_path)
        self.contact_observations = ContactObservationsManager(db_path)
        self.profile = ProfileManager(db_path)
        logger.info(f"PersonalizationService initialized with db_path: {self.db_path}")
    
    @asynccontextmanager
    async def _get_connection(self):
        """Get async database connection."""
        conn = await get_async_connection(
            self.db_path, ensure_schema=False, foreign_keys=False
        )
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()
    
    # ============================================================================
    # USER PROFILE OPERATIONS (delegated to ProfileManager)
    # ============================================================================
    
    async def get_user_profile(self, user_id: str = "default") -> Optional[UserProfile]:
        """Get user profile by ID."""
        return await self.profile.get_user_profile(user_id)
    
    async def create_or_update_user_profile(
        self,
        profile_data: UserProfileCreate,
        user_id: str = "default"
    ) -> UserProfile:
        """Create or update user profile."""
        return await self.profile.create_or_update_user_profile(
            profile_data=profile_data,
            user_id=user_id
        )
    
    # ============================================================================
    # COMMUNICATION STYLE PROFILE OPERATIONS (delegated to CommunicationStyleManager)
    # ============================================================================
    
    async def get_communication_style(
        self,
        context_type: ContextType,
        user_id: str = "default"
    ) -> Optional[CommunicationStyleProfile]:
        """Get communication style for a specific context."""
        return await self.communication_styles.get_communication_style(
            context_type=context_type,
            user_id=user_id
        )
    
    async def save_communication_style(
        self,
        style: CommunicationStyleProfile
    ) -> CommunicationStyleProfile:
        """Save or update communication style profile."""
        return await self.communication_styles.save_communication_style(style)
    
    async def analyze_and_update_style(
        self,
        context_type: ContextType,
        user_id: str = "default",
        force_reanalysis: bool = False
    ) -> Optional[CommunicationStyleProfile]:
        """
        Analyze writing samples and update communication style profile.
        
        Args:
            context_type: Context type to analyze
            user_id: User ID
            force_reanalysis: If True, reanalyze even if recent analysis exists
            
        Returns:
            Updated CommunicationStyleProfile or None if no samples
        """
        return await self.communication_styles.analyze_and_update_style(
            context_type=context_type,
            user_id=user_id,
            force_reanalysis=force_reanalysis
        )
    
    async def analyze_all_contexts(
        self,
        user_id: str = "default"
    ) -> Dict[str, Optional[CommunicationStyleProfile]]:
        """
        Analyze and update style profiles for all contexts that have samples.
        
        Args:
            user_id: User ID
            
        Returns:
            Dict mapping context_type to updated profile (or None if no samples)
        """
        return await self.communication_styles.analyze_all_contexts(user_id=user_id)
    
    # ============================================================================
    # WRITING SAMPLES OPERATIONS (delegated to WritingSamplesManager)
    # ============================================================================
    
    async def add_writing_sample(
        self,
        content: str,
        source_type: SourceType,
        context_type: ContextType,
        app_name: Optional[str] = None,
        recipient: Optional[str] = None,
        subject: Optional[str] = None,
        relationship_type: Optional[RelationshipType] = None,
        was_edited: bool = False,
        edit_distance: Optional[int] = None,
        user_id: str = "default",
        auto_analyze_style: bool = True,
        assistant_output_id: Optional[int] = None
    ) -> WritingSample:
        """
        Add a writing sample.
        
        Args:
            auto_analyze_style: If True, triggers style analysis after adding sample
            
        Returns:
            Created WritingSample
        """
        sample = await self.writing_samples.add_writing_sample(
            content=content,
            source_type=source_type,
            context_type=context_type,
            app_name=app_name,
            recipient=recipient,
            subject=subject,
            relationship_type=relationship_type,
            was_edited=was_edited,
            edit_distance=edit_distance,
            user_id=user_id,
            assistant_output_id=assistant_output_id
        )
        
        # Trigger style analysis for this context
        if auto_analyze_style:
            try:
                await self.communication_styles.analyze_and_update_style(
                    context_type=context_type,
                    user_id=user_id
                )
                logger.info(f"Style analysis triggered for context: {context_type.value}")
            except Exception as e:
                logger.error(f"Failed to analyze style after adding sample: {e}")
                # Don't fail the sample addition if analysis fails
        
        return sample
    
    async def get_relevant_writing_samples(
        self,
        context_type: ContextType,
        recipient: Optional[str] = None,
        app_name: Optional[str] = None,
        limit: int = 3,
        user_id: str = "default"
    ) -> List[WritingSample]:
        """Get most relevant writing samples for context."""
        return await self.writing_samples.get_relevant_writing_samples(
            context_type=context_type,
            recipient=recipient,
            app_name=app_name,
            limit=limit,
            user_id=user_id
        )
    
    async def get_writing_samples_count(
        self,
        context_type: Optional[ContextType] = None,
        user_id: str = "default"
    ) -> int:
        """Get count of writing samples."""
        return await self.writing_samples.get_writing_samples_count(
            context_type=context_type,
            user_id=user_id
        )
    
    async def list_writing_samples(
        self,
        context_type: Optional[ContextType] = None,
        limit: int = 50,
        offset: int = 0,
        user_id: str = "default"
    ) -> List[WritingSample]:
        """List writing samples with pagination."""
        return await self.writing_samples.list_writing_samples(
            context_type=context_type,
            limit=limit,
            offset=offset,
            user_id=user_id
        )
    
    async def delete_writing_sample(
        self,
        sample_id: str,
        user_id: str = "default"
    ) -> bool:
        """Delete a specific writing sample."""
        return await self.writing_samples.delete_writing_sample(
            sample_id=sample_id,
            user_id=user_id
        )
    
    async def update_writing_sample(
        self,
        sample_id: str,
        content: str,
        user_id: str = "default",
        context_type: Optional[ContextType] = None,
        recipient: Optional[str] = None,
        update_recipient: bool = False
    ) -> Optional[WritingSample]:
        """Update a writing sample's content, context type, and recipient."""
        return await self.writing_samples.update_writing_sample(
            sample_id=sample_id,
            content=content,
            user_id=user_id,
            context_type=context_type,
            recipient=recipient,
            update_recipient=update_recipient
        )

    async def find_sample_for_assistant_output(
        self,
        assistant_output_id: int,
        candidate_contents: List[str],
        user_id: str = "default"
    ) -> Optional[WritingSample]:
        """Return the writing sample saved from an Assistant History row, if any."""
        return await self.writing_samples.find_sample_for_assistant_output(
            assistant_output_id=assistant_output_id,
            candidate_contents=candidate_contents,
            user_id=user_id
        )

    async def delete_all_writing_samples(
        self,
        context_type: Optional[ContextType] = None,
        user_id: str = "default"
    ) -> int:
        """Delete all writing samples, optionally filtered by context type."""
        return await self.writing_samples.delete_all_writing_samples(
            context_type=context_type,
            user_id=user_id
        )
    
    # ============================================================================
    # CONTACT RELATIONSHIPS OPERATIONS (delegated to ContactsManager)
    # ============================================================================
    
    async def get_or_create_contact(
        self,
        contact_email: str,
        contact_name: Optional[str] = None,
        user_id: str = "default",
        contact_company: Optional[str] = None
    ) -> ContactRelationship:
        """Get existing contact or create new one."""
        return await self.contacts.get_or_create_contact(
            contact_email=contact_email,
            contact_name=contact_name,
            user_id=user_id,
            contact_company=contact_company
        )

    async def get_contact_by_email(
        self,
        contact_email: str,
        user_id: str = "default"
    ) -> Optional[ContactRelationship]:
        """Get an existing contact by email without creating a new record."""
        return await self.contacts.get_contact_by_email(
            contact_email=contact_email,
            user_id=user_id
        )
    
    async def update_contact_interaction(
        self,
        contact_email: str,
        user_id: str = "default"
    ) -> None:
        """Update contact interaction count and last contact date."""
        return await self.contacts.update_contact_interaction(
            contact_email=contact_email,
            user_id=user_id
        )
    
    # ============================================================================
    # USER SIGNATURES OPERATIONS (delegated to SignaturesManager)
    # ============================================================================
    
    async def add_or_update_signature(
        self,
        signature_text: str,
        context: str = "default",
        signature_html: Optional[str] = None,
        user_id: str = "default"
    ) -> UserSignature:
        """Add or update a user signature."""
        return await self.signatures.add_or_update_signature(
            signature_text=signature_text,
            context=context,
            signature_html=signature_html,
            user_id=user_id
        )
    
    async def get_primary_signature(
        self,
        context: str = "default",
        user_id: str = "default"
    ) -> Optional[UserSignature]:
        """Get primary signature for context."""
        return await self.signatures.get_primary_signature(
            context=context,
            user_id=user_id
        )
    
    # ============================================================================
    # PERSONALIZATION CONTEXT BUILDER
    # ============================================================================
    
    async def build_personalization_context(
        self,
        context_type: ContextType,
        recipient: Optional[str] = None,
        app_name: Optional[str] = None,
        user_id: str = "default"
    ) -> PersonalizationContext:
        """Build complete personalization context for prompt enhancement.
        
        Args:
            context_type: Context type (email_reply, social_media, document, etc.)
            recipient: Optional recipient (email address, Slack user, etc.)
            app_name: Optional app name (Slack, Mail, Discord, Google Docs, etc.)
            user_id: User ID
            
        Returns:
            PersonalizationContext with all available data
        """
        # Fetch all personalization data in parallel would be ideal,
        # but for simplicity we'll do it sequentially for now
        normalized_recipient = normalize_email_address(recipient) if recipient else None
        
        profile = await self.get_user_profile(user_id)
        style = await self.get_communication_style(context_type, user_id)
        samples = await self.get_relevant_writing_samples(
            context_type, 
            recipient=normalized_recipient,
            app_name=app_name,
            limit=3, 
            user_id=user_id
        )
        contact = None
        if normalized_recipient:
            contact = await self.get_contact_by_email(normalized_recipient, user_id=user_id)
            contact = self._enrich_contact_from_mac_contacts(
                contact=contact,
                normalized_recipient=normalized_recipient,
                user_id=user_id,
            )
            contact = await self._enrich_contact_from_observations(
                contact=contact,
                normalized_recipient=normalized_recipient,
                user_id=user_id,
            )
        signature = await self.get_primary_signature(user_id=user_id)
        
        return PersonalizationContext(
            profile=profile,
            style=style,
            writing_samples=samples,
            contact=contact,
            signature=signature
        )

    def _enrich_contact_from_mac_contacts(
        self,
        contact: Optional[ContactRelationship],
        normalized_recipient: str,
        user_id: str,
    ) -> Optional[ContactRelationship]:
        """Merge transient macOS Contacts identity into prompt context only."""
        try:
            preferences = load_preferences()
            if not preferences.behavior.allow_mac_contacts_for_generation:
                return contact

            identity = mac_contacts_provider.lookup_by_email(normalized_recipient)
            if not identity:
                return contact

            if contact:
                return contact.model_copy(
                    update={
                        "contact_name": contact.contact_name or identity.display_name,
                        "contact_company": contact.contact_company or identity.organization_name,
                    }
                )
            return self._transient_contact_from_mac_identity(
                identity=identity,
                normalized_recipient=normalized_recipient,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("Unable to enrich contact from macOS Contacts: %s", exc)
            return contact

    def _transient_contact_from_mac_identity(
        self,
        identity: MacContactIdentity,
        normalized_recipient: str,
        user_id: str,
    ) -> ContactRelationship:
        """Build a non-persisted contact identity for generation context."""
        return ContactRelationship(
            id=f"mac-contacts:{normalized_recipient}",
            user_id=user_id,
            contact_name=identity.display_name,
            contact_email=identity.primary_email or normalized_recipient,
            contact_company=identity.organization_name,
            relationship_type=RelationshipType.UNKNOWN,
            formality_level=FormalityLevel.PROFESSIONAL,
            message_count=0,
            common_topics=[],
            notes=None,
        )

    async def _enrich_contact_from_observations(
        self,
        contact: Optional[ContactRelationship],
        normalized_recipient: str,
        user_id: str,
    ) -> Optional[ContactRelationship]:
        """Fill missing identity fields from high-confidence observations.

        Observations are screen-derived candidates. They are used as transient
        prompt context only: they may supply a missing name or organization but
        must never assert relationship_type, formality, message counts, notes,
        or topics. Nothing here is persisted.
        """
        try:
            if contact and contact.contact_name and contact.contact_company:
                return contact

            observation = await self.contact_observations.get_best_observation_for_email(
                normalized_recipient,
                user_id=user_id,
                min_confidence=OBSERVATION_GENERATION_MIN_CONFIDENCE,
            )
            if not observation:
                return contact

            if contact:
                return contact.model_copy(
                    update={
                        "contact_name": contact.contact_name or observation.display_name,
                        "contact_company": contact.contact_company or observation.organization_name,
                    }
                )
            return self._transient_contact_from_observation(
                observation=observation,
                normalized_recipient=normalized_recipient,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("Unable to enrich contact from observations: %s", exc)
            return contact

    def _transient_contact_from_observation(
        self,
        observation,
        normalized_recipient: str,
        user_id: str,
    ) -> ContactRelationship:
        """Build a non-persisted contact identity from an observation candidate."""
        return ContactRelationship(
            id=f"observation:{normalized_recipient}",
            user_id=user_id,
            contact_name=observation.display_name,
            contact_email=observation.normalized_email or normalized_recipient,
            contact_company=observation.organization_name,
            relationship_type=RelationshipType.UNKNOWN,
            formality_level=FormalityLevel.PROFESSIONAL,
            message_count=0,
            common_topics=[],
            notes=None,
        )

