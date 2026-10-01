#!/usr/bin/env python3
"""One-time American-spelling codemod over tracked and untracked-but-not-ignored text files.

Dry-run by default: writes a unified diff and prints a summary without touching files. Pass --apply to write the changes. Limit a run to one package with one or more --path prefixes. The run refuses to apply when a renamed compound identifier would collide with an identifier that already exists in the same file.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spelling_policy import (  # noqa: E402
    americanize_text,
    compound_identifier_collisions,
    iter_repository_files,
    read_text_preserving_newlines,
    write_text_preserving_newlines,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _selected(relpath: str, prefixes: list[str]) -> bool:
    return not prefixes or any(relpath == prefix or relpath.startswith(prefix + "/") for prefix in prefixes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the americanized files instead of only producing the diff.")
    parser.add_argument("--path", action="append", default=[], help="Repository-relative path prefix that limits the run. Repeatable.")
    parser.add_argument("--diff-out", type=Path, help="Write the unified diff to this file instead of stdout.")
    args = parser.parse_args(argv)
    prefixes = [prefix.strip("/") for prefix in args.path]

    pending: list[tuple[Path, str]] = []
    diff_chunks: list[str] = []
    collisions: list[tuple[str, str, str]] = []
    replacement_count = 0
    for relpath in iter_repository_files(REPO_ROOT):
        if not _selected(relpath, prefixes):
            continue
        file_path = REPO_ROOT / relpath
        original = read_text_preserving_newlines(file_path)
        if original is None:
            continue
        americanized, findings = americanize_text(relpath, original)
        if not findings:
            continue
        if americanized.count("\n") != original.count("\n"):
            raise RuntimeError(f"Line count changed for {relpath}; refusing to continue.")
        replacement_count += len(findings)
        collisions.extend(
            (relpath, british, american)
            for british, american in compound_identifier_collisions(original, americanized)
        )
        diff_chunks.append(
            "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    americanized.splitlines(keepends=True),
                    fromfile=f"a/{relpath}",
                    tofile=f"b/{relpath}",
                )
            )
        )
        pending.append((file_path, americanized))

    diff_text = "".join(diff_chunks)
    if args.diff_out is not None:
        args.diff_out.write_text(diff_text, encoding="utf-8")
    elif diff_text:
        sys.stdout.write(diff_text)

    for relpath, british, american in collisions:
        print(f"COLLISION {relpath}: {british} would become {american}, which already exists in this file", file=sys.stderr)
    mode = "apply" if args.apply else "dry-run"
    print(
        f"[{mode}] {len(pending)} file(s), {replacement_count} replacement(s), "
        f"{len(collisions)} compound-identifier collision(s).",
        file=sys.stderr,
    )
    if collisions:
        return 1
    if args.apply:
        for file_path, americanized in pending:
            write_text_preserving_newlines(file_path, americanized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
