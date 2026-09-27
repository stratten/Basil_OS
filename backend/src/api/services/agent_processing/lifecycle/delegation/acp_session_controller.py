"""Long-lived, one-at-a-time ACP delegated-agent turn controller."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from api.services.agent_providers.runtime.process_supervisor import ProviderLaunchOutcomeStatus


@dataclass
class ActiveAcpDelegatedSession:
    """The in-process capability required for a supervised ACP follow-up turn."""

    provider_run_id: str
    delegated_agent_run_id: str
    supervisor: Any
    session_id: str
    in_flight: bool = False
    cancelling: bool = False
    interaction_ids: set[str] | None = None
    safe_final_message: str | None = None
    safe_receipts: tuple[dict[str, Any], ...] = ()
    runtime_identity: dict[str, Any] | None = None
    evidence_turn_id: str | None = None

    def __post_init__(self) -> None:
        if self.interaction_ids is None:
            self.interaction_ids = set()


class AcpDelegatedSessionController:
    """Own active ACP sessions until the generic controller settles their work."""

    def __init__(self) -> None:
        self._sessions: dict[str, ActiveAcpDelegatedSession] = {}

    def register(
        self,
        *,
        provider_run_id: str,
        delegated_agent_run_id: str,
        supervisor: Any,
        session_id: str,
        runtime_identity: Mapping[str, Any] | None = None,
    ) -> None:
        if delegated_agent_run_id in self._sessions:
            raise RuntimeError("delegated ACP session is already registered")
        self._sessions[delegated_agent_run_id] = ActiveAcpDelegatedSession(
            provider_run_id=provider_run_id,
            delegated_agent_run_id=delegated_agent_run_id,
            supervisor=supervisor,
            session_id=session_id,
            runtime_identity=dict(runtime_identity) if isinstance(runtime_identity, Mapping) else None,
        )

    async def send_follow_up(
        self,
        *,
        delegated_agent_run_id: str,
        instruction: str,
    ) -> Mapping[str, Any]:
        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            raise RuntimeError("delegated ACP session is unavailable for a follow-up turn")
        if active.cancelling:
            raise RuntimeError("delegated ACP session is cancelling")
        if active.in_flight:
            raise RuntimeError("delegated ACP session already has an in-flight turn")
        if active.interaction_ids:
            raise RuntimeError("delegated ACP session has unresolved provider interaction")
        active.in_flight = True
        try:
            response = await active.supervisor.send_prompt(
                session_id=active.session_id,
                prompt=[{"type": "text", "text": instruction}],
            )
        except BaseException:
            active.in_flight = False
            raise
        active.in_flight = False
        active.supervisor.mark_turn_idle()
        return dict(response)

    async def close(
        self,
        *,
        delegated_agent_run_id: str,
        terminal_run: Mapping[str, Any],
    ) -> Any | None:
        """Release a session only after the matching generic run is durable-terminal."""
        if str(terminal_run.get("id")) != delegated_agent_run_id:
            raise RuntimeError("terminal delegated run does not match the ACP session")
        if terminal_run.get("status") not in {"settled", "failed", "cancelled"}:
            raise RuntimeError("ACP session may close only after generic terminal settlement")
        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            return None
        completed = await active.supervisor.complete_turn()
        self._sessions.pop(delegated_agent_run_id, None)
        return completed

    async def cancel(self, *, delegated_agent_run_id: str) -> None:
        """Fence a live ACP process and discard it only after cancellation returns."""
        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            return
        active.cancelling = True
        try:
            outcome = getattr(active.supervisor, "last_outcome", None)
            if outcome is not None and getattr(outcome, "status", None) is not ProviderLaunchOutcomeStatus.RUNNING:
                return
            await active.supervisor.cancel()
        finally:
            self._sessions.pop(delegated_agent_run_id, None)

    def interaction_opened(self, *, delegated_agent_run_id: str, interaction_id: str) -> None:
        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            return
        if not interaction_id.strip():
            raise ValueError("interaction_id must be nonblank")
        active.interaction_ids.add(interaction_id)

    def interaction_resolved(self, *, delegated_agent_run_id: str, interaction_id: str) -> None:
        active = self._sessions.get(delegated_agent_run_id)
        if active is not None:
            active.interaction_ids.discard(interaction_id)

    def begin_evidence_capture(self, *, delegated_agent_run_id: str, delegated_agent_turn_id: str) -> None:
        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            raise RuntimeError("delegated ACP session is unavailable for evidence capture")
        if active.evidence_turn_id is not None:
            raise RuntimeError("delegated ACP session already has an evidence capture turn")
        active.evidence_turn_id = delegated_agent_turn_id

    def end_evidence_capture(self, *, delegated_agent_run_id: str, delegated_agent_turn_id: str) -> None:
        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            return
        if active.evidence_turn_id == delegated_agent_turn_id:
            active.evidence_turn_id = None

    def active_evidence_turn_id(self, *, delegated_agent_run_id: str) -> str | None:
        active = self._sessions.get(delegated_agent_run_id)
        return active.evidence_turn_id if active is not None else None

    def record_safe_activity(
        self,
        *,
        delegated_agent_run_id: str,
        final_message: str | None = None,
        receipt: Mapping[str, Any] | None = None,
    ) -> None:
        """Retain bounded summaries only; raw provider activity never enters this controller."""

        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            return
        if final_message is not None:
            active.safe_final_message = final_message[:4_000]
        if receipt is not None:
            safe_receipt = {str(key): value for key, value in receipt.items() if str(key) in {"kind", "state", "id"}}
            active.safe_receipts = (*active.safe_receipts[-19:], safe_receipt)

    def describe(self, delegated_agent_run_id: str) -> Mapping[str, Any]:
        """Return non-sensitive live-session presence for restart-safe supervision."""

        active = self._sessions.get(delegated_agent_run_id)
        if active is None:
            return {"available": False}
        return {
            "available": True,
            "provider_run_id": active.provider_run_id,
            "session_id": active.session_id,
            "in_flight": active.in_flight,
            "cancelling": active.cancelling,
            "interaction_pending": bool(active.interaction_ids),
            "safe_final_message": active.safe_final_message,
            "safe_receipts": list(active.safe_receipts),
        }

    def contains(self, delegated_agent_run_id: str) -> bool:
        return delegated_agent_run_id in self._sessions

    def get_runtime_identity(self, delegated_agent_run_id: str) -> Mapping[str, Any] | None:
        """Return the immutable tuple required to certify an ACP follow-up."""

        active = self._sessions.get(delegated_agent_run_id)
        return dict(active.runtime_identity) if active and active.runtime_identity is not None else None
