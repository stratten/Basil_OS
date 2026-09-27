"""
Email Composition Mixin

Public operations and backend dispatch for composing, replying to,
and drafting emails. Mixed into EmailClientService.
"""

import re
import logging
from typing import TYPE_CHECKING, Any, Optional

from .email_models import EmailRequest, EmailClient, DraftRequest
from .email_tool_contracts import (
    CreateNewEmailDraftArgs,
    CreateReplyEmailDraftArgs,
    create_draft_args_from_legacy_payload,
    create_new_email_draft_args_from_raw,
    create_reply_email_draft_args_from_raw,
)

if TYPE_CHECKING:
    from .applescript_automation_service import AppleScriptAutomationService

logger = logging.getLogger(__name__)


class EmailCompositionMixin:
    """Composition, reply, and draft operations for emails."""

    applescript_service: 'AppleScriptAutomationService'
    primary_client: Optional[EmailClient]

    def _get_client_by_name(self, client_name: Optional[str] = None) -> Optional[EmailClient]: ...

    async def _run_with_email_compose_timeout(self, operation):
        """Use a longer AppleScript timeout for compose/reply operations.

        Microsoft Outlook's native ``reply to`` and
        ``make new outgoing message`` verbs do recipient resolution
        against the Exchange directory, threading-header lookup, and
        auto-quote rendering synchronously inside the AppleEvent
        round-trip; representative wall-clock on a real account is
        40-60s for a single reply-all draft (validated via live
        osascript probe). The shared ``AppleScriptAutomationService``
        instance is initialized with the short default timeout (30s)
        intended for fast operations like mark-read / move; without
        this helper, every Outlook compose or reply call would time
        out before it could complete and surface as a generic draft
        creation failure to the agent.

        Mirrors ``EmailRetrievalMixin._run_with_email_read_timeout``.
        Reads ``email_compose_applescript_timeout`` off ``self`` (set
        on ``EmailClientService.__init__``); falls back to the
        currently configured timeout if that attribute is missing
        (defensive: protects against test fixtures that mix the
        mixin into a bare object).
        """
        previous_timeout = self.applescript_service.timeout
        compose_timeout = getattr(
            self, "email_compose_applescript_timeout", previous_timeout
        )
        self.applescript_service.timeout = max(previous_timeout, compose_timeout)
        try:
            return await operation()
        finally:
            self.applescript_service.timeout = previous_timeout

    def _clean_template_placeholders(self, text: str) -> str:
        """
        Clean template placeholders from text by removing surrounding {{}} brackets.
        
        Args:
            text: Text that may contain template placeholders like {{value}}
            
        Returns:
            Cleaned text with template brackets removed
        """
        if not isinstance(text, str):
            return text
        return re.sub(r'\{\{([^}]+)\}\}', r'\1', text)

    async def process_email_request(self, email_request: Any, client_name: Optional[str] = None) -> bool:
        """
        Process comprehensive email request (draft, send, reply, forward).
        
        Args:
            email_request: The email request containing all details and action type
            client_name: Optional specific email client to use (e.g., "Microsoft Outlook")
            
        Returns:
            True if email was processed successfully
        """
        if not isinstance(email_request, EmailRequest):
            email_request = create_draft_args_from_legacy_payload(email_request).to_email_request()

        if email_request.action == "reply" or email_request.reference_email_id:
            email_request = create_reply_email_draft_args_from_raw(email_request).to_email_request()
        else:
            email_request = create_new_email_draft_args_from_raw(email_request).to_email_request()

        original_action = email_request.action
        action_was_downgraded = False
        if email_request.action == "send":
            logger.warning("SAFETY: 'send' was converted to 'draft' — email was NOT sent. A draft was created for manual review.")
            email_request.action = "draft"
            action_was_downgraded = True
        
        selected_client = self._get_client_by_name(client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return False
        
        cleaned_request = EmailRequest(
            recipient=self._clean_template_placeholders(email_request.recipient),
            subject=self._clean_template_placeholders(email_request.subject),
            body=self._clean_template_placeholders(email_request.body),
            action=email_request.action,
            reference_email_id=self._clean_template_placeholders(str(email_request.reference_email_id)) if email_request.reference_email_id else None,
            cc=[self._clean_template_placeholders(addr) for addr in email_request.cc] if email_request.cc else [],
            bcc=[self._clean_template_placeholders(addr) for addr in email_request.bcc] if email_request.bcc else [],
            attachments=email_request.attachments
        )
        
        logger.info(f"✍️ Processing email {cleaned_request.action} via {selected_client.name}")
        logger.info(f"   To: {cleaned_request.recipient}")
        logger.info(f"   Subject: {cleaned_request.subject}")
        logger.info(f"   Action: {cleaned_request.action}")
        
        try:
            if selected_client.automation_method == "applescript":
                # Run under the compose-specific timeout so the slow
                # Outlook ``make new outgoing message`` path (recipient
                # resolution, threading, auto-quote rendering) is not
                # cut off by the service's default short timeout. The
                # URL-scheme path below does not go through AppleScript
                # at all and therefore does not need the wrapper.
                return await self._run_with_email_compose_timeout(
                    lambda: self._process_email_via_applescript(cleaned_request, selected_client)
                )
            elif selected_client.automation_method == "url_schemes":
                return await self._process_email_via_url_scheme(cleaned_request)
            else:
                logger.warning(f"⚠️ Email processing not supported for {selected_client.automation_method}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error processing email request: {e}", exc_info=True)
            return False

    async def reply_to_email(self, email_id: str, reply_body: str, reply_all: bool = True, 
                            draft_only: bool = True, client_name: Optional[str] = None) -> bool:
        """
        Reply to an email using native email client reply functionality.
        
        This method uses the email client's native reply instruction which automatically:
        - Quotes the original message
        - Sets proper threading headers (In-Reply-To, References)
        - Populates recipients from the original email (including CC if reply_all=True)
        - Maintains conversation context
        
        Args:
            email_id: ID of the email to reply to
            reply_body: The reply message content
            reply_all: If True, includes all recipients (default: True)
            draft_only: If True, creates draft without sending (default: True for safety)
            client_name: Optional specific email client to use
            
        Returns:
            True if reply draft was created successfully
        """
        reply_args = CreateReplyEmailDraftArgs(
            reference_email_id=email_id,
            reply_body=reply_body,
            reply_all=reply_all,
            draft_only=draft_only,
            client_name=client_name,
        )
        
        logger.info(f"📧 Creating reply to email_id={reply_args.reference_email_id[:20]}..., reply_all={reply_args.reply_all}, draft_only={reply_args.draft_only}")
        
        selected_client = self._get_client_by_name(reply_args.client_name)
        if not selected_client:
            logger.warning("⚠️ No email client available")
            return False
        
        try:
            if selected_client.automation_method == "applescript":
                # Run under the compose-specific timeout. Outlook reply
                # drafts routinely take 40-60s end-to-end inside the
                # AppleEvent layer; the service's default short timeout
                # would cut the call off before it can complete.
                return await self._run_with_email_compose_timeout(
                    lambda: self.applescript_service.reply_to_email_via_applescript(
                        selected_client.name,
                        email_id=reply_args.reference_email_id,
                        reply_body=reply_args.reply_body,
                        reply_all=reply_args.reply_all,
                        draft_only=reply_args.draft_only,
                    )
                )
            else:
                logger.warning(f"⚠️ Reply not supported for {selected_client.automation_method}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error creating reply: {e}", exc_info=True)
            return False

    async def create_new_email_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        client_name: Optional[str] = None
    ) -> bool:
        """
        Create a new email draft with explicit recipient addresses.
        
        Args:
            recipient: Final recipient email address
            subject: Email subject line
            body: Email body content
            cc: Optional CC recipient email addresses
            bcc: Optional BCC recipient email addresses
            client_name: Optional specific email client to use
            
        Returns:
            True if draft was created successfully
        """
        draft_args = CreateNewEmailDraftArgs(
            recipient=recipient,
            subject=subject,
            body=body,
            cc=cc or [],
            bcc=bcc or [],
            client_name=client_name,
        )
        return await self.process_email_request(draft_args.to_email_request(), client_name=draft_args.client_name)

    async def create_reply_email_draft(
        self,
        reference_email_id: str,
        reply_body: str,
        reply_all: bool = True,
        draft_only: bool = True,
        client_name: Optional[str] = None
    ) -> bool:
        """
        Create a reply draft against a stable source email id.
        
        Args:
            reference_email_id: Stable source email/message id for the reply
            reply_body: Reply body content
            reply_all: If True, includes all recipients
            draft_only: Must be True; sending is not supported by this tool
            client_name: Optional specific email client to use
            
        Returns:
            True if reply draft was created successfully
        """
        reply_args = CreateReplyEmailDraftArgs(
            reference_email_id=reference_email_id,
            reply_body=reply_body,
            reply_all=reply_all,
            draft_only=draft_only,
            client_name=client_name,
        )
        return await self.reply_to_email(
            email_id=reply_args.reference_email_id,
            reply_body=reply_args.reply_body,
            reply_all=reply_args.reply_all,
            draft_only=reply_args.draft_only,
            client_name=reply_args.client_name,
        )

    async def create_email_draft(self, draft_request: Any) -> bool:
        """
        Create an email draft (backward compatibility method).

        Args:
            draft_request: Draft specification
            
        Returns:
            True if draft was created successfully
        """
        if isinstance(draft_request, DraftRequest):
            if draft_request.is_reply or draft_request.reference_email_id:
                return await self.create_reply_email_draft(
                    reference_email_id=draft_request.reference_email_id,
                    reply_body=draft_request.body,
                )
            return await self.create_new_email_draft(
                recipient=draft_request.recipient,
                subject=draft_request.subject,
                body=draft_request.body,
            )

        draft_args = create_draft_args_from_legacy_payload(draft_request)
        if isinstance(draft_args, CreateReplyEmailDraftArgs):
            return await self.create_reply_email_draft(
                reference_email_id=draft_args.reference_email_id,
                reply_body=draft_args.reply_body,
                reply_all=draft_args.reply_all,
                draft_only=draft_args.draft_only,
                client_name=draft_args.client_name,
            )

        return await self.create_new_email_draft(
            recipient=draft_args.recipient,
            subject=draft_args.subject,
            body=draft_args.body,
            cc=draft_args.cc,
            bcc=draft_args.bcc,
            client_name=draft_args.client_name,
        )

    # -- Backend dispatch --

    async def _process_email_via_applescript(self, email_request: EmailRequest, selected_client: EmailClient) -> bool:
        """Process email request using AppleScript automation."""
        return await self.applescript_service.process_email_via_applescript(
            selected_client.name, email_request
        )

    async def _process_email_via_url_scheme(self, email_request: EmailRequest) -> bool:
        """Process email request using URL schemes."""
        from urllib.parse import quote
        subject = quote(email_request.subject or '', safe='')
        body = quote(email_request.body or '', safe='')
        mailto_url = f"mailto:{email_request.recipient}?subject={subject}&body={body}"
        script = f'open location "{mailto_url}"'
        result = await self.applescript_service.execute_applescript(script, "open mailto URL")
        return result.success

    async def _create_draft_via_applescript(self, draft_request: DraftRequest) -> bool:
        """Create email draft using AppleScript."""
        email_request = EmailRequest(
            recipient=draft_request.recipient,
            subject=draft_request.subject,
            body=draft_request.body,
            action="draft",
            reference_email_id=draft_request.reference_email_id
        )
        return await self._process_email_via_applescript(email_request, self.primary_client)

    async def _create_draft_via_url_scheme(self, draft_request: DraftRequest) -> bool:
        """Create email draft using URL schemes."""
        email_request = EmailRequest(
            recipient=draft_request.recipient,
            subject=draft_request.subject,
            body=draft_request.body,
            action="draft",
            reference_email_id=draft_request.reference_email_id
        )
        return await self._process_email_via_url_scheme(email_request)
