"""Agent task root summary and search-document helpers."""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from api.core.agent_task_search_text import append_search_value, build_search_document  # noqa: F401
from api.core.json_helpers import json_loads_or_empty as safe_json_loads  # noqa: F401


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


def extract_result_preview(result_data: Any) -> Tuple[Optional[str], int]:
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


# Bump this whenever build_search_document changes what it indexes. Startup housekeeping rebuilds every chain whose recorded version is lower, a few per launch.
SEARCH_BUILDER_VERSION = 2


def root_task_id_for_agent_task(conn: sqlite3.Connection, agent_task_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT COALESCE(root_task_id, id) AS root_id FROM agent_tasks WHERE id = ?",
        (agent_task_id,)
    ).fetchone()
    return row["root_id"] if row else None


# While the newest turn of a chain is in one of these states, work is actively happening and the chain is rewritten many times a minute, so the search entry is left as it was and rebuilt when the turn reaches any other status. A turn that is waiting on the user (awaiting_user_input, needs_clarification, paused) is a resting point and is indexed, and so is any status not listed here, so nothing can silently stay unsearchable.
IN_FLIGHT_TURN_STATUSES = frozenset({
    "capturing", "routing", "processing",
    "awaiting_provider_delegation", "awaiting_delegated_agents",
})


def recompute_root_summary(conn: sqlite3.Connection, root_task_id: str) -> None:
    # Only the small columns are read here. The full rows hold every timeline and artifact in the chain, which can total hundreds of megabytes, and loading them on every write was what held the database write slot for seconds.
    rows = conn.execute(
        """
        SELECT id, timestamp, status
        FROM agent_tasks
        WHERE root_task_id = ? OR (root_task_id IS NULL AND id = ?)
        ORDER BY chain_sequence_number ASC, timestamp ASC, id ASC
        """,
        (root_task_id, root_task_id)
    ).fetchall()
    if not rows:
        clear_search_entry(conn, root_task_id)
        return

    root_exists = any(row["id"] == root_task_id for row in rows)
    if not root_exists:
        clear_search_entry(conn, root_task_id)
        return

    latest = rows[-1]
    preview: Optional[str] = None
    file_count = 0
    for row in reversed(rows):
        result_row = conn.execute(
            "SELECT result_data FROM agent_tasks WHERE id = ?", (row["id"],)
        ).fetchone()
        candidate_preview, candidate_file_count = extract_result_preview(
            safe_json_loads(result_row["result_data"] if result_row else None)
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
            latest_agent_task_id = ?,
            updated_at = CURRENT_TIMESTAMP
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
            root_task_id,
        )
    )

    if latest["status"] in IN_FLIGHT_TURN_STATUSES and has_search_entry(conn, root_task_id):
        return

    rebuild_search_entry(conn, root_task_id)


def has_search_entry(conn: sqlite3.Connection, root_task_id: str) -> bool:
    """Whether the chain already has a search entry. A chain that has none is indexed even while its newest turn runs, so a running task can be found by its request; once it has one, further updates wait until the turn stops."""
    row = conn.execute(
        "SELECT 1 FROM agent_task_search_index_state WHERE root_task_id = ?",
        (root_task_id,)
    ).fetchone()
    return row is not None


def clear_search_entry(conn: sqlite3.Connection, root_task_id: str) -> None:
    conn.execute(
        "DELETE FROM agent_task_search_fts WHERE root_task_id = ?",
        (root_task_id,)
    )
    conn.execute(
        "DELETE FROM agent_task_search_index_state WHERE root_task_id = ?",
        (root_task_id,)
    )


def rebuild_search_entry(conn: sqlite3.Connection, root_task_id: str) -> None:
    """Replace one chain's search entry from its current rows and record the builder version that wrote it."""
    full_rows = conn.execute(
        """
        SELECT *
        FROM agent_tasks
        WHERE root_task_id = ? OR (root_task_id IS NULL AND id = ?)
        ORDER BY chain_sequence_number ASC, timestamp ASC, id ASC
        """,
        (root_task_id, root_task_id)
    ).fetchall()
    conn.execute(
        "DELETE FROM agent_task_search_fts WHERE root_task_id = ?",
        (root_task_id,)
    )
    conn.execute(
        "INSERT INTO agent_task_search_fts(root_task_id, content) VALUES (?, ?)",
        (root_task_id, build_search_document(full_rows))
    )
    conn.execute(
        "INSERT OR REPLACE INTO agent_task_search_index_state(root_task_id, builder_version) VALUES (?, ?)",
        (root_task_id, SEARCH_BUILDER_VERSION)
    )
