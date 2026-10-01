"""
Agent Executor Factory for LangGraph Agent Execution.

This module handles the creation of LangChain components:
- LLM detection and wrapper creation (AuthProxy vs direct API)
- Finalizer tool definition
- Agent executor configuration
"""

from __future__ import annotations

import logging
import json as _json
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from pydantic import BaseModel, Field

from api.core.logging.api_logger import api_logger
from api.core.models.reasoning.model_runtime_profile import (
    get_langchain_max_output_tokens,
    resolve_runtime_model_profile,
    select_description_for_profile,
)
from api.core.models.models_registry import (
    get_omitted_request_parameters,
    requires_responses_api,
    get_reasoning_effort_default,
    get_thinking_request_config,
)
from langchain_core.tools import StructuredTool
from langchain_classic.agents import AgentExecutor
from langchain_classic.agents.output_parsers.tools import ToolsAgentOutputParser
from langchain_classic.agents.format_scratchpad.tools import format_to_tool_messages
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from .execution_limits import AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS
from .model_errors import LLM_RETRY_EXCEPTION_TYPES
from .service_tooling.tool_input_normalization import normalize_structured_tool_args_schemas
from .service_tooling.tool_call_repetition_guard import wrap_tools_with_repetition_guard
from .system_prompts import get_agent_system_prompt

if TYPE_CHECKING:
    from .agent_progress_system import PlanningState

logger = api_logger.getChild("agent_executor_factory")


# =============================================================================
# FINALIZER TOOL INPUT SCHEMA
# =============================================================================

class FinalizeInput(BaseModel):
    """Input schema for finalize_agent_task_result tool."""
    original_prompt: Optional[str] = Field(default="", description="User's exact request")
    agent_task_id: Optional[str] = Field(default=None, description="Agent task identifier")
    active_app: Optional[str] = Field(default=None, description="Application context")
    steps: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Array of execution results")
    self_assessment: Optional[str] = Field(default=None, description="Agent's reflection on whether results match intent (REQUIRED)")
    raw_messages: Optional[List[str]] = Field(default_factory=list, description="REQUIRED - Your FULL output text (email summary, analysis, etc.) that the user will see. For content operations, this MUST contain your actual generated content, not just metadata.")
    standardized_messages: Optional[List[str]] = Field(default=None, description="Optional standardized messages")
    metrics: Optional[Dict[str, Any]] = Field(default=None, description="Optional metrics (steps_completed, steps_total, duration_ms)")
    success: Optional[bool] = Field(default=None, description="Optional success flag")


# =============================================================================
# LLM CREATION
# =============================================================================

def _build_local_model_heartbeat(
    llm_model: Any,
    websocket_manager: Any = None,
    agent_task_id: Optional[str] = None,
    root_task_id: Optional[str] = None,
    previous_task_id: Optional[str] = None,
):
    """Build a heartbeat callback that resets the idle-unload timer and sends
    streaming progress (including thinking content) for a local model.

    The closure looks up the model's registry name by identity match in the
    ModelManager's loaded-models dict, then calls touch_model to reset the
    timer.  If a websocket_manager and agent_task_id are provided it also
    broadcasts a progress update so the frontend knows the model is working.

    Callback signature: ``(tokens_generated, thinking_text, thinking_complete)``
    where ``thinking_text`` is the model's current chain-of-thought (if any)
    and ``thinking_complete`` indicates the model has finished reasoning and
    moved to action/response generation.
    """
    _notifier = None
    _iteration = [0]
    _last_thinking_complete = [True]
    _thinking_segments: List[Dict[str, Any]] = []

    def _get_notifier():
        nonlocal _notifier
        if _notifier is None and websocket_manager is not None:
            from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
            _notifier = WorkflowStatusNotifier(
                websocket_manager=websocket_manager, agent_task_id=agent_task_id,
                root_task_id=root_task_id,
                previous_task_id=previous_task_id,
            )
        return _notifier

    def _heartbeat(
        tokens_generated: int,
        thinking_text: Optional[str] = None,
        thinking_complete: bool = False,
        phase: Optional[str] = None,
    ) -> None:
        try:
            from api.dependencies import get_model_service
            mm = get_model_service().model_manager
            for name, entry in mm._models.items():
                if entry.model is llm_model:
                    mm.touch_model(name)
                    break
        except Exception:
            pass

        if websocket_manager is None or agent_task_id is None:
            return

        # Detect new thinking iteration: previous was complete, now we have new thinking
        if thinking_text and not thinking_complete and _last_thinking_complete[0]:
            _iteration[0] += 1
        _last_thinking_complete[0] = thinking_complete

        # Track thinking segments for persistence
        if thinking_text:
            if _thinking_segments and _thinking_segments[-1]["iteration"] == _iteration[0]:
                _thinking_segments[-1]["text"] = thinking_text
                _thinking_segments[-1]["is_complete"] = thinking_complete
            else:
                _thinking_segments.append({
                    "iteration": _iteration[0],
                    "text": thinking_text,
                    "is_complete": thinking_complete,
                })

        try:
            import asyncio
            from datetime import datetime

            event: Dict[str, Any] = {
                "event_type": "agent_progress_update",
                "execution_method": "dynamic_agent",
                "agent_task_id": agent_task_id,
                "timestamp": datetime.now().isoformat(),
            }
            if root_task_id:
                event["root_task_id"] = root_task_id
            if previous_task_id:
                event["previous_task_id"] = previous_task_id

            if thinking_text and not thinking_complete:
                event["message"] = f"Reasoning… (~{tokens_generated} tokens)"
                event["thinking"] = thinking_text
                event["thinking_complete"] = False
                event["thinking_iteration"] = _iteration[0]
            elif thinking_complete:
                event["message"] = f"Generating response… (~{tokens_generated} tokens)"
                event["thinking_complete"] = True
                event["thinking_iteration"] = _iteration[0]
            elif phase == "waiting_for_model":
                event["message"] = "Waiting for the local model to finish another request…"
            elif phase == "processing_prompt":
                event["message"] = "Local model is reading the prompt…"
            else:
                event["message"] = f"Local model generating… (~{tokens_generated} tokens)"

            asyncio.ensure_future(websocket_manager.broadcast(event))
        except Exception:
            pass

    _heartbeat.thinking_segments = _thinking_segments
    _heartbeat.accepts_phase = True

    return _heartbeat


