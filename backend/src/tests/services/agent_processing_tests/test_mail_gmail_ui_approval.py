from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.shared.agent_runtime_context import set_current_agent_context
from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app import gmail_ui_approval
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.gmail_inbox_ui import (
    NO_APPROVAL_CHANNEL_REASON,
    apply_gmail_inbox_ui,
)

ESCAPE = lambda text: text.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731


def _receipt(external_id: str, rfc: str, core: str, *, siblings: tuple[str, ...] = ()) -> MaterialOperationReceipt:
    return MaterialOperationReceipt(
        entity=LedgerEntityReference("email", "mail_app", {"mailbox": "inbox"}, external_id),
        requested_effect={"operation": "archive", "target_folder": ""},
        execution_state="attempted",
        observed_postcondition={},
        verification_status="unverified",
        evidence={
            "rfc_message_id": rfc,
            "account": "Work",
            "source_mailbox": "INBOX",
            "target_mailbox": "",
            "target_account": "",
            "ui_required": True,
            "subject_core": core,
            "sibling_rfc_ids": list(siblings),
        },
        discrepancy={},
    )


def _invoked_output(core: str) -> str:
    return "RESULT_JSON:" + json.dumps({"results": [{"core_subject": core, "status": "invoked", "detail": "", "row": 2}], "cleanup_notes": ""})


class _Recorder:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    async def run(self, script: str):
        self.scripts.append(script)
        return True, _invoked_output("Catalog"), ""


@pytest.mark.asyncio
async def test_no_approval_channel_leaves_the_message_untouched_and_never_runs_the_menus():
    recorder = _Recorder()
    envelope = MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog"),))
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=recorder.run)
    receipt = result.receipts[0]
    assert recorder.scripts == []
    assert receipt.execution_state == "not_started"
    assert receipt.discrepancy["reason"] == NO_APPROVAL_CHANNEL_REASON
    assert receipt.evidence["blocked_before_mutation"] is True


@pytest.mark.asyncio
async def test_denied_approval_blocks_every_runnable_receipt_with_the_denial_reason():
    recorder = _Recorder()

    async def deny(_summary):
        return False, "The user declined."

    envelope = MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog"), _receipt("2", "<b@x>", "Quarterly")))
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=recorder.run, request_approval=deny)
    assert recorder.scripts == []
    assert [receipt.execution_state for receipt in result.receipts] == ["not_started", "not_started"]
    assert all(receipt.discrepancy["reason"] == "The user declined." for receipt in result.receipts)


@pytest.mark.asyncio
async def test_a_failed_approval_request_is_not_an_approval():
    recorder = _Recorder()

    async def explode(_summary):
        raise RuntimeError("websocket closed")

    envelope = MaterialOperationEnvelope(receipts=(_receipt("1", "<a@x>", "Catalog"),))
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=recorder.run, request_approval=explode)
    assert recorder.scripts == []
    assert result.receipts[0].execution_state == "not_started"
    assert "websocket closed" in result.receipts[0].discrepancy["reason"]


@pytest.mark.asyncio
async def test_approval_is_asked_once_with_a_summary_of_what_will_run_and_receipts_refused_earlier_are_not_counted():
    recorder = _Recorder()
    asked: list[dict] = []

    async def approve(summary):
        asked.append(summary)
        return True, ""

    envelope = MaterialOperationEnvelope(
        receipts=(
            _receipt("1", "<a@x>", "Catalog"),
            _receipt("2", "<b@x>", "Shared thread", siblings=("<unrequested@x>",)),
        )
    )
    result = await apply_gmail_inbox_ui(envelope, "archive", escape=ESCAPE, run_script=recorder.run, request_approval=approve)
    assert len(asked) == 1
    assert asked[0]["message_count"] == 1
    assert asked[0]["subjects"] == ["Catalog"]
    assert asked[0]["accounts"] == ["Work"]
    assert len(recorder.scripts) == 1
    assert result.receipts[0].execution_state == "attempted"
    assert result.receipts[1].execution_state == "not_started"


@pytest.mark.asyncio
async def test_nothing_is_asked_when_no_receipt_needs_the_menus():
    plain = _receipt("1", "<a@x>", "Catalog")
    plain = MaterialOperationReceipt(
        entity=plain.entity,
        requested_effect=plain.requested_effect,
        execution_state="attempted",
        observed_postcondition={},
        verification_status="unverified",
        evidence={**plain.evidence, "ui_required": False},
        discrepancy={},
    )

    async def must_not_ask(_summary):
        raise AssertionError("approval must not be requested")

    result = await apply_gmail_inbox_ui(
        MaterialOperationEnvelope(receipts=(plain,)), "archive", escape=ESCAPE, run_script=_Recorder().run, request_approval=must_not_ask
    )
    assert result.receipts[0].execution_state == "attempted"


@pytest.mark.asyncio
async def test_once_per_call_reuses_the_first_answer_for_the_archive_fallback():
    calls: list[dict] = []

    class _Service:
        async def request_approval_with_outcome(self, command, context):
            calls.append({"command": command, "context": context})
            return SimpleNamespace(approved=True, status="approved", reason="")

    set_current_agent_context({"agent_task_id": "task-1"})
    request = gmail_ui_approval.once_per_call(_Service())
    summary = {"operation": "move", "message_count": 2, "accounts": ["Work"], "subjects": ["Catalog", "Quarterly"], "target_mailboxes": ["Clients"]}
    assert await request(summary) == (True, "")
    assert await request({**summary, "operation": "archive"}) == (True, "")
    assert len(calls) == 1
    context = calls[0]["context"]
    assert context["require_explicit_approval"] is True
    assert context["execution_type"] == "applescript"
    assert context["agent_task_id"] == "task-1"
    assert "2 Gmail messages" in calls[0]["command"]
    assert "Clients" in context["description"] and "20 seconds" in context["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "needle"),
    [("user_denied", "declined"), ("approval_timed_out", "did not answer"), ("approval_unavailable", "no interactive")],
)
async def test_each_non_approval_outcome_explains_itself_to_the_agent(status, needle):
    class _Service:
        async def request_approval_with_outcome(self, command, context):
            return SimpleNamespace(approved=False, status=status, reason="no interactive channel")

    set_current_agent_context({"agent_task_id": "task-1"})
    approved, reason = await gmail_ui_approval.request_mail_ui_approval(
        _Service(), {"operation": "archive", "message_count": 1, "accounts": ["Work"], "subjects": ["Catalog"], "target_mailboxes": []}
    )
    assert approved is False
    assert needle in reason
    assert "nothing was changed" in reason or "no interactive" in reason


@pytest.mark.asyncio
async def test_missing_service_or_task_id_fails_closed():
    set_current_agent_context({})
    summary = {"operation": "archive", "message_count": 1}
    assert await gmail_ui_approval.request_mail_ui_approval(None, summary) == (False, NO_APPROVAL_CHANNEL_REASON)
    assert await gmail_ui_approval.request_mail_ui_approval(object(), summary) == (False, NO_APPROVAL_CHANNEL_REASON)


def test_email_service_has_an_approval_service_only_when_a_websocket_channel_exists():
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import EmailClientService

    assert EmailClientService()._approval_service_for_mail_ui() is None
    with_channel = EmailClientService(websocket_manager=SimpleNamespace(broadcast=lambda event: None))
    first = with_channel._approval_service_for_mail_ui()
    assert first is not None
    assert with_channel._approval_service_for_mail_ui() is first
