#!/bin/bash
# Appcast Management Script for Basil (Sparkle Updates)
# Generates or updates the appcast.xml feed with a new release entry.
#
# Usage:
#   ./update_appcast.sh --version 1.1.0 --build 202602241530 --dmg /path/to/Basil.dmg \
#       --download-url https://downloads.example.com/releases/Basil-1.1.0.dmg \
#       [--release-notes "Bug fixes and improvements"] \
#       [--appcast /path/to/appcast.xml]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[APPCAST]${NC} $1"; }
print_success() { echo -e "${GREEN}[APPCAST]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[APPCAST]${NC} $1"; }
print_error() { echo -e "${RED}[APPCAST]${NC} $1"; }

# Script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Sparkle tools
SPARKLE_SIGN_TOOL="$ROOT_DIR/client/.build/artifacts/sparkle/Sparkle/bin/sign_update"

# Defaults
APPCAST_FILE=""
VERSION=""
BUILD_NUMBER=""
DMG_PATH=""
DOWNLOAD_URL=""
RELEASE_NOTES=""
MIN_SYSTEM_VERSION="13.0"
APPCAST_URL=""

print_usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Generates or updates the appcast.xml feed for Sparkle updates."
    echo ""
    echo "Required options:"
    echo "  --version X.Y.Z       App version (CFBundleShortVersionString)"
    echo "  --build NUMBER        Build number (CFBundleVersion)"
    echo "  --dmg PATH            Path to the signed DMG file"
    echo "  --download-url URL    Public HTTPS URL where the DMG will be hosted"
    echo ""
    echo "Optional:"
    echo "  --release-notes TEXT  Release notes (plain text, wrapped in HTML)"
    echo "  --appcast PATH        Path to appcast.xml (default: build/appcast.xml)"
    echo "  --min-os VERSION      Minimum macOS version (default: 13.0)"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 --version 1.1.0 --build 202602241530 \\"
    echo "     --dmg build/outputs/20260224_153000/Basil-20260224_153000.dmg \\"
    echo "     --download-url https://downloads.example.com/releases/Basil-1.1.0.dmg \\"
    echo "     --release-notes 'Added in-app updates via Sparkle.'"
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --build)
            BUILD_NUMBER="$2"
            shift 2
            ;;
        --dmg)
            DMG_PATH="$2"
            shift 2
            ;;
        --download-url)
            DOWNLOAD_URL="$2"
            shift 2
            ;;
        --release-notes)
            RELEASE_NOTES="$2"
            shift 2
            ;;
        --appcast)
            APPCAST_FILE="$2"
            shift 2
            ;;
        --min-os)
            MIN_SYSTEM_VERSION="$2"
            shift 2
            ;;
        -h|--help)
            print_usage
            ;;
        *)
            print_error "Unknown argument: $1"
            print_usage
            ;;
    esac
done

# Set default appcast path
if [ -z "$APPCAST_FILE" ]; then
    APPCAST_FILE="$ROOT_DIR/build/appcast.xml"
fi

# Validate required arguments
if [ -z "$VERSION" ]; then
    print_error "Missing required argument: --version"
    print_usage
fi

if [ -z "$BUILD_NUMBER" ]; then
    print_error "Missing required argument: --build"
    print_usage
fi

if [ -z "$DMG_PATH" ]; then
    print_error "Missing required argument: --dmg"
    print_usage
fi

if [ -z "$DOWNLOAD_URL" ]; then
    print_error "Missing required argument: --download-url"
    print_usage
fi
APPCAST_URL="${BASIL_APPCAST_URL:-${DOWNLOAD_URL%/releases/*}/appcast.xml}"

if [ ! -f "$DMG_PATH" ]; then
    print_error "DMG file not found at: $DMG_PATH"
    exit 1
fi

# Without --release-notes, use BASIL_RELEASE_NOTES_FILE when set, otherwise this version's CHANGELOG.md section
if [ -z "$RELEASE_NOTES" ]; then
    RELEASE_NOTES_FILE="${BASIL_RELEASE_NOTES_FILE:-}"
    if [ -n "$RELEASE_NOTES_FILE" ]; then
        if [ ! -f "$RELEASE_NOTES_FILE" ] || [ -z "$(tr -d '[:space:]' < "$RELEASE_NOTES_FILE")" ]; then
            print_error "BASIL_RELEASE_NOTES_FILE points to a missing or empty file: $RELEASE_NOTES_FILE"
            exit 1
        fi
        RELEASE_NOTES=$(cat "$RELEASE_NOTES_FILE")
        print_status "Using release notes from: $RELEASE_NOTES_FILE"
    elif RELEASE_NOTES=$("$SCRIPT_DIR/changelog_section.sh" "$VERSION"); then
        print_status "Using release notes from CHANGELOG.md section $VERSION"
    else
        print_error "Add a '## $VERSION' section with '- ' bullets to CHANGELOG.md, or pass --release-notes \"Your notes here\"."
        exit 1
    fi
fi

