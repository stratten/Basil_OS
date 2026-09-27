"""Declarative configs for every table-backed zettel source.

Column names and status vocabularies here were read from schema.py. Carding
uses title_of/summary_of/payload_of to build a thin card; narrative_columns
(and, where the material lives in another table, context_builder) feed the
model finalizing pass.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from api.services.zettel.normalization import truncate
from api.services.zettel.sources.table_source import TableSourceConfig, TableZettelSource

_OUTCOME_BY_STATUS = {
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "missed": "skipped",
    "skipped": "skipped",
}


def _value(row: sqlite3.Row, column: str) -> Optional[Any]:
    try:
        return row[column]
    except (IndexError, KeyError):
        return None


def _text(row: sqlite3.Row, column: str) -> Optional[str]:
    value = _value(row, column)
    return None if value is None else str(value)


def _status_outcome(row: sqlite3.Row, column: str = "status") -> Optional[str]:
    status = _text(row, column)
    return _OUTCOME_BY_STATUS.get((status or "").lower())


# --------------------------------------------------------------------------
# agent_tasks
# --------------------------------------------------------------------------

def _agent_task_title(row: sqlite3.Row) -> str:
    return (
        _text(row, "title")
        or _text(row, "transcribed_prompt")
        or _text(row, "original_prompt")
        or "Agent task"
    )


def _agent_task_summary(row: sqlite3.Row) -> Optional[str]:
    return _text(row, "result_preview") or _text(row, "transcribed_prompt")


def _agent_task_payload(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "task_id": _text(row, "id"),
        "root_task_id": _text(row, "root_task_id"),
        "app_name": _text(row, "app_name"),
        "session_type": _text(row, "session_type"),
        "session_status": _text(row, "session_status"),
        "turn_count": _value(row, "turn_count"),
        "file_count": _value(row, "file_count"),
        "processing_time_ms": _value(row, "processing_time_ms"),
    }


AGENT_TASK_CONFIG = TableSourceConfig(
    source_kind="agent_task",
    event_type="agent_task_run",
    table="agent_tasks",
    id_column="id",
    columns=(
        "id", "timestamp", "status", "session_status", "session_type", "title",
        "transcribed_prompt", "original_prompt", "result_preview", "root_task_id",
        "app_name", "turn_count", "file_count", "processing_time_ms",
    ),
    occurred_column="timestamp",
    status_column="status",
    title_of=_agent_task_title,
    summary_of=_agent_task_summary,
    payload_of=_agent_task_payload,
    outcome_of=_status_outcome,
    narrative_columns=(
        "result_data", "accumulated_artifacts", "execution_timeline", "operation",
        "operation_parameters", "clarifications", "total_planned_steps",
        "turn_count", "user_feedback",
    ),
)


# --------------------------------------------------------------------------
# transcriptions
# --------------------------------------------------------------------------

def _transcription_title(row: sqlite3.Row) -> str:
    text = truncate(_text(row, "transcription_text"), 120)
    return f"Transcription: {text}" if text else "Transcription"


TRANSCRIPTION_CONFIG = TableSourceConfig(
    source_kind="transcription",
    event_type="transcription",
    table="transcriptions",
    id_column="id",
    columns=(
        "id", "timestamp", "status", "transcription_text", "model_name",
        "duration_seconds", "app_name", "window_title", "error_message",
    ),
    occurred_column="timestamp",
    status_column="status",
    title_of=_transcription_title,
    summary_of=lambda row: _text(row, "transcription_text"),
    payload_of=lambda row: {
        "model_name": _text(row, "model_name"),
        "duration_seconds": _value(row, "duration_seconds"),
        "app_name": _text(row, "app_name"),
        "window_title": _text(row, "window_title"),
        "error_message": _text(row, "error_message"),
    },
    outcome_of=_status_outcome,
    narrative_columns=("transcription_text",),
)


# --------------------------------------------------------------------------
# assistant_outputs (no updated_at; occurs at generated_at)
# --------------------------------------------------------------------------

def _assistant_output_title(row: sqlite3.Row) -> str:
    request = truncate(_text(row, "user_request"), 120)
    if request:
        return f"Assistant: {request}"
    output = truncate(_text(row, "output_text"), 120)
    return f"Assistant output: {output}" if output else "Assistant output"


ASSISTANT_OUTPUT_CONFIG = TableSourceConfig(
    source_kind="assistant_output",
    event_type="assistant_output",
    table="assistant_outputs",
    id_column="id",
    columns=(
        "id", "generated_at", "status", "output_type", "output_text",
        "user_request", "model_name", "app_name", "window_title",
        "refinement_count", "input_modality", "processing_time_ms",
    ),
    occurred_column="generated_at",
    status_column="status",
    title_of=_assistant_output_title,
    summary_of=lambda row: _text(row, "output_text"),
    payload_of=lambda row: {
        "output_type": _text(row, "output_type"),
        "model_name": _text(row, "model_name"),
        "app_name": _text(row, "app_name"),
        "window_title": _text(row, "window_title"),
        "refinement_count": _value(row, "refinement_count"),
        "input_modality": _text(row, "input_modality"),
        "processing_time_ms": _value(row, "processing_time_ms"),
    },
    outcome_of=_status_outcome,
    narrative_columns=("output_text", "user_request"),
)


# --------------------------------------------------------------------------
# scheduled_agent_task_runs (material lives on the linked agent task)
# --------------------------------------------------------------------------

def _scheduled_run_context(
    conn: sqlite3.Connection, source_ids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    ids = [str(value) for value in source_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT r.id AS run_id, r.status AS run_status, r.error_message AS error_message, "
        f"t.title AS task_title, t.status AS task_status, t.result_data AS result_data "
        f"FROM scheduled_agent_task_runs r "
        f"LEFT JOIN agent_tasks t ON CAST(t.id AS TEXT) = CAST(r.agent_task_id AS TEXT) "
        f"WHERE CAST(r.id AS TEXT) IN ({placeholders})",
        ids,
    ).fetchall()
    return {
        str(row["run_id"]): {
            "run_status": row["run_status"],
            "error_message": row["error_message"],
            "task_title": row["task_title"],
            "task_status": row["task_status"],
            "result_data": row["result_data"],
        }
        for row in rows
    }


SCHEDULED_RUN_CONFIG = TableSourceConfig(
    source_kind="scheduled_run",
    event_type="scheduled_task_run",
    table="scheduled_agent_task_runs",
    id_column="id",
    columns=(
        "id", "scheduled_agent_task_id", "agent_task_id", "scheduled_for",
        "started_at", "completed_at", "status", "error_message",
    ),
    occurred_column="scheduled_for",
    ended_column="completed_at",
    status_column="status",
    title_of=lambda row: f"Scheduled task run ({_text(row, 'status') or 'scheduled'})",
    summary_of=lambda row: _text(row, "error_message"),
    payload_of=lambda row: {
        "scheduled_agent_task_id": _text(row, "scheduled_agent_task_id"),
        "agent_task_id": _text(row, "agent_task_id"),
    },
    outcome_of=_status_outcome,
    context_builder=_scheduled_run_context,
)


def build_table_sources() -> List[TableZettelSource]:
    """Instantiate every table-backed source."""
    return [
        TableZettelSource(AGENT_TASK_CONFIG),
        TableZettelSource(TRANSCRIPTION_CONFIG),
        TableZettelSource(ASSISTANT_OUTPUT_CONFIG),
        TableZettelSource(SCHEDULED_RUN_CONFIG),
    ]
