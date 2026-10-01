"""Schema migration facade for the SQLite knowledge service."""

import sqlite3
import logging
from typing import Dict, List, Any, Set, Optional, Tuple

from ...schema import get_schema_statements
from .connection import get_sync_connection
from ..schema_management import introspection
from ..schema_management.agent_tasks.migrations import (
    drop_agent_tasks_parent_agent_task_id,
    migrate_agent_task_artifact_revisions,
    migrate_agent_tasks_table,
)
from ..schema_management.agent_tasks.delegated_agent_migrations import (
    migrate_delegated_agent_tables,
)
from ..schema_management.providers.discovery_migrations import migrate_provider_discovery_tables
from ..schema_management.providers.run_migrations import migrate_provider_run_tables
from ..schema_management.providers.interaction_migrations import migrate_provider_interaction_tables
from ..schema_management.execution_approvals.migrations import migrate_execution_approval_tables
from ..schema_management.managed_file_history.migrations import migrate_managed_file_history_tables
from ..schema_management.agent_tasks.summary_backfill import (
    agent_task_summary_backfill_needed,
    append_search_value,
    backfill_agent_task_summaries,
    build_agent_task_search_document,
    extract_agent_task_preview,
    get_finalizer_envelope,
    get_finalizer_file_count,
    safe_json_loads,
)
from ..schema_management.activity_work_context_migrations import migrate_activity_work_contexts
from ..schema_management.agent_work.migrations import migrate_agent_work_session_tables
from ..schema_management.basil_board_migrations import migrate_basil_board_tables
from ..schema_management.todos.migrations import migrate_todo_tables
from ..schema_management.conversation_migrations import migrate_conversation_indexes
from ..schema_management.personalization_migrations import (
    migrate_personalization_profile_table,
    migrate_writing_samples_table,
)
from ..schema_management.core_migrations import (
    migrate_activities_table,
    migrate_assistant_outputs_table,
    migrate_contact_identity_observations_table,
    migrate_retrieval_tables,
    migrate_transcriptions_table,
)
from ..schema_management.mcp_migrations import migrate_mcp_call_log_table
from ..schema_management.scheduling_migrations import migrate_scheduled_agent_tasks_tables
from ..schema_management.zettel_migrations import (
    migrate_conversation_memory_projection,
    migrate_zettel_backreference,
    migrate_zettel_tables,
)
from ..schema_management.american_spelling_migration import migrate_american_spelling
from ..schema_management.agent_follow_up_migrations import migrate_agent_follow_up_tables
from ..schema_management.fts.tables import (
    ensure_agent_task_search_fts,
    ensure_fts_tables,
)

logger = logging.getLogger(__name__)


