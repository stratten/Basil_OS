#!/usr/bin/env python3
"""Static check preventing undeclared literal structural colors in Basil's web components, outside their approved token-definition files.

An approved token-definition file is any CSS file named `theme.css`. Those files declare the real value each `--token-name` custom property resolves to, so a literal color there is the definition, not a leak.

For every other `*.css` file under `web-components/*/src/` and `web-components/shared/`, this script flags each declaration whose value contains one of these structural literal colors:
  - `#ffffff` / `#fff` / `#000000` / `#000` (case-insensitive)
  - `rgb(255, 255, 255` / `rgba(255, 255, 255` (any alpha)
  - `rgb(0, 0, 0` / `rgba(0, 0, 0` (any alpha)

Before scanning, it blanks every `/* ... */` comment and every `:root { ... }` block while keeping their line breaks, so reported line numbers match the file. It skips `box-shadow`, `-webkit-box-shadow`, `filter`, and `text-shadow` declarations, including ones that span several lines.

Each accepted exception in `scripts/literal_structural_colors_allowlist.json` is named by its file, selector, property, and value, and carries a reason. Line numbers are reported for convenience but are not part of the name. A declaration whose name is not in the allowlist fails the check; allowlist entries that no longer match anything are reported as stale.

Usage:
    python3 scripts/check_literal_structural_colors.py
        # check mode (default); exit 1 on any declaration missing from the allowlist
    python3 scripts/check_literal_structural_colors.py --update-baseline --reason "Why these colors are intentional."
        # rewrites the allowlist from the current tree: keeps matching entries and their reasons, drops stale entries, and adds new declarations with the given reason (required whenever something new would be added)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_COMPONENTS_ROOT = REPO_ROOT / "web-components"
BASELINE_PATH = Path(__file__).resolve().parent / "literal_structural_colors_allowlist.json"
BASELINE_VERSION = 2

LITERAL_COLOR_PATTERN = re.compile(
    r"(#fff(?:fff)?\b|#000(?:000)?\b|rgba?\(\s*255\s*,\s*255\s*,\s*255|rgba?\(\s*0\s*,\s*0\s*,\s*0)",
    re.IGNORECASE,
)
ROOT_BLOCK_PATTERN = re.compile(r":root\s*\{[^}]*\}", re.DOTALL)
BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
SHADOW_PROPERTIES = frozenset({"box-shadow", "-webkit-box-shadow", "filter", "text-shadow"})


@dataclass(frozen=True, order=True)
class DeclarationName:
    file: str
    selector: str
    property: str
    value: str

    def label(self) -> str:
        return f"{self.selector} {{ {self.property}: {self.value} }}"


@dataclass(frozen=True)
class LiteralDeclaration:
    selector: str
    property: str
    value: str
    line: int


def _blank_preserving_lines(match: re.Match[str]) -> str:
    return "\n" * match.group(0).count("\n")


def strip_ignored_regions(content: str) -> str:
    content = BLOCK_COMMENT_PATTERN.sub(_blank_preserving_lines, content)
    return ROOT_BLOCK_PATTERN.sub(_blank_preserving_lines, content)


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def iter_literal_declarations(content: str) -> list[LiteralDeclaration]:
    text = strip_ignored_regions(content)
    findings: list[LiteralDeclaration] = []
    selector_stack: list[str] = []
    buffer: list[str] = []
    buffer_line = 1
    line = 1
    quote: str | None = None
    paren_depth = 0

    def record(chunk: str) -> None:
        if not selector_stack or ":" not in chunk:
            return
        prop, value = chunk.split(":", 1)
        prop = prop.strip().lower()
        value = value.strip()
        if prop in SHADOW_PROPERTIES or not LITERAL_COLOR_PATTERN.search(value):
            return
        findings.append(LiteralDeclaration(" / ".join(selector_stack), prop, value, buffer_line))

    for char in text:
        if quote is None and paren_depth == 0 and char in "{};":
            chunk = _collapse_whitespace("".join(buffer))
            if char == "{":
                selector_stack.append(chunk)
            else:
                record(chunk)
                if char == "}" and selector_stack:
                    selector_stack.pop()
            buffer = []
        elif buffer or not char.isspace():
            if not buffer:
                buffer_line = line
            buffer.append(char)
            if quote is not None:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth = max(0, paren_depth - 1)
        if char == "\n":
            line += 1
    return findings


def is_approved_token_definition_file(path: Path) -> bool:
    return path.name == "theme.css"


def iter_css_files() -> list[Path]:
    # Shared CSS lives directly under `web-components/shared/` with no `src/` segment, so it needs its own glob.
    candidates = set(WEB_COMPONENTS_ROOT.glob("*/src/**/*.css"))
    candidates.update(WEB_COMPONENTS_ROOT.glob("shared/**/*.css"))
    return sorted(
        p for p in candidates if "node_modules" not in p.parts and "dist" not in p.parts
    )


def relative_key(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def collect_current_findings() -> dict[DeclarationName, list[int]]:
    current: dict[DeclarationName, list[int]] = {}
    for css_path in iter_css_files():
        if is_approved_token_definition_file(css_path):
            continue
        file_key = relative_key(css_path)
        for declaration in iter_literal_declarations(css_path.read_text(encoding="utf-8")):
            name = DeclarationName(file_key, declaration.selector, declaration.property, declaration.value)
            current.setdefault(name, []).append(declaration.line)
    return current


def load_baseline() -> dict[DeclarationName, str] | None:
    """Return the allowlist, an empty allowlist when the file is missing, or None when it is not version 2."""
    if not BASELINE_PATH.exists():
        return {}
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != BASELINE_VERSION:
        return None
    baseline: dict[DeclarationName, str] = {}
    for file_key, entries in data.get("files", {}).items():
        for entry in entries:
            name = DeclarationName(file_key, entry["selector"], entry["property"], entry["value"])
            baseline[name] = entry["reason"]
    return baseline


def write_baseline(baseline: dict[DeclarationName, str]) -> None:
    files: dict[str, list[dict[str, str]]] = {}
    for name in sorted(baseline):
        files.setdefault(name.file, []).append(
            {
                "selector": name.selector,
                "property": name.property,
                "value": name.value,
                "reason": baseline[name],
            }
        )
    BASELINE_PATH.write_text(
        json.dumps({"version": BASELINE_VERSION, "files": files}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def compare(
    current: dict[DeclarationName, list[int]], baseline: dict[DeclarationName, str]
) -> tuple[dict[DeclarationName, list[int]], list[DeclarationName]]:
    unlisted = {name: lines for name, lines in current.items() if name not in baseline}
    stale = sorted(name for name in baseline if name not in current)
    return unlisted, stale


def _format_finding(name: DeclarationName, lines: list[int]) -> str:
    return f"  {name.file}:{', '.join(str(n) for n in lines)}  {name.label()}"


def run_check() -> int:
    baseline = load_baseline()
    if baseline is None:
        print(
            f"check_literal_structural_colors: {BASELINE_PATH.name} is not a version {BASELINE_VERSION} allowlist. "
            'Regenerate it with --update-baseline --reason "...".'
        )
        return 2
    unlisted, stale = compare(collect_current_findings(), baseline)
    for name in stale:
        print(f"check_literal_structural_colors: stale allowlist entry (no longer in the CSS): {name.file}  {name.label()}")
    if not unlisted:
        print("check_literal_structural_colors: no new undeclared literal structural colors found.")
        return 0
    print("check_literal_structural_colors: found new undeclared literal structural colors:")
    for name in sorted(unlisted):
        print(_format_finding(name, unlisted[name]))
    print(
        "\nReplace each literal with the matching --token-name custom property, or, if it is an intentional fixed "
        f"color, add it to scripts/{BASELINE_PATH.name} with a reason (for example with "
        '--update-baseline --reason "...").'
    )
    return 1


def run_update_baseline(reason: str | None) -> int:
    baseline = load_baseline() or {}
    current = collect_current_findings()
    unlisted, stale = compare(current, baseline)
    new_reason = (reason or "").strip()
    if unlisted and not new_reason:
        print("check_literal_structural_colors: --reason is required because these declarations are not yet in the allowlist:")
        for name in sorted(unlisted):
            print(_format_finding(name, unlisted[name]))
        return 2
    updated = {name: baseline.get(name, new_reason) for name in current}
    write_baseline(updated)
    print(
        f"check_literal_structural_colors: wrote {len(updated)} entries across {len({n.file for n in updated})} files "
        f"to {BASELINE_PATH.name} ({len(unlisted)} added, {len(stale)} stale removed)."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite the allowlist from the current tree instead of checking against it.",
    )
    parser.add_argument(
        "--reason",
        help="Reason recorded on every declaration --update-baseline adds. Required when anything new would be added.",
    )
    args = parser.parse_args()
    if args.reason is not None and not args.update_baseline:
        parser.error("--reason is only valid with --update-baseline")
    if args.update_baseline:
        return run_update_baseline(args.reason)
    return run_check()


if __name__ == "__main__":
    sys.exit(main())
