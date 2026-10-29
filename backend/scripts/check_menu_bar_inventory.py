#!/usr/bin/env python3
"""Drift check: Swift menu source <-> Python menu_bar_inventory catalog.

The setup agent describes the Basil menu bar dropdown to new users
during onboarding. The list of items lives in two places:

  * Source of truth — Swift:
    ``client/Sources/Services/StatusBar/StatusBarMenuBuilder.swift``
  * Mirror for prompt rendering — Python:
    ``backend/src/api/services/setup_assistant/agent_graph/menu_bar_inventory.py``

This script parses the Swift source, resolves a small set of known
``BasilTeamIdentity.*.displayName`` interpolations, and compares the
ordered titles against ``canonical_menu_titles()`` from the Python
catalog. Drift exits 1 with an actionable diff. ``scripts/build-setup-assistant-assets.sh``
runs this on every dev (``dev.sh``) and release build, so
a developer who edits the Swift menu without updating the catalog
finds out immediately rather than in a user-facing hallucination.

Stdlib only — runs cleanly in CI without a venv.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
SWIFT_SOURCE = (
    REPO_ROOT
    / "client"
    / "Sources"
    / "Services"
    / "StatusBar"
    / "StatusBarMenuBuilder.swift"
)
PY_CATALOG = (
    REPO_ROOT
    / "backend"
    / "src"
    / "api"
    / "services"
    / "setup_assistant"
    / "agent_graph"
    / "menu_bar_inventory.py"
)


def _strip_block_comments(text: str) -> str:
    """Strip Swift ``/* ... */`` block comments via a single-pass state machine.

    Swift's block comments nest, but the StatusBarMenuBuilder.swift
    source only uses non-nested blocks today. We support a single
    depth counter so a future nested block won't silently leak its
    contents (and the inner ``*/`` won't prematurely close the outer
    block).

    String literals are preserved verbatim — a ``/*`` inside a quoted
    string must not start a comment. We track whether we're inside a
    double-quoted string and skip the comment machinery while there.
    """

    out: List[str] = []
    i = 0
    depth = 0
    in_string = False
    n = len(text)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if depth == 0 and not in_string and ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "*":
            depth += 1
            i += 2
            continue
        if depth > 0 and ch == "*" and nxt == "/":
            depth -= 1
            i += 2
            continue
        if depth > 0:
            if ch == "\n":
                out.append("\n")  # preserve line numbering for diagnostics
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _strip_line_comments(text: str) -> str:
    """Drop ``//``-to-end-of-line comments, preserving string literals."""

    cleaned: List[str] = []
    for line in text.splitlines(keepends=True):
        rebuilt: List[str] = []
        in_string = False
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            nxt = line[i + 1] if i + 1 < n else ""
            if not in_string and ch == "/" and nxt == "/":
                break
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_string = not in_string
            rebuilt.append(ch)
            i += 1
        cleaned.append("".join(rebuilt))
    return "".join(cleaned)


def _strip_debug_only_blocks(text: str) -> str:
    """Exclude ``#if DEBUG`` blocks from the production menu inventory check. The setup prompt describes normal user-visible menu actions, so development-only comparison actions are intentionally omitted even when the check runs in a DEBUG build. Nested compile-condition blocks inside a DEBUG-only block are skipped with it, while newlines are retained for useful diagnostics."""

    cleaned: List[str] = []
    debug_depth = 0
    for line in text.splitlines(keepends=True):
        directive = line.strip()
        if debug_depth == 0 and directive == "#if DEBUG":
            debug_depth = 1
            cleaned.append("\n" if line.endswith("\n") else "")
            continue
        if debug_depth > 0:
            if directive.startswith("#if "):
                debug_depth += 1
            elif directive == "#endif":
                debug_depth -= 1
            cleaned.append("\n" if line.endswith("\n") else "")
            continue
        cleaned.append(line)
    return "".join(cleaned)


# Matches the leading ``NSMenuItem(title: "..."`` of either the
# multi-line factory form (settings, hotkeysItem, etc.) or the
# single-line form (conversationItem, transcriptionItem, etc.).
# The title body matches anything except a double-quote or backslash,
# but allows escaped sequences via ``\\.`` so a future ``\"`` inside
# a title doesn't terminate the match early.
_TITLE_RE = re.compile(
    r"""NSMenuItem\(
        \s*title:\s*
        "((?:\\.|[^"\\])*)"
    """,
    re.VERBOSE,
)

# Matches an exact ``\(expression)`` interpolation. We only support
# whole-title interpolations and bare-prefix interpolations of the
# form ``Foo \(expr)`` (one interpolation per title; today the Swift
# source only uses that exact shape).
_INTERP_RE = re.compile(r"\\\(([^)]+)\)")


def _resolve_interpolations(
    raw_title: str,
    substitutions: dict[str, str],
    line_hint: str,
) -> str:
    """Substitute known ``BasilTeamIdentity.*.displayName`` expressions.

    Unknown interpolation expressions raise ``KeyError`` with the
    offending expression, so a new dynamic title in the Swift source
    surfaces as a loud failure pointing at this script and at
    ``SWIFT_DISPLAY_NAME_SUBSTITUTIONS`` in ``menu_bar_inventory.py``,
    rather than silently parsing into a literal ``"\\(Foo.bar)"``
    title that would fail the diff in a confusing way.
    """

    def _sub(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        if expr not in substitutions:
            raise KeyError(
                f"Unknown Swift interpolation `\\({expr})` in menu title "
                f"`{raw_title}` ({line_hint}). Add it to "
                f"SWIFT_DISPLAY_NAME_SUBSTITUTIONS in menu_bar_inventory.py "
                f"or update the parser if a new interpolation shape is in use."
            )
        return substitutions[expr]

    return _INTERP_RE.sub(_sub, raw_title)


def parse_swift_titles(
    swift_source: str,
    substitutions: dict[str, str],
) -> List[str]:
    """Return the ordered, resolved titles from a Swift menu source.

    The pipeline is: strip DEBUG-only blocks -> strip block comments -> strip line comments ->
    regex-extract ``NSMenuItem(title: "...")`` matches -> trim
    leading whitespace (the ``"   Transcription History"`` indent
    prefix is a rendering detail, not part of the canonical title) ->
    resolve interpolations against ``substitutions``.
    """

    production_source = _strip_debug_only_blocks(swift_source)
    no_blocks = _strip_block_comments(production_source)
    cleaned = _strip_line_comments(no_blocks)

    titles: List[str] = []
    for match in _TITLE_RE.finditer(cleaned):
        raw = match.group(1).replace(r"\"", '"')
        line_no = cleaned.count("\n", 0, match.start()) + 1
        resolved = _resolve_interpolations(
            raw, substitutions, f"line ~{line_no} of cleaned source"
        )
        titles.append(resolved.lstrip())
    return titles


def _load_catalog():
    """Import ``menu_bar_inventory.py`` directly from disk.

    We do not want to depend on the surrounding ``api.*`` package
    being importable (it pulls in fastapi and the rest of the runtime
    stack), so this script imports the catalog module in isolation
    via ``importlib.util`` instead of via ``import api.services...``.
    """

    spec = importlib.util.spec_from_file_location(
        "menu_bar_inventory_for_drift_check", PY_CATALOG
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Python catalog at {PY_CATALOG}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _diff(swift_titles: List[str], python_titles: List[str]) -> List[str]:
    """Format a human-readable diff of two ordered title lists.

    Returns an empty list when the lists match exactly. Otherwise
    returns lines suitable for printing — grouped by drift kind
    (added in Swift, removed in Swift, reorder-only) so the developer
    can act on the most relevant case first.
    """

    if swift_titles == python_titles:
        return []

    swift_set = set(swift_titles)
    py_set = set(python_titles)
    added = [t for t in swift_titles if t not in py_set]
    removed = [t for t in python_titles if t not in swift_set]
    lines: List[str] = []

    if added:
        lines.append("  In Swift but missing from menu_bar_inventory.py:")
        for title in added:
            lines.append(f'    + "{title}"')
    if removed:
        lines.append("  In menu_bar_inventory.py but missing from Swift:")
        for title in removed:
            lines.append(f'    - "{title}"')
    if not added and not removed:
        # Same set, different order — show both orderings side by side
        # so the developer can spot the swap quickly.
        lines.append("  Reorder-only drift (same items, different order):")
        lines.append("    Swift order:")
        for i, title in enumerate(swift_titles, 1):
            lines.append(f'      {i:2d}. "{title}"')
        lines.append("    Python order:")
        for i, title in enumerate(python_titles, 1):
            lines.append(f'      {i:2d}. "{title}"')
    return lines


def _format_titles(titles: Iterable[str]) -> str:
    return "\n".join(f'  {i + 1:2d}. "{t}"' for i, t in enumerate(titles))


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Default mode. Diff Swift titles against menu_bar_inventory.py and exit 1 on drift.",
    )
    parser.add_argument(
        "--print-swift",
        action="store_true",
        help="Print the parsed Swift titles (debugging aid) and exit 0 without diffing.",
    )
    args = parser.parse_args(argv)

    if not SWIFT_SOURCE.exists():
        print(f"ERROR: Swift source not found at {SWIFT_SOURCE}", file=sys.stderr)
        return 2
    if not PY_CATALOG.exists():
        print(f"ERROR: Python catalog not found at {PY_CATALOG}", file=sys.stderr)
        return 2

    catalog = _load_catalog()
    substitutions = catalog.SWIFT_DISPLAY_NAME_SUBSTITUTIONS
    python_titles = catalog.canonical_menu_titles()

    swift_source = SWIFT_SOURCE.read_text(encoding="utf-8")
    try:
        swift_titles = parse_swift_titles(swift_source, substitutions)
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.print_swift:
        print(f"Parsed {len(swift_titles)} titles from {SWIFT_SOURCE.name}:")
        print(_format_titles(swift_titles))
        return 0

    diff_lines = _diff(swift_titles, python_titles)
    if not diff_lines:
        print(f"OK   menu bar inventory in sync ({len(swift_titles)} items)")
        return 0

    rel_swift = SWIFT_SOURCE.relative_to(REPO_ROOT)
    rel_py = PY_CATALOG.relative_to(REPO_ROOT)
    print("Menu bar inventory drift detected.", file=sys.stderr)
    print(f"  Swift source:   {rel_swift}", file=sys.stderr)
    print(f"  Python catalog: {rel_py}", file=sys.stderr)
    print("", file=sys.stderr)
    for line in diff_lines:
        print(line, file=sys.stderr)
    print("", file=sys.stderr)
    print("Update one or the other, then re-run.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
