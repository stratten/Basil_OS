"""Mail receipt handling against the shapes AppleScript really produces, without touching Mail."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailOperation,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_organization import (
    EmailOrganizationMixin,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mailbox_resolution import (
    mailbox_name_candidates,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.operation_receipt_parser import (
    MailOperationReceiptParseError,
    parse_mail_operation_receipts,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.operation_receipt_scripts import (
    TARGET_SCAN_LIMIT,
    MailOperationReceiptScriptGenerator,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.post_move_verification import (
    classify_receipt,
)
from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationReceipt,
)


def _applescript_shaped_receipt(external_id: str, execution_state: str = "attempted") -> dict:
    """The JSON Foundation writes for the script's records: every empty AppleScript record becomes an empty list."""
    return {
        "entity": {
            "entity_type": "email",
            "source_system": "mail_app",
            "source_scope": {"mailbox": "inbox"},
            "external_id": external_id,
        },
        "requested_effect": {"operation": "move", "target_folder": "Work / Archive"},
        "execution_state": execution_state,
        "observed_postcondition": [],
        "verification_status": "unverified" if execution_state == "attempted" else "failed",
        "evidence": {"rfc_message_id": "<a@x>", "account": "Work", "source_mailbox": "INBOX", "target_mailbox": "Archive"}
        if execution_state == "attempted"
        else {"mail_error_number": -1728},
        "discrepancy": [] if execution_state == "attempted" else {"mail_error": "Can't get mailbox"},
    }


def _output(*receipts: dict) -> str:
    return "RESULT_JSON:" + json.dumps({"contract_version": 1, "material_write": True, "receipts": list(receipts)})


def test_parser_accepts_empty_records_serialized_as_lists():
    operation = EmailOperation(operation="move", email_ids=["1", "2"], target_folder="Work / Archive")
    envelope = parse_mail_operation_receipts(
        _output(_applescript_shaped_receipt("1"), _applescript_shaped_receipt("2", "failed")),
        operation,
    )
    first, second = envelope.receipts
    assert first.observed_postcondition == {} and first.discrepancy == {}
    assert second.discrepancy == {"mail_error": "Can't get mailbox"}


def test_parser_still_rejects_a_non_empty_list_for_an_object_field():
    receipt = _applescript_shaped_receipt("1")
    receipt["observed_postcondition"] = ["not", "an", "object"]
    with pytest.raises(MailOperationReceiptParseError, match="observed_postcondition must be an object"):
        parse_mail_operation_receipts(_output(receipt), EmailOperation(operation="move", email_ids=["1"], target_folder="Work / Archive"))


@pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript is only available on macOS")
def test_real_applescript_serialization_of_empty_records_parses(tmp_path):
    """Run a Mail-free script that builds the same empty records as the receipt script and parse its real output."""
    source = tmp_path / "shape.applescript"
    source.write_text(
        'use framework "Foundation"\nuse scripting additions\n'
        "on jsonTextFor(value)\n"
        "    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)\n"
        "    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text\n"
        "end jsonTextFor\n"
        'set receiptRecord to {entity:{entity_type:"email", source_system:"mail_app", source_scope:{mailbox:"inbox"}, external_id:"7"}, '
        'requested_effect:{operation:"move", target_folder:"Archive"}, execution_state:"attempted", observed_postcondition:{}, '
        'verification_status:"unverified", evidence:{rfc_message_id:"<a@x>"}, discrepancy:{}}\n'
        'return "RESULT_JSON:" & jsonTextFor({contract_version:1, material_write:true, receipts:{receiptRecord}})\n'
    )
    completed = subprocess.run(["osascript", str(source)], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert '"observed_postcondition":[]' in completed.stdout
    envelope = parse_mail_operation_receipts(
        completed.stdout, EmailOperation(operation="move", email_ids=["7"], target_folder="Archive")
    )
    assert envelope.receipts[0].execution_state == "attempted"


def test_move_script_resolves_account_qualified_target_by_name_filter():
    generator = MailOperationReceiptScriptGenerator(lambda value: value)
    script = generator.organize_emails_receipt_script(
        EmailOperation(operation="move", email_ids=["42"], target_folder="Work / Archive")
    )
    assert 'set targetAccountName to "Work"' in script
    assert 'repeat with candidateName in {"Archive"}' in script
    assert "every mailbox of account accountName whose name is mailboxName" in script
    assert 'mailbox "Work / Archive"' not in script
    assert "target_account:targetAccountName" in script
    assert "if targetMailbox is missing value then error targetLookupError number -1728" in script


def test_move_script_offers_conventional_aliases_for_sent_trash_and_drafts():
    assert mailbox_name_candidates("Archive") == ["Archive"]
    assert mailbox_name_candidates("Trash") == ["Trash", "bin", "deleted items", "deleted messages"]
    script = MailOperationReceiptScriptGenerator(lambda value: value).organize_emails_receipt_script(
        EmailOperation(operation="move", email_ids=["42"], target_folder="Work / Trash")
    )
    assert '{"Trash", "bin", "deleted items", "deleted messages"}' in script


def test_verify_script_resolves_by_name_filter_and_bounds_the_target_scan():
    script = MailOperationReceiptScriptGenerator(lambda value: value).verify_locations_script(
        [{"rfc_message_id": "<a@x>", "account": "Work", "target_account": "Home", "source_mailbox": "INBOX", "target_mailbox": "All Mail"}]
    )
    assert 'targetAccountName:"Home"' in script
    assert "every mailbox of account accountName whose name is mailboxName" in script
    assert f"> scanLimit then return -3" in script
    assert f"{TARGET_SCAN_LIMIT})" in script


def _attempted_move() -> MaterialOperationReceipt:
    return MaterialOperationReceipt(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, "1"),
        requested_effect={"operation": "move", "target_folder": "Work / All Mail"},
        execution_state="attempted",
        observed_postcondition={},
        verification_status="unverified",
        evidence={"rfc_message_id": "<a@x>", "account": "Work", "source_mailbox": "INBOX", "target_mailbox": "All Mail"},
        discrepancy={},
    )


