"""Gmail inbox archive and move through Mail's own commands, exercised without touching Mail."""

import json
import shutil
import subprocess

import pytest
from pydantic import ValidationError

from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import EmailOperation
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_operation_contracts import (
    OrganizeEmailsArgs,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.gmail_inbox_ui import (
    apply_gmail_inbox_ui,
    parse_ui_results,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.gmail_inbox_ui_script import (
    ROW_SCAN_LIMIT,
    build_gmail_inbox_ui_script,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mail_app_service import (
    MailAppService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.post_move_verification import (
    classify_receipt,
)

ESCAPE = lambda text: text.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731


async def APPROVE(_summary):
    return True, ""


def _receipt(external_id, rfc, core, *, operation="archive", ui_required=True, siblings=(), target_mailbox="", target_account=""):
    return MaterialOperationReceipt(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, external_id),
        requested_effect={"operation": operation, "target_folder": ""},
        execution_state="attempted",
        observed_postcondition={},
        verification_status="unverified",
        evidence={
            "rfc_message_id": rfc,
            "account": "Work",
            "source_mailbox": "INBOX",
            "target_mailbox": target_mailbox,
            "target_account": target_account,
            "ui_required": ui_required,
            "subject_core": core,
            "sibling_rfc_ids": list(siblings),
        },
        discrepancy={},
    )


def _results(*items, cleanup=""):
    return "RESULT_JSON:" + json.dumps({"results": list(items), "cleanup_notes": cleanup})


class _Runner:
    def __init__(self, output=None, success=True, error=""):
        self.output, self.success, self.error, self.scripts = output, success, error, []

    async def __call__(self, script):
        self.scripts.append(script)
        return self.success, self.output, self.error


@pytest.mark.asyncio
async def test_invoked_conversation_stays_attempted_for_verification_and_records_how_it_was_done():
    runner = _Runner(_results({"core_subject": "Catalog", "status": "invoked", "detail": "", "row": 3}))
    envelope = MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog"),))
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE)
    receipt = result.receipts[0]
    assert receipt.execution_state == "attempted" and receipt.verification_status == "unverified"
    assert receipt.evidence["performed_by"] == "mail_ui_menu" and receipt.evidence["ui_row"] == 3
    assert len(runner.scripts) == 1 and 'set operationName to "archive"' in runner.scripts[0]


@pytest.mark.asyncio
async def test_messages_sharing_one_conversation_run_the_menu_command_once():
    runner = _Runner(_results({"core_subject": "Catalog", "status": "invoked", "detail": "", "row": 3}))
    envelope = MaterialOperationEnvelope(
        receipts=(_receipt("1", "<a@x>", "Catalog", siblings=["<b@x>"]), _receipt("2", "<b@x>", "Catalog", siblings=["<a@x>"]))
    )
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE)
    assert [receipt.execution_state for receipt in result.receipts] == ["attempted", "attempted"]
    assert len(runner.scripts) == 1 and runner.scripts[0].count('"Catalog"') == 1


@pytest.mark.asyncio
async def test_conversation_with_unrequested_inbox_siblings_is_refused_before_any_ui_action():
    runner = _Runner(_results())
    envelope = MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog", siblings=["<other@x>"]),))
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE)
    receipt = result.receipts[0]
    assert receipt.execution_state == "not_started" and receipt.evidence["blocked_before_mutation"] is True
    assert receipt.discrepancy["unrequested_conversation_rfc_message_ids"] == ["<other@x>"]
    assert runner.scripts == []


