"""Handlers that change the mailbox: drafts, sending, labels, Trash, and Spam.

Every tool here has a ``False`` read-only hint, so Basil's connection policy
asks the user before each call unless they have switched that tool to always
allow. Deleting is always Trash (recoverable for 30 days); the connector has no
permanent delete, and the scope Basil requests could not perform one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

from .attachment_files import read_attachment_file
from .gmail_api import GmailApiClient, ToolArgumentError
from .message_shaping import (
    bare_addresses,
    header_map,
    view_url,
)
from .mime_builder import ReplyContext, build_raw_draft
from .reply_recipients import plan_reply_recipients
from .schemas import (
    CreateDraftInput,
    CreateLabelInput,
    DraftAttachment,
    MessageActionInput,
    MessageLabelsInput,
    SendDraftInput,
    SensitiveMessageLabelInput,
    SensitiveThreadLabelInput,
    ThreadActionInput,
    ThreadLabelsInput,
    UpdateMessageLabelsInput,
)

logger = logging.getLogger(__name__)

_PROTECTED_LABELS = {"TRASH", "SPAM"}
"""Labels the generic label tools refuse to add, so moving mail to Trash or Spam always goes through a tool whose name says so."""

_TRASH_NOTE = "It stays in Trash for 30 days and can be restored."

_LABEL_LIST_VISIBILITY = {
    "LABEL_SHOW": "labelShow",
    "LABEL_SHOW_IF_UNREAD": "labelShowIfUnread",
    "LABEL_HIDE": "labelHide",
}

LABEL_COLOR_PRESETS: Dict[str, Dict[str, str]] = {
    "LABEL_COLOR_PRESET_BLACK": {"backgroundColor": "#000000", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_DARK_GRAY": {"backgroundColor": "#434343", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_GRAY": {"backgroundColor": "#666666", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_LIGHT_GRAY": {"backgroundColor": "#cccccc", "textColor": "#000000"},
    "LABEL_COLOR_PRESET_WHITE": {"backgroundColor": "#ffffff", "textColor": "#000000"},
    "LABEL_COLOR_PRESET_RED": {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_ORANGE": {"backgroundColor": "#ffad47", "textColor": "#000000"},
    "LABEL_COLOR_PRESET_YELLOW": {"backgroundColor": "#fad165", "textColor": "#000000"},
    "LABEL_COLOR_PRESET_GREEN": {"backgroundColor": "#16a765", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_MINT": {"backgroundColor": "#43d692", "textColor": "#000000"},
    "LABEL_COLOR_PRESET_TEAL": {"backgroundColor": "#2da2bb", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_BLUE": {"backgroundColor": "#4a86e8", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_PURPLE": {"backgroundColor": "#a479e2", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_PINK": {"backgroundColor": "#f691b2", "textColor": "#000000"},
    "LABEL_COLOR_PRESET_DARK_RED": {"backgroundColor": "#822111", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_DARK_ORANGE": {"backgroundColor": "#a46a21", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_DARK_GREEN": {"backgroundColor": "#076239", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_DARK_BLUE": {"backgroundColor": "#1c4587", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_DARK_PURPLE": {"backgroundColor": "#41236d", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_DARK_PINK": {"backgroundColor": "#83334c", "textColor": "#ffffff"},
    "LABEL_COLOR_PRESET_BROWN": {"backgroundColor": "#7a4706", "textColor": "#ffffff"},
}


def _refuse_protected_labels(label_ids: List[str]) -> None:
    protected = sorted({label for label in label_ids if label.upper() in _PROTECTED_LABELS})
    if protected:
        raise ToolArgumentError(
            f"Adding {', '.join(protected)} through a label tool is not allowed. "
            "Use trash_thread or trash_message to delete, and mark_thread_spam or mark_message_spam for Spam."
        )


async def _default_signature_html(api: GmailApiClient) -> Optional[str]:
    """The user's default Gmail signature as HTML, or nothing when none is set."""
    listing = await api.request("GET", "/settings/sendAs")
    send_as = listing.get("sendAs") or []
    chosen = next((entry for entry in send_as if entry.get("isDefault")), send_as[0] if send_as else {})
    signature = str(chosen.get("signature") or "").strip()
    return signature or None


