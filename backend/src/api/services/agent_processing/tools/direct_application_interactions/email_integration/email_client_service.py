"""
Email Client Service - Foundation for Cross-Client Email Automation

This service provides a unified interface for email automation across different email clients
on macOS, leveraging the non-sandboxed capabilities of Basil for broad automation access.

Supported automation methods:
1. AppleScript - Primary method for Mail.app, Outlook
2. URL Schemes - Fallback for third-party clients
3. Database Access - Direct SQLite access for Mail.app
4. File System Events - Real-time email monitoring

Operations are split into domain mixins:
- EmailRetrievalMixin: get_emails, search_emails, get_inbox_emails
- EmailCompositionMixin: process_email_request, reply_to_email, create_email_draft
- EmailOrganizationMixin: organize_emails, get_folders, create_folder, bulk_organize_emails
"""

import asyncio
import logging
import subprocess
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .email_models import EmailData, EmailClient, EmailRequest, EmailOperation, EmailSearchCriteria, DraftRequest
from .applescript_automation_service import AppleScriptAutomationService
from .email_retrieval import EmailRetrievalMixin
from .email_composition import EmailCompositionMixin
from .email_organization import EmailOrganizationMixin
from .email_service_capabilities import build_service_capabilities

logger = logging.getLogger(__name__)


