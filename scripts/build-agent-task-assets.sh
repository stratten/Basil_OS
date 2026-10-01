#!/bin/bash
# Build every canonical app WKWebView bundle and copy it to Swift resources.
#
# This is the CANONICAL builder for WKWebView bundles shipped in the
# Swift app:
#
#   1. web-components/AgentTaskResult              →
#        client/Sources/Resources/AgentTaskWebAssets/
#   2. web-components/ScheduledRunMiniPanel     →
#        client/Sources/Resources/ScheduledRunMiniPanelAssets/
#   3. web-components/MeetingDetectedMiniPanel →
#        client/Sources/Resources/MeetingDetectedMiniPanelAssets/
#   4. web-components/AmbientSuggestionsPanel  →
#        client/Sources/Resources/AmbientSuggestionsPanelAssets/
#   5. web-components/BasilBoard →
#        client/Sources/Resources/BasilBoardWebAssets/
#   6. web-components/MeetingAssistant →
#        client/Sources/Resources/MeetingAssistantWebAssets/
#   7. web-components/AssistantSession →
#        client/Sources/Resources/AssistantSessionWebAssets/
#   8. web-components/TranscriptionWidget →
#        client/Sources/Resources/TranscriptionWidgetWebAssets/
#   9. web-components/AgentTaskCaptureInput →
#        client/Sources/Resources/AgentTaskCaptureInputWebAssets/
#   10. web-components/SetupAssistantResumeToast →
#        client/Sources/Resources/SetupAssistantResumeToastAssets/
#
# Both dev.sh and build/scripts/build_frontend.sh MUST
# invoke this script (rather than duplicating the build inline) so there is
# exactly one path that produces and stages the JS/CSS that gets bundled
# into the .app's Contents/Resources directory.
#
# Failure modes are loud and fatal on purpose: a stale staged bundle silently
# ships ancient UI into the .app, which is extremely hard to diagnose from
# the Swift side. We refuse to leave an empty staged dir on the way out.
#
# Usage: ./build-agent-task-assets.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

fail() {
    echo "❌ build-agent-task-assets.sh: $1" >&2
    exit 1
}

if ! type -P npm >/dev/null 2>&1; then
    fail "npm not found on PATH. Install Node.js (https://nodejs.org) before running this script."
fi

WEB_SYMBOL_ASSET_DIR="$PROJECT_ROOT/web-components/shared/assets/native-symbols"
REQUIRED_WEB_SYMBOL_ASSETS=(
    conversation-new.png
    conversation-sidebar.png
    conversation-sidebar-expand.png
    copy.png
    open-file.png
    show-in-folder.png
    open-preview-window.png
    open-local-web-preview.png
    analysis-action-items.png
    analysis-suggested-actions.png
    analysis-summary.png
    analysis-decisions.png
    analysis-questions.png
    analysis-sentiment.png
    analysis-custom.png
    agent-sidebar.png
    agent-close.png
    agent-collapse.png
    local-preview-refresh.png
    local-preview-send.png
    local-preview-play.png
    dill-icon.png
    assistant-close.png
    assistant-minimize.png
    assistant-collapse.png
    assistant-history.png
    assistant-mic.png
    assistant-keyboard.png
    assistant-mic-fill.png
    assistant-stop.png
    assistant-check.png
    assistant-edit.png
    assistant-cancel.png
    assistant-save.png
    assistant-refine.png
    assistant-pencil.png
    assistant-submit.png
    assistant-copy-rich.png
    assistant-copy-markdown.png
    assistant-copied.png
    assistant-sidebar.png
    assistant-search.png
    transcription-close.png
    transcription-close-fill.png
    transcription-expand.png
    transcription-minimize.png
    transcription-mic-fill.png
    transcription-record.png
    transcription-stop.png
    transcription-copy.png
    transcription-copied.png
    transcription-clear.png
    transcription-warning.png
    transcription-upload-doc.png
    transcription-upload-drop.png
    transcription-waveform.png
)
for symbol_asset in "${REQUIRED_WEB_SYMBOL_ASSETS[@]}"; do
    if [ ! -f "$WEB_SYMBOL_ASSET_DIR/$symbol_asset" ]; then
        fail "Static web symbol asset missing: $WEB_SYMBOL_ASSET_DIR/$symbol_asset. These PNGs are committed source assets exported from SF Symbols; restore the missing file(s) from version control or re-export from Xcode and commit the result."
    fi
done

# STEP 0: Regenerate processing-color defaults from the canonical Swift
# literals. This MUST run before the Vite build so the bundled JS picks up
# any change to AestheticSystem.Colors.defaultProcessing*. The generator
# overwrites backend/src/api/core/models/generated_processing_colors.py and
# both web-components/*/src/theme/generated-defaults.ts files;
# if they change it prints a WARNING to stderr so `git status` surfaces
# the drift and a developer can commit the regenerated files. If the
# generator can't parse the Swift source it exits non-zero, which under
# `set -euo pipefail` aborts the build immediately rather than silently
# shipping stale defaults.
echo ""
echo "🎨 STEP 0: Regenerating processing color defaults from Swift source..."
PYTHON_BIN=""
for candidate in python3 python; do
    if type -P "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    fail "python3 (or python) not found on PATH. Required to regenerate processing color defaults."
fi
if ! "$PYTHON_BIN" "$SCRIPT_DIR/generate_processing_color_defaults.py"; then
    fail "Processing-color generator failed. Refusing to build with stale defaults."
fi

