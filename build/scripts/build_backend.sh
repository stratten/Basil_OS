#!/usr/bin/env bash

# Use relocatable Python for self-contained backend builds
# This eliminates Poetry dependencies and Python.framework bundling complexity

set -euo pipefail

# Get absolute paths.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

brew_prefix() {
    local formula="$1"
    command -v brew >/dev/null 2>&1 || return 1
    brew --prefix "$formula" 2>/dev/null
}

# Path to our relocatable Python distribution
RELOCATABLE_PYTHON_DIR="$SCRIPT_DIR/../python/python"
RELOCATABLE_PYTHON_BIN="$RELOCATABLE_PYTHON_DIR/bin/python3"

PREPARE_RELOCATABLE_PYTHON="$SCRIPT_DIR/prepare_relocatable_python.sh"
if [[ ! -x "$RELOCATABLE_PYTHON_BIN" ]]; then
    "$PREPARE_RELOCATABLE_PYTHON"
fi

# Build hardening functions
diagnostic_build_check() {
    echo "🔍 Diagnostic build environment check..."
    
    # Check relocatable Python
    if [ -x "$RELOCATABLE_PYTHON_BIN" ]; then
        local python_version=$("$RELOCATABLE_PYTHON_BIN" --version 2>&1)
        echo "   Relocatable Python: ✅ Available ($python_version)"
    else
        echo "   Relocatable Python: ❌ Not found at $RELOCATABLE_PYTHON_BIN"
        echo "   Run: Download python-build-standalone Python 3.11.17 to build/python/"
        return 1
    fi
    
    # Check pip in relocatable Python
    if [ -x "$RELOCATABLE_PYTHON_DIR/bin/pip" ]; then
        local pip_version=$("$RELOCATABLE_PYTHON_DIR/bin/pip" --version 2>&1 | head -1)
        echo "   Relocatable pip: ✅ Available ($pip_version)"
    else
        echo "   Relocatable pip: ❌ Not found"
        return 1
    fi
    
    # Disk space check (diagnostic only)
    local available_gb=$(df -h . | tail -1 | awk '{print $4}' | sed 's/G.*//')
    if [ "$available_gb" -gt 10 ] 2>/dev/null; then
        echo "   Disk space: ✅ Sufficient (${available_gb}GB)"
    elif [ "$available_gb" -gt 5 ] 2>/dev/null; then
        echo "   Disk space: ⚠️ Low (${available_gb}GB)"
    else
        local disk_info=$(df -h . | tail -1 | awk '{print $4}')
        echo "   Disk space: ℹ️ Available: $disk_info"
    fi
    
    echo "ℹ️ Diagnostic complete"
}

# Get the directory where this script is located
BUILD_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
SRC_DIR="$ROOT_DIR/backend/src"
CONFIG_DIR="$ROOT_DIR/backend/src/config"

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "❌ ERROR: Incorrect number of arguments supplied to build_backend.sh"
    echo "Usage: $0 <BACKEND_DEST> [SIGNING_IDENTITY]"
    echo "  BACKEND_DEST: Directory where the built backend will be placed"
    echo "  SIGNING_IDENTITY: Optional code signing identity (e.g., 'Developer ID Application: ...')"
    exit 1
fi

BACKEND_DEST="$1"
SIGNING_IDENTITY="${2:-"-"}"  # Default to ad-hoc signing if not provided

# Validate the provided backend destination directory
if [ -z "$BACKEND_DEST" ]; then
    echo "❌ ERROR: BACKEND_DEST argument is empty or not provided."
    exit 1
fi

