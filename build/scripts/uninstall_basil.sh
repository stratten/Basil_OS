#!/bin/bash

# Basil uninstaller.
#
# Removes Basil and everything Basil has put on this Mac: the app, its databases, recordings, downloaded models, preferences, caches, saved sign-in tokens, saved API keys, and the permissions macOS granted it.
#
# Every location it can touch is listed in the two tables below, so you can read exactly what it will do before you run it. It only acts on those locations. It never searches your disk, and it never deletes files you made in other places (for example documents Basil saved to your Desktop or Documents folder).
#
# Usage:
#   ./uninstall_basil.sh              Show what will be removed, then ask before removing it.
#   ./uninstall_basil.sh --dry-run    Show what would be removed and change nothing.
#   ./uninstall_basil.sh --yes        Remove everything without asking.
#   ./uninstall_basil.sh --keep-models  Keep the downloaded AI models in ~/.basil/models (they are large and can be downloaded again).
#   ./uninstall_basil.sh --keep-app   Remove the data but leave the app installed.
#   ./uninstall_basil.sh --help       Show this help.

set -u

readonly BUNDLE_ID="com.stratten.basil"
readonly PROVIDER_KEYS_KEYCHAIN_SERVICE="com.basil.providerKeys"
readonly KEYCHAIN_ACCOUNT_PREFIX="com.basil."
readonly APP_PROCESS_PATTERN='/Basil\.app/Contents/'

DRY_RUN=0
ASSUME_YES=0
KEEP_MODELS=0
KEEP_APP=0

# Each row is "path|what it holds". The app bundle rows are handled separately so --keep-app can skip them.
APP_BUNDLE_TABLE=(
    "/Applications/Basil.app|The Basil application"
    "$HOME/Applications/Basil.app|The Basil application (per-user install)"
)

DATA_TABLE=(
    "$HOME/.basil|Basil's main data folder: knowledge database, conversations, meeting recordings, agent task history, settings, downloaded models, logs, and backend credentials"
    "$HOME/.config/basil|Setup assistant state and voice listener settings"
    "$HOME/Library/Application Support/Basil|Recordings and captured data written by release builds"
    "$HOME/Library/Application Support/$BUNDLE_ID|Backend logs, process ID files, runtime bootstrap files, and trial key"
    "$HOME/Library/Preferences/$BUNDLE_ID.plist|App preferences and update-check state"
    "$HOME/Library/Caches/$BUNDLE_ID|Cached network responses and update downloads"
    "$HOME/Library/Caches/BasilClient|Cached data from development builds"
    "$HOME/Library/HTTPStorages/$BUNDLE_ID|Network session storage"
    "$HOME/Library/HTTPStorages/BasilClient|Network session storage from development builds"
    "$HOME/Library/WebKit/$BUNDLE_ID|Storage used by the app's built-in web views"
    "$HOME/Library/WebKit/BasilClient|Storage used by the web views of development builds"
    "$HOME/Library/Saved Application State/$BUNDLE_ID.savedState|Remembered window positions"
    "$HOME/Library/Logs/$BUNDLE_ID|Crash and diagnostic logs"
    "$HOME/Library/Logs/Basil|Crash and diagnostic logs"
)

if [ -t 1 ]; then
    BOLD=$'\033[1m'
    RED=$'\033[31m'
    GREEN=$'\033[32m'
    YELLOW=$'\033[33m'
    RESET=$'\033[0m'
else
    BOLD=""
    RED=""
    GREEN=""
    YELLOW=""
    RESET=""
fi

print_usage() {
    sed -n '3,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

fail() {
    echo "${RED}Error:${RESET} $1" >&2
    exit 1
}

for argument in "$@"; do
    case "$argument" in
        --dry-run) DRY_RUN=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        --keep-models) KEEP_MODELS=1 ;;
        --keep-app) KEEP_APP=1 ;;
        --help|-h) print_usage; exit 0 ;;
        *) fail "Unknown option: $argument (use --help)" ;;
    esac
done

[ "$(uname -s)" = "Darwin" ] || fail "This uninstaller is for macOS only."
[ "$(id -u)" -ne 0 ] || fail "Do not run this with sudo. It must run as the same user who uses Basil, because Basil's data lives in that user's home folder."
[ -n "${HOME:-}" ] && [ "${HOME#/}" != "$HOME" ] && [ "$HOME" != "/" ] && [ -d "$HOME" ] || fail "HOME is not set to a valid home folder, so nothing was changed."

