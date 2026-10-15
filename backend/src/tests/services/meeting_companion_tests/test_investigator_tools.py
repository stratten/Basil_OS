import zipfile

import pytest

from api.services.meeting_companion.context_search import ContextSearchService, validate_root
from api.services.meeting_companion.context_service import ContextService
from api.services.meeting_companion.investigator.evidence import EvidenceLedger
from api.services.meeting_companion.investigator.models import RECORD_SOURCE_KINDS
from api.services.meeting_companion.investigator.tools import (
    BUDGET_MESSAGE,
    CANCELED_MESSAGE,
    LEDGER_FULL_MESSAGE,
    UNTRUSTED_NOTE,
    InvestigatorToolEnvironment,
    ToolBudget,
    build_investigator_tools,
    read_attached_file,
    search_attached_files,
    search_basil_records,
)

from .investigator_fakes import FakeRecords

MEETING_HIT = {"source_kind": "meeting", "source_id": "m1", "title": "Vendor sync", "occurred_at": "2026-01-01", "excerpt": "Renewal is net sixty days."}


def environment(service, records=None, *, max_calls=8, ledger=None, cancel_event=None):
    return InvestigatorToolEnvironment(
        context=service,
        ledger=ledger or EvidenceLedger(),
        budget=ToolBudget(max_calls),
        records_search=records or FakeRecords(),
        cancel_event=cancel_event,
    )


@pytest.fixture
def service(project, attach_project):
    context = ContextService()
    attach_project(context, project)
    return context


@pytest.mark.asyncio
async def test_file_search_records_evidence_and_marks_the_output_untrusted(service):
    env = environment(service)
    output = await search_attached_files(env, "retry policy")
    assert output.startswith(UNTRUSTED_NOTE)
    assert "[e1] proj/src/retry_policy.py lines" in output and "max_attempts" in output
    entry = env.ledger.get("e1")
    assert entry.kind == "file" and entry.path == "proj/src/retry_policy.py"
    assert env.budget.calls == 1


@pytest.mark.asyncio
async def test_file_search_handles_blank_unmatched_and_unattached_cases(service):
    env = environment(service)
    assert await search_attached_files(env, "   ") == "Give some words to search for."
    assert await search_attached_files(env, "zebra crossing") == "No matching text was found in the attached files."
    assert len(env.ledger) == 0
    empty = environment(ContextService())
    assert await search_attached_files(empty, "retry policy") == "No files are attached to this meeting."


@pytest.mark.asyncio
async def test_file_search_reports_a_full_ledger(service):
    ledger = EvidenceLedger(max_entries=1)
    ledger.add("file", "elsewhere.txt", 1, 1, "already here")
    assert await search_attached_files(environment(service, ledger=ledger), "retry policy") == LEDGER_FULL_MESSAGE


@pytest.mark.asyncio
async def test_reading_a_long_file_windows_it_and_continues_from_the_hint(project, service):
    (project / "long.txt").write_text("\n".join(f"line {number:03d} alpha" for number in range(1, 301)), encoding="utf-8")
    env = environment(service)
    first = await read_attached_file(env, "proj/long.txt")
    assert "Showing lines 1-120 of 300." in first and "start_line=121" in first and "line 120 alpha" in first
    assert "line 121 alpha" not in first
    second = await read_attached_file(env, "proj/long.txt", 121)
    assert "Showing lines 121-240 of 300." in second and "line 121 alpha" in second
    assert [entry.id for entry in env.ledger.entries()] == ["e1", "e2", "e3", "e4"]
    tail = await read_attached_file(env, "proj/long.txt", 241)
    assert "Showing lines 241-300 of 300." in tail and "start_line=" not in tail
    assert "has only 300 lines" in await read_attached_file(env, "proj/long.txt", 999)


@pytest.mark.asyncio
async def test_reading_a_word_document_returns_its_text_with_a_citable_id(project, service):
    body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Renewal term is twelve months.</w:t></w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(project / "contract.docx", "w") as archive:
        archive.writestr("word/document.xml", body)
    env = environment(service)
    output = await read_attached_file(env, "proj/contract.docx")
    assert "Renewal term is twelve months." in output and "[e1] proj/contract.docx" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["proj/../secret.txt", "../secret.txt", "/etc/hosts", "SECRET_ABSOLUTE", "proj/.env", "proj/link.txt", "proj/missing.py", "other/src/retry_policy.py", "proj/src", "", "   "])
