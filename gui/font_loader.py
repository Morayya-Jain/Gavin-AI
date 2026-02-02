"""
Font loader for BrainDock - registers bundled fonts at startup.

This module handles loading custom fonts (Inter and Lora) that are bundled
with the application, ensuring consistent typography across macOS and Windows.

Must be called BEFORE creating any tkinter windows.
"""
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Track whether fonts have been loaded
_fonts_loaded = False


def get_fonts_dir() -> Path:
    """
    Get the fonts directory, handling bundled app vs development.
    
    Returns:
        Path to the fonts directory.
    """
    if getattr(sys, 'frozen', False):
        # Running as bundled app (PyInstaller)
        base = Path(sys._MEIPASS)
    else:
        # Running in development
        base = Path(__file__).parent.parent
    return base / "assets" / "fonts"


def _load_fonts_macos(fonts_dir: Path) -> bool:
    """
    Load fonts on macOS using CoreText framework.
    
    Args:
        fonts_dir: Path to directory containing TTF files.
        
    Returns:
        True if fonts loaded successfully, False otherwise.
    """
    try:
        from ctypes import cdll, c_void_p, c_bool, c_char_p, c_int
        
        # Load CoreText and CoreFoundation frameworks
        ct = cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreText.framework/CoreText"
        )
        cf = cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        
        # Set up function signatures
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
            c_void_p, c_char_p, c_int, c_bool
        ]
        cf.CFURLCreateFromFileSystemRepresentation.restype = c_void_p
        
        ct.CTFontManagerRegisterFontsForURL.argtypes = [c_void_p, c_int, c_void_p]
        ct.CTFontManagerRegisterFontsForURL.restype = c_bool
        
        fonts_loaded = 0
        for font_file in fonts_dir.glob("*.ttf"):
            font_path = str(font_file).encode('utf-8')
            url = cf.CFURLCreateFromFileSystemRepresentation(
                None, font_path, len(font_path), False
            )
            if url:
                # 1 = kCTFontManagerScopeProcess (process-wide scope)
                result = ct.CTFontManagerRegisterFontsForURL(url, 1, None)
                if result:
                    fonts_loaded += 1
                    logger.debug(f"Loaded font: {font_file.name}")
                else:
                    logger.warning(f"Failed to register font: {font_file.name}")
        
        logger.info(f"Loaded {fonts_loaded} fonts on macOS")
        return fonts_loaded > 0
        
    except Exception as e:
        logger.warning(f"Failed to load fonts on macOS: {e}")
        return False


def _load_fonts_windows(fonts_dir: Path) -> bool:
    """
    Load fonts on Windows using GDI32.
    
    Args:
        fonts_dir: Path to directory containing TTF files.
        
    Returns:
        True if fonts loaded successfully, False otherwise.
    """
    try:
        from ctypes import windll
        
        # FR_PRIVATE: Font is available only to the calling process
        FR_PRIVATE = 0x10
        
        fonts_loaded = 0
        for font_file in fonts_dir.glob("*.ttf"):
            result = windll.gdi32.AddFontResourceExW(
                str(font_file), FR_PRIVATE, 0
            )
            if result > 0:
                fonts_loaded += 1
                logger.debug(f"Loaded font: {font_file.name}")
            else:
                logger.warning(f"Failed to register font: {font_file.name}")
        
        logger.info(f"Loaded {fonts_loaded} fonts on Windows")
        return fonts_loaded > 0
        
    except Exception as e:
        logger.warning(f"Failed to load fonts on Windows: {e}")
        return False


def load_bundled_fonts() -> bool:
    """
    Load bundled fonts into the system font registry.
    
    This function registers the bundled Inter and Lora fonts so they
    can be used by tkinter and CustomTkinter widgets.
    
    Returns:
        True if fonts loaded successfully, False otherwise.
    """
    global _fonts_loaded
    
    if _fonts_loaded:
        logger.debug("Fonts already loaded")
        return True
    
    fonts_dir = get_fonts_dir()
    
    if not fonts_dir.exists():
        # This is expected if custom fonts aren't bundled - use system fonts instead
        logger.debug(f"Fonts directory not found: {fonts_dir} - using system fonts")
        return False
    
    # Check if font files exist
    font_files = list(fonts_dir.glob("*.ttf"))
    if not font_files:
        logger.debug(f"No TTF files found in {fonts_dir} - using system fonts")
        return False
    
    logger.debug(f"Loading fonts from: {fonts_dir}")
    
    if sys.platform == "darwin":
        _fonts_loaded = _load_fonts_macos(fonts_dir)
    elif sys.platform == "win32":
        _fonts_loaded = _load_fonts_windows(fonts_dir)
    else:
        # Linux - fonts should be installed system-wide or use fontconfig
        logger.info("Linux detected - using system fonts")
        _fonts_loaded = False
    
    return _fonts_loaded


def get_font_sans() -> str:
    """
    Return the sans-serif font family name.
    
    Returns:
        'Helvetica' on macOS/Linux, 'Helvetica' with 'Arial' fallback on Windows.
        Windows tkinter will automatically fall back to Arial if Helvetica is unavailable.
    """
    # Helvetica is the primary font on all platforms
    # On Windows where Helvetica may not be installed, tkinter will use Arial as fallback
    return "Helvetica"


def get_font_serif() -> str:
    """
    Return the serif font family name.
    
    Returns:
        'Georgia' (available on both macOS and Windows).
    """
    return "Georgia"


# Font family names - using original system fonts for native appearance
# Bundled fonts (Inter/Lora) are available in assets/fonts/ if needed in future
# 
# Helvetica is preferred on all platforms. On Windows where Helvetica may not be
# installed, tkinter's font system will automatically substitute a similar font.
# We explicitly provide Arial as the fallback for Windows to ensure consistency.
FONT_SANS = "Helvetica"   # Primary sans-serif font
FONT_SERIF = "Georgia"    # Serif (available on both macOS and Windows)

# Fallback font names - Arial is the Windows equivalent of Helvetica
FONT_SANS_FALLBACK = "Arial" if sys.platform == "win32" else "Helvetica"
FONT_SERIF_FALLBACK = "Georgia"


def get_font_with_fallback(primary: str, fallback: str) -> str:
    """
    Get a font name with fallback support.
    
    On Windows, if the primary font (e.g., Helvetica) is not available,
    this returns the fallback font (e.g., Arial).
    
    Args:
        primary: Primary font name to try
        fallback: Fallback font name if primary unavailable
        
    Returns:
        Font name to use (primary if available, otherwise fallback)
    """
    if sys.platform != "win32":
        return primary
    
    # On Windows, check if the font is available using tkinter
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        
        # Create a temporary root if needed
        temp_root = None
        try:
            temp_root = tk._default_root
        except AttributeError:
            pass
        
        if temp_root is None:
            # Can't check fonts without a root window, return primary
            # tkinter will handle fallback automatically
            return primary
        
        available_fonts = tkfont.families()
        if primary in available_fonts:
            return primary
        elif fallback in available_fonts:
            return fallback
        else:
            return primary  # Let tkinter handle it
    except Exception:
        # If we can't check, return primary and let tkinter handle fallback
        return primary
