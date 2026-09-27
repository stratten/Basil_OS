#!/opt/homebrew/bin/bash
# build/cmake/LibsndfileBundler/fix_soundfile_module_dylibs.sh
set -e
echo "Running fix_soundfile_module_dylibs.sh (CFFI version)"

VENV_PATH="$1"
STAGED_GOOD_DYLIBS_DIR="$2"

if [ -z "$VENV_PATH" ] || [ -z "$STAGED_GOOD_DYLIBS_DIR" ]; then
    echo "Error: VENV_PATH (\$1) or STAGED_GOOD_DYLIBS_DIR (\$2) not provided." >&2
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Venv path $VENV_PATH does not exist." >&2
    exit 1
fi

if [ ! -d "$STAGED_GOOD_DYLIBS_DIR" ]; then
    echo "Error: Staged good dylibs path $STAGED_GOOD_DYLIBS_DIR does not exist." >&2
    exit 1
fi

# Determine site-packages path
SITE_PACKAGES_DIR=$(find "$VENV_PATH/lib/" -maxdepth 1 -type d -name "python*" -print -quit)/site-packages
if [ -z "$SITE_PACKAGES_DIR" ] || [ ! -d "$SITE_PACKAGES_DIR" ]; then
    echo "Error: Could not find site-packages directory in $VENV_PATH/lib/" >&2
    exit 1
fi
echo "Found site-packages directory: $SITE_PACKAGES_DIR"

SOUNDFILE_DATA_DIR="$SITE_PACKAGES_DIR/_soundfile_data"

if [ ! -d "$SOUNDFILE_DATA_DIR" ]; then
    echo "Warning: _soundfile_data directory not found at $SOUNDFILE_DATA_DIR. Attempting to create it."
    mkdir -p "$SOUNDFILE_DATA_DIR"
    # Ensure __init__.py exists if we create the directory, as soundfile might expect it to be a package
    if [ ! -f "$SOUNDFILE_DATA_DIR/__init__.py" ]; then
        echo "Creating __init__.py in $SOUNDFILE_DATA_DIR"
        touch "$SOUNDFILE_DATA_DIR/__init__.py"
    fi
fi
echo "Target directory for dylibs: $SOUNDFILE_DATA_DIR"


# 1. Clean existing dylibs from _soundfile_data directory
echo "Cleaning existing *.dylib files from $SOUNDFILE_DATA_DIR"
find "$SOUNDFILE_DATA_DIR" -maxdepth 1 -type f -name '*.dylib' -delete

# 2. Copy our known-good, @rpath-ified dylibs into _soundfile_data
# These dylibs are already processed by prepare_libsndfile_bundle_dylibs.sh
# to have @rpath IDs and @rpath inter-dependencies.

echo "Copying known-good dylibs from $STAGED_GOOD_DYLIBS_DIR to $SOUNDFILE_DATA_DIR"

# Soundfile's CFFI loader typically tries to load "libsndfile.dylib" or a platform-specific name.
# We will provide "libsndfile.dylib" as the primary name.
TARGET_LIBSNDFILE_NAME="libsndfile.dylib"

if [ -f "$STAGED_GOOD_DYLIBS_DIR/libsndfile.1.dylib" ]; then
    cp "$STAGED_GOOD_DYLIBS_DIR/libsndfile.1.dylib" "$SOUNDFILE_DATA_DIR/$TARGET_LIBSNDFILE_NAME"
    echo "  Copied libsndfile.1.dylib as $TARGET_LIBSNDFILE_NAME to $SOUNDFILE_DATA_DIR"
else
    echo "  Error: libsndfile.1.dylib not found in $STAGED_GOOD_DYLIBS_DIR" >&2
    exit 1
fi

