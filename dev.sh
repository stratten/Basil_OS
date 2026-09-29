#!/usr/bin/env bash
# Run from the repository root: ./dev.sh [--no-clean] [--zombies|--no-zombies]
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CLIENT_DIR="$REPO_ROOT/client"
cd "$CLIENT_DIR"

# Global variables
BACKEND_STARTED=false
BACKEND_DIR="$REPO_ROOT/backend"
FFMPEG_LGPL_PREFIX="${BASIL_FFMPEG_PREFIX:-$REPO_ROOT/build/third_party/ffmpeg-lgpl}"
FFMPEG_LGPL_BUILDER="$REPO_ROOT/build/scripts/build_ffmpeg_lgpl.sh"
SCREEN_RECORDING_GRANTED=false
SKIP_CLEAN=false # New variable to control cleaning
ENABLE_ZOMBIES=false
PRESERVE_BACKEND_ON_EXIT=false
CLIENT_CRASH_RESTART_LIMIT=3
CLIENT_CRASH_RESTART_DELAYS=(1 2 4)
INTERRUPTED=false

# Parse instruction line arguments
for arg in "$@"
do
    case $arg in
        --no-clean)
        SKIP_CLEAN=true
        shift # Remove --no-clean from processing
        ;;
        --zombies)
        ENABLE_ZOMBIES=true
        shift # Remove --zombies from processing
        ;;
        --no-zombies)
        ENABLE_ZOMBIES=false
        shift # Remove --no-zombies from processing
        ;;
    esac
done

echo "🚀 Building Basil Client..."

# Diagnostics helper: prefixes lines with a UTC timestamp + dev.sh's PID +
# its parent PID. The 'fork: Resource temporarily unavailable' symptom
# observed in the production logs is consistent with the OS process
# table being saturated by dev/parent process churn, so every backend
# spawn / cleanup decision below is annotated with this header so a log
# reviewer can correlate spawn events to the originating shell instance.
dev_log() {
    local label="$1"
    shift
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[dev.sh][$ts][pid=$$ ppid=$PPID][$label] $*"
}

# Find Python executable
PYTHON_CMD=""
if type -P python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif type -P python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Error: Python not found. Please install Python 3."
    exit 1
fi

echo "🐍 Using Python: $($PYTHON_CMD --version)"

if [ ! -x "$FFMPEG_LGPL_PREFIX/bin/ffmpeg" ]; then
    echo "🎬 Building the verified LGPL FFmpeg dependency..."
    if ! bash "$FFMPEG_LGPL_BUILDER" "$FFMPEG_LGPL_PREFIX"; then
        echo "❌ Error: Could not build LGPL FFmpeg."
        exit 1
    fi
fi
if ! "$FFMPEG_LGPL_PREFIX/bin/ffmpeg" -version 2>&1 | grep --quiet -- '--disable-gpl'; then
    echo "❌ Error: FFmpeg at $FFMPEG_LGPL_PREFIX is not configured with --disable-gpl."
    exit 1
fi
if "$FFMPEG_LGPL_PREFIX/bin/ffmpeg" -version 2>&1 | grep --quiet -- '--enable-gpl'; then
    echo "❌ Error: FFmpeg at $FFMPEG_LGPL_PREFIX is GPL-enabled."
    exit 1
fi
echo "✅ Using LGPL FFmpeg: $FFMPEG_LGPL_PREFIX/bin/ffmpeg"

# Clean up any existing backend processes and state files
echo "🧹 Cleaning up any existing backend processes..."
pkill -f "uvicorn.*api.main:app" || true
pkill -f "python.*api.main" || true
pkill -f "python -m api.main" || true
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9 2>/dev/null || true
rm -f ../.backend.pid ../.server_port

# Kill any dev BasilClient.app instances left over from a previous dev.sh run.
# launch_client() below always starts a fresh process without checking for one
# already running, so without this every re-run accumulates another stale
# instance (each holding its own now-outdated compiled code) instead of
# replacing it. This only matches the .build/debug dev bundle path, never the
# packaged /Applications build.
echo "🧹 Cleaning up any existing dev BasilClient app instances..."
pkill -f "\.build/debug/BasilClient\.app/Contents/MacOS/BasilClient" 2>/dev/null || true

# Huey task DB / PID cleanup intentionally omitted: Huey was removed in Phase 1
# of the Huey-removal plan. Background work (model downloads, capture cleanup)
# now lives inside the FastAPI process; there is no separate consumer to kill.

# Function to cleanup processes
cleanup() {
    echo "🧹 Cleaning up processes..."

    # Kill backend if running
    if [ -f ../.backend.pid ]; then
        local pid=$(cat ../.backend.pid)
        if ps -p $pid > /dev/null 2>&1; then
            echo "🛑 Stopping backend process (PID: $pid)..."
            kill -TERM $pid 2>/dev/null || kill -KILL $pid 2>/dev/null || true
        fi
        rm -f ../.backend.pid
    fi

    # More aggressive cleanup of any remaining processes
    echo "🧹 Performing thorough process cleanup..."

    # Kill any Python processes related to our app
    pkill -f "uvicorn.*api.main:app" 2>/dev/null || true
    pkill -f "python.*api.main" 2>/dev/null || true
    pkill -f "python -m api.main" 2>/dev/null || true

    # Kill any processes using our ports
    for port in $(seq 8000 8010); do
        echo "🔍 Checking port $port..."
        lsof -i :$port | grep LISTEN | awk '{print $2}' | xargs kill -9 2>/dev/null || true
    done

    # Force kill any Python processes that might be related to our app
    ps aux | grep -E "python.*(api.main|uvicorn)" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true

    # Remove state files
    rm -f ../.server_port
    rm -f ../.backend.pid

    echo "✨ Cleanup complete"
}

