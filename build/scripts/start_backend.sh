#!/bin/bash
set -x # Enable instruction tracing to stderr

# Backend startup script for Basil
# This script handles backend startup, port cleanup, and process management

# Add debugging to see what's happening
echo "DEBUG: Script started with args: $@" >&2
echo "DEBUG: Current PATH: $PATH" >&2
echo "DEBUG: Current working directory: $(pwd)" >&2

echo "DEBUG: About to set -e" >&2
set -e
echo "DEBUG: set -e completed successfully" >&2

echo "DEBUG: About to process arguments" >&2
# ARGUMENTS:
# $1: WRITABLE_APP_SUPPORT_DIR (e.g., ~/Library/Application Support/YourBundleID/)
# $2: APP_BUNDLE_RESOURCES_DIR (e.g., .../Basil.app/Contents/Resources/)

WRITABLE_APP_SUPPORT_DIR="${1:-}"
echo "DEBUG: WRITABLE_APP_SUPPORT_DIR set to: $WRITABLE_APP_SUPPORT_DIR" >&2

APP_BUNDLE_RESOURCES_DIR="${2:-}"
echo "DEBUG: APP_BUNDLE_RESOURCES_DIR set to: $APP_BUNDLE_RESOURCES_DIR" >&2

# If no writable app support dir provided, derive it from the app's CFBundleIdentifier
if [ -z "$WRITABLE_APP_SUPPORT_DIR" ]; then
    if [ -z "$APP_BUNDLE_RESOURCES_DIR" ]; then
        echo "❌ Error: APP_BUNDLE_RESOURCES_DIR (Argument 2) not provided" >&2
        exit 1
    fi
    APP_CONTENTS_DIR="$(cd "$APP_BUNDLE_RESOURCES_DIR/.." && pwd)"
    INFO_PLIST="$APP_CONTENTS_DIR/Info.plist"
    if [ -f "$INFO_PLIST" ]; then
        BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST" 2>/dev/null || plutil -extract CFBundleIdentifier raw -o - "$INFO_PLIST" 2>/dev/null || echo 'com.stratten.basil')"
    else
        BUNDLE_ID="com.stratten.basil"
    fi
    WRITABLE_APP_SUPPORT_DIR="$HOME/Library/Application Support/$BUNDLE_ID"
    echo "DEBUG: Derived WRITABLE_APP_SUPPORT_DIR from Info.plist: $WRITABLE_APP_SUPPORT_DIR" >&2
fi

if [ -z "$APP_BUNDLE_RESOURCES_DIR" ]; then
    echo "❌ Error: APP_BUNDLE_RESOURCES_DIR (Argument 2) not provided"
    exit 1
fi

# Create the writable app support directory first if it doesn't exist
mkdir -p "$WRITABLE_APP_SUPPORT_DIR"

# Convert APP_BUNDLE_RESOURCES_DIR to absolute path to avoid issues when changing directories
APP_BUNDLE_RESOURCES_DIR="$(cd "$APP_BUNDLE_RESOURCES_DIR" && pwd)"

# Define paths for WRITABLE locations using $1
# This APP_SUPPORT_DIR is the one an external process (Python backend) will be told to use.
APP_SUPPORT_DIR="$WRITABLE_APP_SUPPORT_DIR"
LOG_DIR="$APP_SUPPORT_DIR/logs"
BACKEND_LOG_FILE="$LOG_DIR/backend.log"
SERVER_PORT_FILE="$APP_SUPPORT_DIR/server_port"
BACKEND_PID_FILE="$APP_SUPPORT_DIR/.basil_backend.pid"
UVICORN_PID_FILE="$APP_SUPPORT_DIR/.basil_uvicorn.pid"