def create_langchain_llm_from_model(
    llm_model: Any,
    *,
    websocket_manager: Any = None,
    agent_task_id: Optional[str] = None,
    root_task_id: Optional[str] = None,
    previous_task_id: Optional[str] = None,
) -> Any:
    """
    Create a LangChain-compatible LLM from a Basil reasoning model instance.

    Detects the model type and creates the appropriate LangChain wrapper:
    - AuthProxyModel -> AuthProxyLangChainAdapter (cloud via proxy)
    - llama.cpp local models -> LlamaCppLangChainAdapter
    - Direct OpenAI/Anthropic API keys -> ChatOpenAI / ChatAnthropic

    Args:
        llm_model: Loaded Basil reasoning model instance
        websocket_manager: Optional websocket manager for local-model heartbeats
        agent_task_id: Optional AgentTask identifier for progress updates
        root_task_id: Optional root task identifier for progress updates
        previous_task_id: Optional previous task identifier for progress updates

    Returns:
        LangChain LLM instance

    Raises:
        RuntimeError: If the model is unsupported or not loaded
    """
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI
    from .auth_proxy_langchain_adapter import create_langchain_llm_from_auth_proxy

    runtime_profile = resolve_runtime_model_profile(llm_model)
    max_out_tokens = get_langchain_max_output_tokens(runtime_profile, llm_model)

    # 1. AuthProxy check (cloud models routed through auth service)
    is_auth_proxy = (
        hasattr(llm_model, 'access_token') and
        hasattr(llm_model, 'openrouter_model_id') and
        llm_model.access_token is not None
    )

    logger.info(f"🔍 LLM model check: class={llm_model.__class__.__name__}, is_auth_proxy={is_auth_proxy}")

    if is_auth_proxy:
        langchain_llm = create_langchain_llm_from_auth_proxy(llm_model)
        logger.info(f"🤖 Using AuthProxyLangChainAdapter: {llm_model.model_name}")
        return langchain_llm

    # 2. Determine engine source from model metadata
    # NOTE: This is meta.source (runtime engine like "llama.cpp", "openai"),
    # NOT the registry "provider" field (model vendor like "qwen", "anthropic").
    engine_source = "unknown"
    try:
        meta = llm_model.get_metadata()
        engine_source = getattr(meta, "source", "unknown") or "unknown"
    except Exception:
        pass

    # 3. Local llama.cpp models — handle before api_key/model_name reads
    #    since LlamaCppModel does not have those attributes
    if engine_source.lower() == "llama.cpp":
        if not hasattr(llm_model, "llm") or llm_model.llm is None:
            model_label = llm_model.model_path.stem if hasattr(llm_model, 'model_path') and llm_model.model_path else "local model"
            raise RuntimeError(
                f"The local model ({model_label}) is not loaded. "
                f"Please ensure the model is downloaded and loaded."
            )
        from .llama_cpp_langchain_adapter import create_langchain_llm_from_llama_cpp

        heartbeat = _build_local_model_heartbeat(
            llm_model,
            websocket_manager=websocket_manager,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
        )
        # Plan B.2: pass the runtime profile so the adapter knows the active
        # tool_rendering mode at delivery time. The construction layer has
        # already chosen FULL vs SLIM description/schema; the adapter only
        # needs the profile to drive its delivery branch (B.3 will branch
        # in _generate to omit `tools=` and inject a text preamble under
        # slim_text_catalog).
        langchain_llm = create_langchain_llm_from_llama_cpp(
            llm_model,
            activity_callback=heartbeat,
            profile=runtime_profile,
            purpose="agent_execution",
        )
        langchain_llm._basil_heartbeat = heartbeat
        model_label = llm_model.model_path.stem if hasattr(llm_model, 'model_path') and llm_model.model_path else "llama.cpp"
        logger.info(
            f"🤖 Using LlamaCppLangChainAdapter (local): {model_label} "
            f"(tool_rendering={runtime_profile.tool_rendering})"
        )
        return langchain_llm

    # 4. User-defined OpenAI-compatible endpoints (Ollama, vLLM, Railway, etc.).
    #    These keep engine_source="custom" so metadata semantics stay accurate,
    #    but AgentTasks need a LangChain wrapper that uses the custom base_url
    #    and model_identifier instead of the built-in OpenAI API endpoint.
    if runtime_profile.handler == "openai_compatible":
        from .openai_compatible_langchain_adapter import (
            create_langchain_llm_from_openai_compatible,
        )

        langchain_llm = create_langchain_llm_from_openai_compatible(
            llm_model, profile=runtime_profile
        )
        logger.info(
            f"🤖 Using OpenAICompatibleLangChainAdapter (custom): "
            f"{getattr(llm_model, 'model_name', 'custom')}"
        )
        return langchain_llm

    # 5. Cloud models with user's own API keys
    api_key = getattr(llm_model, 'api_key', None)
    model_name = getattr(llm_model, 'model_name', 'unknown')
    omitted_request_parameters = set(get_omitted_request_parameters(model_name))
    sampling_kwargs: Dict[str, Any] = {}
    if "temperature" not in omitted_request_parameters:
        sampling_kwargs["temperature"] = llm_model.temperature

    if engine_source.lower() == "openai":
        openai_kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "model": model_name,
            "max_tokens": max_out_tokens,
            "streaming": True,
            "max_retries": 4,
            **sampling_kwargs,
        }
        # Registry-driven endpoint selection. Reasoning models (e.g. GPT-5.6)
        # reject function tools alongside reasoning_effort on Chat Completions;
        # LangChain only routes to the Responses API when a Responses-only arg
        # like `reasoning` is present, so force it here and pass the registry
        # reasoning effort. Non-reasoning models keep Chat Completions unchanged.
        if requires_responses_api(model_name):
            openai_kwargs["use_responses_api"] = True
            openai_kwargs["output_version"] = "responses/v1"
            effort = get_reasoning_effort_default(model_name)
            if effort and effort != "none":
                openai_kwargs["reasoning"] = {"effort": effort}
            logger.info(
                f"🤖 Using OpenAI model (direct API, Responses API): {model_name} "
                f"(reasoning_effort={openai_kwargs.get('reasoning', {}).get('effort')})"
            )
        else:
            logger.info(f"🤖 Using OpenAI model (direct API): {model_name}")
        langchain_llm = ChatOpenAI(**openai_kwargs)
        return langchain_llm

    elif engine_source.lower() == "anthropic":
        if not api_key:
            raise RuntimeError("Anthropic model selected but no API key is available")
        thinking_cfg = get_thinking_request_config(model_name)
        anthropic_kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "model": model_name,
            "max_tokens": max_out_tokens,
            "streaming": True,
            "max_retries": 4,
        }
        if thinking_cfg:
            anthropic_kwargs["thinking"] = thinking_cfg["thinking"]
            if thinking_cfg.get("effort"):
                anthropic_kwargs["effort"] = thinking_cfg["effort"]
            floor = thinking_cfg.get("max_output_tokens_with_thinking")
            if isinstance(floor, int) and floor > max_out_tokens:
                anthropic_kwargs["max_tokens"] = floor
        else:
            anthropic_kwargs.update(sampling_kwargs)
        langchain_llm = ChatAnthropic(**anthropic_kwargs)
        logger.info(
            f"🤖 Using Anthropic model (direct API): {model_name}"
            f"{' [thinking=' + thinking_cfg['thinking']['type'] + ']' if thinking_cfg else ''}"
        )
        return langchain_llm

    else:
        raise RuntimeError(
            f"AgentTasks require a model that supports tool calling. "
            f"The current model ({model_name}, engine: {engine_source}) is not supported. "
            f"Please switch to a supported model in Settings."
        )


