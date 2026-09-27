"""
Outlook Email Parsing

Handles parsing of raw AppleScript output into EmailData objects.
Supports both enhanced (triple-pipe) and legacy (single-pipe) record formats.
Also provides shared utility functions used by other Outlook modules.
"""

import logging
import re
import html
from typing import Dict, List, Optional
from datetime import datetime

from ..email_models import EmailData, EmailDataList
from api.services.agent_processing.shared.llm_text_formatting import sanitize_data_for_llm

logger = logging.getLogger(__name__)


class OutlookEmailParser:
    """Parses raw AppleScript output from Outlook into structured EmailData objects."""

    def parse_emails_from_applescript(self, applescript_result: str) -> List[EmailData]:
        """
        Parse Outlook AppleScript result into EmailData objects.
        
        Args:
            applescript_result: Raw AppleScript output from Outlook
            
        Returns:
            List of EmailData objects
        """
        emails = EmailDataList()
        
        try:
            if applescript_result.startswith("SCRIPT_ERROR:") or applescript_result.startswith("ERROR:"):
                logger.error(f"🚨 Outlook AppleScript error: {applescript_result}")
                return emails

            coverage_metadata = self._extract_coverage_metadata(applescript_result or "")
            applescript_result = self._strip_coverage_metadata(applescript_result or "")
            applescript_result = re.sub(r'\n(?=\d+\|\|\|)', ', ', applescript_result)
                
            logger.info(f"📧 Raw Outlook result: {applescript_result[:200]}...")
            
            record_boundary_pattern = r',\s*(\d+\|\|\|)'
            parts = re.split(record_boundary_pattern, applescript_result)
            
            email_records = []
            if parts:
                current_record = parts[0].strip()
                
                for i in range(1, len(parts), 2):
                    if i + 1 < len(parts):
                        if current_record:
                            email_records.append(current_record)
                        
                        boundary_start = parts[i]
                        record_content = parts[i + 1]
                        current_record = boundary_start + record_content
                
                if current_record:
                    email_records.append(current_record)
            
            logger.info(f"📧 Split into {len(email_records)} email records")
            
            for record_str in email_records:
                record_str = record_str.strip()
                if record_str:
                    email_data = self._parse_outlook_email_record(record_str)
                    if email_data:
                        emails.append(email_data)
                        logger.debug(f"📧 Parsed email: {email_data.subject}")
            
            logger.info(f"📧 Successfully parsed {len(emails)} emails from Outlook AppleScript records")
            emails.coverage_metadata = coverage_metadata
            
        except Exception as e:
            logger.error(f"🚨 Error parsing Outlook emails: {e}")
            logger.exception("Full parsing error:")
        
        return emails

    def _extract_coverage_metadata(self, applescript_result: str) -> Dict[str, str]:
        """Extract Outlook retrieval coverage metadata from script output."""
        prefix = "BASIL_OUTLOOK_METADATA_COVERAGE:"
        for line in (applescript_result or "").splitlines():
            if not line.startswith(prefix):
                continue

            metadata: Dict[str, str] = {}
            payload = line[len(prefix):].strip()
            for part in payload.split(";"):
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                metadata[key.strip()] = value.strip()
            return metadata

        return {}

    def _strip_coverage_metadata(self, applescript_result: str) -> str:
        """Remove coverage metadata lines before record parsing."""
        prefix = "BASIL_OUTLOOK_METADATA_COVERAGE:"
        return "\n".join(
            line for line in (applescript_result or "").splitlines()
            if not line.startswith(prefix)
        )

    def _parse_outlook_email_record(self, record_str: str) -> Optional[EmailData]:
        """
        Parse a single Outlook email record into an EmailData object.
        
        Supports two formats:
        - Enhanced (|||): ID|||Subject|||Sender|||Date|||Content|||ReadStatus|||To|||CC|||ConversationID
        - Legacy (|):     Subject|Sender|To|Content|Date|ReadStatus|ID
        
        Args:
            record_str: Pipe-separated email record (auto-detects delimiter)
            
        Returns:
            EmailData object or None if parsing fails
        """
        try:
            if '|||' in record_str:
                parts = record_str.split('|||')
                
                if len(parts) < 6:
                    logger.warning(f"⚠️ Outlook email record has insufficient parts: {len(parts)} (expected 6+)")
                    return None
                
                email_id = parts[0].strip() if len(parts) > 0 else ""
                subject = parts[1].strip() if len(parts) > 1 else ""
                sender = parts[2].strip() if len(parts) > 2 else ""
                date_sent_str = parts[3].strip() if len(parts) > 3 else ""
                content = parts[4].strip() if len(parts) > 4 else ""
                is_read_str = parts[5].strip() if len(parts) > 5 else "false"
                to_recipients_str = parts[6].strip() if len(parts) > 6 else ""
                cc_recipients_str = parts[7].strip() if len(parts) > 7 else ""
                conversation_id = parts[8].strip() if len(parts) > 8 else ""
                is_flagged_str = parts[9].strip() if len(parts) > 9 else "false"
            else:
                parts = record_str.split('|')
                
                if len(parts) < 5:
                    logger.warning(f"⚠️ Legacy email record has insufficient parts: {len(parts)} (expected 5+)")
                    return None
                
                logger.debug(f"📧 Parsing legacy single-pipe format ({len(parts)} fields)")
                subject = parts[0].strip() if len(parts) > 0 else ""
                sender = parts[1].strip() if len(parts) > 1 else ""
                to_recipients_str = parts[2].strip() if len(parts) > 2 else ""
                content = parts[3].strip() if len(parts) > 3 else ""
                date_sent_str = parts[4].strip() if len(parts) > 4 else ""
                is_read_str = parts[5].strip() if len(parts) > 5 else "false"
                email_id = parts[6].strip() if len(parts) > 6 else ""
                cc_recipients_str = ""
                conversation_id = ""
                is_flagged_str = "false"
            
            to_recipients = [addr.strip() for addr in to_recipients_str.split(',') if addr.strip()] if to_recipients_str else []
            cc_recipients = [addr.strip() for addr in cc_recipients_str.split(',') if addr.strip()] if cc_recipients_str else []
            
            primary_recipient = ""
            if sender and sender.strip():
                if '<' in sender and '>' in sender:
                    email_match = re.search(r'<([^>]+)>', sender)
                    if email_match:
                        primary_recipient = email_match.group(1).strip()
                    else:
                        primary_recipient = sender.strip()
                elif '@' in sender:
                    primary_recipient = sender.strip()
                else:
                    primary_recipient = to_recipients[0] if to_recipients else ""
            else:
                primary_recipient = to_recipients[0] if to_recipients else ""
            
            email = EmailData(
                id=email_id,
                subject=sanitize_data_for_llm(subject),
                sender=sanitize_data_for_llm(sender),
                recipient=sanitize_data_for_llm(primary_recipient),
                content=sanitize_data_for_llm(self.strip_html_content(content)),
                date_sent=self.parse_outlook_date(date_sent_str),
                is_read=is_read_str.lower() in ('true', 'yes', '1'),
                is_flagged=is_flagged_str.lower() in ('true', 'yes', '1', 'flag'),
                folder="inbox",
                thread_id=conversation_id if conversation_id else None,
                cc_recipients=cc_recipients,
                bcc_recipients=[]
            )
            
            logger.debug(f"📧 Parsed email '{subject}' with {len(to_recipients)} TO and {len(cc_recipients)} CC recipients, thread_id={conversation_id[:20] if conversation_id else 'None'}")
            
            return email
            
        except Exception as e:
            logger.error(f"❌ Error parsing Outlook email record '{record_str[:100]}...': {e}")
            return None

    def parse_outlook_date(self, date_str: str) -> datetime:
        """
        Parse Outlook date string into datetime object.
        
        Outlook format: "Friday, July 18, 2025 at 10:35:30 PM"
        
        Args:
            date_str: Date string from Outlook AppleScript
            
        Returns:
            datetime object
        """
        if not date_str or date_str.lower() in ['unknown date', 'missing value']:
            return datetime.now()
        
        formats = [
            '%A, %B %d, %Y at %I:%M:%S %p',   # Friday, July 18, 2025 at 10:35:30 PM
            '%B %d, %Y at %I:%M:%S %p',         # July 18, 2025 at 10:35:30 PM
            '%A, %B %d, %Y at %H:%M:%S',        # Friday, July 18, 2025 at 22:35:30
            '%Y-%m-%d %H:%M:%S %z',              # 2025-07-18 10:35:30 +0000
            '%Y-%m-%dT%H:%M:%S',                 # 2025-07-18T10:35:30
            '%m/%d/%Y %I:%M:%S %p',              # 07/18/2025 10:35:30 PM
            '%d/%m/%Y %H:%M:%S',                 # 18/07/2025 10:35:30
        ]
        
        cleaned = date_str.strip()
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        
        logger.warning(f"Could not parse Outlook date '{date_str}' with any known format, falling back to now()")
        return datetime.now()

    @staticmethod
    def escape_applescript_string(text: str) -> str:
        """Escape string for AppleScript."""
        if not text:
            return ""
        text = str(text)
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        text = text.replace("\n", "\\n")
        text = text.replace("\r", "\\r")
        text = text.replace("\t", "\\t")
        return text

    @staticmethod
    def strip_html_content(content: str) -> str:
        """
        Strip HTML tags and normalize whitespace from email content.
        
        Args:
            content: Raw email content (may contain HTML)
            
        Returns:
            Clean text content without HTML tags
        """
        if not content:
            return ""
            
        try:
            clean_text = re.sub(r'<[^>]+>', '', content)
            clean_text = html.unescape(clean_text)
            clean_text = re.sub(r'\s+', ' ', clean_text)
            clean_text = clean_text.strip()
            return clean_text
            
        except Exception as e:
            logger.warning(f"⚠️ Error stripping HTML content: {e}")
            return content[:1000] + "... [Content processing failed]" if len(content) > 1000 else content
