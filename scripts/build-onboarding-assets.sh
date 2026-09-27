#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly PACKAGE_DIR="$REPO_ROOT/web-components/OnboardingWebComponents"
readonly DESTINATION_DIR="$REPO_ROOT/client/Sources/Resources/OnboardingWebAssets"

if [[ ! -f "$PACKAGE_DIR/package.json" ]]; then
    echo "Onboarding web-component package is missing: $PACKAGE_DIR" >&2
    exit 1
fi

pushd "$PACKAGE_DIR" >/dev/null
npm ci
npm run build
popd >/dev/null

if [[ ! -d "$PACKAGE_DIR/dist" ]]; then
    echo "Onboarding build produced no dist directory." >&2
    exit 1
fi

rm -rf "$DESTINATION_DIR"
mkdir -p "$DESTINATION_DIR"
cp -R "$PACKAGE_DIR/dist/." "$DESTINATION_DIR/"

BASIL_ONBOARDING_DESTINATION="$DESTINATION_DIR" python3 - <<'PY'
import os
from pathlib import Path

destination = Path(os.environ["BASIL_ONBOARDING_DESTINATION"])
replacements = (
    ('"/images/', '"../../images/'),
    ("'/images/", "'../../images/"),
    ("`/images/", "`../../images/"),
    ("(/images/", "(../../images/"),
)
for directory, patterns, prefix in (
    (destination / "src" / "entries", ("*.html",), "../../"),
    (destination / "assets", ("*.js", "*.css"), "../../"),
    (destination, ("*.html",), "./"),
):
    if not directory.exists():
        continue
    for pattern in patterns:
        for path in directory.glob(pattern):
            if directory == destination and path.parent != destination:
                continue
            text = path.read_text()
            if prefix == "./":
                text = text.replace('"/images/', '"./images/').replace("'/images/", "'./images/").replace("`/images/", "`./images/").replace("(/images/", "(./images/")
            else:
                for before, after in replacements:
                    text = text.replace(before, after)
            path.write_text(text)
PY

if rg -q '["'"'"'`(]/images/' "$DESTINATION_DIR"; then
    echo "Onboarding bundle contains unconverted root-relative image paths." >&2
    exit 1
fi