# Copy all other dylibs from the staged bundle (ogg, vorbis, flac, opus, etc.)
# These are dependencies of our new libsndfile.dylib
COPIED_DEPS_COUNT=0
for dylib_file in "$STAGED_GOOD_DYLIBS_DIR"/*.dylib; do
    dylib_basename=$(basename "$dylib_file")
    if [ "$dylib_basename" != "libsndfile.1.dylib" ]; then # Avoid double copy of primary libsndfile
        if [ -f "$dylib_file" ]; then # Ensure it's a file
            cp "$dylib_file" "$SOUNDFILE_DATA_DIR/"
            echo "  Copied $dylib_basename to $SOUNDFILE_DATA_DIR"
            COPIED_DEPS_COUNT=$((COPIED_DEPS_COUNT + 1))
        fi
    fi
done

if [ $COPIED_DEPS_COUNT -eq 0 ]; then
    echo "Warning: No dependency dylibs (ogg, vorbis, etc.) were found or copied from $STAGED_GOOD_DYLIBS_DIR." >&2
    echo "         This is okay if libsndfile.1.dylib has no external dependencies other than system libs." 
fi

# 3. Verification (No .so module modification needed for CFFI)
echo "Verification of dylibs in $SOUNDFILE_DATA_DIR:"
ls -la "$SOUNDFILE_DATA_DIR"

echo ""
echo "--- Verifying linkage of $SOUNDFILE_DATA_DIR/$TARGET_LIBSNDFILE_NAME ---"
otool -L "$SOUNDFILE_DATA_DIR/$TARGET_LIBSNDFILE_NAME"

# Optionally, verify a dependency too
if [ -f "$SOUNDFILE_DATA_DIR/libogg.0.dylib" ]; then
    echo ""
    echo "--- Verifying linkage of $SOUNDFILE_DATA_DIR/libogg.0.dylib ---"
    otool -L "$SOUNDFILE_DATA_DIR/libogg.0.dylib"
fi

# 4. Additional verification for code signing (critical for packaged apps)
echo ""
echo "--- Verifying code signature of bundled libraries ---"
for dylib_file in "$SOUNDFILE_DATA_DIR"/*.dylib; do
    if [ -f "$dylib_file" ]; then
        dylib_name=$(basename "$dylib_file")
        echo "Checking signature of $dylib_name:"
        codesign -dv "$dylib_file" 2>&1 || echo "Warning: $dylib_name signature check failed"
        echo ""
    fi
done

# 5. Create a test script to verify libsndfile can be loaded
echo ""
echo "--- Creating libsndfile test script ---"
TEST_SCRIPT="$SOUNDFILE_DATA_DIR/test_libsndfile.py"
cat > "$TEST_SCRIPT" << 'EOF'
#!/usr/bin/env python3
import sys
import os

# Add the soundfile data directory to the library path
soundfile_data_dir = os.path.dirname(os.path.abspath(__file__))
if hasattr(os, 'add_dll_directory'):  # Windows
    os.add_dll_directory(soundfile_data_dir)
else:  # macOS/Linux
    import ctypes
    # Try to load libsndfile directly from our bundled location
    try:
        lib_path = os.path.join(soundfile_data_dir, 'libsndfile.dylib')
        if os.path.exists(lib_path):
            ctypes.CDLL(lib_path)
            print(f"✅ Successfully loaded libsndfile from: {lib_path}")
        else:
            print(f"❌ libsndfile.dylib not found at: {lib_path}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to load libsndfile: {e}")
        sys.exit(1)

# Test soundfile import
try:
    import soundfile as sf
    print("✅ soundfile module imported successfully")
    
    # Test soundfile functionality with a minimal operation
    # This will fail if the underlying libsndfile can't be loaded
    try:
        # Get available formats - this tests the C library binding
        formats = sf.available_formats()
        print(f"✅ libsndfile binding working - {len(formats)} formats available")
    except Exception as e:
        print(f"❌ libsndfile binding failed: {e}")
        sys.exit(1)
        
except ImportError as e:
    print(f"❌ Failed to import soundfile: {e}")
    sys.exit(1)
    
print("🎉 All libsndfile tests passed!")
EOF

chmod +x "$TEST_SCRIPT"
echo "Test script created at: $TEST_SCRIPT"

# 6. Ensure proper permissions on all bundled libraries
echo ""
echo "--- Setting proper permissions on bundled libraries ---"
for dylib_file in "$SOUNDFILE_DATA_DIR"/*.dylib; do
    if [ -f "$dylib_file" ]; then
        chmod 755 "$dylib_file"
        echo "Set permissions 755 on $(basename "$dylib_file")"
    fi
done

echo ""
echo "fix_soundfile_module_dylibs.sh (CFFI version) complete." 