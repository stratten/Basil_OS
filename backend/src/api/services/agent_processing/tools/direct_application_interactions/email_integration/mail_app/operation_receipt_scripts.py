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
            set receiptRecord to {{
                entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}},
                requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}},
                execution_state:"succeeded",
                observed_postcondition:observedState,
                verification_status:"verified",
                evidence:{{mail_readback:observedState}},
                discrepancy:{{}}
            }}
        on error errMsg number errNum
            set receiptRecord to {{
                entity:{{entity_type:"email", source_system:"mail_app", source_scope:{{mailbox:"inbox"}}, external_id:messageId}},
                requested_effect:{{operation:"{operation.operation}", target_folder:"{target_folder}"}},
                execution_state:"failed",
                observed_postcondition:{{}},
                verification_status:"failed",
                evidence:{{mail_error_number:errNum}},
                discrepancy:{{mail_error:errMsg}}
            }}
        end try
        set end of receiptRecords to receiptRecord
    end repeat
end tell
set envelope to {{contract_version:1, material_write:true, receipts:receiptRecords}}
return "RESULT_JSON:" & jsonTextFor(envelope)
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
