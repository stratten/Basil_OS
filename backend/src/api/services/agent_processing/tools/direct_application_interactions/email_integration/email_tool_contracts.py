"""
Email tool input contracts.

These models define the narrow boundary between agent-produced tool inputs and
the existing email service dataclasses. They normalize recoverable shape drift
while rejecting ambiguous write requests before client automation runs.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from .email_models import EmailRequest, EmailSearchCriteria


EMAIL_ADDRESS_PATTERN = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
ANGLE_BRACKET_ADDRESS_PATTERN = re.compile(r"<([^<>\s]+@[^<>\s]+)>")


class EmailToolInputValidationError(ValueError):
    """Raised when an email write tool receives unsafe or ambiguous input."""


def normalize_email_id(value: Any, field_name: str = "reference_email_id") -> str:
    """Normalize stable email identifiers without guessing missing values."""
    if value is None:
        raise EmailToolInputValidationError(f"{field_name} is required")

    normalized = str(value).strip()
    if not normalized:
        raise EmailToolInputValidationError(f"{field_name} cannot be empty")

    return normalized


def normalize_email_address(value: Any, field_name: str = "recipient") -> str:
    """Normalize one explicit email address, accepting display-name wrappers."""
    if value is None:
        raise EmailToolInputValidationError(f"{field_name} is required")

    candidate = str(value).strip()
    if not candidate:
        raise EmailToolInputValidationError(f"{field_name} cannot be empty")

    bracket_match = ANGLE_BRACKET_ADDRESS_PATTERN.search(candidate)
    if bracket_match:
        candidate = bracket_match.group(1).strip()

    if not EMAIL_ADDRESS_PATTERN.match(candidate):
        raise EmailToolInputValidationError(
            f"{field_name} must be an explicit email address, not a display name"
        )

    return candidate


def normalize_email_address_list(value: Any, field_name: str) -> list[str]:
    """Normalize optional email address lists from strings or sequences."""
    if value is None:
        return []

    raw_values: list[Any]
    if isinstance(value, str):
        raw_values = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raise EmailToolInputValidationError(f"{field_name} must be a string or list of email addresses")

    normalized: list[str] = []
    for raw_value in raw_values:
        if raw_value in (None, ""):
            continue
        normalized.append(normalize_email_address(raw_value, field_name))

    return normalized


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return None


def _parse_optional_datetime(value: Any, field_name: str) -> Optional[datetime]:
    """Normalize agent-facing date strings into datetimes for email search criteria."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EmailToolInputValidationError(
                f"{field_name} must be an ISO datetime string"
            ) from exc

    raise EmailToolInputValidationError(f"{field_name} must be a datetime or ISO datetime string")


class EmailSearchCriteriaArgs(BaseModel):
    """Agent-facing contract for read/search criteria."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sender: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("sender", "from", "from_email", "sender_email", "person"),
        description="Sender email address or recognizable sender text.",
    )
    subject_contains: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("subject_contains", "subject", "subject_query"),
        description="Text that should appear in the subject.",
    )
    body_contains: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("body_contains", "body", "content_contains", "content"),
        description="Text that should appear in the message body.",
    )
    date_from: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("date_from", "date_after", "received_after", "start", "start_date"),
        description="Inclusive lower received-date bound.",
    )
    date_to: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("date_to", "date_before", "received_before", "end", "end_date"),
        description="Inclusive upper received-date bound.",
    )
    is_read: Optional[bool] = Field(default=None, description="Whether messages must be read.")
    is_flagged: Optional[bool] = Field(default=None, description="Whether messages must be flagged.")
    folder: Optional[str] = Field(default=None, description="Folder/mailbox to search.")
    has_attachments: Optional[bool] = Field(default=None, description="Whether messages must have attachments.")

    @model_validator(mode="before")
    @classmethod
    def normalize_date_range(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        date_range = normalized.pop("date_range", None)
        if isinstance(date_range, dict):
            if _first_present(normalized, "date_from", "date_after", "received_after", "start", "start_date") is None:
                start = _first_present(date_range, "date_from", "date_after", "received_after", "start", "start_date")
                if start is not None:
                    normalized["date_from"] = start
            if _first_present(normalized, "date_to", "date_before", "received_before", "end", "end_date") is None:
                end = _first_present(date_range, "date_to", "date_before", "received_before", "end", "end_date")
                if end is not None:
                    normalized["date_to"] = end
        elif date_range not in (None, "", []):
            raise EmailToolInputValidationError("date_range must be a mapping with start/end values")

        return normalized

    @field_validator("sender", "subject_contains", "body_contains", "folder", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def validate_date_bounds(cls, value: Any, info: Any) -> Optional[datetime]:
        return _parse_optional_datetime(value, info.field_name)

    def to_email_search_criteria(self) -> EmailSearchCriteria:
        return EmailSearchCriteria(
            sender=self.sender,
            subject_contains=self.subject_contains,
            body_contains=self.body_contains,
            date_from=self.date_from,
            date_to=self.date_to,
            is_read=self.is_read,
            is_flagged=self.is_flagged,
            folder=self.folder,
            has_attachments=self.has_attachments,
        )


class GetEmailsArgs(BaseModel):
    """Agent-facing contract for retrieving emails from a folder."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    folder: str = Field(default="inbox", description="Folder/mailbox to retrieve from.")
    limit: int = Field(default=10, ge=1, le=500, description="Maximum messages to retrieve.")
    search_criteria: Optional[EmailSearchCriteriaArgs] = Field(
        default=None,
        validation_alias=AliasChoices("search_criteria", "criteria"),
        description="Optional criteria used to bound retrieval.",
    )
    client_name: Optional[str] = Field(default=None, description="Optional target email client.")
    deduplicate_threads: bool = Field(default=False, description="Return only the newest message per thread.")
    skip_default_filter: bool = Field(default=False, description="Disable the default inbox date filter.")


