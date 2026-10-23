cmake_minimum_required(VERSION 3.15)
project(FFmpegBundler LANGUAGES C CXX)

# --- Locate the project-built LGPL FFmpeg ---
set(BASIL_FFMPEG_PREFIX "" CACHE PATH "Prefix of the verified LGPL-only FFmpeg build")
if(NOT BASIL_FFMPEG_PREFIX)
    message(FATAL_ERROR "BASIL_FFMPEG_PREFIX is required. Run build/scripts/build_ffmpeg_lgpl.sh and pass its output prefix to CMake.")
endif()

find_program(FFMPEG_EXECUTABLE_PATH ffmpeg PATHS "${BASIL_FFMPEG_PREFIX}/bin" NO_DEFAULT_PATH)
if(NOT FFMPEG_EXECUTABLE_PATH)
    message(FATAL_ERROR "No FFmpeg executable found under ${BASIL_FFMPEG_PREFIX}/bin")
endif()
get_filename_component(REAL_FFMPEG_EXECUTABLE_PATH "${FFMPEG_EXECUTABLE_PATH}" REALPATH)
set(FFMPEG_OPT_LIB_DIR "${BASIL_FFMPEG_PREFIX}/lib")
if(NOT IS_DIRECTORY "${FFMPEG_OPT_LIB_DIR}")
    message(FATAL_ERROR "No FFmpeg libraries found under ${BASIL_FFMPEG_PREFIX}/lib")
endif()

execute_process(
    COMMAND "${REAL_FFMPEG_EXECUTABLE_PATH}" -version
    OUTPUT_VARIABLE FFMPEG_VERSION_OUTPUT
    ERROR_VARIABLE FFMPEG_VERSION_ERROR
    RESULT_VARIABLE FFMPEG_VERSION_RESULT
)
if(NOT FFMPEG_VERSION_RESULT EQUAL 0)
    message(FATAL_ERROR "Could not inspect the FFmpeg build configuration: ${FFMPEG_VERSION_ERROR}")
endif()
if(NOT FFMPEG_VERSION_OUTPUT MATCHES "(^|\n)configuration:.*--disable-gpl")
    message(FATAL_ERROR "Refusing to bundle an FFmpeg build that was not configured with --disable-gpl.")
endif()
if(FFMPEG_VERSION_OUTPUT MATCHES "(^|\n)configuration:.*--enable-gpl")
    message(FATAL_ERROR "Refusing to bundle a GPL-enabled FFmpeg build.")
endif()


# --- List of primary FFmpeg dylibs to bundle ---
set(FFMPEG_PRIMARY_DYLIBS
    libavcodec
    libavdevice
    libavfilter
    libavformat
    libavutil
    libpostproc
    libswresample
    libswscale
)

set(FFMPEG_PRIMARY_DYLIBS_PATHS "")
foreach(lib_base_name ${FFMPEG_PRIMARY_DYLIBS})
    # find_library will search for e.g. libavcodec.61.dylib, libavcodec.dylib
    find_library(FOUND_DYLIB_PATH
        NAMES "${lib_base_name}.*.dylib" "${lib_base_name}.dylib" # Prefer versioned, then unversioned
        PATHS "${FFMPEG_OPT_LIB_DIR}"
        NO_DEFAULT_PATH
    )

    if(FOUND_DYLIB_PATH)
        # Resolve symlinks to get the actual file path (likely in Cellar)
        file(REAL_PATH "${FOUND_DYLIB_PATH}" ACTUAL_DYLIB_FILE_PATH)
        if(EXISTS "${ACTUAL_DYLIB_FILE_PATH}")
            message(STATUS "Found primary FFmpeg dylib: ${ACTUAL_DYLIB_FILE_PATH} (from symlink/path: ${FOUND_DYLIB_PATH})")
            list(APPEND FFMPEG_PRIMARY_DYLIBS_PATHS "${ACTUAL_DYLIB_FILE_PATH}")
        else()
            message(WARNING "Primary FFmpeg dylib ${lib_base_name} resolved to non-existent REAL_PATH ${ACTUAL_DYLIB_FILE_PATH} from ${FOUND_DYLIB_PATH}.")
        endif()
    else()
        message(WARNING "Primary FFmpeg dylib ${lib_base_name} not found in ${FFMPEG_OPT_LIB_DIR}. This might be okay if it's not a direct critical dependency or has an unexpected name.")
    endif()
    unset(FOUND_DYLIB_PATH CACHE) # Important for find_library in a loop
endforeach()

if(NOT FFMPEG_PRIMARY_DYLIBS_PATHS)
    message(FATAL_ERROR "No primary FFmpeg dylibs were successfully located. Check FFMPEG_PRIMARY_DYLIBS list and the path ${FFMPEG_OPT_LIB_DIR}.")
endif()

# --- Installation ---
# Use provided destination variables or fall back to CMAKE_INSTALL_PREFIX
if(NOT FFMPEG_DEST_BIN)
    set(FFMPEG_DEST_BIN "${CMAKE_INSTALL_PREFIX}/bin")
endif()
if(NOT FFMPEG_DEST_LIBS)
    set(FFMPEG_DEST_LIBS "${CMAKE_INSTALL_PREFIX}/dependencies/libs")
