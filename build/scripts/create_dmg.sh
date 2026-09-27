#!/bin/bash

# DMG Creation Script for Basil
# Creates a distributable disk image from the built application bundle

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILDS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$BUILDS_DIR/outputs"
DMG_DIR="$BUILDS_DIR/dmg_staging"

# DMG Settings
DMG_NAME="Basil"
DMG_BACKGROUND_NAME="background.png"
WINDOW_SIZE="600,400"
ICON_SIZE=72
APP_ICON_POS="150,200"
APPLICATIONS_ICON_POS="450,200"

print_status() {
    echo -e "${BLUE}[DMG]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[DMG]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[DMG]${NC} $1"
}

print_error() {
    echo -e "${RED}[DMG]${NC} $1"
}

find_latest_build() {
    local latest_dir
    latest_dir=$(find "$OUTPUT_DIR" -maxdepth 1 -type d -name "????????_??????" | sort -r | head -n 1)
    
    if [[ -z "$latest_dir" ]]; then
        print_error "No build output directories found in $OUTPUT_DIR"
        print_error "Please run ./build_app.sh first to create an application bundle"
        exit 1
    fi
    
    if [[ ! -d "$latest_dir/Basil.app" ]]; then
        print_error "Basil.app not found in $latest_dir"
        print_error "Please ensure the build completed successfully"
        exit 1
    fi
    
    echo "$latest_dir"
}

create_dmg_staging() {
    local source_dir="$1"
    local timestamp="$2"
    
    print_status "Creating DMG staging directory..."
    
    # Clean and create staging directory
    if [[ -d "$DMG_DIR" ]]; then
        rm -rf "$DMG_DIR"
    fi
    mkdir -p "$DMG_DIR"
    
    # Copy application bundle
    print_status "Copying Basil.app to staging area..."
    cp -R "$source_dir/Basil.app" "$DMG_DIR/"
    
    # Create symbolic link to Applications folder
    print_status "Creating Applications shortcut..."
    ln -s /Applications "$DMG_DIR/Applications"
    
    # Create basic background (simple gradient)
    print_status "Creating DMG background..."
    # Using ImageMagick if available, otherwise skip background
    if type -P convert >/dev/null 2>&1; then
        convert -size 600x400 gradient:#f0f0f0-#e0e0e0 "$DMG_DIR/$DMG_BACKGROUND_NAME"
    else
        print_warning "ImageMagick not found - DMG will use default background"
    fi
    
    # Create a simple README if it doesn't exist
    if [[ ! -f "$DMG_DIR/README.txt" ]]; then
        cat > "$DMG_DIR/README.txt" << EOF
Basil - AI Assistant Application

Installation:
1. Drag Basil.app to the Applications folder
2. Launch Basil from Applications or Spotlight

System Requirements:
- macOS 10.15 or later
- 2GB RAM minimum
- Internet connection for initial model downloads

Build timestamp: $timestamp
EOF
    fi
}