# build_one_bundle <src_dir> <staged_dir> <expected_dist_html_relpath> [...]
#
# Generic per-bundle Vite build → stage flow. Centralizing this avoids the
# previous per-bundle copy/paste drift the comment block above warns about.
build_one_bundle() {
    local web_dir="$1"
    local resources_dir="$2"
    shift 2
    local expected_html_paths=("$@")

    echo ""
    echo "🔧 Building web bundle..."
    echo "   Source:      $web_dir"
    echo "   Staging dir: $resources_dir"

    if [ ! -d "$web_dir" ]; then
        fail "Web bundle source directory not found at $web_dir"
    fi
    if [ "${#expected_html_paths[@]}" -eq 0 ]; then
        fail "No expected HTML entries were supplied for $web_dir"
    fi

    pushd "$web_dir" >/dev/null

    if [ ! -d "node_modules" ]; then
        echo "📦 Installing npm dependencies (no node_modules present in $web_dir)..."
        npm install
    fi

    echo "🏗️  Running Vite build in $web_dir..."
    if ! npm run build; then
        popd >/dev/null
        fail "Vite build failed in $web_dir. The staged bundle at $resources_dir has NOT been updated; do not ship."
    fi

    local dist_dir="$web_dir/dist"

    if [ ! -d "$dist_dir" ]; then
        popd >/dev/null
        fail "Vite reported success but $dist_dir was not produced."
    fi
    for html_rel_path in "${expected_html_paths[@]}"; do
        if [ ! -f "$dist_dir/$html_rel_path" ]; then
            popd >/dev/null
            fail "Expected entry HTML missing after build: $dist_dir/$html_rel_path"
        fi
    done
    local dist_js_count
    dist_js_count=$(find "$dist_dir/assets" -maxdepth 1 -type f -name '*.js' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$dist_js_count" = "0" ]; then
        popd >/dev/null
        fail "No JS bundle found in $dist_dir/assets after build. Refusing to stage an empty bundle."
    fi

    echo "📂 Staging built assets to $resources_dir..."
    rm -rf "$resources_dir"
    mkdir -p "$resources_dir"
    cp -R "$dist_dir/"* "$resources_dir/"

    for html_rel_path in "${expected_html_paths[@]}"; do
        if [ ! -f "$resources_dir/$html_rel_path" ]; then
            popd >/dev/null
            fail "Stage step did not produce $resources_dir/$html_rel_path. Resources directory is in an inconsistent state."
        fi
    done
    local staged_js_count
    staged_js_count=$(find "$resources_dir/assets" -maxdepth 1 -type f -name '*.js' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$staged_js_count" = "0" ]; then
        popd >/dev/null
        fail "Stage step produced no JS in $resources_dir/assets. Refusing to leave a broken staged bundle."
    fi

    echo "✅ Built and staged successfully:"
    ls -la "$resources_dir/assets/" | sed 's/^/   /'

    popd >/dev/null
}

build_one_bundle \
    "$PROJECT_ROOT/web-components/AgentTaskResult" \
    "$PROJECT_ROOT/client/Sources/Resources/AgentTaskWebAssets" \
    "src/entries/agent-task-result.html" \
    "src/entries/local-web-preview.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/ScheduledRunMiniPanel" \
    "$PROJECT_ROOT/client/Sources/Resources/ScheduledRunMiniPanelAssets" \
    "src/entries/scheduled-run-mini-panel.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/ModelDownloadMiniPanel" \
    "$PROJECT_ROOT/client/Sources/Resources/ModelDownloadMiniPanelAssets" \
    "src/entries/model-download-mini-panel.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/PowerUserGuidePanel" \
    "$PROJECT_ROOT/client/Sources/Resources/PowerUserGuidePanelAssets" \
    "src/entries/power-user-guide-panel.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/SetupAssistantResumeToast" \
    "$PROJECT_ROOT/client/Sources/Resources/SetupAssistantResumeToastAssets" \
    "src/entries/setup-assistant-resume-toast.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/MeetingDetectedMiniPanel" \
    "$PROJECT_ROOT/client/Sources/Resources/MeetingDetectedMiniPanelAssets" \
    "src/entries/meeting-detected-mini-panel.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/AmbientSuggestionsPanel" \
    "$PROJECT_ROOT/client/Sources/Resources/AmbientSuggestionsPanelAssets" \
    "src/entries/ambient-suggestions-panel.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/BasilBoard" \
    "$PROJECT_ROOT/client/Sources/Resources/BasilBoardWebAssets" \
    "src/entries/basil-board.html" \
    "src/entries/conversation.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/MeetingAssistant" \
    "$PROJECT_ROOT/client/Sources/Resources/MeetingAssistantWebAssets" \
    "src/entries/meeting-assistant.html" \
    "src/entries/meeting-analysis.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/AssistantSession" \
    "$PROJECT_ROOT/client/Sources/Resources/AssistantSessionWebAssets" \
    "src/entries/assistant-session.html" \
    "src/entries/assistant-output-history.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/TranscriptionWidget" \
    "$PROJECT_ROOT/client/Sources/Resources/TranscriptionWidgetWebAssets" \
    "src/entries/transcription-widget.html" \
    "src/entries/audio-file-upload.html"

build_one_bundle \
    "$PROJECT_ROOT/web-components/AgentTaskCaptureInput" \
    "$PROJECT_ROOT/client/Sources/Resources/AgentTaskCaptureInputWebAssets" \
    "src/entries/agent-task-capture-input.html"

echo ""
echo "✅ All WKWebView bundles built and staged successfully."
