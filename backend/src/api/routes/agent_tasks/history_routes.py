"""History and detail routes for agent tasks."""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService  # type: ignore[import-untyped]
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.list_filters import (  # type: ignore[import-untyped]
    AgentTaskListFilters,
)
from api.dependencies import get_sqlite_knowledge_service  # type: ignore[import-untyped]
from api.services.agent_follow_ups.follow_up_events import notify_follow_ups_changed
from api.services.agent_processing.lifecycle.delegation.delegated_agent_evidence_service import (
    DelegatedAgentEvidenceService,
)
from api.services.agent_processing.lifecycle.finalization.task_state_persistence import (
    normalize_thinking_history,
)

from .models import (
    ActiveAgentItem,
    ActiveAgentsResponse,
    AgentTaskChainItem,
    AgentTaskDetailResponse,
    AgentTaskHistoryResponse,
    AgentTaskListItem,
    AgentTaskPresentationSummaryResponse,
    AgentTaskSearchMatchesResponse,
    CancelPendingFollowUpsResponse,
    PendingFollowUpItem,
    PendingFollowUpsResponse,
)
from .projections.artifact_presentation import build_agent_task_presentation_summary
from .utils import (
    derive_result_severity,
    extract_checkpoint_data,
    extract_connection_references,
    extract_model_used,
    extract_original_model_id,
    extract_result_data,
    extract_result_outcome,
    extract_suggested_follow_ups,
)

logger = logging.getLogger(__name__)

router = APIRouter()

SOURCE_FILTER_PATTERN = "^(direct|conversation|todo|meeting|scheduled)$"
TURNS_FILTER_PATTERN = "^(single|follow_ups)$"


def _list_filters(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    source: Optional[str],
    status: Optional[str],
    app: Optional[str],
    has_documents: Optional[bool],
    turns: Optional[str],
) -> AgentTaskListFilters:
    """Gather the sidebar filter query parameters shared by the history list and the history search."""
    return AgentTaskListFilters(
        start_date=start_date,
        end_date=end_date,
        source=source,
        status=status,
        app_contains=app,
        has_documents=has_documents,
        multi_turn=None if turns is None else turns == "follow_ups",
    )


@router.get("/history", response_model=AgentTaskHistoryResponse, summary="Get AgentTask History")
async def get_agent_task_history(
    limit: int = Query(50, ge=1, le=300, description="Maximum number of agent tasks to return"),
    offset: int = Query(0, ge=0, description="Number of agent tasks to skip for pagination"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'completed'), or 'active' for chains that are running or waiting"),
    archived: bool = Query(False, description="When true, return only archived chains; otherwise only chains that are not archived"),
    start_date: Annotated[Optional[datetime], Query(description="Only chains whose last activity is at or after this instant")] = None,
    end_date: Annotated[Optional[datetime], Query(description="Only chains whose last activity is at or before this instant")] = None,
    source: Annotated[Optional[str], Query(pattern=SOURCE_FILTER_PATTERN, description="Where the task came from: direct, conversation, todo, meeting or scheduled")] = None,
    app: Annotated[Optional[str], Query(description="Only chains captured in an application whose name contains this text")] = None,
    has_documents: Annotated[Optional[bool], Query(description="True keeps chains with documents and false keeps chains without")] = None,
    turns: Annotated[Optional[str], Query(pattern=TURNS_FILTER_PATTERN, description="single keeps one-turn chains and follow_ups keeps chains with follow-ups")] = None,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service)
) -> AgentTaskHistoryResponse:
    """
    Get paginated list of agent_task history.
    Returns summary information for each agent task suitable for display in a sidebar.
    Only returns root agent tasks (not follow-ups in a chain).
    """
    try:
        summaries = await knowledge_service.agent_task_service.list_recent_agent_task_summaries(
            limit=limit + 1,  # Fetch one extra to check if there are more
            offset=offset,
            archived=archived,
            filters=_list_filters(start_date, end_date, source, status, app, has_documents, turns),
        )

        # Check if there are more results
        has_more = len(summaries) > limit
        if has_more:
            summaries = summaries[:limit]  # Trim to requested limit

        agent_task_ids = [summary["id"] for summary in summaries]
        scheduled_mapping = await knowledge_service.scheduled_agent_task_repository.get_scheduled_run_mapping(agent_task_ids)

        # Convert to list items with preview
        agent_task_items = []
        for summary in summaries:
            agent_task_id = summary["id"]
            agent_task_items.append(AgentTaskListItem(
                id=agent_task_id,
                original_prompt=summary["original_prompt"],
                title=summary.get("title"),
                result_preview=summary.get("result_preview"),
                timestamp=summary["timestamp"],
                status=summary["status"],
                outcome=extract_result_outcome(summary.get("result_data")),
                result_severity=derive_result_severity(summary["status"], summary.get("result_data")),
                file_count=summary.get("file_count", 0),
                app_name=summary.get("app_name"),
                follow_up_count=summary.get("follow_up_count", 0),
                origin_type=summary.get("origin_type"),
                origin_id=summary.get("origin_id"),
                archived_at=summary.get("archived_at"),
                is_scheduled_run=agent_task_id in scheduled_mapping,
                scheduled_agent_task_id=scheduled_mapping.get(agent_task_id, {}).get("scheduled_agent_task_id"),
                scheduled_agent_task_title=scheduled_mapping.get(agent_task_id, {}).get("scheduled_agent_task_title"),
            ))

        logger.info(f"Retrieved {len(agent_task_items)} agent_tasks for history (limit={limit}, offset={offset})")

        response = AgentTaskHistoryResponse(
            agentTasks=agent_task_items,
            total_count=len(agent_task_items),
            has_more=has_more
        )
        return response

    except Exception as e:
        logger.error(f"Error getting agent_task history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving agent_task history: {str(e)}")


