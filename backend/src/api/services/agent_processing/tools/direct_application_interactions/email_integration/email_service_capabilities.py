"""
Email Service Capabilities

Agent introspection metadata: execution principles, method signatures,
data structure schemas, and usage examples. Consumed by the agent to
understand how to use the email service.
"""

import inspect
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


# Why these slim docs:
# - The 14 email methods only have to discriminate against EACH OTHER once
#   the agent has decided email is the right family - so each slim_doc
#   surfaces (a) what shape of email work this method is for, and (b) which
#   sibling method to use instead when this is the wrong choice.
# - KEEPS the load-bearing safety invariants from execution_principles
#   inline on the method that owns them: 'recipient must be an explicit
#   email address' on create_new_email_draft, 'reference_email_id must come
#   from a located source email' on create_reply_email_draft, 'direct
#   sending is disabled - drafts only' on both draft methods, the 30-day
#   default window on get_inbox_emails, and the 'prefer the new compact
#   tools over the legacy create_email_draft / reply_to_email' invariant
#   on the legacy methods themselves.
# - DROPS the dynamic Pydantic schema (still rendered by LangChain), the
#   data-structure inventory (kept in capabilities["data_structures"] for
#   non-slim profiles), and the usage_examples block (each method's slim_doc
#   carries the discriminating example inline).
# - Each entry is a single line. No newlines.
_SLIM_DOCS_BY_METHOD: Dict[str, str] = {
    "get_emails": (
        "Retrieve emails from any folder using server-side filters. For the "
        "inbox specifically use get_inbox_emails (which applies a 30-day "
        "default window). For criteria-driven search use search_emails."
    ),
    "get_email_metadata": (
        "Get lightweight email headers (sender, subject, date, ids) without "
        "bodies; use this when listing emails for the user. Pair with "
        "expand_email_details to fetch the body of a specific email."
    ),
    "expand_email_details": (
        "Fetch the full body of one email by id; use after get_email_metadata "
        "or search_emails when you actually need the message content (e.g. to "
        "summarize or draft a reply). Loading bodies for many emails up front "
        "is expensive - prefer headers + selective expand."
    ),
    "process_email_request": (
        "High-level natural-language router for an email request; prefer the "
        "specific email tools (search_emails, create_new_email_draft, "
        "create_reply_email_draft, organize_emails). Use this only when the "
        "user's request is too unstructured for the specific tools."
    ),
    "organize_emails": (
        "Apply one organization operation (move / delete / mark_read / "
        "mark_unread / flag / unflag / archive) to one or more email_ids. "
        "Use bulk_organize_emails when you have multiple distinct operations "
        "to apply in one batch."
    ),
    "search_emails": (
        "Search emails by structured criteria (sender, subject_contains, "
        "body_contains, date range, is_read, is_flagged, folder, "
        "has_attachments). Use this when the user's request includes a "
        "discriminating filter; for the inbox-only listing use "
        "get_inbox_emails."
    ),
    "get_folders": (
        "List the email client's folders / mailboxes (Inbox, Sent, custom "
        "labels). Call this before organize_emails / bulk_organize_emails "
        "when the target folder name is not known to be exact."
    ),
    "create_folder": (
        "Create a new email folder / mailbox in the client. Idempotent on "
        "existing names: if the folder already exists, the call is a no-op."
    ),
    "bulk_organize_emails": (
        "Apply many organize operations in one batch (e.g. mark several "
        "threads read AND move others to folders in the same call). Each "
        "item is an EmailOperation with operation, email_ids, optional "
        "target_folder."
    ),
    "create_email_draft": (
        "Legacy draft endpoint; prefer create_new_email_draft (for new "
        "emails) or create_reply_email_draft (for replies), which have "
        "compact validated inputs and clearer safety contracts."
    ),
    "get_inbox_emails": (
        "List emails from the INBOX specifically. A 30-day window is applied "
        "automatically unless skip_default_filter=True. Use "
        "deduplicate_threads=True to collapse a conversation to its most "
        "recent message."
    ),
    "reply_to_email": (
        "Legacy reply endpoint; prefer create_reply_email_draft, which "
        "requires a stable reference_email_id (no display-name guesses) and "
        "produces a visible draft for manual review. For Outlook, a "
        "SUCCESS return means the AppleScript completed without error and "
        "the draft was handed off to Outlook's Drafts folder; programmatic "
        "readback of the new draft is intentionally skipped because it "
        "hangs the AppleEvent layer. Tell the user the draft is in their "
        "Drafts folder for confirmation rather than claiming a verified send."
    ),
    "create_new_email_draft": (
        "Create a NEW (non-reply) email draft with a compact validated "
        "input. recipient MUST be an explicit email address; display names "
        "alone are not acceptable. Direct sending is disabled - this creates "
        "a visible draft for the user to review and send manually."
    ),
    "create_reply_email_draft": (
        "Create a REPLY draft to an existing email with a compact validated "
        "input. reference_email_id MUST come from a located source email "
        "(e.g. via search_emails or get_inbox_emails); never infer it from a "
        "display name or thread title alone. Direct sending is disabled - "
        "this creates a visible draft for manual review. For Outlook, a "
        "SUCCESS return means the AppleScript completed without error and "
        "the draft was handed off to Outlook's Drafts folder; programmatic "
        "readback of the new draft is intentionally skipped because that "
        "readback hangs the AppleEvent layer (well-known Outlook-for-Mac "
        "issue). When reporting outcomes for Outlook replies, state that "
        "drafts were created and ask the user to confirm them in the "
        "Drafts folder, rather than claiming the drafts were independently "
        "verified."
    ),
}


