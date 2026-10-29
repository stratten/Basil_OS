"""Read-only handlers for the embedded Gmail server.

Each handler validates its arguments with the matching model in
:mod:`schemas`, calls the Gmail API through :class:`GmailApiClient`, and returns
``{"text": str, "structured": dict}``: a brief readable summary for the agent
plus the shaped data. Errors are raised and converted by :mod:`server`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from .gmail_api import GmailApiClient
from .message_shaping import (
    FORMAT_FULL,
    FORMAT_METADATA_ONLY,
    FORMAT_MINIMAL,
    FORMAT_PLAIN_TEXT,
    FORMAT_RAW,
    METADATA_HEADERS,
    api_format_for,
    message_summary_line,
    resolve_message_format,
    shape_message,
    view_url,
)
from .schemas import (
    GetDraftInput,
    GetMessageInput,
    GetThreadInput,
    ListDraftsInput,
    SearchThreadsInput,
)

_THREAD_FETCH_CONCURRENCY = 8
"""Threads fetched at once while building a search result. Bounded so one search cannot burst past Gmail's per-user rate limit."""

_MESSAGES_PER_THREAD_PREVIEW = 5


def _metadata_params(api_format: str) -> Dict[str, Any]:
    return {"format": api_format, "metadataHeaders": METADATA_HEADERS} if api_format == "metadata" else {"format": api_format}


def _without_drafts(query: str | None) -> str:
    """Gmail's search includes drafts; the hosted server excludes them unless asked, so this does too."""
    text = (query or "").strip()
    lowered = text.lower()
    if "in:draft" in lowered or "in:anywhere" in lowered:
        return text
    return f"{text} -in:draft".strip()


def _thread_message_format(requested: str) -> str:
    resolved = resolve_message_format(requested)
    return FORMAT_FULL if resolved == FORMAT_RAW else resolved


