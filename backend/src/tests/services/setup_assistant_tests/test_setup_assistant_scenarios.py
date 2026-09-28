"""Scenario coverage for the event-stream setup assistant."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncIterator, Iterable
from unittest.mock import AsyncMock

import pytest

from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupAgentModelAccess,
    SetupAgentModelAccessMode,
    SetupAgentRequest,
    SetupArtifactKind,
    SetupAssistantPhase,
    SetupConsentReceipt,
    SetupPrivacyImpact,
    SetupToolApprovalState,
    SetupToolCall,
)
from api.core.models.preference_models.hotkeys import HotkeyBinding
from api.services.setup_assistant.action_execution_service import (
    SetupAssistantActionExecutionService,
)
from api.services.setup_assistant.agent_service import SetupAssistantAgentService
from api.services.setup_assistant.discovery_service import SetupAssistantDiscoveryService
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
    build_setup_agent_system_prompt,
)
from api.services.setup_assistant.agent_graph import setup_agent_runtime as setup_agent_runtime_module
from api.services.setup_assistant.agent_graph.setup_agent_runtime import SetupAgentRuntime
from api.services.setup_assistant.agent_graph.setup_agent_tools import (
    SetupAgentToolFactory,
    SetupPendingProposalStore,
)
from api.services.setup_assistant.context_catalog_service import SetupAgentModelSelection
from api.services.setup_assistant.agent_graph.agenda_catalog import applicable_catalog_seed


class FakeSetupAgentRuntime:
    def __init__(self, events: Iterable[SetupAgentEvent]) -> None:
        self.events = list(events)

    async def respond_stream(
        self,
        request: SetupAgentRequest,
        finalize_mode: bool = False,
    ) -> AsyncIterator[SetupAgentEvent]:
        for event in self.events:
            yield event


def build_request(latest_message: str = "Please set up Basil around my work.") -> SetupAgentRequest:
    return SetupAgentRequest(
        latest_message=latest_message,
        phase=SetupAssistantPhase.agent_synthesis,
        setup_agent_model_access=SetupAgentModelAccess(
            mode=SetupAgentModelAccessMode.local,
            local_model_id="qwen-8b",
            resolved=True,
        ),
    )


@pytest.mark.asyncio
async def test_setup_agent_stream_surfaces_observation_then_message() -> None:
    service = SetupAssistantAgentService(
        runtime=FakeSetupAgentRuntime(
            [
                SetupAgentEvent(kind=SetupAgentEventKind.turn_started),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.observation_added,
                    payload={
                        "id": "observation-email",
                        "label": "Email",
                        "title": "Mail is available.",
                        "detail": "Basil can suggest email help later without asking which app you use first.",
                        "tone": "email",
                    },
                ),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.message_completed,
                    payload={
                        "id": "message-1",
                        "role": "basil",
                        "content": "I found Mail and can keep going lightly.",
                    },
                ),
                SetupAgentEvent(kind=SetupAgentEventKind.turn_complete),
            ]
        )
    )

    events = [event async for event in service.respond_stream(build_request())]

    assert [event.kind for event in events] == [
        SetupAgentEventKind.turn_started,
        SetupAgentEventKind.observation_added,
        SetupAgentEventKind.message_completed,
        SetupAgentEventKind.turn_complete,
    ]
    assert events[1].payload["title"] == "Mail is available."


@pytest.mark.asyncio
async def test_say_setup_message_streams_with_one_message_id() -> None:
    events: list[SetupAgentEvent] = []

    async def emit_event(event: SetupAgentEvent) -> None:
        events.append(event)

    factory = SetupAgentToolFactory(
        event_emitter=emit_event,
        proposal_store=SetupPendingProposalStore(),
    )
    content = (
        "Dill is Basil's writing and reply partner. Paprika is Basil's task-running helper."
    )

    await factory.say_setup_message(content)

    message_ids = {
        event.payload["id"]
        for event in events
        if event.kind in {
            SetupAgentEventKind.message_started,
            SetupAgentEventKind.message_delta,
            SetupAgentEventKind.message_completed,
        }
    }
    deltas = [
        event.payload["delta"]
        for event in events
        if event.kind == SetupAgentEventKind.message_delta
    ]

    assert [events[0].kind, events[-1].kind] == [
        SetupAgentEventKind.message_started,
        SetupAgentEventKind.message_completed,
    ]
    assert len(message_ids) == 1
    assert "".join(deltas) == content
    assert events[-1].payload["content"] == content


@pytest.mark.asyncio
async def test_setup_agent_stream_supports_arbitrary_user_input_mid_flow() -> None:
    service = SetupAssistantAgentService(
        runtime=FakeSetupAgentRuntime(
            [
                SetupAgentEvent(kind=SetupAgentEventKind.turn_started),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.chips_set,
                    payload={
                        "chips": [
                            {
                                "id": "lighter",
                                "label": "Keep it lighter",
                                "message": "Keep this setup lighter and explain less.",
                            }
                        ]
                    },
                ),
                SetupAgentEvent(kind=SetupAgentEventKind.turn_complete),
            ]
        )
    )

    events = [
        event
        async for event in service.respond_stream(build_request("Actually, keep this really light."))
    ]

    assert events[1].kind == SetupAgentEventKind.chips_set
    assert events[1].payload["chips"][0]["label"] == "Keep it lighter"


def test_pending_proposal_store_tracks_approval_order_independently() -> None:
    store = SetupPendingProposalStore()
    first = build_tool_call("proposal-model", "start_model_downloads")
    second = build_tool_call("proposal-task", "launch_agent_task")

    store.record_pending_setup_proposal(first)
    store.record_pending_setup_proposal(second)
    store.update_setup_proposal_state("proposal-task", SetupToolApprovalState.approved)
    store.update_setup_proposal_state("proposal-model", SetupToolApprovalState.deferred)

    assert store.get_pending_setup_proposal("proposal-task").approval_state == SetupToolApprovalState.approved
    assert store.get_pending_setup_proposal("proposal-model").approval_state == SetupToolApprovalState.deferred


@pytest.mark.asyncio
async def test_native_launch_tool_call_returns_bridge_required_result() -> None:
    service = SetupAssistantActionExecutionService()
    tool_call = build_tool_call("proposal-dill", "launch_assistant_session")
    tool_call.approval_state = SetupToolApprovalState.approved
    tool_call.payload = {
        "context": "email",
        "prompt": "Draft a reply grounded in the approved setup context.",
    }

    results = await service.execute_approved_setup_actions(actions=[], tool_calls=[tool_call])

    assert results[0].status.value == "skipped"
    assert results[0].result_payload["requires_native_bridge"] is True
    assert results[0].kind == "launch_assistant_session"


@pytest.mark.asyncio
async def test_artifact_rows_and_receipts_stream_one_at_a_time() -> None:
    receipt = SetupConsentReceipt(
        id="receipt-task",
        proposal_id="proposal-task",
        title="Try a real Paprika task",
        rationale="This will show Basil doing useful work after setup.",
        tool_call=build_tool_call("proposal-task", "launch_agent_task"),
    )
    service = SetupAssistantAgentService(
        runtime=FakeSetupAgentRuntime(
            [
                SetupAgentEvent(
                    kind=SetupAgentEventKind.artifact_opened,
                    payload={
                        "id": "tasks",
                        "kind": SetupArtifactKind.task_offer_gallery.value,
                        "title": "Useful first tasks",
                        "payload": {},
                        "rows": [],
                        "is_open": True,
                    },
                ),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.artifact_row_added,
                    payload={
                        "artifact_id": "tasks",
                        "row": {
                            "id": "task-1",
                            "payload": {"title": "Summarize this week's activity"},
                            "receipt": receipt.model_dump(mode="json"),
                        },
                    },
                ),
            ]
        )
    )

    events = [event async for event in service.respond_stream(build_request())]

    assert events[0].kind == SetupAgentEventKind.artifact_opened
    assert events[1].kind == SetupAgentEventKind.artifact_row_added
    assert events[1].payload["row"]["receipt"]["proposal_id"] == "proposal-task"


@pytest.mark.asyncio
async def test_setup_agent_stream_surfaces_prioritized_value_paths_with_optional_breadth() -> None:
    service = SetupAssistantAgentService(
        runtime=FakeSetupAgentRuntime(
            [
                SetupAgentEvent(
                    kind=SetupAgentEventKind.message_completed,
                    payload={
                        "id": "message-value-paths",
                        "role": "basil",
                        "content": (
                            "Dill is Basil's writing and reply partner, and Paprika is Basil's "
                            "task-running helper. Dill looks like the best first thing to make "
                            "concrete because Mail is available and the profile already has a "
                            "useful tone baseline. Paprika also looks promising because GitHub "
                            "and Linear are connected. Basil "
                            "has transcription and automatic activity context too, but those can "
                            "wait unless you want to go deeper before wrapping up."
                        ),
                    },
                ),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.artifact_opened,
                    payload={
                        "id": "value-paths",
                        "kind": SetupArtifactKind.task_offer_gallery.value,
                        "title": "Suggested places to start",
                        "payload": {
                            "value_hypothesis": "Email and project workflows look immediately useful."
                        },
                        "rows": [],
                        "is_open": True,
                    },
                ),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.artifact_row_added,
                    payload={
                        "artifact_id": "value-paths",
                        "row": {
                            "id": "dill-email",
                            "payload": {
                                "title": "Start with Dill for email",
                                "why_this_might_matter": (
                                    "Mail is available and the profile already captures a direct, "
                                    "professional tone."
                                ),
                                "example_use_cases": [
                                    "Draft a concise reply in your voice",
                                    "Tighten a long email before sending",
                                ],
                                "recommended_next_step": (
                                    "Review approved writing context and prep a grounded assistant run."
                                ),
                                "priority": "primary",
                            },
                            "receipt": None,
                        },
                    },
                ),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.artifact_row_added,
                    payload={
                        "artifact_id": "value-paths",
                        "row": {
                            "id": "optional-breadth",
                            "payload": {
                                "title": "Keep transcription and activity context optional",
                                "why_this_might_matter": (
                                    "They can be valuable, but they are not the clearest first "
                                    "experience if Dill and Paprika are already ready."
                                ),
                                "defer_message": (
                                    "Come back after trying the main workflows, unless privacy or "
                                    "context capture is something you want to inspect now."
                                ),
                                "priority": "later",
                            },
                            "receipt": None,
                        },
                    },
                ),
                SetupAgentEvent(
                    kind=SetupAgentEventKind.chips_set,
                    payload={
                        "chips": [
                            {
                                "id": "try-dill",
                                "label": "Prep Dill with email",
                                "message": "Help me prep a Dill email setup using real context.",
                            },
                            {
                                "id": "try-paprika",
                                "label": "Try a Paprika workflow",
                                "message": "Show me a Paprika workflow using GitHub and Linear.",
                            },
                            {
                                "id": "defer-breadth",
                                "label": "Save the rest for later",
                                "message": "Let's defer transcription and activity context for now.",
                            },
                        ]
                    },
                ),
            ]
        )
    )

    events = [event async for event in service.respond_stream(build_request())]
    artifact_rows = [
        event.payload["row"]
        for event in events
        if event.kind == SetupAgentEventKind.artifact_row_added
    ]
    chips_event = next(event for event in events if event.kind == SetupAgentEventKind.chips_set)

    assert "Dill is Basil's writing and reply partner" in events[0].payload["content"]
    assert "Paprika is Basil's task-running helper" in events[0].payload["content"]
    assert artifact_rows[0]["payload"]["priority"] == "primary"
    assert artifact_rows[0]["payload"]["example_use_cases"] == [
        "Draft a concise reply in your voice",
        "Tighten a long email before sending",
    ]
    assert artifact_rows[1]["payload"]["priority"] == "later"
    assert "Come back after trying" in artifact_rows[1]["payload"]["defer_message"]
    assert [chip["id"] for chip in chips_event.payload["chips"]] == [
        "try-dill",
        "try-paprika",
        "defer-breadth",
    ]


def test_setup_agent_prompt_blocks_orientation_conversation_generation() -> None:
    prompt = build_setup_agent_system_prompt()

    assert "When phase is deterministic_discovery" in prompt
    assert "Do not generate the next conversation screen early" in prompt
    assert "Do not call say, set_chips, open_artifact" in prompt
    assert "Do not name Dill or Paprika in orientation observations" in prompt


def test_setup_agent_prompt_blocks_ungrounded_email_demo_language() -> None:
    prompt = build_setup_agent_system_prompt()

    assert "Do not call an email path a \"demo prompt\"" in prompt
    assert "Do not claim there is a selected email, incoming email, or active thread" in prompt
    assert "If sent-email metadata is available" in prompt


def test_setup_agent_prompt_covers_invocation_readiness() -> None:
    prompt = build_setup_agent_system_prompt()

    assert "`choose_invocation_preferences` agenda item" in prompt
    assert "`Hey Basil`" in prompt
    assert "`hotkey-home_board_toggle`" in prompt
    assert "Basil Home" in prompt
    assert "Settings > Hotkeys" in prompt
    assert "behavior.enable_monitoring_at_startup" in prompt
    assert "behavior.enable_voice_listener_at_startup" in prompt
    assert "propose_wrap_up` must summarize readiness" in prompt


def test_setup_agent_prompt_covers_basil_home_and_todo_boundaries() -> None:
    prompt = build_setup_agent_system_prompt()

    assert "`literacy_basil_home_and_todos`" in prompt
    assert "Paprika must not autonomously complete, dismiss, reopen" in prompt


def test_setup_agenda_includes_invocation_preferences_visual() -> None:
    seed = applicable_catalog_seed([])
    invocation_item = next(
        item for item in seed if item["id"] == "choose_invocation_preferences"
    )

    assert invocation_item["kind"] == "action"
    assert invocation_item["default_visual_id"] == "invocation_menu_bar_entry_points"


def test_setup_agenda_includes_basil_home_and_todo_literacy() -> None:
    seed = applicable_catalog_seed([])
    basil_home_item = next(
        item for item in seed if item["id"] == "literacy_basil_home_and_todos"
    )

    assert basil_home_item["kind"] == "literacy"


def test_discovery_formats_invocation_hotkey_facts() -> None:
    service = SetupAssistantDiscoveryService(model_service=object())

    facts = service._build_hotkey_facts(
        {
            "assistant_session": HotkeyBinding(
                key="",
                is_double_press=True,
                double_press_key="option",
                description="Show Dill",
            ),
            "agent_task": HotkeyBinding(
                key="Space",
                modifiers=["option"],
                description="Start Paprika",
            ),
            "home_board_toggle": HotkeyBinding(
                key="B",
                modifiers=["control", "option"],
                description="Show Basil Home",
            ),
        },
        collected_at=datetime.utcnow(),
    )
    values_by_id = {fact.id: fact.value for fact in facts}

    assert values_by_id["hotkey-assistant_session"] == "Option+Option"
    assert values_by_id["hotkey-agent_task"] == "Option+Space"
    assert values_by_id["hotkey-home_board_toggle"] == "Control+Option+B"


@pytest.mark.asyncio
async def test_model_unavailable_streams_error_event() -> None:
    service = SetupAssistantAgentService(
        runtime=FakeSetupAgentRuntime(
            [
                SetupAgentEvent(
                    kind=SetupAgentEventKind.error,
                    payload={"message": "No setup model is available for the selected privacy path."},
                )
            ]
        )
    )

    events = [event async for event in service.respond_stream(build_request())]

    assert events[0].kind == SetupAgentEventKind.error
    assert "No setup model" in events[0].payload["message"]


def build_tool_call(proposal_id: str, tool_name: str) -> SetupToolCall:
    return SetupToolCall(
        id=proposal_id,
        tool_name=tool_name,
        payload={},
        approval_state=SetupToolApprovalState.proposed,
        user_visible_summary=proposal_id,
        privacy_impact=SetupPrivacyImpact.none,
    )


def _build_agenda_tool_and_events():
    events: list[SetupAgentEvent] = []

    async def emit_event(event: SetupAgentEvent) -> None:
        events.append(event)

    factory = SetupAgentToolFactory(
        event_emitter=emit_event,
        proposal_store=SetupPendingProposalStore(),
    )
    tools = factory.create_setup_agent_tools()
    propose = next(tool for tool in tools if tool.name == "propose_session_agenda")
    return propose, events


@pytest.mark.asyncio
async def test_propose_agenda_over_length_intent_returns_corrective_observation() -> None:
    propose, events = _build_agenda_tool_and_events()

    over_length_intent = "x" * 600  # 480-char cap on SetupAgendaItemInput.intent

    observation = await propose.arun(
        {
            "items": [
                {
                    "id": "intro_paprika",
                    "title": "Show what Paprika can do",
                    "intent": over_length_intent,
                    "kind": "demo",
                }
            ]
        }
    )

    # Instead of raising (which previously aborted the whole setup turn), the
    # tool returns a corrective observation carrying the real constraint detail
    # so the model can retry with a shortened intent.
    assert "rejected" in observation.lower()
    assert "480 characters" in observation
    assert "intent" in observation
    # Nothing was applied: no agenda proposal event should have been emitted.
    assert [event.kind for event in events] == []


@pytest.mark.asyncio
async def test_propose_agenda_valid_items_still_emits_proposal() -> None:
    propose, events = _build_agenda_tool_and_events()

    observation = await propose.arun(
        {
            "items": [
                {
                    "id": "intro_paprika",
                    "title": "Show what Paprika can do",
                    "intent": "Give you a quick feel for how Paprika runs tasks for you.",
                    "kind": "demo",
                }
            ]
        }
    )

    assert "Session agenda set with 1 item(s)." == observation
    assert [event.kind for event in events] == [
        SetupAgentEventKind.agenda_proposed
    ]


@pytest.mark.asyncio
async def test_local_setup_model_passes_its_registry_tool_call_profile(monkeypatch) -> None:
    model = SimpleNamespace(
        model_path=Path("/models/qwen35-4b-q4km.gguf"),
    )
    model_service = SimpleNamespace(load_model=AsyncMock(return_value=model))
    runtime = SetupAgentRuntime(model_service=model_service)
    selection = SetupAgentModelSelection(
        model_id="Qwen-qwen35-4b-q4km",
        config={"location": "local"},
    )
    captured: dict[str, object] = {}

    def fake_create(llama_cpp_model, *, profile):
        captured["model"] = llama_cpp_model
        captured["profile"] = profile
        return object()

    monkeypatch.setattr(
        setup_agent_runtime_module,
        "create_langchain_llm_from_llama_cpp",
        fake_create,
    )

    result = await runtime._create_setup_langchain_model(selection)

    assert result is not None
    assert captured["model"] is model
    assert captured["profile"].tool_call_format == "function_parameter_tags"


@pytest.mark.asyncio
async def test_setup_runtime_emits_executor_output_when_no_message_tool_was_called(
    monkeypatch,
) -> None:
    runtime = SetupAgentRuntime()
    executor = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"output": "Setup summary from the agent."})
    )

    async def fake_build_executor(*_args, **_kwargs):
        return executor

    monkeypatch.setattr(
        runtime,
        "_build_setup_agent_executor",
        fake_build_executor,
    )
    monkeypatch.setattr(runtime, "_build_setup_turn_input", lambda _request: "test input")
    monkeypatch.setattr(runtime, "_build_setup_chat_history", lambda _request: [])

    events = [event async for event in runtime.respond_stream(build_request())]

    completed = [
        event
        for event in events
        if event.kind == SetupAgentEventKind.message_completed
    ]
    assert len(completed) == 1
    assert completed[0].payload["content"] == "Setup summary from the agent."

