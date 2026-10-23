"""Opt-in setup-agent tools that pull real email context for a Dill demo.

The flow is intentionally two-tool so the *agent* — not a heuristic — decides
which recent inbox email is worth using as a demo reference:

1. ``peek_recent_inbox_emails`` returns ONLY metadata (sender, subject,
   received_at, id) for the N most recent inbox messages. The agent reads
   this list and judges which one is worth demoing on.
2. ``pull_inbox_email_for_dill`` takes the ``email_id`` the agent chose,
   fetches the body for that one message, sanitizes display-only HTML
   (comments, ``<style>`` and ``<script>`` blocks with their contents, then
   remaining tags, entities, whitespace), emits an ``inline_email_context``
   SSE event so the webview can render it inline, and returns the same
   payload to the agent so it can ground a Dill ``launch_agent_task``
   receipt in that exact message.

There is intentionally no scoring, no "noreply" filter, no automated picking
of "the best" candidate. Email-worthiness for a demo is exactly the kind of
judgment we want the agent to exercise (and re-exercise — peek again,
explain, re-pick) rather than baked-in heuristic logic that ages badly.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from api.routes.setup_assistant.models import SetupAgentEvent, SetupAgentEventKind

from .discovery_tools import slow_setup_tool

logger = logging.getLogger(__name__)


# Stricter than email_integration.outlook.parsing.OutlookParsingService.strip_html_content,
# which only does a single ``<[^>]+>`` pass and therefore leaves CSS bodies
# inside ``<style>`` blocks and HTML comments intact when those bodies do not
# contain a ``>`` character within the excerpt window. That bit us on a real
# Salesforce/Dreamforce marketing email whose entire opening 2000 chars were
# CSS inside an HTML comment. We do not modify the shared stripper because
# other email tools depend on its current behavior and shape; this stricter
# pass is scoped to the Dill demo display path only.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_HTML_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_WHITESPACE_RUN_RE = re.compile(r"[ \t]{2,}")


def _sanitize_email_body_for_display(raw_body: str) -> str:
    """Convert an HTML/multipart email body into clean, readable plain text.

    Steps (order matters):
    1. Strip ``<!-- ... -->`` comments WITH their contents, including
       multi-line CSS-bearing comment blocks.
    2. Strip ``<script>...</script>`` and ``<style>...</style>`` blocks
       WITH their contents.
    3. Strip any remaining HTML tags.
    4. Decode HTML entities (``&amp;``, ``&nbsp;``, etc.).
    5. Remove zero-width / direction-control characters that show up as
       blank squares in the rendered card.
    6. Collapse intra-line whitespace runs, normalize newlines, and trim.

    Returns "" on empty input. Never raises — falls back to a trimmed
    version of the original on unexpected parser failure so the demo at
    worst shows a slightly noisy body rather than a hard error.
    """
    if not raw_body:
        return ""
    try:
        text = _HTML_COMMENT_RE.sub("", raw_body)
        text = _HTML_SCRIPT_RE.sub("", text)
        text = _HTML_STYLE_RE.sub("", text)
        text = _HTML_TAG_RE.sub("", text)
        text = html.unescape(text)
        text = _ZERO_WIDTH_RE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Normalize each line individually so we keep paragraph breaks but
        # squash the in-line whitespace explosions that HTML-to-text often
        # produces.
        lines = [_WHITESPACE_RUN_RE.sub(" ", line).strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line is not None)
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return text.strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Email body sanitization failed; falling back to raw: %s", exc)
        return raw_body.strip()


def _serialize_received_at(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive
        return None


def _split_sender(sender_full: str) -> tuple[str, str]:
    sender_full = (sender_full or "").strip() or "Unknown sender"
    if "<" in sender_full and ">" in sender_full:
        try:
            name = sender_full.split("<", 1)[0].strip().strip('"') or sender_full
            address = sender_full.split("<", 1)[1].rstrip(">").strip()
            return name, address
        except Exception:  # pragma: no cover - defensive
            pass
    return sender_full, sender_full


def _record_to_metadata_dict(record: Any) -> Dict[str, Any]:
    sender_name, sender_address = _split_sender(getattr(record, "sender", "") or "")
    return {
        "email_id": getattr(record, "id", "") or "",
        "subject": (getattr(record, "subject", "") or "").strip() or "(no subject)",
        "sender_name": sender_name,
        "sender_address": sender_address,
        "received_at": _serialize_received_at(getattr(record, "date_sent", None)),
        "is_read": bool(getattr(record, "is_read", False)),
    }


def _sort_metadata_records_by_recency(records: Iterable[Any]) -> List[Any]:
    return sorted(
        list(records),
        key=lambda r: getattr(r, "date_sent", None) or datetime.min,
        reverse=True,
    )


async def _emit_inline_email_context(factory, payload: Dict[str, Any]) -> None:
    try:
        await factory.event_emitter(
            SetupAgentEvent(
                kind=SetupAgentEventKind.inline_email_context,
                payload=payload,
            )
        )
    except Exception as exc:  # pragma: no cover - emission is best-effort
        logger.warning("inline_email_context emission failed: %s", exc)


@slow_setup_tool(
    opening="Peeking at your most recent inbox emails so I can pick a good one to work with.",
    failure="I couldn't peek at your inbox just now — let's describe an email instead.",
)
async def peek_recent_inbox_emails(
    factory,
    limit: int = 10,
) -> Dict[str, Any]:
    """List recent inbox metadata so the agent can judge which one to demo.

    Returns ONLY metadata (sender, subject, received_at, email_id, is_read)
    for the most recent ``limit`` received messages in the primary inbox.
    No bodies are pulled. The agent reasons over the result and chooses an
    ``email_id`` to feed into ``pull_inbox_email_for_dill``.
    """
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (
        EmailClientService,
    )

    service = EmailClientService()
    await service.initialize()
    primary_client = await service.select_primary_client()
    if primary_client is None:
        return {
            "status": "no_email_client",
            "detail": "No supported email client was detected on this machine.",
            "candidates": [],
        }

    bounded_limit = max(1, min(int(limit), 25))
    metadata_records = await service.get_email_metadata(
        folder="inbox",
        limit=bounded_limit,
        client_name=primary_client.name,
        deduplicate_threads=True,
    )
    sorted_records = _sort_metadata_records_by_recency(metadata_records)
    candidates = [_record_to_metadata_dict(record) for record in sorted_records]

    if not candidates:
        return {
            "status": "no_recent_email",
            "detail": "I couldn't find recent received emails in your primary inbox.",
            "client_name": primary_client.name,
            "candidates": [],
        }

    return {
        "status": "ok",
        "client_name": primary_client.name,
        "candidates": candidates,
    }


@slow_setup_tool(
    opening="Pulling that email so we can look at it together.",
    failure="I couldn't pull that email just now — let's pick a different one.",
)
async def pull_inbox_email_for_dill(
    factory,
    email_id: str,
    max_excerpt_chars: int = 2000,
) -> Dict[str, Any]:
    """Pull one specific inbox email by id and emit it as an inline context card.

    The ``email_id`` MUST be one returned by a prior
    ``peek_recent_inbox_emails`` call in the same turn — the agent picks
    which email is worth demoing, this tool just fetches and surfaces it.
    Returns a structured payload AND emits an ``inline_email_context`` SSE
    event so the webview renders a quoted card next to the agent's bubble.
    """
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (
        EmailClientService,
    )

    cleaned_email_id = (email_id or "").strip()
    if not cleaned_email_id:
        return {
            "status": "missing_email_id",
            "detail": (
                "I need a specific email_id to pull. Call peek_recent_inbox_emails "
                "first and pass the id of the message you want to use."
            ),
        }

    service = EmailClientService()
    await service.initialize()
    primary_client = await service.select_primary_client()
    if primary_client is None:
        return {
            "status": "no_email_client",
            "detail": "No supported email client was detected on this machine.",
        }

    bounded_chars = max(200, min(int(max_excerpt_chars), 8000))
    expanded = await service.expand_email_details(
        email_ids=[cleaned_email_id],
        folder="inbox",
        client_name=primary_client.name,
        excerpt_chars=bounded_chars,
    )
    if not expanded:
        return {
            "status": "email_not_found",
            "detail": (
                "I couldn't load that email by id — it may have been moved, "
                "deleted, or the id didn't match anything in your inbox."
            ),
            "client_name": primary_client.name,
            "email_id": cleaned_email_id,
        }

    record = expanded[0]
    raw_body = getattr(record, "content", "") or ""
    cleaned_body = _sanitize_email_body_for_display(raw_body)
    body_excerpt = cleaned_body[:bounded_chars]
    excerpt_truncated = len(cleaned_body) > bounded_chars

    sender_name, sender_address = _split_sender(getattr(record, "sender", "") or "")
    payload = {
        "email_id": getattr(record, "id", "") or cleaned_email_id,
        "subject": (getattr(record, "subject", "") or "").strip() or "(no subject)",
        "sender_name": sender_name,
        "sender_address": sender_address,
        "received_at": _serialize_received_at(getattr(record, "date_sent", None)),
        "body_excerpt": body_excerpt,
        "excerpt_truncated": excerpt_truncated,
        "client_name": primary_client.name,
        "source": "agent_selected",
    }

    await _emit_inline_email_context(factory, payload)

    # Remember the email id on the factory so a subsequent launch_agent_task
    # receipt in this turn can be auto-stamped with ``source_email_id`` even
    # if the agent's payload omits it. See proposal_tools._stamp_setup_source_email_id_for_launch.
    setattr(factory, "last_pulled_email_id", payload.get("email_id") or None)

    return {"status": "ok", **payload}