endif()

message(STATUS "FFmpeg installation destinations:")
message(STATUS "  Executable: ${FFMPEG_DEST_BIN}")
message(STATUS "  Libraries: ${FFMPEG_DEST_LIBS}")

# Install ffmpeg executable (the actual file, not a symlink)
install(
    PROGRAMS "${REAL_FFMPEG_EXECUTABLE_PATH}"
    DESTINATION "${FFMPEG_DEST_BIN}"
    RENAME "ffmpeg"
)
message(STATUS "Installing actual ffmpeg executable from ${REAL_FFMPEG_EXECUTABLE_PATH} to: ${FFMPEG_DEST_BIN}/ffmpeg")

# Install each primary FFmpeg dylib under its install-name basename (e.g. libavcodec.61.dylib), because that is the name ffmpeg and the other FFmpeg dylibs reference.
foreach(ACTUAL_DYLIB_FULL_PATH ${FFMPEG_PRIMARY_DYLIBS_PATHS})
    execute_process(
        COMMAND otool -D "${ACTUAL_DYLIB_FULL_PATH}"
        OUTPUT_VARIABLE DYLIB_ID_OUTPUT
        RESULT_VARIABLE DYLIB_ID_RESULT
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    if(NOT DYLIB_ID_RESULT EQUAL 0)
        message(FATAL_ERROR "Could not read the install name of ${ACTUAL_DYLIB_FULL_PATH}")
    endif()
    string(REGEX REPLACE "^.*\n" "" DYLIB_INSTALL_NAME "${DYLIB_ID_OUTPUT}")
    get_filename_component(DYLIB_BASENAME "${DYLIB_INSTALL_NAME}" NAME)
    if(NOT DYLIB_BASENAME MATCHES "^lib.+\\.dylib$")
        message(FATAL_ERROR "Unexpected install name '${DYLIB_INSTALL_NAME}' for ${ACTUAL_DYLIB_FULL_PATH}")
    endif()
    install(
        FILES "${ACTUAL_DYLIB_FULL_PATH}"
        DESTINATION "${FFMPEG_DEST_LIBS}"
        RENAME "${DYLIB_BASENAME}"
    )
    message(STATUS "Installing primary FFmpeg dylib ${DYLIB_BASENAME} from ${ACTUAL_DYLIB_FULL_PATH} to: ${FFMPEG_DEST_LIBS}/")
endforeach()

# Special handling for libjxl_cms if libjxl was bundled
set(JXL_PATH "${FFMPEG_DEST_LIBS}/libjxl.0.11.dylib")
set(JXL_CMS_ORIGINAL_PATH "/opt/homebrew/opt/jpeg-xl/lib/libjxl_cms.0.11.dylib") # Path based on 'brew --prefix jpeg-xl'
set(JXL_CMS_DEST_PATH "${FFMPEG_DEST_LIBS}/libjxl_cms.0.11.dylib")
if(EXISTS ${JXL_PATH} AND EXISTS ${JXL_CMS_ORIGINAL_PATH} AND NOT EXISTS ${JXL_CMS_DEST_PATH})
  message(STATUS "FFmpegBundler: Manually copying libjxl_cms.0.11.dylib because libjxl.0.11.dylib was found in bundle.")
  execute_process(COMMAND ${CMAKE_COMMAND} -E copy_if_different ${JXL_CMS_ORIGINAL_PATH} ${JXL_CMS_DEST_PATH}
                  RESULT_VARIABLE copy_res_jxl_cms
                  OUTPUT_VARIABLE copy_out_jxl_cms
                  ERROR_VARIABLE copy_err_jxl_cms)
  if(NOT copy_res_jxl_cms EQUAL 0)
      message(WARNING "FFmpegBundler: Failed to copy libjxl_cms.0.11.dylib. Error: ${copy_err_jxl_cms}")
  endif()
elseif(EXISTS ${JXL_PATH} AND NOT EXISTS ${JXL_CMS_ORIGINAL_PATH})
    message(WARNING "FFmpegBundler: libjxl.0.11.dylib is bundled, but original libjxl_cms.0.11.dylib not found at ${JXL_CMS_ORIGINAL_PATH}.")
endif()

# Script to fix dylib paths and sign
set(PREPARE_SCRIPT_PATH "${CMAKE_CURRENT_SOURCE_DIR}/prepare_ffmpeg_bundle.sh")

install(CODE "
    # Ensure the script is executable before trying to run it directly
    execute_process(COMMAND chmod +x \"${PREPARE_SCRIPT_PATH}\")

    # Execute the script, relying on its shebang
    execute_process(
        COMMAND \"${PREPARE_SCRIPT_PATH}\" \"${CMAKE_INSTALL_PREFIX}\"
        RESULT_VARIABLE result
    )

    # Check result
    if(NOT result EQUAL 0)
        message(FATAL_ERROR \"prepare_ffmpeg_bundle.sh failed (Exit Code: ${result}). Check install output for script details.\")
    endif()
") # End of install(CODE)

message(STATUS "FFmpegBundler CMake configuration complete. prepare_ffmpeg_bundle.sh will run at install time.") 