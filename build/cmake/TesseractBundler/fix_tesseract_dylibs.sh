#!/opt/homebrew/bin/bash
# build/cmake/TesseractBundler/fix_tesseract_dylibs.sh
set -e
echo "Running fix_tesseract_dylibs.sh"

BUNDLE_ROOT="$1"
if [ -z "$BUNDLE_ROOT" ]; then
    echo "Error: Bundle root path not provided to fix_tesseract_dylibs.sh" >&2
    exit 1
fi

BIN_DIR="$BUNDLE_ROOT/bin"
LIBS_DIR="$BUNDLE_ROOT/dependencies/libs" # This must match INSTALL_LIB_DIR in CMakeLists.txt
TESS_EXEC="$BIN_DIR/tesseract"

echo "Fixing dylib paths in: $BUNDLE_ROOT"
echo "  Executable: $TESS_EXEC"
echo "  Libs dir: $LIBS_DIR"

# Define the dylibs we've bundled (basename only)
# This list should correspond to the DESIRED_DYLIB_FILENAME used in CMakeLists.txt's RENAME.
declare -A BUNDLED_LIBS_MAP
BUNDLED_LIBS_MAP=(
    ["libtesseract.5.dylib"]=1
    ["libleptonica.6.dylib"]=1
    ["libarchive.13.dylib"]=1
    ["libpng16.16.dylib"]=1
    ["libjpeg.8.dylib"]=1
    ["libgif.dylib"]=1
    ["libtiff.6.dylib"]=1
    ["libwebp.7.dylib"]=1
    ["libwebpmux.3.dylib"]=1
    ["libsharpyuv.0.dylib"]=1
    ["libopenjp2.7.dylib"]=1
    ["liblzma.5.dylib"]=1
    ["libzstd.1.dylib"]=1
    ["liblz4.1.dylib"]=1
    ["libb2.1.dylib"]=1
)

# Dynamically detect the actual paths from the source tesseract binary
# This avoids hardcoding version-specific Cellar paths that change with Homebrew updates
echo "Detecting actual library paths from source Tesseract binary..."
HOMEBREW_TESSERACT_BIN="/opt/homebrew/bin/tesseract"

if [ ! -f "$HOMEBREW_TESSERACT_BIN" ]; then
    echo "Error: Homebrew tesseract binary not found at $HOMEBREW_TESSERACT_BIN" >&2
    exit 1
fi