@router.get("/agent-task-history/search", response_model=AgentTaskHistoryResponse, summary="Search AgentTask History")
async def search_agent_task_history(
    query: Optional[str] = Query(None, description="Text to search in agent task text"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'completed', 'failed'), or 'active' for chains that are running or waiting"),
    app: Optional[str] = Query(None, description="Only chains captured in an application whose name contains this text"),
    days: Optional[int] = Query(None, ge=1, le=365, description="Only search within the last N days"),
    limit: int = Query(50, ge=1, le=300, description="Maximum number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip for pagination"),
    archived: bool = Query(False, description="When true, search only archived chains; otherwise only chains that are not archived"),
    start_date: Annotated[Optional[datetime], Query(description="Only chains whose last activity is at or after this instant")] = None,
    end_date: Annotated[Optional[datetime], Query(description="Only chains whose last activity is at or before this instant")] = None,
    source: Annotated[Optional[str], Query(pattern=SOURCE_FILTER_PATTERN, description="Where the task came from: direct, conversation, todo, meeting or scheduled")] = None,
    has_documents: Annotated[Optional[bool], Query(description="True keeps chains with documents and false keeps chains without")] = None,
    turns: Annotated[Optional[str], Query(pattern=TURNS_FILTER_PATTERN, description="single keeps one-turn chains and follow_ups keeps chains with follow-ups")] = None,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service)
) -> AgentTaskHistoryResponse:
    """
    Search agent_task history with text search and filtering.

    Searches both original_prompt and transcribed_prompt fields.
    Returns summary information for each matching agent task suitable for display in a sidebar.
    Only returns root agent tasks (not follow-ups in a chain).
    """
    try:
        # Calculate start_date if days filter is specified
        days_start_date = None
        if days:
            days_start_date = datetime.now() - timedelta(days=days)

        summaries = await knowledge_service.agent_task_service.search_agent_task_summaries(
            query=query,
            start_date=days_start_date,
            limit=limit + 1,  # Fetch one extra to check if there are more
            offset=offset,
            archived=archived,
            filters=_list_filters(start_date, end_date, source, status, app, has_documents, turns),
        )

        # Check if there are more results
        has_more = len(summaries) > limit
        if has_more:
            summaries = summaries[:limit]  # Trim to requested limit

        agent_task_ids = [summary["id"] for summary in summaries]
        scheduled_mapping = await knowledge_service.scheduled_agent_task_repository.get_scheduled_run_mapping(agent_task_ids)

        # Convert to list items with preview
        agent_task_items = []
        for summary in summaries:
            agent_task_id = summary["id"]
            agent_task_items.append(AgentTaskListItem(
                id=agent_task_id,
                original_prompt=summary["original_prompt"],
                title=summary.get("title"),
                result_preview=summary.get("result_preview"),
                timestamp=summary["timestamp"],
                status=summary["status"],
                outcome=extract_result_outcome(summary.get("result_data")),
                result_severity=derive_result_severity(summary["status"], summary.get("result_data")),
                file_count=summary.get("file_count", 0),
                app_name=summary.get("app_name"),
                follow_up_count=summary.get("follow_up_count", 0),
                origin_type=summary.get("origin_type"),
                origin_id=summary.get("origin_id"),
                archived_at=summary.get("archived_at"),
                is_scheduled_run=agent_task_id in scheduled_mapping,
                scheduled_agent_task_id=scheduled_mapping.get(agent_task_id, {}).get("scheduled_agent_task_id"),
                scheduled_agent_task_title=scheduled_mapping.get(agent_task_id, {}).get("scheduled_agent_task_title"),
            ))

        logger.info(f"AgentTask search returned {len(agent_task_items)} results (query={query}, status={status}, app={app})")

        return AgentTaskHistoryResponse(
            agentTasks=agent_task_items,
            total_count=len(agent_task_items),
            has_more=has_more
        )

    except Exception as e:
        logger.error(f"Error searching agent_task history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error searching agent_task history: {str(e)}")


