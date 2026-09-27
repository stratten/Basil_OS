"""
Streamlined Agent Processing Module

This module provides a streamlined architecture for intelligent agent execution using
LangChain tools and dynamic planning.

Streamlined Architecture (Nov 2025):
- Request analysis and intent interpretation
- Service capability discovery and caching
- Tool creation from available services  
- Dynamic agent execution with LangChain
- Real-time progress tracking and checkpointing

The agent creates execution plans dynamically - no pre-planning required.
All data retrieval and execution happens at runtime via tool calls.
"""

from .lifecycle.planning.request_analyzer import RequestAnalyzer
from .service_capabilities.service_method_planner import ServiceMethodPlanner
from .service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from .service_capabilities.service_execution_engine import ServiceExecutionEngine, ExecutionResult
from .lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from .lifecycle.runtime.workflow_results import WorkflowExecutionResult

__all__ = [
    'RequestAnalyzer',
    'ServiceMethodPlanner',
    'ServiceCapabilityAnalyzer',
    'ServiceExecutionEngine',
    'ExecutionResult',
    'WorkflowExecutionResult',
    'WorkflowCoordinator'
] 