class EmailClientService(EmailRetrievalMixin, EmailCompositionMixin, EmailOrganizationMixin):
    """
    Unified email client automation service.
    
    Provides cross-client email automation using the optimal method for each client.
    Leverages non-sandboxed capabilities for broad system access.
    
    Inherits operations from domain mixins and owns client discovery/selection state.
    """
    
    def __init__(self):
        self.detected_clients: List[EmailClient] = []
        self.primary_client: Optional[EmailClient] = None
        # Default AppleScript timeout, used for short operations like
        # mark-read, move, organize. Tight enough that a genuine hang
        # is caught quickly.
        self.applescript_timeout = 30
        # Read/search operations walk message lists and can legitimately
        # take longer than the default. EmailRetrievalMixin temporarily
        # raises the service's timeout to this value via
        # _run_with_email_read_timeout.
        self.email_read_applescript_timeout = 90
        # Compose/reply operations against Microsoft Outlook take 40-60s
        # on real-world accounts because Outlook's native ``reply to``
        # / ``make new outgoing message`` verbs do recipient resolution
        # against the Exchange directory, threading-header lookup, and
        # auto-quote rendering synchronously inside the AppleEvent
        # round-trip (validated live via osascript probe on May 22,
        # 2026; representative end-to-end wall clock = 47s for a single
        # Outlook reply-all draft). The default 30s timeout cuts these
        # off before they can complete, so EmailCompositionMixin uses
        # _run_with_email_compose_timeout to temporarily raise the
        # service's timeout to this value. 120s is generous enough to
        # absorb slow-sync days while still catching a genuine hang
        # well inside the 1200s agent-execution cap upstream.
        self.email_compose_applescript_timeout = 120

        self.applescript_service = AppleScriptAutomationService(timeout=self.applescript_timeout)
        
        self.client_definitions = {
            "Mail": {
                "bundle_id": "com.apple.mail",
                "automation_method": "applescript",
                "capabilities": [
                    "read_emails", "compose_drafts", "reply_emails", "forward_emails",
                    "search_emails", "move_emails", "delete_emails", "mark_read", "mark_unread",
                    "flag_emails", "unflag_emails", "archive_emails", "create_folders", 
                    "list_folders", "database_access", "bulk_operations"
                ],
                "priority": 1
            },
            "Microsoft Outlook": {
                "bundle_id": "com.microsoft.Outlook",
                "automation_method": "applescript",
                "capabilities": [
                    "read_emails", "compose_drafts", "reply_emails", "forward_emails",
                    "search_emails", "move_emails", "delete_emails", "mark_read", "mark_unread",
                    "flag_emails", "calendar", "contacts", "bulk_operations"
                ],
                "priority": 2
            },
            "Thunderbird": {
                "bundle_id": "org.mozilla.thunderbird",
                "automation_method": "file_system",
                "capabilities": [
                    "read_emails", "profile_access", "search_emails", "limited_organization"
                ],
                "priority": 3
            },
            "Airmail 5": {
                "bundle_id": "it.bloop.airmail5",
                "automation_method": "url_schemes",
                "capabilities": [
                    "compose_drafts", "url_automation", "limited_organization"
                ],
                "priority": 4
            },
            "Spark – Email App by Readdle": {
                "bundle_id": "com.readdle.smartemail-Mac",
                "automation_method": "url_schemes", 
                "capabilities": [
                    "compose_drafts", "url_automation", "limited_organization"
                ],
                "priority": 5
            }
        }
    
    async def initialize(self) -> None:
        """Initialize the service by detecting available email clients."""
        logger.info("🔍 Initializing Email Client Service - detecting available clients...")
        
        try:
            await self.detect_email_clients()
            
            logger.info(f"✅ Email Client Service initialized with {len(self.detected_clients)} available clients")
            for client in self.detected_clients:
                status = "RUNNING" if client.is_running else "INSTALLED"
                logger.info(f"   {status}: {client.name} ({client.automation_method})")
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize Email Client Service: {e}", exc_info=True)
            raise
    
    async def detect_email_clients(self) -> List[EmailClient]:
        """
        Detect all available email clients using NSWorkspace.
        
        Returns:
            List of detected email clients with their capabilities
        """
        logger.info("🔍 Detecting email clients using NSWorkspace...")
        
        detected = []
        
        try:
            running_apps_script = '''
            tell application "System Events"
                set runningApps to name of every application process
                return runningApps
            end tell
            '''
            
            result = await self.applescript_service.execute_applescript(running_apps_script, "detect running applications")
            running_apps = result.data if result.success else None
            if running_apps:
                running_app_names = running_apps.strip().split(', ')
                logger.info(f"📱 Found {len(running_app_names)} running applications")
            else:
                running_app_names = []
            
            for client_name, client_info in self.client_definitions.items():
                is_running = client_name in running_app_names
                
                email_client = EmailClient(
                    name=client_name,
                    bundle_id=client_info["bundle_id"],
                    is_running=is_running,
                    automation_method=client_info["automation_method"],
                    capabilities=client_info["capabilities"],
                    priority=client_info["priority"]
                )
                
                if await self._verify_client_availability(email_client):
                    detected.append(email_client)
                    status = "🟢 RUNNING" if is_running else "⚫ INSTALLED"
                    logger.info(f"   {status} {client_name} ({client_info['automation_method']})")
            
            self.detected_clients = sorted(detected, key=lambda x: x.priority)
            logger.info(f"✅ Detected {len(detected)} available email clients")
            
            return self.detected_clients
            
        except Exception as e:
            logger.error(f"❌ Error detecting email clients: {e}", exc_info=True)
            return []
    
    async def select_primary_client(self) -> Optional[EmailClient]:
        """
        Select the primary email client based on running status and priority.
        
        Returns:
            The selected primary email client
        """
        if not self.detected_clients:
            logger.warning("⚠️ No email clients available for selection")
            return None
        
        running_clients = [c for c in self.detected_clients if c.is_running]
        
        if running_clients:
            self.primary_client = running_clients[0]
            logger.info(f"🎯 Selected running client: {self.primary_client.name}")
        else:
            self.primary_client = self.detected_clients[0]
            logger.info(f"🎯 Selected installed client: {self.primary_client.name} (not currently running)")
        
        return self.primary_client
    
    def _get_client_by_name(self, client_name: Optional[str] = None) -> Optional[EmailClient]:
        """Get client by name, or intelligently select best available client."""
        if client_name:
            logger.info(f"🔍 Looking for requested client: '{client_name}'")
            logger.info(f"🔍 Available clients: {[c.name for c in self.detected_clients]}")
            
            for client in self.detected_clients:
                logger.info(f"🔍 Comparing '{client.name.lower()}' vs '{client_name.lower()}'")
                if client.name.lower() == client_name.lower():
                    logger.info(f"🎯 Using requested client: {client.name}")
                    return client
            logger.warning(f"⚠️ Requested client '{client_name}' not found, selecting best available")
        
        if not self.detected_clients:
            logger.warning("⚠️ No email clients available")
            return None
        
        running_clients = [c for c in self.detected_clients if c.is_running]
        
        if running_clients:
            selected = running_clients[0]
            logger.info(f"🎯 Selected running client: {selected.name}")
            return selected
        else:
            selected = self.detected_clients[0]
            logger.info(f"🎯 Selected installed client: {selected.name} (not currently running)")
            return selected

    async def _verify_client_availability(self, client: EmailClient) -> bool:
        """Verify that an email client is actually installed and available."""
        try:
            result = subprocess.run(
                ["mdfind", f"kMDItemCFBundleIdentifier == '{client.bundle_id}'"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return bool(result.stdout.strip())
        except Exception as e:
            logger.debug(f"Could not verify availability of {client.name}: {e}")
            return False

    # -- Introspection --

    def get_detected_clients(self) -> List[EmailClient]:
        """Get the list of detected email clients."""
        return self.detected_clients
    
    def get_primary_client(self) -> Optional[EmailClient]:
        """Get the primary email client (intelligently selected based on availability)."""
        return self._get_client_by_name()
    
    def get_service_capabilities(self) -> Dict[str, Any]:
        """
        Get service method signatures and parameter information for intelligent operation planning.
        
        Returns:
            Dictionary containing method signatures, parameters, and data structure definitions
        """
        return build_service_capabilities(self)