@router.get("/active", response_model=ActiveAgentsResponse, summary="Get Active Agent Tasks")
async def get_active_agent_tasks(
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service)
) -> ActiveAgentsResponse:
    """
    Get all currently active/processing agent_tasks.

    Active agent tasks are those with status in ('routing', 'processing', 'awaiting_user_input').
    Used to restore multi-agent state on app launch and to populate the active agents sidebar.
    """
    try:
        # Get active agent tasks from the service
        active_agent_tasks = await knowledge_service.agent_task_service.list_active_agent_tasks()

        # Convert to response items
        agent_items = []
        for agent_task in active_agent_tasks:
            agent_items.append(ActiveAgentItem(
                id=agent_task.id,
                original_prompt=agent_task.original_prompt or agent_task.transcribed_prompt or "",
                timestamp=agent_task.timestamp,
                status=agent_task.status or "processing",
                current_step=agent_task.current_step
            ))

        logger.info(f"Retrieved {len(agent_items)} active agents")

        return ActiveAgentsResponse(
            agents=agent_items,
            count=len(agent_items)
        )

    except Exception as e:
        logger.error(f"Error getting active agent tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving active agent tasks: {str(e)}")


async def _delegated_provider_report_cards(
    knowledge_service: SQLiteKnowledgeService,
    parent_agent_task_id: str,
) -> list[dict[str, object]]:
    runs = getattr(knowledge_service, "delegated_agent_repository", None)
    evidence = getattr(knowledge_service, "delegated_agent_evidence_repository", None)
    if runs is None or evidence is None:
        return []
    try:
        return await DelegatedAgentEvidenceService(
            delegated_agent_repository=runs,
            evidence_repository=evidence,
        ).build_parent_report_cards(parent_agent_task_id=parent_agent_task_id)
    except Exception as exc:  # noqa: BLE001 - optional presentation data must not hide a task detail.
        logger.debug(
            "Delegated provider report-card detail projection failed for %s: %s",
            parent_agent_task_id,
            exc.__class__.__name__,
        )
        return []


