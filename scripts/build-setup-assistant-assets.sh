#!/bin/bash
# Build setup-assistant web assets and copy them to Swift resources.
#
# This is the canonical builder for the Setup Assistant WKWebView bundle:
#
#   web-components/SetupAssistantWebComponents →
#     client/Sources/Resources/SetupAssistantWebAssets/
#
# dev.sh and the release build pipeline should invoke this script
# before Swift builds or packages resources. Failure is loud and fatal so the
# app does not silently ship a stale setup assistant bundle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

WEB_DIR="${PROJECT_ROOT}/web-components/SetupAssistantWebComponents"
RESOURCES_DIR="${PROJECT_ROOT}/client/Sources/Resources/SetupAssistantWebAssets"
EXPECTED_HTML_REL="src/entries/setup-assistant.html"

fail() {
    echo "❌ build-setup-assistant-assets.sh: $1" >&2
    exit 1
}

if ! type -P npm >/dev/null 2>&1; then
    fail "npm not found on PATH. Install Node.js (https://nodejs.org) before running this script."
fi

# Verify the setup agent's Python menu bar catalog still matches the
# Swift source of truth (StatusBarMenuBuilder.swift) BEFORE doing any
# expensive npm work. The setup agent walks new users through the
# menu bar items by name, and if the Python catalog at
# backend/src/api/services/setup_assistant/agent_graph/menu_bar_inventory.py
# drifts away from the Swift menu, the agent confidently hallucinates
# missing items at the user. Running this here means a developer who
# touched StatusBarMenuBuilder.swift gets a fast, actionable diff
# instead of waiting through bundling and Swift compilation just to
# get a runtime user complaint about phantom menu items.
echo ""
echo "🔎 Checking setup agent menu bar inventory against StatusBarMenuBuilder.swift..."
if ! python3 "${PROJECT_ROOT}/backend/scripts/check_menu_bar_inventory.py"; then
    fail "Menu bar inventory drifted from StatusBarMenuBuilder.swift (see diff above). Update backend/src/api/services/setup_assistant/agent_graph/menu_bar_inventory.py and re-run."
fi

echo ""
echo "🔧 Building setup assistant web bundle..."
echo "   Source:      $WEB_DIR"
echo "   Staging dir: $RESOURCES_DIR"

if [ ! -d "$WEB_DIR" ]; then
    fail "Setup assistant web source directory not found at $WEB_DIR"
fi

LOGO_SOURCE="${PROJECT_ROOT}/client/Sources/Resources/Assets.xcassets/AppIcon.appiconset/icon_256x256@2x.png"
LOGO_DEST="${WEB_DIR}/public/images/basil-logo.png"

if [ ! -f "$LOGO_SOURCE" ]; then
    fail "Logo source missing at $LOGO_SOURCE.
This script is meant to be run from dev.sh or build/scripts/build_frontend.sh, both of which generate AppIcon.appiconset before calling this script.
To run this script standalone, first invoke scripts/generate_icons.py --variant=dev (or --variant=standard for production parity)."
fi

mkdir -p "$(dirname "$LOGO_DEST")"
cp "$LOGO_SOURCE" "$LOGO_DEST"
echo "🎨 Staged logo: $LOGO_DEST (from $LOGO_SOURCE)"

# Stage the curated set of onboarding-era visuals the setup agent can
# call into the conversation via show_setup_visual. The destination
# filenames here are the stable slugs the backend catalog references
# (backend/src/api/services/setup_assistant/agent_graph/setup_visual_catalog.py),
# so renaming either side requires renaming the other.
#
# Sources fall into three buckets:
#   - SetupAssistantWebComponents/setup-visual-sources/* -- capability screenshots
#   - Resources/{Dill,Paprika,StatusBar}*  -- agent + status-bar icons
#
# The named-status status-bar shots (idle, recording) are staged; the
# full T*_M*_B* matrix is intentionally NOT staged today because we
# don't have semantic mapping for the T/M/B axes. Add explicit entries
# here when those mappings are known.
SETUP_VISUALS_DEST="${WEB_DIR}/public/images/setup"
SETUP_VISUAL_SOURCE_IMAGES="${PROJECT_ROOT}/web-components/SetupAssistantWebComponents/setup-visual-sources"
RESOURCES_ROOT="${PROJECT_ROOT}/client/Sources/Resources"

