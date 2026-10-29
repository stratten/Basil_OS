"""Replying through the direct Gmail connector goes to everyone on the original, like Reply All, unless the user asked otherwise."""

from __future__ import annotations

import base64
import email
import json
from typing import Any, Dict, List

import httpx
import pytest

from api.services.mcp_connectors.gmail_local_server import gmail_api, server
from api.services.mcp_connectors.gmail_local_server.reply_recipients import plan_reply_recipients

TOKEN = "ya29.test-token"
ME = "me@example.com"
ALIAS = "me@alias.example.org"


def plan(*, sender="Ann <ann@example.com>", reply_to="", to="", cc="", reply_all=True, own=(ME, ALIAS)):
    return plan_reply_recipients(
        from_header=sender,
        reply_to_header=reply_to,
        to_header=to,
        cc_header=cc,
        own_addresses=set(own),
        reply_all=reply_all,
    )


def test_a_reply_all_goes_to_the_sender_and_the_other_to_recipients_and_keeps_cc():
    result = plan(to=f"Me <{ME}>, Bob <bob@example.com>", cc="Cy <cy@example.com>")

    assert result.to == ("ann@example.com", "bob@example.com")
    assert result.cc == ("cy@example.com",)


def test_the_users_own_addresses_and_aliases_are_never_added():
    result = plan(to=f"{ME}, {ALIAS.upper()}, bob@example.com", cc=f"{ALIAS}, cy@example.com")

    assert result.to == ("ann@example.com", "bob@example.com")
    assert result.cc == ("cy@example.com",)


def test_an_address_appears_once_even_when_it_is_in_to_and_cc_and_in_different_case():
    result = plan(to="Bob <bob@example.com>, ANN@example.com", cc="BOB@example.com, cy@example.com, cy@example.com")

    assert result.to == ("ann@example.com", "bob@example.com")
    assert result.cc == ("cy@example.com",)


def test_a_reply_to_header_replaces_the_from_address_as_the_sender():
    result = plan(sender="List <list@example.com>", reply_to="Ann <ann@example.com>", to="bob@example.com")

    assert result.to == ("ann@example.com", "bob@example.com")


def test_replying_to_the_sender_alone_ignores_the_other_recipients():
    result = plan(to="bob@example.com", cc="cy@example.com", reply_all=False)

    assert result.to == ("ann@example.com",)
    assert result.cc == ()


def test_replying_to_a_message_the_user_sent_goes_to_the_people_it_was_sent_to():
    everyone = plan(sender=f"Me <{ME}>", to="ann@example.com, bob@example.com", cc="cy@example.com")
    sender_only = plan(sender=f"Me <{ME}>", to="ann@example.com, bob@example.com", cc="cy@example.com", reply_all=False)

    assert everyone.to == ("ann@example.com", "bob@example.com") and everyone.cc == ("cy@example.com",)
    assert sender_only.to == ("ann@example.com", "bob@example.com") and sender_only.cc == ()


def test_a_message_the_user_sent_to_nobody_but_copied_others_moves_the_cc_into_to():
    result = plan(sender=ME, to="", cc="cy@example.com")

    assert result.to == ("cy@example.com",) and result.cc == ()


def test_a_message_with_no_usable_headers_gives_no_recipients():
    result = plan(sender="", to="", cc="")

    assert result.to == () and result.cc == ()


class FakeGmail:
    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self.responses: Dict[tuple, Any] = {}

    def on(self, method: str, path: str, response: Any, status: int = 200) -> None:
        self.responses[(method, path)] = (status, response)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        status, response = self.responses.get((request.method, path), (404, {"error": {"code": 404, "message": f"unrouted {path}", "status": "NOT_FOUND"}}))
        return httpx.Response(status, json=response)

    def drafts_created(self) -> List[Dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests if request.method == "POST" and request.url.path.endswith("/drafts")]


