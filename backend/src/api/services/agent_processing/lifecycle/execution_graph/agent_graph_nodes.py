"""
LangGraph Node Functions for Agent Execution

This module contains all the individual node functions that make up the LangGraph workflow:
- Analysis nodes: analyze_request, plan_capabilities
- Tool setup: create_tools
- Execution: execute_todos_with_tools (agent creates steps dynamically)
- Each node is a pure async function that takes PlanningState and returns updates

These nodes are composed into graphs by the graph builders in agent_graph_runtime.py.
All nodes follow the LangGraph pattern: take state, perform work, return state updates.

REFACTORED (Jan 2026):
- Token trimming utilities moved to shared/prompt_context_trimming.py
- System prompts moved to system_prompts.py
- LLM/agent creation moved to agent_executor_factory.py
- Execution logic moved to agent_execution_core.py
- Finalization logic moved to lifecycle/finalization modules
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

# Import shared state and progress system
from .agent_progress_system import PlanningState

# Import existing modules (kept as-is)
from ..planning.request_analyzer import RequestAnalyzer
from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile
from api.core.logging.api_logger import api_logger

# Tool integration
from .service_tools import create_service_tools

# Import refactored modules
from .agent_executor_factory import (
    create_langchain_llm,
    create_langchain_llm_from_model,
    create_finalizer_tool,
    create_agent_executor,
    create_unsupported_llm_result,
    _build_finalizer_evaluation_context,
)
from .agent_result_synthesis import (
    derive_self_assessment_from_handoff,
    intermediate_steps_to_finalizer_steps,
    run_final_synthesis_for_state,
)
from .execution_limits import AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS
from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
from .agent_execution_core import (
    setup_live_callbacks,
    ModelUnavailableBeforeFirstResponse,
)
from .staged_execution_loop import StagedExecutionRequest, run_staged_tool_loading
from .workflow_deadline import deadline_evidence, deadline_from_context
from ..finalization.execution_result_processing import handle_execution_error, process_agent_result
from ..finalization.recovery import attempt_finalization_recovery
from ..finalization.task_state_persistence import (
    handle_checkpoint_request,
    handle_provider_delegation_wait_request,
)
from api.services.agent_providers.targeting.delegation_service import ProviderDelegationWaitRequest
from ...tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

# Use a child of the configured `api.main` logger so node logs (including the
# skill-consideration decision line) reach the backend log file. A bare
# logging.getLogger(__name__) sits outside that handler tree and is dropped.
logger = api_logger.getChild("agent_graph_nodes")


def _collect_emitted_thinking_history(
    live_callbacks: Any,
    langchain_llm: Any,
    synthesis_thinking_history: Any = None,
) -> List[Dict[str, Any]]:
    """Collect the completed reasoning segments emitted by every active UI source."""
    segments: List[Dict[str, Any]] = []
    if isinstance(live_callbacks, list):
        for callback in live_callbacks:
            getter = getattr(callback, "get_thinking_history", None)
            if callable(getter):
                segments.extend(getter())

    heartbeat = getattr(langchain_llm, "_basil_heartbeat", None)
    heartbeat_segments = getattr(heartbeat, "thinking_segments", None)
    if isinstance(heartbeat_segments, list):
        segments.extend(heartbeat_segments)
    if isinstance(synthesis_thinking_history, list):
        segments.extend(synthesis_thinking_history)
    return segments


def _get_run_coordinator(state: PlanningState):
    """Return the WorkflowCoordinator shared across this graph run."""
    from ..runtime.workflow_coordinator import WorkflowCoordinator

    if state.context is None:
        state.context = {}

    coordinator = state.context.get("_workflow_coordinator")
    if not isinstance(coordinator, WorkflowCoordinator):
        coordinator = WorkflowCoordinator(websocket_manager=state.context.get("websocket_manager"))
        state.context["_workflow_coordinator"] = coordinator
    return coordinator


async def _build_agent_communication_context_section(state: PlanningState) -> str:
    """Build read-only relationship context for email-oriented agent tasks."""
    context = state.context or {}
    screen_text = context.get("screen_text") or ""
    if not isinstance(screen_text, str) or not screen_text.strip():
        return ""

    try:
        from api.core.knowledge.personalization.contact_context import (
            EmailInteractionKind,
            extract_email_participant_context,
        )
        from api.core.knowledge.personalization_models import ContextType
        from api.core.knowledge.personalization_service import PersonalizationService

        lower_screen_text = screen_text.lower()
        if "from:" in lower_screen_text:
            interaction_kind = EmailInteractionKind.REPLY
        elif "to:" in lower_screen_text:
            interaction_kind = EmailInteractionKind.COMPOSE
        else:
            return ""

        participant_context = extract_email_participant_context(screen_text, interaction_kind)
        if not participant_context.primary:
            return ""

        personalization = PersonalizationService()
        personalization_context = await personalization.build_personalization_context(
            context_type=(
                ContextType.EMAIL_COMPOSE
                if interaction_kind == EmailInteractionKind.COMPOSE
                else ContextType.EMAIL_REPLY
            ),
            recipient=participant_context.primary.email,
            app_name=context.get("active_app"),
        )

        lines = [
            "\n\nRELATIONSHIP-AWARE COMMUNICATION CONTEXT:",
            "Use this only when drafting, replying to, or reasoning about the visible email context.",
            "Do not invent relationship facts that are not listed here.",
            f"- Primary participant: {participant_context.primary.label}",
            f"- Interaction type: {interaction_kind.value}",
        ]

        contact = personalization_context.contact
        if contact:
            if contact.contact_name:
                lines.append(f"- Contact name: {contact.contact_name}")
            if contact.contact_company:
                lines.append(f"- Organization: {contact.contact_company}")
            if contact.relationship_type and str(contact.relationship_type) != "unknown":
                lines.append(f"- Stored relationship: {contact.relationship_type}")
            if contact.formality_level:
                lines.append(f"- Typical formality: {contact.formality_level}")
            if contact.message_count and contact.message_count > 0:
                lines.append(f"- Prior tracked exchanges: {contact.message_count}")

        if participant_context.cc_participants:
            cc_labels = ", ".join(participant.label for participant in participant_context.cc_participants[:3])
            lines.append(f"- CC participants: {cc_labels}")

        if personalization_context.writing_samples:
            lines.append("Recipient/context-relevant writing samples:")
            for index, sample in enumerate(personalization_context.writing_samples[:2], 1):
                sample_preview = (sample.content or "").strip().replace("\n", " ")
                if len(sample_preview) > 500:
                    sample_preview = sample_preview[:497].rstrip() + "..."
                recipient_label = f" to {sample.recipient}" if sample.recipient else ""
                lines.append(f"Sample {index}{recipient_label}: {sample_preview}")

        return "\n".join(lines) + "\n"
    except Exception as exc:
        logger.warning(f"Could not build agent communication context: {exc}")
        return ""


def _notification_chain_kwargs(context: Dict[str, Any] | None) -> Dict[str, Any]:
    """Build WebSocket routing identity for task-thread notifications."""
    context = context or {}
    return {
        "agent_task_id": context.get("agent_task_id"),
        "root_task_id": context.get("root_task_id"),
        "previous_task_id": context.get("previous_task_id"),
    }


# =============================================================================
# NODE: ANALYZE REQUEST
# =============================================================================

async def _node_analyze_request(state: PlanningState) -> Dict[str, Any]:
    """Node: analyze_request -> populates request_analysis."""
    coordinator = _get_run_coordinator(state)
    
    # Ensure LLM model is available for intelligent interpretation
    await coordinator._ensure_llm_components_initialized(context=state.context)
    
    # Create analyzer with LLM model for intelligent interpretation
    analyzer = RequestAnalyzer(llm_model=coordinator._llm_model)
    
    try:
        from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
        notifier = WorkflowStatusNotifier(websocket_manager=coordinator._websocket_manager, **_notification_chain_kwargs(state.context))
        await notifier.send_agent_progress_update(message="Analyzing your request…", details=None)
    except Exception:
        pass
    
    analysis = await analyzer.analyze_request(state.user_agent_task, state.context)
    return {"request_analysis": analysis}


# =============================================================================
# NODE: PLAN CAPABILITIES
# =============================================================================

async def _node_plan_capabilities(state: PlanningState) -> Dict[str, Any]:
    """Node: plan_capabilities -> populates capability_cache."""
    from ..runtime.turn_timing import get_or_create_turn_timing
    from ..runtime.warm_artifact_cache import (
        compute_environment_signature,
        get_warm_artifact_cache,
    )

    coordinator = _get_run_coordinator(state)
    timing = get_or_create_turn_timing(state.context)

    if timing is not None:
        timing.start("svc_init")
    await coordinator._ensure_services_initialized()
    if timing is not None:
        timing.stop("svc_init")

    planner = coordinator.service_method_planner
    service_names = tuple(
        sorted(coordinator._service_execution_engine.get_registered_services())
    )
    signature = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=service_names,
    )

    async def _build_capability_cache():
        if timing is not None:
            timing.start("capability_discover")
        try:
            return await planner.plan_service_capabilities()
        finally:
            if timing is not None:
                timing.stop("capability_discover")

    cache, was_hit = await get_warm_artifact_cache().get_or_build(
        key="service_capability_cache",
        signature=signature,
        builder=_build_capability_cache,
    )
    planner._capability_cache = cache
    logger.info(
        "plan_capabilities warm-cache %s services=%s",
        "HIT" if was_hit else "MISS",
        len(service_names),
    )

    try:
        from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
        notifier = WorkflowStatusNotifier(websocket_manager=coordinator._websocket_manager, **_notification_chain_kwargs(state.context))
        svc_count = len(cache.services) if cache and hasattr(cache, 'services') and cache.services else 0
        method_count = sum(len(v.get('methods', {})) for v in cache.services.values()) if cache and hasattr(cache, 'services') and cache.services else 0
        await notifier.send_agent_progress_update(
            message="Planning available actions…",
            details=f"Found {svc_count} services, {method_count} methods"
        )
    except Exception:
        pass
    return {"capability_cache": cache}


# =============================================================================
# NODE: CREATE TOOLS
# =============================================================================

async def _node_create_tools(state: PlanningState) -> Dict[str, Any]:
    """Node: create_tools -> converts services to LangChain Tools for advanced execution."""
    coordinator = _get_run_coordinator(state)
    await coordinator._ensure_services_initialized()
    
    # Propagate agent_task_id to services so approval WS events can route to the correct agent
    _cmd_id = state.context.get("agent_task_id") if state.context else None
    if _cmd_id and coordinator._service_execution_engine:
        for _svc_name in ("shell_service", "applescript_service"):
            _svc = coordinator._service_execution_engine.get_service(_svc_name)
            if _svc and hasattr(_svc, '_agent_task_id'):
                _svc._agent_task_id = _cmd_id
    
    # Initialize LLM components to get model context window for tool output limits
    await coordinator._ensure_llm_components_initialized(context=state.context)
    
    # Get the capability cache that was created in the previous node
    if not state.capability_cache:
        raise RuntimeError("Cannot create tools without capability cache. Ensure plan_capabilities runs first.")
    
    # Send progress update
    try:
        from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
        chain_kwargs = _notification_chain_kwargs(state.context)
        chain_kwargs["agent_task_id"] = _cmd_id
        notifier = WorkflowStatusNotifier(websocket_manager=coordinator._websocket_manager, **chain_kwargs)
        total_methods = sum(len(info.get('methods', {})) for info in state.capability_cache.services.values())
        await notifier.send_agent_progress_update(
            message="Preparing tools…", 
            details=f"{total_methods} ready"
        )
    except Exception:
        pass

    # Get model's context window for dynamic tool output truncation limits
    # This prevents token limit errors by truncating oversized tool outputs at the source
    max_context_tokens = None
    try:
        llm_model = coordinator._llm_model
        if llm_model:
            # Try different attribute names used by various model classes
            if hasattr(llm_model, 'max_context_length'):
                max_context_tokens = llm_model.max_context_length
            elif hasattr(llm_model, 'context_window'):
                max_context_tokens = llm_model.context_window
            elif hasattr(llm_model, 'get_metadata'):
                metadata = llm_model.get_metadata()
                if isinstance(metadata, dict):
                    max_context_tokens = metadata.get('context_window')
                elif hasattr(metadata, 'context_window'):
                    max_context_tokens = metadata.context_window
            
            if max_context_tokens:
                logger.info(f"🔧 Model context window: {max_context_tokens:,} tokens - tool outputs will be limited to ~{int(max_context_tokens * 0.10):,} tokens")
    except Exception as e:
        logger.warning(f"⚠️ Could not determine model context window: {e}. Using default (200K tokens).")

    # Resolve the runtime model profile so the construction layer (per-tool
    # factories + ServiceToolFactory) can pick FULL vs SLIM companion fields.
    # Profile is resolved once here and threaded into every factory.
    runtime_profile = None
    try:
        if coordinator._llm_model is not None:
            runtime_profile = resolve_runtime_model_profile(coordinator._llm_model)
            logger.info(
                f"🧭 Runtime tool_rendering profile: {getattr(runtime_profile, 'tool_rendering', 'full_schema')}"
            )
    except Exception as e:
        logger.warning(f"⚠️ Could not resolve runtime model profile for tool construction: {e}")

    # Create LangChain Tools from all available services
    logger.info(f"🔧 Creating tools from {len(state.capability_cache.services)} services")
    for service_name, service_info in state.capability_cache.services.items():
        logger.info(f"   📋 Service: {service_name} - Methods: {len(service_info.get('methods', {}))}")

    from ..runtime.turn_timing import get_or_create_turn_timing

    chain_context = state.context.get("chain_context") if state.context else None
    delegated_envelope = (
        chain_context.get("delegated_capability_envelope")
        if isinstance(chain_context, dict)
        else None
    )
    constrained_child = (
        isinstance(delegated_envelope, dict)
        and delegated_envelope.get("allows_child_delegation") is False
    )
    tools_result = await create_service_tools(
        service_execution_engine=coordinator._service_execution_engine,
        capability_analyzer=coordinator._service_capability_analyzer,
        services=state.capability_cache.services,
        max_context_tokens=max_context_tokens,
        profile=runtime_profile,
        current_root_task_id=(state.context.get("root_task_id") or _cmd_id) if state.context else None,
        current_agent_task_id=_cmd_id,
        current_conversation_id=state.context.get("conversation_id") if state.context else None,
        agent_task_submission_service=getattr(coordinator, "_agent_task_submission_service", None),
        turn_timing=get_or_create_turn_timing(state.context),
        allow_provider_catalog=not (
            (state.context and state.context.get("provider_delegation_continuation"))
            or constrained_child
        ),
        allow_delegated_agent=not constrained_child,
        allow_child_interaction_tools=not constrained_child,
    )
    
    logger.info(f"🔧 Tool creation result: {len(tools_result.tools)} tools, {len(tools_result.errors)} errors")
    if tools_result.errors:
        for error in tools_result.errors:
            logger.error(f"   ❌ Tool creation error: {error}")
    
    # Vision analysis tool: native multimodal agent model, or optional local Qwen2.5-VL fallback
    from api.core.models.preferences import Preferences
    from api.services.agent_processing.tools.vision.backend_resolver import (
        VisionBackend,
        resolve_agent_vision_backend,
    )
    from api.settings import get_settings

    _prefs = Preferences.load()
    _models_dir = Path(get_settings().models_dir)
    _vb = resolve_agent_vision_backend(coordinator._llm_model, _prefs, _models_dir)

    if _vb != VisionBackend.UNAVAILABLE:
        try:
            from ...tools.internal_basil_tools.vision_analysis_tool import create_vision_analysis_tool

            vision_tool = create_vision_analysis_tool(
                coordinator,
                vision_backend=_vb,
                models_dir=_models_dir,
                local_vision_model_id=_prefs.models.local_vision_model_id,
                profile=runtime_profile,
            )
            tools_result.tools.append(vision_tool)
            tools_result.tool_map["vision.analyze"] = vision_tool
            logger.info(
                "   ✅ Added analyze_with_vision tool (%s)",
                "native" if _vb == VisionBackend.NATIVE else "local_qwen_vl",
            )
        except Exception as e:
            warn = f"Failed to add vision analysis tool: {e}"
            tools_result.optional_warnings.append(warn)
            logger.warning(f"   ⚠️ {warn}")
    else:
        logger.info(
            "   ⏭️ Skipping analyze_with_vision (no native vision; local fallback off or files missing)"
        )
    
    try:
        from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
        notifier = WorkflowStatusNotifier(websocket_manager=coordinator._websocket_manager, **_notification_chain_kwargs(state.context))
        await notifier.send_agent_progress_update(
            message="Preparing tools…",
            details=f"{len(tools_result.tools)} ready"
        )
    except Exception:
        pass
    # Store the tool error log reference on state.context so the finalizer can
    # read it independently of the agent's self-report.
    if state.context is not None:
        state.context["tool_errors"] = tools_result.tool_error_log
        state.context["file_reads"] = tools_result.file_read_log
        if getattr(tools_result, "optional_warnings", None):
            state.context["tool_creation_warnings"] = list(tools_result.optional_warnings)

    # Return the full ToolCreationResult object for runtime; checkpointing will serialize safely via custom serde
    return {"available_tools": tools_result}


# =============================================================================
# NODE: CONSIDER SKILLS (Agent-Owned Skill Selection)
# =============================================================================

async def _node_consider_skills(state: PlanningState) -> Dict[str, Any]:
    """Node: consider_skills -> agent decides whether to load one saved skill.

    The relevance decision is made by the agent model judging catalog metadata;
    the backend only presents the catalog, validates the chosen slug, and loads
    exactly what the agent selected. Any failure is non-fatal and leaves the task
    to run with no preselected skill.
    """
    try:
        from api.services.skills.skill_service import get_skill_service
        from .skill_selection import select_relevant_skill
        from .system_prompts import build_preloaded_skill_prompt_section

        skill_service = get_skill_service()
        catalog_entries = skill_service.list_catalog_entries()
        if not catalog_entries:
            return {}

        # Respect cancellation before spending a model round-trip.
        cancel_event = state.context.get("cancel_event") if state.context else None
        if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
            return {}

        coordinator = _get_run_coordinator(state)
        await coordinator._ensure_llm_components_initialized(context=state.context)
        model = coordinator._llm_model
        if model is None:
            return {}

        try:
            from ..runtime.workflow_status_notifier import WorkflowStatusNotifier
            notifier = WorkflowStatusNotifier(
                websocket_manager=coordinator._websocket_manager,
                **_notification_chain_kwargs(state.context),
            )
            await notifier.send_agent_progress_update(message="Considering saved skills…", details=None)
        except Exception:
            pass

        selection = await select_relevant_skill(
            model=model,
            user_request=state.user_agent_task,
            catalog_entries=catalog_entries,
        )

        if selection.slug is None:
            logger.info("skill-consideration selected_slug=null reason=%r", selection.reason)
            return {}

        skill_record = skill_service.load_skill(selection.slug)
        section = build_preloaded_skill_prompt_section(skill_record.slug, skill_record.body)
        logger.info(
            "skill-consideration selected_slug=%s reason=%r",
            selection.slug,
            selection.reason,
        )
        return {
            "selected_skill_section": section,
            "selected_skill_slug": skill_record.slug,
        }
    except Exception as e:
        logger.warning(f"Skill consideration step failed; proceeding without a selected skill: {e}")
        return {}


# =============================================================================
# NODE: EXECUTE TODOS WITH TOOLS (Main Execution Node)
# =============================================================================

async def _node_execute_todos_with_tools(state: PlanningState) -> Dict[str, Any]:
    """Node: execute_todos_with_tools -> executes todos using LangChain Tools for advanced automation."""
    coordinator = _get_run_coordinator(state)
    logger.info(f"🔧 DEBUG: Coordinator in execute_todos_with_tools has websocket_manager={coordinator._websocket_manager is not None}")
    await coordinator._ensure_services_initialized()
    await coordinator._ensure_llm_components_initialized(context=state.context)
    
    # Ensure we have tools available
    if not state.available_tools:
        raise RuntimeError("Cannot execute with tools without available_tools. Ensure create_tools runs first.")
    
    if state.available_tools.errors:
        raise RuntimeError(f"Tool creation had errors: {state.available_tools.errors}")
    
    # DYNAMIC AGENT EXECUTION - Agent orchestrates tool usage in real-time
    logger.info(f"🤖 DYNAMIC AGENT EXECUTION: {state.user_agent_task}")
    logger.info(f"🔧 Available tools: {[tool.name for tool in state.available_tools.tools]}")
    
    try:
        # Create LangChain LLM
        try:
            cmd_id = state.context.get("agent_task_id") if state.context else None
            langchain_llm = create_langchain_llm(
                coordinator,
                agent_task_id=cmd_id,
                root_task_id=state.context.get("root_task_id") if state.context else None,
                previous_task_id=state.context.get("previous_task_id") if state.context else None,
            )
        except RuntimeError as llm_err:
            # Unsupported provider
            logger.warning(f"⚠️ {llm_err}")
            llm_model = coordinator._llm_model
            provider = "unknown"
            try:
                meta = llm_model.get_metadata()
                provider = getattr(meta, "source", "unknown") or "unknown"
            except Exception:
                pass
            return create_unsupported_llm_result(state, provider, llm_model.model_name)
        
        # Resolve the runtime model profile so the finalizer tool's construction
        # can pick FULL vs SLIM companion fields once a slim companion is authored.
        finalizer_runtime_profile = None
        try:
            if coordinator._llm_model is not None:
                finalizer_runtime_profile = resolve_runtime_model_profile(coordinator._llm_model)
        except Exception:
            pass

        # Finalizer is not an agent tool on the primary path: backend runs streamed
        # synthesis then calls finalize_agent_task_result directly. Keep a recovery
        # executor that still includes the finalizer tool for legacy repair runs.
        finalize_tool_recovery = create_finalizer_tool(state, coordinator, profile=finalizer_runtime_profile)
        
        # Fetch user profile for identity context in the system prompt
        user_profile_context = ""
        custom_instructions_section = ""
        try:
            from api.core.knowledge.personalization_service import PersonalizationService
            profile_svc = PersonalizationService()
            profile = await profile_svc.get_user_profile()
            if profile:
                parts = []
                if profile.full_name:
                    parts.append(f"Name: {profile.full_name}")
                if profile.preferred_name:
                    parts.append(f"Preferred name: {profile.preferred_name}")
                if profile.email:
                    parts.append(f"Email: {profile.email}")
                if profile.job_title:
                    parts.append(f"Title: {profile.job_title}")
                if profile.company_name:
                    parts.append(f"Company: {profile.company_name}")
                user_profile_context = ", ".join(parts) if parts else ""
                if profile.custom_instructions and profile.custom_instructions.strip():
                    custom_instructions_section = (
                        "\n\nUSER'S STANDING COMMUNICATION INSTRUCTIONS (always follow "
                        "these, they take priority over generic style choices you would "
                        f"otherwise make):\n{profile.custom_instructions.strip()}\n"
                    )
        except Exception as e:
            logger.warning(f"Could not load user profile for agent context: {e}")

        communication_context_section = await _build_agent_communication_context_section(state)
        
        # Skill the agent selected during the consider_skills node (if any).
        selected_skill_section = state.selected_skill_section or ""

        # Set up live progress callbacks
        live_callbacks = setup_live_callbacks(state, coordinator)

        # Execute the user agent task with token-limit retry
        logger.info(f"🤖 EXECUTING USER AGENT TASK WITH LANGCHAIN AGENT: {state.user_agent_task}")
        cancel_event = state.context.get("cancel_event") if state.context else None
        if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
            raise asyncio.CancelledError()

        from ..runtime.turn_timing import get_or_create_turn_timing
        _timing = get_or_create_turn_timing(state.context)
        if _timing is not None:
            _timing.start("agent_loop")
        staged_request = StagedExecutionRequest(
            langchain_llm=langchain_llm,
            state=state,
            user_profile_context=user_profile_context,
            communication_context_section=communication_context_section,
            custom_instructions_section=custom_instructions_section,
            selected_skill_section=selected_skill_section,
            live_callbacks=live_callbacks,
            cancel_event=cancel_event,
        )
        try:
            staged = await run_staged_tool_loading(staged_request)
        except ModelUnavailableBeforeFirstResponse as unavailable_err:
            from api.dependencies import get_model_usage_service
            from api.core.models.model_types import ModelCapability
            fallback_model = await get_model_usage_service().get_designated_local_fallback_model(
                {ModelCapability.REASONING}
            )
            if fallback_model is None:
                raise unavailable_err.original_error from unavailable_err
            logger.warning(
                f"⚠️ Preferred reasoning model unreachable before any response; "
                f"retrying agent task once with local fallback model {fallback_model.model_name}"
            )
            fallback_langchain_llm = create_langchain_llm_from_model(
                fallback_model,
                agent_task_id=cmd_id,
                root_task_id=state.context.get("root_task_id") if state.context else None,
                previous_task_id=state.context.get("previous_task_id") if state.context else None,
            )
            langchain_llm = fallback_langchain_llm
            import dataclasses
            staged_request = dataclasses.replace(staged_request, langchain_llm=fallback_langchain_llm)
            if state.context is not None:
                state.context["reasoning_fallback_model_used"] = fallback_model.model_name
            staged = await run_staged_tool_loading(staged_request)
        result = staged.result
        loaded_families = staged.loaded_families
        intermediate_steps = staged.intermediate_steps
        agent_output = staged.agent_output
        final_input = staged.final_input
        active_tools_for_recovery = staged.active_tools_for_recovery
        core_tools = staged.core_tools

        if _timing is not None:
            _timing.stop("agent_loop")

        # Streamed final synthesis, then deterministic finalizer (no in-agent finalizer)
        chain_kwargs = _notification_chain_kwargs(state.context)
        stream_notifier = WorkflowStatusNotifier(
            websocket_manager=coordinator._websocket_manager,
            **chain_kwargs,
        )
        synthesis_thinking_history: List[Dict[str, Any]] = []
        if _timing is not None:
            _timing.start("synthesis")
        try:
            synthesis_result = await run_final_synthesis_for_state(
                state=state,
                final_input=final_input,
                agent_output=agent_output,
                intermediate_steps=intermediate_steps,
                llm_model=coordinator._llm_model,
                stream_notifier=stream_notifier,
                cancel_event=cancel_event,
            )
            synthesized_text = synthesis_result.text
            synthesis_thinking_history = synthesis_result.thinking_history
            if state.context is not None:
                state.context["final_synthesis_evidence"] = synthesis_result.to_evidence_dict()
        except Exception as syn_exc:
            logger.error("Final synthesis failed: %s", syn_exc, exc_info=True)
            synthesized_text = agent_output
            if state.context is not None:
                state.context["final_synthesis_evidence"] = {
                    "terminal": {
                        "reason": "error",
                        "truncated": True,
                        "error_message": str(syn_exc),
                    },
                    "completed_cleanly": False,
                }

        st = (synthesized_text if isinstance(synthesized_text, str) else "").strip()
        if not st:
            synthesized_text = (
                agent_output
                or "The run completed, but no final summary could be generated."
            )
        else:
            synthesized_text = st

        ctx = state.context or {}
        _local = False
        try:
            from api.core.models.models_registry.schema import get_model as _get_model_cfg

            _mid = ctx.get("model_id")
            if _mid:
                _cfg = _get_model_cfg(_mid)
                _local = (_cfg or {}).get("location") == "local"
        except Exception:
            pass

        active_app = ctx.get("active_app")
        if not active_app:
            ac = ctx.get("app_context")
            if isinstance(ac, dict):
                active_app = ac.get("app_name")

        if _timing is not None:
            _timing.stop("synthesis")
        finalizer_steps = intermediate_steps_to_finalizer_steps(intermediate_steps)
        finalize_attempts = 0
        final_envelope = None
        if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
            raise asyncio.CancelledError()
        if _timing is not None:
            _timing.start("finalize")
        # P2: broadcast a provisional envelope now (no LLM eval); run the cloud-only
        # LLM outcome verification off the critical path and patch the result after.
        from .async_finalizer import (
            FinalizeInputs,
            build_provisional_envelope,
            mark_verification_status,
            schedule_outcome_verification,
        )
        finalize_inputs = FinalizeInputs(
            original_prompt=state.user_agent_task,
            agent_task_id=ctx.get("agent_task_id"),
            active_app=active_app,
            steps=finalizer_steps,
            self_assessment=derive_self_assessment_from_handoff(agent_output),
            standardized_messages=[synthesized_text],
            metrics={
                "steps_completed": len(finalizer_steps),
                "steps_total": len(finalizer_steps),
            },
            tool_error_history=ctx.get("tool_errors"),
            read_file_artifacts=ctx.get("file_reads"),
            evaluation_context=_build_finalizer_evaluation_context(ctx),
            synthesis_evidence=ctx.get("final_synthesis_evidence"),
        )
        final_envelope = await build_provisional_envelope(finalize_inputs)
        if final_envelope is not None and coordinator._llm_model is not None:
            schedule_outcome_verification(
                inputs=finalize_inputs,
                llm_model=coordinator._llm_model,
                ws_manager=coordinator._websocket_manager or ctx.get("websocket_manager"),
                agent_task_id=ctx.get("agent_task_id"),
                root_task_id=ctx.get("root_task_id"),
                previous_task_id=ctx.get("previous_task_id"),
                cancel_event=cancel_event,
            )
        elif final_envelope is not None:
            # No model instance available at all (should not happen in practice);
            # resolve the deterministic (unforced) provisional outcome as final.
            mark_verification_status(final_envelope, "resolved")

        if isinstance(final_envelope, dict) and state.context is not None:
            state.context["captured_finalizer_envelope"] = final_envelope

        # Legacy recovery: only if the direct finalizer did not return an envelope
        if final_envelope is None and finalize_attempts == 0:
            deadline = deadline_from_context(state.context)
            recovery_max_execution_time = AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS
            if deadline is not None:
                if not deadline.can_start_execution(
                    per_pass_cap_seconds=AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS,
                ):
                    if state.context is not None:
                        state.context["workflow_deadline_evidence"] = deadline_evidence(
                            deadline,
                            reason="insufficient_remaining_time_for_finalizer_recovery",
                        )
                    raise TimeoutError("Insufficient remaining workflow time for finalizer recovery.")
                recovery_max_execution_time = deadline.execution_seconds_available(
                    per_pass_cap_seconds=AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS,
                )
            recovery_agent_executor = create_agent_executor(
                langchain_llm,
                list(active_tools_for_recovery) + [finalize_tool_recovery],
                user_profile_context=user_profile_context,
                communication_context_section=communication_context_section,
                custom_instructions_section=custom_instructions_section,
                preloaded_skill_section=selected_skill_section,
                staged_tool_metadata={
                    "stage": "recovery",
                    "loaded_families": loaded_families,
                    "family_count": len(loaded_families),
                    "initial_tool_count": len(core_tools),
                    "expanded_tool_count": len(active_tools_for_recovery) + 1,
                    "expansion_count": len(loaded_families),
                },
                max_execution_time_seconds=recovery_max_execution_time,
            )
            recovered_envelope, intermediate_steps = await attempt_finalization_recovery(
                state=state,
                agent_executor=recovery_agent_executor,
                intermediate_steps=intermediate_steps,
                agent_output=agent_output,
                callbacks=live_callbacks,
            )
            if recovered_envelope:
                final_envelope = recovered_envelope
        
        thinking_history = _collect_emitted_thinking_history(
            live_callbacks,
            langchain_llm,
            synthesis_thinking_history,
        )
        if thinking_history:
            if state.context is None:
                state.context = {}
            state.context["thinking_history"] = thinking_history

        if _timing is not None:
            _timing.stop("finalize")

        # Collect execution timeline from live callback handler
        execution_timeline = []
        if live_callbacks:
            for cb in live_callbacks:
                if hasattr(cb, 'get_execution_timeline'):
                    execution_timeline = cb.get_execution_timeline()
                    break

        if _timing is not None:
            _timing.emit()

        # Process and return result
        return await process_agent_result(
            result=result,
            state=state,
            coordinator=coordinator,
            intermediate_steps=intermediate_steps,
            final_envelope=final_envelope,
            finalize_attempts=finalize_attempts,
            execution_timeline=execution_timeline or None
        )
        
    except ProviderDelegationWaitRequest as delegation_wait:
        return await handle_provider_delegation_wait_request(
            delegation_wait,
            state,
            coordinator,
        )
    except CheckpointRequest as checkpoint_err:
        # Agent explicitly requested user input - collaborative flow, NOT an error
        return await handle_checkpoint_request(checkpoint_err, state, coordinator)
        
    except Exception as e:
        # Execution error with possible recovery from every emitted reasoning source.
        error_thinking_history = _collect_emitted_thinking_history(
            locals().get("live_callbacks"),
            locals().get("langchain_llm"),
            locals().get("synthesis_thinking_history"),
        )
        return handle_execution_error(e, state, thinking_history=error_thinking_history)
