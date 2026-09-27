"""Runtime for the LangChain-backed Basil setup agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_classic.agents import AgentExecutor
from langchain_classic.agents.format_scratchpad.tools import format_to_tool_messages
from langchain_classic.agents.output_parsers.tools import ToolsAgentOutputParser
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.auth_proxy_model import AuthProxyModel
from api.core.models.reasoning.model_runtime_profile import (
    resolve_runtime_model_profile,
)
from api.core.services.model_service import ModelService, get_model_service
from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupAgentRequest,
    SetupAssistantPhase,
)
from api.services.setup_assistant.agent_graph.agenda_catalog import (
    applicable_catalog_seed,
)
from api.services.agent_processing.lifecycle.execution_graph.auth_proxy_langchain_adapter import (
    create_langchain_llm_from_auth_proxy,
)
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    create_langchain_llm_from_llama_cpp,
)
from api.services.setup_assistant.agent_graph.setup_agent_progress import SetupAgentProgressCallback
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
    build_setup_agent_system_prompt,
)
from api.services.setup_assistant.agent_graph.setup_agent_tools import (
    SetupAgentToolFactory,
    SetupPendingProposalStore,
)
from api.services.setup_assistant.context_catalog_service import (
    SetupAgentModelSelection,
    SetupAssistantContextCatalogService,
)

logger = logging.getLogger(__name__)
SETUP_AGENT_PROXY_MARKER = "setup_agent"


class SetupAgentRuntime:
    """Run setup turns through a tool-calling LangChain agent and stream UI events."""

    def __init__(
        self,
        *,
        context_catalog_service: Optional[SetupAssistantContextCatalogService] = None,
        model_service: Optional[ModelService] = None,
        proposal_store: Optional[SetupPendingProposalStore] = None,
    ) -> None:
        self.context_catalog_service = context_catalog_service or SetupAssistantContextCatalogService()
        self.model_service = model_service or get_model_service()
        self.proposal_store = proposal_store or SetupPendingProposalStore()

    async def respond_stream(
        self,
        request: SetupAgentRequest,
        finalize_mode: bool = False,
    ) -> AsyncIterator[SetupAgentEvent]:
        event_queue: asyncio.Queue[SetupAgentEvent] = asyncio.Queue()
        done_event = asyncio.Event()
        emitted_message_content = False

        async def emit_event(event: SetupAgentEvent) -> None:
            nonlocal emitted_message_content
            if event.kind == SetupAgentEventKind.message_completed:
                emitted_message_content = True
            await event_queue.put(event)

        async def run_agent_turn() -> None:
            try:
                await emit_event(SetupAgentEvent(kind=SetupAgentEventKind.turn_started))
                executor = await self._build_setup_agent_executor(
                    emit_event, request, finalize_mode=finalize_mode
                )
                result = await executor.ainvoke(
                    {
                        "input": self._build_setup_turn_input(request),
                        "chat_history": self._build_setup_chat_history(request),
                    },
                    config={"callbacks": [SetupAgentProgressCallback(emit_event)]},
                )
                output = result.get("output") if isinstance(result, dict) else None
                if (
                    not emitted_message_content
                    and isinstance(output, str)
                    and output.strip()
                ):
                    message_id = f"message-{id(result)}"
                    await emit_event(
                        SetupAgentEvent(
                            kind=SetupAgentEventKind.message_started,
                            payload={"id": message_id, "role": "basil"},
                        )
                    )
                    await emit_event(
                        SetupAgentEvent(
                            kind=SetupAgentEventKind.message_delta,
                            payload={"id": message_id, "delta": output},
                        )
                    )
                    await emit_event(
                        SetupAgentEvent(
                            kind=SetupAgentEventKind.message_completed,
                            payload={
                                "id": message_id,
                                "role": "basil",
                                "content": output,
                            },
                        )
                    )
                await emit_event(SetupAgentEvent(kind=SetupAgentEventKind.turn_complete))
            except Exception as exc:
                logger.warning("Setup agent turn failed: %s", exc)
                await emit_event(
                    SetupAgentEvent(
                        kind=SetupAgentEventKind.error,
                        payload={"message": str(exc)},
                    )
                )
            finally:
                done_event.set()

        task = asyncio.create_task(run_agent_turn())
        try:
            while not done_event.is_set() or not event_queue.empty():
                try:
                    yield await asyncio.wait_for(event_queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
        finally:
            if not task.done():
                task.cancel()

    async def _build_setup_agent_executor(
        self,
        event_emitter: Any,
        request: SetupAgentRequest,
        finalize_mode: bool = False,
    ) -> AgentExecutor:
        model_selection = self.context_catalog_service.resolve_setup_agent_model(
            request.setup_agent_model_override_id,
            request.setup_agent_model_access,
        )
        langchain_model = await self._create_setup_langchain_model(model_selection)
        tools = SetupAgentToolFactory(
            event_emitter=event_emitter,
            proposal_store=self.proposal_store,
            context_catalog_service=self.context_catalog_service,
            setup_model_selection=model_selection,
        ).create_setup_agent_tools()
        capture_state = self._load_current_capture_state()
        system_prompt = build_setup_agent_system_prompt(
            capture_state, finalize_mode=finalize_mode
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("placeholder", "{chat_history}"),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )
        llm_with_tools = langchain_model.bind_tools(tools).with_retry(
            stop_after_attempt=3,
            wait_exponential_jitter=True,
        )
        agent = (
            RunnablePassthrough.assign(
                agent_scratchpad=lambda values: format_to_tool_messages(values["intermediate_steps"])
            )
            | prompt
            | llm_with_tools
            | RunnableLambda(lambda output: output)
            | ToolsAgentOutputParser()
        )
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
            max_execution_time=600,
        )

    async def _create_setup_langchain_model(self, model_selection: SetupAgentModelSelection) -> Any:
        if model_selection.is_local:
            model_type, variant = model_selection.model_type_and_variant
            model = await self.model_service.load_model(
                model_type=model_type,
                variant=variant,
                capabilities={ModelCapability.REASONING},
                registry_model_id=model_selection.model_id,
            )
            return create_langchain_llm_from_llama_cpp(
                model,
                profile=resolve_runtime_model_profile(model),
            )

        proxy_model = AuthProxyModel(
            model_id=model_selection.model_id,
            access_token=None,
            trial_key=None,
            setup_agent_key=SETUP_AGENT_PROXY_MARKER,
        )
        return create_langchain_llm_from_auth_proxy(proxy_model)

    def _build_setup_turn_input(self, request: SetupAgentRequest) -> str:
        seeded_agenda_items = self._resolve_agenda_items_for_turn(request)
        context_payload: Dict[str, Any] = {
            "phase": request.phase.value,
            "technical_depth": request.technical_depth.value,
            "discovery_facts": [fact.model_dump(mode="json") for fact in request.discovery_facts],
            "setup_agent_model_access": request.setup_agent_model_access.model_dump(mode="json"),
            "calibration_events": [event.model_dump(mode="json") for event in request.calibration_events],
            "current_step_context": request.current_step_context,
            "execution_outcomes": request.execution_outcomes,
            "session_goals": request.session_goals,
            "agenda_items": seeded_agenda_items,
            "available_mutation_tools": [
                tool.model_dump(mode="json")
                for tool in self.context_catalog_service.build_available_tools()
            ],
        }
        agent_task_observations_block = self._format_agent_task_observations(
            request.execution_outcomes
        )
        agenda_confirmation_block = self._format_agenda_confirmation_observations(
            request.execution_outcomes
        )
        agenda_state_block = self._format_agenda_state(
            session_goals=request.session_goals,
            seeded_agenda_items=seeded_agenda_items,
        )
        sections: List[str] = [
            "User's latest setup message:",
            request.latest_message,
            "",
        ]
        if agent_task_observations_block:
            sections.extend([
                "Launched agent-task observations (you must react to these; they came",
                "from the native poller, not the user):",
                agent_task_observations_block,
                "",
            ])
        if agenda_confirmation_block:
            sections.extend([
                "Agenda-confirmation responses (you must react to these; they came",
                "from the user clicking an inline confirmation card, not a chat message):",
                agenda_confirmation_block,
                "",
            ])
        if agenda_state_block:
            sections.extend([agenda_state_block, ""])
        sections.extend([
            "Current setup context:",
            str(context_payload),
        ])
        return "\n".join(sections)

    def _resolve_agenda_items_for_turn(
        self,
        request: SetupAgentRequest,
    ) -> List[Dict[str, Any]]:
        """Decide what the agent sees in `agenda_items` for this turn.

        - On the FIRST conversation-phase turn (agent_synthesis phase,
          no session_goals yet, no agenda_items already provided by
          the frontend), inject the discovery-filtered catalog seed so
          the agent has concrete material to base `propose_session_agenda`
          on. The seed is the menu; the agent picks/trims/adds.
        - On every other turn (orientation, post-proposal conversation,
          finalize), pass through whatever the frontend sent so we don't
          spuriously re-seed after the agent has already laid out an
          agenda. Once `session_goals` is populated, the agent works
          from that.
        """
        existing_items = list(request.agenda_items or [])
        if existing_items:
            return existing_items
        if request.phase != SetupAssistantPhase.agent_synthesis:
            return []
        if request.session_goals:
            return []
        return applicable_catalog_seed(request.discovery_facts)

    @staticmethod
    def _format_agenda_state(
        *,
        session_goals: List[Dict[str, Any]],
        seeded_agenda_items: List[Dict[str, Any]],
    ) -> str:
        """Promote the active agenda + seed to a labeled block.

        When `session_goals` is populated, render it as "Current session
        agenda" so the agent always sees what's pending vs. completed.
        When only the seed is present (first conversation turn), render
        it as "Seeded catalog (call propose_session_agenda to adopt)"
        so the agent treats it as input material rather than already-
        adopted state.
        """
        if session_goals:
            lines = ["Current session agenda (sidebar state — pick from here):"]
            for index, item in enumerate(session_goals, start=1):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id", "<unknown>")
                title = item.get("title", "<untitled>")
                status = item.get("status", "pending")
                kind = item.get("kind", "")
                kind_suffix = f" ({kind})" if kind else ""
                lines.append(f"  {index}. [{status}] {item_id}{kind_suffix}: {title}")
                intent = item.get("intent")
                if isinstance(intent, str) and intent.strip():
                    lines.append(f"     intent: {intent.strip()}")
            return "\n".join(lines)
        if seeded_agenda_items:
            lines = [
                "Seeded agenda catalog (this is the starter menu — call "
                "propose_session_agenda once you've decided what to keep, "
                "reshape, drop, or add):",
            ]
            for index, item in enumerate(seeded_agenda_items, start=1):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id", "<unknown>")
                title = item.get("title", "<untitled>")
                kind = item.get("kind", "")
                kind_suffix = f" ({kind})" if kind else ""
                lines.append(f"  {index}. {item_id}{kind_suffix}: {title}")
                intent = item.get("intent")
                if isinstance(intent, str) and intent.strip():
                    lines.append(f"     intent: {intent.strip()}")
            return "\n".join(lines)
        return ""

    @staticmethod
    def _format_agenda_confirmation_observations(
        execution_outcomes: List[Dict[str, Any]],
    ) -> str:
        """Promote agenda_confirmation_resolved entries to a labeled block.

        The frontend dispatches one of these whenever the user clicks
        Yes / Not quite / Skip on an inline AgendaConfirmationCard.
        Returns the empty string when no such observations are present.
        """
        relevant = [
            outcome for outcome in execution_outcomes
            if isinstance(outcome, dict)
            and outcome.get("kind") == "agenda_confirmation_resolved"
        ]
        if not relevant:
            return ""
        lines: List[str] = []
        for index, outcome in enumerate(relevant, start=1):
            agenda_item_id = outcome.get("agenda_item_id", "<unknown>")
            resolution = outcome.get("resolution", "<unknown>")
            confirmation_id = outcome.get("confirmation_id", "<unknown>")
            lines.append(
                f"  {index}. agenda_item_id={agenda_item_id} "
                f"resolution={resolution} confirmation_id={confirmation_id}"
            )
            prompt = outcome.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                lines.append(f"     prompt_asked: {prompt.strip()}")
        return "\n".join(lines)

    @staticmethod
    def _format_agent_task_observations(
        execution_outcomes: List[Dict[str, Any]],
    ) -> str:
        """Promote agent_task_progress / agent_task_terminal entries to a labeled
        block so the agent does not have to dig them out of the opaque context dump.
        Returns the empty string when no such observations are present.
        """
        agent_task_kinds = {"agent_task_progress", "agent_task_terminal"}
        relevant = [
            outcome for outcome in execution_outcomes
            if isinstance(outcome, dict) and outcome.get("kind") in agent_task_kinds
        ]
        if not relevant:
            return ""
        lines: List[str] = []
        for index, outcome in enumerate(relevant, start=1):
            kind = outcome.get("kind", "agent_task_progress")
            label = "TERMINAL" if kind == "agent_task_terminal" else "PROGRESS"
            agent_task_id = outcome.get("agent_task_id", "<unknown>")
            status = outcome.get("status", "<unknown>")
            lines.append(f"  {index}. [{label}] agent_task_id={agent_task_id} status={status}")
            current_step = outcome.get("current_step")
            if current_step:
                lines.append(f"     current_step: {current_step}")
            result_message = outcome.get("result_message")
            if result_message:
                lines.append(f"     result_message: {result_message}")
            error_message = outcome.get("error_message")
            if error_message:
                lines.append(f"     error_message: {error_message}")
        return "\n".join(lines)

    def _build_setup_chat_history(self, request: SetupAgentRequest) -> List[Any]:
        messages: List[Any] = []
        for message in request.chat_history[-12:]:
            if message.role.value == "system":
                messages.append(SystemMessage(content=message.content))
            elif message.role.value == "basil":
                messages.append(AIMessage(content=message.content))
            else:
                messages.append(HumanMessage(content=message.content))
        return messages

    def _load_current_capture_state(self) -> Optional[Any]:
        """Load preferences.memory_intelligence once for this turn so the system prompt can be honest about capture state."""
        try:
            from api.core.preferences.preferences_io import load_preferences
            return load_preferences().memory_intelligence
        except Exception as exc:  # pragma: no cover - capture-state read failure is non-fatal
            logger.warning("Could not load memory_intelligence settings for setup agent prompt: %s", exc)
            return None

