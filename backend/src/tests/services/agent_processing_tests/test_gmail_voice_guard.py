"""The first Gmail draft of a run is answered with the user's writing voice, so agent drafts sound like the user and not like an assistant."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.external_services.external_catalog import actions as external_catalog_actions
from api.services.agent_processing.tools.external_services.external_catalog import voice_guard
from api.services.agent_processing.tools.external_services.external_catalog.voice_guard import check_voice_guidance

GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"

STYLE_ATTRIBUTES = {
    "style_summary": "Direct and warm. Starts with Hey and signs off with a short offer to help.",
    "formality_level": 0.3,
    "greeting_patterns": ["Hey [Name],"],
    "common_phrases": ["all good", "heads up"],
    "uses_contractions": True,
}


def _record(server_url: str = GMAIL_URL):
    return SimpleNamespace(id="gmail", friendly_name="Gmail", server_url=server_url)


def _personalization(style=True, samples=True, contact=False):
    return SimpleNamespace(
        style=SimpleNamespace(style_attributes=json.dumps(STYLE_ATTRIBUTES)) if style else None,
        writing_samples=[SimpleNamespace(recipient="ann@example.com", content="Hey Ann, all good on our end.")] if samples else [],
        contact=(
            SimpleNamespace(contact_name="Ann", contact_company="Acme", relationship_type="client", formality_level="casual", message_count=12)
            if contact
            else None
        ),
        profile=None,
        signature=None,
    )


async def _check(arguments=None, tool_name="create_draft", record=None, context=None, personalization=None):
    return await check_voice_guidance(
        record or _record(),
        tool_name,
        arguments if arguments is not None else {"body": "Sounds good."},
        context=context if context is not None else {},
        personalization=personalization if personalization is not None else _personalization(),
    )


@pytest.mark.asyncio
async def test_the_first_draft_of_a_run_returns_the_users_style_and_creates_nothing():
    envelope = await _check()

    assert envelope["ok"] is False
    assert envelope["error"]["kind"] == "voice_guidance_required"
    assert envelope["error"]["retryable"] is True
    message = envelope["error"]["message"]
    assert "nothing was created" in message
    assert "Direct and warm" in message
    assert "Uses Contractions: Yes" in message
    assert "Hey [Name]," in message
    assert "Use contractions when their style does" in message
    assert "do not restate or summarize the thread" in message
    assert "use no Markdown even if a sample does" in message


@pytest.mark.asyncio
async def test_writing_samples_and_the_recipient_relationship_are_included_when_known():
    envelope = await _check(personalization=_personalization(contact=True))

    message = envelope["error"]["message"]
    assert "Hey Ann, all good on our end." in message
    assert "Organization: Acme" in message


@pytest.mark.asyncio
async def test_a_later_draft_in_the_same_run_goes_straight_through():
    context = {}

    first = await _check(context=context)
    second = await _check(context=context)

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_a_new_run_is_guided_again():
    assert await _check(context={}) is not None
    assert await _check(context={}) is not None


@pytest.mark.asyncio
async def test_only_create_draft_on_a_gmail_connection_is_guarded():
    assert await _check(tool_name="get_thread") is None
    assert await _check(tool_name="send_draft") is None
    assert await _check(tool_name="label_thread") is None
    assert await _check(record=_record("https://mcp.linear.app/mcp")) is None


@pytest.mark.asyncio
async def test_a_run_with_no_context_is_never_blocked(monkeypatch):
    monkeypatch.setattr(voice_guard, "_guidance_context", lambda: None)

    envelope = await check_voice_guidance(_record(), "create_draft", {"body": "x"}, personalization=_personalization())

    assert envelope is None


@pytest.mark.asyncio
async def test_a_user_with_no_learned_voice_is_not_delayed_and_is_not_asked_again():
    context = {}
    empty = _personalization(style=False, samples=False)

    assert await _check(context=context, personalization=empty) is None
    assert context[voice_guard._GUIDED_KEY] is True
    assert await _check(context=context) is None


@pytest.mark.asyncio
async def test_a_lookup_failure_lets_the_draft_proceed(monkeypatch):
    async def broken(is_reply, recipient):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(voice_guard, "_load_personalization", broken)
    context = {}

    envelope = await check_voice_guidance(_record(), "create_draft", {"body": "x"}, context=context)

    assert envelope is None
    assert context[voice_guard._GUIDED_KEY] is True


@pytest.mark.asyncio
async def test_a_reply_uses_the_reply_style_and_the_first_recipient_is_looked_up(monkeypatch):
    seen = []

    async def fake_load(is_reply, recipient):
        seen.append((is_reply, recipient))
        return _personalization()

    monkeypatch.setattr(voice_guard, "_load_personalization", fake_load)

    await check_voice_guidance(_record(), "create_draft", {"replyToMessageId": "m1", "to": ["", "ann@example.com"]}, context={})
    await check_voice_guidance(_record(), "create_draft", {"to": ["bob@example.com"], "body": "x"}, context={})
    await check_voice_guidance(_record(), "create_draft", {"body": "x"}, context={})

    assert seen == [(True, "ann@example.com"), (False, "bob@example.com"), (False, None)]


@pytest.mark.asyncio
async def test_very_long_samples_cannot_flood_the_agents_context():
    huge = _personalization()
    huge.writing_samples = [SimpleNamespace(recipient="x@example.com", content="word " * 5000) for _ in range(3)]

    envelope = await _check(personalization=huge)

    assert len(envelope["error"]["message"]) < 4200


def _install_dispatch(monkeypatch, context):
    record = SimpleNamespace(
        id="gmail",
        friendly_name="Gmail",
        description=None,
        server_url=GMAIL_URL,
        enabled=True,
        cached_tools=[],
        tool_policies={"create_draft": "always_ask"},
        last_connection_status="connected",
    )
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))
    seen = {"approval": 0, "remote": [], "audit": []}

    async def fake_approval(*args, **kwargs):
        seen["approval"] += 1
        return True

    async def fake_audit(**kwargs):
        seen["audit"].append(kwargs)

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="tok")

    async def fake_schema_guard(record_arg, connection_id, tool_name):
        return None

    async def fake_attribution(record_arg, tool_name, arguments, **kwargs):
        return arguments, None

    async def fake_load(is_reply, recipient):
        return _personalization()

    class FakeClient:
        async def call_tool(self, server_url, tool_name, arguments, access_token):
            seen["remote"].append((tool_name, arguments))
            return {"ok": True, "result": {}}

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "request_external_catalog_user_approval", fake_approval)
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "ensure_tool_schema_surfaced", fake_schema_guard)
    monkeypatch.setattr(external_catalog_actions, "check_restoration_attribution", fake_attribution)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: FakeClient())
    monkeypatch.setattr(voice_guard, "_guidance_context", lambda: context)
    monkeypatch.setattr(voice_guard, "_load_personalization", fake_load)
    return seen


@pytest.mark.asyncio
async def test_dispatch_answers_the_first_draft_with_guidance_then_creates_the_second_after_approval(monkeypatch):
    seen = _install_dispatch(monkeypatch, {})

    first = await external_catalog_actions.call_external_catalog_tool("gmail", "create_draft", {"body": "Sounds good."})

    assert first["error"]["kind"] == "voice_guidance_required"
    assert seen["approval"] == 0
    assert seen["remote"] == []
    assert seen["audit"] == []

    second = await external_catalog_actions.call_external_catalog_tool("gmail", "create_draft", {"body": "Sounds good, Ann. Noon works."})

    assert second["ok"] is True
    assert seen["approval"] == 1
    assert seen["remote"] == [("create_draft", {"body": "Sounds good, Ann. Noon works."})]