@router.get("/follow-ups/pending", response_model=PendingFollowUpsResponse, summary="Get Pending Follow-Up Checks")
async def get_pending_follow_ups(
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service)
) -> PendingFollowUpsResponse:
    """List the Agent Task chains that are waiting on a scheduled follow-up check and when each is due."""
    try:
        due_by_root = await knowledge_service.agent_task_follow_up_repository.all_pending_due_by_root()
        return PendingFollowUpsResponse(
            follow_ups=[
                PendingFollowUpItem(root_task_id=root_task_id, due_at=due_at)
                for root_task_id, due_at in sorted(due_by_root.items(), key=lambda item: item[1])
            ]
        )
    except Exception as e:
        logger.error(f"Error getting pending follow-ups: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving pending follow-ups: {str(e)}")


@router.delete(
    "/follow-ups/{root_task_id}",
    response_model=CancelPendingFollowUpsResponse,
    summary="Stop Scheduled Follow-Up Checks",
)
async def cancel_pending_follow_ups(
    root_task_id: str,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service)
) -> CancelPendingFollowUpsResponse:
    """Cancel every still-scheduled follow-up check for one chain; a check already being dispatched is left to finish."""
    try:
        canceled = await knowledge_service.agent_task_follow_up_repository.cancel_pending_for_root(
            root_task_id, reason="Stopped by the user"
        )
        if canceled:
            await notify_follow_ups_changed([root_task_id])
        return CancelPendingFollowUpsResponse(success=True, canceled_count=int(canceled or 0))
    except Exception as e:
        logger.error(f"Error canceling pending follow-ups for {root_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error stopping scheduled follow-ups: {str(e)}")