def build_service_capabilities(service) -> Dict[str, Any]:
    """
    Build service method signatures and parameter information for intelligent operation planning.
    
    Args:
        service: The EmailClientService instance to introspect
        
    Returns:
        Dictionary containing method signatures, parameters, and data structure definitions
    """
    capabilities = {
        "description": "Email automation and management operations",
        "methods": {},
        "data_structures": {},
        "execution_principles": [
            "EMAIL WRITE CONTRACTS: Use create_new_email_draft for new drafts and create_reply_email_draft for replies; these tools have compact validated inputs.",
            "REPLY SAFETY: Replies require a stable reference_email_id from a found email. Do not draft replies from display names or inferred people alone.",
            "OUTLOOK DRAFT VERIFICATION: For Microsoft Outlook, draft creation tools deliberately do not read the draft back after writing it (AppleScript readback against an unsent Outlook draft hangs the AppleEvent layer; this is a known Outlook-for-Mac issue). A SUCCESS return from a create_*_email_draft call means the AppleScript completed without error and Outlook accepted the draft; the draft is then in the user's Drafts folder. When summarizing results for Outlook, report drafts as created and ask the user to confirm them in the Drafts folder rather than claiming the drafts were programmatically verified. Do not retry the call to 'double check' a successful Outlook draft creation; that retry has no verification value and risks producing duplicates.",
            "RECIPIENT SAFETY: New drafts require explicit recipient email addresses. Display names alone are unresolved contacts, not final recipients.",
            "CONTRACT FAILURE: If an email draft tool rejects ambiguous inputs, resolve the missing email/message id instead of falling back to raw AppleScript composition. This restriction applies ONLY to composing or sending mail; read-only inspection the email tools do not expose (for example, reading a message's raw headers to assess phishing or authenticity) is a legitimate use of AppleScript/shell and must not be refused.",
            "SAFETY: Direct sending is disabled. Email write operations create visible drafts for manual review.",
            "DEFAULT FILTER: When no date criteria are provided for inbox queries, a 30-day window is applied automatically. Pass skip_default_filter=True to retrieve the entire inbox.",
            "CLIENT SELECTION: Use client_name to target a specific email client. If omitted, the primary detected client is used.",
            "THREAD DEDUPLICATION: Use deduplicate_threads=True when listing, summarizing, or replying to emails to collapse conversations to the most recent message per thread",
        ],
        "usage_examples": {
            "get_inbox_emails": "email_service.get_inbox_emails(limit=5, filter_read=False) # Get 5 unread emails",
            "create_new_email_draft": "email_service.create_new_email_draft(recipient='user@example.com', subject='Meeting', body='Thanks for the email...')",
            "create_reply_email_draft": "email_service.create_reply_email_draft(reference_email_id='12345', reply_body='Thanks for the update.', reply_all=True)"
        },
        "parameter_construction_notes": {
            "create_new_email_draft": "Pass direct flat fields. recipient must be an explicit email address.",
            "create_reply_email_draft": "Pass direct flat fields. reference_email_id must come from a located source email."
        }
    }
    
    public_methods = [
        'get_emails', 'get_email_metadata', 'expand_email_details',
        'process_email_request', 'organize_emails', 'search_emails',
        'get_folders', 'create_folder', 'bulk_organize_emails', 'create_email_draft',
        'get_inbox_emails', 'reply_to_email', 'create_new_email_draft',
        'create_reply_email_draft'
    ]
    
    for method_name in public_methods:
        if hasattr(service, method_name):
            method = getattr(service, method_name)
            try:
                signature = inspect.signature(method)
                parameters = {}
                
                for param_name, param in signature.parameters.items():
                    if param_name != 'self':
                        parameters[param_name] = {
                            "type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
                            "default": str(param.default) if param.default != inspect.Parameter.empty else None,
                            "required": param.default == inspect.Parameter.empty
                        }
                
                capabilities["methods"][method_name] = {
                    "signature": str(signature),
                    "parameters": parameters,
                    "doc": method.__doc__ or "No documentation available",
                    "slim_doc": _SLIM_DOCS_BY_METHOD.get(method_name, ""),
                }
            except Exception as e:
                logger.warning(f"Could not inspect method {method_name}: {e}")
    
    capabilities["data_structures"] = {
        "EmailRequest": {
            "fields": {
                "recipient": {"type": "str", "required": True, "description": "Email recipient address"},
                "subject": {"type": "str", "required": True, "description": "Email subject line"},
                "body": {"type": "str", "required": True, "description": "Email body content"},
                "action": {"type": "str", "required": False, "description": "Action type: 'draft' or 'forward'. Direct send is disabled; use visible drafts for manual review."},
                "reference_email_id": {"type": "Optional[str]", "required": False, "description": "ID of original email if replying/forwarding"},
                "cc": {"type": "List[str]", "required": False, "description": "CC recipients"},
                "bcc": {"type": "List[str]", "required": False, "description": "BCC recipients"},
                "attachments": {"type": "List[str]", "required": False, "description": "File paths for attachments"}
            },
            "module_path": "api.services.direct_application_interactions.email_integration.email_models.EmailRequest",
            "construction_example": "EmailRequest(recipient='user@example.com', subject='Re: Meeting', body='Response text', action='draft', reference_email_id='12345')"
        },
        "DraftRequest": {
            "fields": {
                "recipient": {"type": "str", "required": True, "description": "Email recipient address"},
                "subject": {"type": "str", "required": True, "description": "Email subject line"},
                "body": {"type": "str", "required": True, "description": "Email body content"},
                "reference_email_id": {"type": "Optional[str]", "required": False, "description": "ID of original email if replying"},
                "is_reply": {"type": "bool", "required": False, "description": "Whether this is a reply to an existing email"}
            },
            "module_path": "api.services.direct_application_interactions.email_integration.email_models.DraftRequest", 
            "construction_example": "DraftRequest(recipient='user@example.com', subject='Re: Meeting', body='Response text', reference_email_id='12345', is_reply=True)"
        },
        "EmailSearchCriteria": {
            "description": "Represents search criteria for finding emails",
            "module_path": "api.services.direct_application_interactions.email_integration.email_models.EmailSearchCriteria",
            "fields": {
                "sender": {"type": "Optional[str]", "default": "None"},
                "subject_contains": {"type": "Optional[str]", "default": "None"},
                "body_contains": {"type": "Optional[str]", "default": "None"},
                "date_from": {"type": "Optional[datetime]", "default": "None"},
                "date_to": {"type": "Optional[datetime]", "default": "None"},
                "is_read": {"type": "Optional[bool]", "default": "None"},
                "is_flagged": {"type": "Optional[bool]", "default": "None"},
                "folder": {"type": "Optional[str]", "default": "None"},
                "has_attachments": {"type": "Optional[bool]", "default": "None"}
            }
        },
        "EmailOperation": {
            "description": "Represents an email organization operation",
            "module_path": "api.services.direct_application_interactions.email_integration.email_models.EmailOperation",
            "fields": {
                "operation": {"type": "str", "required": True, "options": ["move", "delete", "mark_read", "mark_unread", "flag", "unflag", "archive"]},
                "email_ids": {"type": "List[str]", "required": True},
                "target_folder": {"type": "Optional[str]", "default": "None"}
            }
        }
    }
    
    return capabilities
