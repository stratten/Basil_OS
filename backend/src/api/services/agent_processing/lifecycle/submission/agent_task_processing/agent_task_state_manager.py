"""
AgentTask State Manager

This module implements the state machine for agent task processing.
It defines valid state transitions and handles the business logic for each state.
"""

import logging
from enum import Enum
from typing import Dict, Set, Optional, Callable, Any
from dataclasses import dataclass

from api.core.knowledge.sqlite.sqlite_knowledge_service import AgentTaskEvent

logger = logging.getLogger(__name__)

class AgentTaskStatus(Enum):
    """Valid statuses for agent tasks in the state machine."""
    
    # Initial processing
    CAPTURING = "capturing"                 # Screen context capture/OCR in progress
    ROUTING = "routing"                     # Initial routing in progress
    NEEDS_CLARIFICATION = "needs_clarification"  # Routing failed, needs user input
    
    # After clarification
    CLARIFICATION_ADDED = "clarification_added"  # User provided clarification, ready for re-routing
    
    # Successful routing
    ROUTED = "routed"                      # Successfully routed to operation, ready for processing
    PROCESSING = "processing"              # Operation execution in progress
    AWAITING_PROVIDER_DELEGATION = "awaiting_provider_delegation"
    AWAITING_DELEGATED_AGENTS = "awaiting_delegated_agents"
    
    # Final states
    COMPLETED = "completed"                # Final result ready
    FAILED = "failed"                      # Unrecoverable error
    CANCELLED = "cancelled"                # Explicit user or parent-chain cancellation

@dataclass(frozen=True)
class StateTransition:
    """Represents a state transition with metadata."""
    from_status: Optional[AgentTaskStatus]
    to_status: AgentTaskStatus
    trigger_event: str  # Event type that triggers this transition
    handler: str        # Name of the handler method
    description: str

