#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
normal_home="$HOME"
session_name=""
reset_session=false
keep_open=false
synthetic_transcription_audio=false
force_approval_prompts=false
enable_companion=false

usage() {
  echo "Usage: $0 --session <name> [--reset-session] [--keep-open] [--synthetic-transcription-audio] [--force-approval-prompts] [--enable-companion]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      session_name="${2:-}"
      shift 2
      ;;
    --reset-session)
      reset_session=true
      shift
      ;;
    --keep-open)
      keep_open=true
      shift
      ;;
    --synthetic-transcription-audio)
      synthetic_transcription_audio=true
      shift
      ;;
    --force-approval-prompts)
      force_approval_prompts=true
      shift
      ;;
    --enable-companion)
      enable_companion=true
      shift
      ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
done

if [[ ! "$session_name" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
  echo "Validation session name must contain only letters, numbers, underscores, or hyphens." >&2
  exit 64
fi

sessions_root="$normal_home/Library/Application Support/BasilValidation/sessions"
session_root="$sessions_root/$session_name"
case "$session_root" in
  "$sessions_root"/*) ;;
  *)
    echo "Validation session root escaped its owned directory." >&2
    exit 64
    ;;
esac

if [[ "$reset_session" == true && -e "$session_root" ]]; then
  rm -rf "$session_root"
fi

session_home="$session_root/home"
mkdir -p "$session_home/.basil/config" "$session_home/.config/basil" "$session_root/logs"
chmod 700 "$session_root" "$session_home"

if [[ "$synthetic_transcription_audio" == true ]]; then
  if ! command -v say >/dev/null 2>&1 || ! command -v afconvert >/dev/null 2>&1; then
    echo "Synthetic transcription audio requires the macOS say and afconvert tools." >&2
    exit 69
  fi
  synthetic_audio_dir="$session_root/fixtures/audio"
  synthetic_audio_aiff="$synthetic_audio_dir/transcription-acceptance.aiff"
  synthetic_audio_wav="$synthetic_audio_dir/transcription-acceptance.wav"
  mkdir -p "$synthetic_audio_dir"
  say -v Samantha -r 175 -o "$synthetic_audio_aiff" "Basil native transcription acceptance confirms deterministic audio capture. This fixture verifies quick toggle, press and hold, clipboard completion, and immediate recording restart."
  afconvert -f WAVE -d LEF32@16000 -c 1 "$synthetic_audio_aiff" "$synthetic_audio_wav"
  rm "$synthetic_audio_aiff"
fi

copy_if_present() {
  local source_path="$1"
  local destination_path="$2"
  if [[ -f "$source_path" ]]; then
    cp "$source_path" "$destination_path"
    chmod 600 "$destination_path"
  fi
}

copy_if_present "$normal_home/.basil/config/preferences.json" "$session_home/.basil/config/preferences.json"
copy_if_present "$normal_home/.config/basil/preferences.json" "$session_home/.config/basil/preferences.json"
copy_if_present "$normal_home/.basil/config/api_keys.json" "$session_home/.basil/config/api_keys.json"

if [[ ! -f "$session_home/.basil/config/preferences.json" ]]; then
  printf '%s\n' '{"general":{"has_completed_onboarding":true},"behavior":{"enable_monitoring_at_startup":false,"enable_voice_listener_at_startup":false}}' > "$session_home/.basil/config/preferences.json"
  chmod 600 "$session_home/.basil/config/preferences.json"
fi
if [[ ! -f "$session_home/.config/basil/preferences.json" ]]; then
  cp "$session_home/.basil/config/preferences.json" "$session_home/.config/basil/preferences.json"
  chmod 600 "$session_home/.config/basil/preferences.json"
fi

if [[ "$force_approval_prompts" == true ]]; then
  # Isolated-session-only: forces the local-preview server-start command
  # through a live approval prompt, with no whitelist match, so Package 6A
  # can deterministically exercise a real denial. auto_approve_read_only
  # lets the model's own incidental read-only inspection commands (ls,
  # cat, file, echo, etc. -- issued while it analyzes screenshots/fixtures
  # during the feedback follow-up) auto-approve instead of also raising
  # live prompts; only one execution_approval_request can be pending per
  # agent task at a time (InteractiveApprovalManager tracks a single
  # asyncio.Future per approval_id keyed off the durable "pending approval
  # for this agent task" record), so letting those incidental commands
  # also compete for a live prompt risks a second command's request
  # silently superseding the first's still-unresolved Future -- leaving it
  # to await approval forever even though nothing further will ever
  # decide it. This rewrites only the session-owned preferences copy under
  # $session_home; the operator's real ~/.basil/config/preferences.json is
  # never touched.
  python3 - "$session_home/.basil/config/preferences.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
data["tool_execution"] = {
    "approval_mode": "whitelist_only",
    "whitelisted_commands": [],
    "auto_approve_read_only": True,
    "block_dangerous_patterns": True,
    "safe_execution_mode": False,
    "timeout_behavior": "wait_forever",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
PY
  chmod 600 "$session_home/.basil/config/preferences.json"
fi

port="$(python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_handle:
    socket_handle.bind(("127.0.0.1", 0))
    print(socket_handle.getsockname()[1])
PY
)"
token="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
token_path="$session_root/control-token"
printf '%s' "$token" > "$token_path"
chmod 600 "$token_path"

manifest_path="$session_root/session.json"
SESSION_ROOT="$session_root" \
SESSION_NAME="$session_name" \
BACKEND_PORT="$port" \
MANIFEST_PATH="$manifest_path" \
python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ["SESSION_ROOT"]).resolve()
name = os.environ["SESSION_NAME"]
manifest = {
    "schemaVersion": 1,
    "sessionID": name,
    "sessionRoot": root.as_uri(),
    "backendURL": f"http://127.0.0.1:{os.environ['BACKEND_PORT']}",
    "fixtureManifestURL": (root / "fixtures" / "fixture-manifest.json").as_uri(),
    "probeURL": (root / "probe.json").as_uri(),
    "credentialNamespace": f"com.stratten.basil.validation.{name}.",
    "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "mode": "developerLocal",
}
Path(os.environ["MANIFEST_PATH"]).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY
chmod 600 "$manifest_path"

cleanup() {
  local status=$?
  if [[ -n "${validation_app_pid:-}" ]] && kill -0 "$validation_app_pid" 2>/dev/null; then
    kill -TERM "$validation_app_pid" 2>/dev/null || true
  fi
  if [[ -n "${validation_backend_pid:-}" ]] && kill -0 "$validation_backend_pid" 2>/dev/null; then
    kill -TERM "$validation_backend_pid" 2>/dev/null || true
    wait "$validation_backend_pid" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

for build_script in \
  scripts/build-agent-task-assets.sh \
  scripts/build-setup-assistant-assets.sh \
  scripts/build-profile-editor-assets.sh \
  scripts/build-skill-reconciliation-workspace-assets.sh \
  scripts/build-settings-appearance-assets.sh; do
  bash "$repo_root/$build_script"
done

(
  cd "$repo_root/client"
  swift build -c debug
  app_dir=".build/debug/BasilValidation.app"
  rm -rf "$app_dir"
  mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Resources" "$app_dir/Contents/Frameworks"
  cp "Sources/Support/ValidationInfo.plist" "$app_dir/Contents/Info.plist"
  cp ".build/debug/BasilClient" "$app_dir/Contents/MacOS/Basil Validation"
  cp -R "Sources/Resources/." "$app_dir/Contents/Resources/"
  if [[ -d ".build/arm64-apple-macosx/debug/Sparkle.framework" ]]; then
    cp -R ".build/arm64-apple-macosx/debug/Sparkle.framework" "$app_dir/Contents/Frameworks/"
    install_name_tool -add_rpath "@loader_path/../Frameworks" "$app_dir/Contents/MacOS/Basil Validation" 2>/dev/null || true
  fi
  chmod +x "$app_dir/Contents/MacOS/Basil Validation"
  codesign --force --deep --sign - "$app_dir"
)

shared_models_root="$normal_home/.basil/models"
backend_environment=(
  "HOME=$session_home"
  "BASIL_RUNTIME_PROFILE=validation"
  "BASIL_VALIDATION_SESSION_ROOT=$session_root"
  "BASIL_VALIDATION_SESSION_TOKEN=$token"
  "BASIL_HOST=127.0.0.1"
  "BASIL_PORT=$port"
  "PYTHONPATH=$repo_root/backend/src:$repo_root/backend"
)
if [[ -d "$shared_models_root" ]]; then
  backend_environment+=(
    "BASIL_VALIDATION_SHARED_MODELS_ROOT=$shared_models_root"
    "BASIL_MODELS_DIR=$shared_models_root"
  )
fi
if [[ "$enable_companion" == true ]]; then
  # Starts the live Meeting Companion runtime, which the validation profile otherwise disables.
  backend_environment+=("BASIL_VALIDATION_ENABLE_COMPANION=1")
fi
if [[ "$force_approval_prompts" == true ]]; then
  # Seeds the local-preview fixture task itself as non-terminal (see
  # ValidationFixtureService), since create_pending_execution_approval
  # can only transition a task to 'awaiting_user_input' when its current
  # status is not already 'completed'/'failed'/'canceled'. This is
  # separate from the preferences-file always_prompt merge above; both are
  # required together for a live Approve/Deny prompt to ever appear.
  backend_environment+=("BASIL_VALIDATION_FORCE_APPROVAL_PROMPTS=1")
fi

(
  cd "$repo_root/backend"
  env "${backend_environment[@]}" poetry run python -m api.main --host 127.0.0.1 --port "$port" --log-level info
) > "$session_root/logs/backend.log" 2>&1 &
validation_backend_pid=$!
printf '%s\n' "$validation_backend_pid" > "$session_root/backend.pid"

ready_url="http://127.0.0.1:$port/validation/ready"
for _ in $(seq 1 1800); do
  if curl --fail --silent --show-error \
    -H "X-Basil-Validation-Token: $token" \
    "$ready_url" > "$session_root/ready.json" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$validation_backend_pid" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if [[ ! -s "$session_root/ready.json" ]]; then
  echo "Validation backend did not become ready. See $session_root/logs/backend.log" >&2
  exit 1
fi

validation_app="$repo_root/client/.build/debug/BasilValidation.app/Contents/MacOS/Basil Validation"
HOME="$session_home" "$validation_app" --validation-session "$manifest_path" > "$session_root/logs/client.log" 2>&1 &
validation_app_pid=$!
printf '%s\n' "$validation_app_pid" > "$session_root/client.pid"

echo "Basil Validation is running for session '$session_name'."
echo "Session root: $session_root"
if [[ "$keep_open" == true ]]; then
  echo "Waiting for Basil Validation to exit."
fi
wait "$validation_app_pid"
