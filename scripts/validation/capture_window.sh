#!/bin/bash
#
# Captures a specific application window by title, independent of desktop
# focus, frontmost status, or window stacking order.
#
# Region-based capture (`screencapture -R x,y,w,h`) and frontmost-based
# capture both depend on the target window being on top of the screen at
# capture time, so anything else happening on the desktop while validation
# runs can silently corrupt the evidence. `screencapture -l <CGWindowID>`
# instead reads the target window's own compositor buffer directly, so it
# is correct even if the window is occluded or not frontmost.
#
# Basil Validation (like BasilClient) does not bundle a Cocoa
# Standard-Suite `.scriptSuite`/`.sdef`, so `tell application "Basil
# Validation" to id of window ...` is unavailable -- only the minimal
# run/quit/activate verbs Cocoa provides implicitly work through direct
# `tell application`, and System Events/Accessibility exposes windows
# without their CGWindowID. Resolving the numeric CGWindowID therefore
# goes through Quartz's window list (already a transitive dependency of
# the Basil backend's own window-capture service), matched by owning
# process name and window title substring.
#
# Usage: capture_window.sh <app-name> <window-title-substring> <output-path>

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <app-name> <window-title-substring> <output-path>" >&2
  exit 1
fi

app_name="$1"
title_substring="$2"
output_path="$3"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

window_id="$(cd "$repo_root/backend" && poetry run python3 - "$app_name" "$title_substring" <<'PY'
import sys

import Quartz

app_name, title_substring = sys.argv[1:]

windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
for window in windows:
    owner = window.get("kCGWindowOwnerName", "")
    name = window.get("kCGWindowName", "") or ""
    if owner == app_name and title_substring in name:
        print(window["kCGWindowNumber"])
        break
else:
    raise SystemExit(f'No window of "{app_name}" matched title substring "{title_substring}".')
PY
)"

mkdir -p "$(dirname "$output_path")"
screencapture -x -o -l "$window_id" "$output_path"

if [[ ! -s "$output_path" ]]; then
  echo "capture_window.sh: screencapture produced no file (or an empty file) at $output_path" >&2
  exit 1
fi

echo "$output_path"
