"""Pydantic models for user personalization and profile storage."""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class FormalityLevel(str, Enum):
    """Formality levels for communication."""
    CASUAL = "casual"
    PROFESSIONAL = "professional"
    FORMAL = "formal"


class ToneType(str, Enum):
    """Tone types for communication."""
    FRIENDLY = "friendly"
    BUSINESS = "business"
    TECHNICAL = "technical"
    WARM = "warm"
    DIRECT = "direct"
    CONVERSATIONAL = "conversational"


class RelationshipType(str, Enum):
    """Types of contact relationships."""
    COLLEAGUE = "colleague"
    MANAGER = "manager"
    DIRECT_REPORT = "direct_report"
    CLIENT = "client"
    VENDOR = "vendor"
    FRIEND = "friend"
    FAMILY = "family"
    PERSONAL = "personal"
    UNKNOWN = "unknown"


class ContextType(str, Enum):
    """Context types for communication style."""
    EMAIL_REPLY = "email_reply"
    EMAIL_COMPOSE = "email_compose"
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    DOCUMENT = "document"
    SOCIAL_MEDIA = "social_media"
    ALL = "all"


class SourceType(str, Enum):
    """Source types for writing samples."""
    EMAIL_SENT = "email_sent"
    SLACK_MESSAGE = "slack_message"
    DOCUMENT = "document"
    ASSISTANT_SESSION_ACCEPTED = "assistant_session_accepted"
    SUGGESTION_ACCEPTED = "suggestion_accepted"  # Regular (non-voice) suggestion
    MANUAL_ENTRY = "manual_entry"


class UserProfile(BaseModel):
    """User profile model."""
    id: str = Field(default="default", description="User ID (single user for now)")
    
    # Identity
    full_name: Optional[str] = Field(None, description="User's full name")
    preferred_name: Optional[str] = Field(None, description="Preferred name for addressing")
    email: Optional[str] = Field(None, description="User's email address")
    
    # Professional context
    job_title: Optional[str] = Field(None, description="User's job title")
    company_name: Optional[str] = Field(None, description="User's company name")
    industry: Optional[str] = Field(None, description="User's industry")
    
    # Communication preferences
    default_formality: Optional[FormalityLevel] = Field(None, description="Default formality level")
    default_tone: Optional[ToneType] = Field(None, description="Default tone")
    custom_instructions: Optional[str] = Field(
        None,
        max_length=4000,
        description="Freeform standing instructions (e.g. style/formatting preferences) applied across personalized prompts",
    )
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    profile_version: int = Field(default=1, description="Profile version for migrations")
    
    class Config:
        use_enum_values = True


class StyleAttributes(BaseModel):
    """Communication style attributes."""
    formality_level: float = Field(0.5, ge=0.0, le=1.0, description="Formality level (0=casual, 1=formal)")
    avg_sentence_length: float = Field(15.0, description="Average sentence length in words")
    greeting_patterns: List[str] = Field(default_factory=list, description="Common greeting patterns")
    closing_patterns: List[str] = Field(default_factory=list, description="Common closing patterns")
    common_phrases: List[str] = Field(default_factory=list, description="Frequently used phrases")
    vocabulary_complexity: str = Field("professional", description="Vocabulary complexity level")
    uses_contractions: bool = Field(True, description="Whether user uses contractions")
    uses_emojis: bool = Field(False, description="Whether user uses emojis")
    paragraph_structure: str = Field("varied", description="Paragraph structure preference")
    tone_markers: List[str] = Field(default_factory=list, description="Tone markers")
    style_summary: Optional[str] = Field(None, description="LLM-generated natural language summary of the user's style")


class CommunicationStyleProfile(BaseModel):
    """Learned communication style profile for a specific context."""
    id: str = Field(description="Unique identifier")
    user_id: str = Field(default="default", description="User ID")
    context_type: ContextType = Field(description="Context type for this style")
    
    # Style attributes (stored as JSON in DB)
    style_attributes: StyleAttributes = Field(default_factory=StyleAttributes)
    
    # Confidence and sample size
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in this style profile")
    sample_count: int = Field(0, description="Number of samples analyzed")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = Field(None, description="Last time this style was used")
    
    class Config:
        use_enum_values = True


class WritingSample(BaseModel):
    """User writing sample for learning and analysis."""
    id: str = Field(description="Unique identifier")
    user_id: str = Field(default="default", description="User ID")
    
    # Sample metadata
    source_type: SourceType = Field(description="Source of this writing sample")
    context_type: ContextType = Field(description="Context type")
    app_name: Optional[str] = Field(None, description="Application name")
    
    # The actual writing
    content: str = Field(description="The writing sample content")
    content_hash: str = Field(description="SHA256 hash for deduplication")
    
    # Context about the writing
    recipient: Optional[str] = Field(None, description="Email/message recipient if applicable")
    subject: Optional[str] = Field(None, description="Email subject if applicable")
    relationship_type: Optional[RelationshipType] = Field(None, description="Relationship type")
    
    # Edit tracking (for future analysis)
    was_edited: bool = Field(False, description="Whether user edited before sending")
    edit_distance: Optional[int] = Field(None, description="Levenshtein distance if edited")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


