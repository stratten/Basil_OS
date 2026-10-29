#!/usr/bin/env bash
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly RELEASE_ENV_FILE="$REPO_ROOT/local/release.env"

if [[ -f "$RELEASE_ENV_FILE" ]]; then
    set -a
    source "$RELEASE_ENV_FILE"
    set +a
fi

exec "$REPO_ROOT/build/scripts/build_app.sh" "$@"
