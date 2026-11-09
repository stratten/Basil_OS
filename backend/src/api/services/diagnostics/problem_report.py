"""Builds the Report a problem bundle: a zip with machine and model facts plus a redacted log excerpt, and a pre-filled GitHub issue link.

Nothing here reads conversations, prompts, captured activity or file contents.
The bundle never leaves the Mac by itself: the app reveals it in Finder and the user attaches it to the issue.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from api.services.diagnostics.log_redaction import scrub_line

ISSUE_REPOSITORY = "stratten/Basil_OS"
ISSUE_URL_BODY_LIMIT = 1800
DETAIL_LIMIT = 300
REPORTS_TO_KEEP = 10
BUNDLE_PREFIX = "Basil_Problem_Report_"

README_TEXT = (
    "This bundle was made by Basil's Report a problem command.\n"
    "report.json holds the app version, macOS version, memory size, the models you selected, which models are installed (ids only), and how Basil planned to load the local model.\n"
    "backend_log_excerpt.txt holds only recent lines from model, runtime and download code, with paths, email addresses and secrets removed.\n"
    "It does not contain your conversations, prompts, captured screens or files.\n"
    "Nothing has been sent anywhere. Attach this zip to the GitHub issue if you are comfortable sharing it.\n"
)


@dataclass
class ProblemReportFacts:
    """Everything the bundle reports. Every value is already a plain, non-content fact."""

    source: str
    detail: str
    app_version: str
    macos_version: str
    hardware: Dict[str, Any] = field(default_factory=dict)
    selected_models: Dict[str, Any] = field(default_factory=dict)
    installed_model_ids: List[str] = field(default_factory=list)
    local_model_plan: Optional[Dict[str, Any]] = None
    collection_notes: List[str] = field(default_factory=list)


def sanitize_detail(detail: Optional[str]) -> str:
    """One scrubbed line of at most ``DETAIL_LIMIT`` characters. The caller passes a native return code or similar, never conversation text."""
    if not detail:
        return ""
    single_line = " ".join(detail.split())
    return scrub_line(single_line)[:DETAIL_LIMIT]


def sanitize_source(source: Optional[str]) -> str:
    """The surface that opened the flow, reduced to a short identifier."""
    text = "".join(character for character in (source or "") if character.isalnum() or character in "_-")
    return text[:40] or "unknown"


def report_dict(facts: ProblemReportFacts, generated_at: datetime) -> Dict[str, Any]:
    """The machine-readable report."""
    return {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "source": facts.source,
        "detail": facts.detail,
        "app_version": facts.app_version,
        "macos_version": facts.macos_version,
        "hardware": facts.hardware,
        "selected_models": facts.selected_models,
        "installed_model_ids": sorted(facts.installed_model_ids),
        "local_model_plan": facts.local_model_plan,
        "collection_notes": facts.collection_notes,
    }


def _prune_old_reports(reports_dir: Path) -> None:
    bundles = sorted(
        (entry for entry in reports_dir.glob(f"{BUNDLE_PREFIX}*.zip") if entry.is_file()),
        key=lambda entry: entry.name,
    )
    for stale in bundles[:-REPORTS_TO_KEEP]:
        try:
            stale.unlink()
        except OSError:
            continue


def write_report_bundle(
    reports_dir: Path,
    facts: ProblemReportFacts,
    log_excerpt: str,
    generated_at: datetime,
) -> Path:
    """Write the zip into ``reports_dir`` and return its path. Older reports beyond ``REPORTS_TO_KEEP`` are removed."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%d_%H%M%S")
    bundle_path = reports_dir / f"{BUNDLE_PREFIX}{stamp}.zip"
    suffix = 1
    while bundle_path.exists():
        suffix += 1
        bundle_path = reports_dir / f"{BUNDLE_PREFIX}{stamp}_{suffix}.zip"

    staging = bundle_path.with_suffix(".partial")
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.json", json.dumps(report_dict(facts, generated_at), indent=2, sort_keys=True) + "\n")
            archive.writestr("backend_log_excerpt.txt", log_excerpt)
            archive.writestr("README.txt", README_TEXT)
        shutil.move(str(staging), str(bundle_path))
    finally:
        if staging.exists():
            staging.unlink()
    _prune_old_reports(reports_dir)
    return bundle_path


def issue_body(facts: ProblemReportFacts, bundle_name: str) -> str:
    """The text pre-filled into the new issue. It is facts only; the user adds what happened."""
    memory = facts.hardware.get("total_ram_gb")
    chip = facts.hardware.get("chip_label") or facts.hardware.get("machine") or "unknown"
    models = facts.selected_models
    lines = [
        "**What happened?**",
        "",
        "(Please describe what you were doing and what you expected.)",
        "",
        "**Details Basil collected**",
        "",
        f"- Basil: {facts.app_version or 'unknown'}",
        f"- macOS: {facts.macos_version or 'unknown'}",
        f"- Mac: {chip}, {memory if memory is not None else 'unknown'} GB memory",
        f"- Opened from: {facts.source}",
        f"- Thinking model: {models.get('reasoning_model') or 'not set'}",
        f"- Transcription model: {models.get('transcription_model') or 'not set'}",
    ]
    if facts.detail:
        lines.append(f"- Error detail: {facts.detail}")
    lines += [
        "",
        f"Basil saved `{bundle_name}` and showed it in Finder. Attach it here if you are comfortable sharing it.",
    ]
    return "\n".join(lines)


def issue_url(facts: ProblemReportFacts, bundle_name: str) -> str:
    """A GitHub new-issue link with the title and body filled in, kept short enough to open reliably."""
    title = "Problem report: " + (facts.detail[:60] if facts.detail else facts.source)
    body = issue_body(facts, bundle_name)
    if len(body) > ISSUE_URL_BODY_LIMIT:
        body = body[:ISSUE_URL_BODY_LIMIT]
    return f"https://github.com/{ISSUE_REPOSITORY}/issues/new?title={quote(title, safe='')}&body={quote(body, safe='')}"
