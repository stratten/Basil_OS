#!/usr/bin/env bash
set -euo pipefail

# Exercises build/scripts/update_appcast.sh with a stub sign_update so feed generation, key handling, and feed signing are checked without a real key or the Keychain.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
check() {
    local description="$1"
    shift
    if "$@"; then
        echo "PASS: $description"
    else
        echo "FAIL: $description" >&2
        failures=$((failures + 1))
    fi
}

cat > "$WORK/sign_update" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
{ printf 'ARGS:'; printf ' [%s]' "$@"; printf '\n'; } >> "$STUB_SIGN_LOG"
target=""
for arg in "$@"; do
    if [[ "$arg" == "-" ]]; then
        printf 'STDIN:%s\n' "$(cat)" >> "$STUB_SIGN_LOG"
    fi
    target="$arg"
done
case "$target" in
    *.xml) printf '<!-- stub feed signature -->\n' >> "$target" ;;
    *) printf 'sparkle:edSignature="STUBSIGNATURE" length="%s"\n' "$(wc -c < "$target" | tr -d ' ')" ;;
esac
STUB
chmod +x "$WORK/sign_update"

printf 'fake dmg bytes' > "$WORK/Basil.dmg"
printf -- '- First change\n- Second change\n' > "$WORK/notes.txt"
readonly DOWNLOAD_URL="https://github.com/example/basil/releases/download/main-latest/Basil-main-abc123.dmg"

run_update_appcast() {
    BASIL_SPARKLE_SIGN_TOOL="$WORK/sign_update" \
    STUB_SIGN_LOG="$WORK/sign.log" \
    BASIL_SPARKLE_PRIVATE_KEY="${TEST_KEY:-}" \
    BASIL_RELEASE_NOTES_FILE="$WORK/notes.txt" \
    BASIL_APPCAST_URL="https://github.com/example/basil/releases/download/update-feed/appcast.xml" \
    "$SCRIPT_DIR/update_appcast.sh" \
        --version 1.1.7 --build 202610140400 \
        --dmg "$WORK/Basil.dmg" --download-url "$DOWNLOAD_URL" "$@"
}

feed_has() { grep -qF -- "$1" "$WORK/signed.xml"; }
log_arg_lines() { grep '^ARGS:' "$WORK/sign.log"; }

# Case 1: key from the environment, feed signed.
: > "$WORK/sign.log"
TEST_KEY="TEST-PRIVATE-KEY" run_update_appcast --appcast "$WORK/signed.xml" --sign-feed > "$WORK/case1.out" 2>&1 || { cat "$WORK/case1.out" >&2; exit 1; }
check "feed records the build number" feed_has '<sparkle:version>202610140400</sparkle:version>'
check "feed records the display version" feed_has '<sparkle:shortVersionString>1.1.7</sparkle:shortVersionString>'
check "feed points at the download URL" feed_has "url=\"$DOWNLOAD_URL\""
check "feed carries the DMG signature" feed_has 'sparkle:edSignature="STUBSIGNATURE"'
check "feed lists the first release note" feed_has '<li>First change</li>'
check "feed lists the second release note" feed_has '<li>Second change</li>'
check "feed signature is the last line of the file" test "$(tail -n 1 "$WORK/signed.xml")" = '<!-- stub feed signature -->'
check "both the DMG and the feed are signed with the key read from stdin" test "$(log_arg_lines | grep -cF '[--ed-key-file] [-]')" -eq 2
check "the key text reaches sign_update on stdin" grep -qF 'STDIN:TEST-PRIVATE-KEY' "$WORK/sign.log"
check "the feed is signed last" test "$(log_arg_lines | tail -n 1)" = "ARGS: [--ed-key-file] [-] [$WORK/signed.xml]"

# Case 2: no key in the environment means Keychain mode and an unsigned feed.
: > "$WORK/sign.log"
run_update_appcast --appcast "$WORK/keychain.xml" > "$WORK/case2.out" 2>&1 || { cat "$WORK/case2.out" >&2; exit 1; }
check "Keychain mode signs only the DMG" test "$(log_arg_lines | wc -l | tr -d ' ')" -eq 1
check "Keychain mode does not pass an explicit key file" test "$(log_arg_lines | grep -cF -- '--ed-key-file' || true)" -eq 0
check "an unrequested feed signature is not added" test "$(grep -cF 'stub feed signature' "$WORK/keychain.xml" || true)" -eq 0

# Case 3: feed signing refuses to rewrite an existing appcast.
if TEST_KEY="TEST-PRIVATE-KEY" run_update_appcast --appcast "$WORK/signed.xml" --sign-feed > "$WORK/case3.out" 2>&1; then
    check "--sign-feed on an existing appcast is refused" false
else
    check "--sign-feed on an existing appcast is refused" grep -qF 'only supports creating a new appcast' "$WORK/case3.out"
fi

if [ "$failures" -ne 0 ]; then
    echo "$failures check(s) failed." >&2
    exit 1
fi
echo "All update_appcast checks passed."