# Create necessary writable directories *early*
# Redirect initial mkdir/log output to a temporary bootstrap log in case LOG_DIR creation fails
# Use explicit /bin/mkdir to avoid Homebrew GNU coreutils that may not be accessible in sandbox
BOOTSTRAP_LOG="$WRITABLE_APP_SUPPORT_DIR/backend_bootstrap.log"
echo "Bootstrapping script... WRITABLE_APP_SUPPORT_DIR='$WRITABLE_APP_SUPPORT_DIR'" > "$BOOTSTRAP_LOG"
/bin/mkdir -p "$APP_SUPPORT_DIR" >> "$BOOTSTRAP_LOG" 2>&1
/bin/mkdir -p "$LOG_DIR" >> "$BOOTSTRAP_LOG" 2>&1

# Function for logging (now that LOG_DIR should be writable)
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - [BACKEND] $1" >> "$BACKEND_LOG_FILE"
}

# Define paths for READ-ONLY bundled resources using $2
# UPDATED: use relocatable Python bundled under Resources/backend/python
PYTHON_EXECUTABLE="$APP_BUNDLE_RESOURCES_DIR/backend/python/bin/python3"
# Phase 2 of the Huey-removal / entry-point-consolidation plan replaced
# the bespoke `basil_api.py` script entry with `python -m api.main`. The
# `api` package lives under `backend/src/`, which we add to PYTHONPATH
# below; existence is sanity-checked via BACKEND_MAIN_MODULE_FILE.
BACKEND_MAIN_MODULE="api.main"
BACKEND_MAIN_MODULE_FILE="$APP_BUNDLE_RESOURCES_DIR/backend/src/api/main.py"

log "Starting Basil backend..."
log "Writable App Support Dir: $WRITABLE_APP_SUPPORT_DIR"
log "App Bundle Resources Dir: $APP_BUNDLE_RESOURCES_DIR"
log "Python Executable: $PYTHON_EXECUTABLE"
log "Backend Main Module: $BACKEND_MAIN_MODULE  (file: $BACKEND_MAIN_MODULE_FILE)"
log "Server Port File: $SERVER_PORT_FILE"
log "Backend Log File: $BACKEND_LOG_FILE"

# Clean up any existing processes and ports (using writable paths for PID files)
# ... (rest of cleanup logic is the same, using BACKEND_PID_FILE, UVICORN_PID_FILE defined from WRITABLE_APP_SUPPORT_DIR) ...
# Kill any existing backend processes
if [ -f "$BACKEND_PID_FILE" ]; then
    STORED_BACKEND_PID=$(cat "$BACKEND_PID_FILE" 2>/dev/null || echo "")
    if [ -n "$STORED_BACKEND_PID" ] && kill -0 "$STORED_BACKEND_PID" 2>/dev/null; then
        log "Killing existing backend process (PID: $STORED_BACKEND_PID) from $BACKEND_PID_FILE"
        kill -TERM "$STORED_BACKEND_PID" 2>/dev/null || true; sleep 1
        kill -KILL "$STORED_BACKEND_PID" 2>/dev/null || true
    fi
    rm -f "$BACKEND_PID_FILE"
fi

if [ -f "$UVICORN_PID_FILE" ]; then
    STORED_UVICORN_PID=$(cat "$UVICORN_PID_FILE" 2>/dev/null || echo "")
    if [ -n "$STORED_UVICORN_PID" ] && kill -0 "$STORED_UVICORN_PID" 2>/dev/null; then
        log "Killing existing uvicorn process (PID: $STORED_UVICORN_PID) from $UVICORN_PID_FILE"
        kill -TERM "$STORED_UVICORN_PID" 2>/dev/null || true; sleep 1
        kill -KILL "$STORED_UVICORN_PID" 2>/dev/null || true
    fi
    rm -f "$UVICORN_PID_FILE"
fi

