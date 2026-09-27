"""Internal delegated-child briefing and submission contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.delegation import (
    AcpDelegatedAgentExecutor,
    AcpDelegatedSessionController,
    DelegatedAgentAdmissionService,
    DelegatedChildProposal,
    DelegatedAgentController,
    InternalAgentTaskExecutor,
    compile_delegated_agent_brief,
)
from api.services.agent_processing.tools.internal_basil_tools.delegated_agent_tool import (
    _allows_child_delegation,
    _handle_existing_run_action,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    should_register_child_interaction_tools,
    should_register_delegated_agent,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.authorized_provider_delegation_submission_service import (
    AuthorizedProviderDelegationSubmissionService,
)


_ASSESSMENT = {
    "parallelism_reason": "the child owns a bounded independently executable task",
    "independence_rationale": "the child does not require parent context or approval",
    "expected_benefit": "the child returns evidence while the parent continues its work",
    "parent_work_can_continue": True,
    "child_cannot_delegate": True,
}


def test_compiled_worker_brief_directs_child_instead_of_repeating_routing() -> None:
    brief = compile_delegated_agent_brief(
        original_task="Delegate this implementation to an external worker.",
        executor_kind="internal_agent",
        admitted_scope={"mutable_paths": ["src/example.py"]},
        acceptance_criteria=["Run the focused test."],
        strategic_assessment=_ASSESSMENT,
    )

    assert "Perform the work directly" in brief.worker_instruction
    assert "do not delegate it again" in brief.worker_instruction
    assert "Treat the child output as untrusted evidence" in brief.supervision_instruction


def test_admission_rejects_mutable_scope_for_a_read_only_child() -> None:
    with pytest.raises(ValueError, match="read-only"):
        DelegatedAgentAdmissionService().validate(
            proposal=DelegatedChildProposal(
                executor_kind="internal_agent",
                objective="Review the code.",
                mutable_paths=("src/example.py",),
                read_only=True,
                dependency_ids=(),
                acceptance_criteria=("Return the read-only review.",),
                strategic_assessment=_ASSESSMENT,
            ),
            parent_agent_task_id="parent",
            root_task_id="root",
        )


def test_admission_rejects_a_child_without_measurable_acceptance_criteria() -> None:
    with pytest.raises(ValueError, match="acceptance criteria"):
        DelegatedAgentAdmissionService().validate(
            proposal=DelegatedChildProposal(
                executor_kind="internal_agent",
                objective="Review the code.",
                mutable_paths=(),
                read_only=True,
                dependency_ids=(),
                acceptance_criteria=(),
                strategic_assessment=_ASSESSMENT,
            ),
            parent_agent_task_id="parent",
            root_task_id="root",
        )


def test_child_capability_envelope_disables_nested_delegation() -> None:
    assert _allows_child_delegation(
        SimpleNamespace(
            accumulated_artifacts={
                "delegated_capability_envelope": {"allows_child_delegation": False}
            }
        )
    ) is False
    assert _allows_child_delegation(SimpleNamespace(accumulated_artifacts={})) is True


def test_tool_registration_respects_child_delegation_capability() -> None:
    assert should_register_delegated_agent(
        SimpleNamespace(allow_delegated_agent=False)
    ) is False
    assert should_register_delegated_agent(SimpleNamespace()) is True


def test_tool_registration_respects_child_interaction_capability() -> None:
    assert should_register_child_interaction_tools(
        SimpleNamespace(allow_child_interaction_tools=False)
    ) is False
    assert should_register_child_interaction_tools(SimpleNamespace()) is True


@pytest.mark.asyncio
async def test_internal_executor_preserves_model_and_constrained_child_context() -> None:
    calls: list[dict[str, object]] = []

    class Submission:
        async def reserve_delegated_agent_task(self, **kwargs):
            calls.append(kwargs)
            return {"status": "routing"}

    class Delegations:
        async def reserve_child_agent_task(self, **kwargs):
            calls.append({"reservation": kwargs})

        async def admit_reserved_run(self, **kwargs):
            return {"executor_kind": "internal_agent", **kwargs}

    async def dispatch_reserved_delegated_agent_task(**kwargs):
        calls.append({"dispatch": kwargs})

    submission = Submission()
    submission.dispatch_reserved_delegated_agent_task = dispatch_reserved_delegated_agent_task

    brief = compile_delegated_agent_brief(
        original_task="Implement the focused child task.",
        executor_kind="internal_agent",
        admitted_scope={"mutable_paths": ["src/example.py"]},
        strategic_assessment=_ASSESSMENT,
    )
    result = await InternalAgentTaskExecutor(
        submission_service=submission,
        delegated_agent_repository=Delegations(),
    ).start(
        parent_agent_task_id="parent",
        root_task_id="root",
        parent_chain_sequence_number=4,
        model_id="reasoning-model",
        brief=brief,
        evidence_policy={"required": "provider_reported"},
    )

    assert result["executor_kind"] == "internal_agent"
    assert calls[0]["session_type"] == "internal_delegation"
    assert calls[0]["accumulated_artifacts"]["model_id"] == "reasoning-model"
    assert calls[0]["accumulated_artifacts"]["delegated_capability_envelope"]["allows_approval_decisions"] is False
    assert "Perform the work directly" in calls[0]["agent_task"]


@pytest.mark.asyncio
async def test_acp_controller_keeps_session_alive_for_one_follow_up_then_closes() -> None:
    calls: list[dict[str, object]] = []

    class Supervisor:
        def mark_turn_idle(self):
            return None

        async def send_prompt(self, **kwargs):
            calls.append(kwargs)
            return {"stopReason": "end_turn"}

        async def complete_turn(self):
            calls.append({"closed": True})

    controller = AcpDelegatedSessionController()
    controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=Supervisor(),
        session_id="session",
    )

    response = await controller.send_follow_up(
        delegated_agent_run_id="delegated-run",
        instruction="Run the required verification and report the result.",
    )
    assert response["stopReason"] == "end_turn"
    assert controller.contains("delegated-run") is True
    await controller.close(
        delegated_agent_run_id="delegated-run",
        terminal_run={"id": "delegated-run", "status": "settled"},
    )
    assert calls[-1] == {"closed": True}


@pytest.mark.asyncio
async def test_acp_executor_persists_an_idle_turn_before_any_outcome_is_classified() -> None:
    calls: list[dict[str, object]] = []

    class Runs:
        async def get_run(self, delegated_agent_run_id):
            assert delegated_agent_run_id == "delegated-run"
            return {
                "id": delegated_agent_run_id,
                "executor_kind": "acp_provider",
                "revision": 2,
                "status": "admitted",
            }

        async def start_turn(self, **kwargs):
            calls.append({"start": kwargs})
            return {"id": "turn-1"}

        async def settle_turn_idle(self, **kwargs):
            calls.append({"idle": kwargs})
            return {"id": "delegated-run", "status": "idle", "revision": 4}

    class Capture:
        async def capture_terminal_response(self, **kwargs):
            calls.append({"terminal_capture": kwargs})

    class Supervisor:
        def mark_turn_idle(self):
            calls.append({"provider_idle": True})

        async def send_prompt(self, **kwargs):
            calls.append({"prompt": kwargs})
            return {"stopReason": "end_turn", "text": "I need no further input."}

    sessions = AcpDelegatedSessionController()
    sessions.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=Supervisor(),
        session_id="session",
    )
    result = await AcpDelegatedAgentExecutor(
        delegated_agent_repository=Runs(),
        session_controller=sessions,
        evidence_capture_service=Capture(),
    ).start_turn(
        delegated_agent_run_id="delegated-run",
        instruction="Perform the admitted task directly.",
    )

    assert result["run"]["status"] == "idle"
    assert result["terminal_response"]["stopReason"] == "end_turn"
    call_keys = [next(iter(call)) for call in calls]
    assert call_keys[0] == "start"
    assert "terminal_capture" in call_keys
    assert call_keys.index("terminal_capture") < call_keys.index("idle")
    assert sessions.active_evidence_turn_id(delegated_agent_run_id="delegated-run") is None


@pytest.mark.asyncio
async def test_acp_executor_clears_evidence_turn_binding_after_prompt_failure() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": delegated_agent_run_id,
                "executor_kind": "acp_provider",
                "revision": 2,
                "status": "admitted",
            }

        async def start_turn(self, **kwargs):
            return {"id": "turn-1"}

        async def transition_run(self, **kwargs):
            return {"id": "delegated-run", "status": "supervision_due", "revision": 3}

    class Supervisor:
        def mark_turn_idle(self):
            return None

        async def send_prompt(self, **kwargs):
            raise RuntimeError("simulated transport failure")

    sessions = AcpDelegatedSessionController()
    sessions.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=Supervisor(),
        session_id="session",
    )
    with pytest.raises(RuntimeError, match="simulated transport failure"):
        await AcpDelegatedAgentExecutor(
            delegated_agent_repository=Runs(),
            session_controller=sessions,
        ).start_turn(
            delegated_agent_run_id="delegated-run",
            instruction="Perform the admitted task directly.",
        )

    assert sessions.active_evidence_turn_id(delegated_agent_run_id="delegated-run") is None


@pytest.mark.asyncio
async def test_delegated_controller_persists_outcome_before_parent_resume() -> None:
    calls: list[dict[str, object]] = []

    class Runs:
        async def record_outcome(self, **kwargs):
            calls.append({"outcome": kwargs})
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "child_agent_task_id": "child",
                "executor_kind": "internal_agent",
                "settled_at": "now",
            }

        async def list_active_for_parent(self, parent_agent_task_id):
            assert parent_agent_task_id == "parent"
            return []

        async def list_outcomes_for_parent(self, parent_agent_task_id):
            assert parent_agent_task_id == "parent"
            return [
                {
                    "delegated_agent_run_id": "delegated-run",
                    "executor_kind": "internal_agent",
                    "terminal_status": "settled",
                    "evidence_state": "provider_reported",
                    "summary": "Child completed its stated work.",
                }
            ]

    class Coordinator:
        async def resume_workflow_after_provider_delegation(self, **kwargs):
            calls.append({"resume": kwargs})

    controller = DelegatedAgentController(
        delegated_agent_repository=Runs(),
        workflow_coordinator=Coordinator(),
    )
    await controller.settle_and_resume(
        delegated_agent_run={
            "id": "delegated-run",
            "revision": 4,
            "executor_kind": "internal_agent",
        },
        child_status="completed",
        summary="Child completed its stated work.",
        evidence_state="provider_reported",
    )

    assert list(calls[0]) == ["outcome"]
    assert list(calls[1]) == ["resume"]
    assert calls[1]["resume"]["child_outcomes"][0]["delegated_agent_run_id"] == "delegated-run"


@pytest.mark.asyncio
async def test_delegated_controller_keeps_parent_waiting_for_other_active_children() -> None:
    resumed = False

    class Runs:
        async def record_outcome(self, **kwargs):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "child_agent_task_id": "child",
                "executor_kind": "internal_agent",
                "settled_at": "now",
            }

        async def list_active_for_parent(self, parent_agent_task_id):
            assert parent_agent_task_id == "parent"
            return [{"id": "other-delegated-run"}]

        async def list_outcomes_for_parent(self, parent_agent_task_id):
            raise AssertionError("must not be called while another child is active")

    class Coordinator:
        async def resume_workflow_after_provider_delegation(self, **kwargs):
            nonlocal resumed
            resumed = True

    result = await DelegatedAgentController(
        delegated_agent_repository=Runs(),
        workflow_coordinator=Coordinator(),
    ).settle_and_resume(
        delegated_agent_run={
            "id": "delegated-run",
            "revision": 4,
            "executor_kind": "internal_agent",
        },
        child_status="completed",
        summary="Child completed its stated work.",
        evidence_state="provider_reported",
    )

    assert result["id"] == "delegated-run"
    assert resumed is False


@pytest.mark.asyncio
async def test_delegated_interaction_resolution_replay_is_idempotent() -> None:
    class Runs:
        async def transition_run(self, **kwargs):
            raise AssertionError("an already resolved interaction must not transition again")

    run = {
        "id": "delegated-run",
        "revision": 3,
        "executor_kind": "acp_provider",
        "status": "supervision_due",
    }
    result = await DelegatedAgentController(
        delegated_agent_repository=Runs(),
        workflow_coordinator=None,
    ).handle_provider_interaction_resolved(
        delegated_agent_run=run,
        interaction_id="interaction-1",
    )

    assert result == run


@pytest.mark.asyncio
async def test_propose_has_no_write_and_admit_records_one_event() -> None:
    calls: list[dict[str, object]] = []

    class Submission:
        async def reserve_delegated_agent_task(self, **kwargs):
            calls.append(kwargs)
            return {"status": "routing"}

    class Delegations:
        def __init__(self) -> None:
            self.reservations: list[dict[str, object]] = []

        async def reserve_child_agent_task(self, **kwargs):
            self.reservations.append(kwargs)
            calls.append({"reservation": kwargs})

        async def admit_reserved_run(self, **kwargs):
            calls.append({"admit": kwargs})
            return {"executor_kind": "internal_agent", "id": "delegated-run", "revision": 0, **kwargs}

    async def dispatch_reserved_delegated_agent_task(**kwargs):
        calls.append({"dispatch": kwargs})

    submission = Submission()
    submission.dispatch_reserved_delegated_agent_task = dispatch_reserved_delegated_agent_task
    delegations = Delegations()
    assessment = {
        "parallelism_reason": "isolated read-only review can run alongside the primary task",
        "independence_rationale": "review needs no parent context or approval",
        "expected_benefit": "returns findings before the primary task would reach this file",
        "parent_work_can_continue": True,
        "child_cannot_delegate": True,
    }

    proposal = DelegatedChildProposal(
        executor_kind="internal_agent",
        objective="Review the changed module for obvious defects.",
        mutable_paths=(),
        read_only=True,
        dependency_ids=(),
        acceptance_criteria=("Return a bullet list of findings.",),
        strategic_assessment=assessment,
    )
    admitted_scope = DelegatedAgentAdmissionService().validate(
        proposal=proposal,
        parent_agent_task_id="parent",
        root_task_id="root",
    )

    # Proposal validation alone performs no database write.
    assert calls == []

    brief = compile_delegated_agent_brief(
        original_task=proposal.objective,
        executor_kind="internal_agent",
        admitted_scope={
            "read_only": admitted_scope["read_only"],
            "mutable_paths": admitted_scope["mutable_paths"],
        },
        acceptance_criteria=proposal.acceptance_criteria,
        strategic_assessment=assessment,
    )
    result = await InternalAgentTaskExecutor(
        submission_service=submission,
        delegated_agent_repository=delegations,
    ).start(
        parent_agent_task_id="parent",
        root_task_id="root",
        parent_chain_sequence_number=1,
        model_id="reasoning-model",
        brief=brief,
        evidence_policy={"required": "provider_reported"},
    )

    assert result["executor_kind"] == "internal_agent"
    assert admitted_scope["strategic_assessment"] == assessment
    admit_calls = [call["admit"] for call in calls if "admit" in call]
    assert len(admit_calls) == 1


@pytest.mark.asyncio
async def test_parent_supervision_continues_a_live_acp_session_without_runtime_evidence() -> None:
    class Runs:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def start_turn(self, **kwargs):
            self.calls.append("start_turn")
            return {"id": "turn-2"}

        async def settle_turn_idle(self, **kwargs):
            self.calls.append("settle_turn_idle")
            return {"id": "delegated-run", "revision": 3, "executor_kind": "acp_provider", "status": "idle"}

        async def transition_run(self, **kwargs):
            self.calls.append("transition_run")
            assert kwargs["next_status"] == "supervision_due"
            return {
                "id": "delegated-run",
                "revision": 4,
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

        async def get_run(self, delegated_agent_run_id):
            assert delegated_agent_run_id == "delegated-run"
            return {
                "id": "delegated-run",
                "revision": 2,
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Supervisor:
        def mark_turn_idle(self):
            return None

        async def send_prompt(self, **kwargs):
            return {"stopReason": "end_turn"}

    runs = Runs()
    session_controller = AcpDelegatedSessionController()
    session_controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=Supervisor(),
        session_id="session",
    )
    controller = DelegatedAgentController(
        delegated_agent_repository=runs,
        workflow_coordinator=None,
        acp_session_controller=session_controller,
    )
    delegated_agent_run = {
        "id": "delegated-run",
        "revision": 2,
        "executor_kind": "acp_provider",
        "status": "supervision_due",
    }

    result = await controller.continue_acp_run(
        delegated_agent_run=delegated_agent_run,
        instruction="Report the current status.",
    )

    assert runs.calls == ["start_turn", "settle_turn_idle", "transition_run"]
    assert result["run"]["status"] == "supervision_due"
    assert result["terminal_response"] == {"stopReason": "end_turn"}
    assert result["session"]["available"] is True
    assert not hasattr(controller, "_runtime_evidence")


@pytest.mark.asyncio
async def test_continue_action_returns_bounded_turn_evidence() -> None:
    calls: list[dict[str, object]] = []

    class Runs:
        async def get_run(self, delegated_agent_run_id):
            assert delegated_agent_run_id == "delegated-run"
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        async def continue_acp_run(self, **kwargs):
            calls.append(kwargs)
            return {
                "run": {"id": "delegated-run", "status": "supervision_due"},
                "terminal_response": {"stopReason": "end_turn"},
                "session": {"available": True, "safe_final_message": "Done reading the file."},
            }

    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    result = await _handle_existing_run_action(
        action="continue",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="Continue the admitted task.",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=Controller()),
        evidence_id=None,
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )

    assert calls[0]["delegated_agent_run"]["id"] == "delegated-run"
    assert calls[0]["instruction"] == "Continue the admitted task."
    payload = json.loads(result)
    assert payload["ok"] is True
    assert set(payload) == {"ok", "status", "terminal_response", "session"}
    assert payload["status"] == "supervision_due"
    assert payload["terminal_response"] == {"stopReason": "end_turn"}
    assert "runtime_identity" not in result


@pytest.mark.asyncio
async def test_settle_action_does_not_recursively_resume_parent() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        def __init__(self) -> None:
            self.settle_acp_calls: list[dict[str, object]] = []

        async def settle_acp_run_for_supervision(self, **kwargs):
            self.settle_acp_calls.append(kwargs)
            return {"id": "delegated-run", "status": "settled"}

        async def settle_run_and_maybe_resume_parent(self, **kwargs):
            raise AssertionError("a live parent workflow must not recursively resume itself")

    controller = Controller()
    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    result = await _handle_existing_run_action(
        action="settle_completed",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="The provider finished the requested review.",
        submission_service=SimpleNamespace(delegated_agent_controller=controller),
        evidence_id=None,
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )

    assert json.loads(result) == {"ok": True, "status": "settled"}
    assert len(controller.settle_acp_calls) == 1
    assert controller.settle_acp_calls[0]["summary"] == "The provider finished the requested review."
    assert controller.settle_acp_calls[0]["verification_evidence_id"] is None


@pytest.mark.asyncio
async def test_supervision_action_resolves_controller_from_authorized_submission_owner() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": delegated_agent_run_id,
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        async def settle_acp_run_for_supervision(self, **kwargs):
            assert kwargs["delegated_agent_run"]["id"] == "delegated-run"
            return {"id": "delegated-run", "status": "settled"}

    submission_owner = AuthorizedProviderDelegationSubmissionService(
        SimpleNamespace(),
        delegated_agent_controller=Controller(),
    )
    result = await _handle_existing_run_action(
        action="settle_completed",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=SimpleNamespace(delegated_agent_repository=Runs()),
        instruction="",
        summary="The provider completed the task.",
        submission_service=submission_owner,
        evidence_id=None,
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )

    assert json.loads(result) == {"ok": True, "status": "settled"}


@pytest.mark.asyncio
async def test_cancel_action_sets_terminal_outcome_only_after_session_cancel() -> None:
    order: list[str] = []

    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
                "revision": 5,
            }

        async def transition_run(self, **kwargs):
            order.append("transition_run")
            assert kwargs["next_status"] == "cancelling"
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "cancelling",
                "revision": 6,
            }

        async def record_outcome(self, **kwargs):
            order.append("record_outcome")
            assert kwargs["terminal_status"] == "cancelled"
            return {"id": "delegated-run", "status": "cancelled", "executor_kind": "acp_provider"}

    class Sessions:
        async def cancel(self, *, delegated_agent_run_id):
            order.append("session_cancel")

        def describe(self, delegated_agent_run_id):
            return {"available": False}

        async def close(self, **kwargs):
            order.append("session_close")

    runs = Runs()
    controller = DelegatedAgentController(
        delegated_agent_repository=runs,
        workflow_coordinator=None,
        acp_session_controller=Sessions(),
    )
    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    result = await _handle_existing_run_action(
        action="cancel",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="Cancelling per user request.",
        submission_service=SimpleNamespace(delegated_agent_controller=controller),
        evidence_id=None,
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )

    assert json.loads(result) == {"ok": True, "status": "cancelled"}
    assert order == ["transition_run", "session_cancel", "record_outcome", "session_close"]

    class FailingSessions(Sessions):
        async def cancel(self, *, delegated_agent_run_id):
            order.append("session_cancel_failed")
            raise RuntimeError("transport unavailable")

    failing_controller = DelegatedAgentController(
        delegated_agent_repository=runs,
        workflow_coordinator=None,
        acp_session_controller=FailingSessions(),
    )
    stuck_run = {
        "id": "delegated-run",
        "revision": 6,
        "executor_kind": "acp_provider",
        "status": "supervision_due",
    }
    with pytest.raises(RuntimeError, match="transport unavailable"):
        await failing_controller.cancel_acp_run_for_supervision(
            delegated_agent_run=stuck_run,
            summary="Cancelling per user request.",
        )
    assert order.count("record_outcome") == 1
    assert order.count("session_close") == 1


@pytest.mark.asyncio
async def test_parent_presentation_keeps_capture_unavailable_when_report_card_query_fails() -> None:
    class Evidence:
        async def build_parent_supervision_snapshot(self, **kwargs):
            raise RuntimeError("simulated ledger query failure")

    class Capture:
        def capture_state(self, *, delegated_agent_run_id):
            return "available"

    class Publisher:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def publish_delegated_provider_state(self, **kwargs):
            self.calls.append(kwargs)

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def resume_workflow_for_delegated_supervision(self, **kwargs):
            self.calls.append(kwargs)

    publisher = Publisher()
    coordinator = Coordinator()
    controller = DelegatedAgentController(
        delegated_agent_repository=SimpleNamespace(),
        workflow_coordinator=coordinator,
        delegated_agent_evidence_service=Evidence(),
        evidence_capture_service=Capture(),
        provider_state_publisher=publisher,
    )
    delegated_agent_run = {
        "id": "delegated-run",
        "parent_agent_task_id": "parent",
        "root_task_id": "root",
        "revision": 5,
        "executor_kind": "acp_provider",
        "status": "supervision_due",
    }

    await controller.present_acp_turn_to_parent(delegated_agent_run=delegated_agent_run)

    report_card = coordinator.calls[0]["report_card"]
    assert report_card["capture_state"] == "unavailable"
    assert report_card["evidence_count"] == 0
    assert publisher.calls[0]["message"].endswith("evidence capture is unavailable.")


@pytest.mark.asyncio
async def test_parent_presentation_hands_derived_report_card_to_status_and_resume() -> None:
    report_card = {
        "delegated_agent_run_id": "delegated-run",
        "run_status": "supervision_due",
        "run_revision": 5,
        "capture_state": "available",
        "evidence_count": 1,
        "latest_summary": "Provider reported the requested artifact.",
        "claims": [{"evidence_id": "evidence-1"}],
        "artifacts": [{"evidence_id": "evidence-2"}],
        "next_after_sequence": None,
    }

    class Evidence:
        async def build_parent_supervision_snapshot(self, **kwargs):
            assert kwargs == {
                "parent_agent_task_id": "parent",
                "delegated_agent_run_id": "delegated-run",
                "capture_state": "available",
            }
            return report_card

    class Capture:
        def capture_state(self, *, delegated_agent_run_id):
            return "available"

    class Publisher:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def publish_delegated_provider_state(self, **kwargs):
            self.calls.append(kwargs)

    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def resume_workflow_for_delegated_supervision(self, **kwargs):
            self.calls.append(kwargs)

    publisher = Publisher()
    coordinator = Coordinator()
    controller = DelegatedAgentController(
        delegated_agent_repository=SimpleNamespace(),
        workflow_coordinator=coordinator,
        delegated_agent_evidence_service=Evidence(),
        evidence_capture_service=Capture(),
        provider_state_publisher=publisher,
    )
    delegated_agent_run = {
        "id": "delegated-run",
        "parent_agent_task_id": "parent",
        "root_task_id": "root",
        "revision": 5,
        "executor_kind": "acp_provider",
        "status": "supervision_due",
    }

    await controller.present_acp_turn_to_parent(delegated_agent_run=delegated_agent_run)

    assert coordinator.calls[0]["report_card"] is report_card
    assert publisher.calls[0]["delegation_id"] == "delegated-run"
    assert publisher.calls[0]["message"].endswith("evidence capture is available.")


@pytest.mark.asyncio
async def test_provider_interaction_resolution_leaves_running_turn_for_executor_settlement() -> None:
    class Runs:
        async def transition_run(self, **kwargs):
            raise AssertionError("interaction resolution must not transition the generic run")

    class Sessions:
        def __init__(self) -> None:
            self.opened: list[str] = []
            self.resolved: list[str] = []

        def interaction_opened(self, *, delegated_agent_run_id, interaction_id):
            self.opened.append(interaction_id)

        def interaction_resolved(self, *, delegated_agent_run_id, interaction_id):
            self.resolved.append(interaction_id)

    sessions = Sessions()
    controller = DelegatedAgentController(
        delegated_agent_repository=Runs(),
        workflow_coordinator=None,
        acp_session_controller=sessions,
    )
    running_run = {
        "id": "delegated-run",
        "revision": 4,
        "executor_kind": "acp_provider",
        "status": "running",
    }

    opened = await controller.handle_provider_interaction_opened(
        delegated_agent_run=running_run,
        interaction_id="interaction-1",
        permission=True,
    )
    resolved = await controller.handle_provider_interaction_resolved(
        delegated_agent_run=running_run,
        interaction_id="interaction-1",
    )

    assert opened == running_run
    assert resolved == running_run
    assert sessions.opened == ["interaction-1"]
    assert sessions.resolved == ["interaction-1"]


@pytest.mark.asyncio
async def test_inspect_evidence_rejects_blank_purpose_and_forwards_bounded_request() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def inspect_evidence(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "delegated_agent_run_id": "delegated-run",
                "run_status": "supervision_due",
                "items": [{"evidence_id": "evidence-1", "kind": "artifact_locator"}],
                "next_after_sequence": None,
            }

    controller = Controller()
    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    blank = await _handle_existing_run_action(
        action="inspect_evidence",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=controller),
        evidence_id="evidence-1",
        verification_evidence_id=None,
        after_sequence=2,
        evidence_limit=6,
        inspection_purpose="   ",
    )
    assert json.loads(blank) == {"ok": False, "error": "inspection_purpose is required"}

    result = await _handle_existing_run_action(
        action="inspect_evidence",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=controller),
        evidence_id="evidence-1",
        verification_evidence_id=None,
        after_sequence=2,
        evidence_limit=6,
        inspection_purpose="Review provider artifact evidence before settlement.",
    )
    payload = json.loads(result)
    assert payload == {
        "ok": True,
        "inspection": {
            "delegated_agent_run_id": "delegated-run",
            "run_status": "supervision_due",
            "items": [{"evidence_id": "evidence-1", "kind": "artifact_locator"}],
            "next_after_sequence": None,
        },
    }
    assert controller.calls[0]["evidence_id"] == "evidence-1"
    assert controller.calls[0]["after_sequence"] == 2
    assert controller.calls[0]["limit"] == 6


@pytest.mark.asyncio
async def test_verify_artifact_requires_evidence_id_and_returns_bounded_verification() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        async def verify_workspace_artifact(self, **kwargs):
            assert kwargs["artifact_evidence_id"] == "artifact-evidence-1"
            return {
                "id": "verification-evidence-1",
                "verification_state": "verified",
                "summary": "Basil verified one provider-reported workspace artifact.",
                "structured_data": {
                    "artifact_evidence_id": "artifact-evidence-1",
                    "reason": "regular_file",
                    "byte_count": 12,
                    "sha256": "abc123",
                },
            }

    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    missing = await _handle_existing_run_action(
        action="verify_artifact",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=Controller()),
        evidence_id=None,
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )
    assert json.loads(missing) == {"ok": False, "error": "evidence_id is required for artifact verification"}

    result = await _handle_existing_run_action(
        action="verify_artifact",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=Controller()),
        evidence_id="artifact-evidence-1",
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )
    payload = json.loads(result)
    assert payload == {
        "ok": True,
        "verification": {
            "evidence_id": "verification-evidence-1",
            "verification_state": "verified",
            "summary": "Basil verified one provider-reported workspace artifact.",
            "structured_data": {
                "artifact_evidence_id": "artifact-evidence-1",
                "reason": "regular_file",
                "byte_count": 12,
                "sha256": "abc123",
            },
        },
    }


@pytest.mark.asyncio
async def test_acp_settle_completed_forwards_verification_evidence_id() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def settle_acp_run_for_supervision(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": "delegated-run", "status": "settled"}

    controller = Controller()
    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    submission = SimpleNamespace(delegated_agent_controller=controller)
    await _handle_existing_run_action(
        action="settle_completed",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="Provider completed the bounded task.",
        submission_service=submission,
        evidence_id=None,
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )
    await _handle_existing_run_action(
        action="settle_completed",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="Provider completed the bounded task.",
        submission_service=submission,
        evidence_id=None,
        verification_evidence_id="verification-evidence-1",
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )
    assert controller.calls[0]["verification_evidence_id"] is None
    assert controller.calls[1]["verification_evidence_id"] == "verification-evidence-1"


@pytest.mark.asyncio
async def test_acp_settlement_derives_outcome_state_from_verification_evidence() -> None:
    class Runs:
        async def record_outcome(self, **kwargs):
            self.call = kwargs
            return {"id": "delegated-run", "status": "settled", "executor_kind": "acp_provider"}

    class Verifier:
        async def get_verification_for_settlement(self, **kwargs):
            assert kwargs["verification_evidence_id"] == "verification-evidence-1"
            return {"id": "verification-evidence-1", "verification_state": "verification_mismatch"}

    runs = Runs()
    controller = DelegatedAgentController(
        delegated_agent_repository=runs,
        workflow_coordinator=None,
        delegated_agent_workspace_verifier=Verifier(),
    )
    run = {
        "id": "delegated-run",
        "parent_agent_task_id": "parent",
        "revision": 4,
        "executor_kind": "acp_provider",
        "status": "supervision_due",
    }

    settled = await controller.settle_acp_run_for_supervision(
        delegated_agent_run=run,
        summary="Basil could not verify the reported artifact.",
        verification_evidence_id="verification-evidence-1",
    )

    assert settled["status"] == "settled"
    assert runs.call["evidence_state"] == "verification_mismatch"
    assert runs.call["receipt_references"] == [{
        "evidence_id": "verification-evidence-1",
        "verification_state": "verification_mismatch",
    }]


@pytest.mark.asyncio
async def test_internal_agent_completed_settlement_keeps_provider_reported_branch() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "parent",
                "executor_kind": "internal_agent",
                "status": "supervision_due",
            }

    class Controller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def settle_run(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": "delegated-run", "status": "settled"}

    controller = Controller()
    result = await _handle_existing_run_action(
        action="settle_completed",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=SimpleNamespace(delegated_agent_repository=Runs()),
        instruction="",
        summary="Child completed the bounded task.",
        submission_service=SimpleNamespace(delegated_agent_controller=controller),
        evidence_id=None,
        verification_evidence_id="verification-evidence-1",
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )
    assert json.loads(result) == {"ok": True, "status": "settled"}
    assert controller.calls[0]["evidence_state"] == "provider_reported"


@pytest.mark.asyncio
async def test_foreign_child_ownership_fails_before_inspection_or_verification() -> None:
    class Runs:
        async def get_run(self, delegated_agent_run_id):
            return {
                "id": "delegated-run",
                "parent_agent_task_id": "other-parent",
                "executor_kind": "acp_provider",
                "status": "supervision_due",
            }

    class Controller:
        async def inspect_evidence(self, **kwargs):
            raise AssertionError("foreign ownership must fail before controller inspection")

        async def verify_workspace_artifact(self, **kwargs):
            raise AssertionError("foreign ownership must fail before controller verification")

    knowledge = SimpleNamespace(delegated_agent_repository=Runs())
    inspect_result = await _handle_existing_run_action(
        action="inspect_evidence",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=Controller()),
        evidence_id="evidence-1",
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="Review delegated evidence.",
    )
    verify_result = await _handle_existing_run_action(
        action="verify_artifact",
        delegated_agent_run_id="delegated-run",
        parent_agent_task_id="parent",
        knowledge=knowledge,
        instruction="",
        summary="",
        submission_service=SimpleNamespace(delegated_agent_controller=Controller()),
        evidence_id="evidence-1",
        verification_evidence_id=None,
        after_sequence=None,
        evidence_limit=12,
        inspection_purpose="",
    )
    assert json.loads(inspect_result) == {"ok": False, "error": "delegated child is not owned by this parent"}
    assert json.loads(verify_result) == {"ok": False, "error": "delegated child is not owned by this parent"}


@pytest.mark.asyncio
async def test_acp_session_is_retained_when_complete_turn_fails() -> None:
    class Supervisor:
        def mark_turn_idle(self):
            return None

        async def complete_turn(self):
            raise RuntimeError("completion failed")

    controller = AcpDelegatedSessionController()
    controller.register(
        provider_run_id="provider-run",
        delegated_agent_run_id="delegated-run",
        supervisor=Supervisor(),
        session_id="session",
    )

    with pytest.raises(RuntimeError, match="completion failed"):
        await controller.close(
            delegated_agent_run_id="delegated-run",
            terminal_run={"id": "delegated-run", "status": "settled"},
        )

    assert controller.contains("delegated-run") is True
