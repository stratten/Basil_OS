"""Agent task row and event-data mappers."""

import json
from datetime import datetime
from typing import Any, Dict

from .....models import AgentTask


def row_to_agent_task(row) -> AgentTask:
    """Convert a database row to a AgentTask object."""
    keys = row.keys()
    return AgentTask(
        id=row["id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        original_prompt=row["original_prompt"],
        transcribed_prompt=row["transcribed_prompt"],
        display_prompt_markdown=row["display_prompt_markdown"] if "display_prompt_markdown" in keys else None,
        app_name=row["app_name"],
        window_title=row["window_title"],
        screen_text=row["screen_text"],
        screen_capture_path=row["screen_capture_path"],
        confidence_score=row["confidence_score"],
        status=row["status"],
        operation_parameters=json.loads(row["operation_parameters"]) if row["operation_parameters"] else {},
        result_data=json.loads(row["result_data"]) if row["result_data"] else {},
        clarifications=json.loads(row["clarifications"]) if row["clarifications"] else [],
        root_task_id=row["root_task_id"] if "root_task_id" in keys else row["id"],
        previous_task_id=row["previous_task_id"] if "previous_task_id" in keys else None,
        chain_sequence_number=row["chain_sequence_number"] if row["chain_sequence_number"] is not None else 0,
        session_type=row["session_type"],
        session_status=row["session_status"],
        workflow_plan=json.loads(row["workflow_plan"]) if row["workflow_plan"] else None,
        current_step=row["current_step"],
        total_planned_steps=row["total_planned_steps"],
        completed_steps=json.loads(row["completed_steps"]) if row["completed_steps"] else None,
        pending_steps=json.loads(row["pending_steps"]) if row["pending_steps"] else None,
        accumulated_artifacts=json.loads(row["accumulated_artifacts"]) if row["accumulated_artifacts"] else None,
        last_interaction_timestamp=datetime.fromisoformat(row["last_interaction_timestamp"]) if row["last_interaction_timestamp"] else None,
        interaction_count=row["interaction_count"] if row["interaction_count"] is not None else 0,
        title=row["title"] if "title" in keys else None,
        origin_type=row["origin_type"] if "origin_type" in keys else None,
        origin_id=row["origin_id"] if "origin_id" in keys else None,
        execution_timeline=json.loads(row["execution_timeline"]) if "execution_timeline" in keys and row["execution_timeline"] else None
    )


def build_agent_task_data_dict(agent_task: AgentTask) -> Dict[str, Any]:
    """Build a dictionary from a AgentTask for event detection."""
    return {
        'id': agent_task.id,
        'timestamp': agent_task.timestamp.isoformat(),
        'original_prompt': agent_task.original_prompt,
        'transcribed_prompt': agent_task.transcribed_prompt,
        'display_prompt_markdown': agent_task.display_prompt_markdown,
        'app_name': agent_task.app_name,
        'window_title': agent_task.window_title,
        'screen_text': agent_task.screen_text,
        'screen_capture_path': agent_task.screen_capture_path,
        'confidence_score': agent_task.confidence_score,
        'status': agent_task.status,
        'operation_parameters': agent_task.operation_parameters,
        'result_data': agent_task.result_data,
        'clarifications': agent_task.clarifications,
        'root_task_id': agent_task.root_task_id,
        'previous_task_id': agent_task.previous_task_id,
        'chain_sequence_number': agent_task.chain_sequence_number,
        'updated_at': datetime.now().isoformat()
    }
