"""Eligibility rules for which paths managed file history will version.

An ineligible path is never blocked from being written -- only from being
versioned. ManagedFileHistoryService falls back to the plain
LocalTextFileWriter for ineligible paths so agent write capability is
unaffected by this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_SENSITIVE_DIRECTORY_NAMES = (
    ".ssh",
    ".gnupg",
    ".aws",
    ".docker",
    ".basil",
    "Library",
)

_CLOUD_BACKED_MARKERS = (
    "Mobile Documents",
    "CloudDocs",
    "Dropbox",
    "OneDrive",
    "Google Drive",
)


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str | None = None


def evaluate_eligibility(path: Path) -> EligibilityResult:
    """Return whether ``path`` (already expanded/resolved) is eligible for
    managed history versioning."""
    resolved = Path(path).expanduser().resolve()
    home = Path.home().resolve()

    for part in resolved.parts:
        if part.startswith(".") and part not in (".", ".."):
            return EligibilityResult(
                eligible=False,
                reason=f"Path contains a hidden component ({part!r}) excluded from managed history.",
            )

    try:
        relative_to_home = resolved.relative_to(home)
    except ValueError:
        relative_to_home = None

    if relative_to_home is not None and relative_to_home.parts:
        top_level = relative_to_home.parts[0]
        if top_level in _SENSITIVE_DIRECTORY_NAMES:
            return EligibilityResult(
                eligible=False,
                reason=f"Path is under the excluded sensitive/application-data directory {top_level!r}.",
            )

    resolved_str = str(resolved)
    for marker in _CLOUD_BACKED_MARKERS:
        if marker in resolved_str:
            return EligibilityResult(
                eligible=False,
                reason=f"Path is under a cloud-backed sync root ({marker!r}) excluded from managed history.",
            )

    return EligibilityResult(eligible=True, reason=None)
