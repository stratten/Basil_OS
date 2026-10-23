"""
Email Data Models

Dataclasses and type definitions for email automation services.
These models are separated to prevent circular imports between services.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime


class EmailDataList(list):
    """List of EmailData records with optional retrieval coverage metadata."""

    def __init__(
        self,
        values=None,
        coverage_metadata: Optional[Dict[str, Any]] = None,
        served_by_client: Optional[str] = None,
    ):
        super().__init__(values or [])
        self.coverage_metadata = coverage_metadata or {}
        # The email client that ACTUALLY served this read. May differ from the requested
        # client when resolution substitutes a fallback (see _get_client_by_name). None
        # until a read path stamps it. Additive: EmailDataList is still a plain list.
        self.served_by_client = served_by_client

    def __repr__(self) -> str:
        return (
            f"EmailDataList(served_by_client={self.served_by_client!r}, "
            f"coverage_metadata={self.coverage_metadata!r}, emails={list(self)!r})"
        )


@dataclass
class EmailData:
    """Represents an email message with relevant metadata."""
    id: str
    subject: str
    sender: str
    recipient: str
    content: str
    date_sent: datetime
    is_read: bool
    is_flagged: bool = False
    folder: Optional[str] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    attachments: List[str] = None
    cc_recipients: List[str] = None  # NEW: All CC recipients  
    bcc_recipients: List[str] = None  # NEW: All BCC recipients (if available)
    
    def __post_init__(self):
        if self.attachments is None:
            self.attachments = []
        if self.cc_recipients is None:
            self.cc_recipients = []
        if self.bcc_recipients is None:
            self.bcc_recipients = []


@dataclass
class EmailClient:
    """Represents a detected email client and its capabilities."""
    name: str
    bundle_id: str
    is_running: bool
    automation_method: str
    capabilities: List[str]
    priority: int  # Lower number = higher priority


@dataclass
class EmailRequest:
    """Represents a comprehensive email request (draft, send, reply, forward)."""
    recipient: str
    subject: str
    body: str
    action: str = "draft"  # "draft", "send", "forward" (reply disabled for safety)
    reference_email_id: Optional[str] = None
    cc: List[str] = None
    bcc: List[str] = None
    attachments: List[str] = None
    
    def __post_init__(self):
        if self.cc is None:
            self.cc = []
        if self.bcc is None:
            self.bcc = []
        if self.attachments is None:
            self.attachments = []


@dataclass
class EmailOperation:
    """Represents an email organization operation."""
    operation: str  # "move", "delete", "mark_read", "mark_unread", "flag", "unflag", "archive"
    email_ids: List[str]
    target_folder: Optional[str] = None
    

@dataclass
class EmailSearchCriteria:
    """Represents search criteria for finding emails."""
    sender: Optional[str] = None
    subject_contains: Optional[str] = None
    body_contains: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    is_read: Optional[bool] = None
    is_flagged: Optional[bool] = None
    folder: Optional[str] = None
    has_attachments: Optional[bool] = None


@dataclass
class DraftRequest:
    """
    Represents a request to create an email draft.
    
    DEPRECATED: Use EmailRequest instead for comprehensive email operations.
    This class is maintained for backward compatibility.
    """
    recipient: str
    subject: str
    body: str
    reference_email_id: Optional[str] = None
    is_reply: bool = False 