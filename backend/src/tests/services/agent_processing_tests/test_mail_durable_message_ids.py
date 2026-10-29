"""Mail scripts resolve messages by the durable RFC Message-ID, with the integer id as a fallback."""

import shutil
import subprocess

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import EmailOperation
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_operation_contracts import (
    OrganizeEmailsArgs,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_tool_contracts import (
    ExpandEmailDetailsArgs,
    normalize_email_id,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mail_app_service import (
    MailAppService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.message_lookup import (
    MESSAGE_ID_SCAN_LIMIT,
    MESSAGE_LOOKUP_HANDLERS,
)

RFC_ID = "010001a17df4bcf1-96eafdd5-0f2e-4f09-a526-e6447f9cdbe0-000000@email.amazonses.com"


def test_angle_brackets_around_an_rfc_message_id_are_removed_and_other_ids_are_kept():
    assert normalize_email_id(f"<{RFC_ID}>") == RFC_ID
    assert normalize_email_id(f"  {RFC_ID} ") == RFC_ID
    assert normalize_email_id("16538287") == "16538287"
    assert normalize_email_id("<>") == "<>"


def test_organize_and_expand_contracts_accept_rfc_ids_and_describe_them_as_preferred():
    organize = OrganizeEmailsArgs(operation="archive", email_ids=[f"<{RFC_ID}>", "16538287"])
    assert organize.email_ids == [RFC_ID, "16538287"]
    assert "RFC Message-ID" in OrganizeEmailsArgs.model_fields["email_ids"].description
    expand = ExpandEmailDetailsArgs(email_ids=[RFC_ID])
    assert expand.email_ids == [RFC_ID]
    assert "RFC Message-ID" in ExpandEmailDetailsArgs.model_fields["email_ids"].description


def test_every_mail_script_that_takes_an_id_resolves_it_through_the_shared_handlers():
    service = MailAppService()
    scripts = {
        "archive": service.organize_emails_receipt_script(EmailOperation(operation="archive", email_ids=[RFC_ID])),
        "move": service.organize_emails_receipt_script(EmailOperation(operation="move", email_ids=[RFC_ID], target_folder="Work / X")),
        "delete": service.organize_emails_receipt_script(EmailOperation(operation="delete", email_ids=[RFC_ID])),
        "mark_read": service.organize_emails_receipt_script(EmailOperation(operation="mark_read", email_ids=[RFC_ID])),
        "flag": service.organize_emails_receipt_script(EmailOperation(operation="flag", email_ids=[RFC_ID])),
        "expand": service.expand_email_details_script("inbox", [RFC_ID], 500),
        "reply": service.scripts.reply_to_email_script(RFC_ID, "Hello", True, True),
    }
    for name, script in scripts.items():
        assert "on isMailRowId(token)" in script, name
        assert "whose message id is token" in script, name
        assert "whose id is messageId" not in script and "whose id is (targetId" not in script, name
        assert RFC_ID in script, name
    for name in ("archive", "move", "delete", "mark_read", "flag", "reply"):
        assert "findInboxMessage(" in scripts[name], name
    assert "first message of inbox whose id" not in "".join(scripts.values())


@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is only available on macOS")
def test_lookup_scripts_compile_without_executing(tmp_path):
    service = MailAppService()
    scripts = {
        "mark_read": service.organize_emails_receipt_script(EmailOperation(operation="mark_read", email_ids=[RFC_ID])),
        "expand": service.expand_email_details_script("inbox", [RFC_ID], 500),
        "legacy_flag": service.organize_emails_script(EmailOperation(operation="flag", email_ids=[RFC_ID])),
        "legacy_move": service.organize_emails_script(EmailOperation(operation="move", email_ids=[RFC_ID], target_folder="X")),
    }
    for name, script in scripts.items():
        source = tmp_path / f"{name}.applescript"
        source.write_text(script)
        done = subprocess.run(["osacompile", "-o", str(tmp_path / f"{name}.scpt"), str(source)], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"{name}: {done.stderr}"


@pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript is only available on macOS")
def test_row_id_detector_distinguishes_integer_ids_from_message_ids(tmp_path):
    script = f"""
{MESSAGE_LOOKUP_HANDLERS}
set out to {{}}
repeat with sample in {{"16538287", "{RFC_ID}", "0123", "1.5", "", "12 34"}}
    set end of out to (my isMailRowId(sample as text)) as text
end repeat
set AppleScript's text item delimiters to ","
return out as text
"""
    source = tmp_path / "detect.applescript"
    source.write_text(script)
    done = subprocess.run(["osascript", str(source)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "true,false,false,false,false,false"


def test_expand_uses_per_account_inbox_lookup_for_the_unified_inbox_and_a_size_guard_elsewhere():
    service = MailAppService()
    unified = service.expand_email_details_script("inbox", [RFC_ID], 500)
    assert "set aMessage to my findInboxMessage(targetId as text)" in unified
    scoped = service.expand_email_details_script("Work / Clients", [RFC_ID], 500)
    assert "my firstMessageByToken(" in scoped and 'whose name is "Clients"' in scoped or "Clients" in scoped
    assert f"(count of messages of theMailbox) > {MESSAGE_ID_SCAN_LIMIT} then error" in MESSAGE_LOOKUP_HANDLERS
