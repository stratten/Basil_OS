"""Audit logging for external_catalog dispatches."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Bytes; truncates the persisted preview of the result content so the
# audit log stays scannable in the Settings UI.
AUDIT_PREVIEW_MAX_CHARS = 200


async def record_external_catalog_audit(
    *,
    record,
    tool_name: str,
    arguments: Dict[str, Any],
    classification: str,
    envelope: Dict[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> None:
    """Insert one row into mcp_call_log; tolerate persistence failures.

    A failed audit write must not break the actual tool call — the
    user already got their result/error from the agent — but we log
    loudly so the failure is visible.
    """
    try:
        from api.dependencies import get_sqlite_knowledge_service

        repo = get_sqlite_knowledge_service().mcp_call_log_repository
        agent_task_id = None
        try:
            from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

            context = get_current_agent_context()
            agent_task_id = context.get("agent_task_id") if isinstance(context, dict) else None
        except Exception:
            agent_task_id = None
        error_kind = None
        error_message = None
        content_preview = None

        if envelope.get("ok"):
            result = envelope.get("result") or {}
            text = result.get("text") if isinstance(result, dict) else None
            content_preview = (text or json.dumps(result))[:AUDIT_PREVIEW_MAX_CHARS]
        else:
            err = envelope.get("error") or {}
            error_kind = err.get("kind")
            error_message = err.get("message")

        await repo.record_call(
            connection_id=record.id,
            server_url=record.server_url,
            tool_name=tool_name,
            arguments=arguments,
            result_classification=classification,
            error_kind=error_kind,
            error_message=error_message,
            content_preview=content_preview,
            started_at=started_at,
            completed_at=completed_at,
            agent_task_id=agent_task_id,
        )
    except Exception as exc:
        logger.warning("Failed to write mcp_call_log row: %s", exc)
