"""
Mail.app Service - Facade

Thin composition layer that delegates to focused modules:
- parsing: Email record parsing and utilities
- script_generators: AppleScript code generation for Mail.app
"""

from typing import List, Optional

from ..email_models import EmailData, EmailRequest, EmailOperation, EmailSearchCriteria
from .script_generators import MailAppScriptGenerator
from .operation_receipt_scripts import MailOperationReceiptScriptGenerator
from .parsing import MailAppParser


class MailAppService:
    """
    Dedicated service for Apple Mail.app AppleScript automation.
    Mirrors the structure of OutlookAppleScriptService.
    """

    def __init__(self):
        self.scripts = MailAppScriptGenerator()
        self.operation_receipt_scripts = MailOperationReceiptScriptGenerator(
            self.scripts._escape
        )
        self.parser = MailAppParser()

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

    def organize_emails_receipt_script(self, operation: EmailOperation) -> str:
        return self.operation_receipt_scripts.organize_emails_receipt_script(operation)

    def get_folders_script(self) -> str:
        return self.scripts.get_folders_script()

    def create_folder_script(self, folder_name: str, parent_folder: Optional[str] = None) -> str:
        return self.scripts.create_folder_script(folder_name, parent_folder)

    # -- Parsing delegation --

    def parse_emails_from_applescript(self, applescript_result: str, client_name: str) -> List[EmailData]:
        return self.parser.parse_emails_from_applescript(applescript_result, client_name)

    def parse_folders_from_applescript(self, applescript_result: str) -> List[str]:
        return self.parser.parse_folders_from_applescript(applescript_result)
