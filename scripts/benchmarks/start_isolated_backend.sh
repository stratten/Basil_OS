#!/usr/bin/env bash
# Starts a backend on a loopback port with an isolated HOME, no copied preferences or API keys, and a models directory made of symlinks. Nothing under the real ~/.basil is written. Usage: start_isolated_backend.sh <session-name>. Run it in the background; it stays in the foreground until the backend exits. Prepare the session first with the same name (see the agent suite section of the Benchmarks summary).
set -euo pipefail

session_name="${1:?session name required}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
session_root="$HOME/Library/Application Support/BasilValidation/sessions/$session_name"
session_home="$session_root/home"
port="$(cat "$session_root/port.txt")"
token="$(cat "$session_root/control-token")"
models_root="$session_root/models"
[[ -d "$models_root" ]] || { echo "Missing $models_root" >&2; exit 66; }

cd "$repo_root/backend"
exec env \
  HOME="$session_home" \
  BASIL_RUNTIME_PROFILE=validation \
  BASIL_VALIDATION_SESSION_ROOT="$session_root" \
  BASIL_VALIDATION_SESSION_TOKEN="$token" \
  BASIL_HOST=127.0.0.1 \
  BASIL_PORT="$port" \
  BASIL_VALIDATION_SHARED_MODELS_ROOT="$models_root" \
  BASIL_MODELS_DIR="$models_root" \
  PYTHONPATH="$repo_root/backend/src:$repo_root/backend" \
  "$repo_root/.venv/bin/python" -m api.main --host 127.0.0.1 --port "$port" --log-level info \
  >> "$session_root/logs/backend.log" 2>&1
