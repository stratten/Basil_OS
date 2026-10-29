# build/cmake/TesseractBundler/CMakeLists.txt

cmake_minimum_required(VERSION 3.15)
project(TesseractBundler LANGUAGES NONE) # No actual compilation needed

# --- Configuration: Paths to Homebrew components ---
set(HOMEBREW_OPT_DIR "/opt/homebrew/opt" CACHE PATH "Path to Homebrew's opt directory")
# TESSERACT_VERSION might be useful if cellar paths were needed, but /opt/ paths are more stable
# set(TESSERACT_VERSION "5.5.0_1" CACHE STRING "Tesseract version in Homebrew Cellar")

# --- Define Imported Executable for Tesseract ---
add_executable(tesseract_imported IMPORTED)
set_target_properties(tesseract_imported PROPERTIES
    IMPORTED_LOCATION "${HOMEBREW_OPT_DIR}/tesseract/bin/tesseract"
)

# --- Define Imported Libraries for Tesseract Dependencies ---
set(TESSERACT_BUNDLED_LIBS "") # Initialize a list to hold our library targets

macro(add_imported_dylib lib_cmake_name brew_opt_sub_path)
    add_library(${lib_cmake_name} SHARED IMPORTED)
    set_target_properties(${lib_cmake_name} PROPERTIES
        IMPORTED_LOCATION "${HOMEBREW_OPT_DIR}/${brew_opt_sub_path}"
        MACOSX_RPATH TRUE
        INSTALL_NAME_DIR "@rpath" # For dylibs, this effectively means their ID becomes @rpath/libname.dylib
                                  # and they will look for other dylibs via @rpath as well.
                                  # When placed in the same directory, @loader_path is used.
    )
    list(APPEND TESSERACT_BUNDLED_LIBS ${lib_cmake_name})
endmacro()

# Define all dylibs (using the CMake target name and the path relative to HOMEBREW_OPT_DIR)
add_imported_dylib(libtesseract_dep "tesseract/lib/libtesseract.5.dylib")
add_imported_dylib(libleptonica_dep "leptonica/lib/libleptonica.6.dylib")
add_imported_dylib(libarchive_dep "libarchive/lib/libarchive.13.dylib")
add_imported_dylib(libpng16_dep "libpng/lib/libpng16.16.dylib")
add_imported_dylib(libjpeg8_dep "jpeg-turbo/lib/libjpeg.8.dylib")
add_imported_dylib(libgif_dep "giflib/lib/libgif.dylib")
add_imported_dylib(libtiff6_dep "libtiff/lib/libtiff.6.dylib")
add_imported_dylib(libwebp7_dep "webp/lib/libwebp.7.dylib")
add_imported_dylib(libwebpmux3_dep "webp/lib/libwebpmux.3.dylib")
add_imported_dylib(libsharpyuv0_dep "webp/lib/libsharpyuv.0.dylib")
add_imported_dylib(libopenjp2_dep "openjpeg/lib/libopenjp2.7.dylib")
add_imported_dylib(liblzma5_dep "xz/lib/liblzma.5.dylib")
add_imported_dylib(libzstd1_dep "zstd/lib/libzstd.1.dylib")
add_imported_dylib(liblz4_dep "lz4/lib/liblz4.1.dylib")
add_imported_dylib(libb2_dep "libb2/lib/libb2.1.dylib") # Ensure this is the actual filename in opt/libb2/lib

# --- Installation Destinations ---
# This defines the root directory where `cmake --install .` will place files.
# We can point this to where build_backend.sh expects the Tesseract bundle.
# For standalone testing, it can be a local build directory.
# Let CMAKE_INSTALL_PREFIX be controlled by the user or the calling script.
# Example: cmake -DCMAKE_INSTALL_PREFIX=/path/to/backend_dest/ ..

set(INSTALL_BIN_DIR "bin") # Relative to CMAKE_INSTALL_PREFIX
set(INSTALL_LIB_DIR "dependencies/libs") # Relative to CMAKE_INSTALL_PREFIX
set(INSTALL_TESSDATA_DIR "share/tessdata") # Relative to CMAKE_INSTALL_PREFIX

