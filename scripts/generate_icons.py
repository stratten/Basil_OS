from PIL import Image, ImageDraw, ImageFont
import os
import json
import shutil
import argparse

# Determine paths relative to this script's location
SCRIPT_REAL_PATH = os.path.realpath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_REAL_PATH)
WORKSPACE_ROOT = os.path.dirname(SCRIPT_DIR) # Assumes script is in <WORKSPACE_ROOT>/scripts/
TARGET_JCLIENT_DIR = os.path.join(WORKSPACE_ROOT, "client") # Path to the client directory
TARGET_JCLIENT_SOURCES_DIR = os.path.join(TARGET_JCLIENT_DIR, "Sources")
TARGET_RESOURCES_DIR = os.path.join(TARGET_JCLIENT_SOURCES_DIR, "Resources")
TARGET_ASSETS_XCASSETS_DIR = os.path.join(TARGET_RESOURCES_DIR, "Assets.xcassets")
APP_ICON_MARK_SOURCE = os.path.join(TARGET_RESOURCES_DIR, "app_icon_circle_source.png")
DEV_DOCK_LOGO_SOURCE = os.path.join(TARGET_RESOURCES_DIR, "dev_dock_logo.png")
RUNTIME_DOCK_ICON_PATH = os.path.join(TARGET_RESOURCES_DIR, "DockIcon.png")

def create_icon(size: int, bg_color: tuple[int, int, int], text_color: tuple[int, int, int], font_scale: float = 0.63, dots: dict = None, is_dev_variant: bool = False) -> Image.Image:
    """Create a circular icon with a letter B and optional status dots."""
    
    actual_bg_color = bg_color
    actual_text_color = text_color
    if is_dev_variant:
        # Swap background and text color for dev variant
        actual_bg_color, actual_text_color = text_color, bg_color
        print(f"Creating DEV VARIANT icon with size={size}, bg_color={actual_bg_color}, text_color={actual_text_color}, dots={dots}")
    else:
        print(f"Creating icon with size={size}, bg_color={actual_bg_color}, text_color={actual_text_color}, dots={dots}")
    
    # Create a new image with alpha channel (RGBA)
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Calculate dynamic padding for the circle
    # Ensure the circle doesn't touch the image edges
    # Let's use a padding of about 2.5% of the size, with a minimum of 1px for small icons
    # and ensure it's an integer.
    min_padding = 1 if size <= 32 else 2 # Minimum 1px for tiny, 2px for slightly larger
    calculated_padding = int(size * 0.025) 
    circle_padding = max(min_padding, calculated_padding)

    # Ensure drawing coordinates are within bounds and create a clear visual separation
    # The bounding box for the ellipse should be inset by circle_padding
    ellipse_bbox = [
        circle_padding,
        circle_padding,
        size - circle_padding -1, # Subtract 1 to avoid drawing on the very last pixel line if size is odd and padding is small
        size - circle_padding -1  # Subtract 1 for the same reason
    ]

    # Ensure coordinates are valid (top-left < bottom-right)
    if ellipse_bbox[0] >= ellipse_bbox[2] or ellipse_bbox[1] >= ellipse_bbox[3]:
        # This might happen if size is too small and padding is too large.
        # Fallback to a minimal ellipse if padding makes bbox invalid.
        ellipse_bbox = [0, 0, size-1, size-1]
        if size <=2: # if size is extremely small, just draw a tiny dot
             ellipse_bbox = [0,0,1,1]


    # Draw the circle with full opacity using actual_bg_color
    draw.ellipse(
        ellipse_bbox, # Use the calculated bounding box
        fill=(*actual_bg_color, 255)  # Add full opacity
    )
    
    # Add the letter B with full opacity
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(size * font_scale))
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * font_scale))
        except:
            font = ImageFont.load_default()
    
    # Get text size for centering
    text = "B"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # Draw the text centered with full opacity using actual_text_color
    x = (size - text_width) / 2
    # Adjust Y position for true vertical centering
    y = (size - text_height) / 2 - (size * 0.05)  # Small adjustment for optical centering
    draw.text((x, y), text, font=font, fill=(*actual_text_color, 255))  # Add full opacity
    
    # Add status dots if requested
    if dots:
        dot_size = max(4, int(size * 0.18))  # Slightly smaller dots to fit multiple
        dot_padding = max(1, int(size * 0.05))
        
        # Define dot colors (not affected by dev variant)
        dot_colors = {
            "red": (255, 0, 0, 255),
            "green": (50, 255, 50, 255),  # Bright neon green
            "yellow": (255, 255, 0, 255)
        }
        
        # Position dots around the circle
        # Top-right (same as current recording/active dot)
        if dots.get("top"):
            dot_x = size - dot_size - dot_padding
            dot_y = dot_padding
            color = dot_colors.get(dots["top"], (255, 255, 255, 255))
            draw.ellipse([dot_x, dot_y, dot_x + dot_size, dot_y + dot_size], fill=color)
        
        # Middle-right (voice listener status)
        if dots.get("middle"):
            dot_x = size - dot_size - dot_padding
            dot_y = (size - dot_size) // 2
            color = dot_colors.get(dots["middle"], (255, 255, 255, 255))
            draw.ellipse([dot_x, dot_y, dot_x + dot_size, dot_y + dot_size], fill=color)
        
        # Bottom-right (activity capture status)
        if dots.get("bottom"):
            dot_x = size - dot_size - dot_padding
            dot_y = size - dot_size - dot_padding
            color = dot_colors.get(dots["bottom"], (255, 255, 255, 255))
            draw.ellipse([dot_x, dot_y, dot_x + dot_size, dot_y + dot_size], fill=color)
    
    return img

