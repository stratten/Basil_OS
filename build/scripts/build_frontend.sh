#!/bin/bash
# Exit on error
set -e

# Arguments:
# $1: Absolute path to the client source directory (e.g., /Users/user/Desktop/BasilOpenSource/client)
# $2: Absolute path to the frontend destination directory (e.g., /Users/user/Desktop/BasilOpenSource/build/output/YYYYMMDD_HHMMSS/frontend)
# $3: (Optional) Code signing identity - defaults to ad-hoc ("-") if not provided

CLIENT_SRC_DIR="$1"
FRONTEND_DEST_DIR="$2"
CODE_SIGN_IDENTITY="${3:--}"  # Use provided identity or default to ad-hoc

# Function for logging with timestamp
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

clean_swift_build_artifacts() {
    log "🧹 Cleaning Swift package state..."
    swift package clean 2>/dev/null || log "⚠️ swift package clean failed, continuing with filesystem cleanup"

    if [ ! -d ".build" ]; then
        swift package reset 2>/dev/null || log "⚠️ swift package reset failed, continuing because .build is already absent"
        return 0
    fi

    local cleanup_dir=".build.cleanup.$(date +%s).$$"
    if mv .build "$cleanup_dir" 2>/dev/null; then
        log "🧹 Moved .build to $cleanup_dir for best-effort deletion"
        rm -rf "$cleanup_dir" 2>/dev/null || {
            log "⚠️ Deferred Swift index cleanup raced with SourceKit; removing index-build separately"
            rm -rf "$cleanup_dir/index-build" 2>/dev/null || true
            rm -rf "$cleanup_dir" 2>/dev/null || log "⚠️ Could not fully remove $cleanup_dir; continuing because .build was moved aside"
        }
        swift package reset 2>/dev/null || log "⚠️ swift package reset failed after moving .build aside; continuing"
        return 0
    fi

    log "⚠️ Could not move .build; attempting in-place cleanup"
    rm -rf .build 2>/dev/null || true
    rm -rf .build/index-build 2>/dev/null || true

    if [ -d ".build/release" ] || [ -d ".build/arm64-apple-macosx/release" ]; then
        log "❌ Failed to remove Swift build outputs from .build"
        return 1
    fi

    if [ -d ".build" ]; then
        log "⚠️ Only non-build Swift cache data remains under .build; continuing"
    fi

    swift package reset 2>/dev/null || log "⚠️ swift package reset failed after in-place cleanup; continuing"
}

if [ -z "$CLIENT_SRC_DIR" ] || [ -z "$FRONTEND_DEST_DIR" ]; then
  log "❌ ERROR: Source directory or destination directory not provided."
  log "Usage: ./build_frontend.sh <path_to_BasilClient_src> <path_to_frontend_dest_dir> [code_sign_identity]"
  exit 1
fi

log "🚀 Starting Frontend Build Script..."
log "Client Source: $CLIENT_SRC_DIR"
log "Frontend Destination Root: $FRONTEND_DEST_DIR"

# Ensure script is running from its own directory to resolve relative paths if any (though we use absolute)
cd "$CLIENT_SRC_DIR"
log "Current directory: $(pwd)"

# Generate standard production icons before building
log "🎨 Generating standard production icons..."
SCRIPTS_DIR="$(dirname "$CLIENT_SRC_DIR")/scripts"
PYTHON_CMD="python3"

if [ -f "$SCRIPTS_DIR/generate_icons.py" ]; then
    if ! $PYTHON_CMD "$SCRIPTS_DIR/generate_icons.py" --variant=standard; then
        log "❌ Error: Failed to generate standard production icons. Please check scripts/generate_icons.py"
        exit 1
    fi
    log "✅ Standard production icons generated successfully"
else
    log "⚠️ Warning: Icon generation script not found at $SCRIPTS_DIR/generate_icons.py"
fi

