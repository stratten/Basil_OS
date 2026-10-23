"""LangChain tools for the model-backed setup agent."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.tools import StructuredTool

from api.core.services.model_service import get_model_service
from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupArtifactKind,
    SetupOrientationTone,
    SetupPrivacyImpact,
    SetupSessionAgendaItemStatus,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling import (
    agenda_tools,
    artifact_tools,
    discovery_tools,
    email_demo_tools,
    presentation_tools,
    proposal_tools,
    visual_tools,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling.proposal_store import (
    SetupPendingProposalStore,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling.schemas import (
    SETUP_MESSAGE_DELTA_CHARS,
    SETUP_MESSAGE_DELTA_DELAY_SECONDS,
    SetupAddArtifactRowInput,
    SetupAgendaItemInput,
    SetupCloseArtifactInput,
    SetupDiscoverWritingSampleCandidatesInput,
    SetupEmptyInput,
    SetupMarkAgendaItemInput,
    SetupNarrateProgressInput,
    SetupNoteObservationInput,
    SetupOpenArtifactInput,
    SetupProposeConsentReceiptInput,
    SetupProposeMutationInput,
    SetupProposeSessionAgendaInput,
    SetupProposeWrapUpInput,
    SetupRequestAgendaItemConfirmationInput,
    SetupSayInput,
    SetupSetChipsInput,
    SetupSuggestionChipInput,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling.tool_registry import (
    create_setup_agent_tools_for_factory,
)
from api.services.setup_assistant.context_catalog_service import (
    SetupAgentModelSelection,
    SetupAssistantContextCatalogService,
)
from api.services.setup_assistant.discovery_service import SetupAssistantDiscoveryService


SetupAgentEventEmitter = Callable[[SetupAgentEvent], Awaitable[None]]


class SetupAgentToolFactory:
    """Create setup-agent LangChain tools around presentation, discovery, and proposal calls."""

    def __init__(
        self,
        *,
        event_emitter: SetupAgentEventEmitter,
        proposal_store: SetupPendingProposalStore,
        context_catalog_service: Optional[SetupAssistantContextCatalogService] = None,
        discovery_service: Optional[SetupAssistantDiscoveryService] = None,
        setup_model_selection: Optional[SetupAgentModelSelection] = None,
    ) -> None:
        self.event_emitter = event_emitter
        self.proposal_store = proposal_store
        self.context_catalog_service = context_catalog_service or SetupAssistantContextCatalogService()
        self.discovery_service = discovery_service or SetupAssistantDiscoveryService(get_model_service())
        # Captured at agent-turn build time so proposal/receipt builders can
        # stamp the same model the setup agent is currently using onto
        # outbound launch_agent_task receipts. This is what keeps setup-launched
        # Paprika tasks from silently routing through a user's preferred local
        # reasoning model and hitting llama.cpp context overflows during onboarding.
        self.setup_model_selection = setup_model_selection
        # Monotonic timestamp (seconds) of the most recent narrate_progress
        # event emitted in this turn, regardless of whether it came from the
        # agent or from a slow tool. Used by the slow-tool decorator's
        # staleness guard so tool-emitted opening narrations don't immediately
        # overwrite a fresh agent narration. ``None`` until the first emit.
        self.last_narration_emitted_at: Optional[float] = None
        # Id of the most recently pulled inline email context for the active
        # turn, if any. Set when ``pull_inbox_email_for_dill`` succeeds so the
        # subsequent ``launch_agent_task`` receipt can be auto-stamped with
        # ``source_email_id`` even when the agent forgets to thread it through
        # the payload itself. Cleared between turns by the runtime.
        self.last_pulled_email_id: Optional[str] = None

    def create_setup_agent_tools(self) -> List[StructuredTool]:
        return create_setup_agent_tools_for_factory(self)

    async def note_setup_observation(
        self,
        label: str,
        title: str,
        detail: str,
        tone: SetupOrientationTone = SetupOrientationTone.ready,
    ) -> str:
        return await presentation_tools.note_setup_observation(
            self,
            label=label,
            title=title,
            detail=detail,
            tone=tone,
        )

    async def narrate_setup_progress(self, message: str) -> str:
        return await presentation_tools.narrate_setup_progress(self, message)

    async def set_setup_suggestion_chips(self, chips: List[SetupSuggestionChipInput]) -> str:
        return await presentation_tools.set_setup_suggestion_chips(self, chips)

    async def propose_setup_mutation(
        self,
        title: str,
        rationale: str,
        tool_name: str,
        payload: Dict[str, Any],
        proposal_id: Optional[str] = None,
        privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none,
        mutates_external_state: bool = False,
        required_permissions: Optional[List[str]] = None,
    ) -> str:
        return await proposal_tools.propose_setup_mutation(
            self,
            title=title,
            rationale=rationale,
            tool_name=tool_name,
            payload=payload,
            proposal_id=proposal_id,
            privacy_impact=privacy_impact,
            mutates_external_state=mutates_external_state,
            required_permissions=required_permissions,
        )

    async def propose_setup_consent_receipt(
        self,
        title: str,
        rationale: str,
        mutation_tool_name: str,
        mutation_payload: Dict[str, Any],
        proposal_id: Optional[str] = None,
        privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none,
        mutates_external_state: bool = False,
        required_permissions: Optional[List[str]] = None,
    ) -> str:
        return await proposal_tools.propose_setup_consent_receipt(
            self,
            title=title,
            rationale=rationale,
            mutation_tool_name=mutation_tool_name,
            mutation_payload=mutation_payload,
            proposal_id=proposal_id,
            privacy_impact=privacy_impact,
            mutates_external_state=mutates_external_state,
            required_permissions=required_permissions,
        )

    async def open_setup_artifact(
        self,
        artifact_id: str,
        kind: SetupArtifactKind,
        title: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        return await artifact_tools.open_setup_artifact(
            self,
            artifact_id=artifact_id,
            kind=kind,
            title=title,
            payload=payload,
        )

    async def add_setup_artifact_row(
        self,
        artifact_id: str,
        row_id: str,
        payload: Dict[str, Any],
        receipt: Optional[SetupProposeConsentReceiptInput] = None,
    ) -> str:
        return await artifact_tools.add_setup_artifact_row(
            self,
            artifact_id=artifact_id,
            row_id=row_id,
            payload=payload,
            receipt=receipt,
        )

    async def close_setup_artifact(self, artifact_id: str) -> str:
        return await artifact_tools.close_setup_artifact(self, artifact_id)

    async def say_setup_message(self, content: str) -> str:
        return await presentation_tools.say_setup_message(self, content)

    def _chunk_setup_message_content(self, content: str) -> List[str]:
        return presentation_tools.chunk_setup_message_content(content)

    async def propose_setup_wrap_up(
        self,
        recap: str,
        recommended_next_steps: Optional[List[SetupSuggestionChipInput]] = None,
        optional_breadth: Optional[str] = None,
    ) -> str:
        return await presentation_tools.propose_setup_wrap_up(
            self,
            recap=recap,
            recommended_next_steps=recommended_next_steps,
            optional_breadth=optional_breadth,
        )

    async def discover_setup_email_clients(self) -> Dict[str, Any]:
        return await discovery_tools.discover_setup_email_clients(self)

    async def discover_setup_connections(self) -> Dict[str, Any]:
        return await discovery_tools.discover_setup_connections(self)

    async def discover_setup_local_models(self) -> Dict[str, Any]:
        return await discovery_tools.discover_setup_local_models(self)

    async def discover_setup_profile(self) -> Dict[str, Any]:
        return await discovery_tools.discover_setup_profile(self)

    async def discover_setup_writing_sample_candidates(
        self,
        days_back: int = 14,
        limit: int = 25,
    ) -> Dict[str, Any]:
        return await discovery_tools.discover_setup_writing_sample_candidates(
            self,
            days_back=days_back,
            limit=limit,
        )

    async def discover_setup_permissions(self) -> Dict[str, Any]:
        return await discovery_tools.discover_setup_permissions(self)

    async def peek_recent_inbox_emails(self, limit: int = 10) -> Dict[str, Any]:
        return await email_demo_tools.peek_recent_inbox_emails(self, limit=limit)

    async def pull_inbox_email_for_dill(
        self,
        email_id: str,
        max_excerpt_chars: int = 2000,
    ) -> Dict[str, Any]:
        return await email_demo_tools.pull_inbox_email_for_dill(
            self,
            email_id=email_id,
            max_excerpt_chars=max_excerpt_chars,
        )

    async def propose_session_agenda(
        self,
        items: List[SetupAgendaItemInput],
    ) -> str:
        return await agenda_tools.propose_session_agenda(self, items=items)

    async def mark_agenda_item(
        self,
        id: str,
        status: SetupSessionAgendaItemStatus,
        completion_basis: Optional[str] = None,
    ) -> str:
        return await agenda_tools.mark_agenda_item(
            self,
            id=id,
            status=status,
            completion_basis=completion_basis,
        )

    async def request_agenda_item_confirmation(
        self,
        agenda_item_id: str,
        prompt: str,
    ) -> str:
        return await agenda_tools.request_agenda_item_confirmation(
            self,
            agenda_item_id=agenda_item_id,
            prompt=prompt,
        )

    async def show_setup_visual(
        self,
        visual_id: str,
        caption_override: Optional[str] = None,
    ) -> str:
        return await visual_tools.show_setup_visual(
            self,
            visual_id=visual_id,
            caption_override=caption_override,
        )

    def _validate_setup_tool_name(self, tool_name: str) -> None:
        proposal_tools.validate_setup_tool_name(self, tool_name)
