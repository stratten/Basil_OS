"""
Custom LangChain output parser to inject standardized file operation messages.

This parser intercepts agent outputs and enhances them with consistent
STEP_COMPLETE messages that our UI parsing logic can reliably extract.
"""

import json
import re
import logging
from typing import Union, List, Tuple, Any
from langchain_classic.agents import AgentOutputParser
from langchain_classic.schema import AgentAction, AgentFinish

logger = logging.getLogger(__name__)


class StandardizedFileOperationParser(AgentOutputParser):
    """
    Custom LangChain output parser that injects standardized file operation messages.
    
    This parser works by:
    1. Letting the agent complete its reasoning and tool execution
    2. Analyzing the tool execution history (intermediate_steps)
    3. Injecting standardized STEP_COMPLETE messages into the final output
    4. Preserving all original agent logic while enhancing output formatting
    """
    
    def __init__(self):
        super().__init__()
        # Use private attribute to avoid Pydantic field conflicts
        self._intermediate_steps: List[Tuple[AgentAction, str]] = []
    
    def set_intermediate_steps(self, steps: List[Tuple[AgentAction, str]]):
        """Set the intermediate steps from agent execution for context."""
        self._intermediate_steps = steps
        logger.info(f"🔧 StandardizedFileOperationParser: Set {len(steps)} intermediate steps")
    
    def parse(self, llm_output: str) -> Union[AgentAction, AgentFinish]:
        """Parse agent output and inject standardized file operation messages."""
        
        # Check if this is a final answer
        if "Final Answer:" in llm_output:
            logger.info("🔧 StandardizedFileOperationParser: Processing final answer")
            
            # Extract the final answer
            final_answer = llm_output.split("Final Answer:")[-1].strip()
            
            # Inject standardized file operation messages
            enhanced_output = self._inject_standardized_messages(final_answer)
            
            logger.info(f"🔧 Enhanced output length: {len(enhanced_output)} chars")
            logger.info(f"🔧 Enhanced output preview: {enhanced_output[:200]}...")
            
            return AgentFinish(
                return_values={"output": enhanced_output},
                log=llm_output,
            )
        
        # Handle intermediate actions (tool calls) - use default parsing logic
        return self._parse_intermediate_action(llm_output)
    
    def _parse_intermediate_action(self, llm_output: str) -> AgentAction:
        """Parse intermediate agent actions using standard LangChain patterns."""
        
        # Try multiple parsing patterns for robustness
        patterns = [
            r"Action\s*\d*\s*:(.*?)\nAction\s*\d*\s*Input\s*\d*\s*:[\s]*(.*)",
            r"Action:(.*?)\nAction Input:[\s]*(.*)",
            r"Action\s*:(.*?)\nInput\s*:[\s]*(.*)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, llm_output, re.DOTALL)
            if match:
                action = match.group(1).strip()
                action_input = match.group(2).strip()
                
                # Handle JSON action input
                if action_input.startswith('{') and action_input.endswith('}'):
                    try:
                        import json
                        action_input = json.loads(action_input)
                    except json.JSONDecodeError:
                        pass  # Keep as string if not valid JSON
                
                logger.info(f"🔧 Parsed action: {action}, input: {str(action_input)[:100]}...")
                
                return AgentAction(tool=action, tool_input=action_input, log=llm_output)
        
        # If no pattern matches, raise an error
        raise ValueError(f"Could not parse LLM output: `{llm_output}`")
    
    def _inject_standardized_messages(self, original_output: str) -> str:
        """
        Inject standardized STEP_COMPLETE messages based on tool execution history.
        
        This analyzes the intermediate_steps to identify file operations and
        generates consistent STEP_COMPLETE messages that our UI parser expects.
        """
        
        if not self._intermediate_steps:
            logger.warning("🔧 No intermediate steps available for standardization")
            return original_output
        
        # Analyze tool execution history for file operations
        standardized_messages = []
        
        for i, (action, observation) in enumerate(self._intermediate_steps):
            step_num = i + 1
            
            # Add STEP_START message
            step_start = f"STEP_START: {self._generate_step_start_message(action)}"
            standardized_messages.append(step_start)
            
            # Analyze tool result for file operations
            file_operation_message = self._extract_file_operation_from_tool_result(action, observation)

            if file_operation_message:
                standardized_messages.extend(file_operation_message.split("\n"))
            else:
                # Generic step complete message
                step_complete = f"STEP_COMPLETE: {self._generate_generic_step_complete(action, observation)}"
                standardized_messages.append(step_complete)
        
        # Combine standardized messages with original output
        # Ensure original_output is a string
        if isinstance(original_output, list):
            original_output_str = str(original_output)
        else:
            original_output_str = str(original_output)
            
        if standardized_messages:
            enhanced_output = "\n".join(standardized_messages) + "\n\n" + original_output_str
            logger.info(f"🔧 Injected {len(standardized_messages)} standardized messages")
        else:
            enhanced_output = original_output_str
            logger.info("🔧 No file operations detected, using original output")
        
        return enhanced_output
    
    def _generate_step_start_message(self, action: AgentAction) -> str:
        """Generate a STEP_START message based on the action."""
        
        tool_name = action.tool.lower()
        
        if 'file' in tool_name:
            if 'create' in str(action.tool_input):
                return "Creating a new file"
            elif 'modify' in str(action.tool_input) or 'edit' in str(action.tool_input):
                return "Modifying existing file"
            elif 'delete' in str(action.tool_input):
                return "Deleting file"
            else:
                return "Performing file operation"
        elif 'applescript' in tool_name:
            return "Executing application automation"
        elif 'email' in tool_name:
            return "Processing email operation"
        else:
            return f"Using {action.tool} tool"
    
    def _extract_file_operation_from_tool_result(self, action: AgentAction, observation: str) -> str:
        """
        Render STEP_COMPLETE messages strictly from the tool's structured
        ``file_artifacts`` receipt (see ``shell_file_artifacts.verify_file_operations``
        and ``file_result_extraction.extract_files_from_steps``). Never inspects
        stdout/log text: a tool result that mentions "created" in free-form
        output is not evidence of a real file change.
        """
        if not self._is_file_capable_tool(action):
            return None

        payload = self._parse_structured_result(observation)
        if payload is None:
            return None

        artifacts = payload.get("file_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            return None

        messages = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            name = artifact.get("name") or artifact.get("file_name")
            full_path = artifact.get("full_path") or artifact.get("path")
            operation = str(artifact.get("operation") or "").strip().lower()
            if not name or not operation:
                continue
            if operation == "delete":
                messages.append(f"STEP_COMPLETE: Successfully deleted file '{name}'")
            elif operation in ("create", "modify"):
                verb = "created" if operation == "create" else "modified"
                if full_path:
                    messages.append(
                        f"STEP_COMPLETE: Successfully {verb} file '{name}' at '{full_path}'"
                    )
                else:
                    messages.append(f"STEP_COMPLETE: Successfully {verb} file '{name}'")

        return "\n".join(messages) if messages else None

    @staticmethod
    def _parse_structured_result(observation: Any):
        """Parse the tool's JSON result payload, unwrapping the common
        ``{"result": {...}}`` envelope. Returns None for anything that is not
        a parseable structured payload (never falls back to text scanning)."""
        if isinstance(observation, dict):
            payload = observation
        elif isinstance(observation, str):
            try:
                payload = json.loads(observation)
            except (json.JSONDecodeError, TypeError):
                return None
        else:
            return None
        if not isinstance(payload, dict):
            return None
        inner = payload.get("result")
        if isinstance(inner, dict):
            return inner
        return payload

    def _is_file_capable_tool(self, action: AgentAction) -> bool:
        """Return true only for tools that can plausibly mutate local files."""
        tool_name = (getattr(action, "tool", "") or "").lower()
        return any(
            marker in tool_name
            for marker in (
                "file_service",
                "file_system",
                "filesystem",
                "shell_service",
                "applescript_service",
            )
        )
    
    def _generate_generic_step_complete(self, action: AgentAction, observation: str) -> str:
        """Generate a generic STEP_COMPLETE message for non-file operations."""
        
        tool_name = action.tool
        obs_preview = str(observation)[:50] + "..." if len(str(observation)) > 50 else str(observation)
        
        if 'success' in str(observation).lower():
            return f"{tool_name} completed successfully"
        else:
            return f"{tool_name} executed"

    @property
    def _type(self) -> str:
        """Return the type of this parser."""
        return "standardized_file_operation_parser"
