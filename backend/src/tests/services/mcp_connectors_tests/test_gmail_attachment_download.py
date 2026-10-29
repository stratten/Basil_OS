"""Tests for the ``download_attachment`` tool of the direct Gmail connector.

Gmail is faked with an ``httpx.MockTransport``; files are written under ``tmp_path`` only.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest

from api.services.agent_processing.shared.agent_runtime_context import reset_current_agent_context, set_current_agent_context
from api.services.mcp_connectors.gmail_local_server import attachment_files, gmail_api, handlers_attachments, server
from api.services.mcp_connectors.gmail_local_server.attachment_files import resolve_destination_folder, safe_file_name, write_without_overwriting
from api.services.mcp_connectors.gmail_local_server.gmail_api import ToolArgumentError

TOKEN = "ya29.test-token"
PDF_BYTES = b"%PDF-1.4 fake pdf bytes"
PNG_BYTES = b"\x89PNG fake png bytes"


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class FakeGmail:
    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self.responses: Dict[tuple, Any] = {}

    def on(self, method: str, path: str, response: Any) -> None:
        self.responses[(method, path)] = response

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        response = self.responses.get((request.method, path))
        if response is None:
            return httpx.Response(404, json={"error": {"code": 404, "message": f"unrouted {path}", "status": "NOT_FOUND"}})
        return httpx.Response(200, json=response)

    def paths(self) -> List[str]:
        return [request.url.path.removeprefix("/gmail/v1/users/me") for request in self.requests]


@pytest.fixture
def gmail(monkeypatch) -> FakeGmail:
    fake = FakeGmail()
    monkeypatch.setattr(gmail_api, "new_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


def _message(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"id": "m1", "threadId": "t1", "payload": {"mimeType": "multipart/mixed", "headers": [], "parts": [{"mimeType": "text/plain", "filename": "", "body": {"size": 3, "data": "aGk"}}, *parts]}}


def _part(filename: str, attachment_id: str, data: bytes, mime_type: str = "application/pdf") -> Dict[str, Any]:
    return {"partId": f"part-{attachment_id}", "mimeType": mime_type, "filename": filename, "body": {"attachmentId": attachment_id, "size": len(data)}}


def _route(gmail: FakeGmail, *parts: Dict[str, Any], contents: Optional[Dict[str, bytes]] = None) -> None:
    gmail.on("GET", "/messages/m1", _message(list(parts)))
    for attachment_id, data in (contents or {}).items():
        gmail.on("GET", f"/messages/m1/attachments/{attachment_id}", {"size": len(data), "data": _encode(data)})


async def call(arguments: Dict[str, Any]) -> Dict[str, Any]:
    return await server.call_tool(tool_name="download_attachment", arguments=arguments, access_token=TOKEN)


def error_message(envelope: Dict[str, Any]) -> str:
    assert envelope["ok"] is False, envelope
    return envelope["error"]["message"]


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "workspace"
    monkeypatch.setattr(handlers_attachments, "_default_folder", lambda: folder)
    return folder


@pytest.mark.asyncio
async def test_the_tool_is_registered_as_a_write_tool_so_it_asks_before_saving_files():
    catalog = await server.list_tools()
    tool = next(tool for tool in catalog["tools"] if tool["name"] == "download_attachment")

    assert tool["is_read_only_hint"] is False
    assert set(tool["input_schema"]["properties"]) >= {"messageId", "attachmentId", "partId", "filename", "destinationFolder", "saveAs", "summary"}
    assert tool["input_schema"]["required"] == ["messageId"]


@pytest.mark.asyncio
async def test_an_attachment_saves_to_the_task_workspace_by_default_and_its_contents_are_not_returned(gmail, workspace):
    _route(gmail, _part("invoice.pdf", "a1", PDF_BYTES), contents={"a1": PDF_BYTES})

    result = await call({"messageId": "m1", "attachmentId": "a1"})

    assert result["ok"] is True, result
    saved = Path(result["result"]["structured"]["path"])
    assert saved == workspace / "invoice.pdf"
    assert saved.read_bytes() == PDF_BYTES
    assert result["result"]["structured"]["sizeBytes"] == len(PDF_BYTES)
    assert result["result"]["structured"]["mimeType"] == "application/pdf"
    assert _encode(PDF_BYTES) not in str(result)


@pytest.mark.asyncio
async def test_a_requested_folder_is_used_instead_of_the_workspace_and_created_if_missing(gmail, workspace, tmp_path):
    _route(gmail, _part("invoice.pdf", "a1", PDF_BYTES), contents={"a1": PDF_BYTES})
    chosen = tmp_path / "Documents" / "Invoices"

    result = await call({"messageId": "m1", "attachmentId": "a1", "destinationFolder": str(chosen)})

    assert Path(result["result"]["structured"]["path"]) == chosen / "invoice.pdf"
    assert (chosen / "invoice.pdf").read_bytes() == PDF_BYTES
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_an_attachment_can_be_found_by_filename_and_renamed(gmail, workspace):
    _route(gmail, _part("a.pdf", "a1", PDF_BYTES), _part("Photo.PNG", "a2", PNG_BYTES, "image/png"), contents={"a2": PNG_BYTES})

    result = await call({"messageId": "m1", "filename": "photo.png", "saveAs": "receipt.png"})

    assert (workspace / "receipt.png").read_bytes() == PNG_BYTES
    assert "/messages/m1/attachments/a2" in gmail.paths()
    assert "/messages/m1/attachments/a1" not in gmail.paths()
    assert result["result"]["structured"]["fileName"] == "receipt.png"


@pytest.mark.asyncio
async def test_a_stale_attachment_id_falls_back_to_the_filename(gmail, workspace):
    _route(gmail, _part("invoice.pdf", "fresh-id", PDF_BYTES), contents={"fresh-id": PDF_BYTES})

    result = await call({"messageId": "m1", "attachmentId": "old-id", "filename": "invoice.pdf"})

    assert result["ok"] is True, result
    assert (workspace / "invoice.pdf").read_bytes() == PDF_BYTES


@pytest.mark.asyncio
async def test_the_part_id_picks_one_of_two_attachments_with_the_same_name(gmail, workspace):
    first, second = b"%PDF-1.4 first", b"%PDF-1.4 second, a different file"
    _route(gmail, _part("scan.pdf", "a1", first), _part("scan.pdf", "a2", second), contents={"a1": first, "a2": second})

    result = await call({"messageId": "m1", "partId": "part-a2"})

    assert result["ok"] is True, result
    assert (workspace / "scan.pdf").read_bytes() == second


def test_get_message_lists_the_stable_part_id_and_size_for_each_attachment():
    from api.services.mcp_connectors.gmail_local_server.message_shaping import collect_bodies

    payload = _message([_part("invoice.pdf", "a1", PDF_BYTES)])["payload"]

    _plain, _html, attachments = collect_bodies(payload)

    assert attachments == [{"id": "a1", "partId": "part-a1", "mimeType": "application/pdf", "filename": "invoice.pdf", "size": len(PDF_BYTES)}]


@pytest.mark.asyncio
async def test_an_existing_file_is_never_overwritten(gmail, workspace):
    _route(gmail, _part("invoice.pdf", "a1", PDF_BYTES), contents={"a1": PDF_BYTES})
    workspace.mkdir(parents=True)
    (workspace / "invoice.pdf").write_bytes(b"the user's own file")

    first = await call({"messageId": "m1", "attachmentId": "a1"})
    second = await call({"messageId": "m1", "attachmentId": "a1"})

    assert (workspace / "invoice.pdf").read_bytes() == b"the user's own file"
    assert Path(first["result"]["structured"]["path"]) == workspace / "invoice (1).pdf"
    assert Path(second["result"]["structured"]["path"]) == workspace / "invoice (2).pdf"


@pytest.mark.asyncio
async def test_an_unknown_attachment_lists_what_the_message_has(gmail, workspace):
    _route(gmail, _part("invoice.pdf", "a1", PDF_BYTES))

    message = error_message(await call({"messageId": "m1", "filename": "missing.pdf"}))

    assert "invoice.pdf" in message and "application/pdf" in message
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_two_attachments_with_one_name_ask_for_the_part_id(gmail, workspace):
    _route(gmail, _part("scan.pdf", "a1", PDF_BYTES), _part("scan.pdf", "a2", PDF_BYTES))

    message = error_message(await call({"messageId": "m1", "filename": "scan.pdf"}))

    assert "2 attachments are named" in message and "partId part-a1" in message and "partId part-a2" in message
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_neither_an_id_nor_a_filename_is_refused_before_contacting_gmail(gmail, workspace):
    message = error_message(await call({"messageId": "m1"}))

    assert "filename or partId" in message
    assert gmail.requests == []


@pytest.mark.asyncio
async def test_a_message_with_no_attachments_says_so(gmail, workspace):
    _route(gmail)

    assert "no attachments" in error_message(await call({"messageId": "m1", "filename": "x.pdf"}))


@pytest.mark.asyncio
async def test_an_oversized_attachment_is_refused_without_downloading_it(gmail, workspace):
    huge = {"mimeType": "application/zip", "filename": "big.zip", "body": {"attachmentId": "a1", "size": attachment_files.MAX_ATTACHMENT_BYTES + 1}}
    _route(gmail, huge)

    message = error_message(await call({"messageId": "m1", "attachmentId": "a1"}))

    assert "over the 50 MB limit" in message
    assert "/messages/m1/attachments/a1" not in gmail.paths()


@pytest.mark.asyncio
async def test_a_truncated_download_saves_nothing(gmail, workspace):
    _route(gmail, _part("invoice.pdf", "a1", PDF_BYTES))
    gmail.on("GET", "/messages/m1/attachments/a1", {"size": 5, "data": _encode(PDF_BYTES[:5])})

    message = error_message(await call({"messageId": "m1", "attachmentId": "a1"}))

    assert "so nothing was saved" in message
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_a_relative_or_protected_destination_is_refused_and_nothing_is_saved(gmail, workspace):
    _route(gmail, _part("invoice.pdf", "a1", PDF_BYTES), contents={"a1": PDF_BYTES})

    relative = error_message(await call({"messageId": "m1", "attachmentId": "a1", "destinationFolder": "Documents"}))
    protected = error_message(await call({"messageId": "m1", "attachmentId": "a1", "destinationFolder": "~/.ssh"}))
    system = error_message(await call({"messageId": "m1", "attachmentId": "a1", "destinationFolder": "/etc"}))

    assert "absolute path" in relative
    assert "credentials or startup items" in protected
    assert "system folder" in system
    assert not workspace.exists()


def test_file_names_cannot_escape_the_folder_or_hide():
    assert safe_file_name("../../etc/passwd") == "passwd"
    assert safe_file_name("..\\..\\win.ini") == "win.ini"
    assert safe_file_name(".hidden.pdf") == "hidden.pdf"
    assert safe_file_name("a/b:c\x00d.pdf") == "b_c_d.pdf"
    assert safe_file_name("   ") == "attachment"
    assert safe_file_name("", "application/pdf") == "attachment.pdf"
    long_name = safe_file_name("x" * 400 + ".pdf")
    assert len(long_name) <= 180 and long_name.endswith(".pdf")


def test_a_write_failure_removes_the_partial_file_and_reports_it(tmp_path, monkeypatch):
    real_open = open

    class FailingHandle:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._handle.close()

        def write(self, data):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr("builtins.open", lambda path, mode="r", *a, **k: FailingHandle(real_open(path, mode, *a, **k)) if str(path).startswith(str(tmp_path)) else real_open(path, mode, *a, **k))

    with pytest.raises(ToolArgumentError, match="No space left"):
        write_without_overwriting(tmp_path, "file.pdf", b"data")

    monkeypatch.undo()
    assert not (tmp_path / "file.pdf").exists()


def test_a_folder_that_is_really_a_file_is_refused(tmp_path):
    blocker = tmp_path / "taken"
    blocker.write_text("x")

    with pytest.raises(ToolArgumentError, match="is a file, not a folder"):
        resolve_destination_folder(str(blocker), tmp_path)


def test_the_default_folder_is_the_root_task_workspace(monkeypatch, tmp_path):
    from api.core.config import api_settings

    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)
    token = set_current_agent_context({"root_task_id": "root-1", "agent_task_id": "child-2"})
    try:
        folder = handlers_attachments._default_folder()
    finally:
        reset_current_agent_context(token)

    assert folder == tmp_path / "agent_task_workspaces" / "root-1"


def test_without_a_task_the_default_folder_is_a_fixed_basil_folder(monkeypatch, tmp_path):
    from api.core.config import api_settings

    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)

    assert handlers_attachments._default_folder() == tmp_path / "mail_attachments"
