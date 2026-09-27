"""AgentTask refinement service for iterative agent_task improvements."""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from api.core.llm.service import LLMService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.service import AgentTaskService

logger = logging.getLogger(__name__)


class AgentTaskRefinementService:
    """
    Service for handling iterative refinement of agent tasks.
    
    Enables users to refine previous agent_task outputs by:
    1. Retrieving original agent-task context and execution parameters
    2. Analyzing refinement requests using LLM
    3. Transforming operation parameters for re-execution
    4. Tracking refinement relationships in clarifications
    """
    
    def __init__(self, agent_task_service: AgentTaskService, llm_service: LLMService):
        """Initialize the refinement service.
        
        Args:
            agent_task_service: Service for agent_task database operations
            llm_service: Service for LLM-driven parameter analysis
        """
        self.agent_task_service = agent_task_service
        self.llm_service = llm_service
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def process_refinement_request(
        self, 
        root_task_id: str, 
        refinement_request: str,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        screen_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a refinement request for a previous agent_task.
        
        Args:
            root_task_id: ID of the root task to refine
            refinement_request: User's refinement agent task
            app_name: Current active application (optional)
            window_title: Current window title (optional) 
            screen_text: Current screen context (optional)
            
        Returns:
            Dictionary containing:
            - refined_operation_params: Parameters for re-execution
            - execution_context: Context for workflow coordinator
            - refinement_metadata: Tracking information
        """
        try:
            self.logger.info(f"Processing refinement request for task {root_task_id}")
            
            # Step 1: Retrieve original agent-task context
            original_prompt = await self.agent_task_service.get_agent_task(root_task_id)
            if not original_prompt:
                raise ValueError(f"Original task {root_task_id} not found")
            
            # Step 2: Parse stored operation parameters and result data
            operation_params = json.loads(original_prompt.operation_parameters) if original_prompt.operation_parameters else {}
            result_data = json.loads(original_prompt.result_data) if original_prompt.result_data else {}
            
            # Step 3: Analyze refinement request using LLM
            refinement_analysis = await self._analyze_refinement_request(
                original_request=original_prompt.transcribed_prompt,
                original_parameters=operation_params.get("parameters", {}),
                refinement_request=refinement_request,
                result_data=result_data
            )
            
            # Step 4: Build refined operation parameters
            refined_operation_params = self._build_refined_operation_params(
                original_params=operation_params,
                refinement_analysis=refinement_analysis,
                root_task_id=root_task_id,
                refinement_request=refinement_request
            )
            
            # Step 5: Reconstruct execution context
            execution_context = self._build_execution_context(
                original_prompt=original_prompt,
                refinement_request=refinement_request,
                app_name=app_name,
                window_title=window_title,
                screen_text=screen_text,
                result_data=result_data
            )
            
            # Step 6: Create refinement metadata for tracking
            refinement_metadata = {
                "root_task_id": root_task_id,
                "refinement_request": refinement_request,
                "refinement_iteration": len(original_prompt.clarifications) + 1,
                "analysis": refinement_analysis,
                "timestamp": datetime.now().isoformat()
            }
            
            return {
                "refined_operation_params": refined_operation_params,
                "execution_context": execution_context,
                "refinement_metadata": refinement_metadata,
                "original_prompt": original_prompt
            }
            
        except Exception as e:
            self.logger.error(f"Failed to process refinement request: {e}")
            raise
    
    async def _analyze_refinement_request(
        self,
        original_request: str,
        original_parameters: Dict[str, Any],
        refinement_request: str,
        result_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Use LLM to analyze refinement request and determine parameter modifications.
        
        Args:
            original_request: Original user agent task
            original_parameters: Original operation parameters
            refinement_request: User's refinement agent task
            result_data: Results from original execution
            
        Returns:
            Dictionary with analysis results and modified parameters
        """
        # Extract artifacts from result data for context
        artifacts = self._extract_artifacts_from_result_data(result_data)
        
        prompt = f"""You are analyzing an agent_task refinement request. The user wants to modify a previous agent task's execution.

ORIGINAL AGENT TASK: {original_request}

ORIGINAL PARAMETERS:
{json.dumps(original_parameters, indent=2)}

GENERATED ARTIFACTS: {artifacts}

REFINEMENT REQUEST: {refinement_request}

Analyze what parameters need to be modified to fulfill the refinement request. Respond with JSON:

{{
    "reasoning": "explanation of what needs to change",
    "modified_parameters": {{
        // Only include parameters that need to change
        // Preserve parameter structure and types
    }},
    "preserved_artifacts": [
        // List of artifacts that should be preserved/referenced
    ],
    "action_type": "modify_existing|create_new|replace_content"
}}

Focus on minimal changes that accomplish the refinement while preserving the workflow type and structure."""

        try:
            response = await self.llm_service.generate_response(prompt)
            
            # Parse LLM response
            analysis = json.loads(response)
            
            self.logger.info(f"Refinement analysis: {analysis['reasoning']}")
            return analysis
            
        except (json.JSONDecodeError, KeyError) as e:
            self.logger.warning(f"Failed to parse LLM refinement analysis: {e}")
            # Fallback to basic parameter modification
            return {
                "reasoning": f"Simple refinement: {refinement_request}",
                "modified_parameters": {},
                "preserved_artifacts": artifacts,
                "action_type": "modify_existing"
            }
    
    def _extract_artifacts_from_result_data(self, result_data: Dict[str, Any]) -> List[str]:
        """Extract generated artifacts (files, outputs) from result data."""
        artifacts = []
        
        try:
            # Look for artifacts in workflow_result
            data = result_data.get("data", {})
            workflow_result = data.get("workflow_result", "")
            
            # Extract file paths and outputs from workflow result string
            if "sample.txt" in workflow_result:
                artifacts.append("~/Desktop/sample.txt")
            
            # Look for other common artifact patterns
            if ".txt" in workflow_result:
                # Could extract more file patterns here
                pass
            
            if "applescript_service" in workflow_result:
                artifacts.append("AppleScript execution")
                
        except Exception as e:
            self.logger.warning(f"Failed to extract artifacts: {e}")
        
        return artifacts
    
    def _build_refined_operation_params(
        self,
        original_params: Dict[str, Any],
        refinement_analysis: Dict[str, Any],
        root_task_id: str,
        refinement_request: str
    ) -> Dict[str, Any]:
        """Build refined operation parameters for re-execution."""
        
        # Start with original parameters structure
        refined_params = original_params.copy()
        
        # Merge in the modified parameters from LLM analysis
        modified_parameters = refinement_analysis.get("modified_parameters", {})
        if "parameters" in refined_params:
            refined_params["parameters"].update(modified_parameters)
        else:
            refined_params["parameters"] = modified_parameters
        
        # Update reasoning to reflect refinement context
        original_reasoning = refined_params.get("reasoning", "")
        refined_params["reasoning"] = f"Refinement of task {root_task_id}: {refinement_analysis.get('reasoning', refinement_request)}"
        
        # Add refinement context for workflow coordinator
        refined_params["refinement_context"] = {
            "root_task_id": root_task_id,
            "refinement_request": refinement_request,
            "preserved_artifacts": refinement_analysis.get("preserved_artifacts", []),
            "action_type": refinement_analysis.get("action_type", "modify_existing"),
            "original_reasoning": original_reasoning
        }
        
        # Maintain high confidence for refinements
        refined_params["confidence"] = 0.9
        
        return refined_params
    
    def _build_execution_context(
        self,
        original_prompt,
        refinement_request: str,
        app_name: Optional[str],
        window_title: Optional[str], 
        screen_text: Optional[str],
        result_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build execution context for workflow coordinator."""
        
        return {
            # Use current context if provided, otherwise fall back to original
            "active_app": app_name or original_prompt.app_name,
            "window_title": window_title or original_prompt.window_title,
            "screen_text": screen_text or original_prompt.screen_text,
            
            # Refinement-specific context
            "refinement_agent_task": refinement_request,
            "original_artifacts": self._extract_artifacts_from_result_data(result_data),
            
            # Execution lineage for tracking
            "execution_lineage": {
                "root_task_id": original_prompt.root_task_id or original_prompt.id,
                "refinement_iteration": len(original_prompt.clarifications) + 1,
                "original_prompt": original_prompt.transcribed_prompt
            },
            
            # Pass available services (will be set by caller)
            "available_services": {},
            "websocket_manager": None  # Will be set by caller
        }
    
    async def create_refinement_clarification(
        self,
        root_task_id: str,
        refinement_agent_task_id: str,
        refinement_request: str,
        execution_status: str = "processing"
    ) -> None:
        """Add a refinement entry to the parent agent task's clarifications."""
        
        clarification_entry = {
            "type": "refinement",
            "timestamp": datetime.now().isoformat(),
            "refinement_request": refinement_request,
            "refinement_agent_task_id": refinement_agent_task_id,
            "execution_status": execution_status
        }
        
        await self.agent_task_service.add_agent_task_clarification(
            agent_task_id=root_task_id,
            clarification_text=f"Refinement: {refinement_request}",
            clarification_agent_task=json.dumps(clarification_entry)
        )
        
        self.logger.info(f"Added refinement clarification to task {root_task_id}")