@pytest.mark.asyncio
async def test_message_without_a_subject_is_refused_because_its_row_cannot_be_identified():
    runner = _Runner(_results())
    result = await apply_gmail_inbox_ui(
        MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", ""),)), "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE
    )
    assert result.receipts[0].execution_state == "not_started" and runner.scripts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected",
    [
        ("row_not_found", "no conversation with this subject"),
        ("archive_unavailable", "Archive command is not available"),
        ("target_menu_item_not_found", "no entry for the destination mailbox"),
        ("accessibility_denied", "Accessibility permission"),
        ("ui_unavailable", "could not be opened"),
    ],
)
async def test_each_ui_failure_is_reported_as_not_started_with_its_reason(status, expected):
    runner = _Runner(_results({"core_subject": "Catalog", "status": status, "detail": "", "row": 0}))
    result = await apply_gmail_inbox_ui(
        MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog"),)), "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE
    )
    receipt = result.receipts[0]
    assert receipt.execution_state == "not_started" and receipt.verification_status == "not_applicable"
    assert expected in receipt.discrepancy["reason"] and receipt.discrepancy["ui_status"] == status


@pytest.mark.asyncio
async def test_unknown_outcome_after_a_script_failure_stays_attempted_so_verification_decides():
    for runner in (_Runner(success=False, error="timed out"), _Runner("no marker here")):
        result = await apply_gmail_inbox_ui(
            MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog"),)), "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE
        )
        receipt = result.receipts[0]
        assert receipt.execution_state == "attempted" and "ui_script_error" in receipt.evidence


@pytest.mark.asyncio
async def test_non_ui_receipts_pass_through_untouched_and_move_targets_the_destination_account_menu():
    plain = _receipt("1", "<a@x>", "", ui_required=False)
    runner = _Runner()
    untouched = await apply_gmail_inbox_ui(MaterialOperationEnvelope(receipts=(plain,)), "archive", escape=ESCAPE, run_script=runner, request_approval=APPROVE)
    assert untouched.receipts[0] == plain and runner.scripts == []

    moving = _receipt("2", "<b@x>", "Invoice", operation="move", target_mailbox="RoyalCare", target_account="Work")
    runner = _Runner(_results({"core_subject": "Invoice", "status": "invoked", "detail": "", "row": 2}))
    await apply_gmail_inbox_ui(MaterialOperationEnvelope(receipts=(moving,)), "move", escape=ESCAPE, run_script=runner, request_approval=APPROVE)
    assert 'set targetName to "RoyalCare"' in runner.scripts[0] and 'set headerAccount to "Work"' in runner.scripts[0]


def test_parse_ui_results_requires_the_marker():
    with pytest.raises(ValueError):
        parse_ui_results("nothing")
    assert parse_ui_results(_results({"core_subject": "A", "status": "invoked"}))["A"]["status"] == "invoked"


def test_archive_is_verified_by_the_message_leaving_the_inbox():
    receipt = _receipt("1", "<a@x>", "Catalog")
    gone = classify_receipt(receipt, {"source_count": 0, "target_count": -2, "error": ""}, polls=1)
    assert gone.execution_state == "succeeded" and gone.verification_status == "verified"
    kept = classify_receipt(receipt, {"source_count": 1, "target_count": -2, "error": ""}, polls=4)
    assert kept.execution_state == "failed" and "still present in source" in kept.discrepancy["reason"]


def test_organize_contract_accepts_archive_without_a_target_and_rejects_a_target():
    assert OrganizeEmailsArgs(operation="archive", email_ids=["1"]).to_email_operation().operation == "archive"
    with pytest.raises(ValidationError, match="only supported for move"):
        OrganizeEmailsArgs(operation="archive", email_ids=["1"], target_folder="Work / Archive")


def test_receipt_script_defers_gmail_inbox_messages_to_the_ui_and_marks_them():
    service = MailAppService()
    archive = service.organize_emails_receipt_script(EmailOperation(operation="archive", email_ids=["1"]))
    move = service.organize_emails_receipt_script(
        EmailOperation(operation="move", email_ids=["1"], target_folder="Work / RoyalCare")
    )
    for script in (archive, move):
        assert 'set labelInbox to (sourceMailboxName is not "INBOX")' in script
        assert "ui_required:uiRequired, subject_core:coreText, sibling_rfc_ids:siblingIds" in script
        assert "if labelInbox and true then" in script
        assert "|account|:sourceAccountName" in script
        assert "set theMessage to my findInboxMessage(messageId)" in script and "on filterByMessageToken(theMailbox, token)" in script
    assert "if not labelInbox then move theMessage to targetMailbox" in move
    assert 'my findMailbox(targetAccountName, candidateName as text)' in archive and "if not labelInbox then" in archive
    delete = service.organize_emails_receipt_script(EmailOperation(operation="delete", email_ids=["1"]))
    assert "if labelInbox and false then" in delete and "delete theMessage" in delete


