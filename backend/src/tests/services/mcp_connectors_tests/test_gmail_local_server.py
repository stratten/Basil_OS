"""Tests for the direct Gmail API connector (``gmail_local_server``).

Every test runs against an ``httpx.MockTransport`` injected through
``gmail_api.new_http_client``; nothing reaches Google.
"""

from __future__ import annotations

import base64
import email
import json
from typing import Any, Callable, Dict, List

import httpx
import pytest

from api.services.mcp_connectors.gmail_local_server import gmail_api, server
from api.services.mcp_connectors.mcp_client_service import MCPClientService

GMAIL_URL = "https://gmailmcp.googleapis.com/mcp/v1"
TOKEN = "ya29.test-token"

READ_ONLY_TOOLS = {"search_threads", "get_thread", "get_message", "list_drafts", "get_draft", "list_labels"}


class FakeGmail:
    """Routes Gmail API requests to canned responses and records what was sent."""

    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self.routes: Dict[tuple, Callable[[httpx.Request], httpx.Response]] = {}
        self.tokeninfo_scope = "https://www.googleapis.com/auth/gmail.modify"
        self.tokeninfo_status = 200

    def on(self, method: str, path: str, response: Any = None, status: int = 200) -> None:
        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json=response if response is not None else {})

        self.routes[(method, path)] = respond

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            if self.tokeninfo_status != 200:
                return httpx.Response(self.tokeninfo_status, json={"error": "invalid_token"})
            return httpx.Response(200, json={"scope": self.tokeninfo_scope, "expires_in": "3000"})
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        route = self.routes.get((request.method, path))
        if route is None:
            return httpx.Response(404, json={"error": {"code": 404, "message": f"unrouted {request.method} {path}", "status": "NOT_FOUND"}})
        return route(request)

    def sent(self, method: str, path: str) -> List[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.removeprefix("/gmail/v1/users/me") == path]


@pytest.fixture
def gmail(monkeypatch) -> FakeGmail:
    fake = FakeGmail()
    monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


async def call(tool: str, arguments: Dict[str, Any], token: str | None = TOKEN) -> Dict[str, Any]:
    return await server.call_tool(tool_name=tool, arguments=arguments, access_token=token)


def error_kind(envelope: Dict[str, Any]) -> str:
    assert envelope["ok"] is False, envelope
    return envelope["error"]["kind"]


def header_payload(**headers: str) -> Dict[str, Any]:
    return {"headers": [{"name": name.replace("_", "-"), "value": value} for name, value in headers.items()]}


@pytest.mark.asyncio
async def test_catalog_has_expected_tools_and_read_only_hints():
    catalog = await server.list_tools()
    tools = {tool["name"]: tool for tool in catalog["tools"]}
    assert {name for name, tool in tools.items() if tool["is_read_only_hint"]} == READ_ONLY_TOOLS
    for name in ("trash_thread", "trash_message", "send_draft", "create_draft", "label_thread", "create_label"):
        assert tools[name]["is_read_only_hint"] is False
    assert not any("delete" in name for name in tools), "the connector must never expose a permanent delete"
    assert "threadId" in tools["trash_thread"]["input_schema"]["properties"]
    assert "summary" in tools["trash_thread"]["input_schema"]["properties"]
    assert set(tools["send_draft"]["input_schema"]["required"]) == {"draftId", "recipients", "subject"}


@pytest.mark.asyncio
async def test_missing_token_is_auth_expired(gmail):
    assert error_kind(await call("list_labels", {}, token=None)) == "auth_expired"
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_unknown_tool_is_not_found(gmail):
    assert error_kind(await call("delete_forever", {})) == "not_found"