class SearchEmailsArgs(BaseModel):
    """Agent-facing contract for searching emails."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    criteria: EmailSearchCriteriaArgs = Field(description="Criteria used to bound the search.")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum matching messages to retrieve.")
    client_name: Optional[str] = Field(default=None, description="Optional target email client.")
    deduplicate_threads: bool = Field(default=False, description="Return only the newest message per thread.")


class GetEmailMetadataArgs(BaseModel):
    """Agent-facing contract for metadata-first email retrieval."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    folder: str = Field(default="inbox", description="Folder/mailbox to retrieve from.")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum metadata records to retrieve.")
    search_criteria: Optional[EmailSearchCriteriaArgs] = Field(
        default=None,
        validation_alias=AliasChoices("search_criteria", "criteria"),
        description="Optional criteria used to bound metadata retrieval.",
    )
    client_name: Optional[str] = Field(default=None, description="Optional target email client.")
    deduplicate_threads: bool = Field(default=False, description="Return only the newest message per thread.")
    skip_default_filter: bool = Field(default=False, description="Disable the default inbox date filter.")


class ExpandEmailDetailsArgs(BaseModel):
    """Agent-facing contract for selected email body expansion."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email_ids: list[str] = Field(
        validation_alias=AliasChoices("email_ids", "ids", "message_ids"),
        min_length=1,
        max_length=25,
        description="Stable ids returned by get_email_metadata or get_emails.",
    )
    folder: str = Field(default="inbox", description="Folder/mailbox that contains the selected ids.")
    client_name: Optional[str] = Field(default=None, description="Optional target email client.")
    excerpt_chars: int = Field(default=4000, ge=1, le=20000, description="Maximum body characters per email.")

    @field_validator("email_ids", mode="before")
    @classmethod
    def validate_email_ids(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            raw_values = [part.strip() for part in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            raw_values = list(value)
        else:
            raise EmailToolInputValidationError("email_ids must be a string or list of ids")
        normalized = [normalize_email_id(raw_value, "email_ids") for raw_value in raw_values if raw_value not in (None, "")]
        if not normalized:
            raise EmailToolInputValidationError("email_ids cannot be empty")
        return normalized


def normalize_email_search_criteria(raw_input: Any) -> Optional[EmailSearchCriteria]:
    """Normalize raw agent criteria into the existing EmailSearchCriteria dataclass."""
    if raw_input is None:
        return None
    if isinstance(raw_input, EmailSearchCriteria):
        return raw_input
    if isinstance(raw_input, EmailSearchCriteriaArgs):
        return raw_input.to_email_search_criteria()
    if not isinstance(raw_input, dict):
        raise EmailToolInputValidationError("email search criteria must be a mapping")

    return EmailSearchCriteriaArgs.model_validate(raw_input).to_email_search_criteria()


class CreateNewEmailDraftArgs(BaseModel):
    """Agent-facing contract for creating a new email draft."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    recipient: str = Field(
        validation_alias=AliasChoices("recipient", "to", "email"),
        description="Final recipient email address.",
    )
    subject: str = Field(description="Email subject line.")
    body: str = Field(description="Email body content.")
    cc: list[str] = Field(default_factory=list, description="Optional CC email addresses.")
    bcc: list[str] = Field(default_factory=list, description="Optional BCC email addresses.")
    client_name: Optional[str] = Field(default=None, description="Optional target email client.")

    @field_validator("recipient", mode="before")
    @classmethod
    def validate_recipient(cls, value: Any) -> str:
        recipients = normalize_email_address_list(value, "recipient")
        if len(recipients) != 1:
            raise EmailToolInputValidationError("new email drafts require exactly one primary recipient")
        return recipients[0]

    @field_validator("cc", "bcc", mode="before")
    @classmethod
    def validate_recipient_lists(cls, value: Any, info: Any) -> list[str]:
        return normalize_email_address_list(value, info.field_name)

    @field_validator("subject", "body", mode="before")
    @classmethod
    def validate_required_text(cls, value: Any, info: Any) -> str:
        normalized = "" if value is None else str(value).strip()
        if not normalized:
            raise EmailToolInputValidationError(f"{info.field_name} cannot be empty")
        return normalized

    def to_email_request(self) -> EmailRequest:
        return EmailRequest(
            recipient=self.recipient,
            subject=self.subject,
            body=self.body,
            action="draft",
            cc=list(self.cc),
            bcc=list(self.bcc),
        )


