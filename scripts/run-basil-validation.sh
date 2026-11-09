#!/usr/bin/env bash
# Usage (every example below starts with a cd, so it can be pasted and run from any directory): scripts/run-basil-validation.sh --session <name> [--fresh] [--reset-session] [--keep-open] [--synthetic-transcription-audio] [--force-approval-prompts] [--enable-companion] [--coexist]
#
# This starts a separate "Basil Validation" app and its own loopback backend, with its own synthetic home, database, and credentials, so it never touches your normal Basil, its backend on port 8000, or its Application Support folder. The script stays in the foreground until the validation app exits. Press Ctrl+C in this terminal, or quit Basil Validation, to stop both the app and its backend. Every session lives in ~/Library/Application Support/BasilValidation/sessions/<name>, and logs are in its logs folder (backend.log and client.log). The first run builds the client and the web assets, so it takes a few minutes.
#
# ---- Everyday commands (copy one) ----
#
# Fixture session, safe to run next to your normal Basil. It copies your preferences and API keys, seeds fixture data, uses your existing ~/.basil/models folder so nothing re-downloads, and leaves hotkeys, capture, and meeting detection off. Use it to check a feature without touching real data. Running the same command again reuses that session folder without deleting it:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session my-check
#
# Fixture session started from scratch. This deletes only that one named session folder first, then builds a new one:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session my-check --reset-session
#
# ---- Brand-new-user rehearsal (--fresh) ----
#
# Quit your normal Basil first (the script refuses to start while BasilClient is running, because both copies would answer the same hotkeys and capture the same screen). This copies nothing from your normal Basil, seeds no fixtures, and gives the session its own empty model folder, so the setup assistant, the macOS permission step, and every model download run for real, and the hotkeys, capture, and meeting detection are on, as in the real app. It is slower and uses disk space, because models download into the session:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session first-run --fresh
#
# Start the same rehearsal over from a completely blank state. This deletes that session folder, including its downloaded models, and rebuilds it:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session first-run --fresh --reset-session
#
# When you are done, reopen your normal Basil as usual. Your normal data was never changed.
#
# Brand-new-user rehearsal that can run next to your normal Basil (--fresh --coexist). It is the same rehearsal, with the same empty model folder, first-run permission step, and setup assistant, but the global hotkeys, key monitors, setup resume toast, capture, and meeting detection stay off. Use it when you are checking the setup flow itself and want to keep using your normal Basil at the same time, for example to dictate your notes into it. The hotkey step still checks, records, and saves hotkeys, but the validation app does not act on them. It cannot test what a hotkey does after setup, because nothing is listening for it:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session first-run --fresh --coexist --reset-session
#
# ---- Optional flags (add to a fixture session) ----
#
# Adds a spoken test recording that only the validation app plays back, for checking native transcription without a microphone. It needs the macOS say and afconvert tools:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session transcription-check --reset-session --synthetic-transcription-audio
#
# Starts the live Meeting Companion, which a validation session otherwise leaves off:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session companion-check --reset-session --enable-companion
#
# Forces the local-preview server-start command through a live approval prompt, for approval-flow checks. It rewrites only the session's own copy of the preferences and cannot be combined with --fresh:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session approval-check --reset-session --force-approval-prompts
#
# Only prints a "Waiting for Basil Validation to exit" message. The script always stays in the foreground until the app exits, with or without it. The acceptance scripts under scripts/validation use it in their instructions:
#   cd /Users/strattenwaldt/Desktop/BasilOpenSource && scripts/run-basil-validation.sh --session my-check --keep-open
#
# ---- Housekeeping ----
#
# List your existing validation sessions:
#   ls "$HOME/Library/Application Support/BasilValidation/sessions"
#
# Check how much disk space each session uses (a --fresh session can be tens of gigabytes after its models download):
#   du -sh "$HOME/Library/Application Support/BasilValidation/sessions/"*
#
# Delete one session by hand when its app is closed (replace my-check with the session name; this cannot be undone, and --reset-session does the same thing at launch):
#   rm -rf "$HOME/Library/Application Support/BasilValidation/sessions/my-check"
#
# See scripts/validation/README.md for the seeded fixtures and the per-package acceptance scripts.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
normal_home="$HOME"
session_name=""
reset_session=false
keep_open=false
synthetic_transcription_audio=false
force_approval_prompts=false
enable_companion=false
fresh_install=false
coexist=false

usage() {
  echo "Usage: $0 --session <name> [--reset-session] [--keep-open] [--synthetic-transcription-audio] [--force-approval-prompts] [--enable-companion] [--fresh [--coexist]]"
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
    --coexist)
      # Only with --fresh: keep the global hotkeys, key monitors, setup resume toast, capture, and meeting detection off, so the rehearsal can run next to a normal Basil.
      coexist=true
      shift
      ;;
    --fresh)
      # Behave like a first-time user of the real app: no copied preferences or API keys, no
      # seeded fixtures, a private model directory (so models download again), the first-run
      # permission gate, and the hotkeys, key monitors, and meeting and activity startup that a
      # fixture session leaves off. To start over, add --reset-session, which deletes the whole
      # session folder including its downloaded models.
      fresh_install=true
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

if [[ "$fresh_install" == true && "$force_approval_prompts" == true ]]; then
  echo "--fresh cannot be combined with --force-approval-prompts, because a fresh session starts with no preferences file to rewrite." >&2
  exit 64
fi

if [[ "$coexist" == true && "$fresh_install" != true ]]; then
  echo "--coexist only applies to a --fresh session. A fixture session already leaves hotkeys, capture, and meeting detection off, so it can run next to your normal Basil." >&2
  exit 64
fi

