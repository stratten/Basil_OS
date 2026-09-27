"""Frontend state query helpers for wake-word agent task orchestration."""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def resolve_main_event_loop(service) -> Optional[asyncio.AbstractEventLoop]:
    """Return the FastAPI startup loop captured by WakeWordService, if any."""
    try:
        if service.main_service is not None:
            loop = getattr(service.main_service, "main_event_loop", None)
            if loop is not None:
                return loop
    except Exception as exc:
        logger.debug(f"Could not resolve main event loop: {exc}")
    return None


def schedule_frontend_query(service, query_message: Dict[str, Any], query_name: str) -> bool:
    """Schedule a frontend query from non-event-loop threads."""
    if not (service.main_service and hasattr(service.main_service, "broadcast")):
        logger.warning(f"No WebSocket service available for {query_name} query")
        return False

    main_loop = resolve_main_event_loop(service)
    if main_loop is None:
        logger.warning(f"No FastAPI main event loop available for {query_name} query")
        return False
    if main_loop.is_closed():
        logger.warning(f"FastAPI main event loop is closed for {query_name} query")
        return False

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is main_loop:
        logger.warning(
            f"{query_name} query requested from the FastAPI event loop; "
            "cannot synchronously wait for a frontend response"
        )
        return False

    try:
        asyncio.run_coroutine_threadsafe(
            service.main_service.broadcast(query_message),
            main_loop,
        )
        logger.info(
            f"Scheduled {query_name} query on FastAPI main loop "
            f"(request_id={query_message.get('request_id')})"
        )
        return True
    except Exception as exc:
        logger.warning(f"Error scheduling {query_name} query on main loop: {exc}")
        return False


def query_frontend_operation_state_sync(service, timeout_seconds: float = 0.2) -> bool:
    """
    Synchronously query frontend operation state with timeout.
    Returns True if agent_task can proceed, False if blocked.
    """
    request_id = str(uuid.uuid4())

    # Prepare to track the response
    with service._operation_state_lock:
        service._operation_state_responses[request_id] = None

    try:
        # Send query to frontend via WebSocket
        query_message = {
            "type": "operation_state_query",
            "request_id": request_id,
            "timestamp": time.time()
        }

        if not schedule_frontend_query(service, query_message, "operation_state"):
            with service._operation_state_lock:
                service._operation_state_responses.pop(request_id, None)
            logger.warning(
                "Frontend operation state query could not be scheduled - blocking agent_task"
            )
            return False

        # Wait for response with timeout
        end_time = time.time() + timeout_seconds
        while time.time() < end_time:
            with service._operation_state_lock:
                response = service._operation_state_responses.get(request_id)
                if response is not None:
                    # Clean up
                    del service._operation_state_responses[request_id]
                    can_accept = response.get("can_accept_agent_task", False)
                    logger.info(
                        f"Frontend operation state response for {request_id}: "
                        f"can_accept_agent_task={can_accept}"
                    )
                    return can_accept

            time.sleep(0.01)  # 10ms polling interval

        # Timeout - clean up and block agent_task
        with service._operation_state_lock:
            service._operation_state_responses.pop(request_id, None)

        logger.warning(
            f"Frontend operation state query timeout after {timeout_seconds:.2f}s - blocking agent_task"
        )
        return False

    except Exception as e:
        # Clean up on error
        with service._operation_state_lock:
            service._operation_state_responses.pop(request_id, None)
        logger.warning(f"Error querying frontend operation state: {e} - blocking agent_task")
        return False


def handle_operation_state_response(service, response_data: Dict[str, Any]) -> None:
    """Handle operation state response from frontend."""
    request_id = response_data.get("request_id")
    if request_id:
        with service._operation_state_lock:
            if request_id in service._operation_state_responses:
                service._operation_state_responses[request_id] = response_data
                logger.debug(f"Received operation state response: {response_data}")


def query_widget_state_sync(service, timeout_seconds: float = 0.2) -> Dict[str, Any]:
    """
    Synchronously query widget state with timeout.
    Returns dict with: can_accept_agent_task, is_processing, has_completed_result, root_task_id
    """
    request_id = str(uuid.uuid4())

    # Prepare to track the response
    with service._widget_state_lock:
        service._widget_state_responses[request_id] = None

    try:
        # Send query to frontend via WebSocket
        query_message = {
            "type": "widget_state_query",
            "request_id": request_id,
            "timestamp": time.time()
        }

        if not schedule_frontend_query(service, query_message, "widget_state"):
            with service._widget_state_lock:
                service._widget_state_responses.pop(request_id, None)
            logger.warning("Widget state query could not be scheduled - treating as new agent task")
            return {'can_accept_agent_task': True, 'is_processing': False, 'has_completed_result': False, 'root_task_id': None}

        # Wait for response with timeout
        end_time = time.time() + timeout_seconds
        while time.time() < end_time:
            with service._widget_state_lock:
                response = service._widget_state_responses.get(request_id)
                if response is not None:
                    # Clean up
                    del service._widget_state_responses[request_id]
                    logger.info(
                        f"Frontend widget state response for {request_id}: "
                        f"can_accept_agent_task={response.get('can_accept_agent_task', True)}, "
                        f"is_processing={response.get('is_processing', False)}, "
                        f"has_completed_result={response.get('has_completed_result', False)}"
                    )
                    return {
                        'can_accept_agent_task': response.get("can_accept_agent_task", True),
                        'is_processing': response.get("is_processing", False),
                        'has_completed_result': response.get("has_completed_result", False),
                        'root_task_id': response.get("root_task_id", None)
                    }

            time.sleep(0.01)  # 10ms polling interval

        # Timeout - clean up and treat as new agent task
        with service._widget_state_lock:
            service._widget_state_responses.pop(request_id, None)

        logger.debug("Widget state query timeout - treating as new agent task")
        return {'can_accept_agent_task': True, 'is_processing': False, 'has_completed_result': False, 'root_task_id': None}

    except Exception as e:
        # Clean up on error
        with service._widget_state_lock:
            service._widget_state_responses.pop(request_id, None)
        logger.warning(f"Error querying widget state: {e} - treating as new agent task")
        return {'can_accept_agent_task': True, 'is_processing': False, 'has_completed_result': False, 'root_task_id': None}


def handle_widget_state_response(service, response_data: Dict[str, Any]) -> None:
    """Handle widget state response from frontend."""
    request_id = response_data.get("request_id")
    if request_id:
        with service._widget_state_lock:
            if request_id in service._widget_state_responses:
                service._widget_state_responses[request_id] = response_data
                logger.debug(f"Received widget state response: {response_data}")
