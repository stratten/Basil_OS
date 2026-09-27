"""Executor protocol shared by ACP and Basil-native delegated children."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class DelegatedAgentExecutor(Protocol):
    """A concrete child runtime owned by the generic delegation controller."""

    async def start_turn(
        self,
        *,
        delegated_agent_run_id: str,
        instruction: str,
    ) -> Mapping[str, Any]:
        """Begin exactly one durable delegated-agent turn."""

    async def request_follow_up(
        self,
        *,
        delegated_agent_run_id: str,
        instruction: str,
    ) -> Mapping[str, Any]:
        """Send an allowed follow-up only after the prior turn is idle."""

    async def cancel(self, *, delegated_agent_run_id: str) -> None:
        """Cancel all process or AgentTask work owned by this delegated run."""

    async def reconcile(self, *, delegated_agent_run_id: str) -> Mapping[str, Any]:
        """Return restart-safe runtime evidence without creating a new child."""

    async def collect_outcome(
        self,
        *,
        delegated_agent_run_id: str,
    ) -> Mapping[str, Any]:
        """Return bounded terminal executor evidence for generic settlement."""
