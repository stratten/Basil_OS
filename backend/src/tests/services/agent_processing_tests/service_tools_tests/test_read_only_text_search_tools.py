"""The read-only file tools let an agent search and read local text without a shell command that may need approval."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from api.core.security import protected_runtime_paths
from api.services.agent_processing.lifecycle.execution_graph.service_tools import create_service_tools
from api.services.agent_processing.service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from api.services.agent_processing.service_capabilities.service_execution_engine import ServiceExecutionEngine
from api.services.agent_processing.tools.direct_application_interactions.file_system import text_search
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import (
    FileSystemService,
)
from api.services.agent_processing.tools.direct_application_interactions.file_system.text_search_capabilities import (
    READ_ONLY_TEXT_METHOD_CAPABILITIES,
)


def _tree(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\nHow Apex handling works\nnothing here\n", encoding="utf-8")
    (root / "docs" / "notes.txt").write_text("apex is mentioned in lowercase\n", encoding="utf-8")
    (root / "docs" / "other.md").write_text("no match in this one\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.tsx").write_text("const x = 'APEX';\n", encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "readme.md").write_text("apex inside a dependency\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("apex inside git\n", encoding="utf-8")


def _paths(result: dict, key: str = "matches") -> set[str]:
    return {item["path"] for item in result[key]}


def test_a_search_finds_matching_lines_with_numbers_and_ignores_case_by_default(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = text_search.search_text_in_files(str(tmp_path), ["apex"])

    assert result["success"] is True
    assert _paths(result) == {
        str(tmp_path / "docs" / "guide.md"),
        str(tmp_path / "docs" / "notes.txt"),
        str(tmp_path / "src" / "app.tsx"),
    }
    guide = next(item for item in result["matches"] if item["path"].endswith("guide.md"))
    assert guide["line_number"] == 2
    assert guide["line"] == "How Apex handling works"
    assert result["truncated"] is False
    assert result["truncation_reason"] is None
    assert {item["path"] for item in result["files_with_matches"]} == _paths(result)


def test_a_case_sensitive_search_matches_capitalization_exactly(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = text_search.search_text_in_files(str(tmp_path), ["Apex"], case_sensitive=True)

    assert _paths(result) == {str(tmp_path / "docs" / "guide.md")}


def test_any_of_several_terms_matches(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = text_search.search_text_in_files(str(tmp_path), ["guide", "lowercase"])

    assert _paths(result) == {str(tmp_path / "docs" / "guide.md"), str(tmp_path / "docs" / "notes.txt")}


def test_file_globs_limit_the_files_that_are_searched(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = text_search.search_text_in_files(str(tmp_path), ["apex"], file_globs=["*.MD", "*.tsx"])

    assert _paths(result) == {str(tmp_path / "docs" / "guide.md"), str(tmp_path / "src" / "app.tsx")}


def test_generated_folders_are_skipped_and_named_unless_requested(tmp_path: Path) -> None:
    _tree(tmp_path)

    default = text_search.search_text_in_files(str(tmp_path), ["apex"])
    included = text_search.search_text_in_files(str(tmp_path), ["apex"], include_generated_directories=True)

    assert default["skipped"]["generated_directories_skipped"] == [".git", "node_modules"]
    assert str(tmp_path / "node_modules" / "pkg" / "readme.md") not in _paths(default)
    assert str(tmp_path / "node_modules" / "pkg" / "readme.md") in _paths(included)
    assert str(tmp_path / ".git" / "config") in _paths(included)
    assert included["skipped"]["generated_directories_skipped"] == []


def test_a_term_with_regular_expression_characters_is_matched_literally(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("call f(x) now\nabc\n", encoding="utf-8")

    assert text_search.search_text_in_files(str(tmp_path), ["f(x)"])["total_matches"] == 1
    assert text_search.search_text_in_files(str(tmp_path), [".*"])["total_matches"] == 0
    assert text_search.search_text_in_files(str(tmp_path), ["a.c"])["total_matches"] == 0


def test_binary_oversized_and_symlinked_files_are_skipped_and_counted(tmp_path: Path) -> None:
    (tmp_path / "text.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\0\1needle\2")
    (tmp_path / "huge.txt").write_bytes(b"needle\n" + b"x" * text_search.MAX_FILE_BYTES)
    (tmp_path / "linked.txt").symlink_to(tmp_path / "text.txt")

    result = text_search.search_text_in_files(str(tmp_path), ["needle"])

    assert _paths(result) == {str(tmp_path / "text.txt")}
    assert result["skipped"]["binary_files_skipped"] == 1
    assert result["skipped"]["files_over_2_mib_skipped"] == 1
    assert result["skipped"]["symlinks_skipped"] == 1


def test_the_match_limit_cuts_the_answer_short_and_says_so(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_text("hit\n" * 50, encoding="utf-8")

    result = text_search.search_text_in_files(str(tmp_path), ["hit"], max_matches=5)

    assert result["total_matches"] == 5
    assert result["truncated"] is True
    assert result["truncation_reason"] == "match_limit"


def test_a_limit_outside_the_allowed_range_is_clamped_or_replaced_by_the_default(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_text("hit\n" * 700, encoding="utf-8")

    assert text_search.search_text_in_files(str(tmp_path), ["hit"], max_matches=100000)["total_matches"] == 500
    assert text_search.search_text_in_files(str(tmp_path), ["hit"], max_matches=0)["total_matches"] == 1
    assert text_search.search_text_in_files(str(tmp_path), ["hit"], max_matches="many")["total_matches"] == 100
    assert text_search.search_text_in_files(str(tmp_path), ["hit"], max_matches=True)["total_matches"] == 100


def test_a_very_long_matching_line_is_cut_to_a_readable_length(tmp_path: Path) -> None:
    (tmp_path / "long.txt").write_text("needle " + "x" * 5000 + "\n", encoding="utf-8")

    result = text_search.search_text_in_files(str(tmp_path), ["needle"])

    assert len(result["matches"][0]["line"]) == text_search.MAX_LINE_CHARS


def test_a_file_that_is_not_valid_utf8_is_still_searched_and_does_not_fail(tmp_path: Path) -> None:
    (tmp_path / "latin.txt").write_bytes(b"caf\xe9 needle\n")

    result = text_search.search_text_in_files(str(tmp_path), ["needle"])

    assert result["total_matches"] == 1


@pytest.mark.parametrize(
    ("directory", "terms", "file_globs", "error_type"),
    [
        ("relative/path", ["x"], None, "invalid_path"),
        ("", ["x"], None, "invalid_path"),
        (None, ["x"], None, "invalid_path"),
        ("/definitely/not/a/folder/anywhere", ["x"], None, "not_found"),
        ("TMP/file.txt", ["x"], None, "not_a_directory"),
        ("TMP", [], None, "invalid_terms"),
        ("TMP", ["   "], None, "invalid_terms"),
        ("TMP", [3], None, "invalid_terms"),
        ("TMP", None, None, "invalid_terms"),
        ("TMP", ["x"] * 21, None, "invalid_terms"),
        ("TMP", ["x" * 201], None, "invalid_terms"),
        ("TMP", ["x"], [4], "invalid_file_globs"),
    ],
)
def test_a_search_with_unusable_input_fails_with_a_reason(tmp_path: Path, directory, terms, file_globs, error_type) -> None:
    (tmp_path / "file.txt").write_text("x\n", encoding="utf-8")
    if isinstance(directory, str) and directory.startswith("TMP"):
        directory = directory.replace("TMP", str(tmp_path), 1)

    result = text_search.search_text_in_files(directory, terms, file_globs)

    assert result["success"] is False
    assert result["error_type"] == error_type
    assert result["error"]


def test_a_single_string_is_accepted_where_a_list_of_terms_is_expected(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle\n", encoding="utf-8")

    assert text_search.search_text_in_files(str(tmp_path), "needle")["total_matches"] == 1


@pytest.fixture
def protected_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runtime = tmp_path / "home" / ".basil" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "backend_credentials.json").write_text('{"token": "needle"}\n', encoding="utf-8")
    (tmp_path / "home" / "open.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(protected_runtime_paths, "protected_runtime_directory", lambda: runtime)
    return runtime


def test_the_protected_runtime_folder_is_refused_and_never_searched_through_a_parent(protected_runtime: Path) -> None:
    home = protected_runtime.parent.parent

    refused = text_search.search_text_in_files(str(protected_runtime), ["needle"])
    through_parent = text_search.search_text_in_files(str(home), ["needle"])
    listed = text_search.list_files_in_folder(str(home))
    read = text_search.read_text_file(str(protected_runtime / "backend_credentials.json"))

    assert refused["success"] is False and refused["error_type"] == "policy_blocked"
    assert read["success"] is False and read["error_type"] == "policy_blocked"
    assert _paths(through_parent) == {str(home / "open.txt")}
    assert all(".basil/runtime" not in item["path"] for item in listed["files"])
    assert [item["path"] for item in listed["files"]] == [str(home / "open.txt")]


def test_a_listing_filters_by_name_case_insensitively_and_reports_size(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = text_search.list_files_in_folder(str(tmp_path), ["*.MD"])

    assert {item["path"] for item in result["files"]} == {str(tmp_path / "docs" / "guide.md"), str(tmp_path / "docs" / "other.md")}
    guide = next(item for item in result["files"] if item["path"].endswith("guide.md"))
    assert guide["size_bytes"] == (tmp_path / "docs" / "guide.md").stat().st_size
    assert guide["modified"].endswith("+00:00")
    assert result["skipped"]["generated_directories_skipped"] == [".git", "node_modules"]


def test_a_listing_stops_at_the_result_limit_and_says_so(tmp_path: Path) -> None:
    for index in range(10):
        (tmp_path / f"f{index}.txt").write_text("x", encoding="utf-8")

    result = text_search.list_files_in_folder(str(tmp_path), max_results=3)

    assert result["total_listed"] == 3
    assert result["truncated"] is True
    assert result["truncation_reason"] == "result_limit"


def test_a_listing_of_an_empty_or_missing_folder(tmp_path: Path) -> None:
    empty = text_search.list_files_in_folder(str(tmp_path))
    missing = text_search.list_files_in_folder(str(tmp_path / "gone"))

    assert empty["success"] is True and empty["files"] == [] and empty["truncated"] is False
    assert missing["success"] is False and missing["error_type"] == "not_found"


def test_reading_returns_a_range_with_the_digest_a_later_edit_needs(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")

    result = text_search.read_text_file(str(target), start_line=2, max_lines=2)

    assert result["success"] is True
    assert result["text"] == "two\nthree"
    assert (result["start_line"], result["end_line"], result["total_lines"]) == (2, 3, 5)
    assert result["truncated"] is True
    assert result["next_start_line"] == 4
    assert result["sha256"] == sha256(target.read_bytes()).hexdigest()


def test_reading_the_whole_of_a_short_file_is_not_truncated(tmp_path: Path) -> None:
    target = tmp_path / "short.txt"
    target.write_text("a\r\nb\r\n", encoding="utf-8")

    result = text_search.read_text_file(str(target))

    assert result["text"] == "a\nb"
    assert result["truncated"] is False
    assert result["next_start_line"] is None


def test_a_start_line_past_the_end_returns_an_empty_range_rather_than_the_last_line(tmp_path: Path) -> None:
    target = tmp_path / "short.txt"
    target.write_text("a\nb\n", encoding="utf-8")

    result = text_search.read_text_file(str(target), start_line=50)

    assert result["success"] is True
    assert result["text"] == ""
    assert result["total_lines"] == 2
    assert result["truncated"] is False


@pytest.mark.parametrize("start_line", [0, -3, True, "2", 1.5, None])
def test_an_unusable_start_line_reads_from_the_top(tmp_path: Path, start_line) -> None:
    target = tmp_path / "short.txt"
    target.write_text("a\nb\n", encoding="utf-8")

    assert text_search.read_text_file(str(target), start_line=start_line)["start_line"] == 1


def test_reading_an_empty_file_succeeds_with_no_text(tmp_path: Path) -> None:
    target = tmp_path / "empty.txt"
    target.write_text("", encoding="utf-8")

    result = text_search.read_text_file(str(target))

    assert result["success"] is True
    assert result["text"] == ""
    assert result["total_lines"] == 0


def test_a_huge_single_line_is_cut_to_the_output_budget(tmp_path: Path) -> None:
    target = tmp_path / "minified.js"
    target.write_text("x" * 200_000 + "\nsecond\n", encoding="utf-8")

    result = text_search.read_text_file(str(target), max_lines=1000)

    assert len(result["text"]) <= text_search.MAX_READ_CHARS
    assert result["truncated"] is True


def _binary_file(root: Path) -> Path:
    (root / "b.bin").write_bytes(b"\0\1")
    return root / "b.bin"


def _oversized_file(root: Path) -> Path:
    (root / "big.txt").write_bytes(b"x" * (text_search.MAX_FILE_BYTES + 1))
    return root / "big.txt"


@pytest.mark.parametrize(
    ("make", "error_type"),
    [
        (lambda root: root / "missing.txt", "not_found"),
        (lambda root: root, "not_a_file"),
        (_binary_file, "binary_file"),
        (_oversized_file, "too_large"),
        (lambda root: Path("relative.txt"), "invalid_path"),
    ],
)
def test_reading_something_that_cannot_be_read_fails_with_a_reason(tmp_path: Path, make, error_type) -> None:
    result = text_search.read_text_file(str(make(tmp_path)))

    assert result["success"] is False
    assert result["error_type"] == error_type


def test_a_tilde_path_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")

    assert text_search.read_text_file("~/note.txt")["text"] == "hello"


def test_every_capability_parameter_is_a_real_argument_of_its_method() -> None:
    service = FileSystemService(write_roots=[])

    for entry in READ_ONLY_TEXT_METHOD_CAPABILITIES:
        signature = inspect.signature(getattr(service, entry["name"]))
        declared = {parameter["name"] for parameter in entry["parameters"]}
        required = {parameter["name"] for parameter in entry["parameters"] if parameter["required"]}
        assert declared == set(signature.parameters), entry["name"]
        assert required == {
            name for name, parameter in signature.parameters.items() if parameter.default is inspect.Parameter.empty
        }, entry["name"]


def test_the_file_service_publishes_the_read_only_tools_and_keeps_its_existing_ones() -> None:
    names = [method["name"] for method in FileSystemService(write_roots=[]).get_service_capabilities()["methods"]]

    for expected in ("search_text_in_files", "list_files_in_folder", "read_text_file", "write_text_file", "edit_text_file", "find_file_for_llm", "prepare_file_by_path"):
        assert names.count(expected) == 1, expected


def test_the_agent_prompt_names_every_read_only_tool_and_no_longer_sends_grep_to_the_shell() -> None:
    from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE

    for entry in READ_ONLY_TEXT_METHOD_CAPABILITIES:
        assert f"file_service_{entry['name']}" in AGENT_SYSTEM_PROMPT_TEMPLATE, entry["name"]
    assert "(e.g., grep, tar, ffmpeg, git)" not in AGENT_SYSTEM_PROMPT_TEMPLATE


async def _tools(tmp_path: Path) -> dict:
    service = FileSystemService(write_roots=[tmp_path])
    analyzer = ServiceCapabilityAnalyzer(file_service=service)
    services = analyzer.discover_available_services()
    engine = ServiceExecutionEngine(analyzer)
    engine.register_service("file_service", service)
    result = await create_service_tools(service_execution_engine=engine, capability_analyzer=analyzer, services=services)
    return {tool.name: tool for tool in result.tools}


def test_an_agent_can_search_list_and_read_through_the_real_tool_path(tmp_path: Path) -> None:
    _tree(tmp_path)
    tools = asyncio.run(_tools(tmp_path))

    search = json.loads(asyncio.run(tools["file_service_search_text_in_files"].ainvoke({"directory": str(tmp_path), "terms": ["apex"], "file_globs": ["*.md"]})))
    listing = json.loads(asyncio.run(tools["file_service_list_files_in_folder"].ainvoke({"directory": str(tmp_path), "name_globs": ["*.md"]})))
    read = json.loads(asyncio.run(tools["file_service_read_text_file"].ainvoke({"path": str(tmp_path / "docs" / "guide.md"), "max_lines": 2})))

    assert search["success"] is True
    assert _paths(search["result"]) == {str(tmp_path / "docs" / "guide.md")}
    assert {item["path"] for item in listing["result"]["files"]} == {str(tmp_path / "docs" / "guide.md"), str(tmp_path / "docs" / "other.md")}
    assert read["result"]["text"] == "# Guide\nHow Apex handling works"
    assert read["result"]["truncated"] is True


def test_the_read_tools_change_nothing_on_disk(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    before_times = {path: os.stat(path).st_mtime_ns for path in before}

    text_search.search_text_in_files(str(tmp_path), ["apex"], include_generated_directories=True)
    text_search.list_files_in_folder(str(tmp_path))
    text_search.read_text_file(str(tmp_path / "docs" / "guide.md"))

    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    assert {path: os.stat(path).st_mtime_ns for path in before} == before_times
    assert not any(tmp_path.rglob("*.tmp"))