# --- Build canonical WKWebView bundles ---
#
# Delegate to the canonical builder at scripts/build-agent-task-assets.sh.
# That script builds every Vite bundle, verifies each expected entry, wipes and
# re-stages the matching resource directory, and verifies the staged JS/HTML.
# Basil Board requires both basil-board.html and conversation.html entries.
#
# We must not duplicate that logic inline here -- doing so previously allowed
# the dev and production pipelines to drift, and a stale staged bundle was
# silently shipped into the .app. Single source of truth: that script.
ROOT_DIR="$(dirname "$CLIENT_SRC_DIR")"
WEB_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/AgentTaskWebAssets"
MINI_PANEL_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/ScheduledRunMiniPanelAssets"
MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/ModelDownloadMiniPanelAssets"
POWER_USER_GUIDE_PANEL_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/PowerUserGuidePanelAssets"
MEETING_PANEL_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/MeetingDetectedMiniPanelAssets"
AMBIENT_SUGGESTIONS_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/AmbientSuggestionsPanelAssets"
BASIL_BOARD_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/BasilBoardWebAssets"
MEETING_ASSISTANT_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/MeetingAssistantWebAssets"
ASSISTANT_SESSION_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/AssistantSessionWebAssets"
TRANSCRIPTION_WIDGET_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/TranscriptionWidgetWebAssets"
AGENT_TASK_CAPTURE_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/AgentTaskCaptureInputWebAssets"
CANONICAL_WEB_BUILD="$ROOT_DIR/scripts/build-agent-task-assets.sh"
SETUP_ASSISTANT_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/SetupAssistantWebAssets"
CANONICAL_SETUP_ASSISTANT_BUILD="$ROOT_DIR/scripts/build-setup-assistant-assets.sh"
PROFILE_EDITOR_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/ProfileMemorySkillsEditorWebAssets"
CANONICAL_PROFILE_EDITOR_BUILD="$ROOT_DIR/scripts/build-profile-editor-assets.sh"
RECONCILIATION_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/SkillReconciliationWorkspaceWebAssets"
CANONICAL_RECONCILIATION_BUILD="$ROOT_DIR/scripts/build-skill-reconciliation-workspace-assets.sh"
SETTINGS_APPEARANCE_ASSETS_DEST="$CLIENT_SRC_DIR/Sources/Resources/SettingsWebAssets"
CANONICAL_SETTINGS_APPEARANCE_BUILD="$ROOT_DIR/scripts/build-settings-appearance-assets.sh"

log "🌐 Building WKWebView bundles (via canonical builder)..."
if [ ! -f "$CANONICAL_WEB_BUILD" ]; then
    log "❌ ERROR: Canonical asset builder not found at $CANONICAL_WEB_BUILD"
    log "   Refusing to build the .app with a potentially stale staged WKWebView bundle."
    exit 1
fi
if ! bash "$CANONICAL_WEB_BUILD"; then
    log "❌ ERROR: WKWebView bundle build failed."
    log "   One or more canonical staged bundles, including $BASIL_BOARD_ASSETS_DEST and $MEETING_ASSISTANT_ASSETS_DEST, may be stale or inconsistent."
    log "   Aborting before this script packages a bad bundle into the .app."
    exit 1
fi
# Production-layer sanity checks: confirm the staged dirs that the resource-copy
# step below will pull from are actually populated.
if [ ! -d "$WEB_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$WEB_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $WEB_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -d "$MINI_PANEL_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$MINI_PANEL_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $MINI_PANEL_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -d "$MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST/src/entries/model-download-mini-panel.html" ]; then
    log "❌ ERROR: Asset build reported success but $MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST/src/entries/model-download-mini-panel.html is missing."
    exit 1
fi
if [ ! -d "$POWER_USER_GUIDE_PANEL_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$POWER_USER_GUIDE_PANEL_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $POWER_USER_GUIDE_PANEL_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$POWER_USER_GUIDE_PANEL_ASSETS_DEST/src/entries/power-user-guide-panel.html" ]; then
    log "❌ ERROR: Asset build reported success but $POWER_USER_GUIDE_PANEL_ASSETS_DEST/src/entries/power-user-guide-panel.html is missing."
    exit 1
