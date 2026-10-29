"""
Workflow Status Notifier

Reusable helper for sending intelligent, contextual status updates during 
agent processing workflows via WebSocket.

This module provides:
1. WebSocket status update broadcasting
2. Dynamic status message generation based on workflow context
3. Step completion notifications
4. Contextual message creation for different types of operations

Can be used by WorkflowCoordinator, TodoExecutionEngine, and other workflow components.
"""

import logging
import asyncio
from typing import Optional, Any, Dict

from .agent_timeline_contract import build_timeline_event, safe_timeline_id, timeline_timestamp
from .conversation_progress_projection import broadcast_workflow_notification
from .timeline_persistence import persist_timeline_entry
logger = logging.getLogger(__name__)
class WorkflowStatusNotifier:
    """
    Centralized status update service for workflow progress notifications.
    Uses the same notification pattern as agent_task event handlers.
    """
    
    def __init__(self, websocket_manager=None, agent_task_id: Optional[str] = None, root_task_id: Optional[str] = None, previous_task_id: Optional[str] = None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._websocket_manager = websocket_manager
        self._agent_task_id = agent_task_id
        self._root_task_id = root_task_id
        self._previous_task_id = previous_task_id
        self.logger.info(f"🔧 WorkflowStatusNotifier initialized with websocket_manager: {websocket_manager is not None}")
    def set_agent_task_id(self, agent_task_id: str):
        """Set the agent task ID."""
        self._agent_task_id = agent_task_id
    def set_chain_identity(self, root_task_id: Optional[str] = None, previous_task_id: Optional[str] = None):
        """Set explicit task-thread identity for follow-up notifications."""
        self._root_task_id = root_task_id
        self._previous_task_id = previous_task_id
    def _send_frontend_notification(self, notification_data: Dict[str, Any]) -> None:
        """Send notification to frontend via WebSocket using the same pattern as agent_task event handlers."""
        if self._websocket_manager:
            try:
                self._prepare_frontend_notification(notification_data)

                # Send via WebSocket
                asyncio.create_task(
                    broadcast_workflow_notification(
                        self._websocket_manager,
                        notification_data,
                    )
                )

                self.logger.debug(f"Sent workflow notification: {notification_data['event_type']}")
            except Exception as e:
                self.logger.error(f"Error sending workflow notification: {e}")
        else:
            self.logger.warning("No WebSocket manager available for workflow notifications")

    def _prepare_frontend_notification(self, notification_data: Dict[str, Any]) -> None:
        """Attach shared task-thread metadata before any frontend notification send."""
        if self._agent_task_id:
            notification_data['agent_task_id'] = self._agent_task_id
        if self._root_task_id:
            notification_data['root_task_id'] = self._root_task_id
        if self._previous_task_id:
            notification_data['previous_task_id'] = self._previous_task_id
        notification_data['timestamp'] = timeline_timestamp()
        self._attach_timeline_entry(notification_data)

    def _attach_timeline_entry(self, notification_data: Dict[str, Any]) -> None:
        """Attach complete activity data while preserving legacy event fields."""
        event_type = str(notification_data.get("event_type") or "")
        if not (
            event_type.startswith("agent_")
            or event_type.startswith("dynamic_step")
            or event_type.startswith("checkpoint")
        ):
            return

        existing_entry = notification_data.get("timeline_entry")
        title = (
            notification_data.get("title")
            or notification_data.get("description")
            or notification_data.get("step")
            or notification_data.get("message")
            or (existing_entry or {}).get("title")
            or (existing_entry or {}).get("summary")
        )
        phase = notification_data.get("phase") or (existing_entry or {}).get("phase") or (
            "finalization" if notification_data.get("stage") in {"finalizing", "complete"} else "execution"
        )
        timeline_event = build_timeline_event(
            existing_entry,
            phase=phase,
            state=notification_data.get("status"),
            source=notification_data.get("source") or "workflow_status_notifier",
            title=title,
            correlation_id=(
                notification_data.get("correlation_id")
                or notification_data.get("step_id")
                or self._agent_task_id
            ),
        )
        notification_data["timeline_entry"] = timeline_event["timeline_entry"]

    async def _persist_timeline_entry(self, entry: Dict[str, Any], replace_existing: bool = False) -> None:
        """Persist granular live progress as the same durable execution timeline the UI hydrates."""
        # Every entry this notifier persists is workflow-execution progress; stamping the phase once here lets normalize_timeline_entry mirror progress_phase for hydrated/reloaded timelines (raw_detail entries opt out of the mirror).
        entry.setdefault("phase", "execution")
        try:
            await persist_timeline_entry(
                self._agent_task_id,
                entry,
                replace_existing=replace_existing,
            )
        except Exception as persist_err:
            self.logger.debug("Failed to persist workflow timeline entry: %s", persist_err)

    async def _send_frontend_notification_async(self, notification_data: Dict[str, Any]) -> None:
        """Await frontend broadcast for events where ordered live delivery matters."""
        if self._websocket_manager:
            try:
                self._prepare_frontend_notification(notification_data)
                await broadcast_workflow_notification(
                    self._websocket_manager,
                    notification_data,
                )
                self.logger.debug(f"Sent awaited workflow notification: {notification_data['event_type']}")
            except Exception as e:
                self.logger.error(f"Error sending awaited workflow notification: {e}")
        else:
            self.logger.warning("No WebSocket manager available for workflow notifications")

    async def send_status_update(self, status: str, details: Optional[str] = None):
        """Send status update to frontend via WebSocket."""
        self.logger.info(f"🔧 send_status_update called: status='{status}', has_websocket={self._websocket_manager is not None}")
        
        message_data = {
            "event_type": "agent_task_progress",
            "step": status,
            "status": "started",  # Use "started" to match agent_task event handlers
            "details": details
        }
        self._send_frontend_notification(message_data)
        await self._persist_timeline_entry({
            "id": safe_timeline_id("workflow_status", status),
            "type": "step",
            "timestamp": timeline_timestamp(),
            "content": status,
            "detail_kind": "step_note",
            "summary": status,
            "body": details or status,
            "metadata": {
                "event_type": "agent_task_progress",
                "status": "started",
            },
            "streaming": False,
        })

    async def send_step_completion(self, step: str):
        """Mark a step as completed in the frontend."""
        message_data = {
            "event_type": "agent_task_progress", 
            "step": step,
            "status": "completed"
        }
        self._send_frontend_notification(message_data)
        await self._persist_timeline_entry({
            "id": safe_timeline_id("workflow_complete", step),
            "type": "step",
            "timestamp": timeline_timestamp(),
            "content": step,
            "detail_kind": "step_complete",
            "summary": step,
            "body": step,
            "metadata": {
                "event_type": "agent_task_progress",
                "status": "completed",
            },
            "streaming": False,
        })
    
    def generate_todo_status_message(self, todo_title: str) -> str:
        """Generate contextual status message for todo execution."""
        title_lower = todo_title.lower()
        
        # Generate contextual messages based on todo content
        if any(term in title_lower for term in ['reply', 'respond', 'answer']):
            if 'first' in title_lower or '1' in title_lower:
                return "Drafting first reply"
            elif 'second' in title_lower or '2' in title_lower:
                return "Drafting second reply"
            else:
                return "Drafting reply"
        elif any(term in title_lower for term in ['email', 'message', 'mail']):
            return "Processing email"
        elif any(term in title_lower for term in ['create', 'generate', 'draft']):
            return "Creating content"
        elif any(term in title_lower for term in ['search', 'find', 'locate']):
            return "Searching data"
        elif any(term in title_lower for term in ['analyze', 'review', 'process']):
            return "Analyzing content"
        elif any(term in title_lower for term in ['calendar', 'meeting', 'appointment']):
            return "Managing calendar"
        elif any(term in title_lower for term in ['file', 'document', 'folder']):
            return "Processing files"
        else:
            return f"Executing: {todo_title}"
    
    def generate_step_status_message(self, step_description: str, planned_service: str = None, planned_method: str = None) -> str:
        """Generate contextual status message for step execution."""
        desc_lower = step_description.lower()
        
        # Generate contextual messages based on step content and service
        if 'generate' in desc_lower and 'reply' in desc_lower:
            return "Generating reply content"
        elif 'generate' in desc_lower and 'suggestion' in desc_lower:
            return "Creating content suggestion"
        elif 'create' in desc_lower and 'email' in desc_lower:
            return "Creating email draft"
        elif 'send' in desc_lower and 'email' in desc_lower:
            return "Sending email"
        elif 'process' in desc_lower and 'email' in desc_lower:
            return "Processing email request"
        elif 'retrieve' in desc_lower and 'email' in desc_lower:
            return "Retrieving emails"
        elif planned_service == 'email_service':
            if planned_method and ('get' in planned_method or 'retrieve' in planned_method):
                return "Retrieving emails"
            elif planned_method and ('create' in planned_method or 'draft' in planned_method):
                return "Creating email draft"
            elif planned_method and 'send' in planned_method:
                return "Sending email"
            else:
                return "Processing email"
        elif planned_service == 'router_service':
            if planned_method and 'suggestion' in planned_method:
                return "Generating content"
            else:
                return "Processing request"
        elif planned_service == 'calendar_service':
            return "Managing calendar"
        elif planned_service == 'file_service':
            return "Processing files"
        else:
            # Fallback to first few words of description
            words = step_description.split()[:3]
            return ' '.join(words) + ('...' if len(step_description.split()) > 3 else '')
    
    async def generate_planning_status_message(self, user_agent_task: str) -> str:
        """Generate contextual message for planning phase based on agent-task content."""
        # This could use LLM analysis like the other methods, but for now use simple heuristics
        agent_task_lower = user_agent_task.lower()
        
        if any(keyword in agent_task_lower for keyword in ['email', 'message', 'inbox', 'mail']):
            return "Analyzing email operations"
        elif any(keyword in agent_task_lower for keyword in ['calendar', 'meeting', 'appointment', 'schedule']):
            return "Planning calendar operations" 
        elif any(keyword in agent_task_lower for keyword in ['file', 'document', 'folder']):
            return "Planning file operations"
        else:
            return "Analyzing request and planning actions"
    
    # Phase-level status notification methods
    async def notify_phase_start(self, phase: str, user_agent_task: str, description: str):
        """Notify that a workflow phase is starting."""
        self.logger.info(f"🔧 notify_phase_start called: phase='{phase}', description='{description}'")
        await self.send_status_update(description)
    
    async def notify_phase_completion(self, phase: str):
        """Notify that a workflow phase has completed."""
        self.logger.info(f"🔧 notify_phase_completion called: phase='{phase}'")
        await self.send_step_completion(phase)
    
    async def notify_todo_start(self, todo_title: str):
        """Send notification when a todo starts executing."""
        status_message = self.generate_todo_status_message(todo_title)
        await self.send_status_update(status_message, f"Starting: {todo_title}")
        return status_message
    
    async def notify_todo_completion(self, todo_status: str):
        """Send notification when a todo completes."""
        await self.send_step_completion(todo_status)
    
    async def notify_step_start(self, step_description: str, step_number: int, planned_service: str = None, planned_method: str = None):
        """Send notification when a step starts executing."""
        status_message = self.generate_step_status_message(step_description, planned_service, planned_method)
        await self.send_status_update(status_message, f"Step {step_number}: {step_description}")
        return status_message
    
    async def notify_step_completion(self, step_status: str):
        """Send notification when a step completes."""
        await self.send_step_completion(step_status)
    
    # Live todo checklist methods
    async def send_workflow_plan_ready(self, agent_task_id: str, todo_count: int):
        """Notify frontend that workflow plan is ready for database retrieval."""
        self.logger.info(f"📋 Notifying frontend: workflow plan ready with {todo_count} todos")
        
        workflow_ready_message = {
            "event_type": "workflow_plan_ready",
            "agent_task_id": agent_task_id,
            "todo_count": todo_count
        }
        
        self._send_frontend_notification(workflow_ready_message)
        self.logger.info(f"✅ Workflow plan ready notification sent: {todo_count} todos")
    
    async def send_step_update(self, todo_id: str, step_id: str, status: str, result_summary: str = None):
        """Send step-level progress update to frontend."""
        self.logger.info(f"🔧 Sending step update: {step_id} -> {status}")
        
        step_update_message = {
            "event_type": "step_progress_update",
            "todo_id": todo_id,
            "step_id": step_id,
            "status": status
        }
        
        if result_summary:
            step_update_message["result_summary"] = result_summary
        
        self._send_frontend_notification(step_update_message)
        self.logger.info(f"✅ Step update sent: {step_id} status={status}")

    # Dynamic agent step reporting methods
    async def send_dynamic_step_added(self, todo_id: str, step_description: str, status: str = "in_progress") -> str:
        """Add a new step discovered during dynamic agent execution."""
        import uuid
        step_id = f"dynamic_{uuid.uuid4().hex[:8]}"
        
        self.logger.info(f"🔧 Adding dynamic step: {step_description}")
        
        step_added_message = {
            "event_type": "dynamic_step_added",
            "todo_id": todo_id,
            "step_id": step_id,
            "description": step_description,
            "status": status,
            "execution_method": "dynamic_agent"
        }
        
        self._send_frontend_notification(step_added_message)
        await self._persist_timeline_entry({
            "id": step_id,
            "step_id": step_id,
            "correlation_id": step_id,
            "type": "tool_start",
            "timestamp": timeline_timestamp(),
            "content": step_description,
            "detail_kind": "tool_input",
            "summary": step_description,
            "body": step_description,
            "metadata": {
                "event_type": "dynamic_step_added",
                "todo_id": todo_id,
                "status": status,
                "execution_method": "dynamic_agent",
            },
            "streaming": False,
        }, replace_existing=True)
        self.logger.info(f"✅ Dynamic step added notification sent: {step_id}")
        return step_id

    async def send_dynamic_step_updated(
        self, 
        todo_id: str, 
        step_description: str, 
        status: str,
        completion_message: Optional[str] = None,
        step_id: Optional[str] = None
    ):
        """Update a dynamic step status during agent execution."""
        self.logger.info(f"🔄 Updating dynamic step: {step_description} -> {status}")
        
        step_update_message = {
            "event_type": "dynamic_step_updated",
            "todo_id": todo_id,
            "description": step_description,
            "status": status,
            "execution_method": "dynamic_agent"
        }
        if step_id:
            step_update_message["step_id"] = step_id
        
        if completion_message:
            step_update_message["completion_message"] = completion_message
        
        self._send_frontend_notification(step_update_message)
        persisted_id = f"{step_id}_{status}" if step_id else safe_timeline_id("dynamic_step", step_description)
        await self._persist_timeline_entry({
            "id": persisted_id,
            "step_id": step_id,
            "correlation_id": step_id,
            "type": "tool_complete" if status == "completed" else "step",
            "timestamp": timeline_timestamp(),
            "content": completion_message or step_description,
            "detail_kind": "tool_result" if status == "completed" else "step_note",
            "summary": completion_message or step_description,
            "body": completion_message or step_description,
            "metadata": {
                "event_type": "dynamic_step_updated",
                "todo_id": todo_id,
                "status": status,
                "execution_method": "dynamic_agent",
            },
            "streaming": False,
        }, replace_existing=True)
        self.logger.info(f"✅ Dynamic step update sent: {step_description} status={status}")

    async def send_step_detail_update(
        self,
        entry: Dict[str, Any],
        delta: Optional[str] = None
    ):
        """Send rich, tray-oriented detail for an existing execution step."""
        # Tray details are verbose tool payloads, not readable progress: flag them so the contract mirror skips progress_* and the activity trail excludes them.
        entry = {**entry, "metadata": {**(entry.get("metadata") or {}), "raw_detail": True}}
        detail_message = {
            "event_type": "agent_task_step_detail",
            "entry": entry,
            "timeline_entry": entry,
        }
        if delta is not None:
            detail_message["delta"] = delta

        self._send_frontend_notification(detail_message)
        persisted_entry = dict(entry)
        if delta is not None:
            persisted_entry["body"] = f"{persisted_entry.get('body') or ''}{delta}"
        await self._persist_timeline_entry(persisted_entry, replace_existing=True)
        self.logger.info(
            "✅ Step detail update sent: %s",
            entry.get("summary") or entry.get("content") or entry.get("id"),
        )

    async def publish_agent_task_artifact(
        self,
        *,
        output: Any,
        source_step_id: str,
    ) -> bool:
        """Persist one selected direct-write artifact before optional live delivery."""
        from .artifact_activity_publication import publish_agent_task_artifact

        return await publish_agent_task_artifact(
            websocket_manager=self._websocket_manager,
            agent_task_id=self._agent_task_id,
            root_task_id=self._root_task_id,
            previous_task_id=self._previous_task_id,
            output=output,
            source_step_id=source_step_id,
        )

    async def send_agent_progress_update(self, message: str, details: Optional[str] = None):
        """Send agent-specific progress updates."""
        self.logger.info(f"🤖 Agent progress: {message}")
        
        progress_message = {
            "event_type": "agent_progress_update",
            "message": message,
            "details": details,
            "execution_method": "dynamic_agent"
        }
        
        self._send_frontend_notification(progress_message)
        await self._persist_timeline_entry({
            "id": safe_timeline_id("agent_progress", message),
            "type": "step",
            "timestamp": timeline_timestamp(),
            "content": message,
            "detail_kind": "step_note",
            "summary": message,
            "body": details or message,
            "metadata": {
                "event_type": "agent_progress_update",
                "execution_method": "dynamic_agent",
            },
            "streaming": False,
        })
        self.logger.info(f"✅ Agent progress update sent: {message}")

    async def send_agent_result_streaming_chunk(
        self,
        *,
        token: str,
        partial_result: str,
        operation: str = "multi_step_workflow",
        source: str = "finalizer",
    ):
        """Send provisional user-visible result text while the finalizer is still running."""
        streaming_message = {
            "event_type": "agent_task_streaming",
            "operation": operation,
            "token": token,
            "partial_result": partial_result,
            "stage": "finalizing",
            "streaming": True,
            "source": source,
            "provisional": True,
            "replace_on_complete": True,
            "execution_method": "dynamic_agent",
        }

        await self._send_frontend_notification_async(streaming_message)
        self.logger.debug(
            "Sent provisional finalizer result chunk: token_len=%s partial_len=%s",
            len(token or ""),
            len(partial_result or ""),
        )

    async def send_agent_result_streaming_complete(
        self,
        *,
        final_result: str,
        operation: str = "multi_step_workflow",
        source: str = "finalizer",
    ):
        """Tell the frontend to replace provisional finalizer text with the final result."""
        complete_message = {
            "event_type": "agent_task_streaming_complete",
            "operation": operation,
            "final_result": final_result,
            "stage": "complete",
            "source": source,
            "provisional": False,
            "replace_on_complete": True,
            "execution_method": "dynamic_agent",
        }

        await self._send_frontend_notification_async(complete_message)
        self.logger.info("✅ Finalizer streaming completion sent")
    
    # Checkpoint-aware progress methods (Phase 3.4)
    async def send_checkpoint_waiting_status(self, agent_task_id: str, prompt: str):
        """
        Send status update indicating workflow is paused waiting for user input.
        
        Args:
            agent_task_id: Agent task ID for tracking
            prompt: The prompt shown to the user
        """
        self.logger.info(f"⏸️ Workflow paused at checkpoint: {prompt}")
        
        checkpoint_status_message = {
            "event_type": "checkpoint_waiting",
            "agent_task_id": agent_task_id,
            "status": "waiting_user_input",
            "prompt": prompt,
            "message": "Waiting for your input..."
        }
        
        self._send_frontend_notification(checkpoint_status_message)
        self.logger.info("✅ Checkpoint waiting status sent")

    async def send_blocker_status(
        self,
        agent_task_id: str,
        *,
        kind: str,
        message: str,
        resolved: bool = False,
        connection_id: Optional[str] = None,
    ):
        """Send user-facing status for a temporary or hard execution blocker."""
        blocker_message = {
            "event_type": "agent_task_blocker_resolved" if resolved else "agent_task_blocker_waiting",
            "agent_task_id": agent_task_id,
            "kind": kind,
            "message": message,
        }
        if connection_id:
            blocker_message["connection_id"] = connection_id

        self._send_frontend_notification(blocker_message)
        self.logger.info("✅ Blocker status sent: %s resolved=%s", kind, resolved)
    
    async def send_checkpoint_resumed_status(self, agent_task_id: str, user_response: str):
        """
        Send status update indicating workflow has resumed after checkpoint.
        
        Args:
            agent_task_id: Agent task ID for tracking
            user_response: The user's response
        """
        self.logger.info(f"▶️ Workflow resumed with response: {user_response}")
        
        resumed_status_message = {
            "event_type": "checkpoint_resumed",
            "agent_task_id": agent_task_id,
            "status": "resumed",
            "user_response": user_response,
            "message": "Continuing workflow..."
        }
        
        self._send_frontend_notification(resumed_status_message)
        self.logger.info("✅ Checkpoint resumed status sent")
    
    async def send_session_context_info(self, agent_task_id: str, has_recent_context: bool, context_count: int = 0):
        """
        Send information about session context being used for this agent task.
        
        Helps frontend display continuity indicators like "Using results from previous 3 agent tasks"
        
        Args:
            agent_task_id: Agent task ID for tracking
            has_recent_context: Whether recent agent-task context is available
            context_count: Number of recent agent tasks in context
        """
        if has_recent_context and context_count > 0:
            self.logger.info(f"📚 AgentTask enriched with {context_count} recent agent tasks")
            
            context_info_message = {
                "event_type": "session_context_info",
                "agent_task_id": agent_task_id,
                "has_recent_context": True,
                "context_count": context_count,
                "message": f"Using context from {context_count} recent task{'s' if context_count > 1 else ''}"
            }
            
            self._send_frontend_notification(context_info_message)
            self.logger.info(f"✅ Session context info sent: {context_count} agent tasks")