# Parse otool output to get the actual paths
declare -A ORIGINAL_HOMEBREW_PATHS
while IFS= read -r line; do
    # Skip the first line (binary path itself)
    if [[ "$line" == *"tesseract:"* ]]; then
        continue
    fi
    
    # Extract the path (first field before version info)
    dep_path=$(echo "$line" | awk '{print $1}')
    
    # Only process Homebrew paths
    if [[ "$dep_path" == /opt/homebrew/* ]]; then
        basename_dep=$(basename "$dep_path")
        ORIGINAL_HOMEBREW_PATHS["$basename_dep"]="$dep_path"
        echo "  Detected: $basename_dep -> $dep_path"
    fi
done < <(otool -L "$HOMEBREW_TESSERACT_BIN")

# Also add standard opt paths for dylib-to-dylib dependencies
# These are usually in /opt/homebrew/opt/... format
ORIGINAL_HOMEBREW_PATHS["libpng16.16.dylib"]="/opt/homebrew/opt/libpng/lib/libpng16.16.dylib"
ORIGINAL_HOMEBREW_PATHS["libjpeg.8.dylib"]="/opt/homebrew/opt/jpeg-turbo/lib/libjpeg.8.dylib"
ORIGINAL_HOMEBREW_PATHS["libgif.dylib"]="/opt/homebrew/opt/giflib/lib/libgif.dylib"
ORIGINAL_HOMEBREW_PATHS["libtiff.6.dylib"]="/opt/homebrew/opt/libtiff/lib/libtiff.6.dylib"
ORIGINAL_HOMEBREW_PATHS["libwebp.7.dylib"]="/opt/homebrew/opt/webp/lib/libwebp.7.dylib"
ORIGINAL_HOMEBREW_PATHS["libwebpmux.3.dylib"]="/opt/homebrew/opt/webp/lib/libwebpmux.3.dylib"
ORIGINAL_HOMEBREW_PATHS["libsharpyuv.0.dylib"]="/opt/homebrew/opt/webp/lib/libsharpyuv.0.dylib"
ORIGINAL_HOMEBREW_PATHS["libopenjp2.7.dylib"]="/opt/homebrew/opt/openjpeg/lib/libopenjp2.7.dylib"
ORIGINAL_HOMEBREW_PATHS["liblzma.5.dylib"]="/opt/homebrew/opt/xz/lib/liblzma.5.dylib"
ORIGINAL_HOMEBREW_PATHS["libzstd.1.dylib"]="/opt/homebrew/opt/zstd/lib/libzstd.1.dylib"
ORIGINAL_HOMEBREW_PATHS["liblz4.1.dylib"]="/opt/homebrew/opt/lz4/lib/liblz4.1.dylib"
ORIGINAL_HOMEBREW_PATHS["libb2.1.dylib"]="/opt/homebrew/opt/libb2/lib/libb2.1.dylib"

echo "Path detection complete."
echo ""


# 1. Fix IDs and dependencies for each bundled dylib
echo ""
echo "--- Processing bundled dylibs in $LIBS_DIR ---"
for lib_basename in "${!BUNDLED_LIBS_MAP[@]}"; do
    lib_path="$LIBS_DIR/$lib_basename"
    if [ -f "$lib_path" ]; then
        echo "  Processing $lib_basename:"
        # Change ID to be @rpath relative for better flexibility with RPATH settings on executables
        echo "    Setting ID to @rpath/$lib_basename"
        install_name_tool -id "@rpath/$lib_basename" "$lib_path" 2> >(grep -v "will invalidate the code signature" >&2) || echo "    Warning: Failed to set ID for $lib_basename"
        
        # Change its dependencies on *other* bundled dylibs to also be @rpath relative
        echo "    Changing internal dependencies to @rpath/... for $lib_basename"
        otool -L "$lib_path" | tail -n +2 | awk '{print $1}' | while IFS= read -r dep_path; do
            original_dep_basename=$(basename "$dep_path")
            # Check if this dependency is one of the dylibs we bundled AND it's an absolute Homebrew path
            if [[ -n "${BUNDLED_LIBS_MAP[$original_dep_basename]+_}" && "$dep_path" == /opt/homebrew/* ]]; then
                 echo "      Changing $dep_path -> @rpath/$original_dep_basename"
                 install_name_tool -change "$dep_path" "@rpath/$original_dep_basename" "$lib_path" 2> >(grep -v "will invalidate the code signature" >&2) || echo "      Warning: Failed to change $dep_path for $lib_basename"
            fi
        done
        echo "    Verification for $lib_basename after changes:"
        otool -L "$lib_path" | head -n 5 # Show top few lines
        echo "    ------------------------------------"
    else
        echo "  Warning: Dylib $lib_path not found during processing loop."
    fi
done

# 2. Fix dependencies for the Tesseract executable
echo ""
echo "--- Processing Tesseract executable $TESS_EXEC ---"
if [ -f "$TESS_EXEC" ]; then
    # Change its direct Homebrew dependencies to point to the bundled versions using @executable_path
    # This targets the primary dependencies of Tesseract.
    # Using the specific original paths from ORIGINAL_HOMEBREW_PATHS for these.
    echo "  Changing direct dependencies of Tesseract executable..."
    for lib_basename in libtesseract.5.dylib libleptonica.6.dylib libarchive.13.dylib; do
        original_path="${ORIGINAL_HOMEBREW_PATHS[$lib_basename]}"
        if [ -n "$original_path" ]; then
            echo "    Changing $original_path -> @executable_path/../dependencies/libs/$lib_basename"
            install_name_tool -change "$original_path" "@executable_path/../dependencies/libs/$lib_basename" "$TESS_EXEC" 2> >(grep -v "will invalidate the code signature" >&2) || echo "    Warning: Failed to change $original_path for $TESS_EXEC"
        else
            echo "    Warning: Original Homebrew path for $lib_basename not defined in script."
        fi
    done

    echo "  Adding RPATH @executable_path/../dependencies/libs to $TESS_EXEC"
    install_name_tool -add_rpath "@executable_path/../dependencies/libs" "$TESS_EXEC" 2> >(grep -v "will invalidate the code signature" >&2) || echo "    Warning: Failed to add RPATH to $TESS_EXEC"

    echo "  Verification for $TESS_EXEC after changes:"
    otool -L "$TESS_EXEC"
else
    echo "  Warning: Tesseract executable $TESS_EXEC not found for processing."
fi

echo ""
echo "fix_tesseract_dylibs.sh complete." 