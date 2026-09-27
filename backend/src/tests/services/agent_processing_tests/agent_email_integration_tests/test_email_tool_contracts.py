import asyncio
import os
import subprocess
from datetime import datetime

import pytest

from pydantic import ValidationError

from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import (
    AppleScriptAutomationService,
    AppleScriptResult,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_composition import (
    EmailCompositionMixin,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (
    EmailClientService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailRequest,
    EmailClient,
    EmailOperation,
    EmailSearchCriteria,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_tool_contracts import (
    CreateNewEmailDraftArgs,
    CreateReplyEmailDraftArgs,
    ExpandEmailDetailsArgs,
    GetEmailMetadataArgs,
    GetEmailsArgs,
    normalize_email_search_criteria,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mail_app_service import (
    MailAppService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook.outlook_service import (
    OutlookAppleScriptService,
)
from api.services.agent_processing.service_capabilities.service_execution_engine import ServiceExecutionEngine


def test_reply_email_id_integer_normalizes_to_string():
    args = CreateReplyEmailDraftArgs(
        reference_email_id=167029,
        reply_body="Thanks for the update.",
    )

    assert args.reference_email_id == "167029"


def test_new_draft_accepts_unambiguous_recipient_aliases():
    args = CreateNewEmailDraftArgs.model_validate({
        "to": ["Scott Rumberg <srumberg@CloudFirst.Host>"],
        "subject": "CloudFirst follow-up",
        "body": "Thanks, Scott.",
    })

    assert args.recipient == "srumberg@CloudFirst.Host"


def test_new_draft_rejects_multiple_primary_recipients_from_alias():
    with pytest.raises(ValidationError):
        CreateNewEmailDraftArgs.model_validate({
            "to": ["a@example.com", "b@example.com"],
            "subject": "Ambiguous primary recipient",
            "body": "Hello.",
        })


def test_new_draft_rejects_display_name_only_recipient():
    with pytest.raises(ValidationError):
        CreateNewEmailDraftArgs(
            recipient="Joel Bernath",
            subject="CloudFirst follow-up",
            body="Thanks, Scott.",
        )


def test_reply_draft_requires_reference_email_id():
    with pytest.raises(ValidationError):
        CreateReplyEmailDraftArgs(reply_body="Thanks for the update.")


def test_email_search_criteria_aliases_normalize_to_datetimes():
    criteria = normalize_email_search_criteria({
        "from": "Scott Rumberg",
        "subject": "invoice",
        "received_after": "2026-04-30T00:00:00",
        "date_range": {
            "end": "2026-05-01T23:59:59",
        },
    })

    assert criteria.sender == "Scott Rumberg"
    assert criteria.subject_contains == "invoice"
    assert criteria.date_from == datetime(2026, 4, 30, 0, 0, 0)
    assert criteria.date_to == datetime(2026, 5, 1, 23, 59, 59)


def test_get_emails_args_accepts_criteria_alias():
    args = GetEmailsArgs.model_validate({
        "folder": "inbox",
        "limit": 25,
        "criteria": {
            "date_after": "2026-04-30T00:00:00",
        },
    })

    assert args.search_criteria is not None
    assert args.search_criteria.to_email_search_criteria().date_from == datetime(2026, 4, 30, 0, 0, 0)


def test_metadata_and_expansion_contracts_bound_email_body_work():
    metadata_args = GetEmailMetadataArgs.model_validate({
        "folder": "inbox",
        "limit": 75,
        "criteria": {"received_after": "2026-04-30T00:00:00"},
    })
    expansion_args = ExpandEmailDetailsArgs.model_validate({
        "ids": "167635, 167636",
        "excerpt_chars": 1200,
    })

    assert metadata_args.search_criteria is not None
    assert metadata_args.search_criteria.to_email_search_criteria().date_from == datetime(2026, 4, 30, 0, 0, 0)
    assert expansion_args.email_ids == ["167635", "167636"]
    assert expansion_args.excerpt_chars == 1200


def test_mail_date_bounded_retrieval_uses_whose_predicate():
    mail_service = MailAppService()
    criteria = EmailSearchCriteria(
        date_from=datetime(2026, 4, 30, 0, 0, 0),
        date_to=datetime(2026, 5, 1, 23, 59, 59),
    )

    script = mail_service.get_emails_script("inbox", 50, criteria)

    assert "whose" in script
    assert "date received >= date" in script
    assert "date received <= date" in script
    assert "set allMessages to messages of inbox" not in script


def test_mail_sender_subject_status_retrieval_uses_whose_predicates():
    mail_service = MailAppService()
    criteria = EmailSearchCriteria(
        sender="person@example.com",
        subject_contains="invoice",
        is_read=False,
        is_flagged=True,
    )

    script = mail_service.get_emails_script("inbox", 20, criteria)

    assert 'sender contains "person@example.com"' in script
    assert 'subject contains "invoice"' in script
    assert "read status is false" in script
    assert "flagged status is true" in script
    assert "set allMessages to messages of inbox" not in script


def test_mail_body_only_retrieval_uses_recent_candidate_window():
    mail_service = MailAppService()
    criteria = EmailSearchCriteria(body_contains="needle")

    script = mail_service.get_emails_script("inbox", 10, criteria)

    assert "messages 1 thru candidateEndIndex of inbox" in script
    assert 'content of aMessage as string) contains "needle"' in script
    assert "set allMessages to messages of inbox" not in script


def test_mail_metadata_retrieval_does_not_expand_content():
    mail_service = MailAppService()
    criteria = EmailSearchCriteria(date_from=datetime(2026, 4, 30, 0, 0, 0), body_contains="needle")

    script = mail_service.get_email_metadata_script("inbox", 50, criteria)

    assert "whose" not in script
    assert "messages windowStart thru windowEnd of inbox" in script
    assert '", content:" & ""' in script
    assert "content of aMessage as string" not in script


def test_mail_metadata_date_bounds_select_received_date_candidates_before_limit():
    script = MailAppService().get_email_metadata_script(
        "inbox",
        50,
        EmailSearchCriteria(
            date_from=datetime(2026, 4, 30, 0, 0, 0),
            date_to=datetime(2026, 5, 1, 23, 59, 59),
        ),
    )

    assert "whose" not in script
    assert "messages windowStart thru windowEnd of inbox" in script
    assert "((date received of aMessage) >= date" in script
    assert "((date received of aMessage) <= date" in script
    assert 'set candidateScope to "window_size=" & windowSize' in script
    assert "content of aMessage" not in script


def test_mail_metadata_sent_folder_uses_sent_date_candidates():
    script = MailAppService().get_email_metadata_script(
        "sent",
        50,
        EmailSearchCriteria(date_from=datetime(2026, 4, 30, 0, 0, 0)),
    )

    assert "whose" not in script
    assert 'messages windowStart thru windowEnd of mailbox "sent"' in script
    assert "((date sent of aMessage) >= date" in script
    assert "date received" not in script


def test_mail_body_only_metadata_uses_bounded_candidate_window():
    script = MailAppService().get_email_metadata_script(
        "inbox",
        50,
        EmailSearchCriteria(body_contains="needle"),
    )

    assert "messages windowStart thru windowEnd of inbox" in script
    assert 'set candidateScope to "window_size=" & windowSize' in script
    assert "if true then" in script
    assert "content of aMessage as string" not in script


def test_mail_metadata_unread_only_uses_windowed_scan_not_whose():
    # This is the Bug 2 regression guard: an unread-only metadata read must never
    # emit a whole-mailbox `whose (read status ...)` predicate.
    script = MailAppService().get_email_metadata_script(
        "inbox",
        10,
        EmailSearchCriteria(is_read=False),
    )

    assert "whose" not in script
    assert "messages windowStart thru windowEnd of inbox" in script
    assert "((read status of aMessage) is false)" in script
    assert "content of aMessage as string" not in script


def test_mail_metadata_windows_widen_with_scan_cap_and_report_coverage():
    script = MailAppService().get_email_metadata_script(
        "inbox",
        50,
        EmailSearchCriteria(is_read=False),
    )

    assert "repeat while windowStart <= messageCount" in script
    assert "set windowStart to windowEnd + 1" in script
    assert "if scannedCount >= scanCap then" in script
    assert 'set coverageReason to "scan_cap_reached"' in script
    assert 'set coverageReason to "checked_entire_mailbox"' in script
    assert 'set coverageReason to "result_limit_reached"' in script
    # Settled sizing for limit=50: window_size=min(max(100,25),100)=100, scan_cap=min(max(500,250),1000)=500.
    assert "set windowSize to 100" in script
    assert "set scanCap to 500" in script


def test_mail_metadata_no_filter_uses_plain_recent_window():
    script = MailAppService().get_email_metadata_script("inbox", 5, None)

    assert "whose" not in script
    assert "messages windowStart thru windowEnd of inbox" in script
    assert "if true then" in script
    # Settled sizing for limit=5: window_size=min(max(25,25),100)=25, scan_cap=min(max(250,250),1000)=250.
    assert "set windowSize to 25" in script
    assert "set scanCap to 250" in script


def test_mail_selected_expansion_targets_specific_ids_with_excerpt_bound():
    script = MailAppService().expand_email_details_script("inbox", ["167635"], excerpt_chars=800)

    assert 'set targetIds to {"167635"}' in script
    assert "first message of inbox whose id is" in script
    assert "text 1 thru 800 of fullContent" in script


def test_outlook_date_subject_retrieval_uses_validated_candidate_predicates():
    outlook_service = OutlookAppleScriptService()
    criteria = EmailSearchCriteria(
        date_from=datetime(2026, 4, 30, 0, 0, 0),
        date_to=datetime(2026, 5, 1, 23, 59, 59),
        subject_contains="invoice",
    )

    script = outlook_service.search_emails_script(criteria, 25)

    assert "messages of targetFolder whose" in script
    assert "time received >= date" in script
    assert "time received <= date" in script
    assert 'subject contains "invoice"' in script
    assert "set allMessages to messages of targetFolder" not in script


def test_outlook_body_only_retrieval_uses_bounded_recent_window():
    outlook_service = OutlookAppleScriptService()
    criteria = EmailSearchCriteria(body_contains="needle")

    script = outlook_service.search_emails_script(criteria, 10)

    assert "messages 1 thru candidateEndIndex of targetFolder" in script
    assert 'plain text content of aMessage as string) does not contain "needle"' in script
    assert "set allMessages to messages of targetFolder" not in script


def test_outlook_metadata_retrieval_omits_body_filter_and_body_expansion():
    outlook_service = OutlookAppleScriptService()
    criteria = EmailSearchCriteria(body_contains="needle", date_from=datetime(2026, 4, 30, 0, 0, 0))

    script = outlook_service.get_email_metadata_script("inbox", 50, criteria)

    assert "messages of targetFolder whose" in script
    assert "time received >= date" in script
    assert "plain text content of aMessage" not in script
    assert 'set emailData to emailData & ""' in script


def test_outlook_selected_expansion_targets_specific_ids_with_excerpt_bound():
    script = OutlookAppleScriptService().expand_email_details_script("inbox", ["123"], excerpt_chars=900)

    assert 'set targetIds to {"123"}' in script
    assert "messages of targetFolder whose id is" in script
    assert "text 1 thru 900 of fullContent" in script


def test_outlook_search_script_does_not_include_destructive_email_commands():
    outlook_service = OutlookAppleScriptService()
    criteria = EmailSearchCriteria(
        sender="person@example.com",
        subject_contains="invoice",
        body_contains="needle",
        is_read=False,
        is_flagged=True,
    )

    script = outlook_service.search_emails_script(criteria, 10).lower()

    assert "make new outgoing message" not in script
    assert "\nsend " not in script
    assert "\ndelete " not in script
    assert "\nmove " not in script
    assert "\nreply " not in script


def test_outlook_auxiliary_operations_route_through_dispatch_templates():
    service = AppleScriptAutomationService()
    operation = EmailOperation(
        operation="mark_read",
        email_ids=["123"],
    )

    folders_script = service.script_templates["outlook"]["get_folders"]()
    create_folder_script = service.script_templates["outlook"]["create_folder"](
        "Client Requests",
        "Inbox",
    )
    organize_script = service.script_templates["outlook"]["organize_emails"](operation)

    assert 'tell application "Microsoft Outlook"' in folders_script
    assert 'tell application "Microsoft Outlook"' in create_folder_script
    assert 'tell application "Microsoft Outlook"' in organize_script


def test_mail_and_outlook_send_generators_fail_closed():
    email_request = EmailRequest(
        recipient="to@example.com",
        subject="Safety check",
        body="Body text",
        action="send",
    )

    mail_script = MailAppService().send_email_script(email_request)
    outlook_script = OutlookAppleScriptService().send_email_script(email_request)

    assert "Direct sending is disabled" in mail_script
    assert "Direct sending is disabled" in outlook_script
    assert "send newMessage" not in mail_script
    assert "send newMessage" not in outlook_script


def test_direct_applescript_send_action_downgrades_to_visible_mail_draft():
    async def run_test():
        service = AppleScriptAutomationService()
        captured = {}

        async def fake_execute(script, description="AppleScript"):
            captured["script"] = script
            captured["description"] = description
            return AppleScriptResult(success=True, data="SUCCESS")

        service.execute_applescript = fake_execute
        result = await service.process_email_via_applescript(
            "Mail.app",
            EmailRequest(
                recipient="to@example.com",
                subject="Safety check",
                body="Body text",
                action="send",
            ),
        )
        return result, captured

    result, captured = asyncio.run(run_test())

    assert result is True
    assert "make new outgoing message" in captured["script"]
    assert "set visible of newMessage to true" in captured["script"]
    assert "send newMessage" not in captured["script"]


@pytest.mark.skipif(
    os.environ.get("BASIL_LIVE_OUTLOOK_APPLESCRIPT") != "1",
    reason="Requires local Outlook setup; run manually with BASIL_LIVE_OUTLOOK_APPLESCRIPT=1.",
)
def test_live_outlook_read_only_validation_probe():
    script = OutlookAppleScriptService().scripts.read_only_validation_probe_script()

    result = subprocess.run(
        ["osascript"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0
    assert "folder_count=" in result.stdout
    assert "main_error=" not in result.stdout
    assert "whose_time_received_error=" not in result.stdout


@pytest.mark.skipif(
    os.environ.get("BASIL_LIVE_MAIL_APPLESCRIPT") != "1",
    reason="Requires local Mail.app setup; run manually with BASIL_LIVE_MAIL_APPLESCRIPT=1.",
)
def test_live_mail_date_bounded_metadata_script():
    script = MailAppService().get_email_metadata_script(
        "inbox",
        1,
        EmailSearchCriteria(
            date_from=datetime(1900, 1, 1),
            date_to=datetime(1900, 1, 1),
        ),
    )

    result = subprocess.run(
        ["osascript"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0
    assert "BASIL_MAIL_METADATA_COVERAGE:" in result.stdout


class _FakeAppleScriptService:
    def __init__(self):
        self.calls = 0

    async def process_email_via_applescript(self, selected_client_name, email_request):
        self.calls += 1
        return True


class _FakeEmailService(EmailCompositionMixin):
    def __init__(self):
        self.applescript_service = _FakeAppleScriptService()
        self.primary_client = EmailClient(
            name="Mail.app",
            bundle_id="com.apple.mail",
            is_running=True,
            automation_method="applescript",
            capabilities=["compose"],
            priority=1,
        )

    def _get_client_by_name(self, client_name=None):
        return self.primary_client


def test_invalid_email_contract_fails_before_applescript_execution():
    service = _FakeEmailService()
    execution_engine = ServiceExecutionEngine()
    execution_engine.register_service("email_service", service)

    result = asyncio.run(
        execution_engine.execute_service_method(
            "email_service",
            "create_new_email_draft",
            {
                "recipient": "Joel Bernath",
                "subject": "CloudFirst follow-up",
                "body": "Thanks, Scott.",
            },
        )
    )

    assert result.success is False
    assert "recipient" in result.error
    assert service.applescript_service.calls == 0


def test_outlook_compose_script_includes_cc_and_bcc_recipients():
    outlook_service = OutlookAppleScriptService()
    email_request = EmailRequest(
        recipient="to@example.com",
        subject="Contract mapping check",
        body="Body text",
        action="draft",
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )

    script = outlook_service.compose_email_script(email_request)

    assert "to@example.com" in script
    assert "cc@example.com" in script
    assert "bcc@example.com" in script
    assert "make new to recipient at newMessage" in script
    assert "make new cc recipient at newMessage" in script
    assert "make new bcc recipient at newMessage" in script
    assert "type:cc recipient type" not in script
    assert "type:bcc recipient type" not in script


def test_outlook_reply_all_false_is_preserved_through_composition_path():
    async def run_test():
        service = EmailClientService()
        service.detected_clients = [EmailClient(
            name="Microsoft Outlook",
            bundle_id="com.microsoft.Outlook",
            is_running=True,
            automation_method="applescript",
            capabilities=["compose_drafts", "reply_emails"],
            priority=2,
        )]
        captured = {}

        async def fake_execute(script, description="AppleScript"):
            captured["script"] = script
            captured["description"] = description
            return AppleScriptResult(success=True, data="SUCCESS")

        service.applescript_service.execute_applescript = fake_execute

        result = await service.create_reply_email_draft(
            reference_email_id="167029",
            reply_body="Thanks.",
            reply_all=False,
        )

        return result, captured

    result, captured = asyncio.run(run_test())
    script = captured["script"]

    assert result is True
    assert "reply to originalMessage reply to all false" in script


def test_mail_reply_body_is_set_before_showing_compose_window():
    mail_service = MailAppService()

    script = mail_service.reply_to_email_script(
        email_id="167029",
        reply_body="Thanks.",
        reply_all=True,
    )

    hidden_reply_index = script.index("without opening window")
    set_content_index = script.index("set content of replyMessage to")
    save_index = script.index("save replyMessage")
    verify_index = script.index("set afterContent to content of replyMessage")
    show_index = script.index("set visible of replyMessage to true")

    assert "with opening window" not in script
    assert "set originalContent to content of replyMessage" not in script
    assert hidden_reply_index < set_content_index < save_index < verify_index < show_index


def test_mail_app_client_name_routes_to_mail_reply_dispatch():
    async def run_test():
        service = AppleScriptAutomationService()
        captured = {}

        async def fake_execute(script, description="AppleScript"):
            captured["script"] = script
            captured["description"] = description
            return AppleScriptResult(success=True, data="SUCCESS: Reply draft created")

        service.execute_applescript = fake_execute

        result = await service.reply_to_email_via_applescript(
            "Mail.app",
            email_id="167029",
            reply_body="Thanks.",
            reply_all=False,
        )

        return result, captured

    result, captured = asyncio.run(run_test())

    assert result is True
    assert 'tell application "Mail"' in captured["script"]
    assert "without opening window" in captured["script"]


def test_semantic_applescript_error_stdout_fails_email_operation():
    async def run_test():
        service = EmailClientService()
        service.detected_clients = [EmailClient(
            name="Microsoft Outlook",
            bundle_id="com.microsoft.Outlook",
            is_running=True,
            automation_method="applescript",
            capabilities=["compose_drafts", "reply_emails"],
            priority=2,
        )]

        async def fake_execute(script, description="AppleScript"):
            return AppleScriptResult(success=True, data="ERROR: message not found")

        service.applescript_service.execute_applescript = fake_execute

        return await service.create_reply_email_draft(
            reference_email_id="missing-id",
            reply_body="Thanks.",
        )

    assert asyncio.run(run_test()) is False