COMMON_PORTS="8000 8001 8002 8003 8004 8005"
for port_to_clean in $COMMON_PORTS; do
    PID_ON_PORT=$(lsof -ti:$port_to_clean 2>/dev/null || echo "")
    if [ -n "$PID_ON_PORT" ]; then
        log "Killing process using port $port_to_clean (PID: $PID_ON_PORT)"
        kill -TERM "$PID_ON_PORT" 2>/dev/null || true; sleep 0.5
        kill -KILL "$PID_ON_PORT" 2>/dev/null || true
    fi
done
rm -f "$SERVER_PORT_FILE"

# Verify Python executable exists (from bundle resources)
if [ ! -f "$PYTHON_EXECUTABLE" ]; then
    log "❌ Error: Python executable not found at $PYTHON_EXECUTABLE"
    echo "❌ Error: Python executable not found at $PYTHON_EXECUTABLE" >> "$BOOTSTRAP_LOG"
    exit 1
fi

# Verify backend module file exists (from bundle resources). We launch via
# `python -m api.main`, but a missing api/main.py would otherwise produce a
# late, opaque ModuleNotFoundError -- this fail-fast keeps diagnostics local.
if [ ! -f "$BACKEND_MAIN_MODULE_FILE" ]; then
    log "❌ Error: Backend main module file not found at $BACKEND_MAIN_MODULE_FILE"
    echo "❌ Error: Backend main module file not found at $BACKEND_MAIN_MODULE_FILE" >> "$BOOTSTRAP_LOG"
    exit 1
fi

# Set up environment variables
# APP_SUPPORT_DIR for Python should point to the writable location
export APP_SUPPORT_DIR="$WRITABLE_APP_SUPPORT_DIR"
# UPDATED: point PYTHONPATH to bundled backend src and bundled site-packages
export PYTHONPATH="$APP_BUNDLE_RESOURCES_DIR/backend/src:$APP_BUNDLE_RESOURCES_DIR/backend/python/lib/python3.11/site-packages"
export PYTHON_EXECUTABLE_PATH_FOR_ENV="$PYTHON_EXECUTABLE" # Renamed to avoid conflict, PYTHON_EXECUTABLE is already a var

# Inject a sitecustomize to ensure sys.stdout/stderr expose isatty for uvicorn logging
SITE_CUSTOM_DIR="$APP_SUPPORT_DIR/py_bootstrap"
mkdir -p "$SITE_CUSTOM_DIR"
cat > "$SITE_CUSTOM_DIR/sitecustomize.py" <<'PYEOF'
import sys
if not hasattr(sys.stdout, "isatty"):
    try:
        sys.stdout.isatty = lambda: False  # type: ignore[attr-defined]
    except Exception:
        pass
if not hasattr(sys.stderr, "isatty"):
    try:
        sys.stderr.isatty = lambda: False  # type: ignore[attr-defined]
    except Exception:
        pass
PYEOF
export PYTHONPATH="$SITE_CUSTOM_DIR:$PYTHONPATH"

# UPDATED: libsndfile and other dylib paths now come from bundled python site-packages and backend deps
SOUNDFILE_DATA_LIB_PATH="$APP_BUNDLE_RESOURCES_DIR/backend/python/lib/python3.11/site-packages/_soundfile_data"
FFMPEG_BUNDLED_LIBS_PATH="$APP_BUNDLE_RESOURCES_DIR/backend/dependencies/libs" # Path to FFmpeg's own bundled dylibs

# Remove Framework references; include torch/numpy dylibs under bundled python
export DYLD_LIBRARY_PATH="$SOUNDFILE_DATA_LIB_PATH:$FFMPEG_BUNDLED_LIBS_PATH:$APP_BUNDLE_RESOURCES_DIR/backend/python/lib/python3.11/site-packages/torch/lib:$APP_BUNDLE_RESOURCES_DIR/backend/python/lib/python3.11/site-packages/numpy/.dylibs:$APP_BUNDLE_RESOURCES_DIR/backend/../dependencies/libs:$DYLD_LIBRARY_PATH"
export DYLD_FRAMEWORK_PATH="$DYLD_FRAMEWORK_PATH"

