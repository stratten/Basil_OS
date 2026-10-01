#!/usr/bin/env python3
"""Fail when a scanned text file contains a British spelling outside the protected locations in spelling_policy.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spelling_policy import find_violations, iter_repository_files, read_text_preserving_newlines  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    violations = []
    for relpath in iter_repository_files(REPO_ROOT):
        text = read_text_preserving_newlines(REPO_ROOT / relpath)
        if text is not None:
            violations.extend(find_violations(relpath, text))
    for violation in violations:
        suggestion = f" -> {violation.replacement}" if violation.replacement else ""
        print(f"{violation.path}:{violation.line}:{violation.column}: {violation.token}{suggestion}")
    if violations:
        print(
            f"{len(violations)} British spelling(s) found. Use American spelling, or add a protected "
            "external token to scripts/spelling/spelling_policy.py when the spelling belongs to an "
            "external API, platform symbol, or protocol value.",
            file=sys.stderr,
        )
        return 1
    print("American spelling check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
