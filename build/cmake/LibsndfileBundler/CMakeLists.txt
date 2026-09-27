cmake_minimum_required(VERSION 3.15)
project(LibsndfileBundler LANGUAGES C CXX)

# --- Configuration ---
# Attempt to find Homebrew prefix automatically
if(DEFINED ENV{HOMEBREW_PREFIX})
    set(HOMEBREW_DIR "$ENV{HOMEBREW_PREFIX}")
else()
    # Fallback for common Homebrew locations on arm64 and x86_64
    if(EXISTS "/opt/homebrew")
        set(HOMEBREW_DIR "/opt/homebrew")
    elseif(EXISTS "/usr/local/Homebrew") # Less common but possible
        set(HOMEBREW_DIR "/usr/local/Homebrew")
    elseif(EXISTS "/usr/local") # Older Homebrew or other package managers
        set(HOMEBREW_DIR "/usr/local")
    else()
        message(FATAL_ERROR "Homebrew prefix not found. Please set HOMEBREW_PREFIX environment variable or update this script.")
    endif()
endif()

message(STATUS "Using Homebrew directory: ${HOMEBREW_DIR}")

# Base install directory for these libraries within the bundle
set(INSTALL_SUBDIR "dependencies/libs_sndfile_bundle") # Changed to a more specific subdir for clarity
set(FULL_INSTALL_LIB_DIR "${CMAKE_INSTALL_PREFIX}/${INSTALL_SUBDIR}")

# --- Helper Macro for Importing and Installing Dylibs ---
# @param TARGET_NAME: The CMake target name for this library.
# @param DYLIB_BASENAME: The base filename of the dylib (e.g., "libsndfile.1.dylib").
# @param SOURCE_LIB_DIR: The directory where the original dylib is located.
macro(add_imported_dylib TARGET_NAME DYLIB_BASENAME SOURCE_LIB_DIR)
    set(DYLIB_PATH "${SOURCE_LIB_DIR}/${DYLIB_BASENAME}")

    if(NOT EXISTS ${DYLIB_PATH})
        message(WARNING "Dylib ${DYLIB_PATH} not found. This might be an optional dependency or an error in configuration.")
        return()
    endif()

    # Resolve symlinks to get the path to the actual file
    # This is important because Homebrew's /opt paths are often symlinks to Cellar paths
    file(REAL_PATH "${DYLIB_PATH}" ACTUAL_DYLIB_FILE_PATH)

    if(NOT EXISTS ${ACTUAL_DYLIB_FILE_PATH})
        message(WARNING "Actual dylib file not found at ${ACTUAL_DYLIB_FILE_PATH} (resolved from ${DYLIB_PATH}) for ${DYLIB_BASENAME}.")
        return()
    endif()
    
    # We don't strictly need to define an imported target if we're just copying files
    # and an external script handles all dylib modifications.
    # However, it can be good for structure if CMake needed to know about these for other reasons.

    # Install the actual dylib file, renaming it to the expected basename
    install(FILES "${ACTUAL_DYLIB_FILE_PATH}"
            DESTINATION "${INSTALL_SUBDIR}" # Relative to CMAKE_INSTALL_PREFIX
            RENAME "${DYLIB_BASENAME}"       # Install as libsndfile.1.dylib, not the resolved versioned name from Cellar
            COMPONENT RuntimeLibraries
            PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE) # Typical 0755

    message(STATUS "Prepared ${DYLIB_BASENAME} for bundling (copying from ${ACTUAL_DYLIB_FILE_PATH} to ${INSTALL_SUBDIR}/${DYLIB_BASENAME}).")
endmacro()

# --- Define libsndfile and its dependencies ---

# libsndfile itself
set(HOMEBREW_LIBSNDFILE_OPT_DIR "${HOMEBREW_DIR}/opt/libsndfile")
set(HOMEBREW_LIBSNDFILE_LIB_DIR "${HOMEBREW_LIBSNDFILE_OPT_DIR}/lib")
add_imported_dylib(libsndfile_target "libsndfile.1.dylib" "${HOMEBREW_LIBSNDFILE_LIB_DIR}")

# libogg
set(HOMEBREW_LIBOGG_OPT_DIR "${HOMEBREW_DIR}/opt/libogg")
set(HOMEBREW_LIBOGG_LIB_DIR "${HOMEBREW_LIBOGG_OPT_DIR}/lib")
add_imported_dylib(libogg_target "libogg.0.dylib" "${HOMEBREW_LIBOGG_LIB_DIR}")

# libvorbis (depends on libogg)
set(HOMEBREW_LIBVORBIS_OPT_DIR "${HOMEBREW_DIR}/opt/libvorbis")
set(HOMEBREW_LIBVORBIS_LIB_DIR "${HOMEBREW_LIBVORBIS_OPT_DIR}/lib")
add_imported_dylib(libvorbis_target "libvorbis.0.dylib" "${HOMEBREW_LIBVORBIS_LIB_DIR}")
add_imported_dylib(libvorbisenc_target "libvorbisenc.2.dylib" "${HOMEBREW_LIBVORBIS_LIB_DIR}")

