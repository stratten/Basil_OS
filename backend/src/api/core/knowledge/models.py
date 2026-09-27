"""Database models for the knowledge base."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List

@dataclass
class Activity:
    """Represents an activity record in the database."""
    id: str
    timestamp: datetime
    app_name: str
    window_title: Optional[str] = None
    extracted_text: Optional[str] = None
    duration: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    capture_frequency_minutes: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'app_name': self.app_name,
            'window_title': self.window_title,
            'extracted_text': self.extracted_text,
            'duration': self.duration,
            'metadata': self.metadata or {},
            'ai_analysis': self.ai_analysis or {},
            'capture_frequency_minutes': self.capture_frequency_minutes
        }

@dataclass
class Transcription:
    """Represents a transcription record in the database."""
    id: str
    timestamp: datetime
    transcription_text: str
    model_name: str
    audio_file_path: str
    duration_seconds: Optional[float] = None
    language: str = "en"
    created_at: Optional[datetime] = None
    last_transcribed_at: Optional[datetime] = None
    
    # Context information
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    task_category: Optional[str] = None
    
    # User interaction
    was_edited: bool = False
    edit_distance: Optional[int] = None
    edited_text: Optional[str] = None
    
    # Performance metrics
    confidence_score: Optional[float] = None
    processing_time_ms: Optional[int] = None
    user_rating: Optional[int] = None
    user_feedback: Optional[str] = None
    
    # Relationships
    session_id: Optional[str] = None
    related_activity_id: Optional[str] = None
    
    # Follow-up actions
    action_taken: Optional[str] = None

    # Lifecycle state
    # status is one of "pending", "completed", "failed". Defaults to
    # "completed" so legacy rows (written before this field existed) and any
    # in-code Transcription constructed without an explicit status continue
    # to represent a successful run. The pending/failed values are set by
    # the transcription lifecycle helper when audio is persisted before the
    # model runs -- see services/transcription/transcription_lifecycle.py.
    status: str = "completed"
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'transcription_text': self.transcription_text,
            'model_name': self.model_name,
            'audio_file_path': self.audio_file_path,
            'duration_seconds': self.duration_seconds,
            'language': self.language,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_transcribed_at': self.last_transcribed_at.isoformat() if self.last_transcribed_at else None,
            
            # Context information
            'app_name': self.app_name,
            'window_title': self.window_title,
            'task_category': self.task_category,
            
            # User interaction
            'was_edited': self.was_edited,
            'edit_distance': self.edit_distance,
            'edited_text': self.edited_text,
            
            # Performance metrics
            'confidence_score': self.confidence_score,
            'processing_time_ms': self.processing_time_ms,
            'user_rating': self.user_rating,
            'user_feedback': self.user_feedback,
            
            # Relationships
            'session_id': self.session_id,
            'related_activity_id': self.related_activity_id,
            
            # Follow-up actions
            'action_taken': self.action_taken,

            # Lifecycle state
            'status': self.status,
            'error_message': self.error_message,
        }

@dataclass
class AgentTask:
    """Represents a agent_task record with embedded clarifications."""
    id: str
    timestamp: datetime
    
    # Core agent task data
    original_prompt: str
    transcribed_prompt: str
    display_prompt_markdown: Optional[str] = None
    confidence_score: Optional[float] = None
    
    # Processing context (preserved for clarifications)
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    screen_text: Optional[str] = None
    screen_capture_path: Optional[str] = None
    
    # Display
    title: Optional[str] = None

    # Provenance: which application surface created this task (NULL = directly
    # user-initiated). See schema.py's agent_tasks table comment for the value set.
    origin_type: Optional[str] = None
    origin_id: Optional[str] = None
    
    # Processing results
    operation: Optional[str] = None
    operation_confidence: Optional[float] = None
    operation_parameters: Optional[Dict[str, Any]] = None
    result_data: Optional[Dict[str, Any]] = None
    
    # Status tracking
    status: str = "processing"  # processing, completed, failed, needs_clarification
    processing_time_ms: Optional[int] = None
    
    # Clarifications as nested array (JSON stored)
    clarifications: Optional[List[Dict[str, Any]]] = None
    
    # Task chain fields (for follow-up turns)
    root_task_id: Optional[str] = None  # Stable root task ID for every row in a thread
    previous_task_id: Optional[str] = None  # Immediate predecessor turn; NULL for root rows
    chain_sequence_number: int = 0  # 0 for root, 1+ for follow-ups
    
    # Session fields (used for both manual chains and agent-planned workflows)
    session_type: Optional[str] = None  # NULL='standalone', 'chain', 'collaborative'
    session_status: Optional[str] = None  # 'planning', 'active', 'waiting_input', etc.
    workflow_plan: Optional[List[Dict[str, Any]]] = None  # Planned steps (collaborative only)
    current_step: Optional[int] = None  # Current step index
    total_planned_steps: Optional[int] = None  # Total steps planned
    completed_steps: Optional[List[Dict[str, Any]]] = None  # Completed step results
    pending_steps: Optional[List[Dict[str, Any]]] = None  # Remaining steps (collaborative)
    accumulated_artifacts: Optional[Dict[str, Any]] = None  # Artifacts from all steps in chain
    last_interaction_timestamp: Optional[datetime] = None  # Last user interaction
    interaction_count: int = 0  # Number of interactions/checkpoints
    
    # Execution timeline (unified chronological log of thinking + steps + tool calls)
    execution_timeline: Optional[List[Dict[str, Any]]] = None
    
    # User feedback
    user_rating: Optional[int] = None
    user_feedback: Optional[str] = None
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'original_prompt': self.original_prompt,
            'transcribed_prompt': self.transcribed_prompt,
            'display_prompt_markdown': self.display_prompt_markdown,
            'confidence_score': self.confidence_score,
            
            # Context
            'app_name': self.app_name,
            'window_title': self.window_title,
            'screen_text': self.screen_text,
            'screen_capture_path': self.screen_capture_path,
            
            # Processing
            'operation': self.operation,
            'operation_confidence': self.operation_confidence,
            'operation_parameters': self.operation_parameters or {},
            'result_data': self.result_data or {},
            
            # Status
            'status': self.status,
            'processing_time_ms': self.processing_time_ms,
            
            # Clarifications
            'clarifications': self.clarifications or [],
            'origin_type': self.origin_type,
            'origin_id': self.origin_id,
            
            # Task chain
            'root_task_id': self.root_task_id,
            'previous_task_id': self.previous_task_id,
            'chain_sequence_number': self.chain_sequence_number,
            
            # Session fields
            'session_type': self.session_type,
            'session_status': self.session_status,
            'workflow_plan': self.workflow_plan or [],
            'current_step': self.current_step,
            'total_planned_steps': self.total_planned_steps,
            'completed_steps': self.completed_steps or [],
            'pending_steps': self.pending_steps or [],
            'accumulated_artifacts': self.accumulated_artifacts or {},
            'last_interaction_timestamp': self.last_interaction_timestamp.isoformat() if self.last_interaction_timestamp else None,
            'interaction_count': self.interaction_count,
            
            # User feedback
            'user_rating': self.user_rating,
            'user_feedback': self.user_feedback,
            
            # Timestamps
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        } 