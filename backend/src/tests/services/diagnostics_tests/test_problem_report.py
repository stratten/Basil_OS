"""The Report a problem bundle must carry facts and model-runtime log lines, and never conversation, activity or secret content."""

import json
import zipfile
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from api.routes import diagnostics_routes
from api.services.diagnostics.log_redaction import (
    MAX_EXCERPT_LINES,
    MAX_LINE_CHARS,
    read_log_tail_lines,
    redact_log_lines,
    redacted_log_excerpt,
    scrub_line,
)
from api.services.diagnostics.problem_report import (
    REPORTS_TO_KEEP,
    ProblemReportFacts,
    issue_url,
    sanitize_detail,
    sanitize_source,
    write_report_bundle,
)

HOME = "/Users/someone"
NOW = datetime(2026, 11, 7, 12, 30, 45)


def _facts(**overrides) -> ProblemReportFacts:
    values = dict(
        source="setup_assistant",
        detail="llama_decode returned -3",
        app_version="1.0.2",
        macos_version="macOS 26.1",
        hardware={"total_ram_gb": 8, "chip_label": "Apple M2", "machine": "arm64"},
        selected_models={"reasoning_model": "Qwen-qwen35-4b-mlx-4bit", "transcription_model": "Whisper Tiny (English)"},
        installed_model_ids=["OpenAI-whisper-tiny.en", "Qwen-qwen35-4b-mlx-4bit"],
    )
    values.update(overrides)
    return ProblemReportFacts(**values)


class TestLogRedaction:
    def test_keeps_model_runtime_lines_and_native_faults(self) -> None:
        lines = [
            "INFO:api.core.models.reasoning.llama_cpp_model:[LlamaCpp] Using registry context window: 262144 tokens",
            "2026-11-01 11:30:22,290 - api.core.runtime.llama_cpp_load_plan - INFO - planned n_ctx=16384",
            "ERROR:uvicorn.error:llama_decode returned -3 with a context of 32768 tokens",
            "INFO:api.services.transcription.local_model.model_lifecycle:Loading HF Whisper 'Whisper Tiny (English)'",
        ]

        kept = redact_log_lines(lines, HOME)

        assert len(kept) == 4

    def test_drops_lines_from_other_modules(self) -> None:
        lines = [
            "INFO:api.routes.websocket:Message type: websocket.receive",
            "INFO:     127.0.0.1:51617 - \"POST /api/v1/voice-listener/wake-word-callback HTTP/1.1\" 200 OK",
            ">>> SQLITE SERVICE: Inserting activity 3ea3c25f into database",
            "INFO:api.services.capture.shared.window_capture_bridge:Capture response delivered for request 5473fb0e",
            "INFO:api.core.models.preferences:🔑 HOTKEY LOAD: Found hotkeys section with 12 entries",
        ]

        assert redact_log_lines(lines, HOME) == []

    @pytest.mark.parametrize(
        "line",
        [
            "INFO:api.core.models.reasoning.llama_cpp_model:request_dump messages=[{'role': 'user', 'content': 'secret plan'}] tools=[]",
            "ERROR:api.core.models.reasoning.llama_cpp_model:failed for prompt: my private question",
            "INFO:api.services.setup_assistant.agent_service:content: the user said hello",
            "ERROR:uvicorn.error:llama_decode failed; window title was 'Q3 acquisition - Mail'",
            "INFO:api.services.transcription.processing.transcription_processor:transcript ready: hello world",
        ],
    )
    def test_content_lines_are_dropped_even_from_allowed_modules(self, line) -> None:
        assert redact_log_lines([line], HOME) == []

    def test_a_traceback_is_kept_with_its_allowed_line_and_not_attached_to_a_dropped_one(self) -> None:
        lines = [
            "ERROR:api.core.models.reasoning.llama_cpp_model:Decode failed",
            "Traceback (most recent call last):",
            "  File \"/app/llama_cpp_model.py\", line 10, in decode",
            "RuntimeError: llama_decode returned -3",
            "INFO:api.routes.websocket:unrelated line",
            "  File \"/app/websocket.py\", line 5, in handler",
        ]

        kept = redact_log_lines(lines, HOME)

        assert len(kept) == 4
        assert all("websocket" not in line for line in kept)

    def test_scrub_removes_home_emails_and_secrets(self) -> None:
        line = (
            f"loaded {HOME}/.basil/models/qwen.gguf for jane.doe@example.com "
            "Authorization: Bearer abc123SECRET token=xyz789 key sk-abcdefghijklmnopqrstuvwxyz"
        )

        scrubbed = scrub_line(line, HOME)

        assert HOME not in scrubbed
        assert "~/.basil/models/qwen.gguf" in scrubbed
        assert "jane.doe@example.com" not in scrubbed
        assert "abc123SECRET" not in scrubbed
        assert "xyz789" not in scrubbed
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in scrubbed

    def test_a_long_mixed_token_is_redacted_but_a_long_model_path_is_not(self) -> None:
        token = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2"
        path = "~/.basil/models/qwen3-30b-a3b-instruct-2507-mlx-4bit/model.safetensors"

        assert token not in scrub_line(f"token blob {token}", HOME)
        assert path in scrub_line(f"opened {path}", HOME)

    def test_long_lines_are_cut(self) -> None:
        scrubbed = scrub_line("x" * 5000, HOME)

        assert len(scrubbed) <= MAX_LINE_CHARS + len(" [cut]")

    def test_only_the_latest_lines_are_returned(self) -> None:
        lines = [f"ERROR:uvicorn.error:llama_decode returned -3 attempt {index}" for index in range(MAX_EXCERPT_LINES + 50)]

        kept = redact_log_lines(lines, HOME)

        assert len(kept) == MAX_EXCERPT_LINES
        assert kept[-1].endswith(f"attempt {MAX_EXCERPT_LINES + 49}")

    def test_the_tail_reader_drops_a_cut_first_line_and_handles_a_missing_file(self, tmp_path) -> None:
        log = tmp_path / "backend.log"
        log.write_text("first partial line\nsecond line\nthird line\n")

        assert read_log_tail_lines(log, max_bytes=25) == ["second line", "third line"]
        assert read_log_tail_lines(tmp_path / "absent.log") == []

    def test_an_excerpt_says_so_when_nothing_relevant_is_found(self, tmp_path) -> None:
        log = tmp_path / "backend.log"
        log.write_text("INFO:api.routes.websocket:hello\n")

        assert "No model, runtime or download lines" in redacted_log_excerpt(log, HOME)


