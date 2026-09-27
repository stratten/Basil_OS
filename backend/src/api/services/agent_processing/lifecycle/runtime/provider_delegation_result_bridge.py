"""Compatibility import for the executor-neutral delegated-agent result bridge."""

from .delegated_agent_result_bridge import DelegatedAgentResultBridge

ProviderDelegationResultBridge = DelegatedAgentResultBridge

__all__ = ["DelegatedAgentResultBridge", "ProviderDelegationResultBridge"]
