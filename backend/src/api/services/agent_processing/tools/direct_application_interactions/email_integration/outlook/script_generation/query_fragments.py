"""Shared Outlook AppleScript query fragments."""

from typing import Callable, Optional

from ...email_models import EmailSearchCriteria


class OutlookQueryFragments:
    """Build reusable Outlook AppleScript query and filtering snippets."""

    def __init__(self, escape: Callable[[str], str]):
        self._escape = escape

    def outlook_date_property(self, folder: str) -> str:
        return "time sent" if folder and folder.lower() in {"sent", "sent items", "sent messages"} else "time received"

    def format_outlook_date(self, value, end_of_day: bool = False) -> str:
        if end_of_day:
            return value.strftime("%A, %B %d, %Y at 11:59:59 PM")
        return value.strftime("%A, %B %d, %Y at 12:00:00 AM")

    def build_outlook_predicate_conditions(self, criteria: Optional[EmailSearchCriteria], folder: str) -> list[str]:
        """Build locally validated Outlook `whose` predicates for cheap candidate bounds."""
        if not criteria:
            return []

        conditions = []
        date_property = self.outlook_date_property(folder)

        if criteria.date_from:
            date_from_str = self.format_outlook_date(criteria.date_from)
            conditions.append(f'({date_property} >= date "{date_from_str}")')

        if criteria.date_to:
            date_to_str = self.format_outlook_date(criteria.date_to, end_of_day=True)
            conditions.append(f'({date_property} <= date "{date_to_str}")')

        if criteria.subject_contains:
            escaped_subject = self._escape(criteria.subject_contains)
            conditions.append(f'(subject contains "{escaped_subject}")')

        return conditions

    def candidate_window_size(self, limit: int) -> int:
        return min(max(limit * 5, limit, 50), 200)

    def outlook_candidate_setup(self, criteria: Optional[EmailSearchCriteria], folder: str, limit: int) -> str:
        """Create candidateMessages without relying on whole-folder materialization where possible."""
        predicate_conditions = self.build_outlook_predicate_conditions(criteria, folder)
        if predicate_conditions:
            predicate_clause = " and ".join(predicate_conditions)
            return f'''
                set messageCount to count of messages of targetFolder
                set candidateMessages to messages of targetFolder whose {predicate_clause}
                set candidateCount to count of candidateMessages
            '''

        candidate_limit = self.candidate_window_size(limit)
        return f'''
                set messageCount to count of messages of targetFolder
                set candidateEndIndex to {candidate_limit}
                if messageCount < candidateEndIndex then set candidateEndIndex to messageCount
                if candidateEndIndex > 0 then
                    set candidateMessages to messages 1 thru candidateEndIndex of targetFolder
                else
                    set candidateMessages to {{}}
                end if
                set candidateCount to count of candidateMessages
        '''

    def outlook_coverage_line_applescript(self, requested_folder: str, limit: int) -> str:
        """Build a machine-readable coverage line for Outlook metadata retrieval."""
        escaped_folder = self._escape(requested_folder or "inbox")
        return f'''set coverageLine to "BASIL_OUTLOOK_METADATA_COVERAGE: folder={escaped_folder}; limit={limit}; selected_folder_index=" & selectedFolderIndex & "; selected_folder_name=" & selectedFolderName & "; mailbox_count=" & messageCount & "; candidate_count=" & candidateCount & "; scanned=" & scannedCount & "; returned=" & foundCount & "; skipped=" & skippedCount & "; coverage_complete=" & coverageComplete & "; coverage_reason=" & coverageReason
            set previousTextItemDelimiters to AppleScript's text item delimiters
            set AppleScript's text item delimiters to return
            set emailText to emailList as text
            set AppleScript's text item delimiters to previousTextItemDelimiters
            if emailText is "" then
                return coverageLine
            end if
            return coverageLine & return & emailText'''

    def fallback_inbox_selection_applescript(self, folder: str) -> str:
        """Select the best real Outlook inbox without relying on Outlook's global inbox alias."""
        folder_lower = self._escape((folder or "inbox").lower())
        return f'''
                set selectedFolderIndex to "unknown"
                set selectedFolderName to "unknown"
                set discoveredInboxCount to 0
                set bestMessageCount to -1
                set targetFolder to missing value
                set allFolders to every folder
                repeat with i from 1 to (count of allFolders)
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        set isInboxCandidate to false
                        if folderName is "Inbox" or folderName is "INBOX" or folderName contains "Inbox" then
                            set isInboxCandidate to true
                        end if
                        if isInboxCandidate then
                            set folderMessageCount to count of messages of aFolder
                            set discoveredInboxCount to discoveredInboxCount + 1
                            if "{folder_lower}" is "inbox" or "{folder_lower}" is "main" or "{folder_lower}" is "primary" then
                                if folderMessageCount > bestMessageCount then
                                    set bestMessageCount to folderMessageCount
                                    set targetFolder to aFolder
                                    set selectedFolderIndex to i as string
                                    set selectedFolderName to folderName
                                end if
                            else if folderName contains "{self._escape(folder or '')}" or folderName is "{self._escape(folder or '')}" then
                                set targetFolder to aFolder
                                set selectedFolderIndex to i as string
                                set selectedFolderName to folderName
                                exit repeat
                            end if
                        end if
                    on error
                        -- Skip folders that cannot be inspected.
                    end try
                end repeat
        '''

    def build_outlook_search_filters(self, criteria: EmailSearchCriteria, include_body_filter: bool = True) -> str:
        """Build AppleScript filter conditions for Outlook search."""
        if not criteria:
            return ""

        filters = []

        def add_filter(condition: str):
            filters.append(f'''
                    if includeMessage then
                        if {condition} then
                            set includeMessage to false
                        end if
                    end if''')

        if criteria.sender:
            escaped_sender = self._escape(criteria.sender)
            filters.append(f'''
                    if includeMessage then
                        try
                            set senderObj to sender of aMessage
                            set senderName to name of senderObj
                            set senderAddr to ""
                            try
                                set senderAddr to address of senderObj
                            end try
                            if senderName does not contain "{escaped_sender}" and senderAddr does not contain "{escaped_sender}" then
                                set includeMessage to false
                            end if
                        on error
                            set includeMessage to false
                        end try
                    end if''')

        if criteria.subject_contains:
            escaped_subject = self._escape(criteria.subject_contains)
            add_filter(f'(subject of aMessage as string) does not contain "{escaped_subject}"')

        if include_body_filter and criteria.body_contains:
            escaped_body = self._escape(criteria.body_contains)
            add_filter(f'(plain text content of aMessage as string) does not contain "{escaped_body}"')

        if criteria.is_read is not None:
            read_value = "true" if criteria.is_read else "false"
            add_filter(f'((is read of aMessage) as string) is not "{read_value}"')

        if criteria.is_flagged is not None:
            if criteria.is_flagged:
                add_filter('(todo flag of aMessage as string) is "not flagged"')
            else:
                add_filter('(todo flag of aMessage as string) is not "not flagged"')

        return '\n'.join(filters)
