#!/bin/bash
# Notarization script for Basil
# This script submits the signed app to Apple for notarization to avoid "malware" warnings

set -e

# Configuration
DEVELOPER_ID="${BASIL_APPLE_TEAM_ID:-}"
NOTARY_KEYCHAIN_PROFILE="${BASIL_NOTARY_KEYCHAIN_PROFILE:-notarytool-profile}"
NOTARY_AUTH_ARGS=(--keychain-profile "$NOTARY_KEYCHAIN_PROFILE")
if [[ -n "${BASIL_NOTARY_KEYCHAIN:-}" ]]; then
    NOTARY_AUTH_ARGS+=(--keychain "$BASIL_NOTARY_KEYCHAIN")
fi

# Function for logging with timestamp
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

print_usage() {
    echo "Usage: $0 <app_path> [--dmg <dmg_path>] [--skip-app-notarize]"
    echo ""
    echo "Notarizes a signed macOS application to avoid malware warnings."
    echo ""
    echo "Arguments:"
    echo "  app_path                Path to the signed .app bundle"
    echo "  --dmg dmg_path          Optional: Also notarize and staple the DMG"
    echo "  --skip-app-notarize     Skip the separate .app notarization; only notarize the DMG."
    echo "                          The DMG notarization covers all binaries inside it."
    echo "                          Saves ~1 hour but the .app won't have a locally stapled ticket."
    echo ""
    echo "Requirements:"
    echo "  - App must already be signed with Developer ID"
    echo "  - Xcode instruction line tools installed"
    echo "  - App-specific password stored in the configured keychain profile"
    echo ""
    echo "Setup (run once):"
    echo "  xcrun notarytool store-credentials \"$NOTARY_KEYCHAIN_PROFILE\" \\"
    echo "    --apple-id \"your-apple-id@example.com\" \\"
    echo "    --team-id \"$DEVELOPER_ID\" \\"
    echo "    --password \"your-app-specific-password\""
    exit 1
}

# Parse arguments
APP_PATH=""
DMG_PATH=""
SKIP_APP_NOTARIZE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dmg)
            DMG_PATH="$2"
            shift 2
            ;;
        --skip-app-notarize)
            SKIP_APP_NOTARIZE=true
            shift
            ;;
        -h|--help)
            print_usage
            ;;
        *)
            if [[ -z "$APP_PATH" ]]; then
                APP_PATH="$1"
            else
                echo "Error: Unknown argument $1"
                print_usage
            fi
            shift
            ;;
    esac
done

if [[ -z "$APP_PATH" ]]; then
    echo "Error: App path is required"
    print_usage
fi

if [[ ! -d "$APP_PATH" ]]; then
    echo "Error: App not found at $APP_PATH"
    exit 1
fi

if [[ -z "$DEVELOPER_ID" ]]; then
    echo "Error: Set BASIL_APPLE_TEAM_ID before notarizing a release."
    exit 1
fi

if [[ "$SKIP_APP_NOTARIZE" == true ]] && [[ -z "$DMG_PATH" ]]; then
    echo "Error: --skip-app-notarize requires --dmg <dmg_path> (otherwise nothing would be notarized)"
    exit 1
fi

# Check if app is signed
log "🔍 Verifying app signature..."
if ! codesign --verify --deep --strict "$APP_PATH"; then
    echo "❌ Error: App is not properly signed. Please sign with Developer ID first."
    exit 1
fi

# Check if hardened runtime is enabled
if ! codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep -q "runtime"; then
    echo "❌ Error: Hardened runtime not enabled. Please sign with --options runtime"
    exit 1
fi

log "✅ App signature verified with hardened runtime"

# --- .app Notarization (can be skipped with --skip-app-notarize) ---
if [[ "$SKIP_APP_NOTARIZE" == true ]]; then
    log "⏩ Skipping separate .app notarization (--skip-app-notarize flag set)"
    log "   The DMG notarization will cover all binaries inside the app."
    log "   Note: The .app will NOT have a locally stapled ticket."
    TEMP_DIR=$(mktemp -d)
