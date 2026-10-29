from api.services.agent_processing.lifecycle.execution_graph.agent_graph_nodes import (
    _get_run_coordinator,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import (
    PlanningState,
)
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import (
    WorkflowCoordinator,
)


def test_get_run_coordinator_rebuilds_serialized_checkpoint_placeholder():
    websocket_manager = object()
    state = PlanningState(
        user_agent_task="Continue the paused task",
        context={
            "websocket_manager": websocket_manager,
            "_workflow_coordinator": "<WorkflowCoordinator serialized placeholder>",
        },
    )

    coordinator = _get_run_coordinator(state)

    assert isinstance(coordinator, WorkflowCoordinator)
    assert state.context["_workflow_coordinator"] is coordinator
    assert coordinator._websocket_manager is websocket_manager


def test_get_run_coordinator_reuses_live_coordinator():
    live_coordinator = WorkflowCoordinator()
    state = PlanningState(
        user_agent_task="Continue the paused task",
        context={"_workflow_coordinator": live_coordinator},
    )

    coordinator = _get_run_coordinator(state)

    assert coordinator is live_coordinator
    assert state.context["_workflow_coordinator"] is live_coordinator
