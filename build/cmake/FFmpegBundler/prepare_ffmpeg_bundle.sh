#!/opt/homebrew/bin/bash

# Exit on error
set -e

# Accept optional signing identity parameter
DEVELOPER_ID_CERT="${DEVELOPER_ID_CERT:-}"

echo_green() {
    echo -e "\033[0;32m$1\033[0m"
}

echo_red() {
    echo -e "\033[0;31m$1\033[0m"
}

echo_yellow() {
    echo -e "\033[0;33m$1\033[0m"
}

if [ "$#" -ne 1 ]; then
    echo_red "❌ ERROR: Incorrect number of arguments supplied to prepare_ffmpeg_bundle.sh"
    echo_red "Usage: ./prepare_ffmpeg_bundle.sh <CMAKE_INSTALL_PREFIX>"
    exit 1
fi

CMAKE_INSTALL_PREFIX="$1"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SIGN_ADHOC_SCRIPT_PATH="${SCRIPT_DIR}/../TesseractBundler/sign_adhoc.sh"

if [ ! -f "$SIGN_ADHOC_SCRIPT_PATH" ]; then
    echo_red "❌ ERROR: Ad-hoc signing script not found at ${SIGN_ADHOC_SCRIPT_PATH}"
    exit 1
fi
chmod +x "$SIGN_ADHOC_SCRIPT_PATH"

FFMPEG_EXE_PATH="${CMAKE_INSTALL_PREFIX}/bin/ffmpeg"
BUNDLED_LIBS_DIR="${CMAKE_INSTALL_PREFIX}/dependencies/libs" # All dylibs end up here

if [ ! -f "$FFMPEG_EXE_PATH" ]; then
    echo_red "❌ ERROR: Bundled ffmpeg executable not found at ${FFMPEG_EXE_PATH}"
    exit 1
fi
if [ ! -d "$BUNDLED_LIBS_DIR" ]; then
    echo_red "❌ ERROR: Bundled libraries directory not found at ${BUNDLED_LIBS_DIR}. CMake should have created it and placed primary FFmpeg dylibs there."
    exit 1
fi

echo "🔧 Processing FFmpeg bundle installed at: ${CMAKE_INSTALL_PREFIX}"
echo "   FFmpeg executable: ${FFMPEG_EXE_PATH}"
echo "   Bundled libraries dir: ${BUNDLED_LIBS_DIR}"

# Keep track of processed dylibs to avoid cycles and redundant work
declare -A PROCESSED_DYLIBS

