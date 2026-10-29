import pytest

from api.services.meeting_companion.models import CompanionWatch
from api.services.meeting_companion.watches import (
    MAX_ACTIVE_WATCHES,
    WatchRejected,
    build_watch_created_payload,
    parse_watch_request,
    watch_event_payload,
)


def test_parse_watch_request_variants():
    assert parse_watch_request("When billing comes up, show me the endpoint") == ("billing", "show me the endpoint")
    assert parse_watch_request("whenever the retry policy is mentioned: summarize it.") == ("the retry policy", "summarize it")
    assert parse_watch_request("Once pricing gets discussed - pull up last quarter's numbers") == ("pricing", "pull up last quarter's numbers")
    assert parse_watch_request("if the migration is brought up give me the rollback plan") == ("the migration", "give me the rollback plan")


def test_parse_watch_request_rejects_non_requests():
    assert parse_watch_request("What happens when billing comes up") is None
    assert parse_watch_request("when billing comes up") is None
    assert parse_watch_request("when billing comes up,   ") is None
    assert parse_watch_request("") is None
    assert parse_watch_request("How does the retry policy work?") is None


def test_build_payload_validates_and_derives_keywords():
    payload = build_watch_created_payload("  billing   endpoint ", "Show the handler", active_count=0, id_factory=lambda: "w-1")
    assert payload == {
        "watch_id": "w-1",
        "state": "created",
        "topic": "billing endpoint",
        "instruction": "Show the handler",
        "keywords": ["billing", "endpoint"],
    }
    default_instruction = build_watch_created_payload("billing", "", active_count=0, id_factory=lambda: "w-2")
    assert default_instruction["instruction"] == "Show me what is relevant about billing."


@pytest.mark.parametrize(
    "topic,instruction,active",
    [
        ("ab", "x", 0),
        ("x" * 121, "x", 0),
        ("billing", "y" * 501, 0),
        ("the and for", "x", 0),
        ("billing", "x", MAX_ACTIVE_WATCHES),
    ],
)
def test_build_payload_rejections(topic, instruction, active):
    with pytest.raises(WatchRejected):
        build_watch_created_payload(topic, instruction, active_count=active)


def test_watch_event_payload_copies_fields():
    watch = CompanionWatch(id="w-1", topic="billing", instruction="Show", keywords=["billing"], created_at=1.0)
    payload = watch_event_payload(watch, "triggered")
    assert payload == {"watch_id": "w-1", "state": "triggered", "topic": "billing", "instruction": "Show", "keywords": ["billing"]}
    payload["keywords"].append("other")
    assert watch.keywords == ["billing"]
