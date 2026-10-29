"""Mail.app scripts that emit one Foundation-serialized receipt per message."""

from __future__ import annotations

from typing import Callable

from ..email_models import EmailOperation
from .gmail_inbox_ui_script import SUBJECT_HANDLERS
from .mailbox_resolution import mailbox_name_candidates, split_account_token
from .message_lookup import MESSAGE_LOOKUP_HANDLERS

TARGET_SCAN_LIMIT = 5000
"""A destination mailbox larger than this is not scanned by RFC message id, because Mail filters at roughly 0.4 ms per message (about 30 seconds for 77,000)."""

TARGET_SCAN_SKIPPED = -3
"""The ``target_count`` the verification script reports for a destination mailbox over ``TARGET_SCAN_LIMIT``."""

ARCHIVE_MAILBOX_NAME = "Archive"
"""The mailbox a non-Gmail account archives into. A Gmail account archives through Mail's own Archive command instead, because moving to a label there never removes the Inbox label."""

_MAILBOX_HANDLERS = '''
on joinedMailboxNames(accountName)
    set namesText to ""
    try
        tell application "Mail" to set mailboxNames to name of every mailbox of account accountName
        set AppleScript's text item delimiters to ", "
        set namesText to mailboxNames as text
        set AppleScript's text item delimiters to ""
    end try
    return namesText
end joinedMailboxNames

on findMailbox(accountName, mailboxName)
    tell application "Mail"
        if accountName is "" then return mailbox mailboxName
        set matches to (every mailbox of account accountName whose name is mailboxName)
        if (count of matches) is 1 then return item 1 of matches
        if (count of matches) > 1 then error "Account " & accountName & " has more than one mailbox named " & mailboxName & "." number -1728
        try
            return mailbox mailboxName of account accountName
        on error
            error "Account " & accountName & " has no mailbox named " & mailboxName & ". Available mailboxes: " & my joinedMailboxNames(accountName) & "." number -1728
        end try
    end tell
end findMailbox
'''
"""Shared AppleScript handlers. Mail resolves a mailbox subscripted by name through its special-mailbox aliases, so on Gmail ``mailbox "Archive"`` returns All Mail instead of the label named Archive, and ``mailbox "All Mail"`` cannot be found at all. Filtering with ``whose name is`` returns the mailbox that really carries the name, and the subscript is only a fallback for special mailboxes with no matching name."""


