"""
LangGraph Agent Step Parser

This module handles parsing of agent output text to extract STEP_START/STEP_COMPLETE markers
and convert them into structured progress updates with WebSocket notifications and database persistence.

The step parser is specialized for post-execution analysis of agent output, distinct from the
real-time progress callbacks that happen during tool execution.

Key functions:
- parse_agent_steps_from_output(): Main parsing function that extracts step markers
- WebSocket notification sending for step start/completion
- Database persistence of dynamic steps
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List


def _make_step_detail(
    *,
    step_desc: str,
    detail_kind: str,
    body: str,
    step_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a tray detail entry from STEP_START / STEP_COMPLETE text."""
    from datetime import datetime
    import uuid

    entry_id = step_id or f"parsed_step_{uuid.uuid4().hex[:10]}"
    return {
        "id": entry_id if detail_kind == "step_note" else f"{entry_id}_{detail_kind}",
        "type": "step",
        "timestamp": datetime.now().isoformat(),
        "content": step_desc,
        "step_id": step_id,
        "correlation_id": step_id,
        "detail_kind": detail_kind,
        "summary": step_desc,
        "body": body,
        "metadata": {"source": "step_parser"},
        "streaming": False,
    }


async def parse_agent_steps_from_output(
    agent_output: str, 
    todo_id: Optional[str] = None,
    notifier: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Parse STEP_START and STEP_COMPLETE markers from agent output to create dynamic steps.
    Sends real-time WebSocket notifications and stores steps in database.
    
    Args:
        agent_output: The agent's output text containing step markers
        todo_id: Optional todo ID for database storage
        notifier: Optional WorkflowStatusNotifier for WebSocket updates
        
    Returns:
        List of step dictionaries with description and status
    """
    import logging
    logger = logging.getLogger(__name__)
    
    steps = []
    
    # Handle case where agent_output might be a list
    if isinstance(agent_output, list):
        agent_output = str(agent_output)
    
    # Split on both newlines and common separators where step markers might appear
    # Also handle cases where markers are embedded in longer text
    text_parts = agent_output.replace('\\n', '\n').split('\n')
    
    # Also check for step markers within longer lines
    all_parts = []
    for part in text_parts:
        # Split on sentences and common separators where step markers might be embedded
        sub_parts = part.split('. ')
        all_parts.extend(sub_parts)
    
    lines = all_parts
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if 'STEP_START:' in line_stripped:
            # Extract step description from the line containing STEP_START:
            step_start_pos = line_stripped.find('STEP_START:')
            step_desc = line_stripped[step_start_pos + 11:].strip()  # 11 = len('STEP_START:')
            
            if not step_desc:
                continue  # Skip empty step descriptions
            
            # Send real-time WebSocket notification for step start and store in database
            step_id = None
            logger.info(f"🔧 DEBUG: Attempting WebSocket notification: notifier={notifier is not None}, todo_id={todo_id}")
            if notifier and todo_id:
                try:
                    logger.info(f"🔧 DEBUG: Calling send_dynamic_step_added with todo_id={todo_id}, step_desc={step_desc}")
                    step_id = await notifier.send_dynamic_step_added(
                        todo_id=todo_id,
                        step_description=step_desc,
                        status="in_progress"
                    )
                    logger.info(f"📡 Sent WebSocket notification: Step started - {step_desc}")
                    logger.info(f"🔧 DEBUG: send_dynamic_step_added returned step_id={step_id}")
                except Exception as e:
                    logger.error(f"❌ DEBUG: send_dynamic_step_added failed: {e}")
                
                # Note: Database persistence removed - steps are tracked via WebSocket in real-time
            else:
                logger.warning(f"⚠️ DEBUG: Skipping WebSocket notification: notifier={notifier is not None}, todo_id={todo_id}")
            
            # Look for corresponding STEP_COMPLETE
            complete_desc = None
            for j in range(i+1, len(lines)):
                if 'STEP_COMPLETE:' in lines[j]:
                    complete_start_pos = lines[j].find('STEP_COMPLETE:')
                    complete_desc = lines[j][complete_start_pos + 14:].strip()  # 14 = len('STEP_COMPLETE:')
                    break
            
            step_data = {
                "description": step_desc,
                "completion_desc": complete_desc,
                "status": "completed" if complete_desc else "in_progress",
                "details": [
                    _make_step_detail(
                        step_desc=step_desc,
                        detail_kind="step_note",
                        body=step_desc,
                        step_id=step_id,
                    )
                ]
            }
            
            # Send completion notification if step completed and update database
            if complete_desc and notifier and todo_id and step_id:
                try:
                    await notifier.send_dynamic_step_updated(
                        todo_id=todo_id,
                        step_description=step_desc,
                        status="completed",
                        completion_message=complete_desc,
                        step_id=step_id,
                    )
                    completion_detail = _make_step_detail(
                        step_desc=step_desc,
                        detail_kind="step_complete",
                        body=complete_desc,
                        step_id=step_id,
                    )
                    step_data["details"].append(completion_detail)
                    if hasattr(notifier, "send_step_detail_update"):
                        await notifier.send_step_detail_update(entry=completion_detail)
                    logger.info(f"📡 Sent WebSocket notification: Step completed - {complete_desc}")
                    
                    # Note: Database persistence removed - steps are tracked via WebSocket in real-time
                    
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send completion notification or update database: {e}")
            
            steps.append(step_data)
    
    return steps
