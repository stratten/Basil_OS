#!/bin/bash
# Script to fix dylib references for Python's soundfile C extension (_soundfile_data*.so)
# to use a known-good, fully-featured set of libsndfile and its dependencies.

# This script should be called by your main backend build process AFTER:
# 1. `poetry install` (or equivalent) has installed the `soundfile` Python package.
# 2. The `LibsndfileBundler` CMake project has built and installed a known-good `libsndfile.1.dylib`
#    and all its dependencies (libogg, libvorbis, etc.) into a staging directory.

# Expected arguments:
# $1: VENV_PATH: Path to the root of the bundled Python virtual environment
#     (e.g., YourApp.app/Contents/Resources/backend/venv)
# $2: STAGED_LIBSNDFILE_BUNDLE_DIR: Path to the directory where LibsndfileBundler
#     installed the good libsndfile.1.dylib and all its dependencies.
#     (e.g., YourApp.app/Contents/Resources/backend/dependencies/libs_sndfile_bundle)

set -e # Exit on error

VENV_PATH="$1"
STAGED_LIBSNDFILE_BUNDLE_DIR="$2"

# --- Sanity Checks ---
echo "--- Running fix_soundfile_module_dylibs.sh ---"
echo "Python Venv Path: ${VENV_PATH}"
echo "Staged Libsndfile Bundle Dir: ${STAGED_LIBSNDFILE_BUNDLE_DIR}"

if [ -z "${VENV_PATH}" ] || [ -z "${STAGED_LIBSNDFILE_BUNDLE_DIR}" ]; then
    echo "Error: Missing required arguments: VENV_PATH and STAGED_LIBSNDFILE_BUNDLE_DIR." >&2
    exit 1
fi
if [ ! -d "${VENV_PATH}" ]; then
    echo "Error: Python Venv path not found: ${VENV_PATH}" >&2
    exit 1
fi
if [ ! -d "${STAGED_LIBSNDFILE_BUNDLE_DIR}" ]; then
    echo "Error: Staged Libsndfile bundle directory not found: ${STAGED_LIBSNDFILE_BUNDLE_DIR}" >&2
    exit 1
fi

# --- Determine Paths --- 
PYTHON_VERSION_MAJOR_MINOR=$(basename "$(find "${VENV_PATH}/lib" -maxdepth 1 -type d -name 'python*.*' -print -quit)")
if [ -z "${PYTHON_VERSION_MAJOR_MINOR}" ]; then
    echo "Error: Could not determine Python version from venv path: ${VENV_PATH}/lib" >&2
    exit 1
fi
echo "Determined Python version: ${PYTHON_VERSION_MAJOR_MINOR}"

SITE_PACKAGES_DIR="${VENV_PATH}/lib/${PYTHON_VERSION_MAJOR_MINOR}/site-packages"
SOUNDFILE_BUILDS_DIR="${SITE_PACKAGES_DIR}/soundfile_builds"

if [ ! -d "${SITE_PACKAGES_DIR}" ]; then
    echo "Error: site-packages directory not found: ${SITE_PACKAGES_DIR}" >&2
    exit 1
fi

# The C extension module for soundfile
SOUNDFILE_SO_PATH=$(find "${SITE_PACKAGES_DIR}" -name "_soundfile_data*.so" -print -quit)
if [ -z "${SOUNDFILE_SO_PATH}" ]; then
    echo "Error: _soundfile_data*.so not found in ${SITE_PACKAGES_DIR}" >&2
    exit 1
fi
echo "Found soundfile C extension: ${SOUNDFILE_SO_PATH}"

# --- Replace Vendored libsndfile and its dependencies ---
echo "Preparing to replace vendored libraries in ${SOUNDFILE_BUILDS_DIR}"

# Create the soundfile_builds directory if it doesn't exist (it should, if soundfile installed correctly)
mkdir -p "${SOUNDFILE_BUILDS_DIR}"

# Remove the existing (potentially problematic) vendored libsndfile.dylib
if [ -f "${SOUNDFILE_BUILDS_DIR}/libsndfile.dylib" ]; then
    echo "Removing existing vendored ${SOUNDFILE_BUILDS_DIR}/libsndfile.dylib"
    rm -f "${SOUNDFILE_BUILDS_DIR}/libsndfile.dylib"
fi

echo "Copying known-good libsndfile and its dependencies from ${STAGED_LIBSNDFILE_BUNDLE_DIR} to ${SOUNDFILE_BUILDS_DIR}"

