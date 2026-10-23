#!/bin/bash
# Prints the "- " bullet lines of one CHANGELOG.md section, one bullet per line. The section is "Unreleased" or a version such as 1.1.7. A missing section, a duplicated heading, or a version section without bullets is an error; an empty Unreleased section prints nothing and succeeds. Bullets are rendered as HTML in the Sparkle appcast, so "<" and "&" are rejected.

set -euo pipefail

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <Unreleased|X.Y.Z> [path/to/CHANGELOG.md]" >&2
    exit 2
fi

SECTION="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CHANGELOG_PATH="${2:-$SCRIPT_DIR/../../CHANGELOG.md}"

if [ ! -f "$CHANGELOG_PATH" ]; then
    echo "Error: changelog not found at $CHANGELOG_PATH" >&2
    exit 1
fi

heading_count="$(awk -v want="## $SECTION" '{ sub(/[[:space:]]+$/, "") } $0 == want { n++ } END { print n + 0 }' "$CHANGELOG_PATH")"
if [ "$heading_count" -eq 0 ]; then
    echo "Error: $CHANGELOG_PATH has no '## $SECTION' section." >&2
    exit 1
fi
if [ "$heading_count" -gt 1 ]; then
    echo "Error: $CHANGELOG_PATH has $heading_count '## $SECTION' headings; keep exactly one." >&2
    exit 1
fi

bullets="$(awk -v want="## $SECTION" '
    { sub(/[[:space:]]+$/, "") }
    /^## / { in_section = ($0 == want); next }
    in_section && /^- / { print }
' "$CHANGELOG_PATH")"

if [ -z "$bullets" ]; then
    if [ "$SECTION" = "Unreleased" ]; then
        exit 0
    fi
    echo "Error: the '## $SECTION' section of $CHANGELOG_PATH has no '- ' bullets." >&2
    exit 1
fi

if printf '%s\n' "$bullets" | grep -q '[<&]'; then
    echo "Error: the '## $SECTION' section contains '<' or '&', which would break the HTML release notes. Reword those bullets." >&2
    exit 1
fi

printf '%s\n' "$bullets"