# Get DMG file size in bytes (wc -c is portable across macOS and GNU coreutils)
DMG_LENGTH=$(wc -c < "$DMG_PATH" | tr -d ' ')
print_status "DMG file size: $DMG_LENGTH bytes ($(echo "scale=1; $DMG_LENGTH / 1048576" | bc)MB)"

# Sign the DMG with Sparkle EdDSA key
if [ ! -f "$SPARKLE_SIGN_TOOL" ]; then
    print_error "Sparkle sign_update tool not found at: $SPARKLE_SIGN_TOOL"
    print_error "Run 'swift package resolve' in client/ first."
    exit 1
fi

print_status "Signing DMG with EdDSA key..."
SIGN_OUTPUT=$("$SPARKLE_SIGN_TOOL" "$DMG_PATH" 2>&1)

# The sign_update tool outputs: sparkle:edSignature="..." length="..."
# Extract the edSignature value
ED_SIGNATURE=$(echo "$SIGN_OUTPUT" | grep -o 'sparkle:edSignature="[^"]*"' | sed 's/sparkle:edSignature="//;s/"$//')

if [ -z "$ED_SIGNATURE" ]; then
    print_error "Failed to extract EdDSA signature from sign_update output."
    print_error "Output was: $SIGN_OUTPUT"
    print_error "Make sure EdDSA private key is in your Keychain (run generate_keys if needed)."
    exit 1
fi

print_success "EdDSA signature: ${ED_SIGNATURE:0:20}..."

# Generate publication date in RFC 2822 format
PUB_DATE=$(date -R)

# Convert release notes lines into HTML list items
# Each line starting with "- " becomes an <li>, others become plain <li>
RELEASE_NOTES_HTML=$(echo "$RELEASE_NOTES" | while IFS= read -r line; do
    # Skip empty lines
    [ -z "$(echo "$line" | tr -d '[:space:]')" ] && continue
    # Strip leading "- " if present
    clean_line=$(echo "$line" | sed 's/^[[:space:]]*-[[:space:]]*//')
    echo "            <li>$clean_line</li>"
done)

# Build the new <item> XML entry
NEW_ITEM=$(cat <<EOF
      <item>
        <title>Version $VERSION</title>
        <description><![CDATA[
          <h2>New in $VERSION</h2>
          <ul>
$RELEASE_NOTES_HTML
          </ul>
        ]]></description>
        <pubDate>$PUB_DATE</pubDate>
        <sparkle:version>$BUILD_NUMBER</sparkle:version>
        <sparkle:shortVersionString>$VERSION</sparkle:shortVersionString>
        <sparkle:minimumSystemVersion>$MIN_SYSTEM_VERSION</sparkle:minimumSystemVersion>
        <enclosure url="$DOWNLOAD_URL"
                   length="$DMG_LENGTH"
                   type="application/octet-stream"
                   sparkle:edSignature="$ED_SIGNATURE" />
      </item>
EOF
)

# Create or update the appcast file
if [ -f "$APPCAST_FILE" ]; then
    # Appcast exists - insert new item after <language> tag (newest first)
    print_status "Updating existing appcast at: $APPCAST_FILE"

    # Remove any existing entry for this version to avoid duplicates
    TEMP_FILE=$(mktemp)
    awk -v ver="$VERSION" '
        /<item>/ { buf = $0; inside = 1; next }
        inside {
            buf = buf "\n" $0
            if ($0 ~ /<\/item>/) {
                inside = 0
                if (buf !~ "<sparkle:shortVersionString>" ver "</sparkle:shortVersionString>") {
                    print buf
                }
                buf = ""
            }
            next
        }
        { print }
    ' "$APPCAST_FILE" > "$TEMP_FILE"
    mv "$TEMP_FILE" "$APPCAST_FILE"

    # Insert new item immediately after the <language> line (newest first ordering)
    TEMP_ITEM=$(mktemp)
    TEMP_FILE=$(mktemp)
    echo "$NEW_ITEM" > "$TEMP_ITEM"

    awk -v itemfile="$TEMP_ITEM" '
        { print }
        /<language>/ {
            while ((getline line < itemfile) > 0) print line
            close(itemfile)
        }
    ' "$APPCAST_FILE" > "$TEMP_FILE"

    mv "$TEMP_FILE" "$APPCAST_FILE"
    rm -f "$TEMP_ITEM"
    print_success "New version $VERSION added to existing appcast (newest first)."
else
    # Create a new appcast file
    print_status "Creating new appcast at: $APPCAST_FILE"
    
    cat > "$APPCAST_FILE" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Basil Updates</title>
    <link>$APPCAST_URL</link>
    <description>Updates for the Basil application.</description>
    <language>en</language>
$NEW_ITEM
  </channel>
</rss>
EOF
    
    print_success "New appcast created with version $VERSION."
fi

print_success "Appcast file: $APPCAST_FILE"
print_status ""
print_status "Next steps:"
print_status "  1. Upload the DMG to: $DOWNLOAD_URL"
print_status "  2. Upload the appcast to: $APPCAST_URL"
print_status "  3. Verify HTTPS is working for both URLs"