def test_ui_script_is_bounded_and_always_cleans_up():
    script = build_gmail_inbox_ui_script(
        escape=ESCAPE, account_name="Work", operation="move", target_name="Royal \"Care\"", target_account_name="", core_subjects=["A", "B"]
    )
    assert f"set rowScanLimit to {ROW_SCAN_LIMIT}" in script
    assert 'set targetName to "Royal \\"Care\\""' in script and 'set headerAccount to "Work"' in script
    assert "set coreSubjects to {\"A\", \"B\"}" in script and "set dryRun to false" in script
    assert "repeat with scanAttempt from 1 to 2" in script
    assert "close (first window whose id is viewerWindowId)" in script and "set frontmost of process previousApp to true" in script
    with pytest.raises(ValueError):
        build_gmail_inbox_ui_script(escape=ESCAPE, account_name="W", operation="delete", target_name="", target_account_name="", core_subjects=["A"])


@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is only available on macOS")
def test_receipt_and_ui_scripts_compile_without_executing(tmp_path):
    service = MailAppService()
    scripts = {
        "archive": service.organize_emails_receipt_script(EmailOperation(operation="archive", email_ids=["1"])),
        "move": service.organize_emails_receipt_script(EmailOperation(operation="move", email_ids=["1"], target_folder="Work / RoyalCare")),
        "ui_archive": build_gmail_inbox_ui_script(escape=ESCAPE, account_name="Work", operation="archive", target_name="", target_account_name="", core_subjects=["A"]),
        "ui_move": build_gmail_inbox_ui_script(escape=ESCAPE, account_name="Work", operation="move", target_name="X", target_account_name="Work", core_subjects=["A"], dry_run=True),
    }
    for name, script in scripts.items():
        source = tmp_path / f"{name}.applescript"
        source.write_text(script)
        done = subprocess.run(["osacompile", "-o", str(tmp_path / f"{name}.scpt"), str(source)], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"{name}: {done.stderr}"


def test_move_ignored_because_the_label_was_already_present_is_reopened_as_an_archive():
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.gmail_inbox_ui import (
        prepare_archive_fallback,
    )
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.post_move_verification import (
        GMAIL_LABEL_REASON,
    )

    base = _receipt("1", "<a@x>", "Catalog", operation="move", target_mailbox="RoyalCare", target_account="Work")
    evidence = dict(base.evidence, performed_by="mail_ui_menu")
    stuck = MaterialOperationReceipt(
        entity=base.entity,
        requested_effect=base.requested_effect,
        execution_state="succeeded",
        observed_postcondition={"source_count": 1, "target_count": 1},
        verification_status="unverified",
        evidence=evidence,
        discrepancy={"reason": GMAIL_LABEL_REASON},
    )
    verified = MaterialOperationReceipt(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, "2"),
        requested_effect=base.requested_effect,
        execution_state="succeeded",
        observed_postcondition={"source_absent": True},
        verification_status="verified",
        evidence=evidence,
        discrepancy={},
    )
    reopened, changed = prepare_archive_fallback(MaterialOperationEnvelope(receipts=(stuck, verified)))
    assert changed is True
    assert reopened.receipts[0].execution_state == "attempted" and reopened.receipts[0].evidence["archive_fallback"] is True
    assert reopened.receipts[1] == verified
    again, changed_again = prepare_archive_fallback(reopened)
    assert changed_again is False and again.receipts[0] == reopened.receipts[0]
    settled = classify_receipt(reopened.receipts[0], {"source_count": 0, "target_count": 1, "error": ""}, polls=1)
    assert settled.execution_state == "succeeded" and settled.verification_status == "verified"