async def _own_addresses(api: GmailApiClient) -> Set[str]:
    """The user's own addresses (the account and its send-as aliases), so a reply never addresses them.

    A lookup that fails leaves the set smaller rather than failing the draft: the user reviews every draft, and an extra copy to themselves is harmless.
    """
    profile, send_as = await asyncio.gather(
        api.request("GET", "/profile"),
        api.request("GET", "/settings/sendAs"),
        return_exceptions=True,
    )
    own: Set[str] = set()
    if isinstance(profile, dict):
        own.update(bare_addresses(str(profile.get("emailAddress") or "")))
    elif isinstance(profile, Exception):
        logger.warning("Could not read the Gmail profile to exclude the user from a reply: %s", profile)
    if isinstance(send_as, dict):
        for entry in send_as.get("sendAs") or []:
            own.update(bare_addresses(str(entry.get("sendAsEmail") or "")))
    elif isinstance(send_as, Exception):
        logger.warning("Could not read the Gmail send-as aliases to exclude the user from a reply: %s", send_as)
    return own


async def _reply_context(api: GmailApiClient, message_id: str, *, reply_all: bool) -> ReplyContext:
    # Only the headers are needed: a reply carries just its own text, so the original's body is never fetched or quoted.
    message = await api.request(
        "GET",
        f"/messages/{message_id}",
        params={"format": "metadata", "metadataHeaders": ["From", "Reply-To", "To", "Cc", "Subject", "Message-ID", "References"]},
    )
    payload = message.get("payload") or {}
    headers = header_map(payload)
    recipients = plan_reply_recipients(
        from_header=headers.get("from", ""),
        reply_to_header=headers.get("reply-to", ""),
        to_header=headers.get("to", ""),
        cc_header=headers.get("cc", ""),
        own_addresses=await _own_addresses(api),
        reply_all=reply_all,
    )
    return ReplyContext(
        thread_id=str(message.get("threadId", "")),
        message_id_header=headers.get("message-id", ""),
        references=headers.get("references", ""),
        subject=headers.get("subject", ""),
        to_addresses=recipients.to,
        cc_addresses=recipients.cc,
    )


async def _resolve_attachments(requested: List[DraftAttachment]) -> List[Dict[str, Any]]:
    """Turn each requested attachment into the bytes, file name, and media type the message builder needs, reading files named by path from disk."""
    resolved: List[Dict[str, Any]] = []
    for attachment in requested:
        if attachment.path and attachment.path.strip():
            data, file_name, mime_type = await asyncio.to_thread(read_attachment_file, attachment.path)
            resolved.append(
                {
                    "data": data,
                    "filename": (attachment.filename or "").strip() or file_name,
                    "mimeType": (attachment.mime_type or "").strip() or mime_type,
                }
            )
        else:
            resolved.append(attachment.model_dump(by_alias=True))
    return resolved


async def handle_create_draft(api: GmailApiClient, args: dict) -> dict:
    parsed = CreateDraftInput.model_validate(args)
    if not (
        parsed.to
        or parsed.cc
        or parsed.bcc
        or parsed.subject.strip()
        or parsed.body.strip()
        or parsed.html_body.strip()
        or parsed.attachments
        or parsed.reply_to_message_id
    ):
        raise ToolArgumentError(
            "Nothing was created: the draft would be completely empty. Give at least a recipient, a subject, a body, or an attachment, or replyToMessageId to answer an email."
        )
    # Files are read before any Gmail request, so a wrong path fails without side effects.
    attachments = await _resolve_attachments(parsed.attachments)
    reply = await _reply_context(api, parsed.reply_to_message_id, reply_all=parsed.reply_all) if parsed.reply_to_message_id else None
    # Recipients the agent names are used exactly. A reply fills in only what was left out: To from the original, and Cc only when neither To nor Cc was given.
    to = parsed.to or (list(reply.to_addresses) if reply else [])
    cc = parsed.cc or (list(reply.cc_addresses) if reply and not parsed.to else [])
    signature = await _default_signature_html(api) if parsed.include_signature else None
    raw = build_raw_draft(
        to=to,
        cc=cc,
        bcc=parsed.bcc,
        subject=parsed.subject,
        body=parsed.body,
        html_body=parsed.html_body,
        attachments=attachments,
        reply=reply,
        signature_html=signature,
    )
    message_body: Dict[str, Any] = {"raw": raw}
    if reply is not None and reply.thread_id:
        message_body["threadId"] = reply.thread_id
    draft = await api.request("POST", "/drafts", json_body={"message": message_body})
    message = draft.get("message") or {}
    structured = {
        "id": draft.get("id"),
        "threadId": message.get("threadId"),
        "viewUrl": f"https://mail.google.com/mail/u/0/#drafts?compose={message.get('id', '')}",
        "to": to,
        "cc": cc,
    }
    attached_names = [str(item.get("filename") or "unnamed file") for item in attachments]
    if attached_names:
        structured["attachments"] = attached_names
    recipients_note = f" To: {', '.join(to) or 'nobody'}." + (f" Cc: {', '.join(cc)}." if cc else "")
    if attached_names:
        recipients_note += f" Attached: {', '.join(attached_names)}."
    return {
        "text": f"Created draft {structured['id']}.{recipients_note} It is saved in Drafts and has not been sent.",
        "structured": structured,
    }