class AgentTaskStateMachine:
    """
    State machine for agent task processing.
    
    Defines valid state transitions and handles business logic for each state.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._state_handlers: Dict[str, Callable] = {}
        self._transition_handlers: Dict[str, Callable] = {}
        self._setup_transitions()
        
    def _setup_transitions(self) -> None:
        """Define all valid state transitions."""
        
        # Valid state transitions
        self.transitions = [
            # Initial agent-task flow
            StateTransition(
                from_status=None,  # New agent task
                to_status=AgentTaskStatus.CAPTURING,
                trigger_event="created",
                handler="handle_capture_started",
                description="New agent_task created, screen context capture in progress"
            ),
            StateTransition(
                from_status=AgentTaskStatus.CAPTURING,
                to_status=AgentTaskStatus.ROUTING,
                trigger_event="status_changed",
                handler="handle_new_agent_task",
                description="Screen context captured, start routing"
            ),
            StateTransition(
                from_status=None,  # New agent task
                to_status=AgentTaskStatus.ROUTING,
                trigger_event="created",
                handler="handle_new_agent_task",
                description="New agent_task created, start routing"
            ),
            StateTransition(
                from_status=AgentTaskStatus.FAILED,
                to_status=AgentTaskStatus.ROUTING,
                trigger_event="status_changed",
                handler="handle_new_agent_task",
                description="Failed agent_task retry requested, restart routing"
            ),
            
            # Routing outcomes
            StateTransition(
                from_status=AgentTaskStatus.ROUTING,
                to_status=AgentTaskStatus.ROUTED,
                trigger_event="status_changed",
                handler="handle_routing_success",
                description="Routing successful, ready for processing"
            ),
            StateTransition(
                from_status=AgentTaskStatus.ROUTING,
                to_status=AgentTaskStatus.NEEDS_CLARIFICATION,
                trigger_event="status_changed",
                handler="handle_routing_needs_clarification",
                description="Routing failed, needs user clarification"
            ),
            
            # Clarification flow
            StateTransition(
                from_status=AgentTaskStatus.NEEDS_CLARIFICATION,
                to_status=AgentTaskStatus.CLARIFICATION_ADDED,
                trigger_event="clarification_added",
                handler="handle_clarification_received",
                description="User provided clarification, ready for re-routing"
            ),
            StateTransition(
                from_status=AgentTaskStatus.CLARIFICATION_ADDED,
                to_status=AgentTaskStatus.ROUTED,
                trigger_event="status_changed",
                handler="handle_clarification_routing_success",
                description="Re-routing after clarification successful"
            ),
            StateTransition(
                from_status=AgentTaskStatus.CLARIFICATION_ADDED,
                to_status=AgentTaskStatus.PROCESSING,
                trigger_event="status_changed",
                handler="handle_clarification_routing_success",
                description="Direct processing after clarification (skips routed state)"
            ),
            StateTransition(
                from_status=AgentTaskStatus.CLARIFICATION_ADDED,
                to_status=AgentTaskStatus.NEEDS_CLARIFICATION,
                trigger_event="status_changed",
                handler="handle_clarification_routing_failed",
                description="Re-routing after clarification failed, needs more clarification"
            ),
            
            # Processing flow
            StateTransition(
                from_status=AgentTaskStatus.ROUTING,
                to_status=AgentTaskStatus.PROCESSING,
                trigger_event="status_changed",
                handler="handle_processing_started",
                description="Direct processing after successful routing (skips routed state)"
            ),
            StateTransition(
                from_status=AgentTaskStatus.ROUTED,
                to_status=AgentTaskStatus.PROCESSING,
                trigger_event="status_changed",
                handler="handle_processing_started",
                description="Operation processing started"
            ),
            StateTransition(
                from_status=AgentTaskStatus.PROCESSING,
                to_status=AgentTaskStatus.COMPLETED,
                trigger_event="status_changed",
                handler="handle_processing_completed",
                description="Operation processing completed successfully"
            ),
            StateTransition(
                from_status=AgentTaskStatus.PROCESSING,
                to_status=AgentTaskStatus.AWAITING_PROVIDER_DELEGATION,
                trigger_event="status_changed",
                handler="handle_provider_delegation_waiting",
                description="Primary workflow paused for one delegated provider child",
            ),
            StateTransition(
                from_status=AgentTaskStatus.PROCESSING,
                to_status=AgentTaskStatus.AWAITING_DELEGATED_AGENTS,
                trigger_event="status_changed",
                handler="handle_provider_delegation_waiting",
                description="Primary workflow paused for one or more generic delegated children",
            ),
            StateTransition(
                from_status=AgentTaskStatus.AWAITING_PROVIDER_DELEGATION,
                to_status=AgentTaskStatus.PROCESSING,
                trigger_event="status_changed",
                handler="handle_provider_delegation_resumed",
                description="Delegated provider outcome claimed; bridge resumes primary workflow",
            ),
            StateTransition(
                from_status=AgentTaskStatus.AWAITING_DELEGATED_AGENTS,
                to_status=AgentTaskStatus.PROCESSING,
                trigger_event="status_changed",
                handler="handle_provider_delegation_resumed",
                description="Generic delegated-child outcome gate settled; bridge resumes primary workflow",
            ),
            StateTransition(
                from_status=AgentTaskStatus.AWAITING_PROVIDER_DELEGATION,
                to_status=AgentTaskStatus.CANCELLED,
                trigger_event="status_changed",
                handler="handle_processing_cancelled",
                description="Parent cancellation fences delegated-provider continuation",
            ),
            StateTransition(
                from_status=AgentTaskStatus.AWAITING_DELEGATED_AGENTS,
                to_status=AgentTaskStatus.CANCELLED,
                trigger_event="status_changed",
                handler="handle_processing_cancelled",
                description="Parent cancellation fences generic delegated children",
            ),
            StateTransition(
                from_status=AgentTaskStatus.AWAITING_PROVIDER_DELEGATION,
                to_status=AgentTaskStatus.FAILED,
                trigger_event="status_changed",
                handler="handle_processing_failed",
                description="Delegated-provider continuation failed unrecoverably",
            ),
            StateTransition(
                from_status=AgentTaskStatus.AWAITING_DELEGATED_AGENTS,
                to_status=AgentTaskStatus.FAILED,
                trigger_event="status_changed",
                handler="handle_processing_failed",
                description="Generic delegated-child continuation failed unrecoverably",
            ),
            
            # Error handling
            StateTransition(
                from_status=AgentTaskStatus.ROUTING,
                to_status=AgentTaskStatus.FAILED,
                trigger_event="status_changed",
                handler="handle_routing_failed",
                description="Routing failed with unrecoverable error"
            ),
            StateTransition(
                from_status=AgentTaskStatus.PROCESSING,
                to_status=AgentTaskStatus.FAILED,
                trigger_event="status_changed",
                handler="handle_processing_failed",
                description="Processing failed with unrecoverable error"
            ),

            # Async outcome re-resolution (P2). The finalizer's LLM outcome
            # evaluation runs off the critical path, so a provisional terminal
            # state can flip once verification lands. By then finalizer_result is
            # always set on the record, so handle_processing_completed no-ops the
            # legacy broadcast (P2 emits agent_task_outcome_update itself); it is
            # reused here purely to mark these terminal→terminal transitions valid
            # without re-sending a result. handle_processing_failed is NOT used
            # because it would re-broadcast an agent_task_result.
            StateTransition(
                from_status=AgentTaskStatus.FAILED,
                to_status=AgentTaskStatus.COMPLETED,
                trigger_event="status_changed",
                handler="handle_processing_completed",
                description="Async outcome verification upgraded a provisional failure to completed"
            ),
            StateTransition(
                from_status=AgentTaskStatus.COMPLETED,
                to_status=AgentTaskStatus.FAILED,
                trigger_event="status_changed",
                handler="handle_processing_completed",
                description="Async outcome verification downgraded a provisional success to failed"
            ),
        ]
        
        # Build transition lookup tables
        self._build_transition_tables()
        
    def _build_transition_tables(self) -> None:
        """Build lookup tables for fast transition resolution."""
        self._transitions_by_from_status: Dict[Optional[AgentTaskStatus], Dict[AgentTaskStatus, StateTransition]] = {}
        self._transitions_by_event: Dict[str, Set[StateTransition]] = {}
        
        for transition in self.transitions:
            # Group by from_status
            if transition.from_status not in self._transitions_by_from_status:
                self._transitions_by_from_status[transition.from_status] = {}
            self._transitions_by_from_status[transition.from_status][transition.to_status] = transition
            
            # Group by event type
            if transition.trigger_event not in self._transitions_by_event:
                self._transitions_by_event[transition.trigger_event] = set()
            self._transitions_by_event[transition.trigger_event].add(transition)
    
    def is_valid_transition(self, from_status: Optional[str], to_status: str, event_type: str) -> bool:
        """Check if a state transition is valid."""
        try:
            from_enum = AgentTaskStatus(from_status) if from_status else None
            to_enum = AgentTaskStatus(to_status)
            
            if from_enum in self._transitions_by_from_status:
                transitions = self._transitions_by_from_status[from_enum]
                if to_enum in transitions:
                    transition = transitions[to_enum]
                    return transition.trigger_event == event_type
            
            return False
        except ValueError:
            # Invalid status enum
            return False
    
    def get_transition(self, from_status: Optional[str], to_status: str, event_type: str) -> Optional[StateTransition]:
        """Get the transition object for a state change."""
        try:
            from_enum = AgentTaskStatus(from_status) if from_status else None
            to_enum = AgentTaskStatus(to_status)
            
            if from_enum in self._transitions_by_from_status:
                transitions = self._transitions_by_from_status[from_enum]
                if to_enum in transitions:
                    transition = transitions[to_enum]
                    if transition.trigger_event == event_type:
                        return transition
            
            return None
        except ValueError:
            return None
    
    def get_valid_next_states(self, current_status: Optional[str]) -> Set[AgentTaskStatus]:
        """Get all valid next states from the current status."""
        try:
            current_enum = AgentTaskStatus(current_status) if current_status else None
            
            if current_enum in self._transitions_by_from_status:
                return set(self._transitions_by_from_status[current_enum].keys())
            
            return set()
        except ValueError:
            return set()
    
    def register_state_handler(self, handler_name: str, handler_func: Callable) -> None:
        """Register a handler function for a specific state transition."""
        self._state_handlers[handler_name] = handler_func
        self.logger.info(f"Registered state handler: {handler_name}")
    
    def handle_event(self, event: AgentTaskEvent) -> bool:
        """
        Handle a agent_task event and trigger appropriate state transitions.
        
        Returns True if the event was handled, False if no valid transition.
        """
        agent_task_data = event.agent_task_data
        if not agent_task_data:
            self.logger.warning(f"Event {event.event_type} for {event.agent_task_id} has no agent-task data")
            return False
        
        # Handle different event types
        if event.event_type == 'created':
            return self._handle_created_event(event)
        elif event.event_type == 'status_changed':
            return self._handle_status_changed_event(event)
        elif event.event_type == 'clarification_added':
            return self._handle_clarification_added_event(event)
        elif event.event_type == 'updated':
            return self._handle_updated_event(event)
        
        self.logger.warning(f"Unknown event type: {event.event_type}")
        return False
    
    def _handle_created_event(self, event: AgentTaskEvent) -> bool:
        """Handle new agent-task creation."""
        transition = self.get_transition(None, event.new_status, 'created')
        if transition:
            self.logger.info(f"AgentTask {event.agent_task_id} created with status {event.new_status}")
            return self._execute_transition_handler(transition, event)
        
        self.logger.warning(f"Invalid creation status: {event.new_status}")
        return False
    
    def _handle_status_changed_event(self, event: AgentTaskEvent) -> bool:
        """Handle status change events."""
        transition = self.get_transition(event.old_status, event.new_status, 'status_changed')
        if transition:
            self.logger.info(f"AgentTask {event.agent_task_id}: {event.old_status} → {event.new_status}")
            return self._execute_transition_handler(transition, event)
        
        self.logger.warning(f"Invalid status transition: {event.old_status} → {event.new_status}")
        return False
    
    def _handle_clarification_added_event(self, event: AgentTaskEvent) -> bool:
        """Handle clarification addition."""
        current_status = event.agent_task_data.get('status')
        
        # Find appropriate transition for clarification
        for transition in self._transitions_by_event.get('clarification_added', []):
            if transition.from_status and transition.from_status.value == current_status:
                self.logger.info(f"AgentTask {event.agent_task_id} received clarification")
                return self._execute_transition_handler(transition, event)
        
        self.logger.warning(f"No clarification transition available from status: {current_status}")
        return False
    
    def _handle_updated_event(self, event: AgentTaskEvent) -> bool:
        """Handle general update events."""
        # General updates don't typically trigger state transitions
        self.logger.debug(f"AgentTask {event.agent_task_id} updated")
        return True
    
    def _execute_transition_handler(self, transition: StateTransition, event: AgentTaskEvent) -> bool:
        """Execute the handler for a state transition."""
        handler_func = self._state_handlers.get(transition.handler)
        if handler_func:
            try:
                return handler_func(event, transition)
            except Exception as e:
                self.logger.error(f"Error in transition handler {transition.handler}: {e}")
                return False
        else:
            self.logger.warning(f"No handler registered for: {transition.handler}")
            return False
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get a summary of the state machine configuration."""
        return {
            'total_states': len(AgentTaskStatus),
            'total_transitions': len(self.transitions),
            'registered_handlers': list(self._state_handlers.keys()),
            'states': [status.value for status in AgentTaskStatus],
            'transitions': [
                {
                    'from': transition.from_status.value if transition.from_status else None,
                    'to': transition.to_status.value,
                    'event': transition.trigger_event,
                    'handler': transition.handler,
                    'description': transition.description
                }
                for transition in self.transitions
            ]
        } 