clean_swift_build_artifacts() {
    echo "🧹 Cleaning Swift package state..."
    swift package clean 2>/dev/null || echo "⚠️ swift package clean failed, continuing with filesystem cleanup"

    if [ ! -d ".build" ]; then
        swift package reset 2>/dev/null || echo "⚠️ swift package reset failed, continuing because .build is already absent"
        return 0
    fi

    local cleanup_dir=".build.cleanup.$(date +%s).$$"
    if mv .build "$cleanup_dir" 2>/dev/null; then
        echo "🧹 Moved .build to $cleanup_dir for best-effort deletion"
        rm -rf "$cleanup_dir" 2>/dev/null || {
            echo "⚠️ Deferred Swift index cleanup raced with SourceKit; removing index-build separately"
            rm -rf "$cleanup_dir/index-build" 2>/dev/null || true
            rm -rf "$cleanup_dir" 2>/dev/null || echo "⚠️ Could not fully remove $cleanup_dir; continuing because .build was moved aside"
        }
        swift package reset 2>/dev/null || echo "⚠️ swift package reset failed after moving .build aside; continuing"
        return 0
    fi

    echo "⚠️ Could not move .build; attempting in-place cleanup"
    rm -rf .build 2>/dev/null || true
    rm -rf .build/index-build 2>/dev/null || true

    if [ -d ".build/debug" ] || [ -d ".build/arm64-apple-macosx/debug" ]; then
        echo "❌ Failed to remove Swift build outputs from .build"
        return 1
    fi

    if [ -d ".build" ]; then
        echo "⚠️ Only non-build Swift cache data remains under .build; continuing"
    fi

    swift package reset 2>/dev/null || echo "⚠️ swift package reset failed after in-place cleanup; continuing"
}

# Register cleanup handler
trap cleanup EXIT INT TERM

# Initial cleanup
cleanup

# Start Python backend
echo "🐍 Starting Python backend..."

# Check for Poetry environment
if [ ! -f "$REPO_ROOT/poetry.lock" ]; then
    echo "❌ Error: Poetry lock file not found at $REPO_ROOT/poetry.lock"
    echo "Please ensure the Python backend is properly set up with Poetry"
    exit 1
fi

cd "$BACKEND_DIR"

# Ensure Poetry is installed
if ! type -P poetry &> /dev/null; then
    echo "📦 Installing Poetry..."
    curl -sSL https://install.python-poetry.org | python3 -
fi

# Install dependencies if needed
echo "📦 Checking Python dependencies..."
poetry install

# (Huey consumer launch removed in Phase 1 of the Huey-removal plan.
# Model downloads + capture cleanup now run inside the same uvicorn process.)

# Function to check if a port is available (matching start_backend.sh)
check_port() {
    local port_to_check=$1
    if nc -z localhost $port_to_check 2>/dev/null; then
        return 1 # Port is in use
    else
        return 0 # Port is available
    fi
}

# Find available port (exactly like start_backend.sh)
START_PORT=8000
MAX_PORT_ATTEMPTS=10
FOUND_PORT=""

echo "🔍 Searching for an available port starting from $START_PORT..."
for i in $(seq 0 $MAX_PORT_ATTEMPTS); do
    CURRENT_PORT=$((START_PORT + i))
    if check_port $CURRENT_PORT; then
        PORT=$CURRENT_PORT
        FOUND_PORT="true"
        echo "✅ Port $PORT is available."
        break
    else
        echo "⚠️ Port $CURRENT_PORT is in use."
    fi
done

if [ -z "$FOUND_PORT" ]; then
    echo "❌ Error: Could not find an available port in the range $START_PORT-$((START_PORT + MAX_PORT_ATTEMPTS))."
    exit 1
fi

# Logging setup for uvicorn
LOG_DIR="../zz. Logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/uvicorn.log"

# Start the server using Poetry with uvicorn module (matching start_backend.sh approach)
echo "🚀 Starting backend with Poetry on port $PORT (logging to $LOG_FILE)"

# Set up a clean PATH that matches the packaged environment (no Homebrew paths)
# But include Poetry's location for development
POETRY_PATH=""
if type -P poetry &> /dev/null; then
    POETRY_PATH=$(dirname "$(which poetry)")
    echo "📦 Found Poetry at: $POETRY_PATH"
fi

CLEAN_PATH="$FFMPEG_LGPL_PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
if [ -n "$POETRY_PATH" ]; then
    CLEAN_PATH="$POETRY_PATH:$CLEAN_PATH"
fi

dev_log backend "Spawning initial uvicorn (port=$PORT, reason=initial_start)"
PYTHONUNBUFFERED=1 QT_MAC_DISABLE_MENUBAR=1 NSApplicationActivationPolicy=1 PYTHONPATH="$(pwd)/src:$(pwd)" \
  PATH="$CLEAN_PATH" poetry run python -m uvicorn api.main:app --host 127.0.0.1 --port $PORT --log-level debug --use-colors 2>&1 | tee -a "$LOG_FILE" &

INITIAL_BACKEND_PID=$!
echo $INITIAL_BACKEND_PID > ../.backend.pid
dev_log backend "Recorded initial backend PID=$INITIAL_BACKEND_PID"

# Write port to a file for the Swift client
echo $PORT > ../.server_port

cd - > /dev/null

# Generate DEV VARIANT icons before building the Swift app
echo "🎨 Generating DEV VARIANT icons with circular runtime Dock icon support..."
if ! "$PYTHON_CMD" "$REPO_ROOT/scripts/generate_icons.py" --variant=dev; then
    echo "❌ Error: Failed to generate DEV VARIANT icons. Please check scripts/generate_icons.py"
    exit 1
fi
echo "✅ DEV VARIANT icons generated."

# Build agent-task web components.
#
# This is the ONLY supported path for refreshing the staged WKWebView bundle
# at client/Sources/Resources/AgentTaskWebAssets/. If this step is
# skipped or silently fails, the Swift build will copy a stale bundle into
# .app/Contents/Resources/ and the running app will load ancient UI with no
# indication anything is wrong (we have been bitten by this).
#
# Therefore: a missing OR failing canonical build script is FATAL here.
echo "🌐 Building agent-task web components..."
AGENT_TASK_BUILD_SCRIPT="$REPO_ROOT/scripts/build-agent-task-assets.sh"
if [ ! -f "$AGENT_TASK_BUILD_SCRIPT" ]; then
    echo "❌ ERROR: Canonical asset builder not found at $AGENT_TASK_BUILD_SCRIPT"
    echo "   Refusing to launch with a potentially stale staged WKWebView bundle."
    exit 1
fi
if ! bash "$AGENT_TASK_BUILD_SCRIPT"; then
    echo "❌ ERROR: Agent-task web components build failed."
    echo "   The staged bundle at client/Sources/Resources/AgentTaskWebAssets"
    echo "   may be stale or inconsistent. Aborting before Swift packages a bad bundle."
    exit 1
