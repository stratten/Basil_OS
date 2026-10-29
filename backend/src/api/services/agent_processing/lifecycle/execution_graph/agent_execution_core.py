"""
Agent Execution Core for LangGraph Agent Execution.

Context preparation, live progress callbacks, and the first-response fallback signal for the inner agent loop.
"""

from __future__ import annotations

import logging
from typing import Any, List, TYPE_CHECKING

from ..planning.agent_context_assembler import AgentContextAssembler

if TYPE_CHECKING:
    from .agent_progress_system import PlanningState
    from .activity_progress_callback import ActivityProgressCallbackHandler

logger = logging.getLogger(__name__)


class ModelUnavailableBeforeFirstResponse(Exception):
    """Raised when the preferred model could not be reached at all (network/auth failure) and zero model calls succeeded for this task, so the caller may substitute a local fallback model and restart.

    Never raised once a model call has succeeded; in that case the original exception propagates unchanged and the agent stops, per the settled no-mid-execution-swap decision.
    """

    def __init__(self, original_error: Exception):
        super().__init__(str(original_error))
        self.original_error = original_error


def format_chain_context(state: "PlanningState") -> str:
    """Format all available agent context into the user input string."""
    assembled = AgentContextAssembler().assemble(
        current_request=state.user_agent_task,
        context=state.context or {},
    )
    if assembled.sections:
        logger.info(
            "🔗 CONTEXT FORMATTED: sections=%s omitted=%s budget_chars=%s",
            [section.name for section in assembled.sections],
            assembled.omitted_sections,
            assembled.budget_chars,
        )
    else:
        logger.info("ℹ️ No additional agent context - standalone agent task")
    return assembled.user_input


def setup_live_callbacks(
    state: "PlanningState",
    coordinator: Any
) -> List["ActivityProgressCallbackHandler"]:
    """Set up live progress callbacks for streaming step updates during execution."""
    from .activity_progress_callback import ActivityProgressCallbackHandler
    from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
    
    live_callbacks = []
    
    try:
        ws_manager = coordinator._websocket_manager or state.context.get("websocket_manager")
        todo_id = state.context.get("agent_task_id")
        notifier = WorkflowStatusNotifier(
            websocket_manager=ws_manager,
            agent_task_id=todo_id,
            root_task_id=state.context.get("root_task_id"),
            previous_task_id=state.context.get("previous_task_id"),
        )
        
        if notifier and todo_id:
            from ..runtime.turn_timing import get_or_create_turn_timing
            turn_timing = get_or_create_turn_timing(state.context)
            live_callbacks = [ActivityProgressCallbackHandler(
                notifier=notifier, 
                todo_id=todo_id, 
                available_tools=state.available_tools.tools if state.available_tools else None,
                turn_timing=turn_timing,
            )]
            logger.info(f"✅ Attaching live progress callbacks for agent task {todo_id}")
        else:
            logger.warning(f"⚠️ No activity callbacks: notifier={notifier is not None}, todo_id={todo_id}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to create live progress callbacks: {e}")
    
    if live_callbacks:
        logger.info(f"🔧 DEBUG: Live progress callbacks attached: count={len(live_callbacks)}")
    else:
        logger.info("⚠️ DEBUG: No live progress callbacks attached")
    
    return live_callbacks