@pytest.mark.asyncio
async def test_invalid_arguments_never_reach_gmail(gmail):
    assert error_kind(await call("trash_thread", {})) == "invalid_arguments"
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_search_threads_excludes_drafts_and_fetches_metadata(gmail):
    gmail.on("GET", "/threads", {"threads": [{"id": "t1"}], "nextPageToken": "next"})
    gmail.on(
        "GET",
        "/threads/t1",
        {
            "id": "t1",
            "messages": [
                {
                    "id": "m1",
                    "threadId": "t1",
                    "labelIds": ["INBOX", "UNREAD"],
                    "snippet": "Lunch tomorrow?",
                    "internalDate": "1700000000000",
                    "payload": header_payload(From="Ann <ann@example.com>", To="me@example.com", Subject="Lunch"),
                }
            ],
        },
    )
    result = await call("search_threads", {"query": "from:ann"})
    assert result["ok"] is True
    listing = gmail.sent("GET", "/threads")[0]
    assert listing.url.params["q"] == "from:ann -in:draft"
    assert gmail.sent("GET", "/threads/t1")[0].url.params["format"] == "metadata"
    assert listing.headers["authorization"] == f"Bearer {TOKEN}"
    structured = result["result"]["structured"]
    assert structured["nextPageToken"] == "next"
    assert structured["threads"][0]["subject"] == "Lunch"
    assert "t1" in result["result"]["text"]


@pytest.mark.asyncio
async def test_search_keeps_drafts_when_the_query_asks_for_them(gmail):
    gmail.on("GET", "/threads", {"threads": []})
    await call("search_threads", {"query": "in:draft budget"})
    assert gmail.sent("GET", "/threads")[0].url.params["q"] == "in:draft budget"


@pytest.mark.asyncio
async def test_trash_thread_posts_to_trash_and_never_deletes(gmail):
    gmail.on("POST", "/threads/t1/trash", {"id": "t1", "messages": [{"id": "m1", "labelIds": ["TRASH"]}]})
    result = await call("trash_thread", {"threadId": "t1", "summary": "Newsletter from Acme"})
    assert result["ok"] is True
    assert result["result"]["structured"]["labelIds"] == ["TRASH"]
    assert "30 days" in result["result"]["text"]
    assert [r.method for r in gmail.requests] == ["POST"]
    assert not any(r.method == "DELETE" for r in gmail.requests)


@pytest.mark.asyncio
async def test_apply_sensitive_label_trash_uses_the_trash_endpoint(gmail):
    gmail.on("POST", "/messages/m1/trash", {"id": "m1", "threadId": "t1", "labelIds": ["TRASH"]})
    result = await call("apply_sensitive_message_label", {"messageId": "m1", "labelOption": "TRASH"})
    assert result["ok"] is True
    assert len(gmail.sent("POST", "/messages/m1/trash")) == 1


@pytest.mark.asyncio
async def test_generic_label_tools_refuse_trash_and_spam(gmail):
    assert error_kind(await call("label_thread", {"threadId": "t1", "labelIds": ["TRASH"]})) == "invalid_arguments"
    assert error_kind(await call("label_message", {"messageId": "m1", "labelIds": ["spam"]})) == "invalid_arguments"
    assert error_kind(await call("update_message_labels", {"messageId": "m1", "addLabelIds": ["TRASH"]})) == "invalid_arguments"
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_unlabel_inbox_archives(gmail):
    gmail.on("POST", "/threads/t1/modify", {"id": "t1", "messages": [{"id": "m1", "labelIds": []}]})
    result = await call("unlabel_thread", {"threadId": "t1", "labelIds": ["INBOX"]})
    assert result["ok"] is True
    body = json.loads(gmail.sent("POST", "/threads/t1/modify")[0].content)
    assert body == {"addLabelIds": [], "removeLabelIds": ["INBOX"]}


def _draft_response(to: str, subject: str, cc: str = "") -> Dict[str, Any]:
    headers: Dict[str, str] = {"To": to, "Subject": subject}
    if cc:
        headers["Cc"] = cc
    return {"id": "d1", "message": {"id": "m9", "threadId": "t9", "payload": header_payload(**headers)}}


