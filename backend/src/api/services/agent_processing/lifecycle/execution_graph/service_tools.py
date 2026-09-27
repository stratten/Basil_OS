"""
LangChain Tool Wrappers for Basil Services

This module converts existing Basil services into formal LangChain Tools using the proper
factory pattern with @tool decorators. This enables seamless integration with LangGraph's
tool calling patterns while preserving all existing service functionality.

Key responsibilities:
1. Generate Tool wrappers from ServiceCapabilityAnalyzer outputs using factory pattern
2. Wrap service method calls using LangChain's @tool decorator
3. Provide type-safe parameter validation with Pydantic schemas
4. Enable tool composition and chaining
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

from api.core.models.reasoning.model_runtime_profile import RuntimeModelProfile

from ...service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from ...service_capabilities.service_execution_engine import ServiceExecutionEngine
from .service_tooling.memory_tools import create_memory_tools
from .service_tooling.models import (
    BaseModel,
    BaseTool,
    LANGCHAIN_AVAILABLE,
    ToolCreationResult,
)
from .service_tooling.optional_tool_registry import register_optional_tools
from .service_tooling.progress_metadata import (
    generate_progress_metadata,
    generate_tool_description,
)
from .service_tooling.schema_generation import (
    convert_type_string_to_python_type,
    create_input_model,
    get_explicit_input_model,
)
from .service_tooling.skill_tools import create_skill_tools
from .service_tooling.tool_execution import create_tool_function
from .service_tooling.tool_input_normalization import normalize_structured_tool_args_schemas

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolMethodBlueprint:
    """Conversation-agnostic tool definition before per-turn closure binding."""

    service_name: str
    method_name: str
    tool_name: str
    description: str
    input_model: Type[BaseModel]
    progress_metadata: Dict[str, str]

    @property
    def map_key(self) -> str:
        return f"{self.service_name}.{self.method_name}"


def build_tool_method_blueprints(
    services: Dict[str, Any],
    profile: Optional[RuntimeModelProfile] = None,
) -> Dict[str, ToolMethodBlueprint]:
    """Build cacheable tool blueprints (schemas/descriptions) without live bindings."""
    blueprints: Dict[str, ToolMethodBlueprint] = {}
    for service_name, service_info in services.items():
        capabilities = service_info.get("capabilities", {})
        methods = capabilities.get("supported_methods", capabilities.get("methods", {}))
        execution_principles = capabilities.get("execution_principles", [])

        for method_name, method_info in methods.items():
            # Per-method fault isolation mirrors the pre-P5 _create_tools_for_service
            # loop: a single method whose schema/description cannot be generated is
            # skipped with a warning, never aborting blueprint construction for the
            # rest of the surface.
            try:
                tool_name = f"{service_name}_{method_name}"
                description = generate_tool_description(
                    service_name,
                    method_name,
                    method_info,
                    execution_principles,
                    profile=profile,
                )
                input_model = get_explicit_input_model(service_name, method_name)
                if input_model is None:
                    input_model = create_input_model(tool_name, method_info)
                progress_metadata = generate_progress_metadata(
                    service_name, method_name, method_info
                )
                blueprint = ToolMethodBlueprint(
                    service_name=service_name,
                    method_name=method_name,
                    tool_name=tool_name,
                    description=description,
                    input_model=input_model,
                    progress_metadata=progress_metadata,
                )
                blueprints[blueprint.map_key] = blueprint
            except Exception as e:
                logger.warning(f"   ⚠️ Skipped blueprint {service_name}.{method_name}: {str(e)}")
    return blueprints


class ServiceToolFactory:
    """
    Factory for creating LangChain Tools from Basil services using the proper @tool decorator pattern.

    This factory creates tools using LangChain's recommended approach with closures to capture
    service dependencies, ensuring full compatibility with LangGraph and other LangChain components.
    """

    # Default context window for models (200K is common for Claude models)
    DEFAULT_CONTEXT_TOKENS = 200000

    # Reserve 10% of context for a single tool output (allows multiple tool calls + system prompt + user input)
    TOOL_OUTPUT_CONTEXT_FRACTION = 0.10

    # Approximate characters per token (conservative estimate)
    CHARS_PER_TOKEN = 4

    def __init__(self, service_execution_engine: ServiceExecutionEngine,
                 capability_analyzer: ServiceCapabilityAnalyzer,
                 max_context_tokens: int = None,
                 profile: Optional[RuntimeModelProfile] = None,
                 current_root_task_id: Optional[str] = None,
                 current_agent_task_id: Optional[str] = None,
                 current_conversation_id: Optional[str] = None,
                 agent_task_submission_service: Any = None,
                 allow_provider_catalog: bool = True,
                 allow_delegated_agent: bool = True,
                 allow_child_interaction_tools: bool = True,
                 todo_service: Any = None):
        self.service_execution_engine = service_execution_engine
        self.capability_analyzer = capability_analyzer
        self.profile = profile
        # Chain root for the in-flight task, so recall_agent_tasks can read the
        # current thread without the model having to know its own id.
        self.current_root_task_id = current_root_task_id
        # Current turn id, so recall_agent_tasks(scope='screen') can read the
        # screen text captured for THIS task without the model knowing its id.
        self.current_agent_task_id = current_agent_task_id
        # Conversation thread id for recall_conversations(scope='current_thread').
        self.current_conversation_id = current_conversation_id
        self.agent_task_submission_service = agent_task_submission_service
        self.allow_provider_catalog = bool(allow_provider_catalog)
        self.allow_delegated_agent = bool(allow_delegated_agent)
        self.allow_child_interaction_tools = bool(allow_child_interaction_tools)
        self.todo_service = todo_service
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.tool_error_log: List[Dict[str, str]] = []
        self.file_read_log: List[Dict[str, str]] = []

        # Set context-aware output limits
        context_tokens = max_context_tokens or self.DEFAULT_CONTEXT_TOKENS
        self.max_context_tokens = context_tokens

        # Calculate max tool output: 10% of context window in characters
        # e.g., 200K tokens → 20K tokens → 80K chars per tool output
        self.max_tool_output_chars = int(context_tokens * self.TOOL_OUTPUT_CONTEXT_FRACTION * self.CHARS_PER_TOKEN)

        self.logger.info(
            f"🔧 ServiceToolFactory initialized: context={context_tokens:,} tokens, "
            f"max_tool_output={self.max_tool_output_chars:,} chars (~{int(self.max_tool_output_chars / self.CHARS_PER_TOKEN):,} tokens)"
        )

        if not LANGCHAIN_AVAILABLE:
            raise RuntimeError("LangChain is not available. Please install langchain-core to use Tool integration.")

    def create_tools_from_services(self, services: Dict[str, Any]) -> ToolCreationResult:
        """
        Create LangChain Tools from service capability data.

        Args:
            services: Service capability data from ServiceCapabilityAnalyzer

        Returns:
            ToolCreationResult with created tools and any errors
        """
        tools = []
        tool_map = {}
        errors = []
        optional_warnings: List[str] = []

        self.logger.info(f"🔧 CREATING TOOLS from {len(services)} services")

        for service_name, service_info in services.items():
            try:
                service_tools = self._create_tools_for_service(service_name, service_info)
                tools.extend(service_tools)

                # Build tool map for quick lookup
                for tool_item in service_tools:
                    method_key = tool_item.name.removeprefix(f"{service_name}_")
                    tool_key = f"{service_name}.{method_key}"
                    tool_map[tool_key] = tool_item

                self.logger.info(f"   ✅ Created {len(service_tools)} tools for {service_name}")

            except Exception as e:
                error_msg = f"Failed to create tools for {service_name}: {str(e)}"
                errors.append(error_msg)
                self.logger.error(f"   ❌ {error_msg}")

        return self._finalize_tool_creation(tools, tool_map, errors, optional_warnings)

    def create_tools_from_blueprints(
        self,
        services: Dict[str, Any],
        blueprints: Dict[str, ToolMethodBlueprint],
    ) -> ToolCreationResult:
        """Bind pre-built blueprints to this turn's live execution engine."""
        tools = []
        tool_map = {}
        errors = []
        optional_warnings: List[str] = []

        self.logger.info(
            f"🔧 BINDING TOOLS from {len(blueprints)} cached blueprints "
            f"across {len(services)} services"
        )

        # Error-handling parity with create_tools_from_services: only a
        # catastrophic per-SERVICE failure is recorded in `errors` (a populated
        # errors list makes _node_execute_todos_with_tools abort the turn).
        # Per-method issues -- a method skipped during blueprint construction, or a
        # bind failure -- are silently omitted like the pre-P5 per-method skip, so
        # one bad method never kills the whole tool surface.
        for service_name, service_info in services.items():
            try:
                capabilities = service_info.get("capabilities", {})
                methods = capabilities.get("supported_methods", capabilities.get("methods", {}))
                for method_name in methods:
                    map_key = f"{service_name}.{method_name}"
                    blueprint = blueprints.get(map_key)
                    if blueprint is None:
                        self.logger.debug(f"   ⚠️ No blueprint for {map_key}; skipping")
                        continue
                    try:
                        tool_item = self._bind_tool_from_blueprint(blueprint)
                        tools.append(tool_item)
                        tool_map[map_key] = tool_item
                    except Exception as e:
                        self.logger.warning(f"   ⚠️ Skipped {map_key}: {str(e)}")
            except Exception as e:
                error_msg = f"Failed to create tools for {service_name}: {str(e)}"
                errors.append(error_msg)
                self.logger.error(f"   ❌ {error_msg}")

        return self._finalize_tool_creation(tools, tool_map, errors, optional_warnings)

    def _finalize_tool_creation(
        self,
        tools: List[BaseTool],
        tool_map: Dict[str, BaseTool],
        errors: List[str],
        optional_warnings: List[str],
    ) -> ToolCreationResult:
        # Note: failure_analyzer_analyze tool has been removed (IntelligentFailureAnalyzer deprecated)
        # Agent's built-in reasoning handles failures better than a separate analyzer tool
        register_optional_tools(self, tools, tool_map, optional_warnings)
        tools = normalize_structured_tool_args_schemas(tools)

        self.logger.info(
            f"🔧 TOOL CREATION COMPLETE: {len(tools)} tools created, "
            f"{len(errors)} errors, {len(optional_warnings)} optional warnings"
        )

        return ToolCreationResult(
            tools=tools,
            tool_map=tool_map,
            errors=errors,
            tool_error_log=self.tool_error_log,
            file_read_log=self.file_read_log,
            optional_warnings=optional_warnings,
        )

    def _bind_tool_from_blueprint(self, blueprint: ToolMethodBlueprint) -> BaseTool:
        return self._create_tool_function(
            blueprint.tool_name,
            blueprint.description,
            blueprint.input_model,
            blueprint.service_name,
            blueprint.method_name,
            blueprint.progress_metadata,
        )

    def _create_tools_for_service(self, service_name: str, service_info: Dict[str, Any]) -> List[BaseTool]:
        """Create LangChain Tools for all methods in a service."""
        tools = []
        capabilities = service_info.get("capabilities", {})
        # Try both "supported_methods" (AppleScript) and "methods" (other services) for compatibility
        methods = capabilities.get("supported_methods", capabilities.get("methods", {}))
        execution_principles = capabilities.get("execution_principles", [])

        for method_name, method_info in methods.items():
            try:
                tool_item = self._create_tool_for_method(
                    service_name, method_name, method_info, execution_principles
                )
                tools.append(tool_item)
            except Exception as e:
                self.logger.warning(f"   ⚠️ Skipped {service_name}.{method_name}: {str(e)}")

        return tools

    def _create_memory_tools(self) -> List[BaseTool]:
        """Create explicit LangChain tools for Basil working memory."""
        return create_memory_tools(profile=self.profile)

    def _create_skill_tools(self) -> List[BaseTool]:
        """Create explicit LangChain tools for saved skill discovery and loading."""
        return create_skill_tools(profile=self.profile)

    def _create_tool_for_method(self, service_name: str, method_name: str,
                               method_info: Dict[str, Any], execution_principles: List[str]) -> BaseTool:
        """Create a single LangChain Tool for a service method using the proper @tool decorator pattern."""

        # Generate tool name and description
        tool_name = f"{service_name}_{method_name}"
        description = self._generate_tool_description(service_name, method_name, method_info, execution_principles)

        # Use explicit contracts for high-risk write tools; keep dynamic schemas elsewhere.
        input_model = self._get_explicit_input_model(service_name, method_name)
        if input_model is None:
            input_model = self._create_input_model(tool_name, method_info)

        # Generate progress templates for this tool
        progress_metadata = self._generate_progress_metadata(service_name, method_name, method_info)

        # Create the tool function using closure pattern to capture dependencies
        return self._create_tool_function(tool_name, description, input_model, service_name, method_name, progress_metadata)

    def _generate_tool_description(self, service_name: str, method_name: str,
                                  method_info: Dict[str, Any], execution_principles: List[str]) -> str:
        """Generate a comprehensive description for the tool."""
        return generate_tool_description(
            service_name,
            method_name,
            method_info,
            execution_principles,
            profile=self.profile,
        )

    def _get_explicit_input_model(self, service_name: str, method_name: str) -> Optional[Type[BaseModel]]:
        """Return compact explicit schemas for selected high-risk service methods."""
        return get_explicit_input_model(service_name, method_name)

    def _generate_progress_metadata(self, service_name: str, method_name: str, method_info: Dict[str, Any]) -> Dict[str, str]:
        """Generate intelligent progress templates based on service/method characteristics and parameters."""
        return generate_progress_metadata(service_name, method_name, method_info)

    def _create_input_model(self, tool_name: str, method_info: Dict[str, Any]) -> Type[BaseModel]:
        """Create a dynamic Pydantic model for tool input parameters."""
        return create_input_model(tool_name, method_info)

    def _convert_type_string_to_python_type(self, type_string: str) -> Type:
        """Convert string type annotations to Python types for Pydantic."""
        return convert_type_string_to_python_type(type_string)

    def _create_tool_function(self, tool_name: str, description: str, input_model: Type[BaseModel],
                             service_name: str, method_name: str, progress_metadata: Dict[str, str]) -> BaseTool:
        """Create a proper LangChain Tool using @tool decorator and closure pattern."""
        return create_tool_function(
            self,
            tool_name,
            description,
            input_model,
            service_name,
            method_name,
            progress_metadata,
        )


