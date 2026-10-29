"""Stored results expose the verifier's suggested follow-ups so a reopened task shows the same chips as a live one."""

from __future__ import annotations

from api.routes.agent_tasks.models import AgentTaskChainItem, AgentTaskDetailResponse
from api.routes.agent_tasks.utils import extract_suggested_follow_ups


def _stored(outcome: str, suggestions, *, key: str = "finalizer_result") -> dict:
    return {key: {"result_payload": {"outcome": outcome, "suggested_follow_ups": suggestions}}}


def test_a_clean_success_exposes_its_suggestions():
    assert extract_suggested_follow_ups(_stored("success", ["Draft a reply", "Archive the newsletters"])) == [
        "Draft a reply",
        "Archive the newsletters",
    ]


def test_every_storage_shape_the_finalizer_envelope_uses_is_read():
    assert extract_suggested_follow_ups(_stored("success", ["Draft a reply"], key="final_envelope")) == ["Draft a reply"]
    assert extract_suggested_follow_ups({"data": _stored("success", ["Draft a reply"])}) == ["Draft a reply"]
    assert extract_suggested_follow_ups({"result_payload": {"outcome": "success", "suggested_follow_ups": ["Draft a reply"]}}) == ["Draft a reply"]


def test_non_success_missing_and_malformed_results_give_no_suggestions():
    assert extract_suggested_follow_ups(_stored("partial", ["Do more"])) == []
    assert extract_suggested_follow_ups(_stored("failure", ["Do more"])) == []
    assert extract_suggested_follow_ups({"finalizer_result": {"result_payload": {"outcome": "success"}}}) == []
    assert extract_suggested_follow_ups(_stored("success", "Draft a reply")) == []
    assert extract_suggested_follow_ups(_stored("success", None)) == []
    assert extract_suggested_follow_ups(None) == []
    assert extract_suggested_follow_ups({}) == []


def test_suggestions_are_cleaned_deduplicated_and_capped_like_the_live_path():
    stored = _stored("success", ["  Draft   a reply ", "draft a reply", 7, "", "x" * 81, "Archive", "Summarize", "Delete the spam"])

    assert extract_suggested_follow_ups(stored) == ["Draft a reply", "Archive", "Summarize"]


def test_response_models_default_to_no_suggestions_for_older_clients_and_records():
    assert AgentTaskChainItem.model_fields["suggested_follow_ups"].default == []
    assert AgentTaskDetailResponse.model_fields["suggested_follow_ups"].default == []
