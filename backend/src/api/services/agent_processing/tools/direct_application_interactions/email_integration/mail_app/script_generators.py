"""
Mail.app AppleScript Generators

Generates all AppleScript code for Mail.app email operations:
email retrieval, composition, reply, search, organization, and folder management.
"""

import logging
from typing import Optional

from ..email_models import EmailRequest, EmailOperation, EmailSearchCriteria
from .parsing import MailAppParser
from .retrieval_scripts import MailRetrievalScripts

logger = logging.getLogger(__name__)


class MailAppScriptGenerator:
    """Generates AppleScript code for all Mail.app email operations."""

    def __init__(self) -> None:
        self._retrieval_scripts = MailRetrievalScripts(self._escape)

    def _escape(self, text: str) -> str:
        return MailAppParser.escape_applescript_string(text)

    def get_emails_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        return self._retrieval_scripts.get_emails_script(folder, limit, search_criteria)

    def get_email_metadata_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        return self._retrieval_scripts.get_email_metadata_script(folder, limit, search_criteria)

    def expand_email_details_script(self, folder: str, email_ids: list[str], excerpt_chars: int = 4000) -> str:
        return self._retrieval_scripts.expand_email_details_script(folder, email_ids, excerpt_chars)

    def compose_email_script(self, email_request: EmailRequest, draft_only: bool = True) -> str:
        """Generate AppleScript to compose email in Mail.app."""
        
        escaped_subject = self._escape(email_request.subject)
        escaped_body = self._escape(email_request.body)
        
        to_addresses = [addr.strip() for addr in email_request.recipient.replace(';', ',').split(',') if addr.strip()]
        if len(to_addresses) > 1:
            to_list = ", ".join([f'"{self._escape(addr)}"' for addr in to_addresses])
            to_recipients = f'''
            repeat with toAddr in {{{to_list}}}
                make new to recipient at end of to recipients with properties {{address:toAddr}}
            end repeat
            '''
        else:
            escaped_recipient = self._escape(to_addresses[0] if to_addresses else email_request.recipient)
            to_recipients = f'make new to recipient at end of to recipients with properties {{address:"{escaped_recipient}"}}'
        
        cc_recipients = ""
        bcc_recipients = ""
        
        if email_request.cc:
            cc_list = ", ".join([f'"{self._escape(cc)}"' for cc in email_request.cc])
            cc_recipients = f'''
            repeat with ccAddr in {{{cc_list}}}
                make new cc recipient at end of cc recipients with properties {{address:ccAddr}}
            end repeat
            '''
        
        if email_request.bcc:
            bcc_list = ", ".join([f'"{self._escape(bcc)}"' for bcc in email_request.bcc])
            bcc_recipients = f'''
            repeat with bccAddr in {{{bcc_list}}}
                make new bcc recipient at end of bcc recipients with properties {{address:bccAddr}}
            end repeat
            '''
        
        action = "set visible of newMessage to true" if draft_only else "send newMessage"
        
        return f'''
        tell application "Mail"
            set newMessage to make new outgoing message with properties {{¬
                subject:"{escaped_subject}", ¬
                content:"{escaped_body}"}}
            
            tell newMessage
                {to_recipients}
                {cc_recipients}
                {bcc_recipients}
            end tell
            
            {action}
            
            activate
        end tell
        '''

    def send_email_script(self, email_request: EmailRequest) -> str:
        """Fail closed: Mail.app automation never sends email directly."""
        return '''
        tell application "Mail"
            return "ERROR: Direct sending is disabled. Create a visible draft for manual review instead."
        end tell
        '''

    def reply_to_email_script(self, email_id: str, reply_body: str, reply_all: bool = True, draft_only: bool = True) -> str:
        """
        Generate AppleScript to create a reply draft in Mail.app using native reply functionality.
        
        Uses Mail.app's native "reply" command which automatically:
        - Sets proper threading headers
        - Populates recipients from the original email
        - Maintains conversation context
        """
        escaped_body = self._escape(reply_body)
        escaped_email_id = self._escape(email_id)
        
        reply_params = "with reply to all" if reply_all else ""
        
        script = f'''
        tell application "Mail"
            try
                set originalMessage to (first message of inbox whose id is "{escaped_email_id}")
                
                set replyMessage to reply originalMessage {reply_params} without opening window
                
                set bodyAccepted to false
                set afterContent to ""
                repeat with attemptIndex from 1 to 20
                    set content of replyMessage to "{escaped_body}"
                    save replyMessage
                    set afterContent to content of replyMessage
                    if afterContent begins with "{escaped_body}" then
                        set bodyAccepted to true
                        exit repeat
                    end if
                    delay 0.05
                end repeat

                if bodyAccepted is false then
                    return "ERROR: Mail.app reply body was not accepted by outgoing message"
                end if

                set visible of replyMessage to true
                
                activate
                
                return "SUCCESS: Reply draft created"
                
            on error errMsg
                return "ERROR: " & errMsg
            end try
        end tell
        '''
        
        logger.info(f"📧 Generated Mail.app reply script for email_id={email_id[:20]}..., reply_all={reply_all}, draft_only={draft_only}")
        
        return script

    def organize_emails_script(self, operation: EmailOperation) -> str:
        """Generate AppleScript to organize emails in Mail.app."""
        
        email_ids = ", ".join([f'"{email_id}"' for email_id in operation.email_ids])
        
        if operation.operation == "move":
            return f'''
            tell application "Mail"
                set messageIds to {{{email_ids}}}
                set targetMailbox to mailbox "{operation.target_folder}"
                
                repeat with messageId in messageIds
                    try
                        set theMessage to (first message whose id is messageId)
                        move theMessage to targetMailbox
                    on error
                        -- Skip messages that can't be moved
                    end try
                end repeat
            end tell
            '''
        elif operation.operation == "delete":
            return f'''
            tell application "Mail"
                set messageIds to {{{email_ids}}}
                
                repeat with messageId in messageIds
                    try
                        set theMessage to (first message whose id is messageId)
                        delete theMessage
                    on error
                        -- Skip messages that can't be deleted
                    end try
                end repeat
            end tell
            '''
        elif operation.operation == "mark_read":
            return f'''
            tell application "Mail"
                set messageIds to {{{email_ids}}}
                
                repeat with messageId in messageIds
                    try
                        set theMessage to (first message whose id is messageId)
                        set read status of theMessage to true
                    on error
                        -- Skip messages that can't be marked
                    end try
                end repeat
            end tell
            '''
        elif operation.operation == "flag":
            return f'''
            tell application "Mail"
                set messageIds to {{{email_ids}}}
                
                repeat with messageId in messageIds
                    try
                        set theMessage to (first message whose id is messageId)
                        set flagged status of theMessage to true
                    on error
                        -- Skip messages that can't be flagged
                    end try
                end repeat
            end tell
            '''
        else:
            raise ValueError(f"Unsupported operation: {operation.operation}")

    def get_folders_script(self) -> str:
        """Generate AppleScript listing Mail.app folders as newline-delimited names.

        Emits three kinds of node (newline-delimited so account/folder names may
        contain commas safely):
          - "Inbox": the unified special inbox the read path serves for folder "inbox".
          - "<Account> / <Mailbox>": every per-account mailbox. Apple Mail's app-level
            `every mailbox` omits per-account IMAP inboxes, so these are enumerated from
            `mailboxes of account`. The " / " separator matches
            MailRetrievalScripts.ACCOUNT_FOLDER_SEPARATOR so a listed token round-trips
            unchanged into a read via _mailbox_reference.
          - top-level `every mailbox` names (On My Mac / local), preserving prior behavior.
        """
        return '''
        tell application "Mail"
            set folderList to {}
            set end of folderList to "Inbox"

            repeat with anAccount in accounts
                try
                    set accountName to name of anAccount
                    repeat with aMailbox in mailboxes of anAccount
                        try
                            set end of folderList to accountName & " / " & (name of aMailbox)
                        on error
                            -- Skip mailboxes that can't be named
                        end try
                    end repeat
                on error
                    -- Skip accounts that can't be enumerated
                end try
            end repeat

            repeat with aMailbox in every mailbox
                try
                    set end of folderList to name of aMailbox
                on error
                    -- Skip mailboxes that can't be accessed
                end try
            end repeat

            set previousDelimiters to AppleScript's text item delimiters
            set AppleScript's text item delimiters to linefeed
            set folderText to folderList as text
            set AppleScript's text item delimiters to previousDelimiters

            return folderText
        end tell
        '''

    def create_folder_script(self, folder_name: str, parent_folder: Optional[str] = None) -> str:
        """Generate AppleScript to create folder in Mail.app."""
        
        if parent_folder:
            return f'''
            tell application "Mail"
                set parentMailbox to mailbox "{parent_folder}"
                make new mailbox at parentMailbox with properties {{name:"{folder_name}"}}
            end tell
            '''
        else:
            return f'''
            tell application "Mail"
                make new mailbox with properties {{name:"{folder_name}"}}
            end tell
            '''