create_dmg_image() {
    local source_dir="$1"
    local timestamp="$2"
    local output_dmg="$source_dir/${DMG_NAME}-${timestamp}.dmg"
    local temp_dmg="$source_dir/temp-${DMG_NAME}.dmg"
    
    print_status "Creating disk image..." >&2
    
    # Calculate size needed (app bundle size + generous buffer for large bundles)
    local app_size
    app_size=$(du -sm "$DMG_DIR/Basil.app" | cut -f1)
    # For large bundles, add more buffer space (minimum 200MB buffer)
    local buffer_size=$((app_size > 1000 ? app_size / 5 : 200))
    local dmg_size=$((app_size + buffer_size))
    
    print_status "App bundle size: ${app_size}MB, DMG size: ${dmg_size}MB" >&2
    
    # Create initial DMG
    hdiutil create -size "${dmg_size}m" -fs HFS+ -volname "$DMG_NAME" "$temp_dmg" >&2
    
    # Mount the DMG
    print_status "Mounting disk image for configuration..." >&2
    local mount_point
    mount_point=$(hdiutil attach "$temp_dmg" 2>&1 | grep "Volumes" | cut -f3)
    
    if [[ -z "$mount_point" ]]; then
        print_error "Failed to mount temporary DMG" >&2
        exit 1
    fi
    
    # Copy contents to mounted DMG
    print_status "Copying files to disk image..." >&2
    cp -R "$DMG_DIR/Basil.app" "$mount_point/" 2>/dev/null || {
        print_warning "Some files couldn't be copied due to space constraints" >&2
        print_status "Continuing with available content..." >&2
    }
    
    # Copy other files if space allows
    if cp -R "$DMG_DIR/Applications" "$mount_point/" 2>/dev/null; then
        print_status "Applications shortcut copied successfully" >&2
    fi
    
    if [[ -f "$DMG_DIR/README.txt" ]]; then
        cp "$DMG_DIR/README.txt" "$mount_point/" 2>/dev/null
    fi
    
    if [[ -f "$DMG_DIR/$DMG_BACKGROUND_NAME" ]]; then
        mkdir -p "$mount_point/.background" 2>/dev/null
        cp "$DMG_DIR/$DMG_BACKGROUND_NAME" "$mount_point/.background/" 2>/dev/null
    fi
    
    # Configure DMG window appearance using AppleScript (with error handling)
    print_status "Configuring DMG window appearance..." >&2
    osascript << EOF >/dev/null 2>&1 || print_warning "Could not configure window appearance" >&2
tell application "Finder"
    try
        tell disk "$DMG_NAME"
            open
            set current view of container window to icon view
            set toolbar visible of container window to false
            set statusbar visible of container window to false
            set the bounds of container window to {100, 100, 700, 500}
            set opts to the icon view options of container window
            set icon size of opts to $ICON_SIZE
            set arrangement of opts to not arranged
            
            -- Position icons if they exist
            if exists item "Basil.app" then
                set position of item "Basil.app" of container window to {$APP_ICON_POS}
            end if
            if exists item "Applications" then
                set position of item "Applications" of container window to {$APPLICATIONS_ICON_POS}
            end if
            
            -- Set background if available
            if exists file ".background:$DMG_BACKGROUND_NAME" then
                set background picture of opts to file ".background:$DMG_BACKGROUND_NAME"
            end if
            
            update without registering applications
            delay 2
            close
        end tell
    end try
end tell
EOF
    
    # Unmount the DMG
    print_status "Finalizing disk image..." >&2
    hdiutil detach "$mount_point" >/dev/null 2>&1
    
    # Convert to final compressed DMG
    print_status "Compressing final image..." >&2
    hdiutil convert "$temp_dmg" -format UDZO -o "$output_dmg" >&2
    
    # Add a small delay to ensure file is written before next operations
    sleep 2 
    
    rm "$temp_dmg"
    
    # Only echo the path to stdout for capture
    echo "$output_dmg"
}

main() {
    print_status "Starting DMG creation process..."
    
    # Find the latest build
    local build_dir
    build_dir=$(find_latest_build)
    local timestamp
    timestamp=$(basename "$build_dir")
    
    print_status "Using build from: $build_dir"
    print_status "Build timestamp: $timestamp"
    
    # Create staging area
    create_dmg_staging "$build_dir" "$timestamp"
    
    # Create the DMG
    local final_dmg
    final_dmg=$(create_dmg_image "$build_dir" "$timestamp")
    
    # Cleanup staging
    print_status "Cleaning up staging directory..."
    rm -rf "$DMG_DIR"
    
    print_success "DMG created successfully!"
    print_success "Location: $final_dmg"
    
    # Show file size
    local dmg_size
    dmg_size=$(du -h "$final_dmg" | cut -f1)
    print_success "Size: $dmg_size"
    
    # Verify DMG integrity
    print_status "Verifying DMG integrity..."
    if hdiutil verify "$final_dmg"; then
        print_success "DMG verification passed"
    else
        print_warning "DMG verification failed - image may be corrupted"
    fi
}

# Show usage if help requested
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    echo "Usage: $0 [options]"
    echo ""
    echo "Creates a DMG disk image from the latest Basil application build."
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help message"
    echo ""
    echo "Prerequisites:"
    echo "  - Run ./build_app.sh first to create the application bundle"
    echo "  - ImageMagick (optional, for custom background)"
    echo ""
    echo "Output:"
    echo "  Creates Basil-TIMESTAMP.dmg in the build output directory"
    exit 0
fi

# Run main function
main "$@" 