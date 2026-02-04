#!/usr/bin/env python3
"""
Icon Generator for BrainDock

Converts the source PNG logo to platform-specific icon formats:
- macOS: .icns (using iconutil)
- Windows: .ico (using Pillow)

Creates icons with a white rounded rectangle background and transparent corners,
ensuring proper display on both macOS and Windows.

Usage:
    python build/create_icons.py
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Error: Pillow is required. Install with: pip install pillow")
    sys.exit(1)


# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Use logo_icon.png (1024x1024 with transparency) as the source
LOGO_SOURCE = PROJECT_ROOT / "assets" / "logo_icon.png"
OUTPUT_DIR = SCRIPT_DIR  # Output to build/ directory

# Icon sizes required for each platform
MACOS_ICON_SIZES = [16, 32, 64, 128, 256, 512, 1024]
WINDOWS_ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Icon styling
ICON_BACKGROUND_COLOR = (255, 255, 255, 255)  # White background (RGBA)
ICON_CORNER_RADIUS_RATIO = 0.22  # Corner radius as ratio of icon size (iOS-style)
LOGO_PADDING_RATIO = 0.12  # Padding around logo as ratio of icon size (reduced for clarity)
SMALL_ICON_THRESHOLD = 48  # Icons smaller than this use reduced padding for clarity
SMALL_ICON_PADDING_RATIO = 0.08  # Even less padding for small icons


def create_rounded_rectangle_mask(size: int, radius: int) -> Image.Image:
    """
    Create a rounded rectangle mask for the icon.
    
    Args:
        size: Size of the square image
        radius: Corner radius in pixels
        
    Returns:
        Grayscale image to use as mask (white = visible, black = transparent)
    """
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    # Draw rounded rectangle (PIL 9.2.0+ has rounded_rectangle)
    draw.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=radius,
        fill=255
    )
    return mask


def create_app_icon(logo_path: Path, size: int) -> Image.Image:
    """
    Create a square app icon with the logo on a white rounded rectangle background.
    
    The icon has:
    - Transparent corners (for rounded effect on Windows)
    - White rounded rectangle background
    - Logo centered with padding (reduced for small icons for better clarity)
    
    Args:
        logo_path: Path to the logo image (should have transparency)
        size: Output icon size in pixels
        
    Returns:
        RGBA image ready for icon generation
    """
    # Calculate dimensions - use less padding for small icons
    corner_radius = int(size * ICON_CORNER_RADIUS_RATIO)
    if size < SMALL_ICON_THRESHOLD:
        # Small icons need less padding so the logo is more visible
        padding = int(size * SMALL_ICON_PADDING_RATIO)
    else:
        padding = int(size * LOGO_PADDING_RATIO)
    logo_area_size = size - (padding * 2)
    
    # Create transparent canvas
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    
    # Create white rounded rectangle background
    background = Image.new("RGBA", (size, size), ICON_BACKGROUND_COLOR)
    mask = create_rounded_rectangle_mask(size, corner_radius)
    
    # Apply mask to create rounded corners
    icon.paste(background, (0, 0), mask)
    
    # Load and resize logo
    with Image.open(logo_path) as logo:
        # Convert to RGBA if needed
        if logo.mode != "RGBA":
            logo = logo.convert("RGBA")
        
        # Calculate logo size maintaining aspect ratio
        logo_width, logo_height = logo.size
        aspect_ratio = logo_width / logo_height
        
        if aspect_ratio > 1:
            # Wider than tall
            new_width = logo_area_size
            new_height = int(logo_area_size / aspect_ratio)
        else:
            # Taller than wide or square
            new_height = logo_area_size
            new_width = int(logo_area_size * aspect_ratio)
        
        # Resize logo with high quality
        logo_resized = logo.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Center logo on icon
        x_offset = (size - new_width) // 2
        y_offset = (size - new_height) // 2
        
        # Paste logo onto icon (using logo's alpha as mask)
        icon.paste(logo_resized, (x_offset, y_offset), logo_resized)
    
    return icon


def create_macos_icns(logo_path: Path, output_path: Path) -> bool:
    """
    Create macOS .icns file from logo.
    
    Creates icons with white rounded rectangle background and logo centered.
    
    Args:
        logo_path: Path to logo PNG image (with transparency)
        output_path: Path for output .icns file
        
    Returns:
        True if successful, False otherwise
    """
    print("Creating macOS .icns icon...")
    
    # Create temporary iconset directory
    iconset_dir = output_path.with_suffix(".iconset")
    
    try:
        # Clean up any existing iconset
        if iconset_dir.exists():
            shutil.rmtree(iconset_dir)
        iconset_dir.mkdir(parents=True)
        
        # Generate icons at each required size
        for size in MACOS_ICON_SIZES:
            # Standard resolution
            icon_name = f"icon_{size}x{size}.png"
            icon_img = create_app_icon(logo_path, size)
            icon_img.save(iconset_dir / icon_name, "PNG")
            
            # Retina resolution (@2x) - except for 1024 which is already max
            if size <= 512:
                retina_size = size * 2
                retina_name = f"icon_{size}x{size}@2x.png"
                retina_img = create_app_icon(logo_path, retina_size)
                retina_img.save(iconset_dir / retina_name, "PNG")
        
        print(f"  Created iconset with {len(list(iconset_dir.glob('*.png')))} images")
        
        # Use iconutil to create .icns (macOS only)
        if sys.platform == "darwin":
            result = subprocess.run(
                ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_path)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"  Error running iconutil: {result.stderr}")
                return False
            
            print(f"  Created: {output_path}")
            
            # Clean up iconset directory
            shutil.rmtree(iconset_dir)
            return True
        else:
            print("  Note: iconutil only available on macOS")
            print(f"  Iconset created at: {iconset_dir}")
            print("  This directory is intentionally left for manual processing.")
            print("  Copy to macOS and run: iconutil -c icns icon.iconset")
            return True
            
    except Exception as e:
        print(f"  Error creating macOS icon: {e}")
        # Clean up on error
        if iconset_dir.exists():
            shutil.rmtree(iconset_dir)
        return False


def create_windows_ico(logo_path: Path, output_path: Path) -> bool:
    """
    Create Windows .ico file from logo.
    
    Creates icons with white rounded rectangle background and logo centered.
    Transparent corners ensure the rounded effect displays properly on Windows.
    
    Args:
        logo_path: Path to logo PNG image (with transparency)
        output_path: Path for output .ico file
        
    Returns:
        True if successful, False otherwise
    """
    print("Creating Windows .ico icon...")
    
    try:
        # Create icons at all required sizes
        icon_images = []
        for size in WINDOWS_ICON_SIZES:
            icon_img = create_app_icon(logo_path, size)
            icon_images.append(icon_img)
        
        # Save as .ico with all sizes
        # Largest size first for best quality selection by Windows
        icon_images_reversed = list(reversed(icon_images))
        icon_images_reversed[0].save(
            output_path,
            format="ICO",
            sizes=[(img.width, img.height) for img in icon_images_reversed],
            append_images=icon_images_reversed[1:]
        )
        
        print(f"  Created: {output_path}")
        print(f"  Included sizes: {WINDOWS_ICON_SIZES}")
        print(f"  Features: White rounded background, transparent corners")
        return True
        
    except Exception as e:
        print(f"  Error creating Windows icon: {e}")
        return False


def main():
    """Main entry point for icon generation."""
    print("=" * 50)
    print("BrainDock Icon Generator")
    print("=" * 50)
    print()
    
    # Verify logo exists
    if not LOGO_SOURCE.exists():
        print(f"Error: Logo not found at {LOGO_SOURCE}")
        sys.exit(1)
    
    logo_path = LOGO_SOURCE
    print(f"Using logo: {logo_path.name}")
    
    print(f"Source: {logo_path}")
    print(f"Output: {OUTPUT_DIR}")
    print()
    
    # Verify source image is valid and show info
    try:
        with Image.open(logo_path) as img:
            has_alpha = img.mode in ("RGBA", "LA", "PA")
            print(f"Source image: {img.size[0]}x{img.size[1]} {img.mode}")
            print(f"  Has transparency: {'Yes' if has_alpha else 'No'}")
            if not has_alpha:
                print("  Note: Logo will be composited onto white background")
            print()
    except Exception as e:
        print(f"Error: Cannot open source image: {e}")
        sys.exit(1)
    
    # Create output directory if needed
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    success = True
    
    # Create macOS icon
    icns_path = OUTPUT_DIR / "icon.icns"
    if not create_macos_icns(logo_path, icns_path):
        success = False
    print()
    
    # Create Windows icon
    ico_path = OUTPUT_DIR / "icon.ico"
    if not create_windows_ico(logo_path, ico_path):
        success = False
    print()
    
    # Summary
    print("=" * 50)
    if success:
        print("Icon generation complete!")
        print()
        print("Generated files:")
        if icns_path.exists():
            print(f"  macOS:   {icns_path}")
        if ico_path.exists():
            print(f"  Windows: {ico_path}")
        print()
        print("Icon features:")
        print("  - White rounded rectangle background")
        print("  - Transparent corners (for rounded effect)")
        print("  - Logo centered with padding")
    else:
        print("Icon generation completed with errors.")
        sys.exit(1)
    
    print("=" * 50)


if __name__ == "__main__":
    main()