async def handle_send_draft(api: GmailApiClient, args: dict) -> dict:
    parsed = SendDraftInput.model_validate(args)
    draft = await api.request(
        "GET",
        f"/drafts/{parsed.draft_id}",
        params={"format": "metadata", "metadataHeaders": ["To", "Cc", "Bcc", "Subject"]},
    )
    headers = header_map((draft.get("message") or {}).get("payload") or {})
    actual = {address for field in ("to", "cc", "bcc") for address in bare_addresses(headers.get(field, ""))}
    expected = {address.strip().lower() for address in parsed.recipients if address.strip()}
    actual_subject = headers.get("subject", "").strip()
    if not actual:
        raise ToolArgumentError("The draft has no recipients, so it cannot be sent.")
    if actual != expected or actual_subject != parsed.subject.strip():
        raise ToolArgumentError(
            "Nothing was sent: the recipients or subject given do not match the draft. "
            f"The draft is addressed to {sorted(actual)} with the subject {actual_subject!r}. "
            "Call send_draft again with exactly those values so the user approves what will really be sent."
        )
    sent = await api.request("POST", "/drafts/send", json_body={"id": parsed.draft_id})
    structured = {"id": sent.get("id"), "threadId": sent.get("threadId"), "labelIds": sent.get("labelIds") or []}
    return {"text": f"Sent the draft to {', '.join(sorted(actual))}.", "structured": structured}


def _thread_result(action: str, thread: Dict[str, Any], note: str = "") -> dict:
    thread_id = thread.get("id")
    messages = thread.get("messages") or []
    labels = sorted({label for message in messages for label in message.get("labelIds") or []})
    return {
        "text": f"{action} thread {thread_id} ({len(messages)} message(s)).{(' ' + note) if note else ''}",
        "structured": {"id": thread_id, "messageCount": len(messages), "labelIds": labels, "viewUrl": view_url(str(thread_id))},
    }


def _message_result(action: str, message: Dict[str, Any], note: str = "") -> dict:
    message_id = message.get("id")
    return {
        "text": f"{action} message {message_id}.{(' ' + note) if note else ''}",
        "structured": {"id": message_id, "threadId": message.get("threadId"), "labelIds": message.get("labelIds") or [], "viewUrl": view_url(str(message_id))},
    }


async def _modify_thread(api: GmailApiClient, thread_id: str, add: List[str], remove: List[str]) -> Dict[str, Any]:
    return await api.request("POST", f"/threads/{thread_id}/modify", json_body={"addLabelIds": add, "removeLabelIds": remove})


async def _modify_message(api: GmailApiClient, message_id: str, add: List[str], remove: List[str]) -> Dict[str, Any]:
    return await api.request("POST", f"/messages/{message_id}/modify", json_body={"addLabelIds": add, "removeLabelIds": remove})


async def handle_label_thread(api: GmailApiClient, args: dict) -> dict:
    parsed = ThreadLabelsInput.model_validate(args)
    _refuse_protected_labels(parsed.label_ids)
    return _thread_result("Labeled", await _modify_thread(api, parsed.thread_id, parsed.label_ids, []))


async def handle_unlabel_thread(api: GmailApiClient, args: dict) -> dict:
    parsed = ThreadLabelsInput.model_validate(args)
    return _thread_result("Removed labels from", await _modify_thread(api, parsed.thread_id, [], parsed.label_ids))


async def handle_label_message(api: GmailApiClient, args: dict) -> dict:
    parsed = MessageLabelsInput.model_validate(args)
    _refuse_protected_labels(parsed.label_ids)
    return _message_result("Labeled", await _modify_message(api, parsed.message_id, parsed.label_ids, []))


async def handle_unlabel_message(api: GmailApiClient, args: dict) -> dict:
    parsed = MessageLabelsInput.model_validate(args)
    return _message_result("Removed labels from", await _modify_message(api, parsed.message_id, [], parsed.label_ids))


async def handle_update_message_labels(api: GmailApiClient, args: dict) -> dict:
    parsed = UpdateMessageLabelsInput.model_validate(args)
    if not parsed.add_label_ids and not parsed.remove_label_ids:
        raise ToolArgumentError("Give at least one of addLabelIds or removeLabelIds.")
    _refuse_protected_labels(parsed.add_label_ids)
    return _message_result("Updated labels on", await _modify_message(api, parsed.message_id, parsed.add_label_ids, parsed.remove_label_ids))