def create_imageset(base_path: str, name: str, scales: list[int] = [1, 2, 3]):
    """Create an imageset directory with Contents.json and images at specified scales."""
    
    # Always use the base name for the imageset path and internal filenames
    imageset_path = f"{base_path}/{name}.imageset"
    os.makedirs(imageset_path, exist_ok=True)
    
    # Create Contents.json
    contents = {
        "images": [
            {
                "filename": f"{name}@{scale}x.png" if scale > 1 else f"{name}.png", # Use name directly
                "idiom": "universal",
                "scale": f"{scale}x"
            }
            for scale in scales
        ],
        "info": {
            "author": "xcode",
            "version": 1
        },
        "properties": {
            "template-rendering-intent": "original"
        }
    }
    
    with open(f"{imageset_path}/Contents.json", "w") as f:
        json.dump(contents, f, indent=2)
    
    return imageset_path

def load_circular_app_icon_mark_source() -> Image.Image | None:
    """Load the circle-first Basil app mark used by app and runtime Dock icons."""
    for source_path, label in [
        (DEV_DOCK_LOGO_SOURCE, "custom dev dock logo"),
        (APP_ICON_MARK_SOURCE, "stored circle app mark"),
    ]:
        if os.path.exists(source_path):
            print(f"Using {label} for circular app icon: {source_path}")
            return Image.open(source_path).convert("RGBA")

    return None

def create_circular_app_icon(
    size: int,
    mark_source: Image.Image | None,
    is_dev_variant: bool = False
) -> Image.Image:
    """Create a transparent, circle-first Basil app icon at the requested size."""
    mark = mark_source.copy() if mark_source else create_icon(
        size=1024,
        bg_color=(0, 48, 135),
        text_color=(255, 255, 255),
        font_scale=0.63,
        is_dev_variant=is_dev_variant,
    )
    mark = mark.convert("RGBA")
    mark.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mark_x = (size - mark.width) // 2
    mark_y = (size - mark.height) // 2
    canvas.alpha_composite(mark, (mark_x, mark_y))
    return canvas

