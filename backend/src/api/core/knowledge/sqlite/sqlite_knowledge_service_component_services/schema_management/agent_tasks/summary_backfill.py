"""Agent task summary and search-index backfill helpers."""

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def safe_json_loads(value: Optional[str]) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def get_finalizer_envelope(result_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("finalizer_result", "final_envelope"):
        candidate = result_data.get(key)
        if isinstance(candidate, dict):
            return candidate

    nested_data = result_data.get("data")
    if isinstance(nested_data, dict):
        candidate = nested_data.get("final_envelope") or nested_data.get("finalizer_result")
        if isinstance(candidate, dict):
            return candidate

    return None


def get_finalizer_file_count(result_data: Dict[str, Any]) -> int:
    candidate_envelopes: List[Dict[str, Any]] = []
    for key in ("finalizer_result", "final_envelope"):
        candidate = result_data.get(key)
        if isinstance(candidate, dict):
            candidate_envelopes.append(candidate)

    nested_data = result_data.get("data")
    if isinstance(nested_data, dict):
        for key in ("finalizer_result", "final_envelope"):
            candidate = nested_data.get(key)
            if isinstance(candidate, dict):
                candidate_envelopes.append(candidate)

    for finalizer in candidate_envelopes:
        result_payload = finalizer.get("result_payload")
        if not isinstance(result_payload, dict):
            continue

        nested_files = result_payload.get("files", [])
        if isinstance(nested_files, list):
            return len(nested_files)

    return 0


def get_finalizer_preview(result_data: Dict[str, Any]) -> Optional[str]:
    finalizer = get_finalizer_envelope(result_data)
    if not isinstance(finalizer, dict):
        return None

    result_payload = finalizer.get("result_payload")
    if isinstance(result_payload, dict):
        for key in ("message", "result", "output_text", "content"):
            value = result_payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

    summary = finalizer.get("summary_text")
    return summary if isinstance(summary, str) and summary.strip() else None


def extract_agent_task_preview(result_data: Any) -> Tuple[Optional[str], int]:
    if not isinstance(result_data, dict):
        return None, 0

    preview = get_finalizer_preview(result_data) or (
        result_data.get("message") or
        result_data.get("result") or
        result_data.get("workflow_result") or
        result_data.get("enhanced_output") or
        result_data.get("agent_output") or
        result_data.get("full_content")
    )
    if not preview:
        failure_info = result_data.get("failure_info")
        if isinstance(failure_info, dict):
            preview = failure_info.get("error")

    if isinstance(preview, str):
        preview = " ".join(preview.split())
        if len(preview) > 160:
            preview = preview[:157] + "..."
    else:
        preview = None

    file_count = get_finalizer_file_count(result_data)
    if file_count == 0:
        files = result_data.get("files", [])
        file_count = len(files) if isinstance(files, list) else 0

    return preview, file_count


def append_search_value(parts: List[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value.strip():
            parts.append(value)
        return
    if isinstance(value, (dict, list)):
        parts.append(json.dumps(value, ensure_ascii=False))
        return
    parts.append(str(value))


def build_agent_task_search_document(rows: List[sqlite3.Row]) -> str:
    parts: List[str] = []
    for row in rows:
        for key in (
            "title", "original_prompt", "transcribed_prompt",
            "app_name", "window_title", "screen_text",
            "result_preview", "result_data", "accumulated_artifacts",
            "execution_timeline",
        ):
            if key in row.keys():
                value = row[key]
                if key in {"result_data", "accumulated_artifacts", "execution_timeline"}:
                    value = safe_json_loads(value)
                append_search_value(parts, value)
    return "\n".join(parts)


def agent_task_summary_backfill_needed(conn: sqlite3.Connection) -> bool:
    missing_summary = conn.execute(
        """
        SELECT 1
        FROM agent_tasks
        WHERE COALESCE(root_task_id, id) = id
          AND (last_turn_timestamp IS NULL OR latest_agent_task_id IS NULL)
        LIMIT 1
        """
    ).fetchone()
    if missing_summary:
        return True

    root_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM agent_tasks
        WHERE COALESCE(root_task_id, id) = id
        """
    ).fetchone()[0]
    fts_count = conn.execute(
        "SELECT COUNT(*) FROM agent_task_search_fts"
    ).fetchone()[0]
    return fts_count < root_count


def backfill_agent_task_summaries(conn: sqlite3.Connection) -> None:
    logger.info("Backfilling agent_task root summaries and search index")
    roots = conn.execute(
        """
        SELECT id
        FROM agent_tasks
        WHERE COALESCE(root_task_id, id) = id
        """
    ).fetchall()

    for root in roots:
        root_id = root["id"]
        rows = conn.execute(
            """
            SELECT *
            FROM agent_tasks
            WHERE COALESCE(root_task_id, id) = ?
            ORDER BY chain_sequence_number ASC, timestamp ASC, id ASC
            """,
            (root_id,)
        ).fetchall()
        if not rows:
            continue

        latest = rows[-1]
        preview: Optional[str] = None
        file_count = 0
        for row in reversed(rows):
            candidate_preview, candidate_file_count = extract_agent_task_preview(
                safe_json_loads(row["result_data"])
            )
            if preview is None and candidate_preview:
                preview = candidate_preview
            if file_count == 0 and candidate_file_count:
                file_count = candidate_file_count
            if preview is not None and file_count:
                break

        conn.execute(
            """
            UPDATE agent_tasks
            SET last_turn_timestamp = ?,
                turn_count = ?,
                follow_up_count = ?,
                result_preview = ?,
                file_count = ?,
                latest_status = ?,
                latest_agent_task_id = ?
            WHERE id = ?
            """,
            (
                latest["timestamp"],
                len(rows),
                max(len(rows) - 1, 0),
                preview,
                file_count,
                latest["status"],
                latest["id"],
                root_id,
            )
        )

        search_document = build_agent_task_search_document(rows)
        conn.execute(
            "DELETE FROM agent_task_search_fts WHERE root_task_id = ?",
            (root_id,)
        )
        conn.execute(
            "INSERT INTO agent_task_search_fts(root_task_id, content) VALUES (?, ?)",
            (root_id, search_document)
        )
