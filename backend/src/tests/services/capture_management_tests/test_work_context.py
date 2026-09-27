"""Deterministic work-context extraction for activity captures."""

from api.services.capture.shared.work_context import derive_work_context


def test_cursor_workspace_title_extracts_project_identity():
    ctx = derive_work_context(
        "Cursor",
        "activity_routes.py — Basil_Plus_Auth_Service (Workspace)",
        capture_id="cap-1",
    )
    assert ctx.key == "ide_workspace:cursor:basil-plus-auth-service"
    assert ctx.label == "Basil_Plus_Auth_Service"
    assert ctx.kind == "ide_workspace"
    assert ctx.confidence == "high"
    assert ctx.evidence["workspace"] == "Basil_Plus_Auth_Service"


def test_same_workspace_different_files_share_one_key():
    first = derive_work_context(
        "Cursor",
        "foo.py — Speakeasy_AutoAdmin (Workspace)",
        capture_id="cap-a",
    )
    second = derive_work_context(
        "Cursor",
        "bar.swift — Speakeasy_AutoAdmin (Workspace)",
        capture_id="cap-b",
    )
    assert first.key == second.key == "ide_workspace:cursor:speakeasy-autoadmin"
    assert first.label == second.label == "Speakeasy_AutoAdmin"


def test_distinct_workspaces_do_not_share_a_key():
    basil = derive_work_context(
        "Cursor",
        "main.py — Basil_Plus_Auth_Service (Workspace)",
        capture_id="cap-1",
    )
    speakeasy = derive_work_context(
        "Cursor",
        "main.py — Speakeasy_AutoAdmin (Workspace)",
        capture_id="cap-2",
    )
    assert basil.key != speakeasy.key


def test_outlook_threads_are_separated_by_title():
    thread_a = derive_work_context(
        "Microsoft Outlook",
        "Re: Contract review — Client XYZ",
        capture_id="mail-1",
    )
    thread_b = derive_work_context(
        "Microsoft Outlook",
        "Re: Invoice follow-up — Client ABC",
        capture_id="mail-2",
    )
    assert thread_a.kind == thread_b.kind == "mail_thread"
    assert thread_a.key != thread_b.key
    assert thread_a.key.startswith("mail_thread:microsoft-outlook:")


def test_browser_titles_fallback_to_window_title_kind():
    ctx = derive_work_context(
        "Google Chrome",
        "Basil docs - Google Docs",
        capture_id="web-1",
    )
    assert ctx.kind == "window_title"
    assert ctx.key == "window_title:google-chrome:basil-docs-google-docs"
    assert ctx.confidence == "fallback"


def test_no_window_captures_fragment_by_capture_id():
    first = derive_work_context("Cursor", "No Window", capture_id="cap-100")
    second = derive_work_context("Cursor", "No Window", capture_id="cap-200")
    assert first.key != second.key
    assert first.key.startswith("unidentified:cursor:")
    assert second.key.startswith("unidentified:cursor:")


def test_as_metadata_round_trips_all_fields():
    ctx = derive_work_context(
        "Visual Studio Code",
        "README.md — Basil (Workspace)",
        capture_id="cap-x",
    )
    metadata = ctx.as_metadata()
    assert metadata["work_context_version"] == "1"
    assert metadata["work_context_key"] == ctx.key
    assert "app_name=Visual Studio Code" in metadata["work_context_evidence"]
    assert "workspace=Basil" in metadata["work_context_evidence"]
