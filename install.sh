#!/usr/bin/env bash
# Installs the latest stable Basil release from GitHub.
#
#   curl -fsSL https://raw.githubusercontent.com/stratten/Basil_OS/main/install.sh | bash
#
# Options (pass them after "bash -s --" when piping):
#   --no-open   Install without opening Basil afterward.
#   --help      Show this help.
#
# Environment variables:
#   BASIL_VERSION        Install a specific release tag, for example v1.0.0, instead of the latest.
#   BASIL_INSTALL_DIR    Install into this folder instead of /Applications.
#   BASIL_DOWNLOAD_BASE  Fetch Basil.dmg and SHA256SUMS.txt from this base URL (used for testing).
#
# The script downloads Basil.dmg and SHA256SUMS.txt, checks the SHA-256 checksum, copies Basil.app out of the
# disk image, checks the code signature and Gatekeeper's assessment, and only then replaces any existing copy.
# It never uses sudo. If /Applications is not writable it installs into ~/Applications instead.

set -euo pipefail

readonly REPOSITORY="stratten/Basil_OS"
readonly APP_NAME="Basil.app"
readonly DMG_NAME="Basil.dmg"
readonly SUMS_NAME="SHA256SUMS.txt"

WORK_DIR=""
MOUNT_POINT=""

say() { printf '%s\n' "$*"; }
fail() { printf 'Basil install failed: %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [[ -n "$MOUNT_POINT" && -d "$MOUNT_POINT" ]]; then
        hdiutil detach "$MOUNT_POINT" -quiet >/dev/null 2>&1 || hdiutil detach "$MOUNT_POINT" -force -quiet >/dev/null 2>&1 || true
    fi
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}

usage() {
    cat <<'USAGE'
Installs the latest stable Basil release from GitHub.

  curl -fsSL https://raw.githubusercontent.com/stratten/Basil_OS/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/stratten/Basil_OS/main/install.sh | bash -s -- --no-open

Options:
  --no-open   Install without opening Basil afterward.
  --help      Show this help.

Environment variables:
  BASIL_VERSION        Install a specific release tag, for example v1.0.0, instead of the latest.
  BASIL_INSTALL_DIR    Install into this folder instead of /Applications.
  BASIL_DOWNLOAD_BASE  Fetch Basil.dmg and SHA256SUMS.txt from this base URL (used for testing).
USAGE
}

check_platform() {
    [[ "$(uname -s)" == "Darwin" ]] || fail "Basil runs on macOS only."
    [[ "$(sysctl -in hw.optional.arm64 2>/dev/null || echo 0)" == "1" ]] || fail "Basil needs an Apple Silicon Mac."
    local major
    major="$(sw_vers -productVersion | cut -d. -f1)"
    [[ "$major" -ge 13 ]] || fail "Basil needs macOS 13 or later. This Mac is running macOS $(sw_vers -productVersion)."
    local tool
    for tool in curl hdiutil ditto shasum codesign spctl; do
        command -v "$tool" >/dev/null 2>&1 || fail "The required tool '$tool' was not found."
    done
}

download_base() {
    if [[ -n "${BASIL_DOWNLOAD_BASE:-}" ]]; then
        printf '%s' "${BASIL_DOWNLOAD_BASE%/}"
    elif [[ -n "${BASIL_VERSION:-}" ]]; then
        printf 'https://github.com/%s/releases/download/%s' "$REPOSITORY" "$BASIL_VERSION"
    else
        printf 'https://github.com/%s/releases/latest/download' "$REPOSITORY"
    fi
}

choose_install_dir() {
    local dir="${BASIL_INSTALL_DIR:-/Applications}"
    if [[ -z "${BASIL_INSTALL_DIR:-}" && ! -w "$dir" ]]; then
        dir="$HOME/Applications"
        say "/Applications is not writable by this account, so Basil will go in $dir."
    fi
    mkdir -p "$dir" || fail "Could not create $dir."
    [[ -w "$dir" ]] || fail "$dir is not writable."
    printf '%s' "$dir"
}

