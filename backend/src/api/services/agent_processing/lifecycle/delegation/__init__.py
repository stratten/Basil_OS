"""Executor-neutral delegated child-agent lifecycle components."""

from .briefs import DelegatedAgentBrief, compile_delegated_agent_brief
from .acp_session_controller import AcpDelegatedSessionController
from .internal_agent_executor import InternalAgentTaskExecutor
from .controller import DelegatedAgentController
from .admission import DelegatedAgentAdmissionService, DelegatedChildProposal
from .acp_executor import AcpDelegatedAgentExecutor
from .executor import DelegatedAgentExecutor

__all__ = [
    "AcpDelegatedSessionController",
    "AcpDelegatedAgentExecutor",
    "DelegatedAgentController",
    "DelegatedAgentAdmissionService",
    "DelegatedChildProposal",
    "DelegatedAgentExecutor",
    "DelegatedAgentBrief",
    "InternalAgentTaskExecutor",
    "compile_delegated_agent_brief",
]
