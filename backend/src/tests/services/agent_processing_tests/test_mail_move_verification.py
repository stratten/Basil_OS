"""Mail move and delete verification by RFC message id, mailbox alias resolution, and the organize flow, all without live Mail."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailOperation,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_organization import (
    EmailOrganizationMixin,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mailbox_resolution import (
    AccountMailboxResolver,
    MailboxResolutionError,
    resolve_account_mailbox_name,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.operation_receipt_scripts import (
    MailOperationReceiptScriptGenerator,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.post_move_verification import (
    SETTLE_DELAYS_SECONDS,
    parse_location_counts,
    settle_attempted_receipts,
)

RFC_ID = "<abc123@example.com>"


def _attempted(operation: str, external_id: str = "42", rfc: str = RFC_ID) -> MaterialOperationReceipt:
    return MaterialOperationReceipt(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, external_id),
        requested_effect={"operation": operation, "target_folder": "Archive" if operation == "move" else ""},
        execution_state="attempted",
        observed_postcondition={},
        verification_status="unverified",
        evidence={
            "rfc_message_id": rfc,
            "account": "Work",
            "source_mailbox": "INBOX",
            "target_mailbox": "Archive" if operation == "move" else "",
        },
        discrepancy={},
    )


def _envelope(*receipts: MaterialOperationReceipt) -> MaterialOperationEnvelope:
    return MaterialOperationEnvelope(receipts=tuple(receipts))


def _output(*rows: tuple[int, int]) -> str:
    checks = [
        {"check_index": index, "source_count": source, "target_count": target, "lookup_error": ""}
        for index, (source, target) in enumerate(rows)
    ]
    return "RESULT_JSON:" + json.dumps({"checks": checks})


class _Runner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.scripts = []

    async def __call__(self, script):
        self.scripts.append(script)
        item = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(item, Exception):
            raise item
        return item


def _ok(*rows):
    return (True, _output(*rows), "")


async def _settle(envelope, runner):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    result = await settle_attempted_receipts(
        envelope,
        build_script=lambda checks: json.dumps(checks),
        run_script=runner,
        sleep=fake_sleep,
    )
    return result, slept


@pytest.mark.asyncio
async def test_move_verified_once_message_settles_in_target():
    runner = _Runner([_ok((1, 0)), _ok((0, 1))])
    result, slept = await _settle(_envelope(_attempted("move")), runner)
    receipt = result.receipts[0]
    assert (receipt.execution_state, receipt.verification_status) == ("succeeded", "verified")
    assert receipt.observed_postcondition["destination_mailbox"] == "Archive"
    assert receipt.evidence["verification_polls"] == 2
    assert slept == [3.0]
    assert len(runner.scripts) == 2


@pytest.mark.asyncio
async def test_move_present_in_both_after_window_is_unverified_not_verified():
    runner = _Runner([_ok((1, 1))])
    result, slept = await _settle(_envelope(_attempted("move")), runner)
    receipt = result.receipts[0]
    assert (receipt.execution_state, receipt.verification_status) == ("succeeded", "unverified")
    assert receipt.discrepancy["reason"].startswith("still present in source after settle window")
    assert receipt.discrepancy["source_count"] == 1 and receipt.discrepancy["target_count"] == 1
    assert slept == [3.0, 3.0, 6.0]
    assert len(runner.scripts) == len(SETTLE_DELAYS_SECONDS)


@pytest.mark.asyncio
async def test_move_missing_from_both_is_failed():
    result, _ = await _settle(_envelope(_attempted("move")), _Runner([_ok((0, 0))]))
    receipt = result.receipts[0]
    assert (receipt.execution_state, receipt.verification_status) == ("failed", "failed")
    assert "neither" in receipt.discrepancy["reason"]


@pytest.mark.asyncio
async def test_move_still_in_source_only_is_failed():
    result, _ = await _settle(_envelope(_attempted("move")), _Runner([_ok((1, 0))]))
    receipt = result.receipts[0]
    assert (receipt.execution_state, receipt.verification_status) == ("failed", "failed")
    assert "absent from target" in receipt.discrepancy["reason"]


@pytest.mark.asyncio
async def test_delete_verified_when_absent_from_source():
    result, slept = await _settle(_envelope(_attempted("delete")), _Runner([_ok((0, -2))]))
    receipt = result.receipts[0]
    assert (receipt.execution_state, receipt.verification_status) == ("succeeded", "verified")
    assert receipt.observed_postcondition["source_absent"] is True
    assert slept == []


@pytest.mark.asyncio
async def test_delete_still_present_fails_after_window():
    result, _ = await _settle(_envelope(_attempted("delete")), _Runner([_ok((1, -2))]))
    assert result.receipts[0].verification_status == "failed"


@pytest.mark.asyncio
async def test_verification_errors_leave_receipt_unverified_and_attempted():
    runner = _Runner([(False, None, "Mail got an error")])
    result, _ = await _settle(_envelope(_attempted("move")), runner)
    receipt = result.receipts[0]
    assert (receipt.execution_state, receipt.verification_status) == ("attempted", "unverified")
    assert "Mail got an error" in receipt.discrepancy["reason"]


@pytest.mark.asyncio
async def test_poll_exception_then_success_still_verifies():
    runner = _Runner([RuntimeError("osascript timed out"), _ok((0, 1))])
    result, _ = await _settle(_envelope(_attempted("move")), runner)
    assert result.receipts[0].verification_status == "verified"


@pytest.mark.asyncio
async def test_only_unresolved_receipts_are_repolled_and_untouched_receipts_pass_through():
    flagged = MaterialOperationReceipt(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, "7"),
        requested_effect={"operation": "flag"},
        execution_state="succeeded",
        observed_postcondition={"flagged_status": True},
        verification_status="verified",
        evidence={"mail_readback": {"flagged_status": True}},
    )
    envelope = _envelope(_attempted("move", "1", "<a@x>"), _attempted("move", "2", "<b@x>"), flagged)
    runner = _Runner([_ok((0, 1), (1, 0)), _ok((0, 1))])
    result, _ = await _settle(envelope, runner)
    assert [r.verification_status for r in result.receipts] == ["verified", "verified", "verified"]
    assert "<b@x>" in runner.scripts[1] and "<a@x>" not in runner.scripts[1]


@pytest.mark.asyncio
async def test_no_attempted_receipts_never_runs_a_script():
    runner = _Runner([_ok((0, 1))])
    envelope = _envelope(_attempted("move").__class__(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, "9"),
        requested_effect={"operation": "move"},
        execution_state="failed",
        observed_postcondition={},
        verification_status="failed",
        evidence={"mail_error_number": -1728},
    ))
    result, _ = await _settle(envelope, runner)
    assert result is envelope and runner.scripts == []


def test_parse_location_counts_rejects_output_without_result_marker():
    with pytest.raises(ValueError):
        parse_location_counts("no marker here")
    assert parse_location_counts(_output((0, 2)))[0]["target_count"] == 2


def test_move_script_captures_identity_before_mutating_and_reports_attempted():
    operation = EmailOperation(operation="move", email_ids=["42"], target_folder="Archive")
    script = MailOperationReceiptScriptGenerator(lambda value: value).organize_emails_receipt_script(operation)
    assert script.index("set rfcMessageId to message id of theMessage") < script.index("move theMessage to targetMailbox")
    assert 'set targetAccountName to ""' in script
    assert "if targetAccountName is \"\" then set targetAccountName to sourceAccountName" in script
    assert 'repeat with candidateName in {"Archive"}' in script
    assert 'execution_state:"attempted"' in script
    assert "source_absent" not in script


def test_delete_script_captures_identity_and_flag_script_keeps_inline_readback():
    generator = MailOperationReceiptScriptGenerator(lambda value: value)
    delete_script = generator.organize_emails_receipt_script(EmailOperation(operation="delete", email_ids=["42"]))
    assert delete_script.index("set rfcMessageId") < delete_script.index("delete theMessage")
    assert 'execution_state:"attempted"' in delete_script
    flag_script = generator.organize_emails_receipt_script(EmailOperation(operation="flag", email_ids=["42"]))
    assert 'execution_state:"succeeded"' in flag_script and "rfcMessageId" not in flag_script


def test_verify_script_escapes_values_and_indexes_checks():
    generator = MailOperationReceiptScriptGenerator(lambda value: value.replace('"', '\\"'))
    script = generator.verify_locations_script(
        [
            {"rfc_message_id": '<a"b@x>', "account": "Work", "source_mailbox": "INBOX", "target_mailbox": "Archive"},
            {"rfc_message_id": "<c@x>", "account": "", "source_mailbox": "INBOX", "target_mailbox": ""},
        ]
    )
    assert 'rfcId:"<a\\"b@x>"' in script
    assert "checkIndex:0" in script and "checkIndex:1" in script
    assert "whose message id is rfcId" in script


def test_resolve_mailbox_name_exact_alias_and_error():
    names = ["INBOX", "Sent Items", "Deleted Items", "Drafts"]
    assert resolve_account_mailbox_name("Work", "sent items", names) == "Sent Items"
    assert resolve_account_mailbox_name("Work", "Sent Mail", names) == "Sent Items"
    assert resolve_account_mailbox_name("Work", "Sent", names) == "Sent Items"
    assert resolve_account_mailbox_name("Work", "Trash", names) == "Deleted Items"
    assert resolve_account_mailbox_name("Work", "Draft", names) == "Drafts"
    assert resolve_account_mailbox_name("Work", "Drafts", ["Sent Mail"] + ["Drafts"]) == "Drafts"
    with pytest.raises(MailboxResolutionError) as excinfo:
        resolve_account_mailbox_name("Work", "Receipts", names)
    assert '"Sent Items"' in str(excinfo.value) and "Receipts" in str(excinfo.value)


@pytest.mark.asyncio
async def test_resolver_caches_listing_for_120_seconds_and_passes_through_plain_tokens():
    calls = []
    now = [1000.0]

    async def list_folders():
        calls.append(1)
        return ["Inbox", "Work / INBOX", "Work / Sent Items"]

    resolver = AccountMailboxResolver(list_folders, clock=lambda: now[0])
    assert await resolver.resolve("Work / Sent Mail") == "Work / Sent Items"
    assert await resolver.resolve("Work / Sent") == "Work / Sent Items"
    assert len(calls) == 1
    now[0] += 121
    await resolver.resolve("Work / INBOX")
    assert len(calls) == 2
    assert await resolver.resolve("inbox") == "inbox"
    assert await resolver.resolve("Unknown / Sent Mail") == "Unknown / Sent Mail"
    with pytest.raises(MailboxResolutionError, match="Available mailboxes"):
        await resolver.resolve("Work / Receipts")


@pytest.mark.asyncio
async def test_resolver_falls_back_to_unchanged_token_when_listing_fails():
    async def broken():
        raise RuntimeError("Mail unavailable")

    assert await AccountMailboxResolver(broken).resolve("Work / Sent Mail") == "Work / Sent Mail"


class _Service(EmailOrganizationMixin):
    def __init__(self, outputs):
        self.mail_scripts = []
        self._outputs = list(outputs)
        generator = MailOperationReceiptScriptGenerator(lambda value: value)
        self.applescript_service = SimpleNamespace(
            mail_app_service=SimpleNamespace(
                organize_emails_receipt_script=generator.organize_emails_receipt_script,
                verify_locations_script=generator.verify_locations_script,
            ),
            execute_applescript=self._execute,
        )

    async def _execute(self, script, description):
        self.mail_scripts.append(description)
        data = self._outputs.pop(0) if len(self._outputs) > 1 else self._outputs[0]
        return SimpleNamespace(success=True, data=data, error=None)


@pytest.mark.asyncio
async def test_organize_flow_runs_mutation_then_verifies_by_rfc_id(monkeypatch):
    attempted = _attempted("move")
    mutation_output = "RESULT_JSON:" + json.dumps(_envelope(attempted).to_dict())
    service = _Service([mutation_output, _output((0, 1))])
    operation = EmailOperation(operation="move", email_ids=["42"], target_folder="Archive")
    result = await service._organize_emails_via_applescript(operation, SimpleNamespace(name="Mail"))
    receipt = result["material_operation"]["receipts"][0]
    assert receipt["verification_status"] == "verified"
    assert result["outcome_verification_status"] == "verified"
    assert service.mail_scripts == [
        "organize emails via Mail",
        "verify Mail message locations by RFC message id",
    ]


@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is only available on macOS")
@pytest.mark.parametrize("operation", ["move", "delete", "flag", "mark_read"])
def test_generated_mail_scripts_compile_without_executing(tmp_path, operation):
    """AppleScript record literals cannot span lines, so every generated script must at least compile."""
    generator = MailOperationReceiptScriptGenerator(lambda value: value.replace("\\", "\\\\").replace('"', '\\"'))
    target = "Archive" if operation == "move" else None
    scripts = {
        "receipt": generator.organize_emails_receipt_script(
            EmailOperation(operation=operation, email_ids=["42", "43"], target_folder=target)
        ),
        "verify": generator.verify_locations_script(
            [{"rfc_message_id": "<a@x>", "account": "Work", "source_mailbox": "INBOX", "target_mailbox": "Archive"}]
        ),
    }
    for name, script in scripts.items():
        source = tmp_path / f"{name}.applescript"
        source.write_text(script)
        completed = subprocess.run(
            ["osacompile", "-o", str(tmp_path / f"{name}.scpt"), str(source)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