class SchemaManager:
    """Owns all schema migration, column validation, and introspection logic.

    Attributes:
        db_path: Path to the SQLite database file.
        schema: Cached mapping of ``{table_name: {column_names}}``.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.schema: Dict[str, Set[str]] = {}

    # ------------------------------------------------------------------
    # Initialization & migration
    # ------------------------------------------------------------------

    def initialize_db(self) -> None:
        """Initialize database schema if needed, applying incremental migrations."""
        logger.info(f"Initializing database at {self.db_path}")
        try:
            with get_sync_connection(self.db_path) as conn:
                self._migrate_american_spelling(conn)
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='activities'
                """)
                table_exists = cursor.fetchone() is not None

                if not table_exists:
                    logger.info("Activities table doesn't exist, creating full schema")
                    for statement in get_schema_statements():
                        logger.debug(f"Executing schema statement: {statement[:100]}...")
                        conn.execute(statement)
                    conn.commit()
                    logger.info("Created initial database schema successfully")
                else:
                    logger.info("Activities table exists, checking for schema updates")
                    self._migrate_activities_table(conn)
                    self._migrate_agent_tasks_table(conn)
                    self._migrate_agent_task_artifact_revisions(conn)
                    self._migrate_delegated_agent_tables(conn)
                    self._migrate_assistant_outputs_table(conn)
                    self._migrate_scheduled_agent_tasks_tables(conn)
                    self._migrate_transcriptions_table(conn)
                    self._migrate_mcp_call_log_table(conn)
                    self._migrate_agent_work_session_tables(conn)
                    self._migrate_provider_run_tables(conn)
                    self._migrate_provider_discovery_tables(conn)
                    self._migrate_provider_interaction_tables(conn)
                    self._migrate_execution_approval_tables(conn)
                    self._migrate_contact_identity_observations_table(conn)
                    self._migrate_activity_work_contexts(conn)
                    self._migrate_zettel_tables(conn)
                    self._migrate_retrieval_tables(conn)
                    self._migrate_personalization_profile_table(conn)

                # Runs for both fresh and existing databases: source tables are
                # created without zettel_id in either path, and this adds it
                # idempotently. Presence of zettel_id replaces the watermark.
                self._migrate_delegated_agent_tables(conn)
                self._migrate_zettel_backreference(conn)
                migrate_conversation_memory_projection(conn)
                self._migrate_retrieval_tables(conn)
                self._migrate_conversation_indexes(conn)
                self._migrate_todo_tables(conn)
                self._migrate_basil_board_tables(conn)
                self._migrate_execution_approval_tables(conn)
                self._migrate_managed_file_history_tables(conn)
                self._migrate_agent_follow_up_tables(conn)
                self._migrate_writing_samples_table(conn)

                self._ensure_fts_tables(conn)
                conn.commit()
        except Exception as e:
            logger.error(f"Error initializing database: {e}", exc_info=True)
            raise

    def load_schema(self) -> Dict[str, Set[str]]:
        """Load and cache column information for every table."""
        schema = introspection.load_schema(self.db_path)
        self.schema = schema
        return schema

    # ------------------------------------------------------------------
    # Query-building helpers
    # ------------------------------------------------------------------

    def validate_query_columns(self, table: str, columns: List[str]) -> List[str]:
        """Return the subset of *columns* that actually exist in *table*."""
        return introspection.validate_query_columns(self.schema, table, columns)

    def build_select_query(
        self,
        table: str,
        columns: List[str],
        conditions: Optional[List[Tuple[str, str, Any]]] = None,
    ) -> Tuple[str, List[Any]]:
        """Build a parameterized SELECT query with schema validation.

        Returns:
            ``(query_string, parameters)``
        """
        return introspection.build_select_query(self.schema, table, columns, conditions)

    # ------------------------------------------------------------------
    # Schema introspection (async + sync)
    # ------------------------------------------------------------------

    async def get_schema_info(self) -> Dict[str, Any]:
        """Return detailed schema information (tables, columns, indexes, FKs)."""
        return await introspection.get_schema_info(self.db_path)

    def get_schema_info_sync(self) -> Dict[str, Any]:
        """Synchronous variant of :meth:`get_schema_info`."""
        return introspection.get_schema_info_sync(self.db_path)

    # ------------------------------------------------------------------
    # Internal migration helpers
    # ------------------------------------------------------------------

    def _migrate_activities_table(self, conn: sqlite3.Connection) -> None:
        migrate_activities_table(conn)

    def _migrate_agent_tasks_table(self, conn: sqlite3.Connection) -> None:
        migrate_agent_tasks_table(conn)

    def _migrate_agent_task_artifact_revisions(self, conn: sqlite3.Connection) -> None:
        migrate_agent_task_artifact_revisions(conn)

    def _migrate_delegated_agent_tables(self, conn: sqlite3.Connection) -> None:
        """Create generic parent-owned delegated-agent lifecycle tables."""
        migrate_delegated_agent_tables(conn)

    def _safe_json_loads(self, value: Optional[str]) -> Any:
        return safe_json_loads(value)

    def _get_finalizer_envelope(self, result_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return get_finalizer_envelope(result_data)

    def _get_finalizer_file_count(self, result_data: Dict[str, Any]) -> int:
        return get_finalizer_file_count(result_data)

    def _extract_agent_task_preview(self, result_data: Any) -> Tuple[Optional[str], int]:
        return extract_agent_task_preview(result_data)

    def _append_search_value(self, parts: List[str], value: Any) -> None:
        append_search_value(parts, value)

    def _build_agent_task_search_document(self, rows: List[sqlite3.Row]) -> str:
        return build_agent_task_search_document(rows)

    def _ensure_agent_task_search_fts(self, conn: sqlite3.Connection) -> None:
        ensure_agent_task_search_fts(conn)

    def _agent_task_summary_backfill_needed(self, conn: sqlite3.Connection) -> bool:
        return agent_task_summary_backfill_needed(conn)

    def _backfill_agent_task_summaries(self, conn: sqlite3.Connection) -> None:
        backfill_agent_task_summaries(conn)

    def _drop_agent_tasks_parent_agent_task_id(self, conn: sqlite3.Connection) -> None:
        """Remove the legacy parent_agent_task_id column after chain backfill."""
        drop_agent_tasks_parent_agent_task_id(conn)

    def _migrate_assistant_outputs_table(self, conn: sqlite3.Connection) -> None:
        migrate_assistant_outputs_table(conn)

    def _migrate_scheduled_agent_tasks_tables(self, conn: sqlite3.Connection) -> None:
        """Ensure scheduled agent task tables and indexes exist in existing databases."""
        migrate_scheduled_agent_tasks_tables(conn)

    def _migrate_mcp_call_log_table(self, conn: sqlite3.Connection) -> None:
        """Create the mcp_call_log table and indexes on existing databases.

        Pure additive migration: there is no prior version of this table, so
        the only operation is "create if missing." Mirrors the create-only
        branch of ``_migrate_scheduled_agent_tasks_tables``.
        """
        migrate_mcp_call_log_table(conn)

    def _migrate_agent_work_session_tables(self, conn: sqlite3.Connection) -> None:
        """Create durable iterative work-session tables on existing databases."""
        migrate_agent_work_session_tables(conn)

    def _migrate_provider_run_tables(self, conn: sqlite3.Connection) -> None:
        """Create attended generic ACP provider tables on existing databases."""
        migrate_provider_run_tables(conn)

    def _migrate_provider_discovery_tables(self, conn: sqlite3.Connection) -> None:
        """Create durable provider-target discovery and authorization tables."""
        migrate_provider_discovery_tables(conn)

    def _migrate_provider_interaction_tables(self, conn: sqlite3.Connection) -> None:
        """Create durable provider user-input interaction tables on existing databases."""
        migrate_provider_interaction_tables(conn)

    def _migrate_execution_approval_tables(self, conn: sqlite3.Connection) -> None:
        """Create durable generic execution approval tables on existing databases."""
        migrate_execution_approval_tables(conn)

    def _migrate_managed_file_history_tables(self, conn: sqlite3.Connection) -> None:
        """Create durable managed file-change history tables and reconcile any
        changes left in the ``prepared`` state by an interrupted prior process."""
        migrate_managed_file_history_tables(conn)

    def _migrate_contact_identity_observations_table(self, conn: sqlite3.Connection) -> None:
        """Create the contact_identity_observations table on existing databases.

        Pure additive migration mirroring the create-only branch of
        ``_migrate_mcp_call_log_table``. Observations are screen-derived
        candidate identity facts and are intentionally separate from
        contact_relationships.
        """
        migrate_contact_identity_observations_table(conn)

    def _migrate_transcriptions_table(self, conn: sqlite3.Connection) -> None:
        """Add lifecycle columns (0.9.0) to existing transcriptions tables.

        Existing rows get status='completed' via the column's DEFAULT so the
        history UI keeps treating pre-migration rows as successful runs.
        error_message stays NULL for those rows.
        """
        migrate_transcriptions_table(conn)

    def _migrate_activity_work_contexts(self, conn: sqlite3.Connection) -> None:
        """Backfill work-context metadata and reset stale screen-block projections."""
        migrate_activity_work_contexts(conn)

    def _migrate_zettel_tables(self, conn: sqlite3.Connection) -> None:
        """Create the zettel unified event stream tables on existing databases."""
        migrate_zettel_tables(conn)

    def _migrate_retrieval_tables(self, conn: sqlite3.Connection) -> None:
        """Create canonical retrieval-index metadata tables."""
        migrate_retrieval_tables(conn)

    def _migrate_personalization_profile_table(self, conn: sqlite3.Connection) -> None:
        """Ensure user_profile exists and carries the custom_instructions column."""
        migrate_personalization_profile_table(conn)

    def _migrate_writing_samples_table(self, conn: sqlite3.Connection) -> None:
        """Add the Assistant History link column to writing_samples when present."""
        migrate_writing_samples_table(conn)

    def _migrate_conversation_indexes(self, conn: sqlite3.Connection) -> None:
        """Install additive indexes required by conversation history pages."""
        migrate_conversation_indexes(conn)

    def _migrate_todo_tables(self, conn: sqlite3.Connection) -> None:
        """Create durable To-Do tables and apply additive To-Do schema migrations."""
        migrate_todo_tables(conn)

    def _migrate_basil_board_tables(self, conn: sqlite3.Connection) -> None:
        """Create BasilBoard registry tables and seed the Home tab."""
        migrate_basil_board_tables(conn)

    def _migrate_zettel_backreference(self, conn: sqlite3.Connection) -> None:
        """Add zettel_id to source tables and narrative columns to zettel_entries."""
        migrate_zettel_backreference(conn)

    def _ensure_fts_tables(self, conn: sqlite3.Connection) -> None:
        ensure_fts_tables(conn)

    def _migrate_american_spelling(self, conn: sqlite3.Connection) -> None:
        """Rewrite persisted British cancel spellings before any migration copies rows into American-only CHECK constraints."""
        migrate_american_spelling(conn)

    def _migrate_agent_follow_up_tables(self, conn: sqlite3.Connection) -> None:
        """Create the durable agent follow-up table on fresh and existing databases."""
        migrate_agent_follow_up_tables(conn)
