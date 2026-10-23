"""Mail.app AppleScript generation for retrieval and expansion."""

from __future__ import annotations

from typing import Callable, Optional

from ..email_models import EmailSearchCriteria


class MailRetrievalScripts:
    """Generate bounded Mail.app retrieval AppleScripts."""

    def __init__(self, escape: Callable[[str], str]) -> None:
        self._escape = escape

    def _email_record_applescript(self) -> str:
        """Return AppleScript that builds one full email record."""
        return '''set recipientAddress to ""
                            try
                                set recipientAddress to address of first to recipient of aMessage as string
                            on error
                                try
                                    set recipientAddress to name of first to recipient of aMessage as string
                                on error
                                    set recipientAddress to ""
                                end try
                            end try
                            
                            set emailRecord to {¬
                                email_id:(id of aMessage as string), ¬
                                subject:(subject of aMessage as string), ¬
                                sender:(sender of aMessage as string), ¬
                                recipient:recipientAddress, ¬
                                content:(content of aMessage as string), ¬
                                date_sent:(date sent of aMessage as string), ¬
                                is_read:(read status of aMessage as string), ¬
                                is_flagged:(flagged status of aMessage as string), ¬
                                message_id:(message id of aMessage as string)}
                            
                            set end of emailRecords to emailRecord'''

    def _email_metadata_record_text_applescript(self) -> str:
        """Return parser-compatible Mail metadata without reading content."""
        return '''set recipientAddress to ""
                            try
                                set recipientAddress to address of first to recipient of aMessage as string
                            on error
                                try
                                    set recipientAddress to name of first to recipient of aMessage as string
                                on error
                                    set recipientAddress to ""
                                end try
                            end try
                            
                            set emailRecord to "email_id:" & (id of aMessage as string) & ¬
                                ", subject:" & (subject of aMessage as string) & ¬
                                ", sender:" & (sender of aMessage as string) & ¬
                                ", recipient:" & recipientAddress & ¬
                                ", content:" & "" & ¬
                                ", date_sent:" & (date sent of aMessage as string) & ¬
                                ", is_read:" & (read status of aMessage as string) & ¬
                                ", is_flagged:" & (flagged status of aMessage as string) & ¬
                                ", message_id:" & (message id of aMessage as string)

                            set end of emailRecords to emailRecord'''

    def get_emails_script(
        self,
        folder: str,
        limit: int,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> str:
        """Generate Mail.app retrieval for structured email records."""
        mailbox_reference = self._mailbox_reference(folder)
        predicate_conditions = self._build_mail_predicate_conditions(search_criteria, folder)
        post_filter_conditions = self._build_post_filter_conditions(search_criteria)
        predicate_clause = f" whose {' and '.join(predicate_conditions)}" if predicate_conditions else ""
        post_filter_check = f"if {post_filter_conditions} then" if post_filter_conditions else "if true then"

        if not predicate_conditions and not post_filter_conditions:
            return f'''
            tell application "Mail"
                set emailRecords to {{}}
                
                set messageCount to count of messages of {mailbox_reference}
                set endIndex to {limit}
                if messageCount < endIndex then set endIndex to messageCount
                
                if endIndex > 0 then
                    set recentMessages to messages 1 thru endIndex of {mailbox_reference}
                    
                    repeat with aMessage in recentMessages
                        try
                            {self._email_record_applescript()}
                        on error errMsg
                            -- Skip messages that can't be processed
                        end try
                    end repeat
                end if
                
                return emailRecords
            end tell
            '''

        candidate_source = (
            f"messages of {mailbox_reference}{predicate_clause}"
            if predicate_conditions
            else f"messages 1 thru candidateEndIndex of {mailbox_reference}"
        )
        candidate_window_setup = ""
        candidate_assignment = f"set candidateMessages to {candidate_source}"
        if not predicate_conditions:
            candidate_limit = min(max(limit * 5, limit, 50), 200)
            candidate_window_setup = f'''
                set messageCount to count of messages of {mailbox_reference}
                set candidateEndIndex to {candidate_limit}
                if messageCount < candidateEndIndex then set candidateEndIndex to messageCount
            '''
            candidate_assignment = f'''
                if candidateEndIndex > 0 then
                    set candidateMessages to {candidate_source}
                else
                    set candidateMessages to {{}}
                end if
            '''

        return f'''
        tell application "Mail"
            set emailRecords to {{}}
            {candidate_window_setup}
            {candidate_assignment}
            
            repeat with aMessage in candidateMessages
                try
                    {post_filter_check}
                        {self._email_record_applescript()}
                    end if
                on error errMsg
                    -- Skip messages that can't be processed
                end try
                
                if (count of emailRecords) >= {limit} then
                    exit repeat
                end if
            end repeat
            
            return emailRecords
        end tell
        '''

    def get_email_metadata_script(
        self,
        folder: str,
        limit: int,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> str:
        """Generate bounded metadata-only Mail.app retrieval.

        The candidate set is always a bounded, index-based window of the most
        recent messages (never ``messages ... whose <predicate>``), widened one
        window at a time until ``limit`` matches are collected, a scan cap is
        hit, or the mailbox is exhausted. Every filter (date, sender, subject,
        read, flagged) is applied as a per-message post-filter inside the loop,
        so a large mailbox is never scanned in full by a Mail-side predicate -
        this is the fix for the whole-mailbox timeout (Bug 2).
        """
        mailbox_reference = self._mailbox_reference(folder)
        metadata_criteria = self._metadata_criteria(search_criteria)
        post_filter_conditions = self._build_post_filter_conditions(
            metadata_criteria,
            folder,
            include_metadata_filters=True,
        )
        post_filter_check = f"if {post_filter_conditions} then" if post_filter_conditions else "if true then"
        window_size = self._metadata_window_size(limit)
        scan_cap = self._metadata_scan_cap(limit)

        return f'''
        tell application "Mail"
            set emailRecords to {{}}
            set scannedCount to 0
            set skippedCount to 0
            set messageCount to count of messages of {mailbox_reference}
            set windowSize to {window_size}
            set scanCap to {scan_cap}
            set candidateScope to "window_size=" & windowSize & "; scan_cap=" & scanCap
            set windowStart to 1
            set reachedLimit to false
            set stoppedAtCap to false

            repeat while windowStart <= messageCount
                set windowEnd to windowStart + windowSize - 1
                if windowEnd > messageCount then set windowEnd to messageCount
                set candidateMessages to messages windowStart thru windowEnd of {mailbox_reference}

                repeat with aMessage in candidateMessages
                    set scannedCount to scannedCount + 1
                    try
                        {post_filter_check}
                            {self._email_metadata_record_text_applescript()}
                        end if
                    on error errMsg
                        set skippedCount to skippedCount + 1
                    end try

                    if (count of emailRecords) >= {limit} then
                        set reachedLimit to true
                        exit repeat
                    end if
                end repeat

                if reachedLimit then exit repeat
                if scannedCount >= scanCap then
                    set stoppedAtCap to true
                    exit repeat
                end if
                set windowStart to windowEnd + 1
            end repeat

            if reachedLimit then
                set coverageComplete to false
                set coverageReason to "result_limit_reached"
            else if stoppedAtCap then
                set coverageComplete to false
                set coverageReason to "scan_cap_reached"
            else
                set coverageComplete to true
                set coverageReason to "checked_entire_mailbox"
            end if

            set coverageLine to "BASIL_MAIL_METADATA_COVERAGE: folder={self._escape(folder)}; limit={limit}; " & candidateScope & "; mailbox_count=" & messageCount & "; scanned=" & scannedCount & "; returned=" & (count of emailRecords) & "; skipped=" & skippedCount & "; coverage_complete=" & coverageComplete & "; coverage_reason=" & coverageReason
            set previousTextItemDelimiters to AppleScript's text item delimiters
            set AppleScript's text item delimiters to return
            set emailText to emailRecords as text
            set AppleScript's text item delimiters to previousTextItemDelimiters

            if emailText is "" then
                return coverageLine
            end if
            return coverageLine & return & emailText
        end tell
        '''

    def _metadata_window_size(self, limit: int) -> int:
        """Messages pulled per index window before post-filtering (never a whose scan)."""
        return min(max(limit * 2, 25), 100)

    def _metadata_scan_cap(self, limit: int) -> int:
        """Hard ceiling on total messages scanned across all widened windows."""
        return min(max(limit * 10, 250), 1000)

    def expand_email_details_script(
        self,
        folder: str,
        email_ids: list[str],
        excerpt_chars: int = 4000,
    ) -> str:
        """Generate a bounded Mail.app content-expansion script."""
        mailbox_reference = self._mailbox_reference(folder)
        id_list = ", ".join([f'"{self._escape(email_id)}"' for email_id in email_ids])
        excerpt_chars = min(max(int(excerpt_chars or 4000), 1), 20000)

        return f'''
        tell application "Mail"
            set emailRecords to {{}}
            set targetIds to {{{id_list}}}

            repeat with targetId in targetIds
                try
                    set aMessage to first message of {mailbox_reference} whose id is (targetId as string)
                    set fullContent to content of aMessage as string
                    if (length of fullContent) > {excerpt_chars} then
                        set fullContent to text 1 thru {excerpt_chars} of fullContent
                    end if
                    set recipientAddress to ""
                    try
                        set recipientAddress to address of first to recipient of aMessage as string
                    on error
                        try
                            set recipientAddress to name of first to recipient of aMessage as string
                        on error
                            set recipientAddress to ""
                        end try
                    end try
                    set emailRecord to {{¬
                        email_id:(id of aMessage as string), ¬
                        subject:(subject of aMessage as string), ¬
                        sender:(sender of aMessage as string), ¬
                        recipient:recipientAddress, ¬
                        content:fullContent, ¬
                        date_sent:(date sent of aMessage as string), ¬
                        is_read:(read status of aMessage as string), ¬
                        is_flagged:(flagged status of aMessage as string), ¬
                        message_id:(message id of aMessage as string)}}
                    set end of emailRecords to emailRecord
                on error errMsg
                    -- Skip ids that can't be found or expanded
                end try
            end repeat

            return emailRecords
        end tell
        '''

    ACCOUNT_FOLDER_SEPARATOR = " / "

    def _split_account_folder(self, folder: str) -> tuple[Optional[str], str]:
        """Split an account-qualified folder token into (account, mailbox).

        Enumeration emits per-account mailboxes as "<Account> / <Mailbox>" using
        ACCOUNT_FOLDER_SEPARATOR. A token without the separator is a plain mailbox
        (or the unified "inbox" keyword) and returns account None.
        """
        sep = self.ACCOUNT_FOLDER_SEPARATOR
        if sep in folder:
            account, _, mailbox = folder.partition(sep)
            account = account.strip()
            mailbox = mailbox.strip()
            if account and mailbox:
                return account, mailbox
        return None, folder

    def _mailbox_reference(self, folder: str) -> str:
        account, mailbox = self._split_account_folder(folder)
        if account is not None:
            return f'mailbox "{self._escape(mailbox)}" of account "{self._escape(account)}"'
        if mailbox.lower() == "inbox":
            return "inbox"
        return f'mailbox "{self._escape(mailbox)}"'

    def _metadata_criteria(
        self,
        search_criteria: Optional[EmailSearchCriteria],
    ) -> Optional[EmailSearchCriteria]:
        if not search_criteria or not search_criteria.body_contains:
            return search_criteria
        return EmailSearchCriteria(
            sender=search_criteria.sender,
            subject_contains=search_criteria.subject_contains,
            date_from=search_criteria.date_from,
            date_to=search_criteria.date_to,
            is_read=search_criteria.is_read,
            is_flagged=search_criteria.is_flagged,
            folder=search_criteria.folder,
            has_attachments=search_criteria.has_attachments,
        )

    def _mail_date_property(self, folder: str) -> str:
        """Use sent dates for Sent folders and received dates elsewhere."""
        _, mailbox = self._split_account_folder(folder)
        return "date sent" if mailbox.lower() in {"sent", "sent messages", "sent items"} else "date received"

    def _format_mail_date(self, value, end_of_day: bool = False) -> str:
        if end_of_day:
            return value.strftime("%A, %B %d, %Y at 11:59:59 PM")
        return value.strftime("%A, %B %d, %Y at 12:00:00 AM")

    def _build_mail_predicate_conditions(
        self,
        search_criteria: Optional[EmailSearchCriteria],
        folder: str,
    ) -> list[str]:
        """Build cheap Mail-side predicates before message iteration."""
        if not search_criteria:
            return []

        conditions = []
        date_property = self._mail_date_property(folder)
        if search_criteria.date_from:
            date_from = self._format_mail_date(search_criteria.date_from)
            conditions.append(f'({date_property} >= date "{date_from}")')
        if search_criteria.date_to:
            date_to = self._format_mail_date(search_criteria.date_to, end_of_day=True)
            conditions.append(f'({date_property} <= date "{date_to}")')
        if search_criteria.sender:
            conditions.append(f'(sender contains "{self._escape(search_criteria.sender)}")')
        if search_criteria.subject_contains:
            conditions.append(f'(subject contains "{self._escape(search_criteria.subject_contains)}")')
        if search_criteria.is_read is not None:
            conditions.append(f'(read status is {"true" if search_criteria.is_read else "false"})')
        if search_criteria.is_flagged is not None:
            conditions.append(f'(flagged status is {"true" if search_criteria.is_flagged else "false"})')
        return conditions

    def _build_post_filter_conditions(
        self,
        search_criteria: Optional[EmailSearchCriteria],
        folder: str = "inbox",
        include_metadata_filters: bool = False,
    ) -> str:
        """Build conditions that cannot safely define the candidate set."""
        if not search_criteria:
            return ""

        conditions = []
        if include_metadata_filters:
            date_property = self._mail_date_property(folder)
            if search_criteria.date_from:
                date_from = self._format_mail_date(search_criteria.date_from)
                conditions.append(f'(({date_property} of aMessage) >= date "{date_from}")')
            if search_criteria.date_to:
                date_to = self._format_mail_date(search_criteria.date_to, end_of_day=True)
                conditions.append(f'(({date_property} of aMessage) <= date "{date_to}")')
            if search_criteria.sender:
                conditions.append(f'((sender of aMessage) contains "{self._escape(search_criteria.sender)}")')
            if search_criteria.subject_contains:
                conditions.append(f'((subject of aMessage) contains "{self._escape(search_criteria.subject_contains)}")')
            if search_criteria.is_read is not None:
                conditions.append(f'((read status of aMessage) is {"true" if search_criteria.is_read else "false"})')
            if search_criteria.is_flagged is not None:
                conditions.append(f'((flagged status of aMessage) is {"true" if search_criteria.is_flagged else "false"})')
        if search_criteria.body_contains:
            conditions.append(f'(content of aMessage as string) contains "{self._escape(search_criteria.body_contains)}"')
        if search_criteria.has_attachments is not None:
            conditions.append(
                "(count of mail attachments of aMessage) > 0"
                if search_criteria.has_attachments
                else "(count of mail attachments of aMessage) is 0"
            )
        return " and ".join(conditions)
