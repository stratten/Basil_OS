from datetime import datetime
from enum import Enum

import pytest

from api.services.agent_processing.lifecycle.runtime.ledger_json import (
    LedgerJSONNormalizationError,
    sanitize_ledger_email_list,
    sanitize_ledger_email_record,
    to_ledger_json_value,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailData,
    EmailDataList,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_tool_contracts import (
    EmailSearchCriteriaArgs,
)


class SampleState(Enum):
    READY = "ready"


def test_normalizes_pydantic_dates_and_deterministic_collections() -> None:
    criteria = EmailSearchCriteriaArgs(
        date_from="2026-01-01T00:00:00+00:00",
        date_to="2026-01-02T00:00:00+00:00",
    )

    assert to_ledger_json_value(
        {"criteria": criteria, "values": {2, 1}, "state": SampleState.READY}
    ) == {
        "criteria": {
            "sender": None,
            "subject_contains": None,
            "body_contains": None,
            "date_from": "2026-01-01T00:00:00Z",
            "date_to": "2026-01-02T00:00:00Z",
            "is_read": None,
            "is_flagged": None,
            "folder": None,
            "has_attachments": None,
        },
        "values": [1, 2],
        "state": "ready",
    }


def test_email_projection_excludes_content_and_attachments() -> None:
    email = EmailData(
        id="mail-1",
        subject="Subject",
        sender="sender@example.test",
        recipient="recipient@example.test",
        content="private message body",
        date_sent=datetime(2026, 1, 1, 12, 0),
        is_read=True,
        attachments=["private.pdf"],
    )

    metadata = sanitize_ledger_email_record(email)

    assert metadata["id"] == "mail-1"
    assert metadata["date_sent"] == "2026-01-01T12:00:00"
    assert "content" not in metadata
    assert "attachments" not in metadata


def test_email_list_evidence_keeps_coverage_without_bodies() -> None:
    emails = EmailDataList(
        [
            EmailData(
                id="mail-1",
                subject="Subject",
                sender="sender@example.test",
                recipient="recipient@example.test",
                content="private message body",
                date_sent=datetime(2026, 1, 1, 12, 0),
                is_read=True,
            )
        ],
        coverage_metadata={"coverage_complete": "true"},
    )

    evidence = sanitize_ledger_email_list(emails)

    assert evidence["coverage_metadata"] == {"coverage_complete": "true"}
    assert evidence["items"][0]["id"] == "mail-1"
    assert "content" not in str(evidence)


def test_unsupported_values_are_not_stringified() -> None:
    with pytest.raises(LedgerJSONNormalizationError):
        to_ledger_json_value(object())