# Copy all dylibs from our CMake bundle into soundfile_builds
# The CMake script should have already fixed their internal @id to be @rpath/libname.dylib
for lib_path in "${STAGED_LIBSNDFILE_BUNDLE_DIR}"/*.dylib; do
    if [ -f "${lib_path}" ]; then
        lib_basename=$(basename "${lib_path}")
        target_path="${SOUNDFILE_BUILDS_DIR}/${lib_basename}"
        
        # If the main libsndfile.1.dylib is being copied, also create the symlink/copy for libsndfile.dylib
        if [ "${lib_basename}" == "libsndfile.1.dylib" ]; then
            echo "Copying ${lib_path} to ${SOUNDFILE_BUILDS_DIR}/libsndfile.1.dylib AND as libsndfile.dylib"
            cp "${lib_path}" "${SOUNDFILE_BUILDS_DIR}/libsndfile.1.dylib"
            cp "${lib_path}" "${SOUNDFILE_BUILDS_DIR}/libsndfile.dylib" # This is what soundfile loads by name
        else
            echo "Copying ${lib_path} to ${target_path}"
            cp "${lib_path}" "${target_path}"
        fi
    fi
done

# --- Fix Linkage for _soundfile_data*.so ---
# It needs to find the new libsndfile.dylib (which is our libsndfile.1.dylib) in soundfile_builds.

# What _soundfile_data*.so currently links to for libsndfile might vary:
# - Could be the original Homebrew path if built locally: /opt/homebrew/opt/libsndfile/lib/libsndfile.1.dylib
# - Could be @rpath/libsndfile.dylib if soundfile's setup.py already tried to be clever.
# We need to find out what it is and change it to @rpath/libsndfile.dylib to be sure.

# First, ensure _soundfile_data.so is looking for "libsndfile.dylib" via rpath.
# We'll try to change common known original paths for libsndfile.1.dylib to @rpath/libsndfile.dylib
# (soundfile.PATHS was looking for libsndfile.dylib so we assume _soundfile_data.so might too, or its original build path)
ORIGINAL_BREW_PATH_MAIN="/opt/homebrew/opt/libsndfile/lib/libsndfile.1.dylib"
ORIGINAL_BREW_PATH_SYMLINK="/opt/homebrew/opt/libsndfile/lib/libsndfile.dylib"
EXISTING_RPATH_TARGET="@rpath/libsndfile.dylib" # If it already uses rpath

echo "Modifying ${SOUNDFILE_SO_PATH} to use @rpath/libsndfile.dylib"

# Try changing from specific versioned path
xcrun install_name_tool -change "${ORIGINAL_BREW_PATH_MAIN}" \
                        "@rpath/libsndfile.dylib" \
                        "${SOUNDFILE_SO_PATH}" || echo "Note: Did not find ${ORIGINAL_BREW_PATH_MAIN} in ${SOUNDFILE_SO_PATH}"

# Try changing from symlink path
xcrun install_name_tool -change "${ORIGINAL_BREW_PATH_SYMLINK}" \
                        "@rpath/libsndfile.dylib" \
                        "${SOUNDFILE_SO_PATH}" || echo "Note: Did not find ${ORIGINAL_BREW_PATH_SYMLINK} in ${SOUNDFILE_SO_PATH}"

# If it was already @rpath/libsndfile.dylib, the above won't do anything, which is fine.

# Now, add the crucial rpath to _soundfile_data*.so so it can find things in soundfile_builds.
# @loader_path is relative to the binary being loaded (_soundfile_data.so).
# soundfile_builds is a subdirectory of where soundfile.py is, and _soundfile_data.so is usually alongside soundfile.py.
RPATH_FOR_SOUNDFILE_SO="@loader_path/soundfile_builds"
echo "Adding RPATH '${RPATH_FOR_SOUNDFILE_SO}' to ${SOUNDFILE_SO_PATH}"
xcrun install_name_tool -add_rpath "${RPATH_FOR_SOUNDFILE_SO}" "${SOUNDFILE_SO_PATH}"

# --- Verification --- 
echo "--- Verifying linkages ---"
echo "Verifying: ${SOUNDFILE_SO_PATH}"
otool -L "${SOUNDFILE_SO_PATH}"

echo "Verifying libraries in ${SOUNDFILE_BUILDS_DIR}:"
for lib in "${SOUNDFILE_BUILDS_DIR}"/*.dylib; do
    if [ -f "${lib}" ]; then
        echo "  Checking: $(basename "${lib}")"
        otool -L "${lib}"
    fi
done

echo "--- fix_soundfile_module_dylibs.sh finished ---" 