# Set PATH to prioritize our bundled python and backend binaries
export PATH="$APP_BUNDLE_RESOURCES_DIR/backend/python/bin:$APP_BUNDLE_RESOURCES_DIR/backend/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Force soundfile to use our bundled libsndfile and avoid user site interference
export SOUNDFILE_LIBRARY="$APP_BUNDLE_RESOURCES_DIR/backend/dependencies/libs/libsndfile.dylib"
export PYTHONNOUSERSITE=1

# Basic threading controls (no longer sandboxed, so PyTorch can run normally)
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0
export CUDA_VISIBLE_DEVICES=""
export PYTHONOPTIMIZE="" # Ensure it's not aggressively set by parent process

log "Environment configured for non-sandboxed operation: OMP_NUM_THREADS=1, MKL_NUM_THREADS=1"
log "PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0, CUDA_VISIBLE_DEVICES='' (disabled)"
log "DYLD_LIBRARY_PATH: $DYLD_LIBRARY_PATH"

# Ensure soundfile can resolve libsndfile and its dependencies via expected @rpath layout
SITE_PACKAGES_DIR="$APP_BUNDLE_RESOURCES_DIR/backend/python/lib/python3.11/site-packages"
SOUNDFILE_DIR="$SITE_PACKAGES_DIR/_soundfile_data"
SITE_LIB_DIR="$SITE_PACKAGES_DIR/lib"
mkdir -p "$SITE_LIB_DIR"
# Symlink supporting libs into site-packages/lib where @rpath (@loader_path/../lib) points
for libname in libogg.0.dylib libvorbis.0.dylib libvorbisenc.2.dylib libFLAC.14.dylib libopus.0.dylib libmpg123.0.dylib libmp3lame.0.dylib; do
  if [ -f "$SOUNDFILE_DIR/$libname" ] && [ ! -f "$SITE_LIB_DIR/$libname" ]; then
    ln -sf "$SOUNDFILE_DIR/$libname" "$SITE_LIB_DIR/$libname" || true
  fi
  if [ -f "$FFMPEG_BUNDLED_LIBS_PATH/$libname" ] && [ ! -f "$SITE_LIB_DIR/$libname" ]; then
    ln -sf "$FFMPEG_BUNDLED_LIBS_PATH/$libname" "$SITE_LIB_DIR/$libname" || true
  fi
done
# Provide the architecture-specific name expected by soundfile as a symlink
if [ -f "$SOUNDFILE_DIR/libsndfile.dylib" ] && [ ! -f "$SOUNDFILE_DIR/libsndfile_arm64.dylib" ]; then
  ln -sf "$SOUNDFILE_DIR/libsndfile.dylib" "$SOUNDFILE_DIR/libsndfile_arm64.dylib" || true
fi

# Function to check if a port is available (nc might not be in sandboxed PATH)
# Using Python to check port as it's more reliable in varied environments.
check_port() {
    local port_to_check=$1
    "$PYTHON_EXECUTABLE" -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); exit(0) if s.connect_ex(('127.0.0.1', $port_to_check)) != 0 else exit(1)"
    return $?
}


START_PORT=8000
MAX_PORT_ATTEMPTS=10
FOUND_PORT_FLAG=""

log "Searching for an available port starting from $START_PORT..."
for i in $(seq 0 $MAX_PORT_ATTEMPTS); do
    CURRENT_PORT_TO_CHECK=$((START_PORT + i))
    if check_port $CURRENT_PORT_TO_CHECK; then
        BACKEND_PORT=$CURRENT_PORT_TO_CHECK
        FOUND_PORT_FLAG="true"
        log "Port $BACKEND_PORT is available."
        break
    else
        log "Port $CURRENT_PORT_TO_CHECK is in use."
    fi
done

if [ -z "$FOUND_PORT_FLAG" ]; then
    log "❌ Error: Could not find an available port in the range $START_PORT-$((START_PORT + MAX_PORT_ATTEMPTS))."
    exit 1