download_release() {
    local base="$1"
    say "Downloading the Basil checksum..."
    curl -fsSL --retry 3 -o "$WORK_DIR/$SUMS_NAME" "$base/$SUMS_NAME" || fail "Could not download $SUMS_NAME from $base."
    say "Downloading Basil (about 570 MB)..."
    curl -fL --retry 3 --progress-bar -o "$WORK_DIR/$DMG_NAME" "$base/$DMG_NAME" || fail "Could not download $DMG_NAME from $base."
}

verify_checksum() {
    say "Checking the SHA-256 checksum..."
    local expected actual
    expected="$(awk -v name="$DMG_NAME" '$2 == name || $2 == "*" name { print $1 }' "$WORK_DIR/$SUMS_NAME" | head -n 1)"
    [[ -n "$expected" ]] || fail "$SUMS_NAME does not list $DMG_NAME."
    actual="$(shasum -a 256 "$WORK_DIR/$DMG_NAME" | awk '{ print $1 }')"
    [[ "$expected" == "$actual" ]] || fail "The checksum does not match (expected $expected, got $actual). Nothing was installed."
}

copy_app_out_of_image() {
    say "Opening the disk image..."
    MOUNT_POINT="$WORK_DIR/mount"
    mkdir -p "$MOUNT_POINT"
    hdiutil attach "$WORK_DIR/$DMG_NAME" -nobrowse -readonly -noautoopen -quiet -mountpoint "$MOUNT_POINT" >/dev/null || fail "Could not open the disk image."
    [[ -d "$MOUNT_POINT/$APP_NAME" ]] || fail "$APP_NAME was not found in the disk image."
    say "Copying Basil..."
    ditto "$MOUNT_POINT/$APP_NAME" "$WORK_DIR/$APP_NAME" || fail "Could not copy $APP_NAME out of the disk image."
    hdiutil detach "$MOUNT_POINT" -quiet >/dev/null 2>&1 || true
}

verify_app() {
    say "Checking the code signature and Gatekeeper's assessment..."
    codesign --verify --deep --strict "$WORK_DIR/$APP_NAME" >/dev/null 2>&1 || fail "The code signature is not valid. Nothing was installed."
    spctl --assess --type execute "$WORK_DIR/$APP_NAME" >/dev/null 2>&1 || fail "Gatekeeper rejected the app. Nothing was installed."
}

ensure_not_running() {
    local dest="$1/$APP_NAME"
    if [[ -d "$dest" ]] && pgrep -f "$dest/Contents/" >/dev/null 2>&1; then
        fail "Basil is running from $dest. Quit Basil, then run this command again."
    fi
}

install_app() {
    local dest_dir="$1"
    local dest="$dest_dir/$APP_NAME"
    local previous=""
    if [[ -d "$dest" ]]; then
        previous="$WORK_DIR/previous-$APP_NAME"
        mv "$dest" "$previous" || fail "Could not move the existing Basil out of the way."
    fi
    if ! ditto "$WORK_DIR/$APP_NAME" "$dest"; then
        rm -rf "$dest"
        if [[ -n "$previous" ]]; then
            mv "$previous" "$dest" || true
        fi
        fail "Could not copy Basil into $dest_dir. Your previous copy, if any, was restored."
    fi
}

main() {
    local open_after=1 arg
    for arg in "$@"; do
        case "$arg" in
            --no-open) open_after=0 ;;
            --help|-h) usage; exit 0 ;;
            *) fail "Unknown option '$arg'. Use --help to see the options." ;;
        esac
    done

    check_platform
    trap cleanup EXIT
    WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/basil-install.XXXXXX")"

    local base dest_dir
    base="$(download_base)"
    dest_dir="$(choose_install_dir)"
    ensure_not_running "$dest_dir"

    download_release "$base"
    verify_checksum
    copy_app_out_of_image
    verify_app
    ensure_not_running "$dest_dir"
    install_app "$dest_dir"

    say "Basil is installed in $dest_dir."
    if [[ "$open_after" -eq 1 ]]; then
        open "$dest_dir/$APP_NAME"
    fi
}

main "$@"
