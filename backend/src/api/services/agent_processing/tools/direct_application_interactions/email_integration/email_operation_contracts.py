"""Explicit safe input contracts for material email-organization operations."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .email_models import EmailOperation
from .email_tool_contracts import EmailToolInputValidationError, normalize_email_id


SUPPORTED_EMAIL_OPERATIONS = frozenset({"move", "delete", "mark_read", "flag"})


class OrganizeEmailsArgs(BaseModel):
    """One explicit Mail organization request with stable target identifiers."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["move", "delete", "mark_read", "flag"]
    email_ids: list[str] = Field(min_length=1, max_length=100)
    target_folder: Optional[str] = None
    client_name: Optional[str] = None

    @field_validator("email_ids", mode="before")
    @classmethod
    def validate_email_ids(cls, value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            raise EmailToolInputValidationError("email_ids must be a list of ids")
        normalized = [normalize_email_id(item, "email_ids") for item in value]
        if len(set(normalized)) != len(normalized):
            raise EmailToolInputValidationError("email_ids cannot contain duplicates")
        return normalized

    @field_validator("target_folder")
    @classmethod
    def normalize_target_folder(cls, value: Optional[str]) -> Optional[str]:
        normalized = str(value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_target(self) -> "OrganizeEmailsArgs":
        if self.operation == "move" and not self.target_folder:
            raise EmailToolInputValidationError("move requires target_folder")
        if self.operation != "move" and self.target_folder:
            raise EmailToolInputValidationError(
                "target_folder is only supported for move operations"
            )
        return self

    def to_email_operation(self) -> EmailOperation:
        return EmailOperation(
            operation=self.operation,
            email_ids=list(self.email_ids),
            target_folder=self.target_folder,
        )


class BulkOrganizeEmailsArgs(BaseModel):
    """A bounded set of independently validated organization requests."""

    model_config = ConfigDict(extra="forbid")

    operations: list[OrganizeEmailsArgs] = Field(min_length=1, max_length=25)

    def to_email_operations(self) -> list[EmailOperation]:
        return [operation.to_email_operation() for operation in self.operations]


def organize_emails_args_from_raw(value: Any) -> OrganizeEmailsArgs:
    """Convert raw service-tool input without accepting undocumented write verbs."""
    if isinstance(value, OrganizeEmailsArgs):
        return value
    if isinstance(value, EmailOperation):
        return OrganizeEmailsArgs(
            operation=value.operation,
            email_ids=value.email_ids,
            target_folder=value.target_folder,
        )
    if not isinstance(value, dict):
        raise EmailToolInputValidationError("organize_emails input must be an object")
    return OrganizeEmailsArgs.model_validate(value)
