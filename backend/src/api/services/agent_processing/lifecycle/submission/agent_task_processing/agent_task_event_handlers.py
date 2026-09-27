"""
AgentTask Event Handlers

This module implements the actual business logic for each state transition
in the agent_task state machine.
"""

import asyncio
import logging
import time
from typing import Dict, Any
from datetime import datetime

from api.core.knowledge.sqlite.sqlite_knowledge_service import AgentTaskEvent
from .agent_task_state_manager import StateTransition, AgentTaskStateMachine

logger = logging.getLogger(__name__)

class AgentTaskEventHandlers:
    """
    Event handlers for agent_task state transitions.
    
    Each handler implements the business logic for a specific state transition.
    """
    
    def __init__(self, db_service, model_service=None, operation_router=None, websocket_manager=None):
        self.db_service = db_service
        self.model_service = model_service
        self.operation_router = operation_router
        self.websocket_manager = websocket_manager
        self.logger = logging.getLogger(__name__)
        
        # Background task queue for async operations
        self._background_tasks = []
        
    def register_handlers(self, state_machine: AgentTaskStateMachine) -> None:
        """Register all event handlers with the state machine."""
        handlers = {
            "handle_capture_started": self.handle_capture_started,
            "handle_new_agent_task": self.handle_new_agent_task,
            "handle_routing_success": self.handle_routing_success,
            "handle_routing_needs_clarification": self.handle_routing_needs_clarification,
            "handle_clarification_received": self.handle_clarification_received,
            "handle_clarification_routing_success": self.handle_clarification_routing_success,
            "handle_clarification_routing_failed": self.handle_clarification_routing_failed,
            "handle_processing_started": self.handle_processing_started,
            "handle_processing_completed": self.handle_processing_completed,
            "handle_routing_failed": self.handle_routing_failed,
            "handle_processing_failed": self.handle_processing_failed,
            "handle_provider_delegation_waiting": self.handle_provider_delegation_waiting,
            "handle_provider_delegation_resumed": self.handle_provider_delegation_resumed,
            "handle_processing_cancelled": self.handle_processing_cancelled,
        }
        
        for handler_name, handler_func in handlers.items():
            state_machine.register_state_handler(handler_name, handler_func)
        
        self.logger.info(f"Registered {len(handlers)} event handlers")
    
    # === AgentTask Creation Handlers ===
    
    def handle_capture_started(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle new agent_task creation while screen context capture is in progress.

        Triggers: AgentTask created with 'capturing' status
        Action: Leave routing paused until the orchestrator updates status to 'routing'
        """
        self.logger.info(f"New agent_task {event.agent_task_id} - waiting for screen context capture")
        return True

    def handle_new_agent_task(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle new agent_task creation.
        
        Triggers: AgentTask created with 'routing' status
        Action: Start routing process in background
        """
        self.logger.info(f"New agent_task {event.agent_task_id} - starting routing process")
        
        # Schedule routing in background
        task = asyncio.create_task(self._perform_routing(event.agent_task_id))
        self._background_tasks.append(task)
        
        # No need to send any initial event - orchestrator handles progress events
        
        return True
    
    # === Routing Result Handlers ===
    
    def handle_routing_success(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle successful routing to an operation.
        
        Triggers: Status changed from 'routing' to 'routed'
        Action: Start operation processing in background
        """
        self.logger.info(f"AgentTask {event.agent_task_id} successfully routed - starting processing")
        
        # Schedule processing in background
        task = asyncio.create_task(self._perform_processing(event.agent_task_id))
        self._background_tasks.append(task)
        
        return True
    
    def handle_routing_needs_clarification(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle routing that needs clarification.
        
        Triggers: Status changed from 'routing' to 'needs_clarification'
        Action: Send clarification request to frontend
        """
        self.logger.info(f"AgentTask {event.agent_task_id} needs clarification")
        
        # Extract clarification request from operation parameters
        agent_task_data = event.agent_task_data
        operation_params = agent_task_data.get('operation_parameters', {})
        clarification_message = operation_params.get('clarification_message', 
                                                   "Could you please clarify what you'd like me to do?")
        
        # Send clarification request using compatible agent_task_result format
        self._send_frontend_notification(event.agent_task_id, {
            "event_type": "agent_task_result",
            "success": False,
            "requires_clarification": True,
            "clarification_question": clarification_message,
            "result": clarification_message,
            "error": None,
            "original_prompt": agent_task_data.get('transcribed_prompt'),
            "agent_task_id": event.agent_task_id
        })
        
        return True
    
    def handle_routing_failed(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle unrecoverable routing failure.
        
        Triggers: Status changed from 'routing' to 'failed'
        Action: Send error notification to frontend
        """
        self.logger.error(f"AgentTask {event.agent_task_id} routing failed permanently")
        
        # Send error using compatible agent_task_result format
        self._send_frontend_notification(event.agent_task_id, {
            "event_type": "agent_task_result",
            "success": False,
            "result": "",
            "error": "Unable to understand the agent task. Please try again.",
            "agent_task_id": event.agent_task_id
        })

        # Release the lifecycle gate so wake detection can resume.
        self._release_lifecycle_for_task(event.agent_task_id, "routing_failed")
        return True

    def _release_lifecycle_for_task(self, agent_task_id: str, reason: str) -> None:
        """Release the wake-word lifecycle gate held against this task.

        The gate (in VoiceListenerAgentTaskOrchestrationService) is the
        backend-owned signal that wake detection may resume. Holding it past
        a terminal transition would leave the listener wedged; releasing too
        early (e.g., on processing-started) is what previously allowed
        overlapping wake captures while a task was still running. Releasing
        here, on a true terminal status_changed event, makes the wake
        listener reactivation a function of actual task lifecycle.
        """
        if not agent_task_id:
            return
        try:
            from api.main import app  # local import to avoid circular import at module load
            wake_word_service = getattr(app.state, "wake_word_service", None)
            orchestration = (
                getattr(wake_word_service, "agent_task_orchestration_service", None)
                if wake_word_service is not None
                else None
            )
            if orchestration is not None and hasattr(orchestration, "release_lifecycle"):
                orchestration.release_lifecycle(f"task:{agent_task_id}", reason)
        except Exception as release_err:
            self.logger.debug(
                f"release_lifecycle skipped for {agent_task_id} ({reason}): {release_err}"
            )
    
    # === Clarification Handlers ===
    
    def handle_clarification_received(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle clarification received from user.
        
        Triggers: Clarification added to agent task
        Action: Start re-routing process
        """
        clarification_data = event.agent_task_data.get('clarifications', [])[-1] if event.agent_task_data.get('clarifications') else {}
        clarification_text = clarification_data.get('text', '')
        
        self.logger.info(f"AgentTask {event.agent_task_id} received clarification: '{clarification_text[:50]}{'...' if len(clarification_text) > 50 else ''}'")
        
        # Schedule re-routing with clarification
        task = asyncio.create_task(self._perform_clarification_routing(event.agent_task_id))
        self._background_tasks.append(task)
        
        # DO NOT send extra "Processing clarification" step
        # Clarifications should restart normal flow: Analyzing request → Determining operation → Processing request
        
        return True
    
    def handle_clarification_routing_success(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle successful re-routing after clarification.
        
        Triggers: Status changed from 'clarification_added' to 'routed'
        Action: Start operation processing
        """
        self.logger.info(f"AgentTask {event.agent_task_id} successfully re-routed after clarification")
        
        # Schedule processing in background
        task = asyncio.create_task(self._perform_processing(event.agent_task_id))
        self._background_tasks.append(task)
        
        return True
    
    def handle_clarification_routing_failed(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle failed re-routing after clarification.
        
        Triggers: Status changed from 'clarification_added' to 'needs_clarification'
        Action: Request additional clarification
        """
        self.logger.warning(f"AgentTask {event.agent_task_id} re-routing failed, needs more clarification")
        
        # Send request for additional clarification using compatible format
        previous_attempts = [c.get('text', '') for c in event.agent_task_data.get('clarifications', [])]
        retry_count = len(previous_attempts)
        
        self._send_frontend_notification(event.agent_task_id, {
            "event_type": "agent_task_result",
            "success": False,
            "requires_clarification": True,
            "clarification_question": "I need a bit more clarification. Could you be more specific about what you'd like me to do?",
            "result": "I need a bit more clarification. Could you be more specific about what you'd like me to do?",
            "error": None,
            "retry_count": retry_count,
            "agent_task_id": event.agent_task_id
        })
        
        return True
    
    # === Processing Handlers ===
    
    def handle_processing_started(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle processing start.
        
        Triggers: Status changed from 'routing' to 'processing'
        Action: Schedule actual processing in background and send notification to frontend
        """
        self.logger.info(f"AgentTask {event.agent_task_id} processing started")

        # Notify the wake-word orchestrator that this task has reached 'processing'.
        # That orchestrator's strict-resume gate blocks acceptance of a new wake word
        # until this signal arrives (or its safety timeout fires). Best-effort:
        # missing orchestrator (hotkey-only path, tests, early startup) is fine.
        try:
            from api.main import app  # local import to avoid circular import at module load
            wake_word_service = getattr(app.state, "wake_word_service", None)
            orchestration_service = getattr(wake_word_service, "agent_task_orchestration_service", None) if wake_word_service else None
            if orchestration_service is not None and hasattr(orchestration_service, "signal_processing_started"):
                orchestration_service.signal_processing_started(event.agent_task_id, time.monotonic())
        except Exception as signal_err:
            self.logger.debug(
                f"signal_processing_started skipped for {event.agent_task_id}: {signal_err}"
            )

        # Schedule processing in background
        task = asyncio.create_task(self._perform_processing(event.agent_task_id))
        self._background_tasks.append(task)
        
        # Send compatible progress update to frontend (not a new event type)
        self._send_frontend_notification(event.agent_task_id, {
            "event_type": "agent_task_progress",
            "step": "Processing request",
            "status": "started",
            "details": None
        })
        
        return True

    def handle_provider_delegation_waiting(
        self, event: AgentTaskEvent, transition: StateTransition
    ) -> bool:
        """Keep the primary task durable and visible while its child provider runs."""
        result_data = event.agent_task_data.get("result_data")
        delegation = (
            result_data.get("provider_delegation")
            if isinstance(result_data, dict)
            else None
        )
        root_task_id = event.agent_task_data.get("root_task_id")
        if (
            self.operation_router is not None
            and isinstance(delegation, dict)
            and isinstance(delegation.get("delegation_id"), str)
            and isinstance(root_task_id, str)
        ):
            task = asyncio.create_task(
                self.operation_router.publish_delegated_provider_state(
                    parent_agent_task_id=event.agent_task_id,
                    root_task_id=root_task_id,
                    delegation_id=delegation["delegation_id"],
                    state="awaiting_child",
                    message="Waiting for the delegated provider task to finish.",
                )
            )
            self._background_tasks.append(task)
            return True
        self._send_frontend_notification(
            event.agent_task_id,
            {
                "event_type": "agent_task_progress",
                "agent_task_id": event.agent_task_id,
                "step": "Delegated provider task",
                "status": "waiting",
                "details": "Waiting for the delegated provider task to finish.",
            },
        )
        return True

    def handle_provider_delegation_resumed(
        self, event: AgentTaskEvent, transition: StateTransition
    ) -> bool:
        """The result bridge owns continuation; never schedule initial processing again."""
        return True

    def handle_processing_cancelled(
        self, event: AgentTaskEvent, transition: StateTransition
    ) -> bool:
        """Cancellation is already durable; only release the local lifecycle gate."""
        self._release_lifecycle_for_task(event.agent_task_id, "cancelled")
        return True
    
    def handle_processing_completed(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle successful processing completion.
        
        Triggers: Status changed from 'processing' to 'completed'
        Action: Send results to frontend (unless widget content was already delivered)
        """
        self.logger.info(f"AgentTask {event.agent_task_id} processing completed")
        
        # Extract results
        result_data = event.agent_task_data.get('result_data', {})
        operation_params = event.agent_task_data.get('operation_parameters', {})
        operation = operation_params.get('operation', 'unknown')
        
        # Check if widget content was already delivered (for streaming operations)
        widget_content_delivered = False
        if result_data.get('data') and isinstance(result_data.get('data'), dict):
            widget_content_delivered = result_data.get('data', {}).get('widget_content_delivered', False)
        
        # Skip sending final result if visible content was already delivered to widget
        if widget_content_delivered:
            self.logger.info(f"🔥 EVENT_HANDLER: Skipping final result message for {operation} - widget content already delivered")
            self._release_lifecycle_for_task(event.agent_task_id, "completed_widget_delivered")
            return True
        elif operation == "capture_screen":
            # capture_screen is almost always an intermediate step, not a final result
            self.logger.info(f"🔥 EVENT_HANDLER: Skipping final result message for intermediate operation: {operation}")
            self._release_lifecycle_for_task(event.agent_task_id, "completed_intermediate_capture")
            return True
        
        # Respect agent-finalized results: if router already broadcasted a finalized envelope,
        # do NOT overwrite with a legacy fallback message.
        data_dict = result_data.get('data', {}) if isinstance(result_data.get('data'), dict) else {}
        already_finalized = bool(
            data_dict.get('finalizer_broadcasted') or
            data_dict.get('final_envelope') or
            data_dict.get('finalizer_result') or
            result_data.get('final_envelope') or
            result_data.get('finalizer_result')
        )

        if already_finalized:
            self.logger.info("🔥 EVENT_HANDLER: Skipping legacy final result send — finalizer-driven result already broadcast")
            self._release_lifecycle_for_task(event.agent_task_id, "completed_finalizer_already")
            return True

        # Send results using compatible agent_task_result event (fallback path)
        success = result_data.get('success', True)
        result_message = result_data.get('message', 'Operation completed successfully')
        error_message = result_data.get('error')

        payload = None
        # If a structured payload is available in the stored data, forward it
        if 'final_envelope' in data_dict and isinstance(data_dict.get('final_envelope'), dict):
            payload = data_dict['final_envelope'].get('result_payload')
        elif 'result_payload' in data_dict:
            payload = data_dict.get('result_payload')

        self.logger.info(f"🔥 EVENT_HANDLER: Sending fallback final result for operation: {operation}")
        message = {
            "event_type": "agent_task_result",
            "success": success,
            "result": result_message if success else "",
            "error": error_message if not success else None,
            "operation": operation,
            "agent_task_id": event.agent_task_id
        }
        
        if event.agent_task_data.get('root_task_id'):
            message["root_task_id"] = event.agent_task_data['root_task_id']
        if event.agent_task_data.get('previous_task_id'):
            message["previous_task_id"] = event.agent_task_data['previous_task_id']
        
        if payload is not None:
            message["result_payload"] = payload
        self._send_frontend_notification(event.agent_task_id, message)

        self._release_lifecycle_for_task(event.agent_task_id, "completed")
        return True
    
    def handle_processing_failed(self, event: AgentTaskEvent, transition: StateTransition) -> bool:
        """
        Handle processing failure.
        
        Triggers: Status changed from 'processing' to 'failed'
        Action: Send error notification to frontend
        """
        self.logger.error(f"AgentTask {event.agent_task_id} processing failed")
        
        # Extract error details. Initial AgentTask execution stores router
        # failures under failure_info so the state-change notification should
        # not overwrite them with the generic fallback.
        result_data = event.agent_task_data.get('result_data', {})
        data_dict = result_data.get('data', {}) if isinstance(result_data.get('data'), dict) else {}
        final_envelope = None
        if isinstance(data_dict.get('final_envelope'), dict):
            final_envelope = data_dict.get('final_envelope')
        elif isinstance(result_data.get('final_envelope'), dict):
            final_envelope = result_data.get('final_envelope')

        if isinstance(final_envelope, dict):
            payload = final_envelope.get('result_payload') if isinstance(final_envelope.get('result_payload'), dict) else None
            outcome_reason = (
                final_envelope.get('outcome_reason')
                or (payload.get('outcome_reason') if isinstance(payload, dict) else None)
                or final_envelope.get('summary_text')
                or 'Processing failed. Please try again.'
            )
            message = {
                "event_type": "agent_task_result",
                "success": False,
                "result": final_envelope.get('summary_text', ''),
                "error": outcome_reason,
                "agent_task_id": event.agent_task_id,
                "root_task_id": event.agent_task_data.get("root_task_id"),
                "previous_task_id": event.agent_task_data.get("previous_task_id"),
            }
            if payload is not None:
                message["result_payload"] = payload
            self._send_frontend_notification(event.agent_task_id, message)
            self._release_lifecycle_for_task(event.agent_task_id, "processing_failed_envelope")
            return True

        failure_info = result_data.get('failure_info') if isinstance(result_data, dict) else None
        error_message = (
            result_data.get('error')
            or (failure_info.get('error') if isinstance(failure_info, dict) else None)
            or 'Processing failed. Please try again.'
        )
        
        # Send error using compatible agent_task_result event
        self._send_frontend_notification(event.agent_task_id, {
            "event_type": "agent_task_result",
            "success": False,
            "result": "",
            "error": error_message,
            "agent_task_id": event.agent_task_id,
            "root_task_id": event.agent_task_data.get("root_task_id"),
            "previous_task_id": event.agent_task_data.get("previous_task_id"),
        })

        self._release_lifecycle_for_task(event.agent_task_id, "processing_failed")
        return True
    
    # === Background Processing Methods ===
    
    async def _perform_routing(self, agent_task_id: str) -> None:
        """Perform agent_task routing in background."""
        try:
            # Get agent task from database
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                self.logger.error(f"AgentTask {agent_task_id} not found for routing")
                return
            
            # TODO: Integrate with actual routing logic
            # For now, simulate routing process
            self.logger.info(f"Routing agent_task: {agent_task_record.transcribed_prompt}")
            
            # Simulate routing decision
            if len(agent_task_record.transcribed_prompt.split()) < 2:
                # Too vague, needs clarification
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="needs_clarification",
                    operation_parameters={
                        "clarification_message": "Could you please be more specific about what you'd like me to do?"
                    }
                )
            else:
                # Successfully routed
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="routed",
                    operation_parameters={
                        "operation": "generate_suggestions",
                        "confidence": 0.8,
                        "routing_time_ms": 150
                    }
                )
        except Exception as e:
            self.logger.error(f"Error routing agent_task {agent_task_id}: {e}")
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="failed",
                result_data={"error": str(e)}
            )
    
    async def _perform_clarification_routing(self, agent_task_id: str) -> None:
        """Perform re-routing after clarification."""
        try:
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                self.logger.error(f"AgentTask {agent_task_id} not found for clarification routing")
                return
            
            # Get latest clarification
            clarifications = agent_task_record.clarifications
            if not clarifications:
                self.logger.error(f"No clarifications found for agent_task {agent_task_id}")
                return
            
            latest_clarification = clarifications[-1]
            clarification_text = latest_clarification.get('text', '')
            
            self.logger.info(f"Re-routing with clarification: {clarification_text}")
            
            # TODO: Integrate with actual routing logic using clarification
            # For now, simulate successful re-routing
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="routed",
                operation_parameters={
                    "operation": "generate_suggestions",
                    "confidence": 0.9,
                    "used_clarification": True,
                    "clarification_text": clarification_text
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error in clarification routing for {agent_task_id}: {e}")
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="needs_clarification",
                operation_parameters={
                    "clarification_message": "I'm still having trouble understanding. Could you try rephrasing?"
                }
            )
    
    async def _perform_processing(self, agent_task_id: str) -> None:
        """Perform operation processing in background."""
        try:
            # Update status to processing
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="processing"
            )
            
            # Get agent task from database
            agent_task_record = await self.db_service.get_agent_task(agent_task_id)
            if not agent_task_record:
                self.logger.error(f"AgentTask {agent_task_id} not found for processing")
                return
            
            # TODO: Integrate with actual operation processing
            # For now, simulate processing
            operation_params = agent_task_record.operation_parameters
            operation_type = operation_params.get('operation', 'unknown')
            
            self.logger.info(f"Processing {operation_type} for agent_task {agent_task_id}")
            
            # Simulate processing time
            await asyncio.sleep(1)
            
            # Complete with simulated results
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="completed",
                result_data={
                    "suggestion": f"Here's a suggestion based on your request: '{agent_task_record.transcribed_prompt}'",
                    "confidence": 0.95,
                    "operation_type": operation_type
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error processing agent_task {agent_task_id}: {e}")
            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="failed",
                result_data={"error": str(e)}
            )
    
    def _send_frontend_notification(self, agent_task_id: str, notification_data: Dict[str, Any]) -> None:
        """Send notification to frontend via WebSocket."""
        if self.websocket_manager:
            try:
                # Add agent_task_id to notification
                notification_data['agent_task_id'] = agent_task_id
                notification_data['timestamp'] = datetime.now().isoformat()
                
                # Send via WebSocket
                asyncio.create_task(self.websocket_manager.broadcast(notification_data))
                
                self.logger.debug(f"Sent notification for {agent_task_id}: {notification_data['event_type']}")
            except Exception as e:
                self.logger.error(f"Error sending frontend notification: {e}")
        else:
            self.logger.warning("No WebSocket manager available for frontend notifications")
    
    def cleanup_background_tasks(self) -> None:
        """Clean up completed background tasks."""
        self._background_tasks = [task for task in self._background_tasks if not task.done()] 