class MailOperationReceiptScriptGenerator:
    """Generate per-target Mail organization scripts with readback evidence."""

    def __init__(self, escape: Callable[[str], str]) -> None:
        self._escape = escape

    def organize_emails_receipt_script(self, operation: EmailOperation) -> str:
        """Emit a shared material-operation envelope for a validated request."""
        message_ids = ", ".join(
            f'"{self._escape(message_id)}"' for message_id in operation.email_ids
        )
        target_folder = self._escape(operation.target_folder or "")
        target_account, target_label = split_account_token(operation.target_folder or "")
        if operation.operation in ("move", "delete", "archive"):
            if operation.operation == "archive":
                target_label = ARCHIVE_MAILBOX_NAME
            return self._identity_capturing_script(
                operation,
                message_ids,
                target_folder,
                self._escape(target_account or ""),
                [self._escape(name) for name in mailbox_name_candidates(target_label)] if target_label else [],
            )
        mutation, postcondition = self._mutation_and_readback(
            operation.operation,
            target_folder,
        )
        return f'''
use framework "Foundation"
use scripting additions

on jsonTextFor(value)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
end jsonTextFor
{MESSAGE_LOOKUP_HANDLERS}
set requestedIds to {{{message_ids}}}
set receiptRecords to {{}}
tell application "Mail"
    repeat with requestedId in requestedIds
        set messageId to requestedId as text
        try
            set theMessage to my findInboxMessage(messageId)
            if theMessage is missing value then error "Message " & messageId & " is not in any account's inbox." number -1728
            {mutation}
            {postcondition}
            set receiptRecord to {{entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}}, requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}}, execution_state:"succeeded", observed_postcondition:observedState, verification_status:"verified", evidence:{{mail_readback:observedState}}, discrepancy:{{}}}}
        on error errMsg number errNum
            set receiptRecord to {{entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}}, requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}}, execution_state:"failed", observed_postcondition:{{}}, verification_status:"failed", evidence:{{mail_error_number:errNum}}, discrepancy:{{mail_error:errMsg}}}}
        end try
        set end of receiptRecords to receiptRecord
    end repeat
end tell
set envelope to {{contract_version:1, material_write:true, receipts:receiptRecords}}
return "RESULT_JSON:" & jsonTextFor(envelope)
'''

    def _identity_capturing_script(
        self,
        operation: EmailOperation,
        message_ids: str,
        target_folder: str,
        target_account: str,
        target_labels: list[str],
    ) -> str:
        """Move, archive, or delete, recording the stable identity first. On a Gmail account a move or archive is not performed here, because Mail's scripted move never removes the Inbox label; the receipt is marked ``ui_required`` and nothing changes until the organize step has the user's approval to drive Mail's visible menus through ``gmail_inbox_ui``, which takes over the screen for several seconds per message.

        Mail's integer ``id`` is not unique or stable across mailboxes and a move settles asynchronously, so this pass only reports the attempt
        together with the RFC ``message id``, account, and source mailbox. Verification is a separate pass that looks the message up by RFC id.
        The source is the account's INBOX, because the message was found in the inbox. Mail reports ``mailbox of message`` as All Mail for every Gmail message, so using it would make an archived message look as if it never left the source.
        """
        if operation.operation in ("move", "archive"):
            candidate_list = ", ".join(f'"{name}"' for name in target_labels)
            lookup = f'''set targetMailbox to missing value
            set targetAccountName to "{target_account}"
            if targetAccountName is "" then set targetAccountName to sourceAccountName
            set targetLookupError to ""
            repeat with candidateName in {{{candidate_list}}}
                try
                    set targetMailbox to my findMailbox(targetAccountName, candidateName as text)
                    exit repeat
                on error lookupErrText
                    if targetLookupError is "" then set targetLookupError to lookupErrText
                end try
            end repeat
            if targetMailbox is missing value then error targetLookupError number -1728
            set targetMailboxName to name of targetMailbox'''
            if operation.operation == "archive":
                mutation = f'''set targetMailboxName to ""
            set targetAccountName to ""
            if not labelInbox then
                {lookup}
                move theMessage to targetMailbox
            end if'''
            else:
                mutation = f"{lookup}\n            if not labelInbox then move theMessage to targetMailbox"
        else:
            mutation = "set targetMailboxName to \"\"\n            set targetAccountName to \"\"\n            delete theMessage"
        ui_capable = "true" if operation.operation in ("move", "archive") else "false"
        return f'''
use framework "Foundation"
use scripting additions

on jsonTextFor(value)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
end jsonTextFor
{_MAILBOX_HANDLERS}
{SUBJECT_HANDLERS}
{MESSAGE_LOOKUP_HANDLERS}
set requestedIds to {{{message_ids}}}
set receiptRecords to {{}}
tell application "Mail"
    repeat with requestedId in requestedIds
        set messageId to requestedId as text
        try
            set theMessage to my findInboxMessage(messageId)
            if theMessage is missing value then error "Message " & messageId & " is not in any account's inbox." number -1728
            set sourceMailboxRef to mailbox of theMessage
            set sourceMailboxName to name of sourceMailboxRef
            set labelInbox to (sourceMailboxName is not "INBOX")
            set sourceAccountName to ""
            try
                set sourceAccountName to name of account of sourceMailboxRef
            end try
            if sourceAccountName is not "" then
                try
                    set sourceMailboxName to name of (my findMailbox(sourceAccountName, "INBOX"))
                end try
            end if
            set rfcMessageId to message id of theMessage
            set uiRequired to false
            set coreText to ""
            set siblingIds to {{}}
            if labelInbox and {ui_capable} then
                set uiRequired to true
                set coreText to my coreSubject(subject of theMessage)
                if coreText is not "" then
                    set accountInbox to my findMailbox(sourceAccountName, "INBOX")
                    set siblingMessages to (every message of accountInbox whose subject contains coreText)
                    repeat with siblingMessage in siblingMessages
                        set siblingRfc to message id of siblingMessage
                        if siblingRfc is not rfcMessageId then
                            if (my coreSubject(subject of siblingMessage)) is coreText then set end of siblingIds to siblingRfc
                        end if
                    end repeat
                end if
            end if
            {mutation}
            set receiptRecord to {{entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}}, requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}}, execution_state:"attempted", observed_postcondition:{{}}, verification_status:"unverified", evidence:{{rfc_message_id:rfcMessageId, |account|:sourceAccountName, source_mailbox:sourceMailboxName, target_mailbox:targetMailboxName, target_account:targetAccountName, ui_required:uiRequired, subject_core:coreText, sibling_rfc_ids:siblingIds}}, discrepancy:{{}}}}
        on error errMsg number errNum
            set receiptRecord to {{entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}}, requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}}, execution_state:"failed", observed_postcondition:{{}}, verification_status:"failed", evidence:{{mail_error_number:errNum}}, discrepancy:{{mail_error:errMsg}}}}
        end try
        set end of receiptRecords to receiptRecord
    end repeat
end tell
set envelope to {{contract_version:1, material_write:true, receipts:receiptRecords}}
return "RESULT_JSON:" & jsonTextFor(envelope)
'''

    def verify_locations_script(self, checks: list[dict[str, str]]) -> str:
        """Count each message, found by RFC message id, in its source and target mailbox of one account."""
        records = ", ".join(
            "{"
            f'checkIndex:{index}, rfcId:"{self._escape(check["rfc_message_id"])}", '
            f'accountName:"{self._escape(check.get("account", ""))}", '
            f'targetAccountName:"{self._escape(check.get("target_account") or check.get("account", ""))}", '
            f'sourceName:"{self._escape(check.get("source_mailbox", ""))}", '
            f'targetName:"{self._escape(check.get("target_mailbox", ""))}"'
            "}"
            for index, check in enumerate(checks)
        )
        return f'''
use framework "Foundation"
use scripting additions

on jsonTextFor(value)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
end jsonTextFor
{_MAILBOX_HANDLERS}
on countMatches(accountName, mailboxName, rfcId, scanLimit)
    set theMailbox to my findMailbox(accountName, mailboxName)
    tell application "Mail"
        if scanLimit > 0 and (count of messages of theMailbox) > scanLimit then return {TARGET_SCAN_SKIPPED}
        return count of (messages of theMailbox whose message id is rfcId)
    end tell
end countMatches

set checks to {{{records}}}
set resultRecords to {{}}
repeat with aCheck in checks
    set sourceCount to -1
    set targetCount to -1
    set checkError to ""
    try
        set sourceCount to my countMatches(accountName of aCheck, sourceName of aCheck, rfcId of aCheck, 0)
        if (targetName of aCheck) is "" then
            set targetCount to -2
        else
            set targetCount to my countMatches(targetAccountName of aCheck, targetName of aCheck, rfcId of aCheck, {TARGET_SCAN_LIMIT})
        end if
    on error errMsg
        set checkError to errMsg
    end try
    set end of resultRecords to {{check_index:(checkIndex of aCheck), source_count:sourceCount, target_count:targetCount, lookup_error:checkError}}
end repeat
return "RESULT_JSON:" & jsonTextFor({{checks:resultRecords}})
'''

    @staticmethod
    def _mutation_and_readback(operation: str, target_folder: str) -> tuple[str, str]:
        if operation == "move":
            return (
                f'set sourceMailbox to mailbox "inbox"\n            set targetMailbox to mailbox "{target_folder}"\n            move theMessage to targetMailbox',
                (
                    'set destinationMessage to first message of targetMailbox whose id is messageId\n'
                    '            set observedState to {destination_mailbox:name of targetMailbox, source_absent:(not (exists (first message of sourceMailbox whose id is messageId)))}'
                ),
            )
        if operation == "delete":
            return (
                "delete theMessage",
                'set observedState to {deleted:true}',
            )
        if operation == "mark_read":
            return (
                "set read status of theMessage to true",
                'set observedState to {read_status:(read status of theMessage)}',
            )
        if operation == "flag":
            return (
                "set flagged status of theMessage to true",
                'set observedState to {flagged_status:(flagged status of theMessage)}',
            )
        raise ValueError(f"Unsupported Mail operation: {operation}")
