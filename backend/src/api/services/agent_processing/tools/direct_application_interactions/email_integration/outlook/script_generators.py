"""
Outlook AppleScript Generators

Generates all AppleScript code for Outlook email operations:
email retrieval, composition, reply, search, organization, and folder management.
"""

import logging
from typing import Optional

from ..email_models import EmailRequest, EmailOperation, EmailSearchCriteria
from .parsing import OutlookEmailParser
from .script_generation.composition_scripts import OutlookCompositionScripts
from .script_generation.organization_scripts import OutlookOrganizationScripts
from .script_generation.query_fragments import OutlookQueryFragments
from .script_generation.record_templates import OutlookRecordTemplates
from .script_generation.retrieval_scripts import OutlookRetrievalScripts

logger = logging.getLogger(__name__)


class OutlookScriptGenerator:
    """Generates AppleScript code for all Outlook email operations."""

    def __init__(self, discovery):
        """
        Args:
            discovery: OutlookAccountDiscovery instance for account/folder resolution
        """
        self.discovery = discovery
        self.composition = OutlookCompositionScripts(self._escape)
        self.fragments = OutlookQueryFragments(self._escape)
        self.records = OutlookRecordTemplates()
        self.organization = OutlookOrganizationScripts(self.discovery, self._escape, self.records, self.fragments)
        self.retrieval = OutlookRetrievalScripts(self.discovery, self._escape, self.records, self.fragments)

    @property
    def discovered_accounts(self):
        return self.discovery.discovered_accounts

    def _escape(self, text: str) -> str:
        return OutlookEmailParser.escape_applescript_string(text)

    def read_only_validation_probe_script(self) -> str:
        """Generate a read-only Outlook probe for local AppleScript syntax validation."""
        return '''
        tell application "Microsoft Outlook"
            set probeOutput to {}
            try
                set targetFolder to inbox
                set messageCount to count of messages of targetFolder
                set end of probeOutput to "folder_count=" & (messageCount as string)
                try
                    set subjectMatches to messages of targetFolder whose subject contains "x"
                    set end of probeOutput to "whose_subject_count=" & ((count of subjectMatches) as string)
                on error errMsg
                    set end of probeOutput to "whose_subject_error=" & errMsg
                end try
                try
                    set dateMatches to messages of targetFolder whose time received > ((current date) - (30 * days))
                    set end of probeOutput to "whose_time_received_count=" & ((count of dateMatches) as string)
                on error errMsg
                    set end of probeOutput to "whose_time_received_error=" & errMsg
                end try
            on error errMsg
                set end of probeOutput to "main_error=" & errMsg
            end try
            set AppleScript's text item delimiters to return
            set probeText to probeOutput as text
            set AppleScript's text item delimiters to ""
            return probeText
        end tell
        '''

    def _outlook_date_property(self, folder: str) -> str:
        return self.fragments.outlook_date_property(folder)

    def _format_outlook_date(self, value, end_of_day: bool = False) -> str:
        return self.fragments.format_outlook_date(value, end_of_day)

    def _build_outlook_predicate_conditions(self, criteria: Optional[EmailSearchCriteria], folder: str) -> list[str]:
        """Build locally validated Outlook `whose` predicates for cheap candidate bounds."""
        return self.fragments.build_outlook_predicate_conditions(criteria, folder)

    def _candidate_window_size(self, limit: int) -> int:
        return self.fragments.candidate_window_size(limit)

    def _outlook_candidate_setup(self, criteria: Optional[EmailSearchCriteria], folder: str, limit: int) -> str:
        """Create candidateMessages without relying on whole-folder materialization where possible."""
        return self.fragments.outlook_candidate_setup(criteria, folder, limit)

    def _outlook_coverage_line_applescript(self, requested_folder: str, limit: int) -> str:
        """Build a machine-readable coverage line for Outlook metadata retrieval."""
        return self.fragments.outlook_coverage_line_applescript(requested_folder, limit)

    def _fallback_inbox_selection_applescript(self, folder: str) -> str:
        """Select the best real Outlook inbox without relying on Outlook's global inbox alias."""
        return self.fragments.fallback_inbox_selection_applescript(folder)

    def _email_record_detailed_applescript(self) -> str:
        """Returns detailed AppleScript snippet for building an Outlook email record with all fields."""
        return self.records.detailed_email_record()

    def _email_record_simple_applescript(self) -> str:
        """Returns simplified AppleScript snippet using ||| delimiters matching the enhanced parser format."""
        return self.records.simple_email_record()

    def _email_record_metadata_applescript(self) -> str:
        """Build an Outlook metadata record without reading message body content."""
        return self.records.metadata_email_record()

    def _resolve_folder_reference_script(self, folder: str) -> tuple[str, str]:
        return self.retrieval.resolve_folder_reference_script(folder)

    def get_emails_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        """Generate AppleScript to get emails from Outlook with intelligent account mapping."""
        return self.retrieval.get_emails_script(folder, limit, search_criteria)

    def get_email_metadata_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        """Generate metadata-first Outlook retrieval for cheap triage."""
        return self.retrieval.get_email_metadata_script(folder, limit, search_criteria)

    def expand_email_details_script(self, folder: str, email_ids: list[str], excerpt_chars: int = 4000) -> str:
        """Generate selected-id Outlook content expansion with bounded excerpts."""
        return self.retrieval.expand_email_details_script(folder, email_ids, excerpt_chars)

    def _get_emails_with_discovery_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        """Generate AppleScript that does account discovery AND email retrieval in one script."""
        return self.retrieval.get_emails_with_discovery_script(folder, limit, search_criteria)

    def compose_email_script(self, email_request: EmailRequest, draft_only: bool = True) -> str:
        """Generate AppleScript to compose a new email draft in Microsoft Outlook."""
        return self.composition.compose_email_script(email_request, draft_only)

    def _recipient_applescript_lines(self, recipients: list[str], recipient_type: str) -> str:
        """Generate Outlook AppleScript recipient creation lines."""
        return self.composition.recipient_applescript_lines(recipients, recipient_type)

    def send_email_script(self, email_request: EmailRequest) -> str:
        """Fail closed: Outlook automation never sends email directly."""
        return self.composition.send_email_script(email_request)

    def reply_to_email_script(self, email_id: str, reply_body: str, reply_all: bool = True, draft_only: bool = True) -> str:
        """
        Generate AppleScript to create a reply draft in Outlook using native reply functionality.
        """
        return self.composition.reply_to_email_script(email_id, reply_body, reply_all, draft_only)

    def organize_emails_script(self, operation: EmailOperation) -> str:
        """Generate AppleScript to organize emails in Outlook."""
        return self.organization.organize_emails_script(operation)

    def search_emails_script(self, criteria: EmailSearchCriteria, limit: int) -> str:
        """Generate AppleScript to search emails in Outlook with criteria."""
        return self.organization.search_emails_script(criteria, limit)

    def _build_outlook_search_filters(self, criteria: EmailSearchCriteria, include_body_filter: bool = True) -> str:
        """Build AppleScript filter conditions for Outlook search."""
        return self.fragments.build_outlook_search_filters(criteria, include_body_filter)

    def get_folders_script(self) -> str:
        """Generate AppleScript to get folders from Outlook."""
        return self.organization.get_folders_script()

    def create_folder_script(self, folder_name: str, parent_folder: Optional[str] = None) -> str:
        """Generate AppleScript to create folder in Outlook."""
        return self.organization.create_folder_script(folder_name, parent_folder)

    def _generate_discovery_and_retrieval_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        """
        Generate a fallback script that discovers accounts and retrieves emails.
        Used when intelligent discovery fails to find accounts.
        """
        return self.retrieval.generate_discovery_and_retrieval_script(folder, limit, search_criteria)

    def _generate_discovery_and_metadata_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        """Generate a fallback metadata-only script when account discovery is unavailable."""
        return self.retrieval.generate_discovery_and_metadata_script(folder, limit, search_criteria)