@pytest.mark.asyncio
async def test_send_draft_sends_when_recipients_and_subject_match(gmail):
    gmail.on("GET", "/drafts/d1", _draft_response("Ann <ann@example.com>", "Lunch", cc="bob@example.com"))
    gmail.on("POST", "/drafts/send", {"id": "m9", "threadId": "t9", "labelIds": ["SENT"]})
    result = await call("send_draft", {"draftId": "d1", "recipients": ["BOB@example.com", "ann@example.com"], "subject": "Lunch"})
    assert result["ok"] is True, result
    assert json.loads(gmail.sent("POST", "/drafts/send")[0].content) == {"id": "d1"}


@pytest.mark.asyncio
async def test_send_draft_refuses_a_recipient_mismatch(gmail):
    gmail.on("GET", "/drafts/d1", _draft_response("ann@example.com", "Lunch"))
    result = await call("send_draft", {"draftId": "d1", "recipients": ["someone.else@example.com"], "subject": "Lunch"})
    assert error_kind(result) == "invalid_arguments"
    assert "ann@example.com" in result["error"]["message"]
    assert gmail.sent("POST", "/drafts/send") == []


@pytest.mark.asyncio
async def test_send_draft_refuses_a_subject_mismatch_and_an_empty_draft(gmail):
    gmail.on("GET", "/drafts/d1", _draft_response("ann@example.com", "Lunch"))
    assert error_kind(await call("send_draft", {"draftId": "d1", "recipients": ["ann@example.com"], "subject": "Dinner"})) == "invalid_arguments"
    gmail.on("GET", "/drafts/d2", {"id": "d2", "message": {"id": "m2", "payload": header_payload(Subject="No one")}})
    assert error_kind(await call("send_draft", {"draftId": "d2", "recipients": [], "subject": "No one"})) == "invalid_arguments"
    assert gmail.sent("POST", "/drafts/send") == []


@pytest.mark.asyncio
async def test_create_draft_reply_joins_thread_without_quoting_the_original(gmail):
    original = {
        "id": "m1",
        "threadId": "t1",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Ann <ann@example.com>"},
                {"name": "Subject", "value": "Lunch"},
                {"name": "Message-ID", "value": "<abc@mail.example.com>"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"Are you free?").decode()},
        },
    }
    gmail.on("GET", "/messages/m1", original)
    gmail.on("POST", "/drafts", {"id": "d1", "message": {"id": "m9", "threadId": "t1"}})
    result = await call("create_draft", {"replyToMessageId": "m1", "body": "Yes, noon works."})
    assert result["ok"] is True, result
    assert result["result"]["structured"]["id"] == "d1"
    payload = json.loads(gmail.sent("POST", "/drafts")[0].content)
    assert payload["message"]["threadId"] == "t1"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(payload["message"]["raw"]))
    assert parsed["To"] == "ann@example.com"
    assert parsed["Subject"] == "Re: Lunch"
    assert parsed["In-Reply-To"] == "<abc@mail.example.com>"
    body = parsed.get_payload(decode=True).decode() if not parsed.is_multipart() else parsed.get_payload()[0].get_payload(decode=True).decode()
    assert body.strip() == "Yes, noon works."
    assert "Are you free?" not in body and "wrote:" not in body
    assert not parsed.is_multipart()
    fetches = gmail.sent("GET", "/messages/m1")
    assert [request.url.params.get("format") for request in fetches] == ["metadata"]


