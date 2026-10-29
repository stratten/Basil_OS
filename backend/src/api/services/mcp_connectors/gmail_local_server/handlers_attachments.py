"""Handler that saves a Gmail attachment to the user's computer.

The file's bytes go to disk and are never returned to the agent: a large PDF in the model's context would be wasteful, and impossible for a local model. The agent gets the saved path and reads the file with its own file tools.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .attachment_files import (
    MAX_ATTACHMENT_BYTES,
    resolve_destination_folder,
    safe_file_name,
    write_without_overwriting,
)
from .gmail_api import GmailApiClient, ToolArgumentError
from .schemas import DownloadAttachmentInput

logger = logging.getLogger(__name__)

_FALLBACK_FOLDER_NAME = "mail_attachments"


@dataclass(frozen=True)
class AttachmentPart:
    attachment_id: str
    part_id: str
    filename: str
    mime_type: str
    size: int


def _attachment_parts(part: Dict[str, Any]) -> List[AttachmentPart]:
    """Every part of the message that is a separate file, in the order they appear."""
    found: List[AttachmentPart] = []
    body = part.get("body") or {}
    filename = str(part.get("filename") or "")
    if filename and body.get("attachmentId"):
        found.append(
            AttachmentPart(
                attachment_id=str(body["attachmentId"]),
                part_id=str(part.get("partId") or ""),
                filename=filename,
                mime_type=str(part.get("mimeType") or "application/octet-stream"),
                size=int(body.get("size") or 0),
            )
        )
    for child in part.get("parts") or []:
        found.extend(_attachment_parts(child))
    return found


def _describe(parts: List[AttachmentPart]) -> str:
    if not parts:
        return "This message has no attachments."
    return "Attachments on this message: " + "; ".join(f"{part.filename} (partId {part.part_id}, {part.mime_type}, {part.size} bytes)" for part in parts) + "."


def _choose_part(parts: List[AttachmentPart], parsed: DownloadAttachmentInput) -> AttachmentPart:
    # Gmail issues a different attachmentId on every fetch, so an id from an earlier get_message rarely matches. partId and the file name are stable.
    if parsed.part_id:
        for part in parts:
            if part.part_id == parsed.part_id:
                return part
    if parsed.attachment_id:
        for part in parts:
            if part.attachment_id == parsed.attachment_id:
                return part
    if parsed.filename:
        wanted = parsed.filename.strip().lower()
        named = [part for part in parts if part.filename.lower() == wanted]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            raise ToolArgumentError(
                f"{len(named)} attachments are named {parsed.filename!r}. Pass the partId of the one you want. {_describe(named)}"
            )
    raise ToolArgumentError(f"No attachment on that message matches. {_describe(parts)}")


def _default_folder() -> Path:
    """This task's workspace folder, or a fixed Basil folder when there is no task, such as a direct tool call."""
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
        from api.services.agent_processing.tools.direct_application_interactions.shared.agent_task_workspace import (
            resolve_agent_task_workspace,
        )

        context = get_current_agent_context()
        task_id = context.get("root_task_id") or context.get("agent_task_id")
        if isinstance(task_id, str) and task_id.strip():
            return resolve_agent_task_workspace(task_id)
    except Exception:
        logger.warning("Could not resolve the agent task workspace for an attachment download; using the fallback folder.", exc_info=True)
    from api.core.config.api_settings import settings

    return settings.STORAGE_DIR / _FALLBACK_FOLDER_NAME


def _decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


async def handle_download_attachment(api: GmailApiClient, args: dict) -> dict:
    parsed = DownloadAttachmentInput.model_validate(args)
    if not (parsed.part_id or parsed.attachment_id or parsed.filename):
        raise ToolArgumentError("Give filename or partId to say which attachment to save. get_message lists both for each attachment.")
    # The message is fetched again so the attachment is matched against its current ids, which Gmail can change between fetches.
    message = await api.request("GET", f"/messages/{parsed.message_id}", params={"format": "full"})
    part = _choose_part(_attachment_parts(message.get("payload") or {}), parsed)
    if part.size > MAX_ATTACHMENT_BYTES:
        raise ToolArgumentError(
            f"{part.filename} is {part.size} bytes, over the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit for downloads, so nothing was saved."
        )
    attachment = await api.request("GET", f"/messages/{parsed.message_id}/attachments/{part.attachment_id}")
    data = _decode(str(attachment.get("data") or ""))
    if not data and part.size:
        raise ToolArgumentError(f"Gmail returned no data for {part.filename}, so nothing was saved.")
    if part.size and len(data) < part.size:
        raise ToolArgumentError(f"Gmail returned {len(data)} of {part.size} bytes for {part.filename}, so nothing was saved. Try again.")
    folder = resolve_destination_folder(parsed.destination_folder, _default_folder())
    file_name = safe_file_name(parsed.save_as or part.filename, part.mime_type)
    saved = await asyncio.to_thread(write_without_overwriting, folder, file_name, data)
    structured: Dict[str, Optional[Any]] = {
        "path": str(saved),
        "folder": str(saved.parent),
        "fileName": saved.name,
        "mimeType": part.mime_type,
        "sizeBytes": len(data),
        "messageId": parsed.message_id,
    }
    return {
        "text": f"Saved {part.filename} ({part.mime_type}, {len(data)} bytes) to {saved}. Its contents were not read; open it with the file tools.",
        "structured": structured,
    }