human_size() {
    local kilobytes
    kilobytes=$(du -sk "$1" 2>/dev/null | cut -f1)
    kilobytes=${kilobytes:-0}
    if [ "$kilobytes" -ge 1048576 ]; then
        echo "$((kilobytes / 1048576)) GB"
    elif [ "$kilobytes" -ge 1024 ]; then
        echo "$((kilobytes / 1024)) MB"
    else
        echo "${kilobytes} KB"
    fi
}

path_exists() {
    [ -e "$1" ] || [ -L "$1" ]
}

# Refuses anything that is not strictly inside the user's home folder or /Applications, so a bad table entry can never delete something broad.
is_safe_target() {
    local target="$1"
    case "$target" in
        *"/../"*|*"/.."|"") return 1 ;;
        "$HOME"/?*/?*|"$HOME"/.basil|"$HOME"/Applications/?*|/Applications/?*) return 0 ;;
        *) return 1 ;;
    esac
}

remove_path() {
    local target="$1"
    if ! is_safe_target "$target"; then
        echo "  ${RED}Refused${RESET} (unsafe path): $target"
        return 1
    fi
    if [ -L "$target" ]; then
        echo "  Note: $target is a symbolic link. Only the link is removed; what it points to is left untouched."
    fi
    if rm -rf -- "$target" 2>/dev/null && ! path_exists "$target"; then
        echo "  ${GREEN}Removed${RESET} $target"
        return 0
    fi
    echo "  ${RED}Could not remove${RESET} $target (check its permissions, or remove it yourself)"
    return 1
}

remove_basil_data_folder_keeping_models() {
    local folder="$HOME/.basil"
    local child
    local status=0
    for child in "$folder"/* "$folder"/.[!.]* "$folder"/..?*; do
        path_exists "$child" || continue
        [ "$(basename "$child")" = "models" ] && continue
        remove_path "$child" || status=1
    done
    return $status
}

keychain_snapshot() {
    security dump-keychain 2>/dev/null
}

KEYCHAIN_DUMP="$(keychain_snapshot)"
KEYCHAIN_ACCOUNTS="$(printf '%s\n' "$KEYCHAIN_DUMP" | sed -n 's/^ *"acct"<blob>="\('"${KEYCHAIN_ACCOUNT_PREFIX//./\\.}"'[^"]*\)".*/\1/p' | sort -u)"
PROVIDER_KEY_COUNT="$(printf '%s\n' "$KEYCHAIN_DUMP" | grep -c "\"svce\"<blob>=\"$PROVIDER_KEYS_KEYCHAIN_SERVICE\"")"

count_lines() {
    if [ -z "$1" ]; then
        echo 0
    else
        printf '%s\n' "$1" | grep -c .
    fi
}

SIGN_IN_ITEM_COUNT="$(count_lines "$KEYCHAIN_ACCOUNTS")"

basil_is_running() {
    pgrep -f "$APP_PROCESS_PATTERN" >/dev/null 2>&1
}

print_plan() {
    local row path description
    local found=0

    echo "${BOLD}Basil uninstaller${RESET}"
    echo
    echo "This will remove the following from this Mac (user: $(id -un)):"
    echo

    if [ "$KEEP_APP" -eq 0 ]; then
        for row in "${APP_BUNDLE_TABLE[@]}"; do
            path="${row%%|*}"
            description="${row#*|}"
            if path_exists "$path"; then
                echo "  $path  ($(human_size "$path"))"
                echo "      $description"
                found=1
            fi
        done
    fi

    for row in "${DATA_TABLE[@]}"; do
        path="${row%%|*}"
        description="${row#*|}"
        if path_exists "$path"; then
            if [ "$path" = "$HOME/.basil" ] && [ "$KEEP_MODELS" -eq 1 ]; then
                echo "  $path  (everything except the models folder)"
            else
                echo "  $path  ($(human_size "$path"))"
            fi
            echo "      $description"
            found=1
        fi
    done

    if [ "$PROVIDER_KEY_COUNT" -gt 0 ]; then
        echo "  Keychain: $PROVIDER_KEY_COUNT saved API key(s) under the service \"$PROVIDER_KEYS_KEYCHAIN_SERVICE\""
        found=1
    fi
    if [ "$SIGN_IN_ITEM_COUNT" -gt 0 ]; then
        echo "  Keychain: $SIGN_IN_ITEM_COUNT saved sign-in, connection token, or API key item(s) whose account name starts with \"$KEYCHAIN_ACCOUNT_PREFIX\""
        found=1
    fi

    echo "  Permissions: Basil's macOS privacy grants (microphone, accessibility, screen recording, and so on) are reset for $BUNDLE_ID"
    echo "  Preferences: the stored settings for $BUNDLE_ID are cleared"

    if basil_is_running; then
        echo "  Basil is running right now. It will be quit first."
    fi

    echo
    echo "Not touched by this uninstaller:"
    echo "  - Files Basil created for you in other places, such as documents saved to your Desktop or Documents folder."
    echo "  - Shared model caches used by many tools (~/.cache/huggingface and ~/.cache/whisper). Basil may have downloaded models there; delete them yourself if you want that space back."
    echo "  - Anything that is not listed above."
    echo

    if [ "$found" -eq 0 ]; then
        echo "Nothing from Basil was found in the locations above, so there is nothing to remove."
    fi
}