class ContactRelationship(BaseModel):
    """Contact relationship information."""
    id: str = Field(description="Unique identifier")
    user_id: str = Field(default="default", description="User ID")
    
    # Contact identity
    contact_name: Optional[str] = Field(None, description="Contact's name")
    contact_email: str = Field(description="Contact's email address")
    contact_company: Optional[str] = Field(None, description="Contact's company")
    
    # Relationship metadata
    relationship_type: RelationshipType = Field(
        default=RelationshipType.UNKNOWN,
        description="Type of relationship"
    )
    formality_level: FormalityLevel = Field(
        default=FormalityLevel.PROFESSIONAL,
        description="Formality level for this contact"
    )
    
    # Communication patterns
    message_count: int = Field(0, description="Number of messages exchanged")
    last_contact_date: Optional[datetime] = Field(None, description="Last contact date")
    typical_response_time_hours: Optional[float] = Field(None, description="Typical response time")
    
    # Context
    common_topics: List[str] = Field(default_factory=list, description="Common discussion topics")
    notes: Optional[str] = Field(None, description="Optional notes about this contact")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


class UserSignature(BaseModel):
    """User email signature."""
    id: str = Field(description="Unique identifier")
    user_id: str = Field(default="default", description="User ID")
    
    # Signature content
    signature_text: str = Field(description="Signature text content")
    signature_html: Optional[str] = Field(None, description="HTML signature if available")
    
    # Usage context
    context: str = Field(default="default", description="Context (work, personal, formal, etc.)")
    is_primary: bool = Field(False, description="Whether this is the primary signature")
    
    # Detection metadata
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    occurrence_count: int = Field(1, description="Number of times seen")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence in detection")


class InsightType(str, Enum):
    """Types of personalization insights."""
    VOCABULARY = "vocabulary"
    STRUCTURE = "structure"
    TONE = "tone"
    PATTERN = "pattern"
    GREETING = "greeting"
    CLOSING = "closing"
    FORMALITY = "formality"


class PersonalizationInsight(BaseModel):
    """Derived insight for prompt enhancement."""
    id: str = Field(description="Unique identifier")
    user_id: str = Field(default="default", description="User ID")
    
    # Insight metadata
    insight_type: InsightType = Field(description="Type of insight")
    context_type: Optional[ContextType] = Field(None, description="Context type or 'all'")
    
    # The insight
    insight_key: str = Field(description="Insight key")
    insight_value: str = Field(description="Insight value (JSON for complex values)")
    
    # Confidence and usage
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in this insight")
    times_applied: int = Field(0, description="Number of times applied")
    success_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="Success rate from feedback")
    
    # Source tracking
    derived_from: str = Field(description="Source: writing_samples, feedback_analysis, pattern_recognition, manual")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


# Request/Response models for API

class UserProfileCreate(BaseModel):
    """Request model for creating/updating user profile."""
    full_name: Optional[str] = None
    preferred_name: Optional[str] = None
    email: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    industry: Optional[str] = None
    default_formality: Optional[FormalityLevel] = None
    default_tone: Optional[ToneType] = None
    custom_instructions: Optional[str] = Field(None, max_length=4000)
    
    class Config:
        use_enum_values = True


class PersonalizationContext(BaseModel):
    """Complete personalization context for prompt enhancement."""
    profile: Optional[UserProfile] = None
    style: Optional[CommunicationStyleProfile] = None
    writing_samples: List[WritingSample] = Field(default_factory=list)
    contact: Optional[ContactRelationship] = None
    signature: Optional[UserSignature] = None


class ObservationSourceType(str, Enum):
    """Source of a contact identity observation."""
    ACTIVITY_CAPTURE = "activity_capture"


class ContactIdentityObservationCreate(BaseModel):
    """Request model for recording a contact identity observation.

    Observations are unverified, screen-derived candidate identity facts. They
    must never be treated as an asserted relationship. They only carry
    directly observed identity fields plus extraction provenance.
    """
    source_type: ObservationSourceType = Field(
        default=ObservationSourceType.ACTIVITY_CAPTURE,
        description="Where the observation originated"
    )
    source_activity_id: Optional[str] = Field(None, description="Originating activity id")
    source_app_name: Optional[str] = Field(None, description="App the observation was seen in")
    source_window_title: Optional[str] = Field(None, description="Window title context")

    # Observed identity facts (no relationship inference)
    normalized_email: str = Field(description="Normalized email address of the candidate")
    display_name: Optional[str] = Field(None, description="Observed display name")
    organization_name: Optional[str] = Field(None, description="Observed organization/company")
    job_title: Optional[str] = Field(None, description="Observed job title")
    relationship_hint: Optional[str] = Field(
        None,
        description="Free-text hint about role only; never a confirmed relationship_type"
    )

    # Extraction quality
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Extractor confidence in the candidate")
    reason: Optional[str] = Field(None, description="Why the extractor produced this candidate")
    raw_evidence: Optional[str] = Field(None, description="Short verbatim snippet supporting the candidate")

    class Config:
        use_enum_values = True


class ContactIdentityObservation(BaseModel):
    """A stored contact identity observation candidate."""
    id: str = Field(description="Unique identifier")
    user_id: str = Field(default="default", description="User ID")

    source_type: ObservationSourceType = Field(
        default=ObservationSourceType.ACTIVITY_CAPTURE,
        description="Where the observation originated"
    )
    source_activity_id: Optional[str] = Field(None, description="Originating activity id")
    source_app_name: Optional[str] = Field(None, description="App the observation was seen in")
    source_window_title: Optional[str] = Field(None, description="Window title context")

    normalized_email: str = Field(description="Normalized email address of the candidate")
    display_name: Optional[str] = Field(None, description="Observed display name")
    organization_name: Optional[str] = Field(None, description="Observed organization/company")
    job_title: Optional[str] = Field(None, description="Observed job title")
    relationship_hint: Optional[str] = Field(None, description="Free-text role hint only")

    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Extractor confidence in the candidate")
    reason: Optional[str] = Field(None, description="Why the extractor produced this candidate")
    raw_evidence: Optional[str] = Field(None, description="Short verbatim snippet supporting the candidate")

    occurrence_count: int = Field(1, description="How many times this candidate has been observed")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True