# --- Installation Rules ---
# Install the tesseract executable file directly
get_target_property(TESSERACT_EXE_FILE tesseract_imported IMPORTED_LOCATION)
if(TESSERACT_EXE_FILE)
    install(FILES "${TESSERACT_EXE_FILE}"
        DESTINATION "${INSTALL_BIN_DIR}"
        PERMISSIONS OWNER_EXECUTE OWNER_READ GROUP_EXECUTE GROUP_READ WORLD_EXECUTE WORLD_READ # Typical 0755
        COMPONENT TesseractRuntime
    )
else()
    message(WARNING "IMPORTED_LOCATION not found for tesseract_imported target.")
endif()

# Install the dylib files directly
foreach(lib_target ${TESSERACT_BUNDLED_LIBS})
    get_target_property(IMPORTED_DYLIB_PATH ${lib_target} IMPORTED_LOCATION)
    if(IMPORTED_DYLIB_PATH)
        # Resolve symlinks to get the path to the actual file
        file(REAL_PATH "${IMPORTED_DYLIB_PATH}" ACTUAL_DYLIB_FILE_PATH)
        
        # Get the original desired filename (e.g., libjpeg.8.dylib from the IMPORTED_LOCATION)
        get_filename_component(DESIRED_DYLIB_FILENAME "${IMPORTED_DYLIB_PATH}" NAME)
        
        if(EXISTS "${ACTUAL_DYLIB_FILE_PATH}")
            install(FILES "${ACTUAL_DYLIB_FILE_PATH}" # Install the actual resolved file
                DESTINATION "${INSTALL_LIB_DIR}"
                RENAME "${DESIRED_DYLIB_FILENAME}"   # But name it as what's expected by linkers
                PERMISSIONS OWNER_EXECUTE OWNER_READ GROUP_EXECUTE GROUP_READ WORLD_EXECUTE WORLD_READ # Typical 0755 for dylibs too
                COMPONENT TesseractRuntime
            )
        else()
            message(WARNING "Actual dylib file not found at ${ACTUAL_DYLIB_FILE_PATH} (original imported_location: ${IMPORTED_DYLIB_PATH}, resolved from symlink) for target ${lib_target}.")
        endif()
    else()
        message(WARNING "IMPORTED_LOCATION not found for ${lib_target} target.")
    endif()
endforeach()

# Install tessdata
set(TESSDATA_SOURCE_DIR "${HOMEBREW_OPT_DIR}/tesseract/share/tessdata") # Or /opt/homebrew/share/tessdata
install(DIRECTORY "${TESSDATA_SOURCE_DIR}/" # Trailing slash copies contents
    DESTINATION "${INSTALL_TESSDATA_DIR}"
    COMPONENT TesseractData
)