quit_basil() {
    basil_is_running || return 0
    echo "Quitting Basil..."
    pkill -TERM -f "$APP_PROCESS_PATTERN" >/dev/null 2>&1
    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        basil_is_running || { echo "  Basil has quit."; return 0; }
        sleep 1
    done
    echo "  Basil did not quit in time, so it is being force-quit."
    pkill -KILL -f "$APP_PROCESS_PATTERN" >/dev/null 2>&1
    sleep 1
}

remove_keychain_items() {
    local count=0
    local account
    while security delete-generic-password -s "$PROVIDER_KEYS_KEYCHAIN_SERVICE" >/dev/null 2>&1; do
        count=$((count + 1))
        [ "$count" -ge 500 ] && break
    done
    if [ "$count" -gt 0 ]; then
        echo "  ${GREEN}Removed${RESET} $count saved API key(s) from the keychain"
    fi

    count=0
    while IFS= read -r account; do
        [ -n "$account" ] || continue
        local attempts=0
        while security delete-generic-password -a "$account" >/dev/null 2>&1; do
            count=$((count + 1))
            attempts=$((attempts + 1))
            [ "$attempts" -ge 20 ] && break
        done
    done <<< "$KEYCHAIN_ACCOUNTS"
    if [ "$count" -gt 0 ]; then
        echo "  ${GREEN}Removed${RESET} $count saved sign-in, connection token, or API key item(s) from the keychain"
    fi
}

clear_preferences_and_permissions() {
    defaults delete "$BUNDLE_ID" >/dev/null 2>&1 && echo "  ${GREEN}Cleared${RESET} stored preferences for $BUNDLE_ID"
    if tccutil reset All "$BUNDLE_ID" >/dev/null 2>&1; then
        echo "  ${GREEN}Reset${RESET} macOS privacy permissions for $BUNDLE_ID"
    else
        echo "  ${YELLOW}Could not reset${RESET} macOS privacy permissions. You can remove Basil from System Settings > Privacy & Security yourself."
    fi
}

run_removal() {
    local row path
    local status=0

    quit_basil

    echo "Removing data..."
    for row in "${DATA_TABLE[@]}"; do
        path="${row%%|*}"
        path_exists "$path" || continue
        if [ "$path" = "$HOME/.basil" ] && [ "$KEEP_MODELS" -eq 1 ]; then
            remove_basil_data_folder_keeping_models || status=1
        elif [ "$path" = "$HOME/Library/Preferences/$BUNDLE_ID.plist" ]; then
            continue
        else
            remove_path "$path" || status=1
        fi
    done

    echo "Removing saved credentials and settings..."
    remove_keychain_items
    clear_preferences_and_permissions
    path="$HOME/Library/Preferences/$BUNDLE_ID.plist"
    if path_exists "$path"; then
        remove_path "$path" || status=1
    fi

    if [ "$KEEP_APP" -eq 0 ]; then
        echo "Removing the application..."
        for row in "${APP_BUNDLE_TABLE[@]}"; do
            path="${row%%|*}"
            path_exists "$path" || continue
            remove_path "$path" || status=1
        done
    fi

    echo
    if [ "$status" -eq 0 ]; then
        echo "${GREEN}${BOLD}Done.${RESET} Basil has been removed from this Mac."
    else
        echo "${YELLOW}${BOLD}Finished with problems.${RESET} Items marked above could not be removed."
    fi
    return $status
}

print_plan

if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run: nothing was removed."
    exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
    if [ ! -t 0 ]; then
        fail "No terminal is available to ask for confirmation. Re-run in Terminal, or pass --yes to proceed without asking."
    fi
    printf 'Type "yes" and press Return to remove everything listed above, or anything else to cancel: '
    read -r answer
    if [ "$answer" != "yes" ]; then
        echo "Canceled. Nothing was removed."
        exit 0
    fi
    echo
fi

run_removal
removal_status=$?

if [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; then
    echo
    read -r -p "Press Return to close this window. " _
fi

exit $removal_status
