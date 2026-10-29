"""Build the RFC 2822 message the Gmail API stores as a draft."""

from __future__ import annotations

import base64
import html as html_lib
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from typing import Any, Dict, List, Optional, Tuple

from .attachment_files import MAX_DRAFT_ATTACHMENT_BYTES
from .gmail_api import ToolArgumentError
from .message_shaping import html_to_text

_ADDRESS_PATTERN = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


class DraftValidationError(ToolArgumentError):
    """The draft's arguments cannot form a valid message; the text is safe to show the agent."""


@dataclass(frozen=True)
class ReplyContext:
    """What a reply needs from the message it answers.

    A reply carries only the new text: it joins the original's thread through its headers, and the original is not quoted into the body.
    """

    thread_id: str
    message_id_header: str
    references: str
    subject: str
    to_addresses: Tuple[str, ...]
    cc_addresses: Tuple[str, ...]


def validate_addresses(label: str, addresses: List[str]) -> List[str]:
    """Return the addresses unchanged, or raise when one is not a plain ``name@domain`` address."""
    cleaned = [address.strip() for address in addresses if address and address.strip()]
    for address in cleaned:
        if not _ADDRESS_PATTERN.match(address):
            raise DraftValidationError(
                f"'{address}' in {label} is not a plain email address such as user@example.com."
            )
    return cleaned


def _reply_subject(subject: str, reply: Optional[ReplyContext]) -> str:
    if subject or reply is None:
        return subject
    original = reply.subject or ""
    return original if original.lower().startswith("re:") else f"Re: {original}".strip()


def build_raw_draft(
    *,
    to: List[str],
    cc: List[str],
    bcc: List[str],
    subject: str,
    body: str,
    html_body: str,
    attachments: List[Dict[str, Any]],
    reply: Optional[ReplyContext],
    signature_html: Optional[str],
) -> str:
    """Return the base64url-encoded message the ``drafts.create`` call expects."""
    recipients = validate_addresses("to", to)
    message = EmailMessage()
    if recipients:
        message["To"] = ", ".join(recipients)
    carbon_copies = validate_addresses("cc", cc)
    blind_copies = validate_addresses("bcc", bcc)
    if carbon_copies:
        message["Cc"] = ", ".join(carbon_copies)
    if blind_copies:
        message["Bcc"] = ", ".join(blind_copies)
    message["Subject"] = _reply_subject(subject, reply)
    message["Date"] = formatdate(localtime=True)
    if reply is not None:
        if reply.message_id_header:
            message["In-Reply-To"] = reply.message_id_header
            message["References"] = f"{reply.references} {reply.message_id_header}".strip()

    plain_text = body
    if signature_html:
        plain_text = f"{plain_text}\n\n-- \n{html_to_text(signature_html)}"

    if html_body or signature_html:
        html_text = html_body or html_lib.escape(body).replace("\n", "<br>")
        if signature_html:
            html_text += f"<br><br>-- <br>{signature_html}"
        message.set_content(plain_text)
        message.add_alternative(html_text, subtype="html")
    else:
        message.set_content(plain_text)

    total_bytes = 0
    for attachment in attachments:
        if isinstance(attachment.get("data"), bytes):
            # Already read from disk by the handler.
            content = attachment["data"]
        else:
            try:
                content = base64.b64decode(attachment.get("content") or "", validate=False)
            except ValueError as exc:
                raise DraftValidationError(f"Attachment {attachment.get('filename') or ''!r} is not valid base64.") from exc
        total_bytes += len(content)
        if total_bytes > MAX_DRAFT_ATTACHMENT_BYTES:
            raise DraftValidationError("The attachments total more than 25 MB, the most Gmail allows in one email.")
        mime_type = str(attachment.get("mimeType") or "application/octet-stream")
        main_type, _, sub_type = mime_type.partition("/")
        message.add_attachment(
            content,
            maintype=main_type or "application",
            subtype=sub_type or "octet-stream",
            filename=attachment.get("filename") or None,
        )
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