async def create_service_tools(service_execution_engine: ServiceExecutionEngine,
                        capability_analyzer: ServiceCapabilityAnalyzer,
                        services: Dict[str, Any],
                        max_context_tokens: int = None,
                        profile: Optional[RuntimeModelProfile] = None,
                        current_root_task_id: Optional[str] = None,
                        current_agent_task_id: Optional[str] = None,
                        current_conversation_id: Optional[str] = None,
                        agent_task_submission_service: Any = None,
                        turn_timing: Any = None,
                        allow_provider_catalog: bool = True,
                        allow_delegated_agent: bool = True,
                        allow_child_interaction_tools: bool = True) -> ToolCreationResult:
    """
    Convenience function to create LangChain Tools from Basil services.

    Args:
        service_execution_engine: Engine for executing service methods
        capability_analyzer: Analyzer for service capabilities
        services: Service capability data
        max_context_tokens: Optional context window size for the LLM model.
                           Used to calculate max tool output size (10% of context).
                           Defaults to 200K tokens if not provided.
        profile: Optional RuntimeModelProfile carrying the active tool_rendering value.
                 When the profile selects a slim rendering mode, every tool's factory
                 uses its hand-authored slim companion (description / args_schema)
                 instead of the full form.
        turn_timing: Optional TurnTiming for P5/P6 sub-span telemetry.
        allow_provider_catalog: Whether the provider catalog may be included in this workflow pass. Delegated-provider continuations pass False after one child outcome has been claimed.
        allow_delegated_agent: Whether this AgentTask may create a delegated child AgentTask.
        allow_child_interaction_tools: Whether this AgentTask may request user input or load parent-context recall tools.

    Returns:
        ToolCreationResult with created tools
    """
    from ..runtime.warm_artifact_cache import (
        compute_environment_signature,
        get_warm_artifact_cache,
    )

    factory = ServiceToolFactory(
        service_execution_engine,
        capability_analyzer,
        max_context_tokens,
        profile=profile,
        current_root_task_id=current_root_task_id,
        current_agent_task_id=current_agent_task_id,
        current_conversation_id=current_conversation_id,
        agent_task_submission_service=agent_task_submission_service,
        allow_provider_catalog=allow_provider_catalog,
        allow_delegated_agent=allow_delegated_agent,
        allow_child_interaction_tools=allow_child_interaction_tools,
    )
    try:
        from api.dependencies import get_todo_service
        factory.todo_service = get_todo_service()
    except Exception:
        factory.todo_service = None

    tool_rendering = getattr(profile, "tool_rendering", "full_schema") if profile else "full_schema"
    service_names = tuple(sorted(services.keys()))
    signature = compute_environment_signature(
        model_id="",
        tool_rendering=str(tool_rendering or "full_schema"),
        available_service_names=service_names,
    )

    async def _build_blueprints():
        if turn_timing is not None:
            turn_timing.start("tool_blueprint_gen")
        try:
            return build_tool_method_blueprints(services, profile=profile)
        finally:
            if turn_timing is not None:
                turn_timing.stop("tool_blueprint_gen")

    blueprints, was_hit = await get_warm_artifact_cache().get_or_build(
        key="tool_method_blueprints",
        signature=signature,
        builder=_build_blueprints,
    )
    logger.info(
        "create_tools blueprint-cache %s blueprints=%s",
        "HIT" if was_hit else "MISS",
        len(blueprints),
    )

    if turn_timing is not None:
        turn_timing.start("tool_bind")
    try:
        return factory.create_tools_from_blueprints(services, blueprints)
    finally:
        if turn_timing is not None:
            turn_timing.stop("tool_bind")
