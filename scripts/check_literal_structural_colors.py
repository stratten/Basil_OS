#!/usr/bin/env python3
"""Static check preventing undeclared literal structural colors in Basil's web
components, outside their approved token-definition files.

An "approved token-definition file" is any CSS file literally named
`theme.css` (matched by the `**/theme.css` glob) -- these are the files whose
whole job is to declare the real hex/rgba value each `--token-name` custom
property resolves to, so a literal color there is the definition, not a leak.

For every other `*.css` file under `web-components/*/src/`, this
script flags any of the following "structural" literal-color patterns:
  - `#ffffff` / `#fff` / `#000000` / `#000` (case-insensitive)
  - `rgb(255, 255, 255` / `rgba(255, 255, 255` (any alpha)
  - `rgb(0, 0, 0` / `rgba(0, 0, 0` (any alpha)

Before scanning, this script strips:
  - every `/* ... */` comment (so a match inside a comment never counts);
  - the body of every `:root { ... }` block (fallback `var(--x, #fff)`
    declarations legitimately live there across many files, matching the
    precedent already established in Packages 4B/5/6's own literal-color
    audits, which always excluded each file's own `:root` fallback block);
  - any line whose declaration property is `box-shadow`, `-webkit-box-shadow`,
    `filter`, or `text-shadow` (pure shadow/blur effects using black/white
    with alpha are an already-audited, intentionally-preserved Bucket-2
    "leave alone" category from Packages 5/6, not a structural-surface leak).

Every surviving match is compared against a checked-in baseline allowlist at
`scripts/literal_structural_colors_allowlist.json`, keyed by
`"<relative/path.css>": ["<line_number>:<stripped_line_text>", ...]`. A match
already present in the baseline for that exact file+line+text is accepted
silently (it is already-audited, already-accepted debt from Packages 4B/5/6,
e.g. the universal `rgba(51, 85, 155, 0.15)` SVG-icon-fill convention, the
deferred interactive-pseudo-class literal-hue duplicates, and each file's own
`:root` fallback block that this script's stripping step does not already
remove). Any match NOT already in the baseline is a new, unreviewed literal
structural color and fails the check -- this is what makes the check
regression-preventing rather than merely descriptive: it does not re-flag
already-accepted debt, but it does catch every newly introduced instance.

Usage:
    python3 scripts/check_literal_structural_colors.py            # check mode (default), exit 1 on any new finding
    python3 scripts/check_literal_structural_colors.py --update-baseline
        # regenerates the baseline from the CURRENT tree's matches and writes
        # scripts/literal_structural_colors_allowlist.json. Run this exactly
        # once, at Package 8 implementation time, immediately after this
        # script itself is added and before any other Package 8 sub-package
        # changes a single CSS file, so the generated baseline captures
        # today's already-audited state -- not a moving target that could
        # silently swallow a real new leak introduced later in the same pass.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_COMPONENTS_ROOT = REPO_ROOT / "web-components"
BASELINE_PATH = Path(__file__).resolve().parent / "literal_structural_colors_allowlist.json"

LITERAL_COLOR_PATTERN = re.compile(
    r"(#fff(?:fff)?\b|#000(?:000)?\b|rgba?\(\s*255\s*,\s*255\s*,\s*255|rgba?\(\s*0\s*,\s*0\s*,\s*0)",
    re.IGNORECASE,
)
ROOT_BLOCK_PATTERN = re.compile(r":root\s*\{[^}]*\}", re.DOTALL)
BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
SHADOW_PROPERTY_PATTERN = re.compile(
    r"^\s*(-webkit-)?(box-shadow|filter|text-shadow)\s*:", re.IGNORECASE
)


def is_approved_token_definition_file(path: Path) -> bool:
    return path.name == "theme.css"


def iter_css_files() -> list[Path]:
    # `web-components/*/src/**/*.css` covers every per-panel package's
    # own source tree. `web-components/shared/**/*.css` is a second,
    # separate glob because the shared module lives directly under `shared/`
    # with no intervening `src/` segment (confirmed by inspecting its layout:
    # `basil-window-chrome.css`, `rich-text-followup.css`, etc. sit at
    # `web-components/shared/*.css`) -- without this second glob the
    # shared CSS every consumer package imports would be silently unscanned.
    candidates = set(WEB_COMPONENTS_ROOT.glob("*/src/**/*.css"))
    candidates.update(WEB_COMPONENTS_ROOT.glob("shared/**/*.css"))
    return sorted(
        p for p in candidates if "node_modules" not in p.parts and "dist" not in p.parts
    )


def strip_ignored_regions(content: str) -> str:
    content = BLOCK_COMMENT_PATTERN.sub("", content)
    content = ROOT_BLOCK_PATTERN.sub("", content)
    return content


def find_matches(path: Path) -> list[tuple[int, str]]:
    original_text = path.read_text(encoding="utf-8")
    stripped_text = strip_ignored_regions(original_text)
    stripped_lines = stripped_text.splitlines()
    findings: list[tuple[int, str]] = []
    for line_number, line in enumerate(stripped_lines, start=1):
        if SHADOW_PROPERTY_PATTERN.match(line):
            continue
        if LITERAL_COLOR_PATTERN.search(line):
            findings.append((line_number, line.strip()))
    return findings


def relative_key(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_baseline() -> dict[str, list[str]]:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(baseline: dict[str, list[str]]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def collect_current_findings() -> dict[str, list[str]]:
    current: dict[str, list[str]] = {}
    for css_path in iter_css_files():
        if is_approved_token_definition_file(css_path):
            continue
        matches = find_matches(css_path)
        if not matches:
            continue
        key = relative_key(css_path)
        current[key] = [f"{line_number}:{text}" for line_number, text in matches]
    return current


def run_check() -> int:
    baseline = load_baseline()
    current = collect_current_findings()
    new_findings: dict[str, list[str]] = {}
    for path_key, entries in current.items():
        baseline_entries = set(baseline.get(path_key, []))
        unseen = [entry for entry in entries if entry not in baseline_entries]
        if unseen:
            new_findings[path_key] = unseen

    if not new_findings:
        print("check_literal_structural_colors: no new undeclared literal structural colors found.")
        return 0

    print("check_literal_structural_colors: found new undeclared literal structural colors:")
    for path_key, entries in sorted(new_findings.items()):
        for entry in entries:
            print(f"  {path_key}:{entry}")
    print(
        "\nEach line above is either a real regression (replace the literal with the matching "
        "--token-name custom property) or a genuinely new, intentional fixed-hue exception that "
        "needs a one-line addition to scripts/literal_structural_colors_allowlist.json explaining why."
    )
    return 1


def run_update_baseline() -> int:
    current = collect_current_findings()
    write_baseline(current)
    total_entries = sum(len(v) for v in current.values())
    print(
        f"check_literal_structural_colors: wrote baseline with {total_entries} accepted "
        f"entries across {len(current)} files to {relative_key(BASELINE_PATH)}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Regenerate the baseline allowlist from the current tree instead of checking against it.",
    )
    args = parser.parse_args()
    if args.update_baseline:
        return run_update_baseline()
    return run_check()


if __name__ == "__main__":
    sys.exit(main())
