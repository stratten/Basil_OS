"""Turn Gmail API message resources into the compact JSON the agent reads.

Output keys follow Google's hosted Gmail MCP server (``id``, ``threadId``,
``subject``, ``sender``, ``toRecipients``, ``plaintextBody``, ``labelIds``, ...)
so switching a connection back to the hosted server changes nothing for the
agent. Bodies are capped so one long email cannot exhaust the model's context.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from email.utils import formataddr, getaddresses
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

MAX_BODY_CHARS = 60000
"""Longest body returned for one message. A longer body is cut and flagged with ``bodyTruncated``."""

GMAIL_VIEW_BASE_URL = "https://mail.google.com/mail/u/0/#all"

FORMAT_MINIMAL = "MINIMAL"
FORMAT_METADATA_ONLY = "METADATA_ONLY"
FORMAT_FULL = "FULL_CONTENT"
FORMAT_PLAIN_TEXT = "PLAIN_TEXT"
FORMAT_RAW = "RAW"

METADATA_HEADERS = ["From", "To", "Cc", "Bcc", "Date", "Subject", "Message-ID", "References", "In-Reply-To", "Reply-To"]


def resolve_message_format(requested: Optional[str]) -> str:
    """Normalize a requested format; unspecified means full content, as Google's server does."""
    if not requested or requested == "MESSAGE_FORMAT_UNSPECIFIED":
        return FORMAT_FULL
    return requested


def api_format_for(message_format: str) -> str:
    """The Gmail API ``format`` parameter that supplies what ``message_format`` needs."""
    if message_format in (FORMAT_MINIMAL, FORMAT_METADATA_ONLY):
        return "metadata"
    if message_format == FORMAT_RAW:
        return "raw"
    return "full"


def view_url(identifier: str) -> str:
    return f"{GMAIL_VIEW_BASE_URL}/{identifier}"


def decode_base64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _decode_text(data: str, charset: Optional[str]) -> str:
    raw = decode_base64url(data)
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


class _HtmlToText(HTMLParser):
    """Reduce an HTML email to readable text: block tags become line breaks, scripts and styles are dropped."""

    _BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"}
    _SKIPPED_TAGS = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        collapsed = re.sub(r"[ \t\r\f\v]+", " ", "".join(self._parts))
        return re.sub(r"\n\s*\n\s*\n+", "\n\n", collapsed).strip()


def html_to_text(html: str) -> str:
    parser = _HtmlToText()
    parser.feed(html)
    parser.close()
    return parser.text()


def header_map(payload: Dict[str, Any]) -> Dict[str, str]:
    """Header values keyed by lower-cased name; the first occurrence wins."""
    headers: Dict[str, str] = {}
    for header in payload.get("headers") or []:
        name = str(header.get("name", "")).lower()
        if name and name not in headers:
            headers[name] = str(header.get("value", ""))
    return headers


def split_addresses(header_value: str) -> List[str]:
    """Split an address header into ``Name <address>`` strings."""
    if not header_value:
        return []
    return [formataddr((name, address)) if name else address for name, address in getaddresses([header_value]) if address]


def bare_addresses(header_value: str) -> List[str]:
    """Lower-cased bare addresses from an address header, for comparisons."""
    return [address.lower() for _name, address in getaddresses([header_value]) if address]


def _walk_parts(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    found = [part]
    for child in part.get("parts") or []:
        found.extend(_walk_parts(child))
    return found


def collect_bodies(payload: Dict[str, Any]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Return ``(plain_text, html, attachments)`` from a full-format payload."""
    plain_chunks: List[str] = []
    html_chunks: List[str] = []
    attachments: List[Dict[str, Any]] = []
    for part in _walk_parts(payload):
        mime_type = str(part.get("mimeType", ""))
        body = part.get("body") or {}
        filename = str(part.get("filename") or "")
        if filename and body.get("attachmentId"):
            attachments.append({"id": body["attachmentId"], "partId": str(part.get("partId") or ""), "mimeType": mime_type, "filename": filename, "size": int(body.get("size") or 0)})
            continue
        data = body.get("data")
        if not data:
            continue
        charset = None
        for header in part.get("headers") or []:
            if str(header.get("name", "")).lower() == "content-type":
                match = re.search(r"charset=\"?([\w.-]+)\"?", str(header.get("value", "")), re.IGNORECASE)
                charset = match.group(1) if match else None
        if mime_type == "text/plain":
            plain_chunks.append(_decode_text(data, charset))
        elif mime_type == "text/html":
            html_chunks.append(_decode_text(data, charset))
    return "\n".join(plain_chunks), "\n".join(html_chunks), attachments


def _cap(text: str) -> Tuple[str, bool]:
    if len(text) <= MAX_BODY_CHARS:
        return text, False
    return text[:MAX_BODY_CHARS], True


def iso_date(message: Dict[str, Any], headers: Dict[str, str]) -> str:
    """The message time as ISO 8601 UTC, from Gmail's ``internalDate`` and falling back to the Date header."""
    internal = message.get("internalDate")
    if internal:
        try:
            return datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return headers.get("date", "")


def shape_message(message: Dict[str, Any], message_format: str) -> Dict[str, Any]:
    """Shape one Gmail message resource for ``message_format``."""
    message_id = str(message.get("id", ""))
    if message_format == FORMAT_RAW:
        raw_text, truncated = _cap(_decode_text(message.get("raw", ""), None))
        shaped: Dict[str, Any] = {"id": message_id, "threadId": message.get("threadId"), "raw": raw_text}
        if truncated:
            shaped["bodyTruncated"] = True
        return shaped

    payload = message.get("payload") or {}
    headers = header_map(payload)
    shaped = {
        "id": message_id,
        "threadId": message.get("threadId"),
        "sender": headers.get("from", ""),
        "toRecipients": split_addresses(headers.get("to", "")),
        "ccRecipients": split_addresses(headers.get("cc", "")),
        "bccRecipients": split_addresses(headers.get("bcc", "")),
        "date": iso_date(message, headers),
        "labelIds": message.get("labelIds") or [],
        "viewUrl": view_url(message_id),
    }
    if message_format == FORMAT_METADATA_ONLY:
        shaped["sizeEstimate"] = message.get("sizeEstimate")
        return shaped

    shaped["subject"] = headers.get("subject", "")
    shaped["snippet"] = message.get("snippet", "")
    if message_format == FORMAT_MINIMAL:
        return shaped

    plain, html, attachments = collect_bodies(payload)
    body_text = plain if plain.strip() else html_to_text(html)
    capped_body, truncated = _cap(body_text)
    shaped["plaintextBody"] = capped_body
    if truncated:
        shaped["bodyTruncated"] = True
    shaped["attachments"] = attachments
    shaped["attachmentIds"] = [attachment["id"] for attachment in attachments]
    if message_format == FORMAT_FULL and html:
        shaped["htmlBody"] = _cap(html)[0]
    return shaped


def message_summary_line(shaped: Dict[str, Any]) -> str:
    """One scannable line for the prose summary the agent reads before the structured data."""
    sender = shaped.get("sender") or "?"
    subject = (shaped.get("subject") or "(no subject)").replace("\n", " ")
    snippet = (shaped.get("snippet") or "").replace("\n", " ")[:160]
    return f"- [{shaped.get('date', '')[:10]}] {sender}: {subject} — {snippet}".rstrip(" —")