fi

log "Starting Python backend process on port $BACKEND_PORT..."

# Change to the backend code directory within the app bundle before running uvicorn
cd "$APP_BUNDLE_RESOURCES_DIR/backend"
log "Changed directory to $(pwd) for uvicorn launch."

# Set environment variable to indicate this is a bundled production build
export BASIL_BUNDLED=true
# The backend replaces its loopback credentials at startup so every app launch gets fresh tokens.
export BASIL_ROTATE_BACKEND_CREDENTIALS=1

# Verify libsndfile is working before starting the backend
log "🔍 Verifying libsndfile setup before backend startup..."
SOUNDFILE_TEST_SCRIPT="$APP_BUNDLE_RESOURCES_DIR/backend/python/lib/python3.11/site-packages/_soundfile_data/test_libsndfile.py"
if [ -f "$SOUNDFILE_TEST_SCRIPT" ]; then
    log "Running libsndfile verification test..."
    if "$PYTHON_EXECUTABLE" "$SOUNDFILE_TEST_SCRIPT" >> "$BACKEND_LOG_FILE" 2>&1; then
        log "✅ libsndfile verification passed"
    else
        log "❌ WARNING: libsndfile verification failed - transcription may not work properly"
        echo "libsndfile verification failed at $(date)" >> "${LOG_DIR}/libsndfile_issues.log"
        echo "Test script output:" >> "${LOG_DIR}/libsndfile_issues.log"
        "$PYTHON_EXECUTABLE" "$SOUNDFILE_TEST_SCRIPT" >> "${LOG_DIR}/libsndfile_issues.log" 2>&1 || true
    fi
else
    log "⚠️ libsndfile test script not found at $SOUNDFILE_TEST_SCRIPT"
fi

# Log current directory and relevant paths for ffmpeg diagnostics
echo "Current working directory (before uvicorn): $(pwd)" >> "${LOG_DIR}/ffmpeg_pre_run_diag.log"
echo "APP_BUNDLE_RESOURCES_DIR: ${APP_BUNDLE_RESOURCES_DIR}" >> "${LOG_DIR}/ffmpeg_pre_run_diag.log"
echo "FFMPEG_PATH_TO_CHECK (relative to CWD): ./bin/ffmpeg" >> "${LOG_DIR}/ffmpeg_pre_run_diag.log"
echo "--- ls -l ./bin/ffmpeg (from $(pwd)) ---" >> "${LOG_DIR}/ffmpeg_pre_run_diag.log"
ls -l ./bin/ffmpeg >> "${LOG_DIR}/ffmpeg_pre_run_diag.log" 2>&1
echo "--- End of ffmpeg pre-run diagnostics (otool removed) ---" >> "${LOG_DIR}/ffmpeg_pre_run_diag.log"

# Start the backend process. Phase 2 of the entry-point-consolidation plan
# replaced the script-style invocation (`python .../basil_api.py`) with the
# canonical `python -m api.main`; the CLI flags are parsed by the argparse
# block at the bottom of `api/main.py`.
"$PYTHON_EXECUTABLE" -m "$BACKEND_MAIN_MODULE" --host 127.0.0.1 --port "$BACKEND_PORT" --port-file "$SERVER_PORT_FILE" --log-level info >> "$BACKEND_LOG_FILE" 2>&1 &
ACTUAL_BACKEND_PID=$!

echo "$ACTUAL_BACKEND_PID" > "$BACKEND_PID_FILE" # Using the correct PID file path
log "Backend process started with PID: $ACTUAL_BACKEND_PID. Log: $BACKEND_LOG_FILE"