@router.get(
    "/{root_task_id}/search-matches",
    response_model=AgentTaskSearchMatchesResponse,
    summary="Find the turns of an AgentTask chain that match a search",
)
async def get_agent_task_search_matches(
    root_task_id: str,
    query: str = Query("", description="The text typed in the task search box"),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> AgentTaskSearchMatchesResponse:
    """Say which turns of a chain contain the search words, so the result window can open the right turn."""
    try:
        matches = await knowledge_service.agent_task_service.find_search_matching_turns(root_task_id, query)
    except Exception as e:
        logger.error(f"Error finding search matches for agent_task {root_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error finding search matches: {str(e)}")
    if matches is None:
        raise HTTPException(status_code=404, detail="AgentTask not found")
    return AgentTaskSearchMatchesResponse(tokens=matches.tokens, matched_turn_ids=matches.matched_turn_ids)


@router.get("/{agent_task_id}", response_model=AgentTaskDetailResponse, summary="Get AgentTask Details")
async def get_agent_task_details(
    agent_task_id: str,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service)
) -> AgentTaskDetailResponse:
    """
    Get full details for a specific agent_task by ID.
    Used when selecting an agent task from the history sidebar to view its full content.
    Includes any follow-up agent tasks in the chain.
    """
    try:
        # Get the agent_task
        agent_task_record = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)

        if not agent_task_record:
            raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")

        # Extract main agent-task data
        result_message, files, ref_paths, error_message, timeline = extract_result_data(agent_task_record)
        thinking_history = normalize_thinking_history(
            agent_task_record.result_data.get("thinking_history")
            if isinstance(agent_task_record.result_data, dict)
            else None
        )
        presentation_summary = build_agent_task_presentation_summary(
            agent_task_id=agent_task_record.id,
            lifecycle=agent_task_record.status,
            result_data=agent_task_record.result_data if isinstance(agent_task_record.result_data, dict) else None,
            execution_timeline=timeline if isinstance(timeline, list) else None,
            files=files,
            delegated_provider_report_cards=await _delegated_provider_report_cards(
                knowledge_service,
                agent_task_record.id,
            ),
        )

        # Get follow-up chain for this root task.
        follow_ups = []
        chain = await knowledge_service.agent_task_service.get_agent_task_chain(agent_task_id)
        for chain_cmd in chain:
            if chain_cmd.id == agent_task_id:
                continue

            chain_result_msg, chain_files, chain_ref_paths, chain_error, chain_timeline = extract_result_data(chain_cmd)
            chain_thinking_history = normalize_thinking_history(
                chain_cmd.result_data.get("thinking_history")
                if isinstance(chain_cmd.result_data, dict)
                else None
            )
            chain_presentation_summary = build_agent_task_presentation_summary(
                agent_task_id=chain_cmd.id,
                lifecycle=chain_cmd.status,
                result_data=chain_cmd.result_data if isinstance(chain_cmd.result_data, dict) else None,
                execution_timeline=chain_timeline if isinstance(chain_timeline, list) else None,
                files=chain_files,
                delegated_provider_report_cards=await _delegated_provider_report_cards(
                    knowledge_service,
                    chain_cmd.id,
                ),
            )
            follow_ups.append(AgentTaskChainItem(
                id=chain_cmd.id,
                original_prompt=chain_cmd.original_prompt,
                display_prompt_markdown=chain_cmd.display_prompt_markdown,
                timestamp=chain_cmd.timestamp,
                status=chain_cmd.status,
                outcome=extract_result_outcome(chain_cmd.result_data),
                suggested_follow_ups=extract_suggested_follow_ups(chain_cmd.result_data),
                result_severity=derive_result_severity(chain_cmd.status, chain_cmd.result_data),
                result_message=chain_result_msg,
                files=chain_files,
                agent_task_presentation_summary=AgentTaskPresentationSummaryResponse(**chain_presentation_summary),
                reference_paths=chain_ref_paths,
                connection_references=extract_connection_references(chain_cmd),
                root_task_id=chain_cmd.root_task_id,
                previous_task_id=chain_cmd.previous_task_id,
                chain_sequence_number=chain_cmd.chain_sequence_number or 0,
                error_message=chain_error,
                execution_timeline=chain_timeline,
                thinking_history=chain_thinking_history,
                reasoning_fallback_model_used=(
                    chain_cmd.result_data.get("reasoning_fallback_model_used")
                    if isinstance(chain_cmd.result_data, dict) else None
                ),
                model_used=extract_model_used(chain_cmd.result_data),
                model_id=extract_original_model_id(chain_cmd),
                origin_type=chain_cmd.origin_type,
                origin_id=chain_cmd.origin_id,
            ))

        # Sort follow-ups by chain sequence number
        follow_ups.sort(key=lambda x: x.chain_sequence_number)

        logger.info(f"Retrieved agent_task details for {agent_task_id} with {len(follow_ups)} follow-ups")

        return AgentTaskDetailResponse(
            id=agent_task_record.id,
            original_prompt=agent_task_record.original_prompt,
            transcribed_prompt=agent_task_record.transcribed_prompt,
            display_prompt_markdown=agent_task_record.display_prompt_markdown,
            title=agent_task_record.title,
            origin_type=agent_task_record.origin_type,
            origin_id=agent_task_record.origin_id,
            timestamp=agent_task_record.timestamp,
            status=agent_task_record.status,
            outcome=extract_result_outcome(agent_task_record.result_data),
            suggested_follow_ups=extract_suggested_follow_ups(agent_task_record.result_data),
            result_severity=derive_result_severity(agent_task_record.status, agent_task_record.result_data),
            result_message=result_message,
            app_name=agent_task_record.app_name,
            window_title=agent_task_record.window_title,
            files=files,
            agent_task_presentation_summary=AgentTaskPresentationSummaryResponse(**presentation_summary),
            reference_paths=ref_paths,
            connection_references=extract_connection_references(agent_task_record),
            root_task_id=agent_task_record.root_task_id,
            previous_task_id=agent_task_record.previous_task_id,
            follow_ups=follow_ups,
            error_message=error_message,
            execution_timeline=timeline,
            thinking_history=thinking_history,
            checkpoint_data=extract_checkpoint_data(agent_task_record),
            reasoning_fallback_model_used=(
                agent_task_record.result_data.get("reasoning_fallback_model_used")
                if isinstance(agent_task_record.result_data, dict) else None
            ),
            model_used=extract_model_used(agent_task_record.result_data),
            model_id=extract_original_model_id(agent_task_record),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent_task details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving agent_task: {str(e)}")
