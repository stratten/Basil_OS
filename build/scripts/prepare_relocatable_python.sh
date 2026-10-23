#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
readonly PYTHON_VERSION="3.11.17"
readonly DEFAULT_ARCHIVE="$REPO_ROOT/local/python/python-${PYTHON_VERSION}-relocatable.tar.gz"
readonly DOWNLOADED_ARCHIVE="$REPO_ROOT/build/cache/python-${PYTHON_VERSION}-relocatable.tar.gz"
readonly UPSTREAM_ARCHIVE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.11.17%2B20261003-aarch64-apple-darwin-install_only.tar.gz"
ARCHIVE="${BASIL_RELOCATABLE_PYTHON_ARCHIVE:-$DEFAULT_ARCHIVE}"
readonly EXPECTED_SHA256="${BASIL_RELOCATABLE_PYTHON_SHA256:-3663b71c18364eccfbad74c4f21f9f6149e40b07329cd776287410cc1da5d612}"
readonly DESTINATION="$REPO_ROOT/build/python/python"

for command in shasum tar; do
    command -v "$command" >/dev/null || {
        echo "Required command is unavailable: $command" >&2
        exit 1
    }
done

if [[ -x "$DESTINATION/bin/python3" ]]; then
    "$DESTINATION/bin/python3" --version
    exit 0
fi

if [[ ! -f "$ARCHIVE" && -z "${BASIL_RELOCATABLE_PYTHON_ARCHIVE:-}" ]]; then
    ARCHIVE="$DOWNLOADED_ARCHIVE"
    if [[ ! -f "$ARCHIVE" ]]; then
        command -v curl >/dev/null || {
            echo "Required command is unavailable: curl" >&2
            exit 1
        }
        mkdir -p "$(dirname "$ARCHIVE")"
        curl --fail --location --proto '=https' --tlsv1.2 "$UPSTREAM_ARCHIVE_URL" --output "$ARCHIVE.partial"
        mv "$ARCHIVE.partial" "$ARCHIVE"
    fi
fi

[[ -f "$ARCHIVE" ]] || {
    echo "Relocatable Python archive is unavailable: $ARCHIVE" >&2
    exit 1
}

actual_sha256="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
[[ "$actual_sha256" == "$EXPECTED_SHA256" ]] || {
    echo "Relocatable Python archive checksum mismatch: $ARCHIVE" >&2
    if [[ "$ARCHIVE" == "$DOWNLOADED_ARCHIVE" ]]; then
        echo "Delete that file to download it again." >&2
    fi
    exit 1
}

rm -rf "$DESTINATION"
mkdir -p "$REPO_ROOT/build/python"
tar -xzf "$ARCHIVE" -C "$REPO_ROOT/build/python"
"$DESTINATION/bin/python3" --version