# Function to recursively process a dylib or executable
# Arg1: Path to the item to process (either ffmpeg executable or a dylib)
# Arg2: "executable" or "dylib" to indicate the type of item
process_item() {
    local item_path="$1"
    local item_type="$2"
    local item_basename=$(basename "${item_path}")

    if [[ -n "${PROCESSED_DYLIBS[${item_basename}]}" ]]; then
        # echo_yellow "    ℹ️ Already processed or queued: ${item_basename}, skipping."
        return 0
    fi
    PROCESSED_DYLIBS[${item_basename}]=1
    echo "  ⚙️ Processing ${item_type}: ${item_basename} (Path: ${item_path})"

    # Get dependencies
    local otool_output_file=$(mktemp)
    if ! otool -L "${item_path}" > "${otool_output_file}"; then
        echo_red "    ❌ ERROR: otool -L failed for ${item_path}"
        rm -f "${otool_output_file}"
        return 1
    fi

    # For dylibs, first change their own ID if they are in BUNDLED_LIBS_DIR
    if [ "${item_type}" == "dylib" ] && [[ "${item_path}" == "${BUNDLED_LIBS_DIR}/"* ]]; then
        local new_id="@rpath/${item_basename}"
        echo "    🆔 Setting ID for ${item_basename} to ${new_id}"
        if ! install_name_tool -id "${new_id}" "${item_path}" 2> >(grep -v "will invalidate the code signature" >&2); then
            echo_red "      ❌ ERROR: install_name_tool -id failed for ${item_path}"
        fi
    fi

    # Iterate over dependencies (skip the first line which is the item itself)
    tail -n +2 "${otool_output_file}" | awk '{print $1}' | while IFS= read -r dep_path; do
        local dep_basename=$(basename "${dep_path}")
        local original_dep_path_to_copy="${dep_path}" # Path to use for copy source, defaults to dep_path

        # Special handling for libjxl.0.11.dylib's dependency on libjxl_cms.0.11.dylib
        # This is because libjxl.0.11.dylib itself refers to libjxl_cms.0.11.dylib via @rpath
        # which our script doesn't normally resolve back to a Homebrew path for copying.
        if [[ "${item_basename}" == "libjxl.0.11.dylib" && "${dep_basename}" == "libjxl_cms.0.11.dylib" && "${dep_path}" == "@rpath/"* ]]; then
            original_dep_path_to_copy="/opt/homebrew/opt/jpeg-xl/lib/libjxl_cms.0.11.dylib" # Hardcoded original path
            echo "    ⚠️ Applying special handling for ${item_basename} -> ${dep_basename}. Original source for copy assumed: ${original_dep_path_to_copy}"
        fi

        # ENHANCED: Process ALL Homebrew dependencies AND any @rpath dependencies we can find in system
        should_process_dependency=false
        
        # Every absolute dependency outside macOS must be bundled, including the project-built LGPL FFmpeg prefix.
        if [[ "${original_dep_path_to_copy}" == /* && "${original_dep_path_to_copy}" != /usr/lib/* && "${original_dep_path_to_copy}" != /System/Library/* ]]; then
            should_process_dependency=true
        # For any @rpath dependency, try to find it in the system (comprehensive search)
        elif [[ "${dep_path}" == "@rpath/"* ]]; then
            # First check if it already exists in our bundle (e.g. placed by Tesseract CMake step)
            if [[ -f "${BUNDLED_LIBS_DIR}/${dep_basename}" ]]; then
                original_dep_path_to_copy="${BUNDLED_LIBS_DIR}/${dep_basename}"
                should_process_dependency=true
                echo "    ✅ @rpath dependency ${dep_basename} already in bundle, skipping Homebrew search"
            else
                # Try to find ANY @rpath dependency in common Homebrew locations
                echo "    🔍 Searching for @rpath dependency: ${dep_basename}"
                if [[ -f "/opt/homebrew/lib/${dep_basename}" ]]; then
                    original_dep_path_to_copy="/opt/homebrew/lib/${dep_basename}"
                    should_process_dependency=true
                    echo "    ✅ Found @rpath dependency: ${dep_basename} at ${original_dep_path_to_copy}"
                elif [[ -f "/usr/local/lib/${dep_basename}" ]]; then
                    original_dep_path_to_copy="/usr/local/lib/${dep_basename}"
                    should_process_dependency=true
                    echo "    ✅ Found @rpath dependency: ${dep_basename} at ${original_dep_path_to_copy}"
                else
                    # Search in Homebrew opt directories using find -L to follow symlinks (keg-only packages)
                    opt_search_result=$(find -L /opt/homebrew/opt -name "${dep_basename}" -type f 2>/dev/null | head -1)
                    if [[ -n "$opt_search_result" && -f "$opt_search_result" ]]; then
                        original_dep_path_to_copy="$opt_search_result"
                        should_process_dependency=true
                        echo "    ✅ Found @rpath dependency: ${dep_basename} at ${original_dep_path_to_copy}"
                    else
                        echo "    ❌ Could not find @rpath dependency: ${dep_basename}"
                    fi
                fi
            fi
        fi
        
        if [[ "$should_process_dependency" == "true" ]] && \
           [[ "${original_dep_path_to_copy}" != "/usr/lib/"* && "${original_dep_path_to_copy}" != "/System/Library/"* ]]; then

            local bundled_dep_target_path="${BUNDLED_LIBS_DIR}/${dep_basename}"
            local rpath_for_change=""

            if [ "${item_type}" == "executable" ]; then
                rpath_for_change="@executable_path/../dependencies/libs/${dep_basename}"
            else # item_type is dylib
                # Use @loader_path so dylibs can find each other in the same directory
                rpath_for_change="@loader_path/${dep_basename}"
            fi

            # The install_name_tool -change should use the dep_path as listed by otool for the item_path being processed.
            # This path might be @rpath/... or an absolute /opt/homebrew/... path.
            echo "    🔗 Fixing dependency in ${item_basename}: ${dep_path} -> ${rpath_for_change}"
            if ! install_name_tool -change "${dep_path}" "${rpath_for_change}" "${item_path}" 2> >(grep -v "will invalidate the code signature" >&2); then
                echo_yellow "      ⚠️ WARNING: install_name_tool -change failed for ${dep_path} in ${item_path}. It might already be correct or non-critical."
            fi

            # If the dependency isn't already in BUNDLED_LIBS_DIR, copy it (using original_dep_path_to_copy) and process it
            if [ ! -f "${bundled_dep_target_path}" ]; then
                if [ -f "${original_dep_path_to_copy}" ]; then # Ensure original dependency exists before copying
                    echo "      ➕ Copying new dependency ${dep_basename} from ${original_dep_path_to_copy} to ${BUNDLED_LIBS_DIR}/"
                    cp "${original_dep_path_to_copy}" "${bundled_dep_target_path}"
                    chmod 755 "${bundled_dep_target_path}" # Ensure readable and executable

                    # Recursively process this newly copied dylib
                    process_item "${bundled_dep_target_path}" "dylib"
                else
                    echo_red "      ❌ ERROR: Original dependency ${original_dep_path_to_copy} not found. Cannot copy ${dep_basename} (needed by ${item_basename}). This could be a critical issue."
                    # Consider if this should be fatal, for now, it continues
                fi
            else
                # If already exists, ensure it's processed (e.g. if it was a primary dylib)
                if [[ -z "${PROCESSED_DYLIBS[${dep_basename}]}" ]]; then
                     process_item "${bundled_dep_target_path}" "dylib"
                fi
            fi
        fi
    done
    rm -f "${otool_output_file}"

    # Sign the item after all its paths are modified
    if [ -n "$DEVELOPER_ID_CERT" ]; then
        echo "    🔏 Developer ID signing ${item_type}: ${item_basename}"
        if ! "${SIGN_ADHOC_SCRIPT_PATH}" "${item_path}" "$DEVELOPER_ID_CERT"; then
            echo_red "      ❌ ERROR: Failed to sign ${item_path}"
        else
            echo_green "      ✅ Successfully signed ${item_path}"
        fi
    else
        echo "    🔏 Ad-hoc signing ${item_type}: ${item_basename}"
        if ! "${SIGN_ADHOC_SCRIPT_PATH}" "${item_path}"; then
            echo_red "      ❌ ERROR: Failed to sign ${item_path}"
        else
            echo_green "      ✅ Successfully signed ${item_path}"
        fi
    fi
    
    echo "    🔍 Verifying ${item_type} ${item_basename} after processing:"
    otool -L "${item_path}" | tail -n +2 | awk '{print "      " $1}' || echo_yellow "      ⚠️ Could not verify with otool -L"

}

# First, process all primary dylibs that CMake already copied to BUNDLED_LIBS_DIR
echo "🔄 Initial pass: Processing primary FFmpeg dylibs already in ${BUNDLED_LIBS_DIR}..."
for primary_dylib_path in "${BUNDLED_LIBS_DIR}"/libav*.dylib "${BUNDLED_LIBS_DIR}"/libsw*.dylib "${BUNDLED_LIBS_DIR}"/libpostproc*.dylib; do
    if [ -f "${primary_dylib_path}" ]; then # Check if glob found any files
        process_item "${primary_dylib_path}" "dylib"
    fi
done

# Then, process the main ffmpeg executable
echo "🔄 Main pass: Processing FFmpeg executable ${FFMPEG_EXE_PATH}..."
process_item "${FFMPEG_EXE_PATH}" "executable"

# Add rpath to FFmpeg executable so it can find bundled libraries
echo "🔄 Adding rpath to FFmpeg executable for bundled libraries..."
if ! install_name_tool -add_rpath "@executable_path/../dependencies/libs" "${FFMPEG_EXE_PATH}" 2> >(grep -v "will invalidate the code signature" >&2); then
    echo_yellow "⚠️ WARNING: Failed to add rpath to FFmpeg executable. It may not find bundled libraries."
else
    echo_green "✅ Successfully added rpath to FFmpeg executable"
fi

# Re-sign the executable after modifying it with install_name_tool
echo "🔏 Re-signing FFmpeg executable after rpath modification..."
if [ -n "$DEVELOPER_ID_CERT" ] && [ "$DEVELOPER_ID_CERT" != "-" ]; then
    echo "    🔏 Developer ID signing FFmpeg executable..."
    if ! codesign --force --sign "$DEVELOPER_ID_CERT" "${FFMPEG_EXE_PATH}"; then
        echo_red "      ❌ ERROR: Failed to sign FFmpeg executable with Developer ID"
    else
        echo_green "      ✅ Successfully signed FFmpeg executable with Developer ID"
    fi
else
    echo "    🔏 Ad-hoc signing FFmpeg executable..."
    if ! "${SIGN_ADHOC_SCRIPT_PATH}" "${FFMPEG_EXE_PATH}"; then
        echo_red "      ❌ ERROR: Failed to ad-hoc sign FFmpeg executable"
    else
        echo_green "      ✅ Successfully ad-hoc signed FFmpeg executable"
    fi
fi

echo_green "✅ FFmpeg bundle preparation script finished successfully." 