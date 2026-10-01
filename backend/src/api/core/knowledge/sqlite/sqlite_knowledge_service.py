"""Enhanced SQLite-based knowledge service with full-text search and metadata support.

This module is the public facade.  All heavy logic lives in the component
services under ``sqlite_knowledge_service_component_services/``.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Set, Callable

from ..models import Activity, AgentTask
from api.core.runtime.validation_profile import (
    ValidationRuntimeProfile,
    is_validation_runtime,
)
from .sqlite_knowledge_service_component_services.activities.retrieval_service import ActivityRetrievalService
from .sqlite_knowledge_service_component_services.activities.pattern_repository import ActivityPatternRepository
from .sqlite_knowledge_service_component_services.activities.search_repository import ActivitySearchRepository
from .sqlite_knowledge_service_component_services.activities.storage_repository import ActivityStorageRepository
from .sqlite_knowledge_service_component_services.agent_tasks.events import AgentTaskEvent
from .sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_repository import (
    DelegatedAgentRepository,
)
from .sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_evidence_repository import (
    DelegatedAgentEvidenceRepository,
)
from .sqlite_knowledge_service_component_services.agent_tasks.service import AgentTaskService
from .sqlite_knowledge_service_component_services.agent_work.entity_repository import AgentWorkEntityRepository
from .sqlite_knowledge_service_component_services.agent_work.event_repository import AgentWorkEventRepository
from .sqlite_knowledge_service_component_services.agent_work.item_repository import AgentWorkItemRepository
from .sqlite_knowledge_service_component_services.agent_work.receipt_repository import AgentWorkReceiptRepository
from .sqlite_knowledge_service_component_services.agent_work.session_repository import AgentWorkSessionRepository
from .sqlite_knowledge_service_component_services.execution_approvals.repository import ExecutionApprovalRepository
from .sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
    initialize_sqlite_database_mode,
)
from .sqlite_knowledge_service_component_services.infrastructure.schema_manager import SchemaManager
from .sqlite_knowledge_service_component_services.mcp.call_log_repository import MCPCallLogRepository
from .sqlite_knowledge_service_component_services.meetings.transcript_search_repository import MeetingTranscriptSearchRepository
from .sqlite_knowledge_service_component_services.providers.delegation_repository import ProviderTargetDelegationRepository
from .sqlite_knowledge_service_component_services.providers.discovery_proposal_repository import ProviderDiscoveryProposalRepository
from .sqlite_knowledge_service_component_services.providers.interaction_repository import ProviderInteractionRepository
from .sqlite_knowledge_service_component_services.providers.profile_repository import ProviderProfileRepository
from .sqlite_knowledge_service_component_services.providers.run_repository import ProviderRunRepository
from .sqlite_knowledge_service_component_services.providers.runtime_evidence_repository import (
    ProviderRuntimeEvidenceRepository,
)
from .sqlite_knowledge_service_component_services.providers.target_authorization_repository import ProviderTargetAuthorizationRepository
from .sqlite_knowledge_service_component_services.scheduling.repository import ScheduledAgentTaskRepository
from .sqlite_knowledge_service_component_services.agent_tasks.follow_up_repository import AgentTaskFollowUpRepository

logger = logging.getLogger(__name__)


class SQLiteKnowledgeService:
    """Thin orchestrator that composes specialized component services."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize the knowledge base service."""
        print("\n==== SQLITE SERVICE INITIALIZATION ====")
        print(f"Input db_path: {db_path}")

        if db_path is None:
            if is_validation_runtime():
                db_path = ValidationRuntimeProfile.from_environment().runtime_root / "knowledge_base.db"
            else:
                db_path = Path.home() / ".basil" / "knowledge_base.db"
            print(f"Using default db_path: {db_path}")
        else:
            print(f"Using provided db_path: {db_path}")

        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_path)
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db_path = db_path

        print("\n==== SQLITE SERVICE INITIALIZATION ====")
        print(f"Database path: {self.db_path}")
        print(f"Absolute path: {Path(self.db_path).absolute()}")
        print(f"Path exists: {Path(self.db_path).exists()}")
        print(f"Path is file: {Path(self.db_path).is_file() if Path(self.db_path).exists() else 'N/A'}")
        print(f"Path parent: {Path(self.db_path).parent}")
        print(f"Path parent exists: {Path(self.db_path).parent.exists()}")

        other_path = Path.home() / ".basil" / "knowledge_base.db"
        print(f"Alternative path: {other_path}")
        print(f"Alternative path exists: {other_path.exists()}")
        print(f"Alternative path is file: {other_path.is_file() if other_path.exists() else 'N/A'}")

        print("==== END SQLITE SERVICE INITIALIZATION ====\n")

        db_file = Path(self.db_path)
        if db_file.exists():
            logger.info(f"Database file exists at {self.db_path}, size: {db_file.stat().st_size} bytes")
        else:
            logger.info(f"Database file does not exist at {self.db_path}, will be created")

        try:
            if not db_file.exists():
                with open(self.db_path, 'w'):
                    pass
                logger.info(f"Successfully created empty database file at {self.db_path}")

            with open(self.db_path, 'a'):
                pass
            logger.info(f"Database file is writable at {self.db_path}")
        except Exception as e:
            logger.error(f"Error accessing database file: {e}", exc_info=True)
            raise

        # --- Component services ---------------------------------------------------
        initialize_sqlite_database_mode(self.db_path)
        self._schema_manager = SchemaManager(self.db_path)
        self._schema_manager.initialize_db()
        self.schema: Dict[str, Set[str]] = self._schema_manager.load_schema()
        logger.info(f"Loaded schema: {self.schema}")

        self.activity_retrieval_service = ActivityRetrievalService(self.db_path)
        self.activity_pattern_repository = ActivityPatternRepository(self.db_path, self.schema)
        self.activity_search_repository = ActivitySearchRepository(self.db_path, self.schema)
        self.activity_storage_repository = ActivityStorageRepository(self.db_path, self.schema)
        self.agent_task_service = AgentTaskService(self.db_path)
        self.delegated_agent_repository = DelegatedAgentRepository(self.db_path)
        self.delegated_agent_evidence_repository = DelegatedAgentEvidenceRepository(self.db_path)
        self.scheduled_agent_task_repository = ScheduledAgentTaskRepository(self.db_path)
        self.agent_task_follow_up_repository = AgentTaskFollowUpRepository(self.db_path)
        self.mcp_call_log_repository = MCPCallLogRepository(self.db_path)
        self.agent_work_session_repository = AgentWorkSessionRepository(self.db_path)
        self.agent_work_item_repository = AgentWorkItemRepository(self.db_path)
        self.agent_work_entity_repository = AgentWorkEntityRepository(self.db_path)
        self.agent_work_event_repository = AgentWorkEventRepository(self.db_path)
        self.agent_work_receipt_repository = AgentWorkReceiptRepository(self.db_path)
        self.provider_profile_repository = ProviderProfileRepository(self.db_path)
        self.provider_run_repository = ProviderRunRepository(self.db_path)
        self.provider_discovery_proposal_repository = ProviderDiscoveryProposalRepository(self.db_path)
        self.provider_target_authorization_repository = ProviderTargetAuthorizationRepository(self.db_path)
        self.provider_target_delegation_repository = ProviderTargetDelegationRepository(self.db_path)
        self.provider_runtime_evidence_repository = ProviderRuntimeEvidenceRepository(self.db_path)
        self.provider_interaction_repository = ProviderInteractionRepository(self.db_path)
        self.execution_approval_repository = ExecutionApprovalRepository(self.db_path)
        self.meeting_transcript_search_repository = MeetingTranscriptSearchRepository(self.db_path)

    # ------------------------------------------------------------------
    # Voice-agent-task event callbacks (delegated)
    # ------------------------------------------------------------------

    def register_agent_task_callback(self, callback: Callable[[AgentTaskEvent], None]) -> None:
        """Register a callback to be called when agent_task events occur."""
        return self.agent_task_service.register_agent_task_callback(callback)

    def unregister_agent_task_callback(self, callback: Callable[[AgentTaskEvent], None]) -> None:
        """Unregister a agent_task callback."""
        return self.agent_task_service.unregister_agent_task_callback(callback)

    # ------------------------------------------------------------------
    # Activity storage & mutations (delegated to domain repositories)
    # ------------------------------------------------------------------

    async def store_activity(
        self,
        timestamp: datetime,
        app_name: str,
        window_title: Optional[str] = None,
        extracted_text: Optional[str] = None,
        ai_analysis: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        capture_frequency_minutes: Optional[float] = None,
        content_fingerprint: Optional[str] = None,
        observation_count: int = 1,
        last_observed_at: Optional[datetime] = None,
    ) -> str:
        return await self.activity_storage_repository.store_activity(
            timestamp=timestamp, app_name=app_name, window_title=window_title,
            extracted_text=extracted_text, ai_analysis=ai_analysis,
            duration=duration, metadata=metadata,
            capture_frequency_minutes=capture_frequency_minutes,
            content_fingerprint=content_fingerprint,
            observation_count=observation_count,
            last_observed_at=last_observed_at,
        )

    async def search_activities(
        self,
        time_range: Optional[Dict[str, datetime]] = None,
        text_search: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Activity]:
        return await self.activity_search_repository.search_activities(
            time_range=time_range, text_search=text_search,
            metadata_filters=metadata_filters, limit=limit,
        )

    async def count_activities_by_metadata(self, key: str, value: str) -> int:
        return await self.activity_search_repository.count_activities_by_metadata(key, value)

    async def count_automatic_captures_since(self, cutoff: Optional[datetime]) -> int:
        return await self.activity_search_repository.count_automatic_captures_since(cutoff)

    async def get_activity_patterns(self, lookback_days: int = 7) -> Dict[str, Any]:
        return await self.activity_pattern_repository.get_activity_patterns(lookback_days)

    async def store_pattern(
        self, pattern_type: str, pattern_data: Dict[str, Any], confidence: float = 1.0,
    ) -> str:
        return await self.activity_pattern_repository.store_pattern(pattern_type, pattern_data, confidence)

    async def get_similar_activities(
        self, activity_id: str, min_similarity: float = 0.5, limit: int = 10,
    ) -> List[Dict[str, Any]]:
        return await self.activity_search_repository.get_similar_activities(activity_id, min_similarity, limit)

    async def update_activity(self, activity_id: str, updates: Dict[str, Any]) -> None:
        return await self.activity_storage_repository.update_activity(activity_id, updates)

    async def find_open_sequence_activity(
        self,
        app_name: str,
        work_context_key: Optional[str],
        max_age_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        return await self.activity_storage_repository.find_open_sequence_activity(
            app_name=app_name,
            work_context_key=work_context_key,
            max_age_seconds=max_age_seconds,
        )

    async def update_activity_metadata(self, activity_id: str, metadata: Dict[str, Any]) -> None:
        return await self.activity_storage_repository.update_activity_metadata(activity_id, metadata)

    async def delete_activity(self, activity_id: str) -> bool:
        return await self.activity_storage_repository.delete_activity(activity_id)

    async def cleanup_old_activities(self, days: int = 30) -> None:
        return await self.activity_storage_repository.cleanup_old_activities(days)

    async def get_activity_by_id(self, activity_id: str) -> Optional[Activity]:
        return await self.activity_retrieval_service.get_activity_by_id(activity_id)

    # ------------------------------------------------------------------
    # AgentTask CRUD (delegated to AgentTaskService)
    # ------------------------------------------------------------------

    async def store_agent_task(
        self,
        agent_task_id: str,
        original_prompt: str,
        transcribed_prompt: str,
        display_prompt_markdown: Optional[str] = None,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        screen_text: Optional[str] = None,
        screen_capture_path: Optional[str] = None,
        confidence_score: Optional[float] = None,
        status: str = "processing",
        root_task_id: Optional[str] = None,
        previous_task_id: Optional[str] = None,
        chain_sequence_number: int = 0,
        session_type: Optional[str] = None,
        accumulated_artifacts: Optional[Dict[str, Any]] = None,
        title: Optional[str] = None,
        origin_type: Optional[str] = None,
        origin_id: Optional[str] = None,
    ) -> str:
        return await self.agent_task_service.store_agent_task(
            agent_task_id=agent_task_id, original_prompt=original_prompt,
            transcribed_prompt=transcribed_prompt,
            display_prompt_markdown=display_prompt_markdown, app_name=app_name,
            window_title=window_title, screen_text=screen_text,
            screen_capture_path=screen_capture_path, confidence_score=confidence_score,
            status=status,
            root_task_id=root_task_id, previous_task_id=previous_task_id,
            chain_sequence_number=chain_sequence_number, session_type=session_type,
            accumulated_artifacts=accumulated_artifacts, title=title,
            origin_type=origin_type, origin_id=origin_id,
        )

    async def update_agent_task_status(
        self,
        agent_task_id: str,
        status: str,
        operation_parameters: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        return await self.agent_task_service.update_agent_task_status(
            agent_task_id=agent_task_id, status=status,
            operation_parameters=operation_parameters, result_data=result_data,
        )

    async def update_agent_task_status_if_active(
        self,
        agent_task_id: str,
        status: str,
        operation_parameters: Optional[Dict[str, Any]] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return await self.agent_task_service.update_agent_task_status_if_active(
            agent_task_id=agent_task_id,
            status=status,
            operation_parameters=operation_parameters,
            result_data=result_data,
        )

    async def cancel_agent_tasks_if_active(
        self,
        agent_task_ids: List[str],
        result_data: Dict[str, Any],
    ) -> List[str]:
        return await self.agent_task_service.cancel_agent_tasks_if_active(
            agent_task_ids=agent_task_ids,
            result_data=result_data,
        )

    async def add_agent_task_clarification(
        self,
        agent_task_id: str,
        clarification_text: str,
        clarification_agent_task: Optional[str] = None,
    ) -> None:
        return await self.agent_task_service.add_agent_task_clarification(
            agent_task_id=agent_task_id, clarification_text=clarification_text,
            clarification_agent_task=clarification_agent_task,
        )

    async def get_agent_task(self, agent_task_id: str) -> Optional[AgentTask]:
        return await self.agent_task_service.get_agent_task(agent_task_id)

    async def get_agent_task_chain(self, root_task_id: str) -> List[AgentTask]:
        return await self.agent_task_service.get_agent_task_chain(root_task_id)

    async def list_agent_tasks_by_origin(
        self, origin_type: str, origin_id: str, include_terminal: bool = True
    ) -> List[AgentTask]:
        return await self.agent_task_service.list_agent_tasks_by_origin(origin_type, origin_id, include_terminal)

    async def list_nonterminal_agent_tasks_by_origin_type(self, origin_type: str) -> List[AgentTask]:
        return await self.agent_task_service.list_nonterminal_agent_tasks_by_origin_type(origin_type)

    async def list_latest_agent_task_status_by_origins(
        self, origin_type: str, origin_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        return await self.agent_task_service.list_latest_agent_task_status_by_origins(origin_type, origin_ids)

    async def list_agent_task_origin_ids_by_origin_type(self, origin_type: str) -> List[str]:
        return await self.agent_task_service.list_agent_task_origin_ids_by_origin_type(origin_type)

    async def list_recent_conversation_task_summaries(
        self,
        conversation_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Return bounded terminal task-chain summaries owned by one Conversation."""
        return await self.agent_task_service.list_recent_conversation_task_summaries(
            conversation_id,
            limit,
        )

    async def update_agent_task_screen_context(
        self,
        agent_task_id: str,
        screen_text: Optional[str] = None,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        screen_capture_path: Optional[str] = None,
    ) -> None:
        return await self.agent_task_service.update_agent_task_screen_context(
            agent_task_id=agent_task_id, screen_text=screen_text,
            app_name=app_name, window_title=window_title,
            screen_capture_path=screen_capture_path,
        )

    # ------------------------------------------------------------------
    # Schema introspection (delegated to SchemaManager)
    # ------------------------------------------------------------------

    async def get_schema_info(self) -> Dict[str, Any]:
        return await self._schema_manager.get_schema_info()

    def get_schema_info_sync(self) -> Dict[str, Any]:
        return self._schema_manager.get_schema_info_sync()

    # ------------------------------------------------------------------
    # Generic query execution
    # ------------------------------------------------------------------

    async def execute_write_query(self, query: str, params: tuple = None) -> int:
        """Execute a write query (INSERT, UPDATE, DELETE) and return rows affected."""
        conn = await get_async_connection(self.db_path)
        try:
            cursor = await conn.execute(query, params or ())
            rows_affected = cursor.rowcount
            await conn.commit()
            return rows_affected
        except Exception as e:
            await conn.rollback()
            logger.error(f"Error executing write query: {e}")
            raise
        finally:
            await conn.close()

    async def execute_read_query(self, query: str, params: tuple = None) -> List[Any]:
        """Execute a read query (SELECT) and return the results."""
        conn = await get_async_connection(self.db_path)
        try:
            cursor = await conn.execute(query, params or ())
            rows = await cursor.fetchall()
            return rows
        except Exception as e:
            logger.error(f"Error executing read query: {e}")
            raise
        finally:
            await conn.close()