fi
if [ ! -d "$MEETING_PANEL_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$MEETING_PANEL_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $MEETING_PANEL_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -d "$AMBIENT_SUGGESTIONS_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$AMBIENT_SUGGESTIONS_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $AMBIENT_SUGGESTIONS_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -d "$BASIL_BOARD_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$BASIL_BOARD_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $BASIL_BOARD_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$BASIL_BOARD_ASSETS_DEST/src/entries/basil-board.html" ]; then
    log "❌ ERROR: Asset build reported success but $BASIL_BOARD_ASSETS_DEST/src/entries/basil-board.html is missing."
    exit 1
fi
if [ ! -f "$BASIL_BOARD_ASSETS_DEST/src/entries/conversation.html" ]; then
    log "❌ ERROR: Asset build reported success but $BASIL_BOARD_ASSETS_DEST/src/entries/conversation.html is missing."
    exit 1
fi
if [ ! -d "$MEETING_ASSISTANT_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$MEETING_ASSISTANT_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $MEETING_ASSISTANT_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$MEETING_ASSISTANT_ASSETS_DEST/src/entries/meeting-assistant.html" ]; then
    log "❌ ERROR: Asset build reported success but $MEETING_ASSISTANT_ASSETS_DEST/src/entries/meeting-assistant.html is missing."
    exit 1
fi
if [ ! -f "$MEETING_ASSISTANT_ASSETS_DEST/src/entries/meeting-analysis.html" ]; then
    log "❌ ERROR: Asset build reported success but $MEETING_ASSISTANT_ASSETS_DEST/src/entries/meeting-analysis.html is missing."
    exit 1
fi
if [ ! -d "$ASSISTANT_SESSION_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$ASSISTANT_SESSION_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $ASSISTANT_SESSION_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$ASSISTANT_SESSION_ASSETS_DEST/src/entries/assistant-session.html" ]; then
    log "❌ ERROR: Asset build reported success but $ASSISTANT_SESSION_ASSETS_DEST/src/entries/assistant-session.html is missing."
    exit 1
fi
if [ ! -f "$ASSISTANT_SESSION_ASSETS_DEST/src/entries/assistant-output-history.html" ]; then
    log "❌ ERROR: Asset build reported success but $ASSISTANT_SESSION_ASSETS_DEST/src/entries/assistant-output-history.html is missing."
    exit 1
fi
if [ ! -d "$TRANSCRIPTION_WIDGET_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$TRANSCRIPTION_WIDGET_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $TRANSCRIPTION_WIDGET_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$TRANSCRIPTION_WIDGET_ASSETS_DEST/src/entries/transcription-widget.html" ]; then
    log "❌ ERROR: Asset build reported success but $TRANSCRIPTION_WIDGET_ASSETS_DEST/src/entries/transcription-widget.html is missing."
    exit 1
fi
if [ ! -f "$TRANSCRIPTION_WIDGET_ASSETS_DEST/src/entries/audio-file-upload.html" ]; then
    log "❌ ERROR: Asset build reported success but $TRANSCRIPTION_WIDGET_ASSETS_DEST/src/entries/audio-file-upload.html is missing."
    exit 1