# --- Fix Dylib Paths (before signing) ---
install(CODE "
    message(STATUS \"Fixing Tesseract dylib paths via script...\")
    execute_process(
        COMMAND \"${CMAKE_CURRENT_SOURCE_DIR}/fix_tesseract_dylibs.sh\" \"${CMAKE_INSTALL_PREFIX}\"
        RESULT_VARIABLE _fix_res
        OUTPUT_VARIABLE _fix_out
        ERROR_VARIABLE _fix_err
    )
    # Escape special characters for messages within the install(CODE) string
    string(REPLACE \"\\\"\" \"\\\\\\\"\" _fix_out_escaped \"${_fix_out}\")
    string(REPLACE \"\\\"\" \"\\\\\\\"\" _fix_err_escaped \"${_fix_err}\")
    string(REPLACE \"\\\\\" \"\\\\\\\\\" _fix_out_escaped \"${_fix_out_escaped}\") # Escape backslashes
    string(REPLACE \"\\\\\" \"\\\\\\\\\" _fix_err_escaped \"${_fix_err_escaped}\") # Escape backslashes

    if(NOT _fix_res EQUAL 0)
        message(FATAL_ERROR \"fix_tesseract_dylibs.sh failed (Code: ${_fix_res})\")
        message(FATAL_ERROR \"Output: ${_fix_out_escaped}\")
        message(FATAL_ERROR \"Error: ${_fix_err_escaped}\")
    else()
        message(STATUS \"fix_tesseract_dylibs.sh successful.\")
        # Combine out and err for status. Ensure it's a single clean string for the message.
        set(_combined_output \"Output (stdout and stderr from script): ${_fix_out_escaped} ${_fix_err_escaped}\")
        message(STATUS \"${_combined_output}\")
    endif()
" COMPONENT TesseractRuntime)

# --- RPATH and Install Name Settings for macOS Bundling ---
# This tells the tesseract executable where to find its dylibs at runtime.
# @executable_path/../dependencies/libs/
set(CMAKE_INSTALL_RPATH "@executable_path/../${INSTALL_LIB_DIR}")

# By setting MACOSX_RPATH TRUE and INSTALL_NAME_DIR "@rpath" on the dylib targets,
# CMake should handle setting their own install_name (ID) to "@rpath/libname.dylib"
# and their references to other dylibs to also use "@rpath/otherlib.dylib".
# When these dylibs are all in the same directory (our INSTALL_LIB_DIR),
# @rpath effectively becomes @loader_path for dylib-to-dylib references.

# --- Ad-hoc Code Signing (Post-Installation Custom Step) ---
# This uses install(CODE ...) to run a script after the main installation.
# The script will perform the ad-hoc signing.

install(CODE "
    message(STATUS \"Performing ad-hoc code signing on Tesseract components...\")
    set(CODESIGN_IDENTITY \"-\") # Ad-hoc signing
    set(SIGN_FLAGS \"--force\" \"--sign\" \"${CODESIGN_IDENTITY}\")

    set(STAGED_EXE_PATH \"${CMAKE_INSTALL_PREFIX}/${INSTALL_BIN_DIR}/tesseract\")
    if(EXISTS \${STAGED_EXE_PATH})
        message(STATUS \"Signing executable via script: \${STAGED_EXE_PATH}\")
        execute_process(COMMAND \"${CMAKE_CURRENT_SOURCE_DIR}/sign_adhoc.sh\" \${STAGED_EXE_PATH} RESULT_VARIABLE RES)
        if(NOT RES EQUAL 0)
            message(FATAL_ERROR \"Failed to sign executable (via script): \${STAGED_EXE_PATH}\")
        endif()
    else()
        message(WARNING \"Tesseract executable not found at \${STAGED_EXE_PATH} for signing.\")
    endif()

    file(GLOB DYLIBS \"${CMAKE_INSTALL_PREFIX}/${INSTALL_LIB_DIR}/*.dylib\")
    foreach(DYLIB_PATH \${DYLIBS})
        message(STATUS \"Signing dylib via script: \${DYLIB_PATH}\")
        execute_process(COMMAND \"${CMAKE_CURRENT_SOURCE_DIR}/sign_adhoc.sh\" \${DYLIB_PATH} RESULT_VARIABLE RES)
        if(NOT RES EQUAL 0)
            message(FATAL_ERROR \"Failed to sign dylib (via script): \${DYLIB_PATH}\")
        endif()
    endforeach()
    message(STATUS \"Ad-hoc code signing complete.\")
" COMPONENT TesseractRuntime)

# --- Verification (Optional Post-Install Custom Step) ---
install(CODE "
    message(STATUS \"Verifying signatures of Tesseract components...\")
    set(STAGED_EXE_PATH \"${CMAKE_INSTALL_PREFIX}/${INSTALL_BIN_DIR}/tesseract\")
    if(EXISTS \${STAGED_EXE_PATH})
        message(STATUS \"Verifying executable: \${STAGED_EXE_PATH}\")
        execute_process(COMMAND codesign --verify --deep --strict --verbose=4 \${STAGED_EXE_PATH} RESULT_VARIABLE RES OUTPUT_VARIABLE OUT ERROR_VARIABLE ERR)
        if(NOT RES EQUAL 0)
            message(WARNING \"Signature verification FAILED for executable: \${STAGED_EXE_PATH}\nStdout: \${OUT}\nStderr: \${ERR}\")
        else()
            message(STATUS \"Signature VERIFIED for executable: \${STAGED_EXE_PATH}\")
        endif()
    endif()
    # Could add dylib verification here too if needed
    message(STATUS \"Signature verification step complete.\")
" COMPONENT TesseractRuntime)

message(STATUS "TesseractBundler CMakeLists.txt configuration complete.")
message(STATUS "To build and install: ")
message(STATUS "  cmake -S <path_to_this_dir> -B <build_dir> -DCMAKE_INSTALL_PREFIX=<your_desired_output_path>")
message(STATUS "  cmake --build <build_dir>")
message(STATUS "  cmake --install <build_dir>") # Can also use --prefix here to override CMAKE_INSTALL_PREFIX 