def create_langchain_llm(coordinator: Any, agent_task_id: Optional[str] = None, root_task_id: Optional[str] = None, previous_task_id: Optional[str] = None) -> Any:
    """
    Create a LangChain-compatible LLM from the coordinator's model.

    Detects the model type and creates the appropriate LangChain wrapper:
    - AuthProxyModel -> AuthProxyLangChainAdapter (cloud via proxy)
    - llama.cpp local models -> LlamaCppLangChainAdapter
    - Direct OpenAI/Anthropic API keys -> ChatOpenAI / ChatAnthropic

    Args:
        coordinator: WorkflowCoordinator with initialized LLM model
        agent_task_id: Optional AgentTask identifier for progress updates

    Returns:
        LangChain LLM instance

    Raises:
        RuntimeError: If the model is unsupported or not loaded
    """
    return create_langchain_llm_from_model(
        coordinator._llm_model,
        websocket_manager=getattr(coordinator, "_websocket_manager", None),
        agent_task_id=agent_task_id,
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
    )


# =============================================================================
# FINALIZER TOOL CREATION
# =============================================================================

# Why this slim:
# - The finalizer tool's full description is mostly procedural prose
#   ('BEFORE calling this tool: 1...4...') and an enumeration of args
#   already visible in FinalizeInput. The agent does NOT need either at
#   construction time: the system prompt's TOOL ETIQUETTE tells it to
#   call the finalizer last, and the args schema describes the field
#   names directly.
# - KEEPS the four load-bearing facts: (a) call EXACTLY ONCE as the LAST
#   action, (b) raw_messages must contain the actual user-visible output
#   text not just metadata, (c) self_assessment is required, (d) output
#   is a strict JSON envelope (so the agent does not try to format it
#   itself). Local models in particular need (b) and (c) made explicit;
#   we have observed them stuffing tool metadata into raw_messages and
#   omitting self_assessment when these are buried in a long prose body.
# - DROPS the full input arg list (FinalizeInput renders these), the
#   reflection checklist (system prompt encodes 'check before finalize'
#   already), and the full output envelope shape (return_direct=True
#   + the schema cover this end-to-end).
FINALIZER_SLIM_DESCRIPTION = (
    "finalize_agent_task_result(...) - call EXACTLY ONCE as the LAST "
    "action of the task. raw_messages MUST contain your actual "
    "user-visible output (e.g. the email summary, the analysis, the "
    "answer) - NOT tool metadata or step lists. self_assessment is "
    "REQUIRED and is your honest reflection on whether the result "
    "matches the original prompt. Output is a strict JSON envelope; "
    "do not wrap or reformat it."
)

