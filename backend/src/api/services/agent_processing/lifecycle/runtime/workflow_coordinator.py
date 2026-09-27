"""
Workflow Coordinator

Main orchestrator for the streamlined agent processing system. Coordinates the flow from
request analysis through service capability planning to tool-enhanced execution.

Streamlined Flow (Nov 2024):
1. RequestAnalyzer - Basic text analysis and intent interpretation
2. ServiceMethodPlanner - Service capability discovery and caching  
3. Tool Creation - Convert services to LangChain tools
4. Agent Execution - Dynamic planning and execution via LangChain agent

The agent creates execution steps dynamically - no pre-planning required.
All data retrieval and execution planning happens at runtime via tool calls.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from collections.abc import Mapping, Sequence

from ..planning.request_analyzer import RequestAnalyzer
from ...service_capabilities.service_method_planner import ServiceMethodPlanner, ServiceCapabilityCache
from .checkpoint_workflow_service import WorkflowCheckpointWorkflowService
from .session_context_service import WorkflowSessionContextService
from .workflow_status_notifier import WorkflowStatusNotifier
from .workflow_results import WorkflowExecutionResult
from ..execution_graph.tool_run_watchdog import get_tool_run_registry

# LangGraph integration imports
try:
    from ..execution_graph.agent_graph_runtime import execute_tool_enhanced_workflow
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

logger = logging.getLogger(__name__)


class WorkflowCoordinator:
    """
    Coordinates the streamlined agent processing pipeline.
    
    Manages the flow from request analysis through service capability planning
    to tool-enhanced execution. The agent creates execution steps dynamically.
    """
    
    def __init__(self, service_capability_analyzer=None, service_execution_engine=None, llm_model=None, websocket_manager=None, agent_task_submission_service=None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Store initialization parameters for lazy loading
        self._provided_llm_model = llm_model
        self._llm_model = None
        self._service_capability_analyzer = service_capability_analyzer
        self._service_execution_engine = service_execution_engine
        self._websocket_manager = websocket_manager
        self._agent_task_submission_service = agent_task_submission_service

        # Initialize workflow status notifier
        self.logger.info(f"🔧 WorkflowCoordinator initializing with websocket_manager: {self._websocket_manager is not None}")
        self.status_notifier = WorkflowStatusNotifier(self._websocket_manager)
        
        # Initialize context and checkpoint workflow services.
        self.session_context_service = WorkflowSessionContextService(
            status_notifier=self.status_notifier,
        )
        self.checkpoint_workflow_service = WorkflowCheckpointWorkflowService(
            websocket_manager=self._websocket_manager,
            status_notifier=self.status_notifier,
        )
        self.checkpoint_workflow_service.workflow_coordinator = self
        
        # Initialize component pipeline (LLM model will be set lazily)
        self.request_analyzer = RequestAnalyzer()
        self.service_method_planner = ServiceMethodPlanner(service_capability_analyzer)
    


    async def _ensure_services_initialized(self):
        """Initialize real services like the original MultiStepAgent does."""
        if self._service_capability_analyzer is None:
            # Initialize email service
            try:
                from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import EmailClientService
                email_service = EmailClientService()
                await email_service.initialize()
                self.logger.info("✅ Email service initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize email service: {e}")
                email_service = None
            
            # Initialize file system service (additive wiring; analyzer support added next)
            try:
                from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import FileSystemService
                file_service = FileSystemService()
                await file_service.initialize()
                self.logger.info("✅ File system service initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize file system service: {e}")
                file_service = None
            
            # Initialize shell service (secure non-interactive CLI execution)
            try:
                from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
                shell_service = ShellService(websocket_manager=self._websocket_manager)
                await shell_service.initialize()
                self.logger.info("✅ Shell service initialized with approval support")
            except Exception as e:
                self.logger.error(f"Failed to initialize shell service: {e}")
                shell_service = None
            
            # Initialize AppleScript service
            try:
                from ...tools.direct_application_interactions.applescript_automation.generic_applescript_service import GenericAppleScriptService
                from api.dependencies import get_sqlite_knowledge_service
                applescript_knowledge_service = get_sqlite_knowledge_service()
                applescript_service = GenericAppleScriptService(knowledge_service=applescript_knowledge_service, websocket_manager=self._websocket_manager)
                self.logger.info("✅ AppleScript service initialized with approval support")
            except Exception as e:
                self.logger.error(f"Failed to initialize AppleScript service: {e}")
                applescript_service = None
            
            # Create service capability analyzer with real services
            from ...service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
            self._service_capability_analyzer = ServiceCapabilityAnalyzer(
                email_service=email_service,
                router=None,  # Router removed - agent tasks route directly to agent
                file_service=file_service,
                applescript_service=applescript_service,
                shell_service=shell_service
            )
            
            # Create service execution engine
            from ...service_capabilities.service_execution_engine import ServiceExecutionEngine
            self._service_execution_engine = ServiceExecutionEngine(self._service_capability_analyzer)
            
            # Register services with execution engine
            if email_service:
                self._service_execution_engine.register_service("email_service", email_service)
            if file_service:
                self._service_execution_engine.register_service("file_service", file_service)
            if applescript_service:
                self._service_execution_engine.register_service("applescript_service", applescript_service)
            if shell_service:
                self._service_execution_engine.register_service("shell_service", shell_service)
            
            # Update service method planner
            self.service_method_planner = ServiceMethodPlanner(self._service_capability_analyzer)
            
            self.logger.info("✅ All services initialized")

    async def _ensure_llm_components_initialized(self, context: Dict[str, Any] = None):
        """Ensure LLM-dependent components are initialized."""
        if self._llm_model is None:
            if self._provided_llm_model is not None:
                self._llm_model = self._provided_llm_model
            else:
                model_id = context.get("model_id") if context else None
                self._llm_model = await self._get_reasoning_model(explicit_model_id=model_id)
        
        # Hard-ensure the model is actually loaded before any component uses it.
        # In some test/integration paths a model instance can be constructed but not READY yet.
        try:
            if hasattr(self._llm_model, "is_loaded") and not self._llm_model.is_loaded:
                self.logger.info("🔧 LLM model instance present but not loaded; loading now for planning/execution")
                await self._llm_model.load()
        except Exception as e:
            self.logger.error(f"Failed to load LLM model before initializing components: {e}")
            raise
                
        # Initialize LLM-dependent components if not already done
        # Update request_analyzer with LLM model for intelligent interpretation
        self.request_analyzer.llm_model = self._llm_model
    
    async def _get_reasoning_model(self, explicit_model_id: Optional[str] = None):
        """Get LLM model for reasoning/planning following existing patterns.
        
        Requires FUNCTION_CALLING support since the agent pipeline uses tool calls.
        If the user's preferred model lacks this feature, a ValueError is raised
        immediately before the model is even loaded.
        
        Args:
            explicit_model_id: If provided, overrides the user's default reasoning model preference.
        """
        try:
            from api.dependencies import get_model_usage_service
            from api.core.models.model_types import ModelCapability
            from api.core.models.models_registry.schema import ModelFeature
            
            model_usage_service = get_model_usage_service()
            
            model = await model_usage_service.get_model_for_task(
                capabilities={ModelCapability.REASONING},
                explicit_model_id=explicit_model_id,
                required_features={ModelFeature.FUNCTION_CALLING}
            )
            
            if not model:
                raise Exception("No suitable model found for workflow planning")
            
            return model
            
        except Exception as e:
            self.logger.error(f"Failed to get reasoning model: {e}")
            raise
        
    async def execute_complete_workflow(
        self, 
        user_agent_task: str, 
        context: Dict[str, Any], 
        agent_task_id: Optional[str] = None
    ) -> WorkflowExecutionResult:
        """
        Single entry point for complete workflow execution.
        
        Uses LangGraph with LangChain Tools integration for all workflow execution.
        This is the only supported execution mode after deprecation of legacy paths.
        
        Args:
            user_agent_task: The user's agent task to process
            context: Additional context information
            agent_task_id: Optional AgentTask ID for tracking status updates
            
        Returns:
            WorkflowExecutionResult with complete workflow results
        """
        try:
                    return await self._execute_with_tools(user_agent_task, context, agent_task_id)
            
        except Exception as e:
            self.logger.error(f"Complete workflow execution failed: {e}")
            # Send error status update
            await self.status_notifier.send_status_update("Workflow failed", f"Error: {str(e)}")
            
            # Return failed result using the actual dataclass signature
            # WorkflowExecutionResult is now defined in this file
            return WorkflowExecutionResult(
                original_prompt=user_agent_task,
                execution_results=[],
                total_execution_duration=0.0,
                todos_completed=0,
                todos_failed=1,
                overall_success=False,
            )

    # Utility methods for cache management
    def get_capability_cache(self) -> Optional[ServiceCapabilityCache]:
        """Get the current service capability cache."""
        return self.service_method_planner.get_cached_capabilities()
    
    def invalidate_capability_cache(self):
        """Invalidate the service capability cache to force re-discovery."""
        self.service_method_planner.invalidate_cache()
    
    def is_capability_cache_valid(self, max_age_seconds: int = 300) -> bool:
        """Check if the current capability cache is still valid."""
        return self.service_method_planner.is_cache_valid(max_age_seconds)
    
    async def refresh_capabilities_if_needed(self, max_age_seconds: int = 300):
        """Refresh service capabilities if the cache is too old."""
        if not self.is_capability_cache_valid(max_age_seconds):
            self.logger.info("🔄 REFRESHING STALE CAPABILITY CACHE")
            await self.service_method_planner.plan_service_capabilities()
    
    async def resume_workflow(
        self,
        agent_task_id: str,
        user_response: str,
        context: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecutionResult:
        """
        Resume a paused workflow after receiving user response to a checkpoint.
        
        Delegates to the checkpoint workflow service for actual implementation.
        
        Args:
            agent_task_id: The AgentTask ID (used as thread_id for LangGraph)
            user_response: User's response to the checkpoint prompt
            context: Optional additional context to pass to the resumed workflow
            
        Returns:
            WorkflowExecutionResult with the final execution results
        """
        return await self.checkpoint_workflow_service.resume_workflow(
            agent_task_id=agent_task_id,
            user_response=user_response,
            context=context
        )

    async def resume_workflow_after_provider_delegation(
        self,
        *,
        parent_agent_task_id: str,
        child_outcomes: Sequence[Mapping[str, object]],
    ) -> WorkflowExecutionResult:
        """Resume one primary workflow from every settled delegated-child outcome."""
        return await self.checkpoint_workflow_service.resume_workflow_after_provider_delegation(
            parent_agent_task_id=parent_agent_task_id,
            child_outcomes=child_outcomes,
        )

    async def resume_workflow_for_delegated_supervision(
        self,
        *,
        parent_agent_task_id: str,
        delegated_agent_run: Mapping[str, object],
        report_card: Mapping[str, object],
    ) -> WorkflowExecutionResult:
        """Resume one paused parent so it may supervise a live ACP child turn."""
        return await self.checkpoint_workflow_service.resume_workflow_for_delegated_supervision(
            parent_agent_task_id=parent_agent_task_id,
            delegated_agent_run=delegated_agent_run,
            report_card=report_card,
        )

    async def _execute_with_tools(self, user_agent_task: str, context: Dict[str, Any], agent_task_id: Optional[str]) -> WorkflowExecutionResult:
        """Execute workflow using LangGraph with LangChain Tools integration."""
        if not LANGGRAPH_AVAILABLE:
            self.logger.error("🚫 LangGraph is required for workflow execution")
            raise RuntimeError("LangGraph dependencies are not available. Please install langgraph and related packages.")
        
        self.logger.info(f"🔧 Using TOOL-ENHANCED execution for: {user_agent_task}")
        
        # Enrich context with recent session history for natural continuations (Phase 3.3 & 3.4)
        context = await self.session_context_service.enrich_context_with_session_history(
            user_agent_task, 
            context,
            agent_task_id=agent_task_id
        )

        # Graph nodes resolve their run coordinator from context. Seed this
        # instance so model/service state initialized here is reused throughout
        # the run instead of constructing a fresh, uninitialized coordinator.
        context["_workflow_coordinator"] = self
        
        # CRITICAL: Add agent_task_id to context for progress tracking
        # The agent execution node needs this to attach LiveProgressCallbackHandler
        if agent_task_id:
            context["agent_task_id"] = agent_task_id
            self.status_notifier.set_agent_task_id(agent_task_id)
            root_task_id = context.get("root_task_id")
            previous_task_id = context.get("previous_task_id")
            if root_task_id or previous_task_id:
                self.status_notifier.set_chain_identity(root_task_id=root_task_id, previous_task_id=previous_task_id)
            # Propagate to ShellService so approval broadcasts include agent_task_id
            shell_svc = self._service_execution_engine.get_service("shell_service") if self._service_execution_engine else None
            if shell_svc and hasattr(shell_svc, '_agent_task_id'):
                shell_svc._agent_task_id = agent_task_id
            # Propagate to AppleScriptService so approval broadcasts include agent_task_id
            applescript_svc = self._service_execution_engine.get_service("applescript_service") if self._service_execution_engine else None
            if applescript_svc and hasattr(applescript_svc, '_agent_task_id'):
                applescript_svc._agent_task_id = agent_task_id
            self.logger.info(f"🔧 DEBUG: Added agent_task_id to context: {agent_task_id}")
        
        # Send status update
        await self.status_notifier.send_status_update("Starting tool-enhanced workflow", f"Processing: {user_agent_task}")
        
        try:
            # Execute using tool-enhanced LangGraph pipeline
            self.logger.info(f"🔧 DEBUG: About to call execute_tool_enhanced_workflow with agent task: {user_agent_task}")
            
            # Try to execute - may be interrupted by checkpoint request
            try:
                workflow_wallclock_limit = float(context.get("workflow_wallclock_limit_seconds") or 1500)
                from ..execution_graph.workflow_deadline import WorkflowDeadline
                context["_workflow_deadline"] = WorkflowDeadline.start(
                    total_seconds=workflow_wallclock_limit,
                    finalization_reserve_seconds=float(context.get("finalization_reserve_seconds") or 60),
                )
                tool_results = await asyncio.wait_for(
                    execute_tool_enhanced_workflow(user_agent_task, context),
                    timeout=workflow_wallclock_limit,
                )
                self.logger.info(f"🔧 DEBUG: execute_tool_enhanced_workflow returned: {type(tool_results)} | keys={list(tool_results.keys()) if isinstance(tool_results, dict) else 'n/a'}")
            except asyncio.TimeoutError:
                if agent_task_id:
                    get_tool_run_registry().clear_agent_task(agent_task_id)
                timeout_message = (
                    "Tool-enhanced workflow exceeded the final wall-clock safety guard. "
                    "Active tool progress was reconciled and the task should be retried or narrowed."
                )
                self.logger.error(timeout_message)
                await self.status_notifier.send_status_update(
                    "Tool-enhanced workflow timed out",
                    timeout_message,
                )
                raise TimeoutError(timeout_message)
            except Exception as tool_exec_error:
                # Check if this is a checkpoint request
                if self.checkpoint_workflow_service.is_checkpoint_request(tool_exec_error):
                    self.logger.info(f"🛑 Agent requested checkpoint: {tool_exec_error}")
                    await self.checkpoint_workflow_service.handle_checkpoint_request(
                        tool_exec_error,
                        agent_task_id,
                        user_agent_task,
                    )
                    # Return a special result indicating checkpoint reached
                    return self.checkpoint_workflow_service.create_checkpoint_pending_result(user_agent_task)
                else:
                    # Not a checkpoint, re-raise
                    raise

            # Thread final_envelope through unchanged for downstream consumers (router)
            final_env = None
            try:
                if isinstance(tool_results, dict):
                    final_env = tool_results.get('final_envelope')
                    if isinstance(final_env, dict):
                        files = (final_env.get('result_payload') or {}).get('files') or []
                        self.logger.info(f"🧪 FINALIZER PASS-THROUGH: envelope present; files_count={len(files)}")
                    else:
                        self.logger.info("🧪 FINALIZER PASS-THROUGH: no envelope present in tool_results")
            except Exception as _fe:
                self.logger.info(f"🧪 FINALIZER PASS-THROUGH: error while inspecting tool_results: {_fe}")
            
            # Convert tool results to WorkflowExecutionResult format
            workflow_result = self._convert_tool_results_to_workflow_result(tool_results, user_agent_task)

            # Attach final_envelope attribute so callers can propagate it
            try:
                setattr(workflow_result, 'final_envelope', final_env)
                self.logger.info(f"🧪 FINALIZER PASS-THROUGH: attached to WorkflowExecutionResult: has_envelope={isinstance(final_env, dict)}")
            except Exception as _seterr:
                self.logger.info(f"🧪 FINALIZER PASS-THROUGH: failed to attach to result: {_seterr}")

            # Surface which model actually answered when the preferred reasoning
            # model was unreachable before any response (agent_graph_nodes.py sets
            # this on the same context dict during the one-time local fallback).
            fallback_model_used = context.get("reasoning_fallback_model_used")
            if fallback_model_used:
                try:
                    setattr(workflow_result, 'reasoning_fallback_model_used', fallback_model_used)
                except Exception as _seterr:
                    self.logger.info(f"Failed to attach reasoning_fallback_model_used to result: {_seterr}")
            
            self.logger.info(f"✅ Tool-enhanced workflow finished: {workflow_result.todos_completed} todos completed")
            
            # Check if workflow is waiting for user input (checkpoint)
            needs_user_input = any(
                result.get('needs_user_input', False) 
                for result in workflow_result.execution_results
            )
            
            if needs_user_input:
                self.logger.info("🤝 Workflow is awaiting user input - skipping completion status update")
            else:
                # Save to session context for natural continuations
                self.session_context_service.save_agent_task_to_session_context(
                    user_agent_task, workflow_result, agent_task_id=agent_task_id
                )
                
                # Send completion status only if not waiting for user input
                executed_tool_call_count = len(tool_results.get('tool_execution_results', []))
                await self.status_notifier.send_status_update(
                    "Tool-enhanced workflow completed", 
                    f"Used {executed_tool_call_count} tool calls, completed {workflow_result.todos_completed} todos"
                )
            
            return workflow_result
            
        except Exception as e:
            self.logger.error(f"Tool-enhanced execution failed: {e}")
            await self.status_notifier.send_status_update("Tool-enhanced workflow failed", f"Error: {str(e)}")
            raise

    def _convert_tool_results_to_workflow_result(self, tool_results: Dict[str, Any], original_prompt: str) -> WorkflowExecutionResult:
        """Convert tool-enhanced execution results to standard WorkflowExecutionResult format."""
        # Extract key metrics from tool results
        steps_completed = tool_results.get('steps_completed', 0)
        steps_failed = tool_results.get('steps_failed', 0)
        success_rate = tool_results.get('success_rate', 0.0)
        tool_execution_results = tool_results.get('tool_execution_results', [])
        
        # Convert to WorkflowExecutionResult format
        return WorkflowExecutionResult(
            original_prompt=original_prompt,
            execution_results=tool_execution_results,
            total_execution_duration=0.0,  # Tool results don't currently track this
            todos_completed=steps_completed,
            todos_failed=steps_failed,
            overall_success=success_rate > 0.5 if steps_completed > 0 else True
        ) 
    