def generate_status_bar_icons(is_dev_variant: bool = False):
    """Generate all 27 combinations of status bar icons at 2x scale"""
    base_size = 22
    # Use the globally defined TARGET_RESOURCES_DIR and TARGET_ASSETS_XCASSETS_DIR
    os.makedirs(TARGET_RESOURCES_DIR, exist_ok=True)
    os.makedirs(TARGET_ASSETS_XCASSETS_DIR, exist_ok=True) # Ensure .xcassets exists

    # Define colors (these remain the same, create_icon handles swapping for dev)
    duke_blue = (0, 48, 135)
    white_color = (255, 255, 255)

    # Define all possible dot states
    # Top dot: N(one), G(reen), R(ed)
    # Middle dot: N(one), Y(ellow), G(reen)  
    # Bottom dot: N(one), Y(ellow), G(reen)
    top_states = ["N", "G", "R"]
    middle_states = ["N", "Y", "G"]
    bottom_states = ["N", "Y", "G"]
    
    # Map state codes to actual colors
    dot_color_map = {
        "N": None,
        "G": "green",
        "R": "red", 
        "Y": "yellow"
    }
    
    # Generate all 27 combinations
    for top in top_states:
        for middle in middle_states:
            for bottom in bottom_states:
                # Build the icon name
                icon_name = f"StatusBarIcon_T{top}_M{middle}_B{bottom}"
                
                # Build the dots dictionary
                dots = {}
                if dot_color_map[top]:
                    dots["top"] = dot_color_map[top]
                if dot_color_map[middle]:
                    dots["middle"] = dot_color_map[middle]
                if dot_color_map[bottom]:
                    dots["bottom"] = dot_color_map[bottom]
                
                # Create the icon
                icon = create_icon(
                    size=base_size * 2,
                    bg_color=duke_blue,
                    text_color=white_color,
                    font_scale=0.72,
                    dots=dots if dots else None,
                    is_dev_variant=is_dev_variant
                )
                
                # Save the icon
                icon.save(os.path.join(TARGET_RESOURCES_DIR, f"{icon_name}.png"), "PNG")

                # Create imageset for this combination
                create_imageset(TARGET_ASSETS_XCASSETS_DIR, icon_name)

def generate_app_icon(is_dev_variant: bool = False):
    """Generate app icon at required sizes for macOS"""
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    
    # Always generate to AppIcon.appiconset
    app_icon_set_name = "AppIcon" 
    app_icon_path = f"{TARGET_ASSETS_XCASSETS_DIR}/{app_icon_set_name}.appiconset"
    os.makedirs(app_icon_path, exist_ok=True)

    # Always use standard internal icon prefix "icon"
    internal_icon_prefix = "icon" 

    contents = {
        "images": [
            {
                "filename": f"{internal_icon_prefix}_{size}x{size}.png",
                "idiom": "mac",
                "scale": "1x",
                "size": f"{size}x{size}"
            }
            for size in sizes
        ] + [
            {
                "filename": f"{internal_icon_prefix}_{size}x{size}@2x.png",
                "idiom": "mac",
                "scale": "2x",
                "size": f"{size}x{size}"
            }
            for size in sizes
        ],
        "info": {
            "author": "xcode",
            "version": 1
        }
    }
    
    with open(f"{app_icon_path}/Contents.json", "w") as f:
        json.dump(contents, f, indent=2)
    
    mark_source = load_circular_app_icon_mark_source()
    if mark_source is None:
        print("No app icon foreground source found; using generated circle B mark.")

    dock_icon = create_circular_app_icon(
        size=1024,
        mark_source=mark_source,
        is_dev_variant=is_dev_variant
    )
    dock_icon.save(RUNTIME_DOCK_ICON_PATH, "PNG")
    print(f"Saved runtime circular Dock icon: {RUNTIME_DOCK_ICON_PATH}")

    # Generate icons
    for size in sizes:
        icon_filename_1x = f"{internal_icon_prefix}_{size}x{size}.png"
        icon_filename_2x = f"{internal_icon_prefix}_{size}x{size}@2x.png"

        icon = create_circular_app_icon(
            size=size,
            mark_source=mark_source,
            is_dev_variant=is_dev_variant
        )
        icon.save(f"{app_icon_path}/{icon_filename_1x}", "PNG")
        
        icon2x = create_circular_app_icon(
            size=size * 2,
            mark_source=mark_source,
            is_dev_variant=is_dev_variant
        )
        icon2x.save(f"{app_icon_path}/{icon_filename_2x}", "PNG")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Basil icons.")
    parser.add_argument(
        "--variant",
        type=str,
        default="standard",
        choices=["standard", "dev"],
        help="Icon variant to generate: 'standard' (blue bg, white B) or 'dev' (white bg, blue B)."
    )
    args = parser.parse_args()

    is_dev = args.variant == "dev"

    if is_dev:
        print("Generating DEV VARIANT icons...")
    else:
        print("Generating STANDARD icons...")
        
    generate_status_bar_icons(is_dev_variant=is_dev)
    generate_app_icon(is_dev_variant=is_dev)
    
    if is_dev:
        print("DEV VARIANT icons generated successfully!")
    else:
        print("STANDARD icons generated successfully!") 