async def handle_search_threads(api: GmailApiClient, args: dict) -> dict:
    parsed = SearchThreadsInput.model_validate(args)
    listing = await api.request(
        "GET",
        "/threads",
        params={
            "q": _without_drafts(parsed.query),
            "maxResults": parsed.page_size,
            "pageToken": parsed.page_token,
            "includeSpamTrash": "true" if parsed.include_trash else None,
        },
    )
    stubs: List[Dict[str, Any]] = listing.get("threads") or []
    semaphore = asyncio.Semaphore(_THREAD_FETCH_CONCURRENCY)

    async def fetch(stub: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await api.request("GET", f"/threads/{stub['id']}", params=_metadata_params("metadata"))

    fetched = await asyncio.gather(*(fetch(stub) for stub in stubs))
    message_format = FORMAT_METADATA_ONLY if parsed.view == "THREAD_VIEW_METADATA_ONLY" else FORMAT_MINIMAL
    threads: List[Dict[str, Any]] = []
    lines: List[str] = []
    for thread in fetched:
        messages = [shape_message(message, message_format) for message in thread.get("messages") or []]
        latest = messages[-1] if messages else {}
        entry: Dict[str, Any] = {
            "id": thread.get("id"),
            "messageCount": len(messages),
            "viewUrl": view_url(str(thread.get("id"))),
            "messages": messages[-_MESSAGES_PER_THREAD_PREVIEW:],
        }
        if message_format == FORMAT_MINIMAL:
            entry["subject"] = (messages[0].get("subject") if messages else "") or ""
            entry["snippet"] = latest.get("snippet", "")
        threads.append(entry)
        lines.append(f"- thread {entry['id']} ({entry['messageCount']} message(s)){message_summary_line(latest)[1:]}")
    structured: Dict[str, Any] = {"threads": threads}
    if listing.get("nextPageToken"):
        structured["nextPageToken"] = listing["nextPageToken"]
    summary = f"Found {len(threads)} thread(s) for {parsed.query or 'all mail'!r}."
    if listing.get("nextPageToken"):
        summary += " More are available: pass nextPageToken to continue."
    return {"text": "\n".join([summary, *lines]) if threads else summary, "structured": structured}


async def handle_get_thread(api: GmailApiClient, args: dict) -> dict:
    parsed = GetThreadInput.model_validate(args)
    message_format = _thread_message_format(parsed.message_format)
    thread = await api.request("GET", f"/threads/{parsed.thread_id}", params=_metadata_params(api_format_for(message_format)))
    messages = [
        shape_message(message, message_format)
        for message in thread.get("messages") or []
        if "DRAFT" not in (message.get("labelIds") or [])
    ]
    structured = {"id": thread.get("id"), "viewUrl": view_url(parsed.thread_id), "messages": messages}
    lines = [message_summary_line(message) for message in messages]
    return {"text": "\n".join([f"Thread {parsed.thread_id}: {len(messages)} message(s).", *lines]), "structured": structured}


async def handle_get_message(api: GmailApiClient, args: dict) -> dict:
    parsed = GetMessageInput.model_validate(args)
    message_format = resolve_message_format(parsed.message_format)
    message = await api.request("GET", f"/messages/{parsed.message_id}", params=_metadata_params(api_format_for(message_format)))
    shaped = shape_message(message, message_format)
    summary = f"Message {parsed.message_id}." if message_format == FORMAT_RAW else message_summary_line(shaped).lstrip("- ")
    return {"text": summary, "structured": shaped}


def _shape_draft(draft: Dict[str, Any], message_format: str) -> Dict[str, Any]:
    shaped = shape_message(draft.get("message") or {}, message_format)
    shaped["messageId"] = shaped.pop("id", None)
    shaped["id"] = draft.get("id")
    return shaped


async def handle_list_drafts(api: GmailApiClient, args: dict) -> dict:
    parsed = ListDraftsInput.model_validate(args)
    listing = await api.request(
        "GET",
        "/drafts",
        params={"q": parsed.query, "maxResults": parsed.page_size, "pageToken": parsed.page_token},
    )
    stubs: List[Dict[str, Any]] = listing.get("drafts") or []
    full_view = parsed.view == "DRAFT_VIEW_FULL"
    message_format = FORMAT_PLAIN_TEXT if full_view else FORMAT_METADATA_ONLY
    semaphore = asyncio.Semaphore(_THREAD_FETCH_CONCURRENCY)

    async def fetch(stub: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await api.request("GET", f"/drafts/{stub['id']}", params=_metadata_params(api_format_for(message_format)))

    drafts = [_shape_draft(draft, message_format) for draft in await asyncio.gather(*(fetch(stub) for stub in stubs))]
    structured: Dict[str, Any] = {"drafts": drafts}
    if listing.get("nextPageToken"):
        structured["nextPageToken"] = listing["nextPageToken"]
    lines = [f"- draft {draft['id']} to {', '.join(draft.get('toRecipients') or []) or '(no recipient)'}" for draft in drafts]
    summary = f"Found {len(drafts)} draft(s)."
    return {"text": "\n".join([summary, *lines]) if drafts else summary, "structured": structured}


async def handle_get_draft(api: GmailApiClient, args: dict) -> dict:
    parsed = GetDraftInput.model_validate(args)
    message_format = resolve_message_format(parsed.message_format)
    draft = await api.request("GET", f"/drafts/{parsed.draft_id}", params=_metadata_params(api_format_for(message_format)))
    shaped = _shape_draft(draft, message_format)
    return {"text": f"Draft {parsed.draft_id}.", "structured": shaped}


async def handle_list_labels(api: GmailApiClient, args: dict) -> dict:
    listing = await api.request("GET", "/labels")
    labels = [
        {"id": label.get("id"), "name": label.get("name"), "type": label.get("type")}
        for label in listing.get("labels") or []
    ]
    labels.sort(key=lambda label: (label["type"] != "system", str(label["name"]).lower()))
    lines = [f"- {label['name']} (id: {label['id']}, {label['type']})" for label in labels]
    summary = f"{len(labels)} label(s)."
    return {"text": "\n".join([summary, *lines]) if labels else summary, "structured": {"labels": labels}}
