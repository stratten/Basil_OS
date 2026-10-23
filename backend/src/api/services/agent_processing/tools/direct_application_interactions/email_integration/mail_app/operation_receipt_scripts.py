"""Mail.app scripts that emit one Foundation-serialized receipt per message."""

from __future__ import annotations

from typing import Callable

from ..email_models import EmailOperation


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
        mutation, postcondition = self._mutation_and_readback(
            operation.operation,
            target_folder,
        )
        if operation.operation in ("move", "delete"):
            return self._identity_capturing_script(operation, message_ids, target_folder)
        return f'''
use framework "Foundation"
use scripting additions

on jsonTextFor(value)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
end jsonTextFor

set requestedIds to {{{message_ids}}}
set receiptRecords to {{}}
tell application "Mail"
    repeat with requestedId in requestedIds
        set messageId to requestedId as text
        try
            set theMessage to first message of inbox whose id is messageId
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
    ) -> str:
        """Move or delete, recording the stable identity first.

        Mail's integer ``id`` is not unique or stable across mailboxes and a move settles asynchronously, so this pass only reports the attempt
        together with the RFC ``message id``, account, and source mailbox. Verification is a separate pass that looks the message up by RFC id.
        """
        if operation.operation == "move":
            mutation = (
                f'''set targetMailbox to missing value
            try
                set targetMailbox to mailbox "{target_folder}" of account sourceAccountName
            end try
            if targetMailbox is missing value then set targetMailbox to mailbox "{target_folder}"
            set targetMailboxName to name of targetMailbox
            move theMessage to targetMailbox'''
            )
        else:
            mutation = "set targetMailboxName to \"\"\n            delete theMessage"
        return f'''
use framework "Foundation"
use scripting additions

on jsonTextFor(value)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
end jsonTextFor

set requestedIds to {{{message_ids}}}
set receiptRecords to {{}}
tell application "Mail"
    repeat with requestedId in requestedIds
        set messageId to requestedId as text
        try
            set theMessage to first message of inbox whose id is messageId
            set sourceMailboxRef to mailbox of theMessage
            set sourceMailboxName to name of sourceMailboxRef
            set sourceAccountName to ""
            try
                set sourceAccountName to name of account of sourceMailboxRef
            end try
            set rfcMessageId to message id of theMessage
            {mutation}
            set receiptRecord to {{entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}}, requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}}, execution_state:"attempted", observed_postcondition:{{}}, verification_status:"unverified", evidence:{{rfc_message_id:rfcMessageId, account:sourceAccountName, source_mailbox:sourceMailboxName, target_mailbox:targetMailboxName}}, discrepancy:{{}}}}
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

on countMatches(accountName, mailboxName, rfcId)
    tell application "Mail"
        if accountName is "" then
            set theMailbox to mailbox mailboxName
        else
            set theMailbox to mailbox mailboxName of account accountName
        end if
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
        set sourceCount to my countMatches(accountName of aCheck, sourceName of aCheck, rfcId of aCheck)
        if (targetName of aCheck) is "" then
            set targetCount to -2
        else
            set targetCount to my countMatches(accountName of aCheck, targetName of aCheck, rfcId of aCheck)
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
