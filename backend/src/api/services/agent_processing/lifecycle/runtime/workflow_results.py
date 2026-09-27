"""
Shared result dataclasses for agent processing workflow execution.

These types are extracted to avoid circular import issues between workflow_coordinator
and the workflow runtime services.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class WorkflowExecutionResult:
    """
    Result returned after complete workflow execution.
    
    Note: This dataclass was extracted from the deprecated TodoExecutionEngine but has been
    adapted for the tool-enhanced execution mode. The execution_results field now contains
    raw tool execution results (List[Dict[str, Any]]) rather than TodoExecutionResult objects.
    
    Previously named: execution_result in TodoExecutionEngine
    """
    original_prompt: str
    execution_results: List[Dict[str, Any]]  # Raw tool results from tool-enhanced execution
    total_execution_duration: float
    todos_completed: int
    todos_failed: int
    overall_success: bool
    error_message: str = ""
    
    # New fields for enhanced tool-based execution
    tool_execution_summary: Dict[str, Any] = field(default_factory=dict)


__all__ = ["WorkflowExecutionResult"]