def _build_finalizer_evaluation_context(context: Dict[str, Any]) -> Optional[str]:
    """Build compact chain/retry context for the finalizer evaluator."""
    if not isinstance(context, dict):
        return None

    parts: List[str] = []
    root_task_id = context.get("root_task_id")
    if root_task_id:
        parts.append(f"Root task id: {root_task_id}")
    previous_task_id = context.get("previous_task_id")
    if previous_task_id:
        parts.append(f"Previous task id: {previous_task_id}")

    try:
        from ..planning.agent_context_assembler import AgentContextAssembler

        assembler = AgentContextAssembler()
        chain_context = context.get("chain_context")
        logger.info(
            "🔗 FINALIZER CHAIN CONTEXT present=%s chain_agentTasks=%s",
            isinstance(chain_context, dict) and bool(chain_context),
            len((chain_context or {}).get("chain_agentTasks") or []) if isinstance(chain_context, dict) else 0,
        )
        if isinstance(chain_context, dict) and chain_context:
            parts.append(assembler._format_chain_context(chain_context))

        retry_context = context.get("retry_context")
        if isinstance(retry_context, dict) and retry_context:
            parts.append("Retry context:\n" + assembler._format_retry_context(retry_context))
    except Exception as exc:
        logger.debug("Could not build finalizer evaluation context: %s", exc)

    rendered = "\n\n".join(part.strip() for part in parts if part and part.strip())
    if not rendered:
        return None
    return rendered[:8_000]