# Ensure BACKEND_DEST is an absolute path
if [[ "$BACKEND_DEST" != /* ]]; then
    BACKEND_DEST="$(pwd)/$BACKEND_DEST"
fi

echo "🔧 Backend Build Configuration:"
echo "   Backend Destination: $BACKEND_DEST"
echo "   Signing Identity: $SIGNING_IDENTITY"
echo "   Root Directory: $ROOT_DIR"
echo "   Source Directory: $SRC_DIR"
echo "   Relocatable Python: $RELOCATABLE_PYTHON_BIN"

# Create the backend destination directory structure
mkdir -p "$BACKEND_DEST"

# Set up logging to both console and file
LOG_FILE="$BACKEND_DEST/backend_build.log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Output_DIR is the parent of BACKEND_DEST, e.g., .../output/TIMESTAMP/
# This might be useful if any script operations needed to reference that parent.
OUTPUT_DIR="$(dirname "$BACKEND_DEST")"

# Diagnostic environment check
if ! diagnostic_build_check; then
    echo "❌ ERROR: Environment check failed. Cannot proceed with build."
    exit 1
fi

# Verify relocatable Python works
echo "🐍 Verifying relocatable Python..."
PYTHON_VERSION=$("$RELOCATABLE_PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "🐍 Using relocatable Python: $("$RELOCATABLE_PYTHON_BIN" -c 'import sys; print(sys.executable)') (Version: $PYTHON_VERSION)"

PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if ! ( [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -eq 11 ] ); then
    echo "❌ ERROR: Incorrect Python version. Found $PYTHON_VERSION, but project requires Python 3.11."
    exit 1
fi

# Generate requirements.txt from Poetry (we still use Poetry for development dependency management)
PROJECT_ROOT_FOR_POETRY="$ROOT_DIR"
if [ -f "$PROJECT_ROOT_FOR_POETRY/poetry.lock" ]; then
    # Try to find Poetry instruction
    if ! POETRY_CMD="$(command -v poetry)"; then
        echo "ERROR: Poetry is required to generate requirements.txt." >&2
        exit 1
    fi
    
    echo "📦 Generating requirements.txt with Poetry from $PROJECT_ROOT_FOR_POETRY using $POETRY_CMD..."
    (cd "$PROJECT_ROOT_FOR_POETRY" && $POETRY_CMD run pip freeze | grep -v "^datasets=" | grep -v -E "(^basil|^-e.*basil)" > "$BACKEND_DEST/requirements.txt")
    if [ ! -f "$BACKEND_DEST/requirements.txt" ]; then
        echo "❌ ERROR: requirements.txt was not created by poetry from $PROJECT_ROOT_FOR_POETRY."
        exit 1
    fi
    echo "✅ requirements.txt generated successfully"
else
    if [ -f "$SRC_DIR/requirements.txt" ]; then
        echo "📦 Copying requirements.txt from $SRC_DIR to $BACKEND_DEST..."
        cp "$SRC_DIR/requirements.txt" "$BACKEND_DEST/requirements.txt"
        if [ ! -f "$BACKEND_DEST/requirements.txt" ]; then
            echo "❌ ERROR: Failed to copy requirements.txt to $BACKEND_DEST."
            exit 1
        fi
    else
        echo "⚠️ No poetry.lock found at $PROJECT_ROOT_FOR_POETRY/poetry.lock and no requirements.txt found at $SRC_DIR/requirements.txt."
        echo "❌ ERROR: Cannot proceed without dependency information."
        exit 1
    fi
fi

# Copy the entire relocatable Python distribution to backend
cd "$BACKEND_DEST"
echo "🐍 Copying relocatable Python distribution..."
cp -R "$RELOCATABLE_PYTHON_DIR" "$BACKEND_DEST/python"

# Create the Python environment using the bundled Python
echo "🐍 Installing dependencies using bundled Python..."
BUNDLED_PYTHON="$BACKEND_DEST/python/bin/python3"
BUNDLED_PIP="$BACKEND_DEST/python/bin/pip"

# Install dependencies from the generated requirements.txt
if [ -f "$BACKEND_DEST/requirements.txt" ]; then
    echo "🐍 Installing dependencies from requirements.txt into bundled Python..."
    "$BUNDLED_PIP" install -r "$BACKEND_DEST/requirements.txt"
else
    echo "❌ ERROR: requirements.txt not found at $BACKEND_DEST/requirements.txt."
    exit 1
fi

# Strip test directories from site-packages to reduce app size (~220MB savings)
# Excludes torch/testing, sqlalchemy/testing, keras/*/testing, lightning/*/testing
# which are runtime utility modules, not test suites
SITE_PACKAGES_DIR="$BACKEND_DEST/python/lib/python3.11/site-packages"
echo "🧹 Stripping test directories from site-packages..."
if [ -d "$SITE_PACKAGES_DIR" ]; then
    BEFORE_SIZE=$(du -sm "$SITE_PACKAGES_DIR" | cut -f1)
    find "$SITE_PACKAGES_DIR" -type d \( -name "test" -o -name "tests" -o -name "test_data" \) \
        ! -path "*/torch/testing*" \
        ! -path "*/sqlalchemy/testing*" \
        ! -path "*/keras/*/testing*" \
        ! -path "*/lightning/*/testing*" \
        -exec rm -rf {} + 2>/dev/null || true
    # PyObjC ships its own test suite as a top-level package that the name match above does not catch.
    rm -rf "$SITE_PACKAGES_DIR/PyObjCTest"
    AFTER_SIZE=$(du -sm "$SITE_PACKAGES_DIR" | cut -f1)
    SAVED=$((BEFORE_SIZE - AFTER_SIZE))
    echo "✅ Stripped test directories. Saved ${SAVED}MB (${BEFORE_SIZE}MB → ${AFTER_SIZE}MB)"
else
    echo "⚠️ site-packages not found at $SITE_PACKAGES_DIR, skipping test directory cleanup"
fi

# llama-cpp-python's source build also installs llama.cpp's C++ libraries into site-packages/lib. llama_cpp loads its own copies from llama_cpp/lib, and libllama-common links Homebrew OpenSSL by absolute path, so it cannot load on a Mac without Homebrew.
rm -f "$SITE_PACKAGES_DIR"/lib/libllama-common*.dylib

# Copy backend source code
cd "$SRC_DIR"
echo "📦 Copying backend source code..."
rsync -av --progress \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='build/' \
    --exclude='dist/' \
    --exclude='.pytest_cache/' \
    --exclude='*.egg-info/' \
    --exclude='.git/' \
    --exclude='.vscode/' \
    --exclude='.idea/' \
    --exclude='*.log' \
    --exclude='server_port' \
    --exclude='.server_port' \
    --exclude='tests/' \
    ./ "$BACKEND_DEST/src/"

echo "✅ Backend source code copied successfully"

# --- Bundle OpenWakeWord Models ---
echo "📦 Downloading and bundling OpenWakeWord models for wake word detection..."
MODELS_DIR="$BACKEND_DEST/wake_word_models"
mkdir -p "$MODELS_DIR"

# Copy any custom-trained wake word models shipped with the repo into the bundle.
# This ensures packaged builds include the Basil wake words (not just OpenWakeWord's default downloads).
CUSTOM_WAKEWORD_SRC="$SRC_DIR/api/vendor/models/wake_word"
if [ -d "$CUSTOM_WAKEWORD_SRC" ]; then
    echo "📦 Copying custom wake word models from repo: $CUSTOM_WAKEWORD_SRC"
    cp -v "$CUSTOM_WAKEWORD_SRC"/*.onnx "$MODELS_DIR/" 2>/dev/null || echo "⚠️ No custom .onnx files found in $CUSTOM_WAKEWORD_SRC"
else
    echo "⚠️ Custom wake word models directory not found: $CUSTOM_WAKEWORD_SRC"
fi

# Download the hey_jarvis model using the Python environment
echo "  Downloading hey_jarvis model..."
cd "$BACKEND_DEST"
"$BACKEND_DEST/python/bin/python" -c "
try:
    from openwakeword.utils import download_models
    import os
    models_dir = '$MODELS_DIR'
    os.makedirs(models_dir, exist_ok=True)
    
    # Download hey_jarvis model
    print('Downloading hey_jarvis model...')
    download_models(model_names=['hey_jarvis'], target_directory=models_dir)
    print(f'✅ OpenWakeWord models downloaded to {models_dir}')
    
    # List downloaded files
    import glob
    model_files = glob.glob(os.path.join(models_dir, '*.onnx'))
    print(f'Downloaded model files: {model_files}')
    
except ImportError as e:
    print(f'❌ Error: OpenWakeWord not installed in virtual environment: {e}')
    exit(1)
except Exception as e:
    print(f'❌ Error downloading OpenWakeWord models: {e}')
    exit(1)
"

if [ $? -eq 0 ]; then
    echo "✅ OpenWakeWord models downloaded successfully"
    # List the downloaded models for verification
    echo "📋 Downloaded wake word models:"
    ls -la "$MODELS_DIR"
    
    # Copy support models to OpenWakeWord package directory
    echo "📦 Copying OpenWakeWord support models to package directory..."
    OWW_PACKAGE_MODELS_DIR="$BACKEND_DEST/python/lib/python3.11/site-packages/openwakeword/resources/models"
    mkdir -p "$OWW_PACKAGE_MODELS_DIR"
    if [ -d "$OWW_PACKAGE_MODELS_DIR" ]; then
        cp "$MODELS_DIR/melspectrogram.onnx" "$OWW_PACKAGE_MODELS_DIR/" 2>/dev/null || echo "⚠️ melspectrogram.onnx not found"
        cp "$MODELS_DIR/embedding_model.onnx" "$OWW_PACKAGE_MODELS_DIR/" 2>/dev/null || echo "⚠️ embedding_model.onnx not found"
        cp "$MODELS_DIR/silero_vad.onnx" "$OWW_PACKAGE_MODELS_DIR/" 2>/dev/null || echo "⚠️ silero_vad.onnx not found"
        echo "✅ Support models copied to OpenWakeWord package directory"
    else
        echo "⚠️ OpenWakeWord package models directory not found: $OWW_PACKAGE_MODELS_DIR"
    fi
else
    echo "❌ ERROR: Failed to download OpenWakeWord models"
    exit 1
fi
# --- End OpenWakeWord Model Bundling ---

# Copy backend startup script
echo "📦 Copying backend startup script..."
BACKEND_STARTUP_SCRIPT="$SCRIPT_DIR/start_backend.sh"
if [ -f "$BACKEND_STARTUP_SCRIPT" ]; then
    cp "$BACKEND_STARTUP_SCRIPT" "$BACKEND_DEST/start_backend.sh"
    chmod +x "$BACKEND_DEST/start_backend.sh"
    echo "✅ Backend startup script copied to $BACKEND_DEST/start_backend.sh"
else
    echo "⚠️ Warning: Backend startup script not found at $BACKEND_STARTUP_SCRIPT"
fi

# Copy tesseract executable and dependencies
echo "📦 Copying tesseract executable and primary dependencies..."
mkdir -p "$BACKEND_DEST/bin"
mkdir -p "$BACKEND_DEST/dependencies/libs"

# Destination for all bundled dylibs
BUNDLED_LIBS_DIR="$BACKEND_DEST/dependencies/libs"

# --- Bundle Tesseract using CMake ---
echo "📦 Bundling Tesseract using CMake..."
CMAKE_BUNDLER_DIR="$ROOT_DIR/build/cmake/TesseractBundler"
CMAKE_BUILD_DIR="$BACKEND_DEST/tesseract_cmake_build" # Temporary build dir for CMake

# Ensure CMAKE_INSTALL_PREFIX is absolute for CMake to correctly install into bundle structure
# BACKEND_DEST is already absolute due to earlier script logic.
CMAKE_INSTALL_PREFIX_ABS="$BACKEND_DEST"

echo "  CMake Source Dir: $CMAKE_BUNDLER_DIR"
echo "  CMake Build Dir (temp): $CMAKE_BUILD_DIR"
echo "  CMake Install Prefix (target): $CMAKE_INSTALL_PREFIX_ABS"

# It's good practice to remove the CMake build directory if it exists from a previous run
rm -rf "$CMAKE_BUILD_DIR"
mkdir -p "$CMAKE_BUILD_DIR"

# Run CMake configuration
echo "  Configuring Tesseract CMake project..."
cmake -S "$CMAKE_BUNDLER_DIR" -B "$CMAKE_BUILD_DIR" -DCMAKE_INSTALL_PREFIX="$CMAKE_INSTALL_PREFIX_ABS"
if [ $? -ne 0 ]; then
    echo "❌ ERROR: CMake configuration for Tesseract failed."
    exit 1
fi

# Run CMake install
echo "  Installing Tesseract via CMake..."
cmake --install "$CMAKE_BUILD_DIR" --verbose
if [ $? -ne 0 ]; then
    echo "❌ ERROR: CMake installation for Tesseract failed."
    exit 1
fi

# Cleanup temporary CMake build directory
echo "  Cleaning up temporary CMake build directory: $CMAKE_BUILD_DIR"
rm -rf "$CMAKE_BUILD_DIR"
echo "✅ Tesseract bundled successfully using CMake."
# --- End of CMake Tesseract Bundling ---

# --- Bundle Libsndfile and Dependencies using CMake & Fix Python's soundfile module ---
echo "📦 Bundling Libsndfile and its dependencies via CMake..."
LIBSNDFILE_BUNDLER_CMAKE_DIR="${ROOT_DIR}/build/cmake/LibsndfileBundler"
# Temporary build directory for this CMake project, inside BACKEND_DEST for self-containment during build
LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR="${BACKEND_DEST}/libsndfile_cmake_build"

# CMAKE_INSTALL_PREFIX_ABS is already defined and set to BACKEND_DEST for Tesseract. We use the same.
# LibsndfileBundler's CMakeLists.txt will install into "dependencies/libs_sndfile_bundle" under this prefix.
EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH="${CMAKE_INSTALL_PREFIX_ABS}/dependencies/libs_sndfile_bundle"

echo "  LibsndfileBundler CMake Source Dir: ${LIBSNDFILE_BUNDLER_CMAKE_DIR}"
echo "  LibsndfileBundler CMake Build Dir (temp): ${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}"
echo "  LibsndfileBundler CMake Install Prefix (target root): ${CMAKE_INSTALL_PREFIX_ABS}"
echo "  Effective path for staged good dylibs: ${EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH}"

rm -rf "${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}" # Clean previous build
mkdir -p "${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}"

echo "  Configuring LibsndfileBundler CMake project..."
cmake -Wno-dev -S "${LIBSNDFILE_BUNDLER_CMAKE_DIR}" -B "${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}" -DCMAKE_INSTALL_PREFIX="${CMAKE_INSTALL_PREFIX_ABS}"
if [ $? -ne 0 ]; then
    echo "❌ ERROR: CMake configuration for LibsndfileBundler failed."
    exit 1
fi

echo "  Installing LibsndfileBundler artifacts via CMake..."
# Using --build and --install separately can sometimes be more reliable or offer better logging.
cmake --build "${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}" --verbose
if [ $? -ne 0 ]; then
    echo "❌ ERROR: CMake build for LibsndfileBundler failed."
    exit 1
fi
DEVELOPER_ID_CERT="$SIGNING_IDENTITY" cmake --install "${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}" --verbose
if [ $? -ne 0 ]; then
    echo "❌ ERROR: CMake installation for LibsndfileBundler failed."
    exit 1
fi

echo "  Cleaning up temporary CMake build directory for Libsndfile: ${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}"
rm -rf "${LIBSNDFILE_BUNDLER_CMAKE_BUILD_DIR}"
echo "✅ Libsndfile and dependencies bundled via CMake into ${EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH}"

# Now, fix the Python soundfile module to use these bundled libraries.
# The venv is located at $BACKEND_DEST/venv
FINAL_VENV_PATH_FOR_FIX_SCRIPT="${BACKEND_DEST}/python"

echo "🔧 Running fix_soundfile_module_dylibs.sh to point Python's soundfile to our new dylibs..."
FIX_SOUNDFILE_SCRIPT_PATH="${LIBSNDFILE_BUNDLER_CMAKE_DIR}/fix_soundfile_module_dylibs.sh" # Path to the .sh script itself
chmod +x "${FIX_SOUNDFILE_SCRIPT_PATH}"

echo "  Calling ${FIX_SOUNDFILE_SCRIPT_PATH} with:"
echo "    Venv Path: ${FINAL_VENV_PATH_FOR_FIX_SCRIPT}"
echo "    Staged Libsndfile Bundle Dir (containing good dylibs): ${EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH}"

if [ ! -d "${FINAL_VENV_PATH_FOR_FIX_SCRIPT}" ]; then
    echo "🔴 ERROR: Final Venv Path for fix_soundfile_module_dylibs.sh does not exist: ${FINAL_VENV_PATH_FOR_FIX_SCRIPT}"
    exit 1
fi
if [ ! -d "${EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH}" ]; then
    echo "🔴 ERROR: Staged dylibs path for fix_soundfile_module_dylibs.sh does not exist: ${EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH}"
    echo "         Expected CMake to create it via LibsndfileBundler."
    exit 1
fi

"${FIX_SOUNDFILE_SCRIPT_PATH}" "${FINAL_VENV_PATH_FOR_FIX_SCRIPT}" "${EFFECTIVE_STAGED_LIBSNDFILE_DYLIBS_PATH}"
if [ $? -ne 0 ]; then
    echo "❌ ERROR: fix_soundfile_module_dylibs.sh failed."
    exit 1
fi
echo "✅ fix_soundfile_module_dylibs.sh completed successfully."
# --- End of Libsndfile Bundling and Python soundfile fix ---

echo "======================================================================"
echo "🚀 INTENDING TO START FFmpeg Bundler Section 🚀"
echo "======================================================================"
# --- Bundle FFmpeg using CMake ---
echo "📦 Bundling FFmpeg and its dependencies via CMake..."
FFMPEG_LGPL_BUILDER="${ROOT_DIR}/build/scripts/build_ffmpeg_lgpl.sh"
FFMPEG_LGPL_PREFIX="${BASIL_FFMPEG_PREFIX:-${BUILD_DIR}/third_party/ffmpeg-lgpl}"
FFMPEG_BUNDLER_CMAKE_DIR="${ROOT_DIR}/build/cmake/FFmpegBundler"
# Temporary build directory for this CMake project, inside BACKEND_DEST
FFMPEG_BUNDLER_CMAKE_BUILD_DIR="${BACKEND_DEST}/ffmpeg_cmake_build"

# CMAKE_INSTALL_PREFIX_ABS is already defined and set to BACKEND_DEST.
# FFmpegBundler's CMakeLists.txt will install into bin/ and dependencies/libs/ under this prefix.

if [ ! -x "${FFMPEG_LGPL_PREFIX}/bin/ffmpeg" ]; then
    if [ ! -x "$FFMPEG_LGPL_BUILDER" ]; then
        echo "❌ ERROR: LGPL FFmpeg builder not executable: $FFMPEG_LGPL_BUILDER"
        exit 1
    fi
    "$FFMPEG_LGPL_BUILDER" "$FFMPEG_LGPL_PREFIX"
fi

echo "  FFmpegBundler CMake Source Dir: ${FFMPEG_BUNDLER_CMAKE_DIR}"
echo "  FFmpegBundler CMake Build Dir (temp): ${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}"
echo "  FFmpegBundler CMake Install Prefix (target root): ${CMAKE_INSTALL_PREFIX_ABS}"
echo "  LGPL FFmpeg Prefix: ${FFMPEG_LGPL_PREFIX}"

rm -rf "${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}" # Clean previous build
mkdir -p "${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}"

echo "  STEP 1: Configuring FFmpegBundler CMake project..."
cmake -S "${FFMPEG_BUNDLER_CMAKE_DIR}" -B "${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}" -DCMAKE_INSTALL_PREFIX="${CMAKE_INSTALL_PREFIX_ABS}" -DBASIL_FFMPEG_PREFIX="${FFMPEG_LGPL_PREFIX}"
FFMPEG_CMAKE_CONFIG_EC=$?
echo "  STEP 1 EXIT CODE: ${FFMPEG_CMAKE_CONFIG_EC}"
if [ $FFMPEG_CMAKE_CONFIG_EC -ne 0 ]; then
    echo "❌ ERROR: CMake configuration for FFmpegBundler failed. Exit Code: ${FFMPEG_CMAKE_CONFIG_EC}"
    exit 1
fi
echo "  STEP 1 COMPLETED."

echo "  STEP 2: Building FFmpegBundler artifacts via CMake..."
cmake --build "${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}" --verbose
FFMPEG_CMAKE_BUILD_EC=$?
echo "  STEP 2 EXIT CODE: ${FFMPEG_CMAKE_BUILD_EC}"
if [ $FFMPEG_CMAKE_BUILD_EC -ne 0 ]; then
    echo "❌ ERROR: CMake build for FFmpegBundler failed. Exit Code: ${FFMPEG_CMAKE_BUILD_EC}"
    exit 1
fi
echo "  STEP 2 COMPLETED."

echo "  STEP 3: Installing FFmpegBundler artifacts (triggers prepare_ffmpeg_bundle.sh)..."
DEVELOPER_ID_CERT="$SIGNING_IDENTITY" cmake --install "${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}" --verbose
FFMPEG_CMAKE_INSTALL_EC=$?
echo "  STEP 3 EXIT CODE: ${FFMPEG_CMAKE_INSTALL_EC}"
if [ $FFMPEG_CMAKE_INSTALL_EC -ne 0 ]; then
    echo "❌ ERROR: CMake installation for FFmpegBundler (and execution of prepare_ffmpeg_bundle.sh) failed. Exit Code: ${FFMPEG_CMAKE_INSTALL_EC}"
    exit 1
fi
echo "  STEP 3 COMPLETED."

echo "  Cleaning up temporary CMake build directory for FFmpeg: ${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}"
rm -rf "${FFMPEG_BUNDLER_CMAKE_BUILD_DIR}"
echo "✅ FFmpeg and dependencies bundled successfully using FFmpegBundler CMake project."
# --- End of FFmpeg Bundling ---
echo "======================================================================"
echo "🏁 COMPLETED FFmpeg Bundler Section 🏁"
echo "======================================================================"

# --- CRITICAL: Verify FFmpeg Bundling Actually Works ---
echo "🔍 VERIFYING FFmpeg bundling success..."
BUNDLED_FFMPEG_PATH="${BACKEND_DEST}/bin/ffmpeg"
BUNDLED_FFMPEG_DEPS_DIR="${BACKEND_DEST}/dependencies/libs"

echo "  Checking bundled FFmpeg executable: ${BUNDLED_FFMPEG_PATH}"
if [ -f "${BUNDLED_FFMPEG_PATH}" ]; then
    echo "  ✅ FFmpeg executable exists"
    
    # Check if executable
    if [ -x "${BUNDLED_FFMPEG_PATH}" ]; then
        echo "  ✅ FFmpeg executable has execute permissions"
        
        # Test FFmpeg version (critical test)
        echo "  🧪 Testing FFmpeg version instruction..."
        if FFMPEG_VERSION_OUTPUT=$("${BUNDLED_FFMPEG_PATH}" -version 2>&1); then
            echo "  ✅ FFmpeg version test PASSED"
            echo "  📋 FFmpeg version info:"
            echo "${FFMPEG_VERSION_OUTPUT}" | head -n 3 | sed 's/^/      /'
        else
            echo "  ❌ ERROR: FFmpeg version test FAILED"
            echo "  📋 FFmpeg version error output:"
            echo "${FFMPEG_VERSION_OUTPUT}" | sed 's/^/      /'
            echo "  🚨 This will cause minion audio capture to fail!"
            exit 1
        fi

        # LGPL compliance is a hard release gate: the bundled FFmpeg must be the
        # verified --disable-gpl build, never a GPL-configured binary.
        echo "  🧪 Verifying bundled FFmpeg is LGPL-only (--disable-gpl)..."
        if ! echo "${FFMPEG_VERSION_OUTPUT}" | grep -q -- "--disable-gpl"; then
            echo "  ❌ ERROR: Bundled FFmpeg was not configured with --disable-gpl." >&2
            exit 1
        fi
        echo "  ✅ Bundled FFmpeg reports --disable-gpl"

        echo "  🧪 Verifying bundled FFmpeg license text is LGPL..."
        if ! FFMPEG_LICENSE_OUTPUT=$("${BUNDLED_FFMPEG_PATH}" -L 2>&1) || ! echo "${FFMPEG_LICENSE_OUTPUT}" | grep -q "GNU Lesser General Public"; then
            echo "  ❌ ERROR: Bundled FFmpeg does not report the GNU Lesser General Public license." >&2
            exit 1
        fi
        echo "  ✅ Bundled FFmpeg reports the GNU Lesser General Public License"

        # FFmpeg audio device access will be handled at runtime with proper permissions
        echo "  ℹ️  FFmpeg bundled successfully - audio device access will be requested at runtime"
        echo "  📋 Voice instructions use dual capture architecture (FFmpeg + Swift AudioCaptureService)"
        
    else
        echo "  ❌ ERROR: FFmpeg executable lacks execute permissions"
        echo "  🔧 Attempting to fix permissions..."
        chmod +x "${BUNDLED_FFMPEG_PATH}"
        if [ -x "${BUNDLED_FFMPEG_PATH}" ]; then
            echo "  ✅ Execute permissions fixed"
        else
            echo "  ❌ ERROR: Could not fix execute permissions"
        fi
    fi
else
    echo "  ❌ ERROR: FFmpeg executable not found at ${BUNDLED_FFMPEG_PATH}"
    echo "  🚨 Voice instruction functionality will completely fail!"
fi

# Verify FFmpeg dependencies directory
echo "  Checking FFmpeg dependencies: ${BUNDLED_FFMPEG_DEPS_DIR}"
if [ -d "${BUNDLED_FFMPEG_DEPS_DIR}" ]; then
    FFMPEG_DYLIB_COUNT=$(find "${BUNDLED_FFMPEG_DEPS_DIR}" -name "*.dylib" | wc -l)
    echo "  ✅ FFmpeg dependencies directory exists with ${FFMPEG_DYLIB_COUNT} dylib files"
    
    # List key FFmpeg libraries
    echo "  📋 Key FFmpeg libraries found:"
    find "${BUNDLED_FFMPEG_DEPS_DIR}" -name "libav*.dylib" -o -name "libsw*.dylib" | head -n 8 | sed 's/^/      /'
else
    echo "  ❌ ERROR: FFmpeg dependencies directory not found"
    echo "  🚨 FFmpeg will fail to run due to missing dependencies!"
fi

echo "🔍 FFmpeg bundling verification complete"
echo "======================================================================"
# --- End FFmpeg Verification ---

# Copy additional audio libraries (libsndfile, portaudio)
# libsndfile is now handled by LibsndfileBundler, portaudio might still be needed if not pulled in by ffmpeg.
echo "📦 Checking/Copying additional audio libraries (PortAudio)..."

# portaudio (for audio capture - if not already handled by another bundler)
# We should verify if ffmpeg or other dependencies already bundle portaudio correctly.
PORTAUDIO_PREFIX="$(brew_prefix portaudio)"
PORTAUDIO_COPIED_FLAG=false
if [ -n "$PORTAUDIO_PREFIX" ]; then
    for portaudio_lib_name in "libportaudio.dylib" "libportaudio.2.dylib"; do
        # Use find to handle cases where the exact symlink/file might not exist but a version does
        found_portaudio_lib=$(find "$PORTAUDIO_PREFIX/lib" -maxdepth 1 -name "$portaudio_lib_name" -print -quit)
        if [ -n "$found_portaudio_lib" ] && [ -f "$found_portaudio_lib" ]; then
            echo "  Found PortAudio library: $found_portaudio_lib"
            # Ensure target directory exists
            mkdir -p "$BUNDLED_LIBS_DIR" # BUNDLED_LIBS_DIR defined earlier as ${BACKEND_DEST}/dependencies/libs
            cp "$found_portaudio_lib" "$BUNDLED_LIBS_DIR/"
            PORTAUDIO_COPIED_FLAG=true
        fi
    done
fi

if [ "$PORTAUDIO_COPIED_FLAG" = true ]; then
    echo "✅ PortAudio libraries copied to $BUNDLED_LIBS_DIR."
else
    echo "❌ ERROR: No PortAudio library found via 'brew --prefix portaudio'. Install PortAudio (brew install portaudio) before building." >&2
    exit 1
fi

# Create startup scripts for the bundled Python
echo "📦 Creating startup scripts for relocatable Python..."

# Create start_backend.sh that uses the bundled Python
echo "ℹ️ Using copied advanced start_backend.sh; skipping heredoc generation"

# Verify the bundled Python distribution is working
echo "🔍 Verifying bundled Python distribution..."
if "$BACKEND_DEST/python/bin/python3" --version; then
    echo "✅ Bundled Python is working correctly"
else
    echo "❌ ERROR: Bundled Python verification failed"
    exit 1
fi

# Test importing key dependencies
echo "🔍 Testing key dependencies..."
"$BACKEND_DEST/python/bin/python3" -c "
import sys
print(f'Python version: {sys.version}')
print(f'Python executable: {sys.executable}')

# Test key imports
try:
    import uvicorn
    print('✅ uvicorn imported successfully')
except ImportError as e:
    print(f'❌ uvicorn import failed: {e}')

try:
    import anthropic
    print('✅ anthropic imported successfully')
except ImportError as e:
    print(f'❌ anthropic import failed: {e}')

try:
    import soundfile
    print('✅ soundfile imported successfully')
except ImportError as e:
    print(f'❌ soundfile import failed: {e}')
" || echo "⚠️ Warning: Some dependency tests failed, but build will continue"

echo "✅ Backend build complete! Backend artifacts saved to: $BACKEND_DEST"
echo "   Build log: $LOG_FILE" 