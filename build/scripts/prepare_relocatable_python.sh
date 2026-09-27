#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
readonly PYTHON_VERSION="3.11.13"
readonly ARCHIVE="${BASIL_RELOCATABLE_PYTHON_ARCHIVE:-$REPO_ROOT/local/python/python-${PYTHON_VERSION}-relocatable.tar.gz}"
readonly EXPECTED_SHA256="${BASIL_RELOCATABLE_PYTHON_SHA256:-d97de34acef2eeaf64cfddab978a894977732704d4b9f0ce78cf09ee7497d9c5}"
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

[[ -f "$ARCHIVE" ]] || {
    echo "Relocatable Python archive is unavailable: $ARCHIVE" >&2
    exit 1
}

actual_sha256="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
[[ "$actual_sha256" == "$EXPECTED_SHA256" ]] || {
    echo "Relocatable Python archive checksum mismatch." >&2
    exit 1
}

rm -rf "$DESTINATION"
mkdir -p "$REPO_ROOT/build/python"
tar -xzf "$ARCHIVE" -C "$REPO_ROOT/build/python"
"$DESTINATION/bin/python3" --version
