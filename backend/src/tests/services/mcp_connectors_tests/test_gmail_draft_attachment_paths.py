"""Tests for attaching files to a Gmail draft by path.

Gmail is faked with an ``httpx.MockTransport``. Files live under ``tmp_path``, and HOME is pointed there so the protected-folder checks run against a throwaway home.
"""

from __future__ import annotations

import base64
import email
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from api.services.mcp_connectors.gmail_local_server import attachment_files, gmail_api, mime_builder, server
from api.services.mcp_connectors.gmail_local_server.schemas import DraftAttachment

TOKEN = "ya29.test-token"
PDF_BYTES = b"%PDF-1.4 " + bytes(range(256)) * 300


class FakeGmail:
    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        if request.method == "POST" and path == "/drafts":
            return httpx.Response(200, json={"id": "d1", "message": {"id": "m9", "threadId": "t1"}})
        return httpx.Response(404, json={"error": {"code": 404, "message": f"unrouted {path}", "status": "NOT_FOUND"}})

    def drafted_message(self) -> email.message.Message:
        posts = [request for request in self.requests if request.method == "POST" and request.url.path.endswith("/drafts")]
        assert len(posts) == 1
        raw = json.loads(posts[0].content)["message"]["raw"]
        return email.message_from_bytes(base64.urlsafe_b64decode(raw))


@pytest.fixture
def gmail(monkeypatch) -> FakeGmail:
    fake = FakeGmail()
    monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    return folder