@pytest.mark.asyncio
async def test_create_draft_rejects_a_malformed_address(gmail):
    result = await call("create_draft", {"to": ["not-an-address"], "subject": "x", "body": "y"})
    assert error_kind(result) == "invalid_arguments"
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_create_label_creates_missing_parents(gmail):
    gmail.on("GET", "/labels", {"labels": [{"id": "L1", "name": "Projects"}]})
    gmail.on("POST", "/labels", {"id": "L9", "name": "Projects/Alpha/2026"})
    result = await call("create_label", {"displayName": "Projects/Alpha/2026"})
    assert result["ok"] is True
    names = [json.loads(r.content)["name"] for r in gmail.sent("POST", "/labels")]
    assert names == ["Projects/Alpha", "Projects/Alpha/2026"]
    assert result["result"]["structured"]["createdParentLabels"] == ["Projects/Alpha"]


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (401, {"code": 401, "message": "expired", "status": "UNAUTHENTICATED"}, "auth_expired"),
        (403, {"code": 403, "message": "scope", "status": "PERMISSION_DENIED", "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}, "permission_denied"),
        (403, {"code": 403, "message": "off", "status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}, "permission_denied"),
        (404, {"code": 404, "message": "gone", "status": "NOT_FOUND"}, "not_found"),
        (409, {"code": 409, "message": "Label name exists or conflicts", "status": "ALREADY_EXISTS"}, "invalid_arguments"),
        (429, {"code": 429, "message": "slow down", "status": "RESOURCE_EXHAUSTED"}, "rate_limited"),
        (500, {"code": 500, "message": "oops", "status": "INTERNAL"}, "server_error"),
    ],
)
@pytest.mark.asyncio
async def test_gmail_errors_map_to_standard_kinds(gmail, status, error, expected):
    gmail.on("GET", "/labels", {"error": error}, status=status)
    result = await call("list_labels", {})
    assert error_kind(result) == expected
    if expected == "auth_expired":
        assert "Reconnect" in result["error"]["user_action_required"]
    if status == 403 and error["details"][0]["reason"] == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
        assert "Reconnect" in result["error"]["user_action_required"]
    if expected in ("rate_limited", "server_error"):
        assert result["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_timeout_and_network_failures_are_enveloped(monkeypatch):
    def timing_out(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(timing_out)))
    assert error_kind(await call("list_labels", {})) == "timeout"
    monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(unreachable)))
    assert error_kind(await call("list_labels", {})) == "network_error"


@pytest.mark.asyncio
async def test_error_message_never_contains_the_token(gmail):
    gmail.on("GET", "/labels", {"error": {"code": 500, "message": "boom", "status": "INTERNAL"}}, status=500)
    assert TOKEN not in json.dumps(await call("list_labels", {}))