def create_finalizer_tool(state: "PlanningState", coordinator: Any, profile=None) -> StructuredTool:
    """
    Create the finalizer tool that the agent MUST call as its last action.

    The finalizer queries the database for the complete agent execution context,
    making it an independent, unbiased observer that can request retries if needed.

    Args:
        state: Current PlanningState with context
        coordinator: WorkflowCoordinator with LLM model
        profile: Optional RuntimeModelProfile carrying the active tool_rendering value.
                 Under a slim profile the description is swapped to
                 ``FINALIZER_SLIM_DESCRIPTION``; otherwise the full description
                 (defined inline below) flows through unchanged.

    Returns:
        StructuredTool for finalize_agent_task_result
    """
    from ..finalization.result_finalizer_tool import finalize_agent_task_result as _finalize
    
    async def _finalize_wrapper(
        original_prompt: str = "",
        agent_task_id: Optional[str] = None,
        active_app: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        self_assessment: Optional[str] = None,
        raw_messages: Optional[List[str]] = None,
        standardized_messages: Optional[List[str]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        success: Optional[bool] = None
    ) -> str:
        """Accept structured input; return strict JSON envelope as string."""

        ctx = state.context if hasattr(state, 'context') and isinstance(state.context, dict) else {}
        runtime_agent_task_id = ctx.get("agent_task_id")
        if agent_task_id and runtime_agent_task_id and agent_task_id != runtime_agent_task_id:
            logger.warning(
                "Ignoring model-supplied finalizer agent_task_id %r; using runtime agent_task_id %r",
                agent_task_id,
                runtime_agent_task_id,
            )
        agent_task_id = runtime_agent_task_id or agent_task_id

        # Resolve active_app from state context if not provided
        if not active_app:
            ctx_app = ctx.get("active_app")
            if not ctx_app:
                app_ctx = ctx.get("app_context")
                if isinstance(app_ctx, dict):
                    ctx_app = app_ctx.get("app_name")
            active_app = ctx_app
        
        # Determine if the model is local using the registry's canonical location field
        _local = False
        try:
            from api.core.models.models_registry.schema import get_model as _get_model_cfg
            _mid = ctx.get("model_id")
            if _mid:
                _cfg = _get_model_cfg(_mid)
                _local = (_cfg or {}).get("location") == "local"
        except Exception:
            pass

        tool_error_history = None
        evaluation_context = None
        if ctx:
            tool_error_history = state.context.get("tool_errors")
            evaluation_context = _build_finalizer_evaluation_context(state.context)

        stream_notifier = None
        try:
            from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
            ws_manager = getattr(coordinator, "_websocket_manager", None) or ctx.get("websocket_manager")
            if ws_manager and agent_task_id:
                stream_notifier = WorkflowStatusNotifier(
                    websocket_manager=ws_manager,
                    agent_task_id=agent_task_id,
                    root_task_id=ctx.get("root_task_id"),
                    previous_task_id=ctx.get("previous_task_id"),
                )
        except Exception as stream_err:
            logger.debug("Could not create finalizer stream notifier: %s", stream_err)

        envelope = await _finalize(
            original_prompt=original_prompt or state.user_agent_task if hasattr(state, 'user_agent_task') else "",
            agent_task_id=agent_task_id,
            active_app=active_app,
            steps=steps or [],
            self_assessment=self_assessment,
            standardized_messages=standardized_messages or raw_messages or [],
            metrics=metrics,
            success=success,
            llm_model=coordinator._llm_model,
            is_local_model=_local,
            tool_error_history=tool_error_history,
            read_file_artifacts=(state.context.get("file_reads") if ctx else None),
            evaluation_context=evaluation_context,
            stream_notifier=stream_notifier,
        )
        
        # Capture ANY finalizer envelope so handle_execution_error can recover it
        # if a subsequent LLM call fails (e.g., context overflow on the post-tool
        # response, or local model producing unparseable output).
        if isinstance(envelope, dict):
            if hasattr(state, 'context') and isinstance(state.context, dict):
                state.context["captured_finalizer_envelope"] = envelope
                logger.info(f"✅ FINALIZER: Captured envelope to state context (success={envelope.get('success')})")
        
        return _json.dumps(envelope, ensure_ascii=False)

    full_description = (
        "FINAL REFLECTION CHECKPOINT - Call this EXACTLY ONCE as your LAST action.\n"
        "\n"
        "BEFORE calling this tool:\n"
        "1. Compare original_prompt to what you actually produced\n"
        "2. Check for consistency across multiple similar items\n"
        "3. Verify semantic correctness (does it match user intent?)\n"
        "4. If you find issues: make MINIMAL targeted corrections, then call this\n"
        "\n"
        "Input: Structured arguments:\n"
        "  - original_prompt: User's exact request\n"
        "  - agent_task_id: AgentTask identifier\n"
        "  - active_app: Application context\n"
        "  - steps: Array of execution results\n"
        "  - self_assessment: YOUR reflection on whether results match intent (REQUIRED)\n"
        "  - raw_messages: **REQUIRED** - Your FULL output text (email summary, analysis, etc.) - what the user will see\n"
        "  - standardized_messages: (optional)\n"
        "  - metrics: (optional: steps_completed, steps_total, duration_ms)\n"
        "  - success: (optional)\n"
        "\n"
        "Output: STRICT JSON with {success, summary_text, result_payload{agent_task_id, app_context, files[], steps, duration_ms}, self_assessment}."
    )
    chosen_description = select_description_for_profile(
        profile, full_description, FINALIZER_SLIM_DESCRIPTION
    )

    finalize_tool = StructuredTool(
        name="finalize_agent_task_result",
        func=_finalize_wrapper,
        coroutine=_finalize_wrapper,  # CRITICAL: Tell LangChain this is async
        args_schema=FinalizeInput,
        return_direct=True,
        description=chosen_description,
    )
    
    return finalize_tool


# =============================================================================
# AGENT EXECUTOR CREATION
# =============================================================================

def _telemetry_schema_for_tool(tool: Any) -> Dict[str, Any]:
    """Mirror LlamaCppLangChainAdapter._get_tool_parameters so the size
    we measure matches what the local adapter actually sends. Cloud
    adapters use the same Pydantic schema source, so this number is
    representative for both paths."""
    schema_obj = getattr(tool, "args_schema", None)
    if schema_obj is not None:
        try:
            schema = schema_obj.model_json_schema()
            schema.pop("title", None)
            return schema
        except Exception:
            pass
    return {"type": "object", "properties": {}, "required": []}


def _log_prompt_tool_surface_telemetry(
    *,
    langchain_llm: Any,
    tools: List[Any],
    system_prompt_text: str,
    staged_tool_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit two structured INFO lines describing the build-time prompt
    and tool surface for this executor. Wrapped in a try/except so a
    logging failure can never break executor creation."""
    try:
        system_chars = len(system_prompt_text or "")
        system_tokens_est = system_chars // 4

        per_tool: List[Tuple[str, int, int]] = []
        for t in tools or []:
            name = getattr(t, "name", "?") or "?"
            desc_chars = len(getattr(t, "description", "") or "")
            try:
                schema_chars = len(_json.dumps(
                    _telemetry_schema_for_tool(t),
                    separators=(",", ":"),
                ))
            except Exception:
                schema_chars = 0
            per_tool.append((name, desc_chars, schema_chars))

        tool_count = len(per_tool)
        desc_total = sum(d for _, d, _ in per_tool)
        schema_total = sum(s for _, _, s in per_tool)
        if per_tool:
            desc_max_tool, desc_max_chars, _ = max(per_tool, key=lambda x: x[1])
            schema_max_tool, _, schema_max_chars = max(per_tool, key=lambda x: x[2])
        else:
            desc_max_tool = schema_max_tool = "-"
            desc_max_chars = schema_max_chars = 0

        # Plan B: capture the active rendering profile and (when in
        # slim_text_catalog mode) the catalog preamble size so the
        # master map's pinned telemetry reflects the real on-the-wire
        # tool surface, not just what bind_tools handed off.
        tool_rendering_value = "full_schema"
        catalog_chars = 0
        try:
            profile = getattr(langchain_llm, "_tool_rendering_profile", None)
            if profile is not None:
                tool_rendering_value = getattr(
                    profile, "tool_rendering", "full_schema"
                ) or "full_schema"
            if tool_rendering_value == "slim_text_catalog":
                from .slim_catalog_renderer import render_slim_catalog_preamble
                preview = render_slim_catalog_preamble(tools or [])
                catalog_chars = len(preview)
        except Exception:
            pass

        if tool_rendering_value == "slim_text_catalog":
            # tools= is omitted on the wire; the catalog preamble is the
            # tool surface the model actually sees. Reflect that in the
            # build totals so the headroom estimate is honest.
            build_chars_total = system_chars + catalog_chars
        else:
            build_chars_total = system_chars + desc_total + schema_total
        build_tokens_est = build_chars_total // 4

        model_class = type(langchain_llm).__name__
        model_name = getattr(langchain_llm, "model_name", None)
        llm_type = getattr(langchain_llm, "_llm_type", None)
        context_window = getattr(langchain_llm, "context_window", None)

        stage = "-"
        loaded_families = "-"
        family_count = "-"
        initial_tool_count = "-"
        expanded_tool_count = "-"
        expansion_count = "-"
        if isinstance(staged_tool_metadata, dict):
            stage = str(staged_tool_metadata.get("stage") or "-")
            loaded_families_value = staged_tool_metadata.get("loaded_families") or []
            if isinstance(loaded_families_value, (list, tuple, set)):
                loaded_families = ",".join(str(item) for item in loaded_families_value) or "-"
            else:
                loaded_families = str(loaded_families_value)
            family_count = str(staged_tool_metadata.get("family_count", "-"))
            initial_tool_count = str(staged_tool_metadata.get("initial_tool_count", "-"))
            expanded_tool_count = str(staged_tool_metadata.get("expanded_tool_count", "-"))
            expansion_count = str(staged_tool_metadata.get("expansion_count", "-"))

        logger.info(
            "[AgentTelemetry] prompt-slice "
            f"model_class={model_class} model_name={model_name} llm_type={llm_type} "
            f"context_window={context_window} "
            f"tool_rendering={tool_rendering_value} "
            f"tool_surface_stage={stage} loaded_families={loaded_families} "
            f"family_count={family_count} "
            f"initial_tool_count={initial_tool_count} expanded_tool_count={expanded_tool_count} "
            f"expansion_count={expansion_count} "
            f"system_chars={system_chars} system_tokens_est={system_tokens_est} "
            f"build_chars_total={build_chars_total} build_tokens_est={build_tokens_est}"
        )
        logger.info(
            "[AgentTelemetry] tool-surface "
            f"tool_rendering={tool_rendering_value} "
            f"tool_surface_stage={stage} loaded_families={loaded_families} "
            f"family_count={family_count} "
            f"initial_tool_count={initial_tool_count} expanded_tool_count={expanded_tool_count} "
            f"expansion_count={expansion_count} "
            f"tool_count={tool_count} "
            f"desc_total_chars={desc_total} desc_max_chars={desc_max_chars} desc_max_tool={desc_max_tool} "
            f"schema_total_chars={schema_total} schema_max_chars={schema_max_chars} schema_max_tool={schema_max_tool} "
            f"catalog_chars={catalog_chars}"
        )

        if logger.isEnabledFor(logging.DEBUG):
            for name, dc, sc in per_tool:
                logger.debug(
                    f"[AgentTelemetry] tool name={name} desc_chars={dc} schema_chars={sc}"
                )
    except Exception as exc:
        logger.debug(f"[AgentTelemetry] emission failed: {exc}")


def _handle_tool_error(error: Exception) -> str:
    """
    Convert tool errors into actionable feedback for the agent.
    
    Instead of crashing, the agent sees the error and can reason about recovery.
    This is LangChain's native pattern for agent resilience.
    """
    error_str = str(error)
    error_type = type(error).__name__
    
    # Provide actionable guidance based on error type
    if "timeout" in error_str.lower():
        return f"Tool timed out: {error_str[:200]}. Try a simpler approach or break into smaller steps."
    elif "json" in error_str.lower() or "parse" in error_str.lower():
        return f"Data format error: {error_str[:200]}. Check your input format and try again."
    elif "not found" in error_str.lower() or "does not exist" in error_str.lower():
        return f"Resource not found: {error_str[:200]}. Verify the path/name and try again."
    elif "permission" in error_str.lower() or "access" in error_str.lower():
        return f"Permission error: {error_str[:200]}. Try a different approach that doesn't require this access."
    else:
        return f"Tool error ({error_type}): {error_str[:300]}. Review and try a different approach if needed."


def create_agent_executor(
    langchain_llm: Any,
    tools: List[Any],
    include_scratchpad: bool = True,
    user_profile_context: str = "",
    communication_context_section: str = "",
    custom_instructions_section: str = "",
    preloaded_skill_section: str = "",
    staged_tool_metadata: Optional[Dict[str, Any]] = None,
    max_execution_time_seconds: Optional[float] = None,
    enforce_native_time_limit: bool = True,
) -> AgentExecutor:
    """
    Create an AgentExecutor with the provided LLM and tools.
    
    Uses LangChain's native resilience patterns:
    - .with_retry() on LLM for automatic retry with exponential backoff
    - handle_parsing_errors as callable for actionable error feedback
    - Agent sees errors and can reason about recovery
    
    IMPORTANT: We manually create the agent instead of using create_tool_calling_agent
    because we need to bind tools BEFORE adding retry. The .with_retry() wrapper
    returns a RunnableRetry that doesn't have bind_tools(), so we must:
    1. Bind tools to the LLM first
    2. Then wrap with retry
    3. Then construct the agent runnable manually
    
    Args:
        langchain_llm: LangChain LLM instance
        tools: List of LangChain tools
        include_scratchpad: Whether to include agent scratchpad in prompt
        user_profile_context: Pre-formatted user identity string for the system prompt
        communication_context_section: Optional relationship-aware context for communication tasks
        preloaded_skill_section: Optional saved-skill body selected before execution
        
    Returns:
        Configured AgentExecutor instance
    """
    # Get the system prompt
    system_prompt_text = get_agent_system_prompt(
        user_profile_context=user_profile_context,
        communication_context_section=communication_context_section,
        custom_instructions_section=custom_instructions_section,
        preloaded_skill_section=preloaded_skill_section,
    )
    
    # Build the agent prompt
    agent_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_text),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    # CRITICAL FIX: Bind tools FIRST, then add retry
    # This ensures the LLM has tool-calling capability before being wrapped
    tools = normalize_structured_tool_args_schemas(tools)
    # Loop-control wrapper: detect and halt repeated identical invalid tool
    # calls before they consume the full execution-time cap. Applied centrally
    # here so every agent-bound tool is covered without per-tool changes.
    tools = wrap_tools_with_repetition_guard(tools)
    llm_with_tools = langchain_llm.bind_tools(tools)

    _log_prompt_tool_surface_telemetry(
        langchain_llm=langchain_llm,
        tools=tools,
        system_prompt_text=system_prompt_text,
        staged_tool_metadata=staged_tool_metadata,
    )

    # Retry a single failed model call only for typed transient failures (timeouts,
    # connection errors, 408/429/5xx, local mid-stream stalls). Context overflow,
    # authentication, and other errors go straight to execute_with_token_retry,
    # which recovers from each kind differently instead of repeating it unchanged.
    llm_with_retry = llm_with_tools.with_retry(
        retry_if_exception_type=LLM_RETRY_EXCEPTION_TYPES,
        stop_after_attempt=3,
        wait_exponential_jitter=True
    )
    
    # Manually create the agent runnable (replicating create_tool_calling_agent internals)
    # This is necessary because create_tool_calling_agent calls bind_tools internally,
    # but we've already bound tools and added retry
    from langchain_core.runnables import RunnableLambda

    def _log_llm_output(output):
        try:
            tc = getattr(output, "tool_calls", None) or []
            content_len = len(getattr(output, "content", "") or "")
            logger.info(
                f"🔬 PIPELINE: LLM returned to chain — "
                f"type={type(output).__name__}, content_len={content_len}, "
                f"tool_calls={len(tc)}"
            )
        except Exception as _e:
            logger.info(f"🔬 PIPELINE: LLM returned (logging failed: {_e})")
        return output

    _output_parser = ToolsAgentOutputParser()

    def _log_parser_output(output):
        try:
            logger.info(
                f"🔬 PIPELINE: OutputParser returned — "
                f"type={type(output).__name__}, value={str(output)[:200]}"
            )
        except Exception as _e:
            logger.info(f"🔬 PIPELINE: OutputParser returned (logging failed: {_e})")
        return output

    agent = (
        RunnablePassthrough.assign(
            agent_scratchpad=lambda x: format_to_tool_messages(x["intermediate_steps"])
        )
        | agent_prompt
        | llm_with_retry
        | RunnableLambda(_log_llm_output)
        | _output_parser
        | RunnableLambda(_log_parser_output)
    )
    
    # Create agent executor with enhanced configuration
    # handle_parsing_errors as callable gives agent actionable feedback instead of crashing
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=None,  # Uncapped - let agent work until completion or timeout
        handle_parsing_errors=_handle_tool_error,  # Agent sees errors and can adapt
        return_intermediate_steps=True,  # Capture tool usage details
        # Wall-clock safety net (see execution_limits). On the ASYNC path we use
        # (``ainvoke`` -> ``_acall``), LangChain wraps the reasoning loop in
        # ``async with asyncio_timeout(max_execution_time)``, so this cap CAN
        # interrupt a mid-tool-call ``await`` — it is a hard timeout, not just a
        # between-iterations check. Because ``max_iterations=None``, this cap is
        # the only trigger for LangChain's force-stop message, which
        # agent_execution_core relabels as an explicit execution timeout.
        # Staged passes disable this native cap and enforce a pause-aware pass budget in execute_with_token_retry instead, so time spent waiting on approvals or command input is not charged to the pass.
        max_execution_time=(
            (max_execution_time_seconds or AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS)
            if enforce_native_time_limit
            else None
        ),
        # ``early_stopping_method`` is intentionally left at its default
        # of ``"force"``. We attempted to set it to ``"generate"`` so
        # LangChain would call the LLM one more time on timeout to
        # produce a real wrap-up, but in langchain 0.3.27 the agent
        # path we use (BaseSingleActionAgent.return_stopped_response)
        # only accepts ``"force"`` -- ``"generate"`` raises
        # ``ValueError: Got unsupported early_stopping_method
        # `generate```` and crashes the run before any tool can
        # finalize (validated live on the May 22 8 PM scheduled run,
        # which failed at the cap with this exact error). The
        # ``"generate"`` branch only exists on the legacy ``Agent``
        # class (langchain/agents/agent.py lines 954-1003), which is
        # not the path our executor takes. Until we either upgrade
        # langchain to a version that supports ``"generate"`` on the
        # base agent classes, or override ``return_stopped_response``
        # ourselves, leaving this unset is the only safe value. LangChain's
        # raw wrap-up on timeout is the generic
        # ``"Agent stopped due to iteration limit or time limit."`` string;
        # agent_execution_core rewrites it into an explicit execution-timeout
        # message (see execution_limits.execution_timeout_message) so the user
        # never sees the misleading "iteration limit" wording.
    )
    
    return agent_executor


def create_unsupported_llm_result(state: "PlanningState", provider: str, model_name: str) -> Dict[str, Any]:
    """
    Create a failure result for unsupported LLM providers.
    
    Args:
        state: Current PlanningState
        provider: LLM provider name
        model_name: Model name
        
    Returns:
        Result dictionary indicating failure
    """
    return {
        "tool_execution_results": [{
            "execution_method": "dynamic_langchain_agent",
            "user_agent_task": state.user_agent_task,
            "status": "failed",
            "error": f"AgentTasks require a model that supports tool calling. The current model ({model_name}, provider: {provider}) does not support this. Please switch to a supported model in Settings.",
            "tools_available": [tool.name for tool in state.available_tools.tools] if state.available_tools else []
        }]
    }
