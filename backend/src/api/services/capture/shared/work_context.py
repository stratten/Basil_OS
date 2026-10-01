"""Stable, deterministic work identity for an activity capture."""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Optional

WORK_CONTEXT_VERSION = "1"
_IDE_APPS = frozenset({"cursor", "visual studio code", "code"})
_MAIL_APPS = frozenset({"microsoft outlook", "mail"})
_PLACEHOLDERS = frozenset({"", "unknown", "no window", "capture failed", "capture error"})

@dataclass(frozen=True)
class WorkContext:
    key: str
    label: str
    kind: str
    confidence: str
    evidence: Dict[str, str]

    def as_metadata(self) -> Dict[str, str]:
        return {
            "work_context_key": self.key,
            "work_context_label": self.label,
            "work_context_kind": self.kind,
            "work_context_confidence": self.confidence,
            "work_context_version": WORK_CONTEXT_VERSION,
            "work_context_evidence": "|".join(f"{key}={value}" for key, value in sorted(self.evidence.items())),
        }

def _normalize(value: Optional[str]) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split()).strip()

def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"

def derive_work_context(app_name: str, window_title: Optional[str], *, capture_id: Optional[str] = None) -> WorkContext:
    app = _normalize(app_name)
    title = _normalize(window_title)
    app_key = _slug(app)
    if title.casefold() in _PLACEHOLDERS:
        suffix = _slug(capture_id or title or "unidentified")
        return WorkContext(f"unidentified:{app_key}:{suffix}", title or "Unidentified window", "unidentified", "fallback", {"app_name": app, "window_title": title})
    if app.casefold() in _IDE_APPS and " — " in title:
        workspace = re.sub(r"\s+\(Workspace\)$", "", title.rsplit(" — ", 1)[1]).strip()
        if workspace:
            return WorkContext(f"ide_workspace:{app_key}:{_slug(workspace)}", workspace, "ide_workspace", "high", {"app_name": app, "window_title": title, "workspace": workspace})
    kind = "mail_thread" if app.casefold() in _MAIL_APPS else "window_title"
    return WorkContext(f"{kind}:{app_key}:{_slug(title)}", title, kind, "fallback", {"app_name": app, "window_title": title})
