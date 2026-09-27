import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.models.model_types import ModelCapability
from api.services.conversation.conversation_route_selector import (
    ConversationRouteClassification,
    ConversationRouteDecision,
    ConversationRouteSelector,
)
from api.services.conversation.conversation_turn_contract import (
    ConversationTaskContinuationCandidate,
    ConversationTurnRoute,
)


class FakeModelUsageService:
    def __init__(self, models_by_id):
        self.models_by_id = models_by_id
        self.calls = []

    async def get_model_for_task(self, capabilities, explicit_model_id=None):
        self.calls.append((capabilities, explicit_model_id))
        value = self.models_by_id.get(explicit_model_id)
        if isinstance(value, Exception):
            raise value
        return value


def selector(*, models_by_id, call_with_schema, reasoning_model_id="reasoning-model"):
    return ConversationRouteSelector(
        model_usage_service=FakeModelUsageService(models_by_id),
        configured_reasoning_model_id=reasoning_model_id,
        call_with_schema=call_with_schema,
    )


def continuation_candidate(candidate_id: int) -> ConversationTaskContinuationCandidate:
    return ConversationTaskContinuationCandidate(
        candidate_id=candidate_id,
        root_task_id=f"root-{candidate_id}",
        previous_task_id=f"previous-{candidate_id}",
        request_text=f"Request {candidate_id}",
        outcome_text=f"Outcome {candidate_id}",
        terminal_status="completed",
    )


@pytest.mark.asyncio
async def test_selected_model_returns_direct_for_valid_structured_route():
    model = object()
    call_with_schema = AsyncMock(
        return_value=SimpleNamespace(
            value=ConversationRouteClassification(route=ConversationTurnRoute.DIRECT)
        )
    )
    route_selector = selector(
        models_by_id={"selected-model": model},
        call_with_schema=call_with_schema,
    )

    decision = await route_selector.select_route(
        content="What did we decide?",
        bounded_recent_messages=[
            {"role": "user", "content": "We discussed the deployment."},
            {"role": "assistant", "content": "We deferred it."},
            {"role": "system", "content": "Must not enter the prompt."},
        ],
        selected_model_id="selected-model",
        delegation_opt_out=False,
    )

    assert decision.route is ConversationTurnRoute.DIRECT
    assert route_selector._model_usage_service.calls == [
        ({ModelCapability.REASONING}, "selected-model")
    ]
    prompt = call_with_schema.await_args.kwargs["prompt"]
    assert "We discussed the deployment." in prompt
    assert "Must not enter the prompt." not in prompt
    assert call_with_schema.await_args.kwargs["response_model"] is ConversationRouteClassification


@pytest.mark.asyncio
async def test_selected_model_falls_back_only_to_configured_reasoning_model():
    reasoning_model = object()
    call_with_schema = AsyncMock(
        return_value=SimpleNamespace(
            value=ConversationRouteClassification(route=ConversationTurnRoute.AGENT_TASK)
        )
    )
    route_selector = selector(
        models_by_id={"selected-model": None, "reasoning-model": reasoning_model},
        call_with_schema=call_with_schema,
    )

    decision = await route_selector.select_route(
        content="Prepare a durable research brief.",
        bounded_recent_messages=[],
        selected_model_id="selected-model",
        delegation_opt_out=False,
    )

    assert decision.route is ConversationTurnRoute.AGENT_TASK
    assert [model_id for _, model_id in route_selector._model_usage_service.calls] == [
        "selected-model",
        "reasoning-model",
    ]


@pytest.mark.asyncio
async def test_selected_model_load_failure_falls_back_to_configured_reasoning_model():
    reasoning_model = object()
    call_with_schema = AsyncMock(
        return_value=SimpleNamespace(
            value=ConversationRouteClassification(route=ConversationTurnRoute.DIRECT)
        )
    )
    route_selector = selector(
        models_by_id={
            "selected-model": RuntimeError("selected model unavailable"),
            "reasoning-model": reasoning_model,
        },
        call_with_schema=call_with_schema,
    )

    decision = await route_selector.select_route(
        content="What did we decide?",
        bounded_recent_messages=[],
        selected_model_id="selected-model",
        delegation_opt_out=False,
    )

    assert decision.route is ConversationTurnRoute.DIRECT
    assert [model_id for _, model_id in route_selector._model_usage_service.calls] == [
        "selected-model",
        "reasoning-model",
    ]
    assert call_with_schema.await_args.args[0] is reasoning_model


