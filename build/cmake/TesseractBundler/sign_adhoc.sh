#!/bin/bash
# build/cmake/TesseractBundler/sign_adhoc.sh
set -e # Exit on error

FILE_TO_SIGN="$1"
SIGN_IDENTITY="${2:--}"  # Use provided identity or default to ad-hoc ("-")

if [ -z "$FILE_TO_SIGN" ]; then
    echo "Error: No file path provided to sign_adhoc.sh" >&2
    echo "Usage: sign_adhoc.sh <file_to_sign> [signing_identity]" >&2
    exit 1
fi

if [ "$SIGN_IDENTITY" = "-" ]; then
    echo "Attempting ad-hoc sign on: $FILE_TO_SIGN"
else
    echo "Attempting Developer ID sign with '$SIGN_IDENTITY' on: $FILE_TO_SIGN"
fi

# Use -e to check if path exists (file, dir, or symlink)
# codesign itself should handle symlinks by operating on their target.
if [ ! -e "$FILE_TO_SIGN" ]; then
    echo "Error: Path not found at $FILE_TO_SIGN" >&2
    exit 1
fi

# Use timestamp and runtime options for Developer ID signing
if [ "$SIGN_IDENTITY" = "-" ]; then
    codesign --force --sign - "$FILE_TO_SIGN"
else
    codesign --force --sign "$SIGN_IDENTITY" --timestamp --options runtime "$FILE_TO_SIGN"
fi

# Optional: Verify immediately after signing (can also be done in CMake after this script)
# codesign --verify --deep --strict "$FILE_TO_SIGN"

echo "Signing completed for: $FILE_TO_SIGN" 