def test_move_into_a_mailbox_too_large_to_scan_is_verified_by_source_absence():
    final = classify_receipt(_attempted_move(), {"source_count": 0, "target_count": -3, "error": ""}, polls=1)
    assert (final.execution_state, final.verification_status) == ("succeeded", "verified")
    assert final.observed_postcondition["target_scan_skipped"] is True
    assert "target_count" not in final.observed_postcondition


def test_move_still_in_source_with_unscannable_target_stays_unverified():
    final = classify_receipt(_attempted_move(), {"source_count": 1, "target_count": -3, "error": ""}, polls=4)
    assert (final.execution_state, final.verification_status) == ("attempted", "unverified")


class _Service(EmailOrganizationMixin):
    def __init__(self, data):
        generator = MailOperationReceiptScriptGenerator(lambda value: value)
        self.applescript_service = SimpleNamespace(
            mail_app_service=SimpleNamespace(
                organize_emails_receipt_script=generator.organize_emails_receipt_script,
                verify_locations_script=generator.verify_locations_script,
            ),
            execute_applescript=self._execute,
        )
        self._data = data

    async def _execute(self, script, description):
        return SimpleNamespace(success=True, data=self._data, error=None)


@pytest.mark.asyncio
async def test_unreadable_receipt_after_a_mutation_is_attempted_unverified_not_failed():
    service = _Service("RESULT_JSON:not json")
    operation = EmailOperation(operation="move", email_ids=["42"], target_folder="Work / Archive")
    result = await service._organize_emails_via_applescript(operation, SimpleNamespace(name="Mail"))
    receipt = result["material_operation"]["receipts"][0]
    assert (receipt["execution_state"], receipt["verification_status"]) == ("attempted", "unverified")
    assert "could not be read" in receipt["discrepancy"]["reason"]


@pytest.mark.asyncio
async def test_failed_script_receipt_surfaces_mail_error_text():
    failed = _applescript_shaped_receipt("42", "failed")
    service = _Service(_output(failed))
    operation = EmailOperation(operation="move", email_ids=["42"], target_folder="Work / Nope")
    result = await service._organize_emails_via_applescript(operation, SimpleNamespace(name="Mail"))
    receipt = result["material_operation"]["receipts"][0]
    assert receipt["execution_state"] == "failed"
    assert receipt["discrepancy"] == {"mail_error": "Can't get mailbox"}


def test_move_and_delete_scripts_report_the_account_inbox_as_the_source_mailbox():
    generator = MailOperationReceiptScriptGenerator(lambda value: value)
    for operation, target in (("move", "Work / All Mail"), ("delete", None)):
        script = generator.organize_emails_receipt_script(
            EmailOperation(operation=operation, email_ids=["42"], target_folder=target)
        )
        assert 'set sourceMailboxName to name of (my findMailbox(sourceAccountName, "INBOX"))' in script


def test_move_present_in_source_and_target_explains_gmail_label_behavior():
    final = classify_receipt(_attempted_move(), {"source_count": 1, "target_count": 1, "error": ""}, polls=4)
    assert (final.execution_state, final.verification_status) == ("succeeded", "unverified")
    assert "label" in final.discrepancy["reason"] and "has not left the inbox" in final.discrepancy["reason"]


def test_organize_emails_slim_doc_lists_only_supported_operations_and_gmail_archive_rule():
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_operation_contracts import (
        SUPPORTED_EMAIL_OPERATIONS,
    )
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_service_capabilities import (
        _SLIM_DOCS_BY_METHOD,
    )

    doc = _SLIM_DOCS_BY_METHOD["organize_emails"]
    assert all(operation in doc for operation in SUPPORTED_EMAIL_OPERATIONS)
    assert "unflag" not in doc and "mark_unread" not in doc
    assert "archive" in doc and "Gmail" in doc and "Accessibility" in doc
    assert "All Mail" not in doc