class TestBundle:
    def test_the_zip_holds_exactly_the_report_the_excerpt_and_the_readme(self, tmp_path) -> None:
        path = write_report_bundle(tmp_path, _facts(), "an excerpt\n", NOW)

        assert path.name == "Basil_Problem_Report_20261107_123045.zip"
        with zipfile.ZipFile(path) as archive:
            assert sorted(archive.namelist()) == ["README.txt", "backend_log_excerpt.txt", "report.json"]
            report = json.loads(archive.read("report.json"))
            assert archive.read("backend_log_excerpt.txt").decode() == "an excerpt\n"
        assert report["hardware"]["total_ram_gb"] == 8
        assert report["installed_model_ids"] == ["OpenAI-whisper-tiny.en", "Qwen-qwen35-4b-mlx-4bit"]
        assert report["selected_models"]["reasoning_model"] == "Qwen-qwen35-4b-mlx-4bit"
        assert not list(tmp_path.glob("*.partial"))

    def test_two_reports_in_one_second_do_not_overwrite_each_other(self, tmp_path) -> None:
        first = write_report_bundle(tmp_path, _facts(), "one", NOW)
        second = write_report_bundle(tmp_path, _facts(), "two", NOW)

        assert first != second
        assert first.exists() and second.exists()

    def test_only_the_newest_reports_are_kept(self, tmp_path) -> None:
        for day in range(1, REPORTS_TO_KEEP + 4):
            write_report_bundle(tmp_path, _facts(), "x", datetime(2026, 10, day, 9, 0, 0))

        names = sorted(path.name for path in tmp_path.glob("*.zip"))

        assert len(names) == REPORTS_TO_KEEP
        assert names[-1] == f"Basil_Problem_Report_202610{REPORTS_TO_KEEP + 3:02d}_090000.zip"

    def test_a_non_report_file_in_the_folder_is_never_removed(self, tmp_path) -> None:
        keep = tmp_path / "notes.zip"
        keep.write_text("mine")
        for day in range(1, REPORTS_TO_KEEP + 3):
            write_report_bundle(tmp_path, _facts(), "x", datetime(2026, 10, day, 9, 0, 0))

        assert keep.read_text() == "mine"


