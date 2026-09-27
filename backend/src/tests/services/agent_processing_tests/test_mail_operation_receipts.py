"""Strict Mail operation-contract and parser tests without live mutation."""

import json

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_operation_contracts import (
    OrganizeEmailsArgs,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailOperation,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.operation_receipt_parser import (
    MailOperationReceiptParseError,
    parse_mail_operation_receipts,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.operation_receipt_scripts import (
    MailOperationReceiptScriptGenerator,
)


def _receipt(message_id: str) -> dict:
    return {
        "entity": {
            "entity_type": "email",
            "source_system": "mail_app",
            "source_scope": {"mailbox": "inbox"},
            "external_id": message_id,
        },
        "requested_effect": {"operation": "flag"},
        "execution_state": "succeeded",
        "observed_postcondition": {"flagged_status": True},
        "verification_status": "verified",
        "evidence": {"mail_readback": {"flagged_status": True}},
        "discrepancy": {},
    }


def test_organization_contract_rejects_duplicate_ids_and_missing_move_target():
    with pytest.raises(ValueError, match="duplicates"):
        OrganizeEmailsArgs(operation="flag", email_ids=["one", "one"])
    with pytest.raises(ValueError, match="target_folder"):
        OrganizeEmailsArgs(operation="move", email_ids=["one"])


def test_mail_parser_requires_exactly_one_receipt_per_requested_message():
    operation = EmailOperation(operation="flag", email_ids=["one", "two"])
    payload = {"contract_version": 1, "material_write": True, "receipts": [_receipt("one")]}

    with pytest.raises(MailOperationReceiptParseError, match="missing"):
        parse_mail_operation_receipts(json.dumps(payload), operation)


def test_mail_receipt_script_uses_foundation_json_and_per_message_receipts():
    operation = EmailOperation(operation="move", email_ids=["one"], target_folder="Archive")
    script = MailOperationReceiptScriptGenerator(lambda value: value).organize_emails_receipt_script(operation)

    assert 'use framework "Foundation"' in script
    assert "NSJSONSerialization" in script
    assert "receiptRecords" in script
    assert 'targetMailbox to mailbox "Archive"' in script
