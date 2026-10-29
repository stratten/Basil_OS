"""Tool registry plus the ``list_tools`` and ``call_tool`` entry points.

``MCPClientService`` calls these for a Gmail connection that uses the direct
Gmail API. Both return what the remote path returns: ``list_tools`` the catalog
dict, ``call_tool`` a normalized envelope. The tool names match Google's hosted
Gmail MCP server, plus ``send_draft``, so the agent cannot tell which one it is
talking to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

from ..error_normalizer import (
    ERROR_KIND_AUTH_EXPIRED,
    ERROR_KIND_INVALID_ARGUMENTS,
    ERROR_KIND_NETWORK_ERROR,
    ERROR_KIND_NOT_FOUND,
    ERROR_KIND_PERMISSION_DENIED,
    ERROR_KIND_SERVER_ERROR,
    ERROR_KIND_TIMEOUT,
    make_envelope,
    make_success,
)
from . import connection_probe, handlers_attachments, handlers_read, handlers_write, schemas
from .error_mapping import RECONNECT_ACTION, normalize_gmail_api_error
from .gmail_api import GmailApiClient, GmailApiError, ToolArgumentError

logger = logging.getLogger(__name__)

_SERVER_NAME = "basil-gmail-api"
_SERVER_VERSION = "0.1.0"
_PROTOCOL_VERSION = "2024-11-05"

Handler = Callable[[GmailApiClient, dict], Awaitable[dict]]

_SUMMARY_NOTE = " Always fill summary with the sender and subject so the user can recognize what they are approving."


@dataclass(frozen=True)
class _ToolDescriptor:
    name: str
    description: str
    is_read_only_hint: bool
    input_model: Type[BaseModel]
    handler: Handler


def _read(name: str, description: str, model: Type[BaseModel], handler: Handler) -> _ToolDescriptor:
    return _ToolDescriptor(name, description, True, model, handler)


def _write(name: str, description: str, model: Type[BaseModel], handler: Handler) -> _ToolDescriptor:
    return _ToolDescriptor(name, description, False, model, handler)


_TOOL_REGISTRY: List[_ToolDescriptor] = [
    _read(
        "search_threads",
        "Lists email threads from the user's Gmail account that match a Gmail search query, newest first, with up to 5 recent messages per thread (sender, recipients, date, labels, subject, snippet). Full bodies are not returned: use get_thread with a thread id. Results page with nextPageToken. Archived and sent mail is included; drafts are excluded unless the query says in:draft.",
        schemas.SearchThreadsInput,
        handlers_read.handle_search_threads,
    ),
    _read(
        "get_thread",
        "Retrieves one email thread with every message, including each message id. PLAIN_TEXT is the recommended messageFormat. Drafts are omitted: use list_drafts.",
        schemas.GetThreadInput,
        handlers_read.handle_get_thread,
    ),
    _read(
        "get_message",
        "Retrieves one email message by id: use it to read the exact wording or attachment names of a single message. For a conversation use get_thread. PLAIN_TEXT is the recommended messageFormat.",
        schemas.GetMessageInput,
        handlers_read.handle_get_message,
    ),
    _read(
        "list_drafts",
        "Lists the user's draft emails, optionally filtered by a Gmail query. DRAFT_VIEW_FULL adds subject and body.",
        schemas.ListDraftsInput,
        handlers_read.handle_list_drafts,
    ),
    _read(
        "get_draft",
        "Retrieves one draft by id, with a link to open and edit it in Gmail.",
        schemas.GetDraftInput,
        handlers_read.handle_get_draft,
    ),
    _read(
        "list_labels",
        "Lists every label with its id, name, and type. Use it to find a label id before labeling or unlabeling. System labels include INBOX, UNREAD, STARRED, IMPORTANT, SENT, DRAFT, TRASH, SPAM and the CATEGORY_* inbox tabs.",
        schemas.ListLabelsInput,
        handlers_read.handle_list_labels,
    ),
    _write(
        "create_draft",
        "Creates a draft email in the user's Gmail account. It is saved in Drafts and is NOT sent; the user reviews and edits it in Gmail, or you can send it with send_draft after the user approves. Give plain recipient addresses, a subject, and a plain-text body without Markdown (htmlBody for rich text). To answer an email pass replyToMessageId and leave to and cc out: the draft joins that thread and goes to everyone on the original, as Reply All does (the user is never added). Reply to everyone unless the user asked to reply to the sender alone, in which case set replyAll to false. The result lists the To and Cc addresses it chose; send_draft needs exactly those. Write only the new reply text: the original message and the earlier thread are not quoted into the draft, so never paste or summarize them into the body. To attach a file, pass attachments with each file's path (an absolute path such as /Users/name/Documents/report.pdf, including files you saved or created in this task); Basil reads the file itself, so never base64-encode a file into the call. The combined attachments may total 25 MB. Returns the draft id, threadId, and a link." + _SUMMARY_NOTE,
        schemas.CreateDraftInput,
        handlers_write.handle_create_draft,
    ),
    _write(
        "send_draft",
        "Sends an existing draft. It cannot compose a new message: create a draft first, then send it. You must pass the draft's exact recipients (To, Cc, and Bcc) and subject, which the user sees in the approval prompt, and the send is refused if they do not match the draft. Sending cannot be undone." + _SUMMARY_NOTE,
        schemas.SendDraftInput,
        handlers_write.handle_send_draft,
    ),
    _write(
        "download_attachment",
        "Saves one attachment of an email to the user's computer and returns the saved file's path. The file's contents are NOT returned: open the saved file with the file tools. Identify the attachment with its exact filename from get_message, or with its partId when two attachments share a name. Do not rely on attachmentId: Gmail changes it on every fetch. By default the file goes into this task's workspace folder; set destinationFolder (an absolute path) only when the user asked for it to be saved somewhere else, and saveAs only to rename it. An existing file is never replaced: a name clash saves as 'name (1).ext'. Attachments up to 50 MB." + _SUMMARY_NOTE,
        schemas.DownloadAttachmentInput,
        handlers_attachments.handle_download_attachment,
    ),
    _write(
        "label_thread",
        "Adds labels to every message in a thread. To archive, use unlabel_thread with INBOX. To delete use trash_thread, and for Spam use mark_thread_spam: TRASH and SPAM are refused here." + _SUMMARY_NOTE,
        schemas.ThreadLabelsInput,
        handlers_write.handle_label_thread,
    ),
    _write(
        "unlabel_thread",
        "Removes labels from every message in a thread. Remove UNREAD to mark it read, or INBOX to archive it." + _SUMMARY_NOTE,
        schemas.ThreadLabelsInput,
        handlers_write.handle_unlabel_thread,
    ),
    _write(
        "apply_sensitive_thread_label",
        "Prefer trash_thread or mark_thread_spam. Applies TRASH or SPAM to one thread." + _SUMMARY_NOTE,
        schemas.SensitiveThreadLabelInput,
        handlers_write.handle_apply_sensitive_thread_label,
    ),
    _write(
        "trash_thread",
        "Moves an entire thread to Trash. This is the tool for 'delete', 'remove' or 'get rid of' an email conversation. Trash is recoverable for 30 days (untrash_thread restores it); Basil has no permanent delete." + _SUMMARY_NOTE,
        schemas.ThreadActionInput,
        handlers_write.handle_trash_thread,
    ),
    _write(
        "untrash_thread",
        "Restores a thread from Trash." + _SUMMARY_NOTE,
        schemas.RestoreThreadInput,
        handlers_write.handle_untrash_thread,
    ),
    _write(
        "mark_thread_spam",
        "Marks an entire thread as Spam and takes it out of the inbox." + _SUMMARY_NOTE,
        schemas.ThreadActionInput,
        handlers_write.handle_mark_thread_spam,
    ),
    _write(
        "unmark_thread_spam",
        "Moves a thread out of Spam and back to the inbox." + _SUMMARY_NOTE,
        schemas.RestoreThreadInput,
        handlers_write.handle_unmark_thread_spam,
    ),
    _write(
        "label_message",
        "Adds labels to one message. TRASH and SPAM are refused here: use trash_message or mark_message_spam." + _SUMMARY_NOTE,
        schemas.MessageLabelsInput,
        handlers_write.handle_label_message,
    ),
    _write(
        "update_message_labels",
        "Adds and removes labels on one message in a single step, such as moving it between labels. TRASH and SPAM cannot be added here." + _SUMMARY_NOTE,
        schemas.UpdateMessageLabelsInput,
        handlers_write.handle_update_message_labels,
    ),
    _write(
        "unlabel_message",
        "Removes labels from one message." + _SUMMARY_NOTE,
        schemas.MessageLabelsInput,
        handlers_write.handle_unlabel_message,
    ),
    _write(
        "apply_sensitive_message_label",
        "Prefer trash_message or mark_message_spam. Applies TRASH or SPAM to one message." + _SUMMARY_NOTE,
        schemas.SensitiveMessageLabelInput,
        handlers_write.handle_apply_sensitive_message_label,
    ),
    _write(
        "trash_message",
        "Moves one message to Trash. For a whole conversation prefer trash_thread. Trash is recoverable for 30 days (untrash_message restores it); Basil has no permanent delete." + _SUMMARY_NOTE,
        schemas.MessageActionInput,
        handlers_write.handle_trash_message,
    ),
    _write(
        "untrash_message",
        "Restores one message from Trash." + _SUMMARY_NOTE,
        schemas.RestoreMessageInput,
        handlers_write.handle_untrash_message,
    ),
    _write(
        "mark_message_spam",
        "Marks one message as Spam and takes it out of the inbox." + _SUMMARY_NOTE,
        schemas.MessageActionInput,
        handlers_write.handle_mark_message_spam,
    ),
    _write(
        "unmark_message_spam",
        "Moves one message out of Spam and back to the inbox." + _SUMMARY_NOTE,
        schemas.RestoreMessageInput,
        handlers_write.handle_unmark_message_spam,
    ),
    _write(
        "create_label",
        "Creates a label. Nested names such as Projects/Alpha create missing parents by default." + _SUMMARY_NOTE,
        schemas.CreateLabelInput,
        handlers_write.handle_create_label,
    ),
]


def _find_tool(name: str) -> Optional[_ToolDescriptor]:
    return next((tool for tool in _TOOL_REGISTRY if tool.name == name), None)


async def list_tools(*, access_token: Optional[str] = None) -> Dict[str, Any]:
    """Return the catalog payload ``MCPClientService.list_tools`` produces for a remote server."""
    return {
        "server": {"name": _SERVER_NAME, "version": _SERVER_VERSION, "protocol": _PROTOCOL_VERSION, "instructions": None},
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
                "is_read_only_hint": tool.is_read_only_hint,
            }
            for tool in _TOOL_REGISTRY
        ],
    }


async def call_tool(
    *,
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    access_token: Optional[str],
) -> Dict[str, Any]:
    """Run one tool and return a normalized envelope; failures never raise."""
    if not access_token:
        return make_envelope(
            kind=ERROR_KIND_AUTH_EXPIRED,
            message="The Gmail connection has no access token.",
            retryable=False,
            user_action_required=RECONNECT_ACTION,
        )
    descriptor = _find_tool(tool_name)
    if descriptor is None:
        return make_envelope(
            kind=ERROR_KIND_NOT_FOUND,
            message=f"No such Gmail tool: {tool_name!r}.",
            retryable=False,
            raw={"available_tools": [tool.name for tool in _TOOL_REGISTRY]},
        )
    try:
        async with GmailApiClient(access_token) as api:
            shaped = await descriptor.handler(api, arguments or {})
    except ValidationError as exc:
        return make_envelope(
            kind=ERROR_KIND_INVALID_ARGUMENTS,
            message=f"Invalid arguments for {tool_name}: {exc.errors(include_url=False, include_context=False, include_input=False)}",
            retryable=False,
            raw={"errors": exc.errors(include_url=False, include_context=False, include_input=False)},
        )
    except ToolArgumentError as exc:
        return make_envelope(kind=ERROR_KIND_INVALID_ARGUMENTS, message=str(exc), retryable=False)
    except GmailApiError as exc:
        return normalize_gmail_api_error(exc, tool_name=tool_name)
    except httpx.TimeoutException:
        return make_envelope(
            kind=ERROR_KIND_TIMEOUT,
            message=f"Gmail did not answer {tool_name} in time.",
            retryable=True,
        )
    except httpx.HTTPError as exc:
        return make_envelope(
            kind=ERROR_KIND_NETWORK_ERROR,
            message=f"Could not reach Gmail for {tool_name}: {type(exc).__name__}.",
            retryable=True,
        )
    except Exception as exc:
        logger.exception("Unhandled exception in gmail_local_server.%s", tool_name)
        return make_envelope(
            kind=ERROR_KIND_SERVER_ERROR,
            message=f"Gmail tool {tool_name} failed: {type(exc).__name__}: {exc}",
            retryable=False,
            raw={"exc_type": type(exc).__name__},
        )
    return make_success(shaped)


async def verified_list_tools(*, access_token: Optional[str]) -> Dict[str, Any]:
    """Confirm with Google that the sign-in works and carries Gmail access, then return the catalog as a success envelope.

    ``list_tools`` alone never contacts Google, so a revoked or under-scoped token would still look healthy. Any failure comes back as the same normalized envelope a tool call would return, with a reconnect instruction where reconnecting helps.
    """
    if not access_token:
        return make_envelope(
            kind=ERROR_KIND_AUTH_EXPIRED,
            message="The Gmail connection has no access token.",
            retryable=False,
            user_action_required=RECONNECT_ACTION,
        )
    try:
        details = await connection_probe.describe_connection(access_token)
    except GmailApiError as exc:
        return normalize_gmail_api_error(exc, tool_name="the connection check")
    except httpx.TimeoutException:
        return make_envelope(kind=ERROR_KIND_TIMEOUT, message="Google did not answer the Gmail connection check in time.", retryable=True)
    except httpx.HTTPError as exc:
        return make_envelope(
            kind=ERROR_KIND_NETWORK_ERROR,
            message=f"Could not reach Google to check the Gmail connection: {type(exc).__name__}.",
            retryable=True,
        )
    if not details.has_required_access:
        granted = ", ".join(details.scope_labels) or "no Gmail permissions"
        return make_envelope(
            kind=ERROR_KIND_PERMISSION_DENIED,
            message=f"The Gmail sign-in does not include gmail.modify, which Basil needs to read, draft, label, and trash mail. Google granted: {granted}.",
            retryable=False,
            user_action_required=(
                "Reconnect Gmail in Settings → Connections and approve every permission Google lists, "
                "so Basil receives the access it needs."
            ),
            raw={"granted_scopes": details.granted_scopes},
        )
    catalog = await list_tools(access_token=access_token)
    mailbox = details.account or "an unknown mailbox"
    catalog["server"]["account_summary"] = f"Signed in as {mailbox} with {', '.join(details.scope_labels)}."
    return make_success(catalog)


__all__ = ["call_tool", "list_tools", "verified_list_tools"]
