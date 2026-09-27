"""Outlook AppleScript organization, search, and folder script generation."""

import logging
from typing import Callable

from ...email_models import EmailOperation, EmailSearchCriteria
from .query_fragments import OutlookQueryFragments
from .record_templates import OutlookRecordTemplates

logger = logging.getLogger(__name__)


class OutlookOrganizationScripts:
    """Generate Outlook organization, search, and folder AppleScript."""

    def __init__(self, discovery, escape: Callable[[str], str], records: OutlookRecordTemplates, fragments: OutlookQueryFragments):
        self.discovery = discovery
        self._escape = escape
        self.records = records
        self.fragments = fragments

    @property
    def discovered_accounts(self):
        return self.discovery.discovered_accounts

    def organize_emails_script(self, operation: EmailOperation) -> str:
        """Generate AppleScript to organize emails in Outlook."""
        email_ids = ", ".join([f'"{email_id}"' for email_id in operation.email_ids])

        operation_actions = {
            "move": f'move theMessage to folder "{operation.target_folder}"',
            "delete": 'delete theMessage',
            "mark_read": 'set read of theMessage to true',
            "flag": 'set todo flag of theMessage to not completed'
        }

        action = operation_actions.get(operation.operation)
        if not action:
            logger.warning(f"⚠️ Unsupported Outlook operation: {operation.operation}")
            return '''
            tell application "Microsoft Outlook"
                -- Unsupported operation
                return "Operation not supported"
            end tell
            '''

        return f'''
        tell application "Microsoft Outlook"
            set messageIds to {{{email_ids}}}

            repeat with messageId in messageIds
                try
                    set theMessage to (first message whose id is messageId)
                    {action}
                on error
                    -- Skip messages that can't be processed
                end try
            end repeat
        end tell
        '''

    def search_emails_script(self, criteria: EmailSearchCriteria, limit: int) -> str:
        """Generate AppleScript to search emails in Outlook with criteria."""
        requested_folder = criteria.folder or "inbox"
        search_filters = self.fragments.build_outlook_search_filters(criteria)
        candidate_setup = self.fragments.outlook_candidate_setup(criteria, requested_folder, limit)

        if self.discovered_accounts:
            folder_reference = self.discovery.get_folder_reference(requested_folder, self.discovered_accounts)
            folder_selection = f'''
            -- Use discovered account/folder mapping when available.
            try
                set targetFolder to {folder_reference}
                {candidate_setup}
            on error
                return ""
            end try'''
        else:
            folder_selection = f'''
            -- Discovery has not been populated, so avoid Outlook's often-empty global inbox alias.
            try
                {self.fragments.fallback_inbox_selection_applescript(requested_folder)}
                if targetFolder is missing value then
                    return ""
                end if
                {candidate_setup}
            on error
                return ""
            end try'''

        return f'''
        tell application "Microsoft Outlook"
            set emailList to {{}}
            set foundCount to 0

            {folder_selection}

            repeat with aMessage in candidateMessages
                if foundCount < {limit} then
                    set includeMessage to true

                    {search_filters}

                    if includeMessage then
                        try
                            {self.records.simple_email_record()}
                            set foundCount to foundCount + 1
                        on error
                            -- Skip messages that can't be read
                        end try
                    end if
                end if
            end repeat

            set AppleScript's text item delimiters to return
            set emailText to emailList as text
            set AppleScript's text item delimiters to ""

            return emailText
        end tell
        '''

    def get_folders_script(self) -> str:
        """Generate AppleScript to get folders from Outlook."""
        return '''
        tell application "Microsoft Outlook"
            set folderList to {}
            set allFolders to every folder

            repeat with aFolder in allFolders
                try
                    set folderInfo to (name of aFolder) & " (Index: " & (my getItemIndex(aFolder, allFolders)) & ")"
                    set end of folderList to folderInfo
                on error
                    -- Skip folders that can't be accessed
                    try
                        set end of folderList to "Unknown folder"
                    end try
                end try
            end repeat

            set AppleScript's text item delimiters to ","
            set folderText to folderList as text
            set AppleScript's text item delimiters to ""

            return folderText
        end tell

        on getItemIndex(targetItem, itemList)
            repeat with i from 1 to count of itemList
                if item i of itemList is targetItem then
                    return i
                end if
            end repeat
            return 0
        end getItemIndex
        '''

    def create_folder_script(self, folder_name: str, parent_folder: str | None = None) -> str:
        """Generate AppleScript to create folder in Outlook."""
        escaped_folder_name = self._escape(folder_name)

        if parent_folder:
            escaped_parent = self._escape(parent_folder)
            return f'''
            tell application "Microsoft Outlook"
                try
                    set parentFolder to folder "{escaped_parent}"
                    make new folder at parentFolder with properties {{name:"{escaped_folder_name}"}}
                    return "Folder created successfully"
                on error errMsg
                    return "Error: " & errMsg
                end try
            end tell
            '''

        return f'''
            tell application "Microsoft Outlook"
                try
                    make new folder with properties {{name:"{escaped_folder_name}"}}
                    return "Folder created successfully"
                on error errMsg
                    return "Error: " & errMsg
                end try
            end tell
            '''