async def call(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await server.call_tool(tool_name="create_draft", arguments=arguments, access_token=TOKEN)


def _attachments(message: email.message.Message) -> List[email.message.Message]:
    return [part for part in message.walk() if part.get_content_disposition() == "attachment"]


def _write_pdf(home: Path, name: str = "SOW v4.pdf") -> Path:
    documents = home / "Documents"
    documents.mkdir(exist_ok=True)
    target = documents / name
    target.write_bytes(PDF_BYTES)
    return target


@pytest.mark.asyncio
async def test_a_file_named_by_path_is_attached_byte_for_byte(gmail, home):
    pdf = _write_pdf(home)
    result = await call({"to": ["ann@example.com"], "subject": "SOW", "body": "Attached.", "attachments": [{"path": str(pdf)}]})
    assert result["ok"] is True, result
    attached = _attachments(gmail.drafted_message())
    assert len(attached) == 1
    assert attached[0].get_filename() == "SOW v4.pdf"
    assert attached[0].get_content_type() == "application/pdf"
    assert attached[0].get_payload(decode=True) == PDF_BYTES
    assert result["result"]["structured"]["attachments"] == ["SOW v4.pdf"]
    assert "Attached: SOW v4.pdf." in result["result"]["text"]


@pytest.mark.asyncio
async def test_a_tilde_path_expands_to_the_home_folder(gmail, home):
    _write_pdf(home, "report.pdf")
    result = await call({"to": ["ann@example.com"], "attachments": [{"path": "~/Documents/report.pdf"}]})
    assert result["ok"] is True, result
    assert _attachments(gmail.drafted_message())[0].get_payload(decode=True) == PDF_BYTES


@pytest.mark.asyncio
async def test_filename_and_media_type_can_be_overridden(gmail, home):
    pdf = _write_pdf(home)
    await call({"to": ["ann@example.com"], "attachments": [{"path": str(pdf), "filename": "Statement of Work.pdf", "mimeType": "application/x-custom"}]})
    attached = _attachments(gmail.drafted_message())[0]
    assert attached.get_filename() == "Statement of Work.pdf"
    assert attached.get_content_type() == "application/x-custom"


@pytest.mark.asyncio
async def test_inline_base64_content_still_works(gmail, home):
    encoded = base64.b64encode(b"hello").decode()
    result = await call({"to": ["ann@example.com"], "attachments": [{"content": encoded, "filename": "note.txt", "mimeType": "text/plain"}]})
    assert result["ok"] is True, result
    attached = _attachments(gmail.drafted_message())[0]
    assert attached.get_filename() == "note.txt"
    assert attached.get_payload(decode=True) == b"hello"


@pytest.mark.asyncio
async def test_a_path_and_content_together_or_neither_are_rejected_before_gmail(gmail, home):
    pdf = _write_pdf(home)
    both = await call({"to": ["ann@example.com"], "attachments": [{"path": str(pdf), "content": "aGk="}]})
    neither = await call({"to": ["ann@example.com"], "attachments": [{"filename": "x.pdf"}]})
    for result in (both, neither):
        assert result["ok"] is False
        assert result["error"]["kind"] == "invalid_arguments"
    assert gmail.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_path", ["Documents/report.pdf", "report.pdf", "./report.pdf"])
async def test_a_relative_path_is_refused_without_calling_gmail(gmail, home, bad_path):
    result = await call({"to": ["ann@example.com"], "attachments": [{"path": bad_path}]})
    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert "absolute" in result["error"]["message"]
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_a_missing_file_and_a_folder_are_refused_with_a_clear_reason(gmail, home):
    _write_pdf(home)
    missing = await call({"to": ["ann@example.com"], "attachments": [{"path": str(home / "Documents" / "nope.pdf")}]})
    folder = await call({"to": ["ann@example.com"], "attachments": [{"path": str(home / "Documents")}]})
    assert "There is no file at" in missing["error"]["message"]
    assert "is a folder, not a file" in folder["error"]["message"]
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_credential_folders_cannot_be_attached_even_through_a_symlink(gmail, home):
    ssh = home / ".ssh"
    ssh.mkdir()
    key = ssh / "id_ed25519"
    key.write_text("PRIVATE KEY MATERIAL")
    link = home / "Documents"
    link.mkdir()
    (link / "innocent.txt").symlink_to(key)
    direct = await call({"to": ["ann@example.com"], "attachments": [{"path": str(key)}]})
    through_link = await call({"to": ["ann@example.com"], "attachments": [{"path": str(link / "innocent.txt")}]})
    for result in (direct, through_link):
        assert result["ok"] is False
        assert "holds credentials" in result["error"]["message"]
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_a_file_over_the_size_limit_is_refused_before_it_is_read(gmail, home, monkeypatch):
    pdf = _write_pdf(home)
    monkeypatch.setattr(attachment_files, "MAX_DRAFT_ATTACHMENT_BYTES", 1000)
    result = await call({"to": ["ann@example.com"], "attachments": [{"path": str(pdf)}]})
    assert result["ok"] is False
    assert "25 MB limit" in result["error"]["message"]
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_the_combined_size_of_all_attachments_is_limited(gmail, home, monkeypatch):
    first = _write_pdf(home, "a.pdf")
    second = _write_pdf(home, "b.pdf")
    monkeypatch.setattr(mime_builder, "MAX_DRAFT_ATTACHMENT_BYTES", len(PDF_BYTES) + 10)
    result = await call({"to": ["ann@example.com"], "attachments": [{"path": str(first)}, {"path": str(second)}]})
    assert result["ok"] is False
    assert "25 MB" in result["error"]["message"]
    assert not any(request.url.path.endswith("/drafts") for request in gmail.requests)


@pytest.mark.asyncio
async def test_an_unreadable_file_reports_the_reason(gmail, home):
    pdf = _write_pdf(home)
    pdf.chmod(0)
    try:
        result = await call({"to": ["ann@example.com"], "attachments": [{"path": str(pdf)}]})
    finally:
        pdf.chmod(0o644)
    assert result["ok"] is False
    assert "Could not read" in result["error"]["message"]
    assert gmail.requests == []


def test_the_attachment_schema_lists_path_first_and_steers_agents_away_from_base64():
    properties = DraftAttachment.model_json_schema(by_alias=True)["properties"]
    assert list(properties)[0] == "path"
    assert "you never write its contents" in properties["path"]["description"]
    assert "use path instead" in properties["content"]["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"to": [], "subject": "", "body": "", "htmlBody": "", "attachments": []},
        {"subject": "   ", "body": "\n  "},
        {"summary": "A summary alone is not draft content"},
    ],
)
async def test_a_completely_empty_draft_is_refused_before_gmail(gmail, home, arguments):
    result = await call(arguments)
    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert "completely empty" in result["error"]["message"]
    assert gmail.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [{"to": ["ann@example.com"]}, {"subject": "Hello"}, {"body": "Hi"}, {"htmlBody": "<p>Hi</p>"}, {"bcc": ["ann@example.com"]}],
)
async def test_a_draft_with_any_one_field_is_still_created(gmail, home, arguments):
    result = await call(arguments)
    assert result["ok"] is True, result