if [[ "$fresh_install" == true && "$coexist" != true ]] && pgrep -x BasilClient >/dev/null 2>&1; then
  # A fresh session turns global hotkeys, capture, and meeting detection back on, and two copies of Basil would answer the same keys and capture the same screen.
  echo "A normal Basil (BasilClient) is running. Quit it before starting a --fresh session, or add --coexist to run next to it with hotkeys, capture, and meeting detection off, then run this again." >&2
  exit 75
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

if [[ "$fresh_install" != true ]]; then
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
FRESH_INSTALL="$fresh_install" \
COEXIST="$coexist" \
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
if os.environ["FRESH_INSTALL"] == "true":
    manifest["freshInstall"] = True
    if os.environ["COEXIST"] == "true":
        manifest["suppressAmbientBehavior"] = True
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

# Every stage prints one line with the seconds since the script started, so the terminal says what is running now and how long each step took.
script_started_at=$SECONDS
stage() {
  printf '[%3ss] %s\n' "$((SECONDS - script_started_at))" "$*"
}

# Runs a noisy build step with its full output in a log file, and shows that output only if the step fails.
run_logged_stage() {
  local description="$1"
  local log_file="$2"
  shift 2
  local started=$SECONDS
  stage "$description"
  if ! "$@" > "$log_file" 2>&1; then
    echo "Failed: $description. The last lines of $log_file:" >&2
    tail -n 25 "$log_file" >&2
    exit 1
  fi
  stage "  done in $((SECONDS - started))s (full output: $log_file)"
}

asset_build_scripts=(
  scripts/build-agent-task-assets.sh
  scripts/build-setup-assistant-assets.sh
  scripts/build-profile-editor-assets.sh
  scripts/build-skill-reconciliation-workspace-assets.sh
  scripts/build-settings-appearance-assets.sh
)
asset_build_index=0
for build_script in "${asset_build_scripts[@]}"; do
  asset_build_index=$((asset_build_index + 1))
  asset_build_name="$(basename "$build_script" .sh)"
  asset_build_name="${asset_build_name#build-}"
  asset_build_name="${asset_build_name%-assets}"
  run_logged_stage "Building web assets ($asset_build_index of ${#asset_build_scripts[@]}): $asset_build_name" "$session_root/logs/build-$asset_build_name.log" bash "$repo_root/$build_script"
done

stage "Compiling the client with swift build. It only recompiles what changed, so this is quick when no Swift files did."
swift_build_started=$SECONDS
(
  cd "$repo_root/client"
  swift build -c debug
)
stage "  done in $((SECONDS - swift_build_started))s"

stage "Packaging BasilValidation.app and signing it ad hoc so macOS will launch it. Signing itself takes well under a second."
(
  cd "$repo_root/client"
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
  if ! sign_output="$(codesign --force --deep --sign - "$app_dir" 2>&1)"; then
    echo "Failed to sign $app_dir:" >&2
    echo "$sign_output" >&2
    exit 1
  fi
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
if [[ "$fresh_install" == true ]]; then
  # No shared model directory: the session downloads its own models into its synthetic home.
  backend_environment+=("BASIL_VALIDATION_FRESH_INSTALL=1")
  if [[ -d "$shared_models_root" ]]; then
    # Read-only source for the setup assistant's "Copy from my normal Basil" option, which copies an installed model into the session instead of downloading it. Nothing is ever written here.
    backend_environment+=("BASIL_VALIDATION_COPY_SOURCE_MODELS_ROOT=$shared_models_root")
  fi
elif [[ -d "$shared_models_root" ]]; then
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

stage "Starting the backend on port $port. It loads its Python modules and sets up the model service before it answers, which is the longest wait. Log: $session_root/logs/backend.log"
backend_started=$SECONDS
(
  cd "$repo_root/backend"
  env "${backend_environment[@]}" poetry run python -m api.main --host 127.0.0.1 --port "$port" --log-level info
) > "$session_root/logs/backend.log" 2>&1 &
validation_backend_pid=$!
printf '%s\n' "$validation_backend_pid" > "$session_root/backend.pid"

ready_url="http://127.0.0.1:$port/validation/ready"
last_progress_report=$SECONDS
for _ in $(seq 1 1800); do
  if curl --fail --silent --show-error \
    -H "X-Basil-Validation-Token: $token" \
    "$ready_url" > "$session_root/ready.json" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$validation_backend_pid" 2>/dev/null; then
    break
  fi
  if (( SECONDS - last_progress_report >= 5 )); then
    last_progress_report=$SECONDS
    # The newest backend log line is what the backend is doing right now.
    stage "  Backend still starting after $((SECONDS - backend_started))s. Latest log line: $(tail -n 1 "$session_root/logs/backend.log" 2>/dev/null | cut -c1-150)"
  fi
  sleep 0.1
done
if [[ ! -s "$session_root/ready.json" ]]; then
  echo "Validation backend did not become ready. See $session_root/logs/backend.log" >&2
  exit 1
fi

stage "  Backend ready after $((SECONDS - backend_started))s."

validation_app="$repo_root/client/.build/debug/BasilValidation.app/Contents/MacOS/Basil Validation"
stage "Launching Basil Validation. Its own log: $session_root/logs/client.log"
HOME="$session_home" "$validation_app" --validation-session "$manifest_path" > "$session_root/logs/client.log" 2>&1 &
validation_app_pid=$!
printf '%s\n' "$validation_app_pid" > "$session_root/client.pid"

echo "Basil Validation is running for session '$session_name'."
echo "Session root: $session_root"
if [[ "$fresh_install" == true ]]; then
  echo "Fresh install: nothing was copied from your normal Basil, and models download into the session. Add --reset-session to start over."
fi
if [[ "$keep_open" == true ]]; then
  echo "Waiting for Basil Validation to exit."
fi
wait "$validation_app_pid"
