"""
Mail.app Email Parsing

Handles parsing of raw AppleScript output from Mail.app into EmailData objects.
Also provides shared utility functions (escaping, date parsing) used by script generators.
"""

import logging
import re
from typing import Dict, List, Optional
from datetime import datetime

from ..email_models import EmailData, EmailDataList
from api.services.agent_processing.shared.llm_text_formatting import sanitize_data_for_llm

logger = logging.getLogger(__name__)


class MailAppParser:
    """Parses raw AppleScript output from Mail.app into structured EmailData objects."""

    def parse_emails_from_applescript(self, applescript_result: str, client_name: str) -> List[EmailData]:
        """
        Parse AppleScript result into EmailData objects using structured data.
        
        Args:
            applescript_result: AppleScript output containing structured records
            client_name: Name of the email client
            
        Returns:
            List of EmailData objects
        """
        emails = EmailDataList()
        coverage_metadata = self._extract_coverage_metadata(applescript_result or "")
        
        try:
            if applescript_result.startswith("SCRIPT_ERROR:"):
                logger.error(f"❌ AppleScript execution error: {applescript_result}")
                return emails
            
            if not applescript_result.strip():
                logger.info("📧 No emails found in AppleScript result")
                return emails
            
            record_parts = applescript_result.split("email_id:")
            
            for i, record_part in enumerate(record_parts):
                if i == 0:
                    continue
                
                record_str = "email_id:" + record_part.strip()
                
                try:
                    email_data = self._parse_applescript_record(record_str)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse email record: {e}")
                    continue
            
            emails.coverage_metadata = coverage_metadata
            logger.info(f"📧 Successfully parsed {len(emails)} emails from AppleScript records")
            return emails
                
        except Exception as e:
            logger.error(f"❌ Error parsing AppleScript result: {e}", exc_info=True)
            return emails

    def _extract_coverage_metadata(self, applescript_result: str) -> Dict[str, str]:
        """Extract Mail.app retrieval coverage metadata from the script output."""
        prefix = "BASIL_MAIL_METADATA_COVERAGE:"
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

    def _parse_applescript_record(self, record_str: str) -> Optional[EmailData]:
        """
        Parse a single AppleScript record into an EmailData object.
        
        Args:
            record_str: Single AppleScript record string in format "key:value, key:value, ..."
            
        Returns:
            EmailData object or None if parsing fails
        """
        try:
            email_dict = {}
            
            known_keys = ['email_id', 'subject', 'sender', 'recipient', 'content', 'date_sent', 'is_read', 'is_flagged', 'message_id']
            
            key_positions = {}
            for key in known_keys:
                pos = record_str.find(f"{key}:")
                if pos != -1:
                    key_positions[key] = pos
            
            sorted_keys = sorted(key_positions.items(), key=lambda x: x[1])
            
            for i, (key, start_pos) in enumerate(sorted_keys):
                value_start = start_pos + len(key) + 1
                
                if i + 1 < len(sorted_keys):
                    next_key, next_pos = sorted_keys[i + 1]
                    next_key_pattern = f", {next_key}:"
                    next_key_pos = record_str.find(next_key_pattern, value_start)
                    if next_key_pos != -1:
                        value_end = next_key_pos
                    else:
                        value_end = next_pos
                else:
                    value_end = len(record_str)
                
                value = record_str[value_start:value_end].strip()
                
                if value.startswith(", "):
                    value = value[2:]
                elif value.startswith(","):
                    value = value[1:]
                
                value = value.strip()
                
                if value == "missing value":
                    value = ""
                
                email_dict[key] = value
            
            message_id = email_dict.get('message_id', '')
            
            email = EmailData(
                id=email_dict.get('email_id', ''),
                subject=sanitize_data_for_llm(email_dict.get('subject', '')),
                sender=sanitize_data_for_llm(email_dict.get('sender', '')),
                recipient=sanitize_data_for_llm(email_dict.get('recipient', '')),
                content=sanitize_data_for_llm(email_dict.get('content', '')),
                date_sent=self.parse_date(email_dict.get('date_sent', '')),
                is_read=email_dict.get('is_read', 'false').lower() in ('true', 'yes', '1'),
                is_flagged=email_dict.get('is_flagged', 'false').lower() in ('true', 'yes', '1'),
                folder="inbox",
                message_id=message_id if message_id else None,
                thread_id=message_id if message_id else None
            )
            
            return email
            
        except Exception as e:
            logger.error(f"❌ Error parsing AppleScript record '{record_str[:100]}...': {e}")
            return None

    def parse_folders_from_applescript(self, applescript_result: str) -> List[str]:
        """Parse AppleScript folder output into de-duplicated folder names.

        Mail.app returns newline-delimited names (so account/folder names may contain
        commas); Outlook returns a single comma-delimited line. Prefer newline
        splitting and fall back to commas only when the output is a single line, so
        both clients parse correctly. Names are de-duplicated case-insensitively while
        preserving first-seen order.
        """
        try:
            raw = applescript_result or ""
            lines = [line.strip() for line in raw.splitlines()]
            lines = [line for line in lines if line]
            if len(lines) <= 1:
                source = lines[0] if lines else raw
                lines = [part.strip() for part in source.split(',')]
            seen = set()
            folders: List[str] = []
            for name in lines:
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                folders.append(name)
            return folders
        except Exception as e:
            logger.error(f"❌ Error parsing folders from AppleScript: {e}")
            return []

    @staticmethod
    def parse_date(date_str: str) -> datetime:
        """Parse date string from AppleScript into datetime object.
        
        Mail.app returns dates in macOS locale format, typically:
        "Saturday, April 5, 2026 at 10:30:00 AM"
        """
        if not date_str or date_str.lower() in ['missing value', '']:
            return datetime.now()
        
        formats = [
            '%A, %B %d, %Y at %I:%M:%S %p',   # Saturday, April 5, 2026 at 10:30:00 AM
            '%B %d, %Y at %I:%M:%S %p',         # April 5, 2026 at 10:30:00 AM
            '%A, %B %d, %Y at %H:%M:%S',        # Saturday, April 5, 2026 at 22:30:00
            '%Y-%m-%d %H:%M:%S %z',              # 2026-04-05 10:30:00 +0000
            '%Y-%m-%dT%H:%M:%S',                 # 2026-04-05T10:30:00
            '%m/%d/%Y %I:%M:%S %p',              # 04/05/2026 10:30:00 AM
            '%d/%m/%Y %H:%M:%S',                 # 05/04/2026 10:30:00
        ]
        
        cleaned = date_str.strip()
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        
        logger.warning(f"Could not parse Mail.app date '{date_str}' with any known format, falling back to now()")
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
