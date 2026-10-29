"""
Email Thread Utilities

Provides thread detection and deduplication logic for email conversations.
Ensures only the most recent email from each thread is returned when requested.
"""

import logging
import hashlib
from typing import List, Dict, Optional
from datetime import datetime
from .email_models import EmailData

logger = logging.getLogger(__name__)


def deduplicate_email_threads(emails: List[EmailData]) -> List[EmailData]:
    """
    Deduplicate emails by thread, keeping only the most recent email from each thread.
    
    Thread detection strategy:
    1. Use thread_id if available (Outlook conversation ID or Mail.app message-id)
    2. Fall back to subject + sender combination if thread_id is missing
    
    Args:
        emails: List of EmailData objects to deduplicate
        
    Returns:
        List of EmailData objects with only the most recent email per thread
    """
    if not emails:
        return []
    
    logger.info(f"📧 Deduplicating {len(emails)} emails by thread...")
    
    # Group emails by thread
    threads: Dict[str, List[EmailData]] = {}
    
    for email in emails:
        thread_key = _get_thread_key(email)
        
        if thread_key not in threads:
            threads[thread_key] = []
        
        threads[thread_key].append(email)
    
    logger.info(f"📧 Found {len(threads)} unique threads")
    
    # For each thread, keep only the most recent email
    deduplicated_emails = []
    
    for thread_key, thread_emails in threads.items():
        # Sort by date_sent (most recent first)
        thread_emails.sort(key=lambda e: e.date_sent, reverse=True)
        
        most_recent = thread_emails[0]
        deduplicated_emails.append(most_recent)
        
        if len(thread_emails) > 1:
            logger.debug(f"📧 Thread '{thread_key[:50]}...' had {len(thread_emails)} emails, kept most recent from {most_recent.date_sent}")
    
    # Sort deduplicated emails by date (most recent first)
    deduplicated_emails.sort(key=lambda e: e.date_sent, reverse=True)
    
    logger.info(f"📧 Deduplicated to {len(deduplicated_emails)} emails (removed {len(emails) - len(deduplicated_emails)} duplicates)")
    
    return deduplicated_emails


def _get_thread_key(email: EmailData) -> str:
    """
    Generate a unique thread key for an email.
    
    Strategy:
    1. Use thread_id if available (Outlook conversation ID or Mail.app message-id)
    2. Fall back to normalized subject + sender combination
    
    Args:
        email: EmailData object
        
    Returns:
        Unique thread key string
    """
    # Strategy 1: Use thread_id if available
    if email.thread_id:
        return f"thread_id:{email.thread_id}"
    
    # Strategy 2: Fall back to subject + sender
    # Normalize subject by removing common reply/forward prefixes
    normalized_subject = _normalize_subject(email.subject)
    
    # Create a hash of subject + sender for thread key
    thread_key_str = f"{normalized_subject}|{email.sender}"
    thread_hash = hashlib.md5(thread_key_str.encode()).hexdigest()[:16]
    
    logger.debug(f"📧 Using fallback thread key for email '{email.subject[:30]}...': subject_sender:{thread_hash}")
    
    return f"subject_sender:{thread_hash}"


def _normalize_subject(subject: str) -> str:
    """
    Normalize email subject by removing reply/forward prefixes.
    
    Removes common prefixes like:
    - Re:
    - RE:
    - Fwd:
    - FW:
    - [External]
    - Multiple nested prefixes (e.g., "Re: Re: Re:")
    
    Args:
        subject: Original email subject
        
    Returns:
        Normalized subject string
    """
    if not subject:
        return ""
    
    normalized = subject.strip()
    
    # Remove common prefixes repeatedly until none remain
    prefixes = ['re:', 'RE:', 'Re:', 'fwd:', 'FWD:', 'Fwd:', 'fw:', 'FW:', 'Fw:', '[external]', '[External]', '[EXTERNAL]']
    
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if normalized.lower().startswith(prefix.lower()):
                normalized = normalized[len(prefix):].strip()
                changed = True
                break
    
    return normalized


def group_emails_by_thread(emails: List[EmailData]) -> Dict[str, List[EmailData]]:
    """
    Group emails by thread without deduplication.
    
    Useful for displaying full conversation history.
    
    Args:
        emails: List of EmailData objects to group
        
    Returns:
        Dictionary mapping thread keys to lists of emails in that thread
    """
    threads: Dict[str, List[EmailData]] = {}
    
    for email in emails:
        thread_key = _get_thread_key(email)
        
        if thread_key not in threads:
            threads[thread_key] = []
        
        threads[thread_key].append(email)
    
    # Sort emails within each thread by date (oldest first for conversation flow)
    for thread_key in threads:
        threads[thread_key].sort(key=lambda e: e.date_sent)
    
    return threads


def get_thread_for_email(email: EmailData, all_emails: List[EmailData]) -> List[EmailData]:
    """
    Get all emails in the same thread as the given email.
    
    Args:
        email: The email to find the thread for
        all_emails: All available emails to search through
        
    Returns:
        List of EmailData objects in the same thread, sorted chronologically
    """
    target_thread_key = _get_thread_key(email)
    
    thread_emails = [
        e for e in all_emails
        if _get_thread_key(e) == target_thread_key
    ]
    
    # Sort chronologically (oldest first)
    thread_emails.sort(key=lambda e: e.date_sent)
    
    return thread_emails