@pytest.mark.asyncio
async def test_opt_out_returns_direct_without_model_resolution_or_inference():
    call_with_schema = AsyncMock()
    route_selector = selector(models_by_id={}, call_with_schema=call_with_schema)

    decision = await route_selector.select_route(
        content="Research the conversation history.",
        bounded_recent_messages=[],
        selected_model_id="selected-model",
        delegation_opt_out=True,
    )

    assert decision.route is ConversationTurnRoute.DIRECT
    assert route_selector._model_usage_service.calls == []
    call_with_schema.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call_with_schema",
    [
        AsyncMock(side_effect=asyncio.TimeoutError()),
        AsyncMock(side_effect=RuntimeError("structured output failed")),
        AsyncMock(return_value=SimpleNamespace(value={"route": "direct"})),
    ],
)
async def test_invalid_or_failed_classification_falls_closed_to_agent_task(call_with_schema):
    route_selector = selector(models_by_id={"reasoning-model": object()}, call_with_schema=call_with_schema)

    decision = await route_selector.select_route(
        content="Can you help with this?",
        bounded_recent_messages=[],
        selected_model_id=None,
        delegation_opt_out=False,
    )

    assert decision.route is ConversationTurnRoute.AGENT_TASK


@pytest.mark.asyncio
async def test_missing_models_and_blank_content_fall_closed_to_agent_task():
    call_with_schema = AsyncMock()
    route_selector = selector(models_by_id={}, call_with_schema=call_with_schema)

    no_model = await route_selector.select_route(
        content="Find the linked task.",
        bounded_recent_messages=[],
        selected_model_id=None,
        delegation_opt_out=False,
    )
    blank_content = await route_selector.select_route(
        content="   ",
        bounded_recent_messages=[],
        selected_model_id="selected-model",
        delegation_opt_out=False,
    )

    assert no_model.route is ConversationTurnRoute.AGENT_TASK
    assert blank_content.route is ConversationTurnRoute.AGENT_TASK
    call_with_schema.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_task_classification_retains_only_a_supplied_continuation_candidate():
    call_with_schema = AsyncMock(
        return_value=SimpleNamespace(
            value=ConversationRouteClassification(
                route=ConversationTurnRoute.AGENT_TASK,
                continuation_candidate_id=2,
            )
        )
    )
    route_selector = selector(
        models_by_id={"reasoning-model": object()},
        call_with_schema=call_with_schema,
    )
    candidates = [continuation_candidate(1), continuation_candidate(2)]

    decision = await route_selector.select_route(
        content="Break down the work you just completed.",
        bounded_recent_messages=[],
        selected_model_id=None,
        delegation_opt_out=False,
        continuation_candidates=candidates,
    )

    assert decision == ConversationRouteDecision(
        route=ConversationTurnRoute.AGENT_TASK,
        continuation_candidate_id=2,
    )
    prompt = call_with_schema.await_args.kwargs["prompt"]
    assert "root-1" not in prompt
    assert "previous-2" not in prompt
    assert '"candidate_id": 1' in prompt
    assert '"candidate_id": 2' in prompt


@pytest.mark.asyncio
async def test_direct_or_unknown_candidate_classifications_fall_back_to_no_continuation():
    candidates = [continuation_candidate(1)]
    direct_selector = selector(
        models_by_id={"reasoning-model": object()},
        call_with_schema=AsyncMock(
            return_value=SimpleNamespace(
                value=ConversationRouteClassification(
                    route=ConversationTurnRoute.DIRECT,
                    continuation_candidate_id=1,
                )
            )
        ),
    )
    unknown_selector = selector(
        models_by_id={"reasoning-model": object()},
        call_with_schema=AsyncMock(
            return_value=SimpleNamespace(
                value=ConversationRouteClassification(
                    route=ConversationTurnRoute.AGENT_TASK,
                    continuation_candidate_id=9,
                )
            )
        ),
    )

    direct = await direct_selector.select_route(
        content="What did we decide?",
        bounded_recent_messages=[],
        selected_model_id=None,
        delegation_opt_out=False,
        continuation_candidates=candidates,
    )
    unknown = await unknown_selector.select_route(
        content="Continue the research.",
        bounded_recent_messages=[],
        selected_model_id=None,
        delegation_opt_out=False,
        continuation_candidates=candidates,
    )

    assert direct.continuation_candidate_id is None
    assert unknown.continuation_candidate_id is None


def test_route_schema_rejects_legacy_or_extra_values():
    with pytest.raises(ValueError):
        ConversationRouteClassification.model_validate({"route": "contextual_agent"})
    with pytest.raises(ValueError):
        ConversationRouteClassification.model_validate(
            {"route": "direct", "confidence": 0.99}
        )