class CreateReplyEmailDraftArgs(BaseModel):
    """Agent-facing contract for drafting a reply to an existing email."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    reference_email_id: str = Field(
        validation_alias=AliasChoices("reference_email_id", "email_id", "in_reply_to", "reply_to_id"),
        description="Stable source email/message id for the reply.",
    )
    reply_body: str = Field(
        validation_alias=AliasChoices("reply_body", "body"),
        description="Reply body content.",
    )
    reply_all: bool = Field(default=True, description="Whether to reply all.")
    draft_only: bool = Field(default=True, description="Always create a draft instead of sending.")
    client_name: Optional[str] = Field(default=None, description="Optional target email client.")

    @field_validator("reference_email_id", mode="before")
    @classmethod
    def validate_reference_email_id(cls, value: Any) -> str:
        return normalize_email_id(value)

    @field_validator("reply_body", mode="before")
    @classmethod
    def validate_reply_body(cls, value: Any) -> str:
        normalized = "" if value is None else str(value).strip()
        if not normalized:
            raise EmailToolInputValidationError("reply_body cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_draft_only(self) -> "CreateReplyEmailDraftArgs":
        if self.draft_only is not True:
            raise EmailToolInputValidationError("reply email tool only supports draft_only=True")
        return self

    def to_email_request(self) -> EmailRequest:
        return EmailRequest(
            recipient="",
            subject="",
            body=self.reply_body,
            action="reply",
            reference_email_id=self.reference_email_id,
        )


def create_new_email_draft_args_from_raw(raw_input: Any) -> CreateNewEmailDraftArgs:
    """Build new-draft args from an agent tool payload or existing request object."""
    if isinstance(raw_input, CreateNewEmailDraftArgs):
        return raw_input

    if isinstance(raw_input, EmailRequest):
        return CreateNewEmailDraftArgs(
            recipient=raw_input.recipient,
            subject=raw_input.subject,
            body=raw_input.body,
            cc=raw_input.cc,
            bcc=raw_input.bcc,
        )

    if not isinstance(raw_input, dict):
        raise EmailToolInputValidationError("new email draft input must be a mapping")

    return CreateNewEmailDraftArgs.model_validate(raw_input)


def create_reply_email_draft_args_from_raw(raw_input: Any) -> CreateReplyEmailDraftArgs:
    """Build reply-draft args from an agent tool payload or existing request object."""
    if isinstance(raw_input, CreateReplyEmailDraftArgs):
        return raw_input

    if isinstance(raw_input, EmailRequest):
        return CreateReplyEmailDraftArgs(
            reference_email_id=raw_input.reference_email_id,
            reply_body=raw_input.body,
        )

    if not isinstance(raw_input, dict):
        raise EmailToolInputValidationError("reply email draft input must be a mapping")

    return CreateReplyEmailDraftArgs.model_validate(raw_input)


def create_draft_args_from_legacy_payload(raw_input: Any) -> CreateNewEmailDraftArgs | CreateReplyEmailDraftArgs:
    """
    Interpret legacy draft payloads without guessing unsafe destinations.

    If a reference email id or reply flag is present, the payload is treated as
    a reply draft; otherwise it is treated as a new email draft.
    """
    if isinstance(raw_input, (CreateNewEmailDraftArgs, CreateReplyEmailDraftArgs)):
        return raw_input

    if isinstance(raw_input, EmailRequest):
        if raw_input.action == "reply" or raw_input.reference_email_id:
            return create_reply_email_draft_args_from_raw(raw_input)
        return create_new_email_draft_args_from_raw(raw_input)

    if not isinstance(raw_input, dict):
        raise EmailToolInputValidationError("email draft input must be a mapping")

    reference_email_id = _first_present(raw_input, "reference_email_id", "email_id", "in_reply_to", "reply_to_id")
    is_reply = bool(raw_input.get("is_reply")) or reference_email_id is not None

    if is_reply:
        reply_payload = {
            "reference_email_id": reference_email_id,
            "reply_body": _first_present(raw_input, "reply_body", "body"),
            "reply_all": raw_input.get("reply_all", True),
            "draft_only": raw_input.get("draft_only", True),
            "client_name": raw_input.get("client_name"),
        }
        return CreateReplyEmailDraftArgs.model_validate(reply_payload)

    new_draft_payload = {
        "recipient": _first_present(raw_input, "recipient", "to", "email"),
        "subject": raw_input.get("subject"),
        "body": raw_input.get("body"),
        "cc": raw_input.get("cc", []),
        "bcc": raw_input.get("bcc", []),
        "client_name": raw_input.get("client_name"),
    }
    return CreateNewEmailDraftArgs.model_validate(new_draft_payload)