mkdir -p "$SETUP_VISUALS_DEST"
echo "🎨 Generating high-resolution setup menu-bar reference icons..."
python3 - <<PY
import sys
from pathlib import Path

project_root = Path("${PROJECT_ROOT}")
sys.path.insert(0, str(project_root / "scripts"))

from generate_icons import create_icon

dest = Path("${SETUP_VISUALS_DEST}")
duke_blue = (0, 48, 135)
white = (255, 255, 255)

variants = [
    ("setup_menu_bar_idle.png", {"top": "green"}),
    ("setup_menu_bar_recording.png", {"top": "red"}),
]
for filename, dots in variants:
    icon = create_icon(
        size=176,
        bg_color=duke_blue,
        text_color=white,
        font_scale=0.72,
        dots=dots,
        is_dev_variant=False,
    )
    output = dest / filename
    icon.save(output, "PNG")
    print(f"   {filename} (generated at 176x176 for setup reference cards)")
PY

# slug|absolute_source_path
SETUP_VISUAL_ENTRIES=(
    "intro_dill_email_response.png|${SETUP_VISUAL_SOURCE_IMAGES}/01_Email_Response.png"
    "activity_capture_summary.png|${SETUP_VISUAL_SOURCE_IMAGES}/02_Activity_Summary.png"
    "voice_command_folder_analysis.png|${SETUP_VISUAL_SOURCE_IMAGES}/03_Voice_Command_Download_Folder_Analysis.png"
    "voice_command_file_find_and_merge.png|${SETUP_VISUAL_SOURCE_IMAGES}/04_Voice_Command_File_Find_and_Merge.png"
    "dill_icon.png|${RESOURCES_ROOT}/DillIcon.png"
    "paprika_icon.png|${RESOURCES_ROOT}/PaprikaIcon.png"
    "status_bar_idle.png|${RESOURCES_ROOT}/StatusBarIcon.png"
    "status_bar_recording.png|${RESOURCES_ROOT}/StatusBarIconRecording.png"
)

echo "🖼️  Staging setup visuals into $SETUP_VISUALS_DEST"
for entry in "${SETUP_VISUAL_ENTRIES[@]}"; do
    slug="${entry%%|*}"
    source_path="${entry#*|}"
    if [ ! -f "$source_path" ]; then
        fail "Setup visual source missing: $source_path
This file is referenced by setup_visual_catalog.py and must be present in client/Sources/Resources for the setup agent's show_setup_visual tool to work. If the source has moved or been renamed, update both SETUP_VISUAL_ENTRIES above and the matching entry in setup_visual_catalog.py."
    fi
    cp "$source_path" "${SETUP_VISUALS_DEST}/${slug}"
    echo "   ${slug} (from ${source_path#${PROJECT_ROOT}/})"
done

pushd "$WEB_DIR" >/dev/null

if [ ! -d "node_modules" ]; then
    echo "📦 Installing npm dependencies (no node_modules present in $WEB_DIR)..."
    npm install
fi

echo "🏗️  Running Vite build in $WEB_DIR..."
if ! npm run build; then
    popd >/dev/null
    fail "Vite build failed in $WEB_DIR. The staged bundle at $RESOURCES_DIR has NOT been updated; do not ship."
fi

DIST_DIR="$WEB_DIR/dist"
DIST_HTML="$DIST_DIR/$EXPECTED_HTML_REL"

if [ ! -d "$DIST_DIR" ]; then
    popd >/dev/null
    fail "Vite reported success but $DIST_DIR was not produced."
fi

if [ ! -f "$DIST_HTML" ]; then
    popd >/dev/null
    fail "Expected entry HTML missing after build: $DIST_HTML"
fi

DIST_JS_COUNT=$(find "$DIST_DIR/assets" -maxdepth 1 -type f -name '*.js' 2>/dev/null | wc -l | tr -d ' ')
if [ "$DIST_JS_COUNT" = "0" ]; then
    popd >/dev/null
    fail "No JS bundle found in $DIST_DIR/assets after build. Refusing to stage an empty bundle."