else
    # Create temporary directory for notarization
    TEMP_DIR=$(mktemp -d)
    ZIP_PATH="$TEMP_DIR/$(basename "$APP_PATH" .app).zip"

    log "📦 Creating zip archive for notarization using ditto (preserves signatures)..."
    # Use ditto instead of zip to preserve extended attributes and code signatures
    ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

    log "🚀 Submitting app for notarization..."
    log "   This may take 15-30 minutes depending on Apple's servers..."

    # Submit for notarization
    SUBMISSION_ID=$(xcrun notarytool submit "$ZIP_PATH" \
        "${NOTARY_AUTH_ARGS[@]}" \
        --wait \
        --output-format plist | \
        plutil -extract id raw -)

    if [[ -z "$SUBMISSION_ID" ]]; then
        echo "❌ Error: Failed to submit for notarization"
        rm -rf "$TEMP_DIR"
        exit 1
    fi

    log "📋 Submission ID: $SUBMISSION_ID"

    # Check notarization status
    log "⏳ Waiting for notarization to complete..."
    xcrun notarytool wait "$SUBMISSION_ID" "${NOTARY_AUTH_ARGS[@]}"

    # Get notarization info
    log "📄 Getting notarization results..."
    NOTARIZATION_INFO=$(xcrun notarytool info "$SUBMISSION_ID" "${NOTARY_AUTH_ARGS[@]}" --output-format plist)

    # Check if notarization succeeded
    STATUS=$(echo "$NOTARIZATION_INFO" | plutil -extract status raw -)

    if [[ "$STATUS" != "Accepted" ]]; then
        echo "❌ Notarization failed with status: $STATUS"
        echo "📄 Getting detailed log..."
        xcrun notarytool log "$SUBMISSION_ID" "${NOTARY_AUTH_ARGS[@]}"
        rm -rf "$TEMP_DIR"
        exit 1
    fi

    log "✅ Notarization succeeded!"

    # Staple the notarization ticket to the app
    log "📎 Stapling notarization ticket to app..."
    if xcrun stapler staple "$APP_PATH"; then
        log "✅ Successfully stapled ticket to app"
    else
        echo "⚠️ Warning: Failed to staple ticket to app, but notarization succeeded"
    fi

    # Verify stapling
    if xcrun stapler validate "$APP_PATH"; then
        log "✅ App stapling verified"
    else
        log "⚠️ Warning: Could not verify stapling, but app should still work"
    fi
fi

# Notarize DMG if provided
if [[ -n "$DMG_PATH" ]]; then
    if [[ ! -f "$DMG_PATH" ]]; then
        echo "❌ Error: DMG not found at $DMG_PATH"
        rm -rf "$TEMP_DIR"
        exit 1
    else
        log "📦 Notarizing DMG..."
        
        DMG_SUBMISSION_ID=$(xcrun notarytool submit "$DMG_PATH" \
            "${NOTARY_AUTH_ARGS[@]}" \
            --wait \
            --output-format plist | \
            plutil -extract id raw -)
        
        if [[ -n "$DMG_SUBMISSION_ID" ]]; then
            log "📋 DMG Submission ID: $DMG_SUBMISSION_ID"
            xcrun notarytool wait "$DMG_SUBMISSION_ID" "${NOTARY_AUTH_ARGS[@]}"
            
            DMG_STATUS=$(xcrun notarytool info "$DMG_SUBMISSION_ID" "${NOTARY_AUTH_ARGS[@]}" --output-format plist | plutil -extract status raw -)
            
            if [[ "$DMG_STATUS" == "Accepted" ]]; then
                log "📎 Stapling notarization ticket to DMG..."
                if xcrun stapler staple "$DMG_PATH"; then
                    log "✅ Successfully stapled ticket to DMG"
                else
                    echo "❌ Error: Failed to staple the notarization ticket to the DMG"
                    rm -rf "$TEMP_DIR"
                    exit 1
                fi
            else
                echo "❌ DMG notarization failed with status: $DMG_STATUS"
                xcrun notarytool log "$DMG_SUBMISSION_ID" "${NOTARY_AUTH_ARGS[@]}" || true
                rm -rf "$TEMP_DIR"
                exit 1
            fi
        else
            echo "❌ Failed to submit DMG for notarization"
            rm -rf "$TEMP_DIR"
            exit 1
        fi
    fi
fi

# Cleanup
rm -rf "$TEMP_DIR"

log "🎉 Notarization process complete!"
log "📱 Your app should now launch without malware warnings on other machines."
log ""
log "Next steps:"
log "1. Test the app on another machine to verify no warnings appear"
log "2. If distributing via DMG, use the notarized DMG"
log "3. Consider adding this script to your automated build process" 