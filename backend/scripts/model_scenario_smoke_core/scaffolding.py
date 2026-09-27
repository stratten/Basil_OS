"""In-process construction of the app services each scenario needs.

Everything here is built by calling the same constructors production code
uses, bypassing only the FastAPI ``app.state`` wiring (which requires the
full ASGI startup lifecycle, including audio/wake-word bring-up) in favor of
direct constructor injection. Each builder is a plain function so the
matrix runner can build once and reuse across every model candidate.
"""

from __future__ import annotations

from functools import lru_cache

from api.dependencies import get_sqlite_knowledge_service
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_orchestrator import (
    AgentTaskOrchestrator,
)
from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
    AgentTaskSubmissionService,
)
from api.services.setup_assistant.agent_graph.setup_agent_runtime import SetupAgentRuntime


@lru_cache()
def get_agent_task_submission_service() -> AgentTaskSubmissionService:
    """Build the direct AgentTask submission path without wake-word audio.

    Mirrors ``WakeWordService._initialize_components``'s wiring (see
    ``api/services/wake_word/wake_word_service.py``) minus the audio
    capture/detector/manager pieces, which are irrelevant here and would
    have real side effects (microphone capture, permission prompts).
    ``websocket_manager=None`` is the orchestrator's own default -- it is
    only used to broadcast UI progress events, which this headless harness
    doesn't need.
    """
    db_service = get_sqlite_knowledge_service()
    orchestrator = AgentTaskOrchestrator(
        llm_service=None,
        websocket_manager=None,
        basil_services=None,
        db_service=db_service,
    )
    return AgentTaskSubmissionService(
        agent_task_orchestrator=orchestrator,
        db_service=db_service,
        wake_word_service=None,
    )


@lru_cache()
def get_setup_agent_runtime() -> SetupAgentRuntime:
    """Build the Setup Wizard's LangChain agent runtime.

    Mirrors the default construction in
    ``api/services/setup_assistant/agent_graph/setup_agent_runtime.py``
    (``context_catalog_service``, ``model_service``, and ``proposal_store``
    all default-construct when omitted).
    """
    return SetupAgentRuntime()
