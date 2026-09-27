"""
Email Organization Mixin

Public operations and backend dispatch for organizing emails,
managing folders, and bulk operations. Mixed into EmailClientService.
"""

import logging
from typing import TYPE_CHECKING, Any, List, Dict, Optional

from .email_models import EmailOperation, EmailClient
from .email_operation_contracts import organize_emails_args_from_raw
from .mail_app.operation_receipt_parser import (
    MailOperationReceiptParseError,
    parse_mail_operation_receipts,
)
from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)

if TYPE_CHECKING:
    from .applescript_automation_service import AppleScriptAutomationService

logger = logging.getLogger(__name__)


class EmailOrganizationMixin:
    """Organization, folder management, and bulk operations for emails."""

    applescript_service: 'AppleScriptAutomationService'

    def _get_client_by_name(self, client_name: Optional[str] = None) -> Optional[EmailClient]: ...

    async def organize_emails(
        self,
        operation: Any,
        email_ids: Optional[List[str]] = None,
        target_folder: Optional[str] = None,
        client_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform organization operations on emails (move, delete, flag, etc.).
        
        Args:
            operation: The organization operation to perform
            client_name: Optional specific email client to use (e.g., "Microsoft Outlook")
            
        Returns:
            True if operation was successful
        """
        raw_operation = (
            {
                "operation": operation,
                "email_ids": email_ids,
                "target_folder": target_folder,
                "client_name": client_name,
            }
            if isinstance(operation, str)
            else operation
        )
        validated = organize_emails_args_from_raw(raw_operation)
        operation = validated.to_email_operation()
        selected_client = self._get_client_by_name(client_name or validated.client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return _not_started_envelope(operation, "No email client is available.")
        
        logger.info(f"📁 Performing {operation.operation} operation via {selected_client.name}")
        logger.info(f"   Email IDs: {operation.email_ids}")
        if operation.target_folder:
            logger.info(f"   Target folder: {operation.target_folder}")
        
        try:
            if selected_client.name in {"Mail", "Mail.app"}:
                return await self._organize_emails_via_applescript(operation, selected_client)
            logger.warning(
                "⚠️ Email organization receipt contract is unavailable for %s",
                selected_client.name,
            )
            return _not_started_envelope(
                operation,
                "Selected email adapter does not emit material-operation receipts.",
            )
                
        except Exception as e:
            logger.error(f"❌ Error organizing emails: {e}", exc_info=True)
            return _failed_envelope(operation, str(e))

    async def get_folders(self, client_name: Optional[str] = None) -> List[str]:
        """
        Get list of available email folders.
        
        Args:
            client_name: Optional specific email client to use (e.g., "Microsoft Outlook")
        
        Returns:
            List of folder names
        """
        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return []
        
        logger.info(f"📁 Getting folders from {selected_client.name}")
        
        try:
            if selected_client.automation_method == "applescript":
                return await self._get_folders_via_applescript(selected_client)
            else:
                logger.warning(f"⚠️ Folder listing not supported for {selected_client.automation_method}")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error getting folders: {e}", exc_info=True)
            raise Exception(f"Folder retrieval failed: {str(e)}")

    async def create_folder(self, folder_name: str, parent_folder: Optional[str] = None, client_name: Optional[str] = None) -> bool:
        """
        Create a new email folder.
        
        Args:
            folder_name: Name of the folder to create
            parent_folder: Parent folder (if creating subfolder)
            client_name: Optional specific email client to use (e.g., "Microsoft Outlook")
            
        Returns:
            True if folder was created successfully
        """
        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return False
        
        logger.info(f"📁 Creating folder '{folder_name}' via {selected_client.name}")
        
        try:
            if selected_client.automation_method == "applescript":
                return await self._create_folder_via_applescript(folder_name, parent_folder, selected_client)
            else:
                logger.warning(f"⚠️ Folder creation not supported for {selected_client.automation_method}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error creating folder: {e}", exc_info=True)
            return False

    async def bulk_organize_emails(self, operations: List[Any]) -> Dict[str, Dict[str, Any]]:
        """
        Perform multiple organization operations efficiently.
        
        Args:
            operations: List of organization operations to perform
            
        Returns:
            Dictionary mapping operation descriptions to success status
        """
        selected_client = self._get_client_by_name()
        if not selected_client:
            logger.warning("⚠️ No email client available for bulk operations")
            return {}
        
        logger.info(f"📦 Performing {len(operations)} bulk operations via {selected_client.name}")
        
        results: Dict[str, Dict[str, Any]] = {}
        for i, raw_operation in enumerate(operations):
            operation = organize_emails_args_from_raw(raw_operation).to_email_operation()
            try:
                success = await self.organize_emails(operation)
                results[f"operation_{i}_{operation.operation}"] = success
            except Exception as e:
                logger.error(f"❌ Error in bulk operation {i}: {e}")
                results[f"operation_{i}_{operation.operation}"] = _failed_envelope(
                    operation,
                    str(e),
                )
        
        return results

    # -- Backend dispatch --

    async def _organize_emails_via_applescript(
        self,
        operation: EmailOperation,
        selected_client: EmailClient,
    ) -> Dict[str, Any]:
        """Run Mail's receipt-producing script and return its shared envelope."""
        script = self.applescript_service.mail_app_service.organize_emails_receipt_script(
            operation
        )
        result = await self.applescript_service.execute_applescript(
            script,
            f"organize emails via {selected_client.name}",
        )
        if not result.success:
            return _failed_envelope(operation, str(result.error or "Mail execution failed."))
        try:
            envelope = parse_mail_operation_receipts(str(result.data or ""), operation)
        except MailOperationReceiptParseError as exc:
            return _failed_envelope(operation, str(exc))
        return envelope.to_tool_result_fields()

    async def _get_folders_via_applescript(self, selected_client: EmailClient) -> List[str]:
        """Get folders using AppleScript automation."""
        return await self.applescript_service.get_folders_via_applescript(selected_client.name)

    async def _create_folder_via_applescript(self, folder_name: str, parent_folder: Optional[str] = None, selected_client: Optional[EmailClient] = None) -> bool:
        """Create folder using AppleScript automation."""
        if not selected_client:
            logger.warning("⚠️ No selected client provided for folder creation")
            return False
        return await self.applescript_service.create_folder_via_applescript(
            selected_client.name, folder_name, parent_folder
        )


def _not_started_envelope(operation: EmailOperation, reason: str) -> Dict[str, Any]:
    return _email_operation_envelope(
        operation,
        execution_state="not_started",
        verification_status="not_applicable",
        evidence={"blocked_before_mutation": True},
        discrepancy={"reason": reason},
    )


def _failed_envelope(operation: EmailOperation, reason: str) -> Dict[str, Any]:
    return _email_operation_envelope(
        operation,
        execution_state="failed",
        verification_status="failed",
        evidence={"adapter_error": True},
        discrepancy={"reason": reason},
    )


def _email_operation_envelope(
    operation: EmailOperation,
    *,
    execution_state: str,
    verification_status: str,
    evidence: Dict[str, Any],
    discrepancy: Dict[str, Any],
) -> Dict[str, Any]:
    envelope = MaterialOperationEnvelope(
        receipts=tuple(
            MaterialOperationReceipt(
                entity=LedgerEntityReference(
                    entity_type="email",
                    source_system="mail_app",
                    source_scope={"mailbox": "inbox"},
                    external_id=email_id,
                ),
                requested_effect={
                    "operation": operation.operation,
                    **(
                        {"target_folder": operation.target_folder}
                        if operation.target_folder
                        else {}
                    ),
                },
                execution_state=execution_state,
                observed_postcondition={},
                verification_status=verification_status,
                evidence={**evidence, "email_id": email_id},
                discrepancy=discrepancy,
            )
            for email_id in operation.email_ids
        )
    )
    return envelope.to_tool_result_fields()
