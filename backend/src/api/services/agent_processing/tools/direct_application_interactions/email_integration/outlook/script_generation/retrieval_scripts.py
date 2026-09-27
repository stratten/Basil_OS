"""Outlook AppleScript retrieval script generation."""

import logging
from typing import Optional

from ...email_models import EmailSearchCriteria
from .query_fragments import OutlookQueryFragments
from .record_templates import OutlookRecordTemplates

logger = logging.getLogger(__name__)


class OutlookRetrievalScripts:
    """Generate Outlook email retrieval and metadata AppleScript."""

    def __init__(self, discovery, escape, records: OutlookRecordTemplates, fragments: OutlookQueryFragments):
        self.discovery = discovery
        self._escape = escape
        self.records = records
        self.fragments = fragments

    @property
    def discovered_accounts(self):
        return self.discovery.discovered_accounts

    def resolve_folder_reference_script(self, folder: str) -> tuple[str, str]:
        account_context = None
        actual_folder = "inbox"

        if folder and folder.lower() != "inbox":
            account_context = folder.lower()
            actual_folder = "inbox"

        if self.discovered_accounts:
            folder_reference = self.discovery.get_folder_reference(actual_folder, self.discovered_accounts, account_context)
            if folder_reference.isdigit():
                return f"item {folder_reference} of every folder", actual_folder
            return folder_reference, actual_folder

        return "inbox", actual_folder

    def get_emails_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        """Generate AppleScript to get emails from Outlook with intelligent account mapping."""
        account_context = None
        actual_folder = "inbox"

        if folder and folder.lower() != "inbox":
            account_context = folder.lower()
            actual_folder = "inbox"
            logger.info(f"🎯 Account-qualified request: '{account_context}' inbox")

        if self.discovered_accounts:
            folder_reference = self.discovery.get_folder_reference(actual_folder, self.discovered_accounts, account_context)
            logger.info(f"📧 Using intelligent mapping: '{folder}' -> folder {folder_reference}")

            if folder_reference.isdigit():
                folder_applescript = f"item {folder_reference} of every folder"
            else:
                folder_applescript = folder_reference
        else:
            logger.warning(f"⚠️ No discovered accounts available, using discovery-based script for '{folder}'")
            return self.generate_discovery_and_retrieval_script(folder, limit, search_criteria)

        candidate_setup = self.fragments.outlook_candidate_setup(search_criteria, actual_folder, limit)
        search_filters = self.fragments.build_outlook_search_filters(search_criteria)

        return f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            set foundCount to 0
            set scannedCount to 0
            set skippedCount to 0
            set coverageComplete to true
            set coverageReason to "checked_candidate_set"
            set selectedFolderIndex to "mapped"
            set selectedFolderName to "mapped"
            try
                set targetFolder to {folder_applescript}
                try
                    set selectedFolderName to name of targetFolder
                end try
                {candidate_setup}

                repeat with aMessage in candidateMessages
                    try
                        set scannedCount to scannedCount + 1
                        if foundCount < {limit} then
                            set includeMessage to true

                            {search_filters}

                            if includeMessage then
                                {self.records.detailed_email_record()}
                                set foundCount to foundCount + 1
                            end if
                        end if
                    on error emailErr
                        set end of emailList to "ERROR_PROCESSING_EMAIL|" & emailErr & "||||"
                    end try
                end repeat

            on error mainErr
                return "MAIN_ERROR: " & mainErr
            end try

            return emailList
        end tell
        '''

    def get_email_metadata_script(
        self,
        folder: str,
        limit: int,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> str:
        """Generate metadata-first Outlook retrieval for cheap triage."""
        if not self.discovered_accounts:
            return self.generate_discovery_and_metadata_script(folder, limit, search_criteria)

        folder_applescript, actual_folder = self.resolve_folder_reference_script(folder)
        candidate_setup = self.fragments.outlook_candidate_setup(search_criteria, actual_folder, limit)
        search_filters = self.fragments.build_outlook_search_filters(search_criteria, include_body_filter=False)

        return f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            set foundCount to 0
            set scannedCount to 0
            set skippedCount to 0
            set coverageComplete to true
            set coverageReason to "checked_candidate_set"
            set selectedFolderIndex to "mapped"
            set selectedFolderName to "mapped"
            try
                set targetFolder to {folder_applescript}
                try
                    set selectedFolderName to name of targetFolder
                end try
                {candidate_setup}

                repeat with aMessage in candidateMessages
                    try
                        set scannedCount to scannedCount + 1
                        if foundCount < {limit} then
                            set includeMessage to true

                            {search_filters}

                            if includeMessage then
                                {self.records.metadata_email_record()}
                                set foundCount to foundCount + 1
                            end if
                        end if
                    on error emailErr
                        set skippedCount to skippedCount + 1
                        set end of emailList to "ERROR_PROCESSING_EMAIL|" & emailErr & "||||"
                    end try
                    if foundCount >= {limit} then
                        set coverageComplete to false
                        set coverageReason to "result_limit_reached"
                        exit repeat
                    end if
                end repeat
            on error mainErr
                return "MAIN_ERROR: " & mainErr
            end try

            {self.fragments.outlook_coverage_line_applescript(folder, limit)}
        end tell
        '''

    def expand_email_details_script(self, folder: str, email_ids: list[str], excerpt_chars: int = 4000) -> str:
        """Generate selected-id Outlook content expansion with bounded excerpts."""
        folder_applescript, _actual_folder = self.resolve_folder_reference_script(folder)
        id_list = ", ".join([f'"{self._escape(email_id)}"' for email_id in email_ids])
        excerpt_chars = min(max(int(excerpt_chars or 4000), 1), 20000)

        return f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            set targetIds to {{{id_list}}}
            try
                set targetFolder to {folder_applescript}
                repeat with targetId in targetIds
                    try
                        set matchedMessages to messages of targetFolder whose id is (targetId as string)
                        if (count of matchedMessages) > 0 then
                            set aMessage to item 1 of matchedMessages
                            set fullContent to content of aMessage as string
                            if (length of fullContent) > {excerpt_chars} then
                                set fullContent to text 1 thru {excerpt_chars} of fullContent
                            end if
                            set emailData to ""
                            set emailData to emailData & (id of aMessage as string)
                            set emailData to emailData & "|||"
                            set emailData to emailData & (subject of aMessage)
                            set emailData to emailData & "|||"
                            try
                                set senderObj to sender of aMessage
                                set senderName to name of senderObj
                                set senderAddr to address of senderObj
                                if senderName is not missing value and senderName is not "" then
                                    set emailData to emailData & senderName & " <" & senderAddr & ">"
                                else
                                    set emailData to emailData & senderAddr
                                end if
                            on error
                                set emailData to emailData & "Unknown Sender"
                            end try
                            set emailData to emailData & "|||"
                            set emailData to emailData & (time sent of aMessage as string)
                            set emailData to emailData & "|||"
                            set emailData to emailData & fullContent
                            set emailData to emailData & "|||"
                            set emailData to emailData & ((is read of aMessage) as string)
                            set emailData to emailData & "|||||||||"
                            try
                                set emailData to emailData & (conversation id of aMessage as string)
                            on error
                                set emailData to emailData & ""
                            end try
                            set end of emailList to emailData
                        end if
                    on error emailErr
                        set end of emailList to "ERROR_PROCESSING_EMAIL|" & emailErr & "||||"
                    end try
                end repeat
            on error mainErr
                return "MAIN_ERROR: " & mainErr
            end try

            return emailList
        end tell
        '''

    def get_emails_with_discovery_script(
        self,
        folder: str,
        limit: int,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> str:
        """Generate AppleScript that does account discovery AND email retrieval in one script."""
        folder_lower = folder.lower()

        return f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            set allFolders to every folder

            -- Find the best inbox for this request
            set targetFolder to missing value
            set bestMatchScore to 0
            set selectedFolderIndex to "unknown"
            set selectedFolderName to "unknown"

            repeat with i from 1 to (count of allFolders)
                try
                    set aFolder to item i of allFolders
                    set folderName to name of aFolder

                    -- Check if this is an inbox
                    if folderName is "Inbox" or folderName is "INBOX" or folderName contains "Inbox" then
                        set messageCount to count of messages of aFolder
                        if messageCount > 0 then
                            set matchScore to 0

                            -- Try to match based on account info
                            try
                                set folderAccount to account of aFolder
                                set accountEmail to email address of folderAccount

                                -- Score based on user request matching account email
                                if "{folder_lower}" contains "@" then
                                    if accountEmail contains "{folder_lower}" then
                                        set matchScore to 100
                                    end if
                                else if "{folder_lower}" is "inbox" or "{folder_lower}" is "main" or "{folder_lower}" is "primary" then
                                    -- For generic requests, prefer inbox with most messages
                                    set matchScore to messageCount / 100
                                else
                                    -- For other requests, try to match account name or domain
                                    if accountEmail contains "{folder_lower}" then
                                        set matchScore to 50
                                    end if
                                end if
                            on error
                                -- No account info, use message count as fallback
                                if "{folder_lower}" is "inbox" or "{folder_lower}" is "main" or "{folder_lower}" is "primary" then
                                    set matchScore to messageCount / 100
                                end if
                            end try

                            if matchScore > bestMatchScore then
                                set bestMatchScore to matchScore
                                set targetFolder to aFolder
                                set selectedFolderIndex to i as string
                                set selectedFolderName to folderName
                            end if
                        end if
                    end if
                on error
                    -- Skip problematic folders
                end try
            end repeat

            -- If we found a target folder, get emails from it
            if targetFolder is not missing value then
                {self.fragments.outlook_candidate_setup(search_criteria, folder, limit)}
                set foundCount to 0

                repeat with aMessage in candidateMessages
                    if foundCount < {limit} then
                        try
                            set includeMessage to true

                            {self.fragments.build_outlook_search_filters(search_criteria)}

                            if includeMessage then
                                {self.records.simple_email_record()}
                                set foundCount to foundCount + 1
                            end if
                        on error
                            -- Skip messages that can't be read
                        end try
                    end if
                end repeat
            end if

            set AppleScript's text item delimiters to return
            set emailText to emailList as text
            set AppleScript's text item delimiters to ""

            return emailText
        end tell
        '''

    def generate_discovery_and_retrieval_script(
        self,
        folder: str,
        limit: int,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> str:
        """Generate a fallback script that discovers accounts and retrieves emails."""
        logger.info(f"🔄 Generating discovery-and-retrieval script for folder '{folder}', limit {limit}")
        search_filters = self.fragments.build_outlook_search_filters(search_criteria)

        script = f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            try
                {self.fragments.fallback_inbox_selection_applescript(folder)}
                if targetFolder is missing value then
                    return ""
                end if

                {self.fragments.outlook_candidate_setup(search_criteria, folder, limit)}
                set foundCount to 0

                repeat with aMessage in candidateMessages
                    if foundCount < {limit} then
                        try
                            set includeMessage to true
                            {search_filters}
                            if includeMessage then
                                {self.records.simple_email_record()}
                                set foundCount to foundCount + 1
                            end if
                        on error emailError
                            -- Skip problematic emails
                        end try
                    end if
                end repeat

                set previousTextItemDelimiters to AppleScript's text item delimiters
                set AppleScript's text item delimiters to return
                set emailText to emailList as text
                set AppleScript's text item delimiters to previousTextItemDelimiters
                return emailText
            on error scriptError
                return "Error: " & scriptError
            end try
        end tell
        '''

        return script

    def generate_discovery_and_metadata_script(
        self,
        folder: str,
        limit: int,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> str:
        """Generate a fallback metadata-only script when account discovery is unavailable."""
        logger.info(f"🔄 Generating discovery-and-metadata script for folder '{folder}', limit {limit}")
        search_filters = self.fragments.build_outlook_search_filters(search_criteria, include_body_filter=False)

        return f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            set foundCount to 0
            set scannedCount to 0
            set skippedCount to 0
            set coverageComplete to true
            set coverageReason to "checked_candidate_set"
            try
                {self.fragments.fallback_inbox_selection_applescript(folder)}
                if targetFolder is missing value then
                    set coverageComplete to false
                    set coverageReason to "no_real_inbox_found"
                    set messageCount to 0
                    set candidateCount to 0
                    {self.fragments.outlook_coverage_line_applescript(folder, limit)}
                end if

                {self.fragments.outlook_candidate_setup(search_criteria, folder, limit)}
                if discoveredInboxCount > 1 then
                    set coverageComplete to false
                    set coverageReason to "selected_best_inbox_from_multiple"
                end if

                repeat with aMessage in candidateMessages
                    try
                        set scannedCount to scannedCount + 1
                        if foundCount < {limit} then
                            set includeMessage to true
                            {search_filters}
                            if includeMessage then
                                {self.records.metadata_email_record()}
                                set foundCount to foundCount + 1
                            end if
                        end if
                    on error emailError
                        set skippedCount to skippedCount + 1
                    end try
                    if foundCount >= {limit} then
                        set coverageComplete to false
                        set coverageReason to "result_limit_reached"
                        exit repeat
                    end if
                end repeat

                {self.fragments.outlook_coverage_line_applescript(folder, limit)}
            on error scriptError
                return "Error: " & scriptError
            end try
        end tell
        '''