# libflac
set(HOMEBREW_FLAC_OPT_DIR "${HOMEBREW_DIR}/opt/flac") # Corrected variable name from LIBFLAC to FLAC
set(HOMEBREW_FLAC_LIB_DIR "${HOMEBREW_FLAC_OPT_DIR}/lib")
add_imported_dylib(libflac_target "libFLAC.14.dylib" "${HOMEBREW_FLAC_LIB_DIR}")

# libopus
set(HOMEBREW_OPUS_OPT_DIR "${HOMEBREW_DIR}/opt/opus") # Corrected variable name
set(HOMEBREW_OPUS_LIB_DIR "${HOMEBREW_OPUS_OPT_DIR}/lib")
add_imported_dylib(libopus_target "libopus.0.dylib" "${HOMEBREW_OPUS_LIB_DIR}")

# mpg123
set(HOMEBREW_MPG123_OPT_DIR "${HOMEBREW_DIR}/opt/mpg123")
set(HOMEBREW_MPG123_LIB_DIR "${HOMEBREW_MPG123_OPT_DIR}/lib")
add_imported_dylib(libmpg123_target "libmpg123.0.dylib" "${HOMEBREW_MPG123_LIB_DIR}")

# lame (for mp3 support)
set(HOMEBREW_LAME_OPT_DIR "${HOMEBREW_DIR}/opt/lame")
set(HOMEBREW_LAME_LIB_DIR "${HOMEBREW_LAME_OPT_DIR}/lib")
add_imported_dylib(liblame_target "libmp3lame.0.dylib" "${HOMEBREW_LAME_LIB_DIR}")

# --- Installation of the directory structure (ensures INSTALL_SUBDIR is created) ---
# This is somewhat redundant if install(FILES...) creates the destination, but good for clarity.
install(DIRECTORY DESTINATION "${INSTALL_SUBDIR}" COMPONENT RuntimeLibraries USE_SOURCE_PERMISSIONS)

# --- Call External Script to Fix Dylib IDs and Paths ---
# This script will run after all files are copied by the rules above.
# It needs to know the root where these dylibs were installed relative to CMAKE_INSTALL_PREFIX.
set(FIX_DYLIBS_SCRIPT_NAME "prepare_libsndfile_bundle_dylibs.sh")
set(FIX_DYLIBS_SCRIPT_PATH "${CMAKE_CURRENT_SOURCE_DIR}/${FIX_DYLIBS_SCRIPT_NAME}")

if(NOT EXISTS "${FIX_DYLIBS_SCRIPT_PATH}")
    message(FATAL_ERROR "Dylib fixing script not found: ${FIX_DYLIBS_SCRIPT_PATH}")
endif()

install(CODE "
    message(STATUS \\\"Running ${FIX_DYLIBS_SCRIPT_NAME} to fix dylib IDs and paths in bundle: ${CMAKE_INSTALL_PREFIX}/${INSTALL_SUBDIR}\\\")
    # We pass CMAKE_INSTALL_PREFIX, the script will know to look in INSTALL_SUBDIR
    execute_process(
        COMMAND bash \"${FIX_DYLIBS_SCRIPT_PATH}\" \"${CMAKE_INSTALL_PREFIX}\" \"${INSTALL_SUBDIR}\"
        RESULT_VARIABLE _fix_res
        OUTPUT_VARIABLE _fix_out
        ERROR_VARIABLE _fix_err
    )
    # Escape special characters for messages
    string(REPLACE \\\"\\\\\\\"\\\" \\\"\\\\\\\\\\\\\\\"\\\" _fix_out_escaped \\\"${_fix_out}\\\")
    string(REPLACE \\\"\\\\\\\"\\\" \\\"\\\\\\\\\\\\\\\"\\\" _fix_err_escaped \\\"${_fix_err}\\\")
    string(REPLACE \\\"\\\\\\\\\\\" \\\"\\\\\\\\\\\\\\\\\\\" _fix_out_escaped \\\"${_fix_out_escaped}\\\")
    string(REPLACE \\\"\\\\\\\\\\\" \\\"\\\\\\\\\\\\\\\\\\\" _fix_err_escaped \\\"${_fix_err_escaped}\\\")

    if(NOT _fix_res EQUAL 0)
        message(FATAL_ERROR \\\"${FIX_DYLIBS_SCRIPT_NAME} failed (Code: ${_fix_res}). Output: [${_fix_out_escaped}]. Error: [${_fix_err_escaped}]\\\")
    else()
        message(STATUS \\\"${FIX_DYLIBS_SCRIPT_NAME} successful. Output: [${_fix_out_escaped} ${_fix_err_escaped}]\\\")
    endif()
" COMPONENT RuntimeLibraries)

message(STATUS "LibsndfileBundler configured. Dylibs will be copied to ${FULL_INSTALL_LIB_DIR}")
message(STATUS "An external script (${FIX_DYLIBS_SCRIPT_NAME}) will be called during install to fix their paths.")
message(STATUS "Ensure CMAKE_INSTALL_PREFIX is set correctly (e.g. -DCMAKE_INSTALL_PREFIX=/path/to/your_app_bundle_backend_dest).")
message(STATUS "IMPORTANT: After installation, you MUST fix the rpaths for the Python 'soundfile' library's C extension (_soundfile_data*.so) to find these bundled libraries.") 