"""Full-text search table creation helpers."""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def ensure_agent_task_search_fts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS agent_task_search_fts USING fts5(
            root_task_id UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
        """
    )


def ensure_meeting_transcript_fts(conn: sqlite3.Connection) -> None:
    """Ensure the rebuildable, structured FTS index over meeting data."""
    expected_columns = ["meeting_id", "name", "purpose", "participants", "transcript"]
    existing_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(meeting_transcript_fts)")
    ]
    if existing_columns and existing_columns != expected_columns:
        # This table is a derived cache; meeting metadata/transcripts on disk are
        # authoritative and startup backfill immediately reconstructs its rows.
        conn.execute("DROP TABLE meeting_transcript_fts")

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS meeting_transcript_fts USING fts5(
            meeting_id UNINDEXED,
            name,
            purpose,
            participants,
            transcript,
            tokenize='porter unicode61'
        )
        """
    )


def ensure_zettel_raw_search_fts(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS zettel_raw_search_fts USING fts5(
            document_id UNINDEXED,
            source_kind UNINDEXED,
            source_id UNINDEXED,
            event_type UNINDEXED,
            occurred_at UNINDEXED,
            ended_at UNINDEXED,
            title UNINDEXED,
            summary UNINDEXED,
            outcome UNINDEXED,
            source_status UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
        """
    )
    conn.execute("DELETE FROM zettel_raw_search_fts")
    conn.executescript(
        """
        INSERT INTO zettel_raw_search_fts (
            document_id, source_kind, source_id, event_type, occurred_at, ended_at,
            title, summary, outcome, source_status, content
        )
        SELECT
            'transcription:' || CAST(id AS TEXT), 'transcription', CAST(id AS TEXT),
            'transcription', timestamp, NULL,
            substr(trim('Transcription: ' || COALESCE(transcription_text, '')), 1, 200),
            substr(trim(COALESCE(transcription_text, '')), 1, 4000),
            status, status,
            substr(trim(COALESCE(transcription_text, '') || char(10) ||
                        'Status: ' || COALESCE(status, '') || char(10) ||
                        'App: ' || COALESCE(app_name, '') || char(10) ||
                        'Window: ' || COALESCE(window_title, '')), 1, 4000)
        FROM transcriptions WHERE zettel_id IS NULL;

        INSERT INTO zettel_raw_search_fts (
            document_id, source_kind, source_id, event_type, occurred_at, ended_at,
            title, summary, outcome, source_status, content
        )
        SELECT
            'assistant_output:' || CAST(id AS TEXT), 'assistant_output', CAST(id AS TEXT),
            'assistant_output', generated_at, NULL,
            substr(trim(COALESCE(user_request, output_text, 'Assistant output')), 1, 200),
            substr(trim(COALESCE(output_text, '')), 1, 4000),
            status, status,
            substr(trim('User request: ' || COALESCE(user_request, '') || char(10) ||
                        'Assistant output: ' || COALESCE(output_text, '') || char(10) ||
                        'Status: ' || COALESCE(status, '')), 1, 4000)
        FROM assistant_outputs WHERE zettel_id IS NULL;

        INSERT INTO zettel_raw_search_fts (
            document_id, source_kind, source_id, event_type, occurred_at, ended_at,
            title, summary, outcome, source_status, content
        )
        SELECT
            'scheduled_run:' || CAST(id AS TEXT), 'scheduled_run', CAST(id AS TEXT),
            'scheduled_task_run', scheduled_for, completed_at,
            substr(trim('Scheduled task run: ' || COALESCE(status, 'scheduled')), 1, 200),
            substr(trim(COALESCE(error_message, '')), 1, 4000),
            status, status,
            substr(trim('Scheduled task run' || char(10) ||
                        'Status: ' || COALESCE(status, '') || char(10) ||
                        'Error: ' || COALESCE(error_message, '')), 1, 4000)
        FROM scheduled_agent_task_runs WHERE zettel_id IS NULL;
        """
    )


def ensure_zettel_search_fts(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS zettel_search_fts USING fts5(
            entry_id UNINDEXED,
            source_kind UNINDEXED,
            occurred_at UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
        """
    )
    conn.execute("DELETE FROM zettel_search_fts")
    conn.execute(
        """
        INSERT INTO zettel_search_fts (entry_id, source_kind, occurred_at, content)
        SELECT id, source_kind, occurred_at,
               substr(trim(COALESCE(title, '') || char(10) ||
                           COALESCE(summary, '') || char(10) ||
                           COALESCE(outcome, '') || char(10) ||
                           COALESCE(narrative, '')), 1, 4000)
        FROM zettel_entries
        """
    )


def ensure_zettel_retrieval_fts_triggers(conn: sqlite3.Connection) -> None:
    raw_specs = (
        (
            "transcriptions",
            "transcription",
            "transcription",
            "NEW.timestamp",
            "NULL",
            "NEW.status",
            "NEW.status",
            "substr(trim('Transcription: ' || COALESCE(NEW.transcription_text, '')), 1, 200)",
            "substr(trim(COALESCE(NEW.transcription_text, '')), 1, 4000)",
            "substr(trim(COALESCE(NEW.transcription_text, '') || char(10) || "
            "'Status: ' || COALESCE(NEW.status, '') || char(10) || "
            "'App: ' || COALESCE(NEW.app_name, '') || char(10) || "
            "'Window: ' || COALESCE(NEW.window_title, '')), 1, 4000)",
        ),
        (
            "assistant_outputs",
            "assistant_output",
            "assistant_output",
            "NEW.generated_at",
            "NULL",
            "NEW.status",
            "NEW.status",
            "substr(trim(COALESCE(NEW.user_request, NEW.output_text, 'Assistant output')), 1, 200)",
            "substr(trim(COALESCE(NEW.output_text, '')), 1, 4000)",
            "substr(trim('User request: ' || COALESCE(NEW.user_request, '') || char(10) || "
            "'Assistant output: ' || COALESCE(NEW.output_text, '') || char(10) || "
            "'Status: ' || COALESCE(NEW.status, '')), 1, 4000)",
        ),
        (
            "scheduled_agent_task_runs",
            "scheduled_run",
            "scheduled_task_run",
            "NEW.scheduled_for",
            "NEW.completed_at",
            "NEW.status",
            "NEW.status",
            "substr(trim('Scheduled task run: ' || COALESCE(NEW.status, 'scheduled')), 1, 200)",
            "substr(trim(COALESCE(NEW.error_message, '')), 1, 4000)",
            "substr(trim('Scheduled task run' || char(10) || "
            "'Status: ' || COALESCE(NEW.status, '') || char(10) || "
            "'Error: ' || COALESCE(NEW.error_message, '')), 1, 4000)",
        ),
    )
    for table, kind, event_type, occurred, ended, outcome, source_status, title, summary, content in raw_specs:
        document_id = f"'{kind}:' || CAST(NEW.id AS TEXT)"
        insert = (
            "INSERT INTO zettel_raw_search_fts "
            "(document_id, source_kind, source_id, event_type, occurred_at, ended_at, "
            "title, summary, outcome, source_status, content) "
            f"SELECT {document_id}, '{kind}', CAST(NEW.id AS TEXT), '{event_type}', "
            f"{occurred}, {ended}, {title}, {summary}, {outcome}, {source_status}, {content} "
            "WHERE NEW.zettel_id IS NULL;"
        )
        delete = f"DELETE FROM zettel_raw_search_fts WHERE document_id = {document_id};"
        for suffix, timing, body in (
            ("ai", "AFTER INSERT", delete + insert),
            ("au", "AFTER UPDATE", delete + insert),
            ("ad", "AFTER DELETE", f"DELETE FROM zettel_raw_search_fts WHERE document_id = '{kind}:' || CAST(OLD.id AS TEXT);"),
        ):
            name = f"trg_retrieval_raw_{table}_{suffix}"
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            conn.execute(f"CREATE TRIGGER {name} {timing} ON {table} BEGIN {body} END")

    zettel_content = (
        "substr(trim(COALESCE(NEW.title, '') || char(10) || "
        "COALESCE(NEW.summary, '') || char(10) || "
        "COALESCE(NEW.outcome, '') || char(10) || "
        "COALESCE(NEW.narrative, '')), 1, 4000)"
    )
    zettel_insert = (
        "INSERT INTO zettel_search_fts (entry_id, source_kind, occurred_at, content) "
        f"VALUES (NEW.id, NEW.source_kind, NEW.occurred_at, {zettel_content});"
    )
    for name, timing, body in (
        ("trg_retrieval_zettel_entries_ai", "AFTER INSERT", zettel_insert),
        ("trg_retrieval_zettel_entries_au", "AFTER UPDATE", "DELETE FROM zettel_search_fts WHERE entry_id = NEW.id;" + zettel_insert),
        ("trg_retrieval_zettel_entries_ad", "AFTER DELETE", "DELETE FROM zettel_search_fts WHERE entry_id = OLD.id;"),
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute(f"CREATE TRIGGER {name} {timing} ON zettel_entries BEGIN {body} END")


def ensure_fts_tables(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='activities_fts'
    """)
    if cursor.fetchone() is None:
        logger.info("Creating full-text search tables...")
        conn.execute("""
            CREATE VIRTUAL TABLE activities_fts USING fts5(
                activity_id UNINDEXED,
                content,
                tokenize='porter unicode61'
            )
        """)
        conn.execute("""
            INSERT INTO activities_fts(activity_id, content)
            SELECT id, COALESCE(window_title, '') || ' ' || COALESCE(extracted_text, '')
            FROM activities
        """)
        logger.info("Created and populated FTS tables")
    ensure_agent_task_search_fts(conn)
    ensure_meeting_transcript_fts(conn)
    ensure_zettel_raw_search_fts(conn)
    ensure_zettel_search_fts(conn)
    ensure_zettel_retrieval_fts_triggers(conn)