async def handle_trash_thread(api: GmailApiClient, args: dict) -> dict:
    parsed = ThreadActionInput.model_validate(args)
    return _thread_result("Moved to Trash:", await api.request("POST", f"/threads/{parsed.thread_id}/trash"), _TRASH_NOTE)


async def handle_untrash_thread(api: GmailApiClient, args: dict) -> dict:
    parsed = ThreadActionInput.model_validate(args)
    return _thread_result("Restored from Trash:", await api.request("POST", f"/threads/{parsed.thread_id}/untrash"))


async def handle_trash_message(api: GmailApiClient, args: dict) -> dict:
    parsed = MessageActionInput.model_validate(args)
    return _message_result("Moved to Trash:", await api.request("POST", f"/messages/{parsed.message_id}/trash"), _TRASH_NOTE)


async def handle_untrash_message(api: GmailApiClient, args: dict) -> dict:
    parsed = MessageActionInput.model_validate(args)
    return _message_result("Restored from Trash:", await api.request("POST", f"/messages/{parsed.message_id}/untrash"))


async def handle_mark_thread_spam(api: GmailApiClient, args: dict) -> dict:
    parsed = ThreadActionInput.model_validate(args)
    return _thread_result("Marked as Spam:", await _modify_thread(api, parsed.thread_id, ["SPAM"], ["INBOX"]))


async def handle_unmark_thread_spam(api: GmailApiClient, args: dict) -> dict:
    parsed = ThreadActionInput.model_validate(args)
    return _thread_result("Removed from Spam:", await _modify_thread(api, parsed.thread_id, ["INBOX"], ["SPAM"]))


async def handle_mark_message_spam(api: GmailApiClient, args: dict) -> dict:
    parsed = MessageActionInput.model_validate(args)
    return _message_result("Marked as Spam:", await _modify_message(api, parsed.message_id, ["SPAM"], ["INBOX"]))


async def handle_unmark_message_spam(api: GmailApiClient, args: dict) -> dict:
    parsed = MessageActionInput.model_validate(args)
    return _message_result("Removed from Spam:", await _modify_message(api, parsed.message_id, ["INBOX"], ["SPAM"]))


async def handle_apply_sensitive_thread_label(api: GmailApiClient, args: dict) -> dict:
    parsed = SensitiveThreadLabelInput.model_validate(args)
    if parsed.label_option == "TRASH":
        return await handle_trash_thread(api, {"threadId": parsed.thread_id})
    if parsed.label_option == "SPAM":
        return await handle_mark_thread_spam(api, {"threadId": parsed.thread_id})
    raise ToolArgumentError("labelOption must be TRASH or SPAM.")


async def handle_apply_sensitive_message_label(api: GmailApiClient, args: dict) -> dict:
    parsed = SensitiveMessageLabelInput.model_validate(args)
    if parsed.label_option == "TRASH":
        return await handle_trash_message(api, {"messageId": parsed.message_id})
    if parsed.label_option == "SPAM":
        return await handle_mark_message_spam(api, {"messageId": parsed.message_id})
    raise ToolArgumentError("labelOption must be TRASH or SPAM.")


async def handle_create_label(api: GmailApiClient, args: dict) -> dict:
    parsed = CreateLabelInput.model_validate(args)
    name = "/".join(part.strip() for part in parsed.display_name.split("/") if part.strip())
    if not name:
        raise ToolArgumentError("displayName must contain a label name.")
    created_parents: List[str] = []
    if parsed.auto_create_parent_labels and "/" in name:
        existing = {str(label.get("name")) for label in (await api.request("GET", "/labels")).get("labels") or []}
        parts = name.split("/")
        for depth in range(1, len(parts)):
            parent = "/".join(parts[:depth])
            if parent not in existing:
                await api.request("POST", "/labels", json_body={"name": parent})
                created_parents.append(parent)
    body: Dict[str, Any] = {
        "name": name,
        "labelListVisibility": _LABEL_LIST_VISIBILITY.get(parsed.label_list_visibility, "labelShow"),
        "messageListVisibility": "hide" if parsed.message_list_visibility == "HIDE" else "show",
    }
    preset = LABEL_COLOR_PRESETS.get(parsed.color_preset)
    if preset:
        body["color"] = preset
    label = await api.request("POST", "/labels", json_body=body)
    structured = {"labelId": label.get("id"), "name": label.get("name"), "createdParentLabels": created_parents}
    return {"text": f"Created label {structured['name']} (id: {structured['labelId']}).", "structured": structured}