fi
STAGED_WEB_ASSETS_DIR="Sources/Resources/AgentTaskWebAssets/assets"
if [ ! -d "$STAGED_WEB_ASSETS_DIR" ] || [ -z "$(ls -A "$STAGED_WEB_ASSETS_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_WEB_ASSETS_DIR is empty/missing."
    exit 1
fi
STAGED_MINI_PANEL_DIR="Sources/Resources/ScheduledRunMiniPanelAssets/assets"
if [ ! -d "$STAGED_MINI_PANEL_DIR" ] || [ -z "$(ls -A "$STAGED_MINI_PANEL_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MINI_PANEL_DIR is empty/missing."
    exit 1
fi
STAGED_MODEL_DOWNLOAD_PANEL_DIR="Sources/Resources/ModelDownloadMiniPanelAssets/assets"
if [ ! -d "$STAGED_MODEL_DOWNLOAD_PANEL_DIR" ] || [ -z "$(ls -A "$STAGED_MODEL_DOWNLOAD_PANEL_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MODEL_DOWNLOAD_PANEL_DIR is empty/missing."
    exit 1
fi
STAGED_MODEL_DOWNLOAD_PANEL_ENTRY="Sources/Resources/ModelDownloadMiniPanelAssets/src/entries/model-download-mini-panel.html"
if [ ! -f "$STAGED_MODEL_DOWNLOAD_PANEL_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MODEL_DOWNLOAD_PANEL_ENTRY is missing."
    exit 1
fi
STAGED_POWER_USER_GUIDE_PANEL_DIR="Sources/Resources/PowerUserGuidePanelAssets/assets"
if [ ! -d "$STAGED_POWER_USER_GUIDE_PANEL_DIR" ] || [ -z "$(ls -A "$STAGED_POWER_USER_GUIDE_PANEL_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_POWER_USER_GUIDE_PANEL_DIR is empty/missing."
    exit 1
fi
STAGED_POWER_USER_GUIDE_PANEL_ENTRY="Sources/Resources/PowerUserGuidePanelAssets/src/entries/power-user-guide-panel.html"
if [ ! -f "$STAGED_POWER_USER_GUIDE_PANEL_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_POWER_USER_GUIDE_PANEL_ENTRY is missing."
    exit 1
fi
STAGED_SETUP_ASSISTANT_RESUME_TOAST_DIR="Sources/Resources/SetupAssistantResumeToastAssets/assets"
if [ ! -d "$STAGED_SETUP_ASSISTANT_RESUME_TOAST_DIR" ] || [ -z "$(ls -A "$STAGED_SETUP_ASSISTANT_RESUME_TOAST_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_SETUP_ASSISTANT_RESUME_TOAST_DIR is empty/missing."
    exit 1
fi
STAGED_SETUP_ASSISTANT_RESUME_TOAST_ENTRY="Sources/Resources/SetupAssistantResumeToastAssets/src/entries/setup-assistant-resume-toast.html"
if [ ! -f "$STAGED_SETUP_ASSISTANT_RESUME_TOAST_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_SETUP_ASSISTANT_RESUME_TOAST_ENTRY is missing."
    exit 1
fi
STAGED_MEETING_PANEL_DIR="Sources/Resources/MeetingDetectedMiniPanelAssets/assets"
if [ ! -d "$STAGED_MEETING_PANEL_DIR" ] || [ -z "$(ls -A "$STAGED_MEETING_PANEL_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MEETING_PANEL_DIR is empty/missing."
    exit 1
fi
STAGED_MEETING_ASSISTANT_DIR="Sources/Resources/MeetingAssistantWebAssets/assets"
if [ ! -d "$STAGED_MEETING_ASSISTANT_DIR" ] || [ -z "$(ls -A "$STAGED_MEETING_ASSISTANT_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MEETING_ASSISTANT_DIR is empty/missing."
    exit 1
fi
STAGED_MEETING_ASSISTANT_ENTRY="Sources/Resources/MeetingAssistantWebAssets/src/entries/meeting-assistant.html"
if [ ! -f "$STAGED_MEETING_ASSISTANT_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MEETING_ASSISTANT_ENTRY is missing."
    exit 1
fi
STAGED_MEETING_ANALYSIS_ENTRY="Sources/Resources/MeetingAssistantWebAssets/src/entries/meeting-analysis.html"
if [ ! -f "$STAGED_MEETING_ANALYSIS_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_MEETING_ANALYSIS_ENTRY is missing."
    exit 1
fi
STAGED_ASSISTANT_SESSION_DIR="Sources/Resources/AssistantSessionWebAssets/assets"
if [ ! -d "$STAGED_ASSISTANT_SESSION_DIR" ] || [ -z "$(ls -A "$STAGED_ASSISTANT_SESSION_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_ASSISTANT_SESSION_DIR is empty/missing."
    exit 1
fi
STAGED_ASSISTANT_SESSION_ENTRY="Sources/Resources/AssistantSessionWebAssets/src/entries/assistant-session.html"
if [ ! -f "$STAGED_ASSISTANT_SESSION_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_ASSISTANT_SESSION_ENTRY is missing."
    exit 1
fi
STAGED_ASSISTANT_HISTORY_ENTRY="Sources/Resources/AssistantSessionWebAssets/src/entries/assistant-output-history.html"
if [ ! -f "$STAGED_ASSISTANT_HISTORY_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_ASSISTANT_HISTORY_ENTRY is missing."
    exit 1
fi
STAGED_TRANSCRIPTION_WIDGET_DIR="Sources/Resources/TranscriptionWidgetWebAssets/assets"
if [ ! -d "$STAGED_TRANSCRIPTION_WIDGET_DIR" ] || [ -z "$(ls -A "$STAGED_TRANSCRIPTION_WIDGET_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_TRANSCRIPTION_WIDGET_DIR is empty/missing."
    exit 1
fi
STAGED_TRANSCRIPTION_WIDGET_ENTRY="Sources/Resources/TranscriptionWidgetWebAssets/src/entries/transcription-widget.html"
if [ ! -f "$STAGED_TRANSCRIPTION_WIDGET_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_TRANSCRIPTION_WIDGET_ENTRY is missing."
    exit 1
fi
STAGED_AUDIO_UPLOAD_ENTRY="Sources/Resources/TranscriptionWidgetWebAssets/src/entries/audio-file-upload.html"
if [ ! -f "$STAGED_AUDIO_UPLOAD_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_AUDIO_UPLOAD_ENTRY is missing."
    exit 1
fi
STAGED_AGENT_TASK_CAPTURE_DIR="Sources/Resources/AgentTaskCaptureInputWebAssets/assets"
if [ ! -d "$STAGED_AGENT_TASK_CAPTURE_DIR" ] || [ -z "$(ls -A "$STAGED_AGENT_TASK_CAPTURE_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_AGENT_TASK_CAPTURE_DIR is empty/missing."
    exit 1
fi
STAGED_AGENT_TASK_CAPTURE_ENTRY="Sources/Resources/AgentTaskCaptureInputWebAssets/src/entries/agent-task-capture-input.html"
if [ ! -f "$STAGED_AGENT_TASK_CAPTURE_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_AGENT_TASK_CAPTURE_ENTRY is missing."
    exit 1
fi
STAGED_AMBIENT_PANEL_DIR="Sources/Resources/AmbientSuggestionsPanelAssets/assets"
if [ ! -d "$STAGED_AMBIENT_PANEL_DIR" ] || [ -z "$(ls -A "$STAGED_AMBIENT_PANEL_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_AMBIENT_PANEL_DIR is empty/missing."
    exit 1
fi
STAGED_BASIL_BOARD_DIR="Sources/Resources/BasilBoardWebAssets/assets"
if [ ! -d "$STAGED_BASIL_BOARD_DIR" ] || [ -z "$(ls -A "$STAGED_BASIL_BOARD_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_BASIL_BOARD_DIR is empty/missing."
    exit 1
fi
STAGED_BASIL_BOARD_ENTRY="Sources/Resources/BasilBoardWebAssets/src/entries/basil-board.html"
if [ ! -f "$STAGED_BASIL_BOARD_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_BASIL_BOARD_ENTRY is missing."
    exit 1
fi
STAGED_CONVERSATION_ENTRY="Sources/Resources/BasilBoardWebAssets/src/entries/conversation.html"
if [ ! -f "$STAGED_CONVERSATION_ENTRY" ]; then
    echo "❌ ERROR: Asset build reported success but $STAGED_CONVERSATION_ENTRY is missing."
    exit 1
fi

echo "📦 Staged WKWebView bundles ready:"
ls -la "$STAGED_WEB_ASSETS_DIR"
ls -la "$STAGED_MINI_PANEL_DIR"
ls -la "$STAGED_MODEL_DOWNLOAD_PANEL_DIR"
ls -la "$STAGED_MEETING_PANEL_DIR"
ls -la "$STAGED_AMBIENT_PANEL_DIR"
ls -la "$STAGED_BASIL_BOARD_DIR"
ls -la "$STAGED_MEETING_ASSISTANT_DIR"

# Build setup assistant web components.
#
# Same canonical-build requirement as the other WKWebView bundles: the staged
# resources are what Swift packages into the development app, so the dev flow
# must fail loudly if the setup assistant bundle cannot be refreshed.
echo "🌐 Building setup assistant web components..."
SETUP_ASSISTANT_BUILD_SCRIPT="$REPO_ROOT/scripts/build-setup-assistant-assets.sh"
if [ ! -f "$SETUP_ASSISTANT_BUILD_SCRIPT" ]; then
    echo "❌ ERROR: Canonical setup assistant asset builder not found at $SETUP_ASSISTANT_BUILD_SCRIPT"
    echo "   Refusing to launch with a potentially stale SetupAssistantWebAssets bundle."
    exit 1
fi
if ! bash "$SETUP_ASSISTANT_BUILD_SCRIPT"; then
    echo "❌ ERROR: Setup assistant web components build failed."
    echo "   The staged bundle at client/Sources/Resources/SetupAssistantWebAssets"
    echo "   may be stale or inconsistent. Aborting before Swift packages a bad bundle."
    exit 1
fi
STAGED_SETUP_ASSISTANT_DIR="Sources/Resources/SetupAssistantWebAssets"
if [ ! -d "$STAGED_SETUP_ASSISTANT_DIR" ] || [ -z "$(ls -A "$STAGED_SETUP_ASSISTANT_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Setup assistant asset build reported success but $STAGED_SETUP_ASSISTANT_DIR is empty/missing."
    exit 1
fi
echo "📦 Staged setup assistant WKWebView bundle ready:"
ls -la "$STAGED_SETUP_ASSISTANT_DIR"

# Build profile editor web components.
#
# Same canonical-build requirement as the other WKWebView bundles: the staged
# resources at client/Sources/Resources/ProfileMemorySkillsEditorWebAssets/
# are what Swift packages into the development app and what the Profile Editor
# webview (launched from the Memory and Skills settings subtabs) loads at
# runtime. If we skip this step, edits to web-components/
# ProfileMemorySkillsEditor/ never reach the running dev build and the editor
# silently runs the previous bundle.
echo "🌐 Building profile editor web components..."
PROFILE_EDITOR_BUILD_SCRIPT="$REPO_ROOT/scripts/build-profile-editor-assets.sh"
if [ ! -f "$PROFILE_EDITOR_BUILD_SCRIPT" ]; then
    echo "❌ ERROR: Canonical profile editor asset builder not found at $PROFILE_EDITOR_BUILD_SCRIPT"
    echo "   Refusing to launch with a potentially stale ProfileMemorySkillsEditorWebAssets bundle."
    exit 1
fi
if ! bash "$PROFILE_EDITOR_BUILD_SCRIPT"; then
    echo "❌ ERROR: Profile editor web components build failed."
    echo "   The staged bundle at client/Sources/Resources/ProfileMemorySkillsEditorWebAssets"
    echo "   may be stale or inconsistent. Aborting before Swift packages a bad bundle."
    exit 1
fi
STAGED_PROFILE_EDITOR_DIR="Sources/Resources/ProfileMemorySkillsEditorWebAssets"
if [ ! -d "$STAGED_PROFILE_EDITOR_DIR" ] || [ -z "$(ls -A "$STAGED_PROFILE_EDITOR_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Profile editor asset build reported success but $STAGED_PROFILE_EDITOR_DIR is empty/missing."
    exit 1
fi
echo "📦 Staged profile editor WKWebView bundle ready:"
ls -la "$STAGED_PROFILE_EDITOR_DIR"

# Build settings appearance web components.
#
# Same canonical-build requirement as the other WKWebView bundles: the staged
# resources at client/Sources/Resources/SettingsWebAssets/ are what Swift
# packages into the development app and what the "Settings - React" window
# (opened from its own top-level menu bar item) loads at runtime. If we skip
# this step, edits to web-components/SettingsWebComponents/ never
# reach the running dev build and the window silently runs the previous
# bundle.
echo "🌐 Building settings appearance web components..."
SETTINGS_APPEARANCE_BUILD_SCRIPT="$REPO_ROOT/scripts/build-settings-appearance-assets.sh"
if [ ! -f "$SETTINGS_APPEARANCE_BUILD_SCRIPT" ]; then
    echo "❌ ERROR: Canonical settings appearance asset builder not found at $SETTINGS_APPEARANCE_BUILD_SCRIPT"
    echo "   Refusing to launch with a potentially stale SettingsWebAssets bundle."
    exit 1
fi
if ! bash "$SETTINGS_APPEARANCE_BUILD_SCRIPT"; then
    echo "❌ ERROR: Settings appearance web components build failed."
    echo "   The staged bundle at client/Sources/Resources/SettingsWebAssets"
    echo "   may be stale or inconsistent. Aborting before Swift packages a bad bundle."
    exit 1
fi
STAGED_SETTINGS_APPEARANCE_DIR="Sources/Resources/SettingsWebAssets"
if [ ! -d "$STAGED_SETTINGS_APPEARANCE_DIR" ] || [ -z "$(ls -A "$STAGED_SETTINGS_APPEARANCE_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Settings appearance asset build reported success but $STAGED_SETTINGS_APPEARANCE_DIR is empty/missing."
    exit 1
fi
echo "📦 Staged settings appearance WKWebView bundle ready:"
ls -la "$STAGED_SETTINGS_APPEARANCE_DIR"

# Build skill reconciliation workspace web components.
#
# Same canonical-build requirement as the other WKWebView bundles: the staged
# resources at client/Sources/Resources/SkillReconciliationWorkspaceWebAssets/
# are what Swift packages into the development app and what the Skill
# Reconciliation Workspace webview (launched from the Skills settings subtab)
# loads at runtime. If we skip this step, edits to web-components/
# SkillReconciliationWorkspace/ never reach the running dev build and the
# workspace silently runs the previous bundle.
echo "🌐 Building skill reconciliation workspace web components..."
RECONCILIATION_BUILD_SCRIPT="$REPO_ROOT/scripts/build-skill-reconciliation-workspace-assets.sh"
if [ ! -f "$RECONCILIATION_BUILD_SCRIPT" ]; then
    echo "❌ ERROR: Canonical skill reconciliation asset builder not found at $RECONCILIATION_BUILD_SCRIPT"
    echo "   Refusing to launch with a potentially stale SkillReconciliationWorkspaceWebAssets bundle."
    exit 1
fi
if ! bash "$RECONCILIATION_BUILD_SCRIPT"; then
    echo "❌ ERROR: Skill reconciliation workspace web components build failed."
    echo "   The staged bundle at client/Sources/Resources/SkillReconciliationWorkspaceWebAssets"
    echo "   may be stale or inconsistent. Aborting before Swift packages a bad bundle."
    exit 1
fi
STAGED_RECONCILIATION_DIR="Sources/Resources/SkillReconciliationWorkspaceWebAssets"
if [ ! -d "$STAGED_RECONCILIATION_DIR" ] || [ -z "$(ls -A "$STAGED_RECONCILIATION_DIR" 2>/dev/null)" ]; then
    echo "❌ ERROR: Skill reconciliation asset build reported success but $STAGED_RECONCILIATION_DIR is empty/missing."
    exit 1
fi
echo "📦 Staged skill reconciliation WKWebView bundle ready:"
ls -la "$STAGED_RECONCILIATION_DIR"

# Clean previous build artifacts (full clean of .build)
if [ "$SKIP_CLEAN" = false ] ; then
    echo "🧹 Cleaning previous build artifacts (full clean of .build)..."
    clean_swift_build_artifacts
else
    echo "⏩ Skipping build artifact cleaning as per --no-clean flag."
fi

echo "🏗️ Building application (warnings will be displayed by default)..."
echo "# To suppress warnings, comment out the active 'swift build' lines below and uncomment the ones with '-Xswiftc -suppress-warnings'."

# Original build attempt with warning suppression (now commented out)
# if ! swift build -c debug -Xswiftc -suppress-warnings; then
# Active build attempt (warnings will be displayed)
if ! swift build -c debug; then
    echo "⚠️ Initial build failed. Performing aggressive clean and retrying..."
    clean_swift_build_artifacts
    rm -rf .swiftpm Package.resolved
    swift package resolve
    # Original retry build attempt with warning suppression (now commented out)
    # if ! swift build -c debug -Xswiftc -suppress-warnings; then
    # Active retry build attempt (warnings will be displayed)
    if ! swift build -c debug; then
        echo "❌ Build failed after aggressive clean. Please check your dependencies."
        exit 1
    fi
fi

# Clean up stray Swift compiler artifacts from root directory
# These can appear from SourceKit-LSP (language server) or Xcode indexing
echo "🧹 Cleaning up stray Swift compiler artifacts..."
find . -maxdepth 1 -name "*.o" -delete 2>/dev/null || true
find . -maxdepth 1 -name "*.d" -delete 2>/dev/null || true
find . -maxdepth 1 -name "*.swiftdeps" -delete 2>/dev/null || true

# Create application bundle structure
echo "📁 Creating application bundle structure..."
APP_DIR=".build/debug/BasilClient.app"
mkdir -p "$APP_DIR/Contents/"{MacOS,Resources}

# Copy Info.plist
echo "📄 Copying Info.plist..."
cp Sources/Support/Info.plist "$APP_DIR/Contents/"

# Copy the executable
echo "📦 Copying executable..."
if [ -f ".build/debug/BasilClient" ]; then
    cp ".build/debug/BasilClient" "$APP_DIR/Contents/MacOS/"
else
    echo "❌ Error: Executable not found at .build/debug/BasilClient"
    exit 1
fi

# Copy Sparkle.framework into the app bundle
echo "📦 Embedding Sparkle.framework..."
mkdir -p "$APP_DIR/Contents/Frameworks"
SPARKLE_FRAMEWORK=".build/arm64-apple-macosx/debug/Sparkle.framework"
if [ -d "$SPARKLE_FRAMEWORK" ]; then
    cp -R "$SPARKLE_FRAMEWORK" "$APP_DIR/Contents/Frameworks/"
    echo "✅ Sparkle.framework embedded successfully"
else
    echo "⚠️ Warning: Sparkle.framework not found at $SPARKLE_FRAMEWORK"
    echo "   The app will crash at launch without it. Run 'swift build' first."
fi

# Add Frameworks rpath so the executable can find Sparkle.framework at runtime
echo "🔗 Adding Frameworks rpath to executable..."
install_name_tool -add_rpath "@loader_path/../Frameworks" "$APP_DIR/Contents/MacOS/BasilClient" 2>/dev/null || true
echo "✅ Frameworks rpath added"

# Create Resources directory if it doesn't exist
echo "📦 Setting up resources..."
mkdir -p "$APP_DIR/Contents/Resources"

# Check if we have the icon files
ICON_SOURCE_DIR="Sources/Resources/Assets.xcassets/AppIcon.appiconset"
if [ -d "$ICON_SOURCE_DIR" ]; then
    echo "🎨 Processing application icons..."
    ICON_DIR=".build/AppIcon.iconset"
    mkdir -p "$ICON_DIR"

    # Simple icon copying
    for size in 16 32 64 128 256 512 1024; do
        # Copy regular size
        if [ -f "$ICON_SOURCE_DIR/icon_${size}x${size}.png" ]; then
            cp "$ICON_SOURCE_DIR/icon_${size}x${size}.png" "$ICON_DIR/icon_${size}x${size}.png"
        fi
        # Copy 2x size
        if [ -f "$ICON_SOURCE_DIR/icon_${size}x${size}@2x.png" ]; then
            cp "$ICON_SOURCE_DIR/icon_${size}x${size}@2x.png" "$ICON_DIR/icon_${size}x${size}@2x.png"
        fi
    done

    echo "🖼️ Contents of intermediate .iconset directory ($ICON_DIR):"
    ls -l "$ICON_DIR"

    # Generate icns file
    echo "🎨 Generating icns file..."
    if ! iconutil -c icns "$ICON_DIR" -o "$APP_DIR/Contents/Resources/AppIcon.icns"; then
        echo "⚠️ Warning: Failed to generate ICNS file"
    fi

    echo "📄 Details of generated .icns file:"
    ls -l "$APP_DIR/Contents/Resources/AppIcon.icns"

    # Clean up temporary iconset
    # rm -rf "$ICON_DIR"
else
    echo "⚠️ Warning: Icon source directory not found at $ICON_SOURCE_DIR"
fi

# Copy other resources
echo "📦 Copying additional resources..."
if [ -d "Sources/Resources" ]; then
    cp -R Sources/Resources/* "$APP_DIR/Contents/Resources/" || echo "⚠️ Warning: Some resources could not be copied"
fi

# Copy StatusBarResources so code can load custom status bar icons by direct path
if [ -d "Sources/StatusBarResources" ]; then
    echo "📦 Copying custom status bar resources..."
    cp -R "Sources/StatusBarResources" "$APP_DIR/Contents/Resources/StatusBarResources" || echo "⚠️ Warning: Failed to copy StatusBarResources"
fi

# After copying resources, regenerate AppIcon.icns to overwrite any stale copy
# that may have been brought in from Sources/Resources during the copy step.
ICON_SOURCE_DIR="Sources/Resources/Assets.xcassets/AppIcon.appiconset"
if [ -d "$ICON_SOURCE_DIR" ]; then
    echo "🔁 Regenerating AppIcon.icns after resource copy..."
    ICON_DIR=".build/AppIcon.iconset"
    rm -rf "$ICON_DIR"
    mkdir -p "$ICON_DIR"

    for size in 16 32 64 128 256 512 1024; do
        # Copy regular size
        if [ -f "$ICON_SOURCE_DIR/icon_${size}x${size}.png" ]; then
            cp "$ICON_SOURCE_DIR/icon_${size}x${size}.png" "$ICON_DIR/icon_${size}x${size}.png"
        fi
        # Copy 2x size
        if [ -f "$ICON_SOURCE_DIR/icon_${size}x${size}@2x.png" ]; then
            cp "$ICON_SOURCE_DIR/icon_${size}x${size}@2x.png" "$ICON_DIR/icon_${size}x${size}@2x.png"
        fi
    done

    if iconutil -c icns "$ICON_DIR" -o "$APP_DIR/Contents/Resources/AppIcon.icns"; then
        echo "✅ AppIcon.icns regenerated and overwritten"
    else
        echo "⚠️ Warning: Failed to regenerate AppIcon.icns after resource copy"
    fi
fi

echo "📋 Resources copied. Top-level contents:"
ls "$APP_DIR/Contents/Resources/"

# Set executable permissions
echo "🔒 Setting permissions..."
chmod +x "$APP_DIR/Contents/MacOS/BasilClient"

# Function to check screen recording permission
check_screen_recording_permission() {
    # Check if we can actually capture a screen without errors
    # This is a more reliable test than checking TCC database
    if screencapture -x -C /tmp/test_screen_permission.png 2>/dev/null; then
        rm -f /tmp/test_screen_permission.png
        return 0
    else
        return 1
    fi
}

# Sign the application with entitlements
echo "🔏 Signing application with entitlements..."
# First check if the entitlements file exists
ENTITLEMENTS_FILE="Sources/Support/Basil.entitlements"
if [ ! -f "$ENTITLEMENTS_FILE" ]; then
    # Create the entitlements file if it doesn't exist
    echo "📝 Creating entitlements file..."
    cat > "$ENTITLEMENTS_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.device.audio-input</key>
    <true/>
    <key>com.apple.security.automation.apple-events</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
    <key>com.apple.security.files.downloads.read-write</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
    <key>com.apple.security.network.bonjour</key>
    <true/>
    <key>com.apple.security.device.camera</key>
    <true/>
    <key>com.apple.security.temporary-exception.apple-events</key>
    <array>
        <string>com.apple.systemevents</string>
    </array>
    <key>com.apple.security.accessibility</key>
    <true/>
    <key>com.apple.security.device.screen-recording</key>
    <true/>
    <key>com.apple.security.temporary-exception.screen-recording</key>
    <true/>
</dict>
</plist>
EOF
fi

# Sign the application with ad-hoc signature and the entitlements
if codesign --force --deep --sign - --entitlements "$ENTITLEMENTS_FILE" "$APP_DIR"; then
    echo "✅ Application signed successfully with entitlements"
else
    echo "⚠️ Warning: Failed to sign application with entitlements"
    echo "Will continue with unsigned application, but permissions may not work correctly"
fi

# Touch the app bundle to potentially refresh the icon cache
echo "🔄 Touching application bundle to refresh icon cache..."
touch "$APP_DIR"
touch "$APP_DIR/Contents/Info.plist"

echo "🧹 Clearing LaunchServices icon cache for the app..."
if type -P lsregister &> /dev/null; then
    lsregister -f "$APP_DIR"
else
    echo "⚠️ lsregister instruction not found, skipping direct cache clear for app."
fi

echo "🔄 Restarting Dock and Finder to refresh icon caches..."
# killall Dock || true # This line is now removed
# killall Finder || true
sleep 1 # Give them a moment to restart

# Test backend connection
echo "🔌 Testing backend connection..."
BACKEND_STARTUP_TIMEOUT_SECONDS=60
BACKEND_POLL_INTERVAL_SECONDS=2
MAX_RETRIES=$((BACKEND_STARTUP_TIMEOUT_SECONDS / BACKEND_POLL_INTERVAL_SECONDS))
RETRY_COUNT=0
# Hard cap on how many times we will spawn a replacement backend during
# the readiness wait. The previous loop would try to (re)spawn on every
# missing-PID iteration, which combined with slow uvicorn startup +
# `pkill -f` could fork a replacement on every poll until the process
# table was exhausted (the `fork: Resource temporarily unavailable`
# pattern observed in the logs). One replacement is enough to recover
# from a genuinely dead process; anything beyond that is masking a real
# failure.
MAX_REPLACEMENT_SPAWNS=1
REPLACEMENT_SPAWNS=0

spawn_replacement_backend() {
    local reason="$1"
    if [ "$REPLACEMENT_SPAWNS" -ge "$MAX_REPLACEMENT_SPAWNS" ]; then
        dev_log backend "Refusing to spawn another backend (already=$REPLACEMENT_SPAWNS, max=$MAX_REPLACEMENT_SPAWNS, reason=$reason)"
        return 1
    fi
    REPLACEMENT_SPAWNS=$((REPLACEMENT_SPAWNS + 1))
    dev_log backend "Spawning replacement uvicorn #$REPLACEMENT_SPAWNS (port=$PORT, reason=$reason)"
    cd "$BACKEND_DIR"
    PYTHONUNBUFFERED=1 QT_MAC_DISABLE_MENUBAR=1 NSApplicationActivationPolicy=1 PYTHONPATH="$(pwd)/src:$(pwd)" PATH="$CLEAN_PATH" poetry run python -m uvicorn api.main:app --host 127.0.0.1 --port $PORT --log-level debug 2>&1 | tee -a "$LOG_FILE" &
    local new_pid=$!
    echo $new_pid > ../.backend.pid
    cd - > /dev/null
    dev_log backend "Recorded replacement backend PID=$new_pid (reason=$reason)"
    return 0
}

while ! curl -s "http://localhost:$PORT/health" > /dev/null && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo "⚠️ Backend not responding, attempt $(($RETRY_COUNT + 1))/$MAX_RETRIES"
    if [ -f ../.backend.pid ]; then
        RECORDED_PID=$(cat ../.backend.pid)
        if kill -0 "$RECORDED_PID" 2>/dev/null; then
            # Recorded process is alive but the health endpoint isn't ready
            # yet. Health check polling alone is NOT a reason to spawn a
            # replacement - large model loads can easily push first health
            # success past 30 seconds. Keep waiting.
            dev_log backend "Recorded PID=$RECORDED_PID alive but /health not ready yet (attempt=$((RETRY_COUNT + 1)))"
        else
            dev_log backend "Recorded PID=$RECORDED_PID confirmed dead - attempting replacement"
            rm ../.backend.pid
            spawn_replacement_backend "recorded_pid_dead" || true
        fi
    else
        dev_log backend "Backend PID file missing - attempting replacement"
        # Only kill stragglers if we're about to spawn a replacement, to
        # avoid racing against a healthy process that just hasn't written
        # its PID yet.
        if pkill -f "uvicorn.*api.main:app" 2>/dev/null; then
            dev_log backend "Killed orphaned uvicorn before spawn"
        fi
        spawn_replacement_backend "pid_file_missing" || true
    fi
    sleep $BACKEND_POLL_INTERVAL_SECONDS
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ Error: Backend failed to respond after ${BACKEND_STARTUP_TIMEOUT_SECONDS}s"
    echo "📝 Uvicorn log output (last 50 lines):"
    tail -n 50 "$LOG_FILE"
    if [ -f ../.backend.pid ]; then
        kill $(cat ../.backend.pid) 2>/dev/null || true
        rm ../.backend.pid
    fi
    rm -f ../.server_port
    exit 1
fi

echo "✅ Backend is responding"
BACKEND_STARTED=true

launch_client() {
    APP_PID=""

    echo "🚀 Launching application..."
    if [ ! -d "$APP_DIR" ]; then
        echo "❌ Error: Application bundle not found at $APP_DIR"
        return 1
    fi

    echo "🔒 Running development build with proper entitlements"
    echo "📝 Passing --no-backend-startup flag to prevent duplicate backend"

    if [ -f "$APP_DIR/Contents/MacOS/BasilClient" ]; then
        echo "🔧 Launching executable directly for better permission handling..."
        if [ "$ENABLE_ZOMBIES" = true ]; then
            echo "🧟 Zombie diagnostics enabled (--zombies)"
            echo "   NSZombieEnabled=YES NSDeallocateZombies=NO MallocScribble=1"
            NSZombieEnabled=YES NSDeallocateZombies=NO MallocScribble=1 \
                "$APP_DIR/Contents/MacOS/BasilClient" --no-backend-startup &
        else
            "$APP_DIR/Contents/MacOS/BasilClient" --no-backend-startup &
        fi
        APP_PID=$!
        dev_log lifecycle "Launched BasilClient PID=$APP_PID zombies=$ENABLE_ZOMBIES"
        echo "🚀 App launched with PID: $APP_PID"
        return 0
    fi

    echo "⚠️ Executable not found, falling back to 'open' instruction..."
    if [ "$ENABLE_ZOMBIES" = true ]; then
        echo "⚠️ --zombies requested, but open(1) may not preserve all env vars."
        echo "   Prefer direct executable launch path above for reliable zombie diagnostics."
    fi
    open "$APP_DIR" --args --no-backend-startup
    dev_log lifecycle "Launched BasilClient with open(1); no PID is available for supervision"
    return 0
}

launch_client

echo "✅ Build process completed!"

# Check screen recording permission after a delay
echo "⏳ Waiting for app to launch and request permissions..."
echo "🧹 Note: All permissions were cleared - app will prompt for fresh permissions"
sleep 5

# Check if screen recording permission is working
echo "🔍 Checking if screen recording permission has been granted..."
if check_screen_recording_permission; then
    echo "✅ Screen recording permission is working!"
    SCREEN_RECORDING_GRANTED=true
else
    echo "📝 Screen recording permission not yet granted (expected for clean slate)"
    echo ""
    echo "🔧 This is normal behavior since all permissions were cleared"
    echo ""
    echo "When the app prompts for permissions:"
    echo "  ✅ Grant Screen Recording permission for image capture features"
    echo "  ✅ Grant Accessibility permission for system automation"
    echo "  ✅ Grant Microphone permission for audio transcription"
    echo ""
    echo "After granting Screen Recording permission:"
    echo "  📱 The app will need to restart (this is a macOS requirement)"
    echo "  🔄 Press Ctrl+C here to stop the backend, then run ./dev.sh again"
    echo ""
    echo "💡 You can test if permissions are working by pressing F10 (capture hotkey)"
    echo "   If it captures window content, permissions are working correctly."
fi

# Cleanup function (re-defined here to override the earlier one with a
# version that knows about $BACKEND_STARTED). Huey consumer cleanup is
# intentionally absent post Huey-removal.
cleanup() {
    dev_log cleanup "Performing thorough cleanup (BACKEND_STARTED=$BACKEND_STARTED)"

    if [ "$PRESERVE_BACKEND_ON_EXIT" = true ]; then
        dev_log cleanup "Preserving backend after exhausted BasilClient crash restart budget"
        echo "⚠️ BasilClient restart budget exhausted; backend remains running on port $PORT."
        echo "   Re-run ./dev.sh after investigating the client crash."
        return
    fi

    if [ "$BACKEND_STARTED" = true ] || [ -f ../.backend.pid ]; then
        if [ -f ../.backend.pid ]; then
            CLEANUP_PID=$(cat ../.backend.pid)
            if kill -0 "$CLEANUP_PID" 2>/dev/null; then
                dev_log cleanup "Killing recorded backend PID=$CLEANUP_PID"
                kill -9 "$CLEANUP_PID" 2>/dev/null || true
            else
                dev_log cleanup "Recorded backend PID=$CLEANUP_PID already dead"
            fi
            rm -f ../.backend.pid
        fi
        pkill -f "uvicorn.*api.main:app" 2>/dev/null && dev_log cleanup "Killed stray uvicorn matchers" || true
        pkill -f "python.*api.main" 2>/dev/null || true
        pkill -f "python -m api.main" 2>/dev/null || true
        rm -f ../.server_port
    fi

    # Kill any processes using our ports
    for port in $(seq 8000 8010); do
        echo "🔍 Checking port $port..."
        lsof -i :$port | grep LISTEN | awk '{print $2}' | xargs kill -9 2>/dev/null || true
    done

    # Force kill any Python processes that might be related to our app
    ps aux | grep -E "python.*(api.main|uvicorn)" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true

    echo "✨ Cleanup complete"
}

# Set up cleanup on script exit
trap cleanup EXIT
trap 'INTERRUPTED=true' INT

# Keep the script running to maintain the backend process. Two cases:
#
#   1. Direct-executable launch above captured the BasilClient PID into
#      $APP_PID. Wait on that PID so this script exits the moment the
#      user quits the app (menu-bar Quit, Cmd+Q, app crash, etc.). The
#      EXIT trap then fires `cleanup`, which kills the recorded backend
#      PID and any stray uvicorn workers - the same teardown Ctrl+C has
#      always produced. `wait` is signal-interruptible, so Ctrl+C still
#      works exactly as before.
#
#   2. The `open`-based fallback path doesn't yield a PID we can wait
#      on. Keep the original sleep loop there with a clear note so it
#      isn't silently broken if the direct path ever stops working.
if [ "$BACKEND_STARTED" = true ]; then
    if [ -n "${APP_PID:-}" ] && kill -0 "$APP_PID" 2>/dev/null; then
        CLIENT_CRASH_RESTART_COUNT=0
        echo "✨ Development environment ready! Quit the app or press Ctrl+C to stop the backend."

        while true; do
            dev_log lifecycle "Waiting on BasilClient PID=$APP_PID restart_count=$CLIENT_CRASH_RESTART_COUNT"
            set +e
            wait "$APP_PID"
            APP_EXIT_STATUS=$?
            set -e

            if [ "$INTERRUPTED" = true ]; then
                dev_log lifecycle "Received SIGINT while waiting on BasilClient PID=$APP_PID; running normal cleanup"
                break
            fi

            if [ "$APP_EXIT_STATUS" -eq 0 ]; then
                dev_log lifecycle "BasilClient PID=$APP_PID exited normally; running cleanup via EXIT trap"
                break
            fi

            CLIENT_CRASH_RESTART_COUNT=$((CLIENT_CRASH_RESTART_COUNT + 1))
            if [ "$CLIENT_CRASH_RESTART_COUNT" -gt "$CLIENT_CRASH_RESTART_LIMIT" ]; then
                PRESERVE_BACKEND_ON_EXIT=true
                dev_log lifecycle "BasilClient PID=$APP_PID exited status=$APP_EXIT_STATUS after $CLIENT_CRASH_RESTART_LIMIT replacement launches; preserving backend"
                exit "$APP_EXIT_STATUS"
            fi

            RESTART_DELAY="${CLIENT_CRASH_RESTART_DELAYS[$((CLIENT_CRASH_RESTART_COUNT - 1))]}"
            dev_log lifecycle "BasilClient PID=$APP_PID exited status=$APP_EXIT_STATUS; restarting replacement $CLIENT_CRASH_RESTART_COUNT/$CLIENT_CRASH_RESTART_LIMIT in ${RESTART_DELAY}s"
            sleep "$RESTART_DELAY"
            if [ "$INTERRUPTED" = true ]; then
                dev_log lifecycle "Received SIGINT during BasilClient restart backoff; running normal cleanup"
                break
            fi
            if ! launch_client; then
                PRESERVE_BACKEND_ON_EXIT=true
                dev_log lifecycle "Replacement BasilClient launch failed; preserving backend"
                exit 1
            fi

            if [ -z "${APP_PID:-}" ] || ! kill -0 "$APP_PID" 2>/dev/null; then
                PRESERVE_BACKEND_ON_EXIT=true
                dev_log lifecycle "Replacement BasilClient did not provide a live direct-launch PID; preserving backend"
                exit 1
            fi
        done
    else
        dev_log lifecycle "No tracked APP_PID (open(1) fallback path); falling back to Ctrl+C-only teardown"
        echo "✨ Development environment ready! Press Ctrl+C to stop the backend and cleanup."
        echo "ℹ️  Quitting the app from its menu will NOT stop the backend in this path"
        echo "    (no PID captured by 'open'). Use Ctrl+C here to tear it down."
        while true; do
            sleep 1
            if [ "$INTERRUPTED" = true ]; then
                dev_log lifecycle "Received SIGINT without a tracked BasilClient PID; running normal cleanup"
                break
            fi
        done
    fi
fi 