@pytest.fixture
def gmail(monkeypatch) -> FakeGmail:
    fake = FakeGmail()
    monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    fake.on("GET", "/profile", {"emailAddress": ME})
    fake.on("GET", "/settings/sendAs", {"sendAs": [{"sendAsEmail": ME, "isDefault": True}, {"sendAsEmail": ALIAS}]})
    fake.on(
        "GET",
        "/messages/m1",
        {
            "id": "m1",
            "threadId": "t1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Ann <ann@example.com>"},
                    {"name": "To", "value": f"{ME}, Bob <bob@example.com>"},
                    {"name": "Cc", "value": "Cy <cy@example.com>"},
                    {"name": "Subject", "value": "Lunch"},
                    {"name": "Message-ID", "value": "<abc@mail.example.com>"},
                ]
            },
        },
    )
    fake.on("POST", "/drafts", {"id": "d1", "message": {"id": "m9", "threadId": "t1"}})
    return fake


async def create_draft(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await server.call_tool(tool_name="create_draft", arguments={"body": "Noon works.", **arguments}, access_token=TOKEN)


def headers_of(fake: FakeGmail) -> email.message.Message:
    raw = fake.drafts_created()[0]["message"]["raw"]
    return email.message_from_bytes(base64.urlsafe_b64decode(raw))


@pytest.mark.asyncio
async def test_a_reply_defaults_to_everyone_on_the_original(gmail):
    result = await create_draft({"replyToMessageId": "m1"})

    assert result["ok"] is True, result
    parsed = headers_of(gmail)
    assert parsed["To"] == "ann@example.com, bob@example.com"
    assert parsed["Cc"] == "cy@example.com"
    structured = result["result"]["structured"]
    assert structured["to"] == ["ann@example.com", "bob@example.com"] and structured["cc"] == ["cy@example.com"]
    assert "To: ann@example.com, bob@example.com. Cc: cy@example.com." in result["result"]["text"]


@pytest.mark.asyncio
async def test_reply_all_false_replies_to_the_sender_alone(gmail):
    await create_draft({"replyToMessageId": "m1", "replyAll": False})

    parsed = headers_of(gmail)
    assert parsed["To"] == "ann@example.com"
    assert parsed["Cc"] is None


@pytest.mark.asyncio
async def test_an_explicit_to_is_used_exactly_and_adds_no_automatic_cc(gmail):
    await create_draft({"replyToMessageId": "m1", "to": ["dee@example.com"]})

    parsed = headers_of(gmail)
    assert parsed["To"] == "dee@example.com"
    assert parsed["Cc"] is None


@pytest.mark.asyncio
async def test_an_explicit_cc_alone_keeps_the_reply_all_to_and_replaces_the_cc(gmail):
    await create_draft({"replyToMessageId": "m1", "cc": ["eve@example.com"]})

    parsed = headers_of(gmail)
    assert parsed["To"] == "ann@example.com, bob@example.com"
    assert parsed["Cc"] == "eve@example.com"


@pytest.mark.asyncio
async def test_a_failed_own_address_lookup_does_not_fail_the_draft(gmail):
    gmail.on("GET", "/profile", {"error": {"code": 500, "message": "boom", "status": "INTERNAL"}}, status=500)
    gmail.on("GET", "/settings/sendAs", {"error": {"code": 500, "message": "boom", "status": "INTERNAL"}}, status=500)

    result = await create_draft({"replyToMessageId": "m1"})

    assert result["ok"] is True, result
    assert headers_of(gmail)["To"] == f"ann@example.com, {ME}, bob@example.com"


@pytest.mark.asyncio
async def test_a_draft_that_is_not_a_reply_is_unchanged(gmail):
    result = await create_draft({"to": ["dee@example.com"], "subject": "Hello"})

    assert result["ok"] is True, result
    parsed = headers_of(gmail)
    assert parsed["To"] == "dee@example.com" and parsed["Cc"] is None
    assert [request.url.path for request in gmail.requests if request.method == "GET"] == []


@pytest.mark.asyncio
async def test_the_tool_text_tells_the_agent_to_reply_to_everyone_by_default():
    catalog = await server.list_tools()
    tool = next(tool for tool in catalog["tools"] if tool["name"] == "create_draft")

    assert "replyAll" in tool["input_schema"]["properties"]
    assert tool["input_schema"]["properties"]["replyAll"]["default"] is True
    assert "Reply All" in tool["description"]