fi
if [ ! -d "$AGENT_TASK_CAPTURE_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$AGENT_TASK_CAPTURE_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Asset build reported success but $AGENT_TASK_CAPTURE_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
if [ ! -f "$AGENT_TASK_CAPTURE_ASSETS_DEST/src/entries/agent-task-capture-input.html" ]; then
    log "❌ ERROR: Asset build reported success but $AGENT_TASK_CAPTURE_ASSETS_DEST/src/entries/agent-task-capture-input.html is missing."
    exit 1
fi
log "✅ WKWebView bundles built and staged. Contents:"
ls -la "$WEB_ASSETS_DEST/assets" | sed 's/^/   AgentTask:    /'
ls -la "$MINI_PANEL_ASSETS_DEST/assets" | sed 's/^/   MiniPanel:    /'
ls -la "$MODEL_DOWNLOAD_MINI_PANEL_ASSETS_DEST/assets" | sed 's/^/   ModelDownloadPanel: /'
ls -la "$POWER_USER_GUIDE_PANEL_ASSETS_DEST/assets" | sed 's/^/   PowerUserGuidePanel: /'
ls -la "$AMBIENT_SUGGESTIONS_ASSETS_DEST/assets" | sed 's/^/   AmbientPanel: /'
ls -la "$MEETING_ASSISTANT_ASSETS_DEST/assets" | sed 's/^/   MeetingAssistant: /'
ls -la "$ASSISTANT_SESSION_ASSETS_DEST/assets" | sed 's/^/   AssistantSession: /'
ls -la "$AGENT_TASK_CAPTURE_ASSETS_DEST/assets" | sed 's/^/   AgentTaskCapture: /'

log "🌐 Building Setup Assistant WKWebView bundle (via canonical builder)..."
if [ ! -f "$CANONICAL_SETUP_ASSISTANT_BUILD" ]; then
    log "❌ ERROR: Canonical setup assistant asset builder not found at $CANONICAL_SETUP_ASSISTANT_BUILD"
    log "   Refusing to build the .app with a potentially stale SetupAssistantWebAssets bundle."
    exit 1
fi
if ! bash "$CANONICAL_SETUP_ASSISTANT_BUILD"; then
    log "❌ ERROR: Setup Assistant WKWebView bundle build failed."
    log "   Staged bundle at $SETUP_ASSISTANT_ASSETS_DEST may be stale or inconsistent."
    log "   Aborting before this script packages a bad bundle into the .app."
    exit 1
fi
if [ ! -d "$SETUP_ASSISTANT_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$SETUP_ASSISTANT_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Setup assistant asset build reported success but $SETUP_ASSISTANT_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
log "✅ Setup Assistant WKWebView bundle built and staged. Contents:"
ls -la "$SETUP_ASSISTANT_ASSETS_DEST/assets" | sed 's/^/   SetupAssistant: /'

log "🌐 Building Profile Editor WKWebView bundle (via canonical builder)..."
if [ ! -f "$CANONICAL_PROFILE_EDITOR_BUILD" ]; then
    log "❌ ERROR: Canonical profile editor asset builder not found at $CANONICAL_PROFILE_EDITOR_BUILD"
    log "   Refusing to build the .app with a potentially stale ProfileMemorySkillsEditorWebAssets bundle."
    exit 1
fi
if ! bash "$CANONICAL_PROFILE_EDITOR_BUILD"; then
    log "❌ ERROR: Profile Editor WKWebView bundle build failed."
    log "   Staged bundle at $PROFILE_EDITOR_ASSETS_DEST may be stale or inconsistent."
    log "   Aborting before this script packages a bad bundle into the .app."
    exit 1
fi
if [ ! -d "$PROFILE_EDITOR_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$PROFILE_EDITOR_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Profile editor asset build reported success but $PROFILE_EDITOR_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
log "✅ Profile Editor WKWebView bundle built and staged. Contents:"
ls -la "$PROFILE_EDITOR_ASSETS_DEST/assets" | sed 's/^/   ProfileEditor:  /'

log "🌐 Building Skill Reconciliation Workspace WKWebView bundle (via canonical builder)..."
if [ ! -f "$CANONICAL_RECONCILIATION_BUILD" ]; then
    log "❌ ERROR: Canonical skill reconciliation asset builder not found at $CANONICAL_RECONCILIATION_BUILD"
    log "   Refusing to build the .app with a potentially stale SkillReconciliationWorkspaceWebAssets bundle."
    exit 1
fi
if ! bash "$CANONICAL_RECONCILIATION_BUILD"; then
    log "❌ ERROR: Skill Reconciliation Workspace WKWebView bundle build failed."
    log "   Staged bundle at $RECONCILIATION_ASSETS_DEST may be stale or inconsistent."
    log "   Aborting before this script packages a bad bundle into the .app."
    exit 1
fi
if [ ! -d "$RECONCILIATION_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$RECONCILIATION_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Skill reconciliation asset build reported success but $RECONCILIATION_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
log "✅ Skill Reconciliation Workspace WKWebView bundle built and staged. Contents:"
ls -la "$RECONCILIATION_ASSETS_DEST/assets" | sed 's/^/   Reconciliation:  /'

log "🌐 Building Settings Appearance WKWebView bundle (via canonical builder)..."
if [ ! -f "$CANONICAL_SETTINGS_APPEARANCE_BUILD" ]; then
    log "❌ ERROR: Canonical settings appearance asset builder not found at $CANONICAL_SETTINGS_APPEARANCE_BUILD"
    log "   Refusing to build the .app with a potentially stale SettingsWebAssets bundle."
    exit 1
fi
if ! bash "$CANONICAL_SETTINGS_APPEARANCE_BUILD"; then
    log "❌ ERROR: Settings Appearance WKWebView bundle build failed."
    log "   Staged bundle at $SETTINGS_APPEARANCE_ASSETS_DEST may be stale or inconsistent."
    log "   Aborting before this script packages a bad bundle into the .app."
    exit 1
fi
if [ ! -d "$SETTINGS_APPEARANCE_ASSETS_DEST/assets" ] || [ -z "$(ls -A "$SETTINGS_APPEARANCE_ASSETS_DEST/assets" 2>/dev/null)" ]; then
    log "❌ ERROR: Settings appearance asset build reported success but $SETTINGS_APPEARANCE_ASSETS_DEST/assets is empty/missing."
    exit 1
fi
log "✅ Settings Appearance WKWebView bundle built and staged. Contents:"
ls -la "$SETTINGS_APPEARANCE_ASSETS_DEST/assets" | sed 's/^/   SettingsAppearance: /'

cd "$CLIENT_SRC_DIR"
# --- End Web Components ---

log "🧹 Cleaning previous Swift build artifacts (full clean of .build)..."
clean_swift_build_artifacts
# swift package resolve # Uncomment if you face resolution issues; usually not needed if Package.resolved is committed

log "📦 Building Swift application (release configuration)..."
if ! swift build --configuration release -Xswiftc -suppress-warnings; then
    log "❌ Swift build failed!"
    exit 1
fi
log "✅ Swift application built successfully."

# Define paths for the .app bundle
APP_NAME="BasilClient.app"
APP_BUNDLE_PATH="$FRONTEND_DEST_DIR/$APP_NAME"
log "🛠️ Creating application bundle at: $APP_BUNDLE_PATH"

# Create bundle structure
mkdir -p "$APP_BUNDLE_PATH/Contents/MacOS"
mkdir -p "$APP_BUNDLE_PATH/Contents/Resources"
mkdir -p "$APP_BUNDLE_PATH/Contents/Frameworks" # For any bundled frameworks/dylibs later

log "📄 Copying Info.plist..."
INFO_PLIST_PATH="Sources/Support/Info.plist"
if [ -f "$INFO_PLIST_PATH" ]; then
    cp "$INFO_PLIST_PATH" "$APP_BUNDLE_PATH/Contents/"
else
    log "⚠️ Warning: $INFO_PLIST_PATH not found. The app bundle will be missing Info.plist."
fi

log "📦 Copying executable..."
# Default Swift executable name matches the package name (now BasilClient)
BUILT_EXECUTABLE_NAME="BasilClient"
BUILT_EXECUTABLE_PATH=".build/release/$BUILT_EXECUTABLE_NAME"

if [ -f "$BUILT_EXECUTABLE_PATH" ]; then
    cp "$BUILT_EXECUTABLE_PATH" "$APP_BUNDLE_PATH/Contents/MacOS/$BUILT_EXECUTABLE_NAME"
else
    log "❌ Error: Executable not found at $BUILT_EXECUTABLE_PATH. Check your Swift package's target name."
    exit 1
fi

log "🎨 Copying application icon..."
# Always (re)generate AppIcon.icns from the freshly created AppIcon.appiconset
APPICONSET_DIR="$CLIENT_SRC_DIR/Sources/Resources/Assets.xcassets/AppIcon.appiconset"
TEMP_ICONSET_DIR=".build/AppIcon.iconset"
mkdir -p "$TEMP_ICONSET_DIR"

if [ -d "$APPICONSET_DIR" ]; then
    log "🎨 Rebuilding AppIcon.icns from asset catalog..."
    rm -rf "$TEMP_ICONSET_DIR"
    mkdir -p "$TEMP_ICONSET_DIR"
    for size in 16 32 64 128 256 512 1024; do
        [ -f "$APPICONSET_DIR/icon_${size}x${size}.png" ] && cp "$APPICONSET_DIR/icon_${size}x${size}.png" "$TEMP_ICONSET_DIR/icon_${size}x${size}.png"
        [ -f "$APPICONSET_DIR/icon_${size}x${size}@2x.png" ] && cp "$APPICONSET_DIR/icon_${size}x${size}@2x.png" "$TEMP_ICONSET_DIR/icon_${size}x${size}@2x.png"
    done
    if /usr/bin/iconutil -c icns "$TEMP_ICONSET_DIR" -o "$APP_BUNDLE_PATH/Contents/Resources/AppIcon.icns"; then
        log "✅ AppIcon.icns regenerated and copied to app bundle."
    else
        log "⚠️ Warning: Failed to regenerate AppIcon.icns; continuing without custom icon."
    fi
else
    log "⚠️ Warning: AppIcon.appiconset not found at $APPICONSET_DIR."
fi

# Copy additional client resources including Assets.xcassets
log "📦 Copying additional client resources..."
CLIENT_RESOURCES_DIR="Sources/Resources"
if [ -d "$CLIENT_RESOURCES_DIR" ]; then
    log "📁 Copying from $CLIENT_RESOURCES_DIR to app bundle resources..."
    cp -R "$CLIENT_RESOURCES_DIR/"* "$APP_BUNDLE_PATH/Contents/Resources/"
    log "✅ Client resources copied successfully"
else
    log "⚠️ Warning: Client resources directory not found at $CLIENT_RESOURCES_DIR"
fi

# Regenerate AppIcon.icns after resource copy to overwrite any stale copy
# that was brought in from Sources/Resources/ during the bulk copy above.
if [ -d "$APPICONSET_DIR" ]; then
    log "🔁 Regenerating AppIcon.icns after resource copy..."
    rm -rf "$TEMP_ICONSET_DIR"
    mkdir -p "$TEMP_ICONSET_DIR"
    for size in 16 32 64 128 256 512 1024; do
        [ -f "$APPICONSET_DIR/icon_${size}x${size}.png" ] && cp "$APPICONSET_DIR/icon_${size}x${size}.png" "$TEMP_ICONSET_DIR/icon_${size}x${size}.png"
        [ -f "$APPICONSET_DIR/icon_${size}x${size}@2x.png" ] && cp "$APPICONSET_DIR/icon_${size}x${size}@2x.png" "$TEMP_ICONSET_DIR/icon_${size}x${size}@2x.png"
    done
    if /usr/bin/iconutil -c icns "$TEMP_ICONSET_DIR" -o "$APP_BUNDLE_PATH/Contents/Resources/AppIcon.icns"; then
        log "✅ AppIcon.icns regenerated and overwritten"
    else
        log "⚠️ Warning: Failed to regenerate AppIcon.icns after resource copy"
    fi
fi

# --- Copy Dependencies (Frameworks) ---
log "📦 Copying framework dependencies (e.g., HotKey.framework)..."
# SPM usually puts framework products directly in the .build/release directory
# The exact name might vary if HotKey package product name is different or if it's a .dylib
# Assuming HotKey.framework is the target
BUILT_FRAMEWORK_PATH=".build/release/HotKey.framework"
DEST_FRAMEWORKS_DIR="$APP_BUNDLE_PATH/Contents/Frameworks"

if [ -d "$BUILT_FRAMEWORK_PATH" ]; then
    cp -R "$BUILT_FRAMEWORK_PATH" "$DEST_FRAMEWORKS_DIR/"
    log "✅ Copied HotKey.framework to $DEST_FRAMEWORKS_DIR"
else
    log "⚠️ Warning: HotKey.framework not found at $BUILT_FRAMEWORK_PATH. If it's a dynamic dependency, the app may crash."
    log "   (Looking for .build/release/HotKey.framework)"
fi

# Copy Sparkle.framework for in-app updates
SPARKLE_FRAMEWORK_PATH=".build/release/Sparkle.framework"
if [ ! -d "$SPARKLE_FRAMEWORK_PATH" ]; then
    # SPM may place it under the architecture-specific path
    SPARKLE_FRAMEWORK_PATH=".build/arm64-apple-macosx/release/Sparkle.framework"
fi
if [ -d "$SPARKLE_FRAMEWORK_PATH" ]; then
    cp -R "$SPARKLE_FRAMEWORK_PATH" "$DEST_FRAMEWORKS_DIR/"
    log "✅ Copied Sparkle.framework to $DEST_FRAMEWORKS_DIR"
else
    log "⚠️ Warning: Sparkle.framework not found. In-app updates will not work and the app will crash at launch."
fi

# Add Frameworks rpath so the executable can find Sparkle.framework at runtime
log "🔗 Adding Frameworks rpath to executable..."
install_name_tool -add_rpath "@loader_path/../Frameworks" "$APP_BUNDLE_PATH/Contents/MacOS/$BUILT_EXECUTABLE_NAME" 2>/dev/null || true
log "✅ Frameworks rpath added"
# --- End Copy Dependencies ---

# Specifically copy status bar icons if they exist as standalone PNG files
log "🎨 Ensuring status bar icons are available..."
STATUS_BAR_ICONS=("StatusBarIcon.png" "StatusBarIconActive.png" "StatusBarIconRecording.png")
for icon in "${STATUS_BAR_ICONS[@]}"; do
    ICON_PATH="$CLIENT_RESOURCES_DIR/$icon"
    if [ -f "$ICON_PATH" ]; then
        cp "$ICON_PATH" "$APP_BUNDLE_PATH/Contents/Resources/"
        log "✅ Copied $icon to app bundle"
    else
        log "⚠️ Warning: Status bar icon $icon not found at $ICON_PATH"
    fi
done

# Copy StatusBarResources directory if it exists (for development compatibility)
if [ -d "Sources/StatusBarResources" ]; then
    log "📦 Copying StatusBarResources directory..."
    cp -R "Sources/StatusBarResources" "$APP_BUNDLE_PATH/Contents/Resources/StatusBarResources"
    log "✅ StatusBarResources copied successfully"
fi

# --- Code Signing ---
log "🔐 Signing application bundle..."

# Strip extended attributes that interfere with code signing (resource forks, Finder metadata, etc.)
log "🧹 Stripping extended attributes from app bundle..."
# Absolute path: the PyPI xattr package installs an `xattr` command without -r that can shadow Apple's on PATH.
/usr/bin/xattr -cr "$APP_BUNDLE_PATH"

ENTITLEMENTS_PATH="$CLIENT_SRC_DIR/Sources/Support/Basil.entitlements"

if [ ! -f "$ENTITLEMENTS_PATH" ]; then
    log "❌ Error: Entitlements file not found at $ENTITLEMENTS_PATH"
    exit 1
fi

log "📝 Using entitlements file: $ENTITLEMENTS_PATH"

# Sign the main executable first
log "🖋️ Signing main executable: $APP_BUNDLE_PATH/Contents/MacOS/$BUILT_EXECUTABLE_NAME"
codesign --force --sign "$CODE_SIGN_IDENTITY" --entitlements "$ENTITLEMENTS_PATH" --timestamp --options runtime "$APP_BUNDLE_PATH/Contents/MacOS/$BUILT_EXECUTABLE_NAME"

# Then sign the application bundle itself
log "🖋️ Signing application bundle: $APP_BUNDLE_PATH"
codesign --force --sign "$CODE_SIGN_IDENTITY" --entitlements "$ENTITLEMENTS_PATH" --timestamp --options runtime "$APP_BUNDLE_PATH"

log "✅ Application bundle signed."
# --- End Code Signing ---

log "✅ Frontend .app bundle created successfully at $APP_BUNDLE_PATH" 