async def test_reading_outside_the_attached_roots_is_not_found(tmp_path, project, service, path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    (project / ".env").write_text("TOKEN=abc123", encoding="utf-8")
    (project / "link.txt").symlink_to(secret)
    wanted = str(secret) if path == "SECRET_ABSOLUTE" else path
    env = environment(service)
    output = await read_attached_file(env, wanted)
    assert output.startswith("No attached file is named")
    assert "top secret" not in output and "abc123" not in output and len(env.ledger) == 0


def test_a_single_file_root_reads_by_its_display_name(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("alpha\nbeta\n", encoding="utf-8")
    search = ContextSearchService()
    resolved, kind = validate_root(str(notes), home=tmp_path.parent)
    search.add_root("r1", resolved, kind, "notes.md")
    result = search.read_attached_file("notes.md")
    assert result.status == "ok" and result.text == "alpha\nbeta\n" and result.display_path == "notes.md"
    assert search.read_attached_file("notes.md/other").status == "not_found"
    assert search.read_attached_file("other.md").status == "not_found"


def test_binary_and_oversized_files_are_unreadable_while_not_found_is_reserved_for_unknown_paths(project):
    (project / "huge.txt").write_text("a" * 1_100_000, encoding="utf-8")
    (project / "image.txt").write_bytes(b"\x00\x01\x02" * 100)
    search = ContextSearchService()
    resolved, kind = validate_root(str(project), home=project.parent.parent)
    search.add_root("r1", resolved, kind, project.name)
    result = search.read_attached_file("proj/image.txt")
    assert result.status == "unreadable" and result.detail
    assert search.read_attached_file("proj/huge.txt").status == "unreadable"


@pytest.mark.asyncio
async def test_the_call_budget_refuses_without_running_the_tool(service):
    records = FakeRecords([MEETING_HIT])
    env = environment(service, records, max_calls=2)
    await search_basil_records(env, "renewal")
    await search_basil_records(env, "renewal")
    assert await search_basil_records(env, "renewal") == BUDGET_MESSAGE
    assert await search_attached_files(env, "retry policy") == BUDGET_MESSAGE
    assert await read_attached_file(env, "proj/src/retry_policy.py") == BUDGET_MESSAGE
    assert len(records.calls) == 2 and env.budget.calls == 2


@pytest.mark.asyncio
async def test_a_canceled_run_refuses_without_spending_budget(service):
    import asyncio

    event = asyncio.Event()
    event.set()
    records = FakeRecords([MEETING_HIT])
    env = environment(service, records, cancel_event=event)
    assert await search_basil_records(env, "renewal") == CANCELED_MESSAGE
    assert env.budget.calls == 0 and records.calls == []


@pytest.mark.asyncio
async def test_record_search_keeps_only_allowed_sources_and_cites_a_basil_path():
    hits = [
        {"source_kind": "screen_block", "source_id": "s1", "title": "Screen", "excerpt": "password hunter2"},
        {"source_kind": "meeting", "source_id": "", "title": "No id", "excerpt": "ignored"},
        {"source_kind": "conversation", "source_id": "c1", "title": "Chat", "excerpt": "   "},
        MEETING_HIT,
    ]
    records = FakeRecords(hits)
    env = environment(ContextService(), records)
    output = await search_basil_records(env, "renewal", ["screen_block", "meeting"])
    assert records.calls == [("renewal", ["meeting"])]
    assert output.startswith(UNTRUSTED_NOTE) and "hunter2" not in output and "ignored" not in output
    entry = env.ledger.get("e1")
    assert entry.kind == "record" and entry.path == "basil:meeting:m1" and len(env.ledger) == 1
    await search_basil_records(env, "renewal", ["screen_block"])
    assert records.calls[1] == ("renewal", list(RECORD_SOURCE_KINDS))


@pytest.mark.asyncio
async def test_record_search_failure_and_empty_results_return_plain_messages():
    failing = environment(ContextService(), FakeRecords(error=RuntimeError("database locked")))
    assert await search_basil_records(failing, "renewal") == "Basil records could not be searched right now."
    empty = environment(ContextService(), FakeRecords([]))
    assert await search_basil_records(empty, "renewal") == "No matching Basil records were found."
    assert await search_basil_records(empty, "  ") == "Give some words to search for."


def test_the_tool_allow_list_depends_on_attached_files(service):
    names = [tool.name for tool in build_investigator_tools(environment(service))]
    assert names == ["search_attached_files", "read_attached_file", "search_basil_records"]
    assert [tool.name for tool in build_investigator_tools(environment(ContextService()))] == ["search_basil_records"]