fi

echo "📂 Staging built assets to $RESOURCES_DIR..."
rm -rf "$RESOURCES_DIR"
mkdir -p "$RESOURCES_DIR"
cp -R "$DIST_DIR/"* "$RESOURCES_DIR/"

STAGED_HTML="$RESOURCES_DIR/$EXPECTED_HTML_REL"
if [ ! -f "$STAGED_HTML" ]; then
    popd >/dev/null
    fail "Stage step did not produce $STAGED_HTML. Resources directory is in an inconsistent state."
fi

STAGED_JS_COUNT=$(find "$RESOURCES_DIR/assets" -maxdepth 1 -type f -name '*.js' 2>/dev/null | wc -l | tr -d ' ')
if [ "$STAGED_JS_COUNT" = "0" ]; then
    popd >/dev/null
    fail "Stage step produced no JS in $RESOURCES_DIR/assets. Refusing to leave a broken staged bundle."
fi

echo "🔧 Normalizing setup assistant asset paths for WKWebView..."

rewrite_paths() {
    local file="$1"
    local prefix="$2"
    # Match `/images/` only when preceded by a quote or `(` so that
    # already-relative paths like `../../images/...` are left alone.
    sed -i '' \
        -e "s|\"/images/|\"${prefix}images/|g" \
        -e "s|'/images/|'${prefix}images/|g" \
        -e "s|\`/images/|\`${prefix}images/|g" \
        -e "s|(/images/|(${prefix}images/|g" \
        "$file"
}

count_image_refs() {
    local file="$1"
    grep -cE '["'"'"'`(]/images/' "$file" 2>/dev/null || true
}

rewrites_total=0

if [ -d "$RESOURCES_DIR/src/entries" ]; then
    while IFS= read -r f; do
        before=$(count_image_refs "$f")
        rewrite_paths "$f" "../../"
        after_neg=$(count_image_refs "$f")
        converted=$((before - after_neg))
        if [ "$converted" -gt 0 ]; then
            echo "   $(basename "$f"): rewrote $converted /images/ → ../../images/"
            rewrites_total=$((rewrites_total + converted))
        fi
    done < <(find "$RESOURCES_DIR/src/entries" -type f -name '*.html')
fi

if [ -d "$RESOURCES_DIR/assets" ]; then
    while IFS= read -r f; do
        before=$(count_image_refs "$f")
        rewrite_paths "$f" "../../"
        after_neg=$(count_image_refs "$f")
        converted=$((before - after_neg))
        if [ "$converted" -gt 0 ]; then
            echo "   $(basename "$f"): rewrote $converted /images/ → ../../images/"
            rewrites_total=$((rewrites_total + converted))
        fi
    done < <(find "$RESOURCES_DIR/assets" -type f \( -name '*.js' -o -name '*.css' \))
fi

while IFS= read -r f; do
    before=$(count_image_refs "$f")
    rewrite_paths "$f" "./"
    after_neg=$(count_image_refs "$f")
    converted=$((before - after_neg))
    if [ "$converted" -gt 0 ]; then
        echo "   $(basename "$f"): rewrote $converted /images/ → ./images/"
        rewrites_total=$((rewrites_total + converted))
    fi
done < <(find "$RESOURCES_DIR" -maxdepth 1 -type f -name '*.html')

leftover=$(grep -rEl '["'"'"'`(]/images/' "$RESOURCES_DIR" 2>/dev/null || true)
if [ -n "$leftover" ]; then
    echo "❌ build-setup-assistant-assets.sh: Path normalization left unconverted /images/ literals in:" >&2
    echo "$leftover" | while read -r f; do
        echo "❌ build-setup-assistant-assets.sh:   $f" >&2
    done
    popd >/dev/null
    exit 1
fi

if [ "$rewrites_total" -eq 0 ]; then
    echo "   No /images/ literals found (already normalized or no icon refs)."
else
    echo "   Normalized $rewrites_total path(s). No leftover /images/ literals remain."
fi

echo "✅ Setup assistant web bundle built and staged successfully:"
ls -la "$RESOURCES_DIR/assets/" | sed 's/^/   /'

popd >/dev/null

