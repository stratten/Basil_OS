"""
Email Retrieval Mixin

Public operations and backend dispatch for email retrieval and search.
Mixed into EmailClientService.
"""

import logging
from typing import TYPE_CHECKING, List, Optional
from datetime import datetime

from .email_models import EmailData, EmailDataList, EmailSearchCriteria, EmailClient
from .email_tool_contracts import normalize_email_search_criteria

if TYPE_CHECKING:
    from .applescript_automation_service import AppleScriptAutomationService

logger = logging.getLogger(__name__)


class EmailRetrievalMixin:
    """Retrieval and search operations for emails."""

    applescript_service: 'AppleScriptAutomationService'

    def _get_client_by_name(self, client_name: Optional[str] = None) -> Optional[EmailClient]: ...

    async def _run_with_email_read_timeout(self, operation):
        """Use a longer AppleScript timeout only for potentially expensive read/search operations."""
        previous_timeout = self.applescript_service.timeout
        read_timeout = getattr(self, "email_read_applescript_timeout", previous_timeout)
        self.applescript_service.timeout = max(previous_timeout, read_timeout)
        try:
            return await operation()
        finally:
            self.applescript_service.timeout = previous_timeout

    async def get_emails(self, folder: str = "inbox", limit: int = 10, 
                        search_criteria: Optional[EmailSearchCriteria] = None,
                        client_name: Optional[str] = None,
                        deduplicate_threads: bool = False,
                        skip_default_filter: bool = False) -> List[EmailData]:
        """
        Get emails from specified folder with optional search criteria.
        
        Args:
            folder: Folder to retrieve emails from (inbox, sent, drafts, etc.)
            limit: Maximum number of emails to retrieve
            search_criteria: Optional search criteria to filter emails
            client_name: Optional specific email client to use (e.g., "Microsoft Outlook")
            deduplicate_threads: If True, return only the most recent email from each thread
            skip_default_filter: Set True to disable 30-day default filter (for "analyze entire inbox" requests)
            
        Returns:
            List of EmailData objects
        """
        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return []
        
        search_criteria = normalize_email_search_criteria(search_criteria)

        if not search_criteria and folder == "inbox" and not skip_default_filter:
            from datetime import timedelta
            logger.info("🛡️ DEFENSIVE FILTER: No date criteria specified, applying 30-day default for performance")
            logger.warning("NOTE: Only showing emails from the last 30 days. Pass skip_default_filter=True to retrieve all emails.")
            search_criteria = EmailSearchCriteria(
                date_from=datetime.now() - timedelta(days=30)
            )
        
        logger.info(f"📧 Getting emails from {folder} via {selected_client.name} (limit: {limit}, deduplicate_threads: {deduplicate_threads}, skip_default_filter: {skip_default_filter})")
        
        try:
            if selected_client.automation_method == "applescript":
                emails = await self._run_with_email_read_timeout(
                    lambda: self._get_emails_via_applescript(selected_client, folder, limit, search_criteria)
                )
            elif selected_client.automation_method == "file_system":
                emails = await self._get_emails_via_filesystem(selected_client, folder, limit, search_criteria)
            else:
                logger.warning(f"⚠️ Reading emails not supported for {selected_client.automation_method}")
                return []
            
            if deduplicate_threads and emails:
                from .email_thread_utils import deduplicate_email_threads
                emails = deduplicate_email_threads(emails)
            
            return emails
                
        except Exception as e:
            logger.error(f"❌ Error getting emails: {e}", exc_info=True)
            raise Exception(f"Email retrieval failed: {str(e)}")

    async def search_emails(self, criteria: EmailSearchCriteria, limit: int = 50, 
                           client_name: Optional[str] = None,
                           deduplicate_threads: bool = False) -> List[EmailData]:
        """
        Search for emails based on specified criteria.
        
        Args:
            criteria: Search criteria
            limit: Maximum number of results to return
            client_name: Optional specific email client to use (e.g., "Microsoft Outlook")
            deduplicate_threads: If True, return only the most recent email from each thread
            
        Returns:
            List of matching EmailData objects
        """
        criteria = normalize_email_search_criteria(criteria)

        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return []
        
        logger.info(f"🔍 Searching emails via {selected_client.name} (deduplicate_threads: {deduplicate_threads})")
        
        try:
            if selected_client.automation_method == "applescript":
                emails = await self._run_with_email_read_timeout(
                    lambda: self._search_emails_via_applescript(criteria, limit, selected_client)
                )
            elif selected_client.automation_method == "file_system":
                emails = await self._search_emails_via_filesystem(criteria, limit)
            else:
                logger.warning(f"⚠️ Email search not supported for {selected_client.automation_method}")
                return []
            
            if deduplicate_threads and emails:
                from .email_thread_utils import deduplicate_email_threads
                emails = deduplicate_email_threads(emails)
            
            return emails
                
        except Exception as e:
            logger.error(f"❌ Error searching emails: {e}", exc_info=True)
            raise Exception(f"Email search failed: {str(e)}")

    async def get_email_metadata(
        self,
        folder: str = "inbox",
        limit: int = 50,
        search_criteria: Optional[EmailSearchCriteria] = None,
        client_name: Optional[str] = None,
        deduplicate_threads: bool = False,
        skip_default_filter: bool = False,
    ) -> List[EmailData]:
        """
        Retrieve metadata-only email records for triage before body expansion.

        This is the preferred first pass for large or unknown-size inbox work.
        Returned records intentionally have empty content; call
        expand_email_details() for selected message ids when body text is needed.
        """
        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return []

        search_criteria = normalize_email_search_criteria(search_criteria)
        if not search_criteria and folder == "inbox" and not skip_default_filter:
            from datetime import timedelta
            search_criteria = EmailSearchCriteria(date_from=datetime.now() - timedelta(days=30))

        if selected_client.automation_method != "applescript":
            logger.warning(f"⚠️ Email metadata is not supported for {selected_client.automation_method}")
            return []

        emails = await self._run_with_email_read_timeout(
            lambda: self.applescript_service.get_email_metadata_via_applescript(
                selected_client.name,
                folder,
                limit,
                search_criteria,
            )
        )

        # Preserve parser coverage metadata (dedup below returns a plain list and would drop
        # it), then re-wrap so the ACTUALLY-serving client identity is observable to callers.
        # This is what lets the probe/adapter loop detect a wrong bind. Additive only:
        # EmailDataList is a list subclass, so list-consuming callers are unaffected.
        coverage_metadata = getattr(emails, "coverage_metadata", {})

        if deduplicate_threads and emails:
            from .email_thread_utils import deduplicate_email_threads
            emails = deduplicate_email_threads(emails)

        result = EmailDataList(emails, coverage_metadata=coverage_metadata)
        result.served_by_client = selected_client.name
        return result

    async def expand_email_details(
        self,
        email_ids: List[str],
        folder: str = "inbox",
        client_name: Optional[str] = None,
        excerpt_chars: int = 4000,
    ) -> List[EmailData]:
        """
        Expand selected email ids into bounded body excerpts or full text.

        Use after get_email_metadata() has narrowed the candidate set. The
        caller controls excerpt_chars to keep context growth explicit.
        """
        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return []

        if not email_ids:
            return []

        if selected_client.automation_method != "applescript":
            logger.warning(f"⚠️ Email expansion is not supported for {selected_client.automation_method}")
            return []

        bounded_ids = [str(email_id).strip() for email_id in email_ids if str(email_id).strip()][:25]
        return await self.applescript_service.expand_email_details_via_applescript(
            selected_client.name,
            bounded_ids,
            folder,
            excerpt_chars,
        )

    async def get_inbox_emails(self, limit: int = 10, filter_read: bool = True) -> List[EmailData]:
        """
        Get inbox emails (backward compatibility method).
        
        Args:
            limit: Maximum number of emails to retrieve
            filter_read: If True, only return read emails; if False, only return unread emails
            
        Returns:
            List of EmailData objects
        """
        search_criteria = EmailSearchCriteria(is_read=filter_read)
        return await self.get_emails(folder="inbox", limit=limit, search_criteria=search_criteria)

    # -- Backend dispatch --

    async def _get_emails_via_applescript(self, selected_client: EmailClient, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> List[EmailData]:
        """Get emails using AppleScript automation."""
        logger.info(f"📧 REQUESTING EMAILS: folder={folder}, limit={limit}, search_criteria={search_criteria}")
        
        has_active_filters = (
            search_criteria and
            any([search_criteria.sender, search_criteria.subject_contains,
                 search_criteria.body_contains, search_criteria.date_from, search_criteria.date_to,
                 search_criteria.is_read is not None,
                 search_criteria.is_flagged is not None, search_criteria.has_attachments is not None])
        )
        
        if selected_client.name == "Microsoft Outlook" and has_active_filters:
            logger.info(f"🔍 Outlook with active filters — routing through search_emails_script for filtered retrieval")
            await self.applescript_service._ensure_outlook_discovery(folder)
            if not search_criteria.folder:
                search_criteria.folder = folder
            script = self.applescript_service.outlook_service.search_emails_script(search_criteria, limit)
            result = await self.applescript_service.execute_applescript(script, "get filtered emails from Microsoft Outlook")
            if not result.success:
                raise RuntimeError(f"Filtered email retrieval failed: {result.error}")
            emails = self.applescript_service.outlook_service.parse_emails_from_applescript(result.data)
        else:
            emails = await self.applescript_service.get_emails_via_applescript(
                selected_client.name, folder, limit, search_criteria
            )
        
        logger.info(f"📧 RETRIEVED {len(emails)} EMAILS FROM APPLESCRIPT")
        
        for i, email in enumerate(emails):
            logger.info(f"📧 EMAIL #{i+1} FULL CONTENT:")
            logger.info(f"   ID: {email.id}")
            logger.info(f"   Subject: '{email.subject}'")
            logger.info(f"   Sender: '{email.sender}'")
            logger.info(f"   Recipient: '{email.recipient}'")
            logger.info(f"   Date: {email.date_sent}")
            logger.info(f"   Is Read: {email.is_read}")
            logger.info(f"   Is Flagged: {email.is_flagged}")
            logger.info(f"   Folder: '{email.folder}'")
            logger.info(f"   Content Length: {len(email.content)} chars")
            logger.info(f"   Content Preview: '{email.content[:200]}{'...' if len(email.content) > 200 else ''}'")
            logger.info(f"   Full Content: '{email.content}'")
            logger.info(f"📧 END EMAIL #{i+1}")
        
        return emails

    async def _get_emails_via_filesystem(self, selected_client: EmailClient, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> List[EmailData]:
        """Get emails using direct file system access (for Thunderbird, etc.)."""
        raise NotImplementedError("File system email reading not yet implemented")

    async def _search_emails_via_applescript(self, criteria: EmailSearchCriteria, limit: int, selected_client: EmailClient) -> List[EmailData]:
        """Search emails using AppleScript automation."""
        criteria = normalize_email_search_criteria(criteria)
        
        folder = criteria.folder if criteria and criteria.folder else "inbox"

        if selected_client.name == "Microsoft Outlook":
            await self.applescript_service._ensure_outlook_discovery(folder)
            script = self.applescript_service.outlook_service.search_emails_script(criteria, limit)
            result = await self.applescript_service.execute_applescript(script, "search emails in Microsoft Outlook")
            if not result.success:
                raise RuntimeError(f"Email search failed: {result.error}")
            return self.applescript_service.outlook_service.parse_emails_from_applescript(result.data)
        else:
            return await self.applescript_service.get_emails_via_applescript(
                selected_client.name, folder, limit, criteria
            )

    async def _search_emails_via_filesystem(self, criteria: EmailSearchCriteria, limit: int) -> List[EmailData]:
        """Search emails using direct file system access."""
        raise NotImplementedError("File system email search not yet implemented")