# Wait for the backend to be ready.
# REPLACED: Previously we wrote the port file early and checked only for file presence.
# Now we gate purely on the health endpoint; once healthy, we ensure the port file contains the actual port.
#
# Implementation note: this loop tracks wall-clock seconds via the bash
# builtin `SECONDS` rather than counting iterations. The earlier version
# conflated the two and silently collapsed a 45s budget into ~6s, because:
#   * the loop condition `COUNTER_WAIT < TIMEOUT_SECONDS` treated
#     iteration count as elapsed seconds; and
#   * `sleep 0.$((BACKOFF_MS))` produced `sleep 0.1000` once BACKOFF_MS
#     reached 1000, which `sleep` parses as 0.1 seconds (trailing zeros
#     after a decimal are insignificant), capping the per-iteration
#     backoff at 100ms forever.
# Both are addressed below: the duration is formatted with `printf` so the
# whole-seconds component is explicit, and the budget check uses `SECONDS`.
TIMEOUT_SECONDS=45
log "Waiting for backend health at http://127.0.0.1:$BACKEND_PORT/health (up to ${TIMEOUT_SECONDS}s) ..."
BACKOFF_MS=200          # current per-probe backoff; ramps to 1000ms
SECONDS=0               # bash-builtin: wall-clock seconds since this assignment
LAST_HEARTBEAT=0

while [ "$SECONDS" -lt "$TIMEOUT_SECONDS" ]; do
    # If the process died, fail fast
    if ! kill -0 "$ACTUAL_BACKEND_PID" 2>/dev/null; then
        log "❌ Backend process (PID: $ACTUAL_BACKEND_PID) died unexpectedly after ${SECONDS}s."
        log "Last few lines of backend log ($BACKEND_LOG_FILE):"
        tail -10 "$BACKEND_LOG_FILE" 2>/dev/null || log "(Backend log not found or empty)"
        exit 1
    fi

    # Health check (short timeout so we can retry quickly)
    if /usr/bin/curl -sS --max-time 1 --fail "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null; then
        CURRENT_PORT_FILE_CONTENT="$(/bin/cat "$SERVER_PORT_FILE" 2>/dev/null | tr -d '[:space:]' || true)"
        if [ "$CURRENT_PORT_FILE_CONTENT" != "$BACKEND_PORT" ]; then
            echo "$BACKEND_PORT" > "$SERVER_PORT_FILE"
            log "Wrote confirmed listening port $BACKEND_PORT to $SERVER_PORT_FILE"
        fi
        log "✅ Backend is healthy on port $BACKEND_PORT after ${SECONDS}s (health endpoint OK)."
        rm -f "$BOOTSTRAP_LOG"
        exit 0
    fi

    # Format BACKOFF_MS as a `<sec>.<ms>` string. printf with explicit
    # whole and fractional fields sidesteps the `sleep 0.1000 == 0.1s` trap.
    # Examples: 200 -> "0.200", 800 -> "0.800", 1000 -> "1.000".
    BACKOFF_SEC=$(printf '%d.%03d' "$((BACKOFF_MS / 1000))" "$((BACKOFF_MS % 1000))")
    /bin/sleep "$BACKOFF_SEC" 2>/dev/null || /bin/sleep 1

    if [ $BACKOFF_MS -lt 1000 ]; then BACKOFF_MS=$((BACKOFF_MS + 200)); fi

    # Heartbeat every 5 wall-clock seconds (not every 5 iterations -- iteration
    # count varies with backoff and curl latency, which made the old cadence
    # essentially unpredictable).
    if [ $((SECONDS - LAST_HEARTBEAT)) -ge 5 ]; then
        log "⏳ Waiting for health... (${SECONDS}/${TIMEOUT_SECONDS}s)"
        LAST_HEARTBEAT=$SECONDS
    fi
done

log "❌ Backend failed to become healthy on port $BACKEND_PORT within ${SECONDS}s (budget: ${TIMEOUT_SECONDS}s)."
log "Final check of backend log ($BACKEND_LOG_FILE):"
tail -50 "$BACKEND_LOG_FILE" 2>/dev/null || log "(Backend log not found or empty)"
exit 1 