class TestRouting:
    def test_gmail_url_routes_locally_by_default(self, monkeypatch):
        monkeypatch.delenv("BASIL_GMAIL_TRANSPORT", raising=False)
        assert MCPClientService._routes_to_local_server(GMAIL_URL) is True

    def test_mcp_transport_env_restores_the_hosted_server(self, monkeypatch):
        monkeypatch.setenv("BASIL_GMAIL_TRANSPORT", "mcp")
        assert MCPClientService._routes_to_local_server(GMAIL_URL) is False

    def test_other_urls_are_untouched(self, monkeypatch):
        monkeypatch.delenv("BASIL_GMAIL_TRANSPORT", raising=False)
        assert MCPClientService._routes_to_local_server("https://example.com/mcp") is False
        assert MCPClientService._routes_to_local_server("basil-local://slack") is True

    @pytest.mark.asyncio
    async def test_client_service_serves_gmail_through_the_api(self, gmail, monkeypatch):
        monkeypatch.delenv("BASIL_GMAIL_TRANSPORT", raising=False)
        gmail.on("GET", "/labels", {"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]})
        gmail.on("GET", "/profile", {"emailAddress": "me@example.com"})
        service = MCPClientService()
        listed = await service.list_tools(GMAIL_URL, access_token=TOKEN)
        assert listed["ok"] is True and len(listed["result"]["tools"]) == 25
        called = await service.call_tool(GMAIL_URL, "list_labels", {}, access_token=TOKEN)
        assert called["ok"] is True
        assert called["result"]["structured"]["labels"][0]["id"] == "INBOX"


class TestConnectionCheck:
    @pytest.mark.asyncio
    async def test_success_reports_mailbox_and_scopes_and_sends_the_token_in_the_body(self, gmail):
        gmail.on("GET", "/profile", {"emailAddress": "me@example.com"})
        result = await server.verified_list_tools(access_token=TOKEN)
        assert result["ok"] is True
        assert result["result"]["server"]["account_summary"] == "Signed in as me@example.com with gmail.modify."
        assert len(result["result"]["tools"]) == 25
        tokeninfo = [r for r in gmail.requests if r.url.host == "oauth2.googleapis.com"][0]
        assert tokeninfo.method == "POST" and TOKEN not in str(tokeninfo.url)
        assert b"ya29.test-token" in tokeninfo.content

    @pytest.mark.asyncio
    async def test_missing_token_is_auth_expired_without_any_request(self, gmail):
        assert error_kind(await server.verified_list_tools(access_token=None)) == "auth_expired"
        assert gmail.requests == []

    @pytest.mark.asyncio
    async def test_a_token_google_rejects_is_auth_expired(self, gmail):
        gmail.tokeninfo_status = 400
        result = await server.verified_list_tools(access_token=TOKEN)
        assert error_kind(result) == "auth_expired"
        assert result["error"]["user_action_required"]

    @pytest.mark.asyncio
    async def test_a_token_without_gmail_modify_is_permission_denied_and_names_what_was_granted(self, gmail):
        gmail.tokeninfo_scope = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"
        result = await server.verified_list_tools(access_token=TOKEN)
        assert error_kind(result) == "permission_denied"
        assert "gmail.readonly" in result["error"]["message"] and "gmail.compose" in result["error"]["message"]
        assert "Reconnect Gmail" in result["error"]["user_action_required"]
        assert gmail.sent("GET", "/profile") == []

    @pytest.mark.asyncio
    async def test_full_gmail_access_counts_as_modify(self, gmail):
        gmail.tokeninfo_scope = "https://mail.google.com/"
        gmail.on("GET", "/profile", {"emailAddress": "me@example.com"})
        assert (await server.verified_list_tools(access_token=TOKEN))["ok"] is True

    @pytest.mark.asyncio
    async def test_gmail_api_turned_off_is_reported_with_the_console_fix(self, gmail):
        gmail.on(
            "GET",
            "/profile",
            {"error": {"code": 403, "message": "Gmail API has not been used", "status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}},
            status=403,
        )
        result = await server.verified_list_tools(access_token=TOKEN)
        assert error_kind(result) == "permission_denied"
        assert "Gmail API" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_unreachable_google_is_a_retryable_network_error(self, monkeypatch):
        def unreachable(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(unreachable)))
        result = await server.verified_list_tools(access_token=TOKEN)
        assert error_kind(result) == "network_error" and result["error"]["retryable"] is True

    @pytest.mark.asyncio
    async def test_status_message_includes_the_account_summary(self):
        from datetime import datetime

        from api.services.mcp_connectors.connection_status_service import _healthy_from_envelope

        envelope = {"ok": True, "result": {"tools": [{}], "server": {"account_summary": "Signed in as me@example.com with gmail.modify."}}}
        message = _healthy_from_envelope(envelope, datetime.now(), refreshed=False).message
        assert message == "Connection validated successfully (1 tool(s) visible). Signed in as me@example.com with gmail.modify."
        plain = _healthy_from_envelope({"ok": True, "result": {"tools": [{}], "server": None}}, datetime.now(), refreshed=False).message
        assert plain == "Connection validated successfully (1 tool(s) visible)."


def test_approval_prompt_leads_with_the_summary():
    from api.services.agent_processing.tools.external_services.external_catalog.approval import _arguments_for_prompt

    ordered = _arguments_for_prompt({"threadId": "18f", "summary": "  Invoice from Acme  "})
    assert list(ordered) == ["summary", "threadId"]
    assert ordered["summary"] == "Invoice from Acme"
    assert len(_arguments_for_prompt({"summary": "x" * 500})["summary"]) == 120
    plain = {"threadId": "18f"}
    assert _arguments_for_prompt(plain) is plain
    assert _arguments_for_prompt({"summary": "  "}) == {"summary": "  "}
