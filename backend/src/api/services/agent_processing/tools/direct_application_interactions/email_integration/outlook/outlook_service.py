"""
Outlook AppleScript Service - Facade

Thin composition layer that delegates to focused modules:
- account_discovery: Account/folder discovery and mapping
- script_generators: AppleScript code generation
- parsing: Email record parsing and utilities
"""

from typing import List, Dict, Any, Optional

from ..email_models import EmailData, EmailRequest, EmailOperation, EmailSearchCriteria
from .account_discovery import OutlookAccountDiscovery
from .script_generators import OutlookScriptGenerator
from .parsing import OutlookEmailParser


class OutlookAppleScriptService:
    """
    Dedicated service for Microsoft Outlook AppleScript automation.
    
    Handles all Outlook-specific operations including dynamic account mapping
    based on discovered folder structure.
    """

    def __init__(self):
        self.discovery = OutlookAccountDiscovery()
        self.scripts = OutlookScriptGenerator(self.discovery)
        self.parser = OutlookEmailParser()

    # -- discovered_accounts compat (read/written directly by applescript_automation_service) --

    @property
    def discovered_accounts(self):
        return self.discovery.discovered_accounts

    @discovered_accounts.setter
    def discovered_accounts(self, value):
        self.discovery.discovered_accounts = value

    # -- Discovery delegation --

    def discover_inbox_folders_script(self) -> str:
        return self.discovery.discover_inbox_folders_script()

    async def discover_and_map_accounts(self, applescript_executor) -> Dict[str, Dict[str, Any]]:
        return await self.discovery.discover_and_map_accounts(applescript_executor)

    def find_matching_account(self, folder_identifier: str, discovered_accounts: Dict[str, Dict[str, Any]]) -> Optional[str]:
        return self.discovery.find_matching_account(folder_identifier, discovered_accounts)

    async def quick_account_count(self, execute_applescript_func) -> int:
        return await self.discovery.quick_account_count(execute_applescript_func)

    async def quick_inbox_discovery(self, execute_applescript_func) -> Dict[str, Any]:
        return await self.discovery.quick_inbox_discovery(execute_applescript_func)

    async def intelligent_discovery(self, execute_applescript_func, account_context: str = None) -> Dict[str, Any]:
        return await self.discovery.intelligent_discovery(execute_applescript_func, account_context)

    def get_folder_reference(self, folder_request: str, discovered_accounts: Dict[str, Any],
                           account_context: str = None) -> str:
        return self.discovery.get_folder_reference(folder_request, discovered_accounts, account_context)

    def get_account_info_script(self) -> str:
        return self.discovery.get_account_info_script()

    async def discover_accounts_by_email_analysis(self, execute_applescript_func) -> Dict[str, Any]:
        return await self.discovery.discover_accounts_by_email_analysis(execute_applescript_func)

    # -- Script generation delegation --

    def get_emails_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        return self.scripts.get_emails_script(folder, limit, search_criteria)

    def get_email_metadata_script(self, folder: str, limit: int, search_criteria: Optional[EmailSearchCriteria] = None) -> str:
        return self.scripts.get_email_metadata_script(folder, limit, search_criteria)

    def expand_email_details_script(self, folder: str, email_ids: list[str], excerpt_chars: int = 4000) -> str:
        return self.scripts.expand_email_details_script(folder, email_ids, excerpt_chars)

    def compose_email_script(self, email_request: EmailRequest, draft_only: bool = True) -> str:
        return self.scripts.compose_email_script(email_request, draft_only)

    def send_email_script(self, email_request: EmailRequest) -> str:
        return self.scripts.send_email_script(email_request)

    def reply_to_email_script(self, email_id: str, reply_body: str, reply_all: bool = True, draft_only: bool = True) -> str:
        return self.scripts.reply_to_email_script(email_id, reply_body, reply_all, draft_only)

    def organize_emails_script(self, operation: EmailOperation) -> str:
        return self.scripts.organize_emails_script(operation)

    def search_emails_script(self, criteria: EmailSearchCriteria, limit: int) -> str:
        return self.scripts.search_emails_script(criteria, limit)

    def get_folders_script(self) -> str:
        return self.scripts.get_folders_script()

    def create_folder_script(self, folder_name: str, parent_folder: Optional[str] = None) -> str:
        return self.scripts.create_folder_script(folder_name, parent_folder)

    # -- Parsing delegation --

    def parse_emails_from_applescript(self, applescript_result: str) -> List[EmailData]:
        return self.parser.parse_emails_from_applescript(applescript_result)
