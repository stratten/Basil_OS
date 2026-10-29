#!/opt/homebrew/bin/bash
# build/cmake/LibsndfileBundler/prepare_libsndfile_bundle_dylibs.sh
set -e
echo "Running prepare_libsndfile_bundle_dylibs.sh"

# Accept optional signing identity parameter
DEVELOPER_ID_CERT="${DEVELOPER_ID_CERT:-}"

CMAKE_INSTALL_PREFIX="$1"
INSTALL_SUBDIR="$2"

if [ -z "$CMAKE_INSTALL_PREFIX" ] || [ -z "$INSTALL_SUBDIR" ]; then
    echo "Error: CMAKE_INSTALL_PREFIX (\$1) or INSTALL_SUBDIR (\$2) not provided." >&2
    exit 1
fi

LIBS_DIR="$CMAKE_INSTALL_PREFIX/$INSTALL_SUBDIR"

echo "Fixing dylib IDs and paths in: $LIBS_DIR"

if [ ! -d "$LIBS_DIR" ]; then
    echo "Error: Dylibs directory $LIBS_DIR does not exist." >&2
    exit 1
fi

# Define the dylibs we've bundled (basename only)
declare -A BUNDLED_LIBS_MAP
BUNDLED_LIBS_MAP=(
    ["libsndfile.1.dylib"]=1
    ["libogg.0.dylib"]=1
    ["libvorbis.0.dylib"]=1
    ["libvorbisenc.2.dylib"]=1
    ["libFLAC.14.dylib"]=1
    ["libopus.0.dylib"]=1
    ["libmpg123.0.dylib"]=1
    ["libmp3lame.0.dylib"]=1
)

echo ""
echo "--- Processing bundled dylibs in $LIBS_DIR ---"
for lib_basename in "${!BUNDLED_LIBS_MAP[@]}"; do
    lib_path="$LIBS_DIR/$lib_basename"
    if [ -f "$lib_path" ]; then
        echo "  Processing $lib_basename:"
        # Change ID to be @rpath relative
        echo "    Setting ID to @rpath/$lib_basename"
        install_name_tool -id "@rpath/$lib_basename" "$lib_path" 2> >(grep -v "will invalidate the code signature" >&2) || echo "    Warning: Failed to set ID for $lib_basename (Command was: install_name_tool -id \"@rpath/$lib_basename\" \"$lib_path\")"
        
        # Change its dependencies on *other* bundled dylibs to also be @rpath relative
        echo "    Changing internal dependencies to @rpath/... for $lib_basename"
        OTOOL_OUTPUT_FILE=$(mktemp)
        if ! otool -L "$lib_path" > "$OTOOL_OUTPUT_FILE"; then
            echo "    Warning: otool -L failed for $lib_path"
            rm -f "$OTOOL_OUTPUT_FILE"
            continue
        fi

        # Skip the first line (which is the library's own ID path)
        tail -n +2 "$OTOOL_OUTPUT_FILE" | awk '{print $1}' | while IFS= read -r dep_path; do
            original_dep_basename=$(basename "$dep_path")
            
            if [[ -n "${BUNDLED_LIBS_MAP[$original_dep_basename]+_}" && "$dep_path" == /opt/homebrew/* ]]; then
                 echo "      Changing $dep_path -> @rpath/$original_dep_basename"
                 install_name_tool -change "$dep_path" "@rpath/$original_dep_basename" "$lib_path" 2> >(grep -v "will invalidate the code signature" >&2) || echo "      Warning: Failed to change $dep_path to @rpath/$original_dep_basename in $lib_basename (Command was: install_name_tool -change \"$dep_path\" \"@rpath/$original_dep_basename\" \"$lib_path\")"
            fi
        done
        rm -f "$OTOOL_OUTPUT_FILE"

        # Sign the dylib after all path modifications
        SIGN_SCRIPT_PATH="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/../TesseractBundler/sign_adhoc.sh"
        if [ -f "$SIGN_SCRIPT_PATH" ]; then
            if [ -n "$DEVELOPER_ID_CERT" ]; then
                echo "    Attempting to Developer ID sign $lib_path using $SIGN_SCRIPT_PATH..."
                if "$SIGN_SCRIPT_PATH" "$lib_path" "$DEVELOPER_ID_CERT"; then
                    echo "      ✅ Successfully signed $lib_basename"
                else
                    echo "      ⚠️ Warning: Failed to sign $lib_basename using $SIGN_SCRIPT_PATH"
                fi
            else
                echo "    Attempting to ad-hoc sign $lib_path using $SIGN_SCRIPT_PATH..."
                if "$SIGN_SCRIPT_PATH" "$lib_path"; then
                    echo "      ✅ Successfully signed $lib_basename"
                else
                    echo "      ⚠️ Warning: Failed to sign $lib_basename using $SIGN_SCRIPT_PATH"
                fi
            fi
        else
            echo "    ⚠️ Warning: sign_adhoc.sh script not found at $SIGN_SCRIPT_PATH"
        fi

        echo "    Verification for $lib_basename after changes (first 5 lines):"
        otool -L "$lib_path" | head -n 5 
        echo "    ------------------------------------"
    else
        echo "  Warning: Dylib $lib_path not found during processing loop."
    fi
done

echo ""
echo "prepare_libsndfile_bundle_dylibs.sh complete." 