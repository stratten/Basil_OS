#!/usr/bin/env bash
set -euo pipefail

# Checks a downloaded repository build: stapled notarization, Developer ID signature, Gatekeeper acceptance, the source commit stamped by the build workflow, and that automatic updates are disabled.

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <Basil.dmg> [expected 40-character commit SHA]" >&2
    exit 2
fi

readonly DMG_PATH="$1"
readonly EXPECTED_COMMIT="${2:-}"

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

[[ -f "$DMG_PATH" ]] || fail "DMG not found: $DMG_PATH"

xcrun stapler validate "$DMG_PATH" > /dev/null 2>&1 || fail "The DMG has no valid stapled notarization ticket."
echo "PASS: a notarization ticket is stapled to the DMG"

MOUNT_DIR="$(mktemp -d)"
detach_image() {
    hdiutil detach "$MOUNT_DIR" -quiet > /dev/null 2>&1 || true
    rmdir "$MOUNT_DIR" > /dev/null 2>&1 || true
}
trap detach_image EXIT
hdiutil attach "$DMG_PATH" -nobrowse -readonly -noautoopen -mountpoint "$MOUNT_DIR" -quiet || fail "Could not mount the DMG."

readonly APP_PATH="$MOUNT_DIR/Basil.app"
[[ -d "$APP_PATH" ]] || fail "Basil.app is missing from the DMG."

codesign --verify --deep --strict "$APP_PATH" > /dev/null 2>&1 || fail "The app's code signature is invalid."
signature_details="$(codesign --display --verbose=4 "$APP_PATH" 2>&1)"
authority="$(printf '%s\n' "$signature_details" | awk -F= '/^Authority=Developer ID Application/ {print $2; exit}')"
team_id="$(printf '%s\n' "$signature_details" | awk -F= '/^TeamIdentifier=/ {print $2; exit}')"
[[ -n "$authority" ]] || fail "The app is not signed with a Developer ID Application certificate."
echo "PASS: signed by $authority (team $team_id)"

assessment="$(spctl --assess --type execute --verbose=4 "$APP_PATH" 2>&1)" || fail "Gatekeeper rejected the app: $assessment"
printf '%s\n' "$assessment" | grep -q "source=Notarized Developer ID" || fail "Gatekeeper did not report a notarized Developer ID source: $assessment"
echo "PASS: Gatekeeper accepts the app as notarized Developer ID software"

readonly INFO_PLIST="$APP_PATH/Contents/Info.plist"
commit="$(/usr/libexec/PlistBuddy -c 'Print :BasilSourceCommit' "$INFO_PLIST" 2>/dev/null)" || fail "The app has no BasilSourceCommit, so it was not produced by the repository build workflow."
repository="$(/usr/libexec/PlistBuddy -c 'Print :BasilSourceRepository' "$INFO_PLIST" 2>/dev/null || echo "unrecorded repository")"
if [[ -n "$EXPECTED_COMMIT" && "$commit" != "$EXPECTED_COMMIT" ]]; then
    fail "BasilSourceCommit is $commit, but $EXPECTED_COMMIT was expected."
fi
echo "PASS: built from commit $commit ($repository)"

if /usr/libexec/PlistBuddy -c 'Print :SUFeedURL' "$INFO_PLIST" > /dev/null 2>&1; then
    fail "The app has a Sparkle update feed; repository builds must not replace themselves with a different binary."
fi
echo "PASS: automatic updates are disabled"

echo "SHA-256 of $(basename "$DMG_PATH"): $(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
