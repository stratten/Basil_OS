"""ACP implementation of the generic delegated-agent executor contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .acp_session_controller import AcpDelegatedSessionController


class AcpDelegatedAgentExecutor:
    """Persist each ACP turn around one already-established provider session."""

    def __init__(
        self,
        *,
        delegated_agent_repository: Any,
        session_controller: AcpDelegatedSessionController,
        evidence_capture_service: Any | None = None,
    ) -> None:
        self._runs = delegated_agent_repository
        self._sessions = session_controller
        self._evidence_capture = evidence_capture_service

    async def start_turn(
        self,
        *,
        delegated_agent_run_id: str,
        instruction: str,
    ) -> Mapping[str, Any]:
        """Deliver one initial or supervisory instruction and preserve idle evidence."""

        return await self._send_turn(
            delegated_agent_run_id=delegated_agent_run_id,
            instruction=instruction,
        )

    async def request_follow_up(
        self,
        *,
        delegated_agent_run_id: str,
        instruction: str,
    ) -> Mapping[str, Any]:
        """Deliver a follow-up only through the same admitted ACP session."""

        return await self._send_turn(
            delegated_agent_run_id=delegated_agent_run_id,
            instruction=instruction,
        )

    async def cancel(self, *, delegated_agent_run_id: str) -> None:
        """Stop the process after the controller has fenced future turns."""

        await self._sessions.cancel(delegated_agent_run_id=delegated_agent_run_id)

    async def reconcile(self, *, delegated_agent_run_id: str) -> Mapping[str, Any]:
        """Report that an in-process ACP session cannot survive a restart."""

        run = await self._require_run(delegated_agent_run_id)
        return {
            "delegated_agent_run_id": str(run["id"]),
            "run_status": str(run["status"]),
            "session": dict(self._sessions.describe(delegated_agent_run_id)),
        }

    async def collect_outcome(
        self,
        *,
        delegated_agent_run_id: str,
    ) -> Mapping[str, Any]:
        """Return only the durable generic state; raw provider output stays in turns."""

        run = await self._require_run(delegated_agent_run_id)
        return {
            "delegated_agent_run_id": str(run["id"]),
            "status": str(run["status"]),
            "settled_at": run.get("settled_at"),
        }

    async def _send_turn(
        self,
        *,
        delegated_agent_run_id: str,
        instruction: str,
    ) -> Mapping[str, Any]:
        run = await self._require_run(delegated_agent_run_id)
        turn = await self._runs.start_turn(
            delegated_agent_run_id=delegated_agent_run_id,
            expected_revision=int(run["revision"]),
            controller_instruction=instruction,
        )
        turn_id = str(turn["id"])
        self._sessions.begin_evidence_capture(
            delegated_agent_run_id=delegated_agent_run_id,
            delegated_agent_turn_id=turn_id,
        )
        try:
            response = await self._sessions.send_follow_up(
                delegated_agent_run_id=delegated_agent_run_id,
                instruction=instruction,
            )
        except Exception as exc:
            await self._runs.transition_run(
                delegated_agent_run_id=delegated_agent_run_id,
                expected_revision=int(run["revision"]) + 1,
                next_status="supervision_due",
                event_data={"reason": type(exc).__name__},
            )
            raise
        finally:
            self._sessions.end_evidence_capture(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=turn_id,
            )
        if self._evidence_capture is not None:
            await self._evidence_capture.capture_terminal_response(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=turn_id,
                response=response,
            )
        settled = await self._runs.settle_turn_idle(
            delegated_agent_run_id=delegated_agent_run_id,
            turn_id=turn_id,
            expected_revision=int(run["revision"]) + 1,
            terminal_response=response,
        )
        return {"run": settled, "turn": turn, "terminal_response": dict(response)}

    async def record_interaction_wait(
        self,
        *,
        delegated_agent_run_id: str,
        expected_revision: int,
        permission: bool,
    ) -> Mapping[str, Any]:
        """Persist a waiting state without asserting a terminal child result."""

        return await self._runs.transition_run(
            delegated_agent_run_id=delegated_agent_run_id,
            expected_revision=expected_revision,
            next_status="waiting_permission" if permission else "waiting_user_input",
        )

    async def record_transport_failure(
        self,
        *,
        delegated_agent_run_id: str,
        expected_revision: int,
        reason: str,
    ) -> Mapping[str, Any]:
        """Preserve a nonterminal transport failure for parent-controlled supervision."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("transport failure reason must be nonblank")
        return await self._runs.transition_run(
            delegated_agent_run_id=delegated_agent_run_id,
            expected_revision=expected_revision,
            next_status="supervision_due",
            event_data={"reason": reason.strip()[:200]},
        )

    async def _require_run(self, delegated_agent_run_id: str) -> Mapping[str, Any]:
        run = await self._runs.get_run(delegated_agent_run_id)
        if run is None:
            raise RuntimeError("delegated-agent run does not exist")
        if str(run["executor_kind"]) != "acp_provider":
            raise RuntimeError("delegated-agent run is not an ACP provider child")
        return run
