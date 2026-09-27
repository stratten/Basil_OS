"""Streaming facade for Basil's LangChain-backed setup agent."""

from __future__ import annotations

from typing import AsyncIterator, Optional

from api.core.services.model_service import ModelService
from api.routes.setup_assistant.models import SetupAgentEvent, SetupAgentRequest
from api.services.setup_assistant.agent_graph.setup_agent_runtime import SetupAgentRuntime
from api.services.setup_assistant.agent_graph.setup_agent_tools import SetupPendingProposalStore
from api.services.setup_assistant.context_catalog_service import SetupAssistantContextCatalogService


class SetupAssistantAgentService:
    """Run Basil setup turns through the shared LangChain agent infrastructure."""

    def __init__(
        self,
        *,
        context_catalog_service: Optional[SetupAssistantContextCatalogService] = None,
        model_service: Optional[ModelService] = None,
        proposal_store: Optional[SetupPendingProposalStore] = None,
        runtime: Optional[SetupAgentRuntime] = None,
    ) -> None:
        self.context_catalog_service = context_catalog_service or SetupAssistantContextCatalogService()
        self.model_service = model_service
        self.proposal_store = proposal_store or SetupPendingProposalStore()
        self.runtime = runtime or SetupAgentRuntime(
            context_catalog_service=self.context_catalog_service,
            model_service=self.model_service,
            proposal_store=self.proposal_store,
        )

    async def respond_stream(
        self,
        request: SetupAgentRequest,
        finalize_mode: bool = False,
    ) -> AsyncIterator[SetupAgentEvent]:
        """Yield setup-agent events as Basil reasons and calls setup tools.

        ``finalize_mode`` is set by the synchronous ``/agent/finalize`` endpoint so the
        system prompt nudges the model to call ``propose_wrap_up`` immediately and exit.
        """

        async for event in self.runtime.respond_stream(request, finalize_mode=finalize_mode):
            yield event

    def get_pending_setup_proposal(self, proposal_id: str):
        """Return a pending setup proposal captured by the active runtime."""

        return self.proposal_store.get_pending_setup_proposal(proposal_id)