class TestIssueLink:
    def test_the_link_targets_the_repository_and_carries_facts_not_content(self) -> None:
        url = issue_url(_facts(), "Basil_Problem_Report_20261107_123045.zip")

        parsed = urlparse(url)
        assert (parsed.scheme, parsed.netloc, parsed.path) == ("https", "github.com", "/stratten/Basil_OS/issues/new")
        query = parse_qs(parsed.query)
        assert query["title"] == ["Problem report: llama_decode returned -3"]
        body = query["body"][0]
        assert "8 GB memory" in body
        assert "macOS 26.1" in body
        assert "Qwen-qwen35-4b-mlx-4bit" in body
        assert "Basil_Problem_Report_20261107_123045.zip" in body

    def test_the_title_falls_back_to_the_source_and_the_body_stays_short(self) -> None:
        facts = _facts(detail="", hardware={}, selected_models={})

        url = issue_url(facts, "x.zip")

        query = parse_qs(urlparse(url).query)
        assert query["title"] == ["Problem report: setup_assistant"]
        assert "unknown GB memory" in query["body"][0]
        assert len(url) < 4000

    def test_an_oversized_body_is_cut(self) -> None:
        facts = _facts(app_version="v" * 5000)

        assert len(parse_qs(urlparse(issue_url(facts, "x.zip")).query)["body"][0]) <= 1800


class TestSanitizing:
    def test_detail_is_one_scrubbed_capped_line(self) -> None:
        detail = "line one\nline two  with  gaps " + "z" * 600 + " me@example.com"

        cleaned = sanitize_detail(detail)

        assert "\n" not in cleaned
        assert len(cleaned) <= 300
        assert sanitize_detail(None) == ""
        assert sanitize_detail("contact me@example.com") == "contact [email]"

    @pytest.mark.parametrize(("raw", "expected"), [("setup_assistant", "setup_assistant"), ("a b/c;d", "abcd"), ("", "unknown"), (None, "unknown")])
    def test_source_is_a_short_identifier(self, raw, expected) -> None:
        assert sanitize_source(raw) == expected


class TestRoute:
    def _service(self, installed=None):
        downloader = SimpleNamespace(get_installed_models=lambda: installed or {})
        return SimpleNamespace(model_downloader=downloader)

    def test_the_route_writes_a_bundle_and_returns_the_path_and_link(self, tmp_path, monkeypatch) -> None:
        support = tmp_path / "support"
        (support / "logs").mkdir(parents=True)
        (support / "logs" / "backend.log").write_text(
            "ERROR:uvicorn.error:llama_decode returned -3 with a context of 32768 tokens\n"
            "INFO:api.routes.websocket:Text message received: json type='secret'\n"
        )
        monkeypatch.setenv("APP_SUPPORT_DIR", str(support))
        monkeypatch.setattr(diagnostics_routes, "reports_directory", lambda: tmp_path / "reports")
        installed = {"OpenAI": {"variants": {"whisper-tiny.en": {"model_id": "OpenAI-whisper-tiny.en"}}}}

        request = diagnostics_routes.ProblemReportRequest(source="setup_assistant", detail="llama_decode returned -3", app_version="1.0.2", macos_version="macOS 26.1")
        response = diagnostics_routes._build_bundle(request, self._service(installed))

        assert response.log_excerpt_available is True
        assert response.issue_url.startswith("https://github.com/stratten/Basil_OS/issues/new?")
        with zipfile.ZipFile(response.bundle_path) as archive:
            excerpt = archive.read("backend_log_excerpt.txt").decode()
            report = json.loads(archive.read("report.json"))
        assert "llama_decode returned -3" in excerpt
        assert "secret" not in excerpt
        assert report["installed_model_ids"] == ["OpenAI-whisper-tiny.en"]
        assert report["app_version"] == "1.0.2"

    def test_the_route_still_produces_a_bundle_without_a_log_file_or_model_service_data(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("APP_SUPPORT_DIR", raising=False)
        monkeypatch.setattr(diagnostics_routes, "reports_directory", lambda: tmp_path / "reports")
        broken_service = SimpleNamespace(model_downloader=SimpleNamespace(get_installed_models=lambda: (_ for _ in ()).throw(RuntimeError("boom"))))

        response = diagnostics_routes._build_bundle(diagnostics_routes.ProblemReportRequest(), broken_service)

        assert response.log_excerpt_available is False
        with zipfile.ZipFile(response.bundle_path) as archive:
            report = json.loads(archive.read("report.json"))
        assert any("Installed models unavailable" in note for note in report["collection_notes"])
        assert any("No backend log file" in note for note in report["collection_notes"])
