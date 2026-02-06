#!/usr/bin/env python3
"""
DMG Background Generator for BrainDock

Creates a professional DMG installer background with:
- BrainDock app icon (with rounded corners) on the left
- Arrow pointing to Applications folder on the right

Usage:
    python build/create_dmg_background.py
"""

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Error: Pillow is required. Install with: pip install pillow")
    sys.exit(1)


# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SOURCE_LOGO = PROJECT_ROOT / "assets" / "logo_icon.png"
OUTPUT_PATH = SCRIPT_DIR / "dmg_background.png"

# DMG window dimensions (standard size for installer windows)
DMG_WIDTH = 660
DMG_HEIGHT = 400

# Icon positions - centered in the window with good spacing
# Left icon (app) and right icon (Applications) with arrow between
ICON_Y = 190  # Vertical center for icons
LEFT_ICON_X = 180  # App icon position
RIGHT_ICON_X = 480  # Applications folder position
ARROW_CENTER_X = (LEFT_ICON_X + RIGHT_ICON_X) // 2  # Arrow centered between icons

# Colors
BACKGROUND_COLOR = (30, 30, 35)  # Dark grey, matches app theme
ARROW_COLOR = (255, 255, 255)  # White arrow
ICON_BG_COLOR = (45, 45, 50)  # Slightly lighter for icon background


def create_rounded_mask(size: tuple, radius: int) -> Image:
    """
    Create a rounded rectangle mask for app icon style.
    
    Args:
        size: (width, height) tuple
        radius: Corner radius
        
    Returns:
        PIL Image mask with rounded corners
    """
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def create_app_icon(logo: Image, size: int = 100, corner_radius: int = 22) -> Image:
    """
    Create an app icon with rounded corners (macOS style).
    
    Args:
        logo: Source logo image
        size: Output icon size
        corner_radius: Radius for rounded corners
        
    Returns:
        PIL Image with app icon styling
    """
    # Create icon background with rounded corners
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    
    # Create rounded rectangle background
    bg = Image.new("RGBA", (size, size), ICON_BG_COLOR)
    mask = create_rounded_mask((size, size), corner_radius)
    
    # Apply rounded mask to background
    icon.paste(bg, (0, 0), mask)
    
    # Resize logo to fit within the icon (with padding)
    logo_padding = 16
    logo_size = size - (logo_padding * 2)
    logo_resized = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
    
    # Center logo on icon
    logo_offset = logo_padding
    
    # Create a composite with the logo
    icon.paste(logo_resized, (logo_offset, logo_offset), logo_resized)
    
    # Apply rounded mask to entire icon for clean edges
    final_icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    final_icon.paste(icon, (0, 0), mask)
    
    return final_icon


def draw_arrow(draw: ImageDraw, start_x: int, start_y: int, 
               length: int = 80, thickness: int = 4, 
               head_size: int = 20, color: tuple = ARROW_COLOR):
    """
    Draw an arrow pointing right.
    
    Args:
        draw: PIL ImageDraw object
        start_x: Starting X position (left side of arrow)
        start_y: Y position (vertical center of arrow)
        length: Total length of arrow
        thickness: Line thickness
        head_size: Size of arrowhead
        color: Arrow color (RGB tuple)
    """
    end_x = start_x + length
    half_thick = thickness // 2
    
    # Draw arrow shaft (rectangle)
    shaft_end = end_x - head_size
    draw.rectangle(
        [start_x, start_y - half_thick, shaft_end, start_y + half_thick],
        fill=color
    )
    
    # Draw arrowhead (triangle pointing right)
    arrow_points = [
        (shaft_end - 2, start_y - head_size // 2),  # Top left of head
        (end_x, start_y),                            # Tip
        (shaft_end - 2, start_y + head_size // 2),  # Bottom left of head
    ]
    draw.polygon(arrow_points, fill=color)


def create_dmg_background():
    """
    Create the DMG background image with app icon and arrow.
    
    Returns:
        True if successful, False otherwise
    """
    print("=" * 50)
    print("BrainDock DMG Background Generator")
    print("=" * 50)
    print()
    
    # Verify source logo exists
    if not SOURCE_LOGO.exists():
        print(f"Error: Source logo not found at {SOURCE_LOGO}")
        return False
    
    print(f"Source logo: {SOURCE_LOGO}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Dimensions: {DMG_WIDTH}x{DMG_HEIGHT}")
    print()
    
    try:
        # Create base image with dark background
        background = Image.new("RGBA", (DMG_WIDTH, DMG_HEIGHT), BACKGROUND_COLOR)
        draw = ImageDraw.Draw(background)
        
        # Load the logo
        with Image.open(SOURCE_LOGO) as logo:
            # Convert to RGBA if necessary
            if logo.mode != "RGBA":
                logo = logo.convert("RGBA")
            
            # Create app icon with rounded corners (macOS style)
            icon_size = 100
            app_icon = create_app_icon(logo, size=icon_size, corner_radius=22)
            
            # Position app icon on the left (centered at LEFT_ICON_X)
            icon_x = LEFT_ICON_X - icon_size // 2
            icon_y = ICON_Y - icon_size // 2
            
            # Paste app icon onto background
            background.paste(app_icon, (icon_x, icon_y), app_icon)
        
        # Draw arrow between app icon and Applications folder position
        arrow_length = 100
        arrow_start_x = ARROW_CENTER_X - arrow_length // 2
        
        draw_arrow(
            draw,
            start_x=arrow_start_x,
            start_y=ICON_Y,
            length=arrow_length,
            thickness=6,
            head_size=24,
            color=ARROW_COLOR
        )
        
        # Save the background image
        background.save(OUTPUT_PATH, "PNG")
        
        print(f"Background created: {OUTPUT_PATH}")
        print(f"App icon position: ({LEFT_ICON_X}, {ICON_Y})")
        print(f"Applications position: ({RIGHT_ICON_X}, {ICON_Y})")
        print()
        print("=" * 50)
        print("DMG background generation complete!")
        print("=" * 50)
        
        return True
        
    except Exception as e:
        print(f"Error creating DMG background: {e}")
        return False


def main():
    """Main entry point."""
    if not create_dmg_background():
        sys.exit(1)


if __name__ == "__main__":
    main()
