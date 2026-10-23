"""Unit coverage for the fast-lane intent gate (P7).

Deterministic; no live model. Verifies the gate is a genuine structured
decision call (no keyword matching) and that every failure mode resolves to
escalation, never to guessing fast-lane.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services.agent_processing.lifecycle.submission import fast_lane_intent_gate
from api.services.agent_processing.lifecycle.submission.fast_lane_intent_gate import (
    FAST_LANE_CONFIDENCE_THRESHOLD,
    evaluate_fast_lane_intent,
)


@pytest.mark.asyncio
async def test_confident_context_answerable_takes_fast_lane(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        assert enable_web_search is False
        return '{"can_answer_from_context": true, "confidence": 0.92, "reason": "already explained above"}'

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)

    decision = await evaluate_fast_lane_intent(object(), "why did that fail?", "You: it failed because X.")

    assert decision.takes_fast_lane is True
    assert decision.confidence == 0.92


@pytest.mark.asyncio
async def test_low_confidence_escalates_even_when_answerable_flag_is_true(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        return '{"can_answer_from_context": true, "confidence": 0.4, "reason": "maybe"}'

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)

    decision = await evaluate_fast_lane_intent(object(), "and the other one?", "some history")

    assert decision.confidence < FAST_LANE_CONFIDENCE_THRESHOLD
    assert decision.takes_fast_lane is False


@pytest.mark.asyncio
async def test_execution_request_escalates(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        return '{"can_answer_from_context": false, "confidence": 0.95, "reason": "requires a new action"}'

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)

    decision = await evaluate_fast_lane_intent(object(), "now go ahead and do it", "history")

    assert decision.takes_fast_lane is False


@pytest.mark.asyncio
async def test_malformed_json_escalates_without_raising(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        return "not json at all"

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)

    decision = await evaluate_fast_lane_intent(object(), "explain that", "history")

    assert decision.takes_fast_lane is False


@pytest.mark.asyncio
async def test_syntactically_valid_non_object_json_escalates_without_raising(monkeypatch):
    """A model can emit valid JSON that isn't an object (e.g. a bare `null`);
    this must escalate like any other malformed response, not raise
    AttributeError from calling `.get(...)` on a non-dict payload."""
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        return "null"

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)

    decision = await evaluate_fast_lane_intent(object(), "explain that", "history")

    assert decision.takes_fast_lane is False


@pytest.mark.asyncio
async def test_model_call_exception_escalates_without_raising(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)

    decision = await evaluate_fast_lane_intent(object(), "explain that", "history")

    assert decision.takes_fast_lane is False


@pytest.mark.asyncio
async def test_timeout_escalates_without_raising(monkeypatch):
    async def _fake_caller(model, messages, *, enable_web_search=True, max_tokens=None):
        await asyncio.sleep(999)

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _fake_caller)
    monkeypatch.setattr(fast_lane_intent_gate, "_DECISION_TIMEOUT_SECONDS", 0.05)

    decision = await evaluate_fast_lane_intent(object(), "explain that", "history")

    assert decision.takes_fast_lane is False


@pytest.mark.asyncio
async def test_no_model_escalates_without_calling_anything(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("must not call the model when model is None")

    monkeypatch.setattr(fast_lane_intent_gate, "call_agent_model_with_messages", _boom)

    decision = await evaluate_fast_lane_intent(None, "explain that", "history")

    assert decision.takes_fast_lane is False
