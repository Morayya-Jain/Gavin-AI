"""
BrainDock UI Components - CustomTkinter Edition

This module provides reusable UI components and a scaling system for the
BrainDock application, built on CustomTkinter for consistent cross-platform
appearance.
"""
import sys
import logging
from typing import Dict, Tuple, Optional, Callable
import customtkinter as ctk
from customtkinter import CTkFont

logger = logging.getLogger(__name__)


# --- Windows-Specific Work Area Detection ---

def _get_windows_work_area() -> Optional[Tuple[int, int, int, int]]:
    """
    Get the Windows work area (screen minus taskbar) using ctypes.
    
    Returns:
        Tuple of (left, top, width, height) or None if not on Windows/failed.
    """
    if sys.platform != 'win32':
        return None
    
    try:
        import ctypes
        from ctypes import wintypes
        
        # RECT structure for work area
        class RECT(ctypes.Structure):
            _fields_ = [
                ('left', wintypes.LONG),
                ('top', wintypes.LONG),
                ('right', wintypes.LONG),
                ('bottom', wintypes.LONG)
            ]
        
        # SPI_GETWORKAREA = 0x0030
        SPI_GETWORKAREA = 0x0030
        
        rect = RECT()
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        
        if result:
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            return (rect.left, rect.top, width, height)
        
    except Exception as e:
        logger.debug(f"Failed to get Windows work area: {e}")
    
    return None


def _get_windows_dpi_scale() -> float:
    """
    Get the Windows DPI scale factor for the primary monitor.
    
    Returns:
        DPI scale factor (1.0 = 100%, 1.25 = 125%, etc.) or 1.0 on failure.
    """
    if sys.platform != 'win32':
        return 1.0
    
    try:
        import ctypes
        
        # Try to get DPI for the desktop window (primary monitor)
        user32 = ctypes.windll.user32
        
        # GetDpiForSystem (Windows 10 1607+)
        try:
            dpi = user32.GetDpiForSystem()
            return dpi / 96.0  # 96 DPI = 100% scaling
        except AttributeError:
            pass
        
        # Fallback: GetDeviceCaps with LOGPIXELSX
        try:
            hdc = user32.GetDC(0)
            gdi32 = ctypes.windll.gdi32
            LOGPIXELSX = 88
            dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
            user32.ReleaseDC(0, hdc)
            return dpi / 96.0
        except Exception:
            pass
        
    except Exception as e:
        logger.debug(f"Failed to get Windows DPI scale: {e}")
    
    return 1.0

# Import font loader for bundled fonts
try:
    from gui.font_loader import (
        load_bundled_fonts, get_font_sans, get_font_serif,
        FONT_SANS, FONT_SERIF, FONT_SANS_FALLBACK, FONT_SERIF_FALLBACK
    )
except ImportError:
    # Fallback if font_loader not available
    def load_bundled_fonts() -> bool:
        return False
    def get_font_sans() -> str:
        return "Helvetica"
    def get_font_serif() -> str:
        return "Georgia"
    FONT_SANS = "Helvetica"
    FONT_SERIF = "Georgia"
    FONT_SANS_FALLBACK = "Helvetica"
    FONT_SERIF_FALLBACK = "Georgia"


# --- Scaling System ---

# Reference dimensions (design target - the original design resolution)
REFERENCE_WIDTH = 1500
REFERENCE_HEIGHT = 950

# Minimum window dimensions (larger minimum for readability)
MIN_WIDTH = 950
MIN_HEIGHT = 680

# Font scaling bounds (base_size, min_size, max_size)
FONT_BOUNDS = {
    "timer": (50, 35, 65),      # Base 50pt, min 35, max 65
    "stat": (23, 15, 29),       # Base 23pt, min 15, max 29
    "title": (24, 17, 32),      # Base 24pt, min 17, max 32
    "status": (19, 15, 25),     # Base 19pt, min 15, max 25
    "body": (15, 11, 19),       # Base 15pt, min 11, max 19
    "button": (13, 10, 16),     # Base 13pt, min 10, max 16
    "small": (13, 10, 17),      # Base 13pt, min 10, max 17
    "badge": (10, 8, 14),       # Base 10pt, min 8, max 14
    "caption": (12, 9, 16),     # Base 12pt, min 9, max 16
    "heading": (26, 18, 34),    # For payment screen (unchanged)
    "subheading": (20, 15, 26), # For payment screen (unchanged)
    "input": (16, 12, 20),      # For input fields (unchanged)
    "body_bold": (16, 12, 20),  # Bold body text (unchanged)
    "display": (34, 26, 44),    # Large display text (unchanged)
}

# Which font keys use serif (display) vs sans (interface)
SERIF_FONTS = {"timer", "title", "stat", "display", "heading", "subheading"}

# Which font keys are bold
BOLD_FONTS = {"timer", "title", "stat", "heading", "caption", "body_bold", "button", "badge"}


def _is_bundled() -> bool:
    """Check if running from a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


class ScalingManager:
    """
    Centralized scaling manager for responsive GUI elements.
    
    Handles screen detection, scale factor calculation, and provides
    utilities for scaling dimensions, fonts, and padding.
    
    Note: CustomTkinter handles DPI scaling automatically, so this class
    focuses on responsive layout scaling based on window/screen size.
    
    On Windows, this class accounts for:
    - Work area (excluding taskbar) for proper centering
    - DPI scaling for consistent element sizing
    """
    
    def __init__(self, root: ctk.CTk):
        """
        Initialize the scaling manager.
        
        Args:
            root: The root CustomTkinter window.
        """
        self.root = root
        self._current_scale = 1.0
        self._screen_width = 0
        self._screen_height = 0
        self._fonts: Dict[str, CTkFont] = {}
        
        # Windows-specific: work area (screen minus taskbar)
        self._work_area: Optional[Tuple[int, int, int, int]] = None  # (left, top, width, height)
        self._windows_dpi_scale = 1.0
        
        # Load bundled fonts at initialization
        load_bundled_fonts()
        
        # Detect screen size
        self._detect_screen_size()
    
    def _detect_screen_size(self):
        """
        Detect the current screen dimensions for window sizing.
        
        On Windows, also gets the work area (excluding taskbar) and DPI scale.
        On macOS, uses standard screen dimensions.
        """
        self.root.update_idletasks()
        self._screen_width = self.root.winfo_screenwidth()
        self._screen_height = self.root.winfo_screenheight()
        
        # Windows-specific: get work area and DPI scale
        if sys.platform == 'win32':
            self._work_area = _get_windows_work_area()
            self._windows_dpi_scale = _get_windows_dpi_scale()
            
            # If we got a valid work area, use it for more accurate sizing
            if self._work_area:
                _, _, work_width, work_height = self._work_area
                # Use work area dimensions if they're reasonable
                if work_width > 100 and work_height > 100:
                    logger.debug(
                        f"Windows work area: {work_width}x{work_height}, "
                        f"DPI scale: {self._windows_dpi_scale}"
                    )
    
    @property
    def screen_width(self) -> int:
        """Get the screen width."""
        return self._screen_width
    
    @property
    def screen_height(self) -> int:
        """Get the screen height."""
        return self._screen_height
    
    @property
    def current_scale(self) -> float:
        """Get the current scale factor."""
        return self._current_scale
    
    def get_initial_window_size(self) -> Tuple[int, int]:
        """
        Calculate the initial window size based on screen dimensions.
        
        On Windows, uses work area (excluding taskbar) for sizing.
        
        Returns:
            Tuple of (width, height) for the initial window size.
        """
        # Determine available screen space
        if sys.platform == 'win32' and self._work_area:
            _, _, avail_width, avail_height = self._work_area
        else:
            avail_width = self._screen_width
            avail_height = self._screen_height
        
        # Target 75% of available width, 80% of available height
        # But cap at reference dimensions for larger screens
        target_width = min(int(avail_width * 0.75), REFERENCE_WIDTH)
        target_height = min(int(avail_height * 0.8), REFERENCE_HEIGHT)
        
        # Ensure minimum size (but only if screen is large enough)
        target_width = max(target_width, MIN_WIDTH)
        target_height = max(target_height, MIN_HEIGHT)
        
        # Final safeguard: never exceed 95% of available space to prevent overflow
        max_width = int(avail_width * 0.95)
        max_height = int(avail_height * 0.95)
        target_width = min(target_width, max_width)
        target_height = min(target_height, max_height)
        
        return target_width, target_height
    
    def get_popup_centered_position(
        self, 
        popup_width: int, 
        popup_height: int,
        parent_x: int,
        parent_y: int, 
        parent_width: int, 
        parent_height: int
    ) -> Tuple[int, int]:
        """
        Calculate centered position for a popup relative to parent window.
        
        On Windows, ensures the popup stays within the work area bounds.
        
        Args:
            popup_width: Width of the popup.
            popup_height: Height of the popup.
            parent_x: Parent window X position.
            parent_y: Parent window Y position.
            parent_width: Parent window width.
            parent_height: Parent window height.
        
        Returns:
            Tuple of (x, y) position for the popup.
        """
        # Calculate position centered on parent
        x = parent_x + (parent_width - popup_width) // 2
        y = parent_y + (parent_height - popup_height) // 2
        
        # Windows-specific: ensure popup stays within work area
        if sys.platform == 'win32' and self._work_area:
            work_left, work_top, work_width, work_height = self._work_area
            
            # Clamp to work area bounds
            x = max(work_left, min(x, work_left + work_width - popup_width))
            y = max(work_top, min(y, work_top + work_height - popup_height))
        
        return x, y
    
    def get_centered_position(self, width: int, height: int) -> Tuple[int, int]:
        """
        Calculate the centered position for a window.
        
        On Windows, uses the work area (excluding taskbar) for accurate centering.
        On macOS, uses standard screen dimensions.
        
        Args:
            width: Window width.
            height: Window height.
        
        Returns:
            Tuple of (x, y) position to center the window.
        """
        if sys.platform == 'win32' and self._work_area:
            # Windows: center within work area (excluding taskbar)
            work_left, work_top, work_width, work_height = self._work_area
            x = work_left + (work_width - width) // 2
            y = work_top + (work_height - height) // 2
            
            # Ensure window stays within work area bounds
            x = max(work_left, min(x, work_left + work_width - width))
            y = max(work_top, min(y, work_top + work_height - height))
            return x, y
        else:
            # macOS/Linux: standard centering
            x = (self._screen_width - width) // 2
            y = (self._screen_height - height) // 2
            return x, y
    
    def calculate_scale(self, window_width: int, window_height: int) -> float:
        """
        Calculate the scale factor based on window dimensions.
        
        Args:
            window_width: Current window width.
            window_height: Current window height.
        
        Returns:
            Scale factor (1.0 = reference size).
        """
        width_scale = window_width / REFERENCE_WIDTH
        height_scale = window_height / REFERENCE_HEIGHT
        return min(width_scale, height_scale)
    
    def update_scale(self, window_width: int, window_height: int, threshold: float = 0.02) -> bool:
        """
        Update the current scale factor if it changed significantly.
        
        Args:
            window_width: Current window width.
            window_height: Current window height.
            threshold: Minimum scale change to trigger update (default 2%).
        
        Returns:
            True if scale changed significantly, False otherwise.
        """
        new_scale = self.calculate_scale(window_width, window_height)
        
        if abs(new_scale - self._current_scale) > threshold:
            self._current_scale = new_scale
            return True
        return False
    
    def set_scale(self, scale: float):
        """
        Directly set the current scale factor.
        
        Args:
            scale: The scale factor to set.
        """
        self._current_scale = scale
    
    def scale_dimension(self, base_value: int, min_value: Optional[int] = None) -> int:
        """
        Scale a dimension by the current scale factor.
        
        Args:
            base_value: The base dimension value.
            min_value: Optional minimum value (won't go below this).
        
        Returns:
            Scaled dimension value.
        """
        scaled = int(base_value * self._current_scale)
        if min_value is not None:
            return max(scaled, min_value)
        return scaled
    
    def scale_padding(self, base_padding: int) -> int:
        """
        Scale padding/margin by the current scale factor.
        
        Args:
            base_padding: The base padding value.
        
        Returns:
            Scaled padding value (minimum 2).
        """
        return max(2, int(base_padding * self._current_scale))
    
    def scale_font_size(self, font_key: str) -> int:
        """
        Get the scaled font size for a font key.
        
        Args:
            font_key: Key from FONT_BOUNDS (e.g., "timer", "title", "body").
        
        Returns:
            Scaled font size within bounds.
        """
        if font_key not in FONT_BOUNDS:
            font_key = "body"
        
        base_size, min_size, max_size = FONT_BOUNDS[font_key]
        scaled_size = int(base_size * self._current_scale)
        
        return max(min_size, min(scaled_size, max_size))
    
    def get_scaled_font(self, font_key: str) -> CTkFont:
        """
        Get a CTkFont object scaled appropriately.
        
        Args:
            font_key: Key from FONT_BOUNDS (e.g., "timer", "title", "body").
        
        Returns:
            CTkFont object with appropriate family, size, and weight.
        """
        size = self.scale_font_size(font_key)
        family = get_font_serif() if font_key in SERIF_FONTS else get_font_sans()
        weight = "bold" if font_key in BOLD_FONTS else "normal"
        
        return CTkFont(family=family, size=size, weight=weight)
    
    def get_popup_size(
        self, 
        base_width: int, 
        base_height: int, 
        use_window_scale: bool = True,
        min_width: Optional[int] = None,
        min_height: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Calculate popup size based on current window scale or screen dimensions.
        
        On Windows with high DPI scaling, reduces popup sizes to prevent
        elements appearing too large.
        
        Args:
            base_width: Base popup width.
            base_height: Base popup height.
            use_window_scale: If True, scale based on current window.
            min_width: Optional minimum width.
            min_height: Optional minimum height.
        
        Returns:
            Tuple of (width, height) for the popup.
        """
        if use_window_scale:
            popup_scale = max(self._current_scale, 0.6)
        else:
            popup_scale = min(
                self._screen_width / 1920,
                self._screen_height / 1080,
                1.0
            )
            popup_scale = max(popup_scale, 0.6)
        
        # Windows-specific: compensate for DPI scaling to prevent oversized popups
        # When Windows DPI is >100%, CustomTkinter scales everything up automatically
        # We reduce our base sizes proportionally to maintain consistent visual size
        if sys.platform == 'win32' and self._windows_dpi_scale > 1.0:
            # Reduce base sizes inversely proportional to DPI scale
            # e.g., 150% DPI -> multiply by ~0.75 to counteract the automatic scaling
            dpi_compensation = 1.0 / self._windows_dpi_scale
            # Apply a gentler compensation (don't fully counteract, keep some scaling)
            # This gives a balanced result - not too large, not too small
            gentle_compensation = 0.6 + (0.4 * dpi_compensation)
            popup_scale *= gentle_compensation
        
        width = int(base_width * popup_scale)
        height = int(base_height * popup_scale)
        
        if min_width is not None:
            width = max(width, min_width)
        if min_height is not None:
            height = max(height, min_height)
        
        return width, height
    
    def get_popup_fonts_scale(self) -> float:
        """
        Get the scale factor to use for popup fonts.
        
        On Windows with high DPI, reduces font scale to prevent oversized text.
        
        Returns:
            Scale factor for popup fonts (based on current window scale).
        """
        base_scale = max(self._current_scale, 0.7)
        
        # Windows-specific: reduce font scale when DPI scaling is active
        if sys.platform == 'win32' and self._windows_dpi_scale > 1.0:
            # Apply gentle compensation for DPI scaling
            dpi_compensation = 1.0 / self._windows_dpi_scale
            gentle_compensation = 0.6 + (0.4 * dpi_compensation)
            base_scale *= gentle_compensation
        
        return base_scale
    
    def get_windows_dpi_scale(self) -> float:
        """
        Get the Windows DPI scale factor.
        
        Returns:
            DPI scale factor (1.0 on non-Windows platforms).
        """
        return self._windows_dpi_scale if sys.platform == 'win32' else 1.0


def get_screen_scale_factor(root: ctk.CTk) -> float:
    """
    Get a scale factor based on screen size (utility function).
    
    Args:
        root: CustomTkinter root window.
    
    Returns:
        Scale factor relative to 1920x1080.
    """
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    
    scale = min(screen_width / 1920, screen_height / 1080, 1.0)
    return max(scale, 0.6)


# --- Design System Constants (Seraphic Focus) ---
COLORS = {
    "bg": "#F9F8F4",           # Warm Cream
    "bg_primary": "#F9F8F4",   # Alias for bg
    "surface": "#FFFFFF",       # White Cards
    "text_primary": "#1C1C1E",  # Sharp Black
    "text_secondary": "#8E8E93", # System Gray
    "accent": "#2C3E50",        # Dark Blue/Grey
    "button_bg": "#1C1C1E",     # Black for primary actions
    "button_bg_hover": "#333333", # Dark grey for hover
    "button_text": "#FFFFFF",
    "border": "#E5E5EA",
    "shadow_light": "#E5E5EA", 
    "shadow_lighter": "#F2F2F7",
    "success": "#34C759",       # Subtle green
    "input_bg": "#F2F0EB",      # Light beige for inputs
    "link": "#2C3E50",          # Link color
    "status_gadget": "#EF4444", # Red for errors
    "button_start": "#34C759",  # Green for success/start
    "button_start_hover": "#2DB84C",
    "transparent": "transparent",
}

# Font tuples for backward compatibility
# These use bundled fonts (Inter/Lora) when available
def _get_font_tuple(family_type: str, size: int, weight: str = "normal") -> tuple:
    """Get a font tuple with the appropriate family."""
    family = get_font_serif() if family_type == "serif" else get_font_sans()
    if weight == "bold":
        return (family, size, "bold")
    return (family, size)


# FONTS dict for backward compatibility with existing code
FONTS = {
    "display": (get_font_serif(), 34, "bold"),
    "heading": (get_font_serif(), 26, "bold"),
    "subheading": (get_font_serif(), 20),
    "body": (get_font_sans(), 16),
    "body_bold": (get_font_sans(), 16, "bold"),
    "caption": (get_font_sans(), 13, "bold"),
    "small": (get_font_sans(), 14),
    "input": (get_font_sans(), 16),
}


def get_ctk_font(font_key: str, scale: float = 1.0) -> CTkFont:
    """
    Get a CTkFont object for the given font key.
    
    Args:
        font_key: Key from FONT_BOUNDS.
        scale: Scale factor to apply (default 1.0).
    
    Returns:
        CTkFont object.
    """
    if font_key not in FONT_BOUNDS:
        font_key = "body"
    
    base_size, min_size, max_size = FONT_BOUNDS[font_key]
    size = int(max(min_size, min(max_size, base_size * scale)))
    family = get_font_serif() if font_key in SERIF_FONTS else get_font_sans()
    weight = "bold" if font_key in BOLD_FONTS else "normal"
    
    return CTkFont(family=family, size=size, weight=weight)


# --- CustomTkinter Widget Wrappers ---

class RoundedButton(ctk.CTkButton):
    """
    A rounded button using CustomTkinter's CTkButton.
    
    This is a drop-in replacement for the old Canvas-based RoundedButton.
    """
    
    def __init__(
        self, 
        parent, 
        text: str,
        command: Optional[Callable] = None,
        width: int = 200,
        height: int = 50,
        radius: int = 25,
        bg_color: str = COLORS["button_bg"],
        hover_color: Optional[str] = None,
        text_color: str = COLORS["button_text"],
        font_type: str = "body_bold",
        font: Optional[CTkFont] = None,
        canvas_bg: Optional[str] = None,  # Ignored, for compatibility
        **kwargs
    ):
        """
        Initialize a rounded button.
        
        Args:
            parent: Parent widget.
            text: Button text.
            command: Callback function when clicked.
            width: Button width.
            height: Button height.
            radius: Corner radius.
            bg_color: Background color.
            hover_color: Hover color (defaults to bg_color).
            text_color: Text color.
            font_type: Font key from FONTS.
            font: Optional CTkFont to use directly.
            canvas_bg: Ignored (for backward compatibility).
        """
        # Get font from font_type if not provided
        if font is None:
            font = get_ctk_font(font_type)
        
        super().__init__(
            parent,
            text=text,
            command=command,
            width=width,
            height=height,
            corner_radius=radius,
            fg_color=bg_color,
            hover_color=hover_color or bg_color,
            text_color=text_color,
            font=font,
            **kwargs
        )
        
        # Store original values for compatibility
        self._original_bg = bg_color
        self.bg_color = bg_color
        self.hover_color = hover_color or bg_color
        self.text_color = text_color
        self.text_str = text
        self.font_type = font_type
    
    def draw(self, offset: int = 0):
        """Compatibility method - no-op for CTkButton."""
        pass
    
    def configure(self, **kwargs):
        """Configure button properties with backward compatibility."""
        # Map old parameter names to CTk parameter names
        if "bg_color" in kwargs:
            kwargs["fg_color"] = kwargs.pop("bg_color")
            self.bg_color = kwargs["fg_color"]
            self._original_bg = kwargs["fg_color"]
        if "text_color" in kwargs:
            # CTkButton uses text_color directly
            self.text_color = kwargs["text_color"]
        if "text" in kwargs:
            self.text_str = kwargs["text"]
        
        super().configure(**kwargs)


class Card(ctk.CTkFrame):
    """
    A card container using CustomTkinter's CTkFrame.
    
    This is a drop-in replacement for the old Canvas-based Card.
    """
    
    def __init__(
        self,
        parent,
        width: int = 300,
        height: int = 150,
        radius: int = 20,
        bg_color: str = COLORS["surface"],
        text: str = "",
        text_color: Optional[str] = None,
        font: Optional[CTkFont] = None,
        **kwargs
    ):
        """
        Initialize a card.
        
        Args:
            parent: Parent widget.
            width: Card width.
            height: Card height.
            radius: Corner radius.
            bg_color: Background color.
            text: Optional text to display (for stat cards).
            text_color: Text color.
            font: Font for text.
        """
        super().__init__(
            parent,
            width=width,
            height=height,
            corner_radius=radius,
            fg_color=bg_color,
            **kwargs
        )
        
        self.radius = radius
        self.bg_color = bg_color
        self.text = text
        self.text_color = text_color or COLORS["text_primary"]
        self.font = font
        
        # Add text label if text provided
        if text:
            self._text_label = ctk.CTkLabel(
                self,
                text=text,
                text_color=self.text_color,
                font=font,
                fg_color="transparent"
            )
            self._text_label.place(relx=0.5, rely=0.5, anchor="center")
    
    def draw(self):
        """Compatibility method - no-op for CTkFrame."""
        pass


class StyledEntry(ctk.CTkFrame):
    """
    A styled entry field with placeholder and error state support.
    
    This uses CTkEntry with additional error/success feedback.
    """
    
    def __init__(
        self,
        parent,
        placeholder: str = "",
        width: int = 200,
        height: int = 50,
        **kwargs
    ):
        """
        Initialize a styled entry.
        
        Args:
            parent: Parent widget.
            placeholder: Placeholder text.
            width: Entry width.
            height: Entry height.
        """
        super().__init__(parent, fg_color="transparent", **kwargs)
        
        self.placeholder = placeholder
        self.command = None
        self._has_feedback = False
        self._persistent_message = False  # If True, message won't be cleared by key press
        
        # Main entry widget
        self.entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            width=width,
            height=height,
            corner_radius=12,
            fg_color=COLORS["input_bg"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_secondary"],
            border_color=COLORS["input_bg"],
            border_width=2,
            font=get_ctk_font("input")
        )
        self.entry.pack(fill="x")
        
        # Error/success label - internal pady adds space for descenders
        self.error_label = ctk.CTkLabel(
            self,
            text=" ",
            text_color=COLORS["status_gadget"],
            font=get_ctk_font("small"),
            anchor="w",
            justify="left",
            pady=6
        )
        self.error_label.pack(fill="x", pady=(4, 0))
        
        # Bind configure event to update wraplength dynamically
        self.error_label.bind("<Configure>", self._update_wraplength)
        
        # Bind events
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<Key>", self._on_key_press)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
    
    def show_error(self, message: str):
        """Show an error message with red border."""
        self.error_label.configure(text=message, text_color=COLORS["status_gadget"])
        self.entry.configure(border_color=COLORS["status_gadget"])
        self._has_feedback = True
        self._persistent_message = False  # Errors can be cleared
    
    def show_success(self, message: str):
        """Show a success message with green border."""
        self.error_label.configure(text=message, text_color=COLORS["success"])
        self.entry.configure(border_color=COLORS["success"])
        self._has_feedback = True
        self._persistent_message = False  # Success can be cleared
    
    def show_info(self, message: str, persistent: bool = False):
        """
        Show info message without changing border color.
        
        Args:
            message: The message to display.
            persistent: If True, message won't be cleared by key presses.
        """
        self.error_label.configure(text=message, text_color=COLORS["text_secondary"])
        self._has_feedback = True
        self._persistent_message = persistent
    
    def clear_error(self, force: bool = False):
        """
        Clear error state.
        
        Args:
            force: If True, clears even persistent messages.
        """
        if self._persistent_message and not force:
            return  # Don't clear persistent messages
        self.error_label.configure(text=" ")
        # Check if entry has focus by comparing with the window's focus widget
        try:
            focused_widget = self.winfo_toplevel().focus_get()
            has_focus = (focused_widget == self.entry) or (focused_widget == self.entry._entry if hasattr(self.entry, '_entry') else False)
        except Exception:
            has_focus = False
        self.entry.configure(border_color=COLORS["accent"] if has_focus else COLORS["input_bg"])
        self._has_feedback = False
        self._persistent_message = False
    
    def _update_wraplength(self, event=None):
        """Update the wraplength of error_label to match the widget width."""
        # Get the actual width of the label, with some padding
        width = self.error_label.winfo_width()
        if width > 1:  # Only update if we have a valid width
            # Leave some margin to prevent edge clipping
            self.error_label.configure(wraplength=max(100, width - 10))
    
    def _on_focus_in(self, event):
        """Handle focus in."""
        self.entry.configure(border_color=COLORS["accent"])
    
    def _on_focus_out(self, event):
        """Handle focus out."""
        if not self._has_feedback:
            self.entry.configure(border_color=COLORS["input_bg"])
    
    def _on_key_press(self, event):
        """Handle key press - clear error."""
        self.clear_error()
    
    def _on_return(self, event):
        """Handle return key."""
        if self.command:
            self.command()
    
    def get(self) -> str:
        """Get the entry value."""
        return self.entry.get()
    
    def bind_return(self, command: Callable):
        """Bind a command to the return key."""
        self.command = command
    
    def delete(self, first, last=None):
        """Delete text from entry."""
        self.entry.delete(first, last)
    
    def insert(self, index, string: str):
        """Insert text into entry."""
        self.entry.insert(index, string)
    
    def focus_set(self):
        """Set focus to the entry."""
        self.entry.focus_set()


# Backward compatibility aliases
normalize_tk_scaling = lambda root: None  # No-op, CTk handles this


# --- Natural Scroll System ---

import time as time_module
import weakref
from collections import deque


class NaturalScroller:
    """
    Cross-platform natural scrolling with physics-based momentum.
    
    Provides smooth, finger-following scroll behavior that works consistently
    across macOS and Windows, with trackpad, mouse wheel, and scrollbar.
    
    Uses weak references to prevent memory leaks and automatically cleans up
    bindings when the window is destroyed.
    """
    
    # Physics constants (tuned for natural feel)
    BASE_SENSITIVITY = 0.0005  # Base finger-to-content ratio
    MIN_VELOCITY = 0.0002      # Threshold to stop momentum
    TARGET_FRAME_INTERVAL = 8  # Target ~120fps (ms), will adapt if device can't keep up
    MAX_FRAME_INTERVAL = 16    # Fallback to ~60fps for slower devices
    VELOCITY_SAMPLES = 5       # Number of samples for velocity averaging
    INERTIA_DELAY = 50         # Delay before starting inertia (ms)
    
    # Friction values for different frame rates (to maintain consistent feel)
    # Higher FPS needs higher friction per frame to achieve same momentum duration
    FRICTION_120FPS = (0.96, 0.99)  # (base, max) for 120fps
    FRICTION_60FPS = (0.92, 0.98)   # (base, max) for 60fps
    
    # Scroll delta normalization (consistent across platforms)
    # Both platforms use same base multiplier for consistent UX
    SCROLL_MULTIPLIER = 15  # Units per scroll notch
    
    def __init__(self, scrollable_frame: ctk.CTkScrollableFrame, window):
        """
        Initialize the natural scroller.
        
        Args:
            scrollable_frame: The CTkScrollableFrame to add natural scrolling to.
            window: The parent window (for scheduling animations).
        """
        # Use weak references to prevent memory leaks
        self._scrollable_frame_ref = weakref.ref(scrollable_frame)
        self._window_ref = weakref.ref(window, self._on_window_collected)
        self._destroyed = False
        
        # Scroll state
        self._velocity = 0.0
        self._last_time = 0.0
        self._animating = False
        self._target_pos = None
        self._current_pos = None
        
        # Adaptive frame rate tracking
        self._frame_interval = self.TARGET_FRAME_INTERVAL
        self._last_frame_time = 0.0
        self._slow_frame_count = 0
        self._base_friction, self._max_friction = self.FRICTION_120FPS
        
        # Velocity tracking with weighted moving average
        self._velocity_samples: deque = deque(maxlen=self.VELOCITY_SAMPLES)
        self._weights = [1, 2, 3, 4, 5]  # Recent samples weighted more heavily
        
        # Store bound function IDs for cleanup
        self._bound_events = []
        
        # Bind scroll events
        self._bind_scroll_events()
        
        # Track window destruction
        window.bind("<Destroy>", self._on_destroy, add="+")
    
    @property
    def scrollable_frame(self):
        """Get scrollable frame or None if garbage collected."""
        return self._scrollable_frame_ref()
    
    @property
    def window(self):
        """Get window or None if garbage collected."""
        return self._window_ref()
    
    def _on_window_collected(self, ref):
        """Called when window is garbage collected - mark as destroyed."""
        self._destroyed = True
        self._animating = False
    
    def _on_destroy(self, event):
        """Handle window destruction to prevent errors."""
        window = self.window
        if window is not None and event.widget == window:
            self._destroyed = True
            self._animating = False
            self.unbind_scroll_events()
    
    def _bind_scroll_events(self):
        """Bind all scroll events for cross-platform support."""
        window = self.window
        if window is None:
            return
        
        # macOS Tk 9+ touchpad scroll
        window.bind_all("<TouchpadScroll>", self._on_scroll)
        # macOS/Windows mouse wheel
        window.bind_all("<MouseWheel>", self._on_scroll)
        # Linux scroll buttons (Button-4 = up, Button-5 = down)
        window.bind_all("<Button-4>", self._on_linux_scroll_up)
        window.bind_all("<Button-5>", self._on_linux_scroll_down)
        
        # Track bound events for cleanup
        self._bound_events = [
            "<TouchpadScroll>",
            "<MouseWheel>",
            "<Button-4>",
            "<Button-5>"
        ]
    
    def unbind_scroll_events(self):
        """Unbind all scroll events (call when closing window)."""
        window = self.window
        if window is None:
            self._bound_events = []
            return
        
        for event in self._bound_events:
            try:
                window.unbind_all(event)
            except Exception:
                pass  # Widget may already be destroyed
        
        self._bound_events = []
        self._destroyed = True
        self._animating = False
    
    def _normalize_delta(self, event) -> float:
        """
        Normalize scroll delta across platforms and devices.
        
        Uses consistent normalization for both Windows and macOS to ensure
        identical scroll behavior across platforms.
        
        Args:
            event: The scroll event.
        
        Returns:
            Normalized delta value (positive = scroll down, negative = scroll up).
        """
        if not hasattr(event, 'delta'):
            return 0.0
        
        delta = event.delta
        
        if sys.platform == 'win32':
            # Windows: delta is typically 120 per notch
            # Normalize to consistent scroll amount
            return -delta / 120 * self.SCROLL_MULTIPLIER
        else:
            # macOS: handle signed 16-bit delta for touchpad
            # Using same multiplier as Windows for consistent UX
            delta_y = delta & 0xFFFF
            if delta_y > 32767:
                delta_y -= 65536
            # Scale macOS delta to match Windows behavior
            # macOS typically gives smaller deltas, so we normalize differently
            return delta_y * (self.SCROLL_MULTIPLIER / 15)
    
    def _get_adaptive_sensitivity(self, delta: float) -> float:
        """
        Calculate adaptive sensitivity based on scroll speed.
        
        Fast scrolls get slightly lower sensitivity (more control).
        Slow precise scrolls get slightly higher sensitivity (better tracking).
        
        Args:
            delta: The scroll delta.
        
        Returns:
            Adjusted sensitivity multiplier.
        """
        speed_factor = min(1.0, abs(delta) / 100)
        adaptive_factor = 1.0 - (0.12 * speed_factor)
        return self.BASE_SENSITIVITY * adaptive_factor
    
    def _get_adaptive_friction(self, velocity: float) -> float:
        """
        Calculate adaptive friction based on current velocity and frame rate.
        
        Faster scrolls coast longer (higher friction = less deceleration).
        Slower scrolls stop quicker (lower friction = more deceleration).
        Friction values automatically adjust based on detected frame rate.
        
        Args:
            velocity: Current scroll velocity.
        
        Returns:
            Friction factor adjusted for current frame rate.
        """
        velocity_factor = min(1.0, abs(velocity) / 0.01)
        return self._base_friction + ((self._max_friction - self._base_friction) * velocity_factor)
    
    def _calculate_weighted_velocity(self) -> float:
        """
        Calculate velocity using weighted moving average of recent samples.
        
        Returns:
            Weighted average velocity.
        """
        if not self._velocity_samples:
            return 0.0
        
        samples = list(self._velocity_samples)
        weights = self._weights[:len(samples)]
        
        weighted_sum = sum(s * w for s, w in zip(samples, weights))
        weight_total = sum(weights)
        
        return weighted_sum / weight_total if weight_total > 0 else 0.0
    
    def _on_scroll(self, event):
        """Handle scroll events from trackpad or mouse wheel."""
        if self._destroyed:
            return
        
        scrollable_frame = self.scrollable_frame
        window = self.window
        if scrollable_frame is None or window is None:
            return
        
        try:
            delta = self._normalize_delta(event)
            
            if abs(delta) < 1:
                return
            
            current_time = time_module.time()
            time_delta = current_time - self._last_time
            
            # Stop any ongoing momentum animation
            self._animating = False
            
            # Get canvas and current position
            canvas = scrollable_frame._parent_canvas
            current = canvas.yview()
            visible = current[1] - current[0]
            
            # Calculate scroll amount with adaptive sensitivity
            sensitivity = self._get_adaptive_sensitivity(delta)
            scroll_amount = -delta * sensitivity
            
            # Calculate new position with bounds
            new_pos = current[0] + scroll_amount
            new_pos = max(0.0, min(1.0 - visible, new_pos))
            
            # Apply scroll immediately (direct finger tracking)
            canvas.yview_moveto(new_pos)
            
            # Track velocity for momentum
            if time_delta > 0 and time_delta < 0.15:
                self._velocity_samples.append(scroll_amount)
            else:
                self._velocity_samples.clear()
                self._velocity_samples.append(scroll_amount)
            
            self._last_time = current_time
            
            # Schedule inertia check after brief delay
            window.after(self.INERTIA_DELAY, self._start_inertia)
            
        except Exception:
            pass  # Silently handle any errors
    
    def _on_linux_scroll_up(self, event):
        """Handle Linux scroll up (Button-4)."""
        if self._destroyed:
            return
        self._apply_discrete_scroll(-3)
    
    def _on_linux_scroll_down(self, event):
        """Handle Linux scroll down (Button-5)."""
        if self._destroyed:
            return
        self._apply_discrete_scroll(3)
    
    def _apply_discrete_scroll(self, units: int):
        """
        Apply discrete scroll (for Linux or line-based scrolling).
        
        Args:
            units: Number of units to scroll (positive = down).
        """
        scrollable_frame = self.scrollable_frame
        if scrollable_frame is None:
            return
        
        try:
            canvas = scrollable_frame._parent_canvas
            current = canvas.yview()
            visible = current[1] - current[0]
            
            scroll_amount = units * self.BASE_SENSITIVITY * 20
            new_pos = current[0] + scroll_amount
            new_pos = max(0.0, min(1.0 - visible, new_pos))
            
            canvas.yview_moveto(new_pos)
        except Exception:
            pass
    
    def _start_inertia(self):
        """Start momentum animation if finger has lifted."""
        if self._destroyed:
            return
        
        window = self.window
        if window is None:
            return
        
        # Only start if no recent input
        if time_module.time() - self._last_time > 0.04:
            velocity = self._calculate_weighted_velocity()
            if abs(velocity) >= self.MIN_VELOCITY and not self._animating:
                self._velocity = velocity
                self._animating = True
                self._last_frame_time = time_module.time()
                self._slow_frame_count = 0
                self._apply_inertia()
    
    def _adapt_frame_rate(self, actual_frame_time_ms: float):
        """
        Adapt frame rate if device can't keep up with target FPS.
        
        Args:
            actual_frame_time_ms: How long the last frame actually took (ms).
        """
        # If frames are consistently taking longer than target, fall back to 60fps
        if actual_frame_time_ms > self._frame_interval * 1.5:
            self._slow_frame_count += 1
            if self._slow_frame_count >= 3:
                # Switch to 60fps mode
                self._frame_interval = self.MAX_FRAME_INTERVAL
                self._base_friction, self._max_friction = self.FRICTION_60FPS
        else:
            # Reset slow frame counter if we're keeping up
            self._slow_frame_count = max(0, self._slow_frame_count - 1)
    
    def _apply_inertia(self):
        """Apply momentum animation frame with adaptive frame rate."""
        if self._destroyed or not self._animating:
            return
        
        scrollable_frame = self.scrollable_frame
        window = self.window
        if scrollable_frame is None or window is None:
            self._animating = False
            return
        
        current_frame_time = time_module.time()
        
        # Stop if velocity too low
        if abs(self._velocity) < self.MIN_VELOCITY:
            self._velocity = 0.0
            self._animating = False
            return
        
        # Stop if new input detected
        if current_frame_time - self._last_time < 0.04:
            self._animating = False
            return
        
        try:
            # Measure actual frame time and adapt if needed
            if self._last_frame_time > 0:
                actual_frame_ms = (current_frame_time - self._last_frame_time) * 1000
                self._adapt_frame_rate(actual_frame_ms)
            self._last_frame_time = current_frame_time
            
            canvas = scrollable_frame._parent_canvas
            current = canvas.yview()
            visible = current[1] - current[0]
            
            # Stop at boundaries
            if (self._velocity > 0 and current[1] >= 1.0) or \
               (self._velocity < 0 and current[0] <= 0.0):
                self._velocity = 0.0
                self._animating = False
                return
            
            # Apply velocity
            new_pos = current[0] + self._velocity
            new_pos = max(0.0, min(1.0 - visible, new_pos))
            canvas.yview_moveto(new_pos)
            
            # Apply adaptive friction (adjusted for current frame rate)
            friction = self._get_adaptive_friction(self._velocity)
            self._velocity *= friction
            
            # Schedule next frame at current (possibly adapted) interval
            window.after(self._frame_interval, self._apply_inertia)
            
        except Exception:
            self._animating = False


def setup_natural_scroll(scrollable_frame: ctk.CTkScrollableFrame, window) -> NaturalScroller:
    """
    Convenience function to set up natural scrolling on a CTkScrollableFrame.
    
    Args:
        scrollable_frame: The scrollable frame to enhance.
        window: The parent window.
    
    Returns:
        NaturalScroller instance (keep reference to prevent garbage collection).
    """
    return NaturalScroller(scrollable_frame, window)


# --- Windows-Compatible Scrollable Frame ---

def _is_windows_bundled() -> bool:
    """Check if running as a PyInstaller bundle on Windows."""
    return (
        sys.platform == 'win32' and 
        getattr(sys, 'frozen', False) and 
        hasattr(sys, '_MEIPASS')
    )


class WindowsCompatibleScrollableFrame(ctk.CTkFrame):
    """
    A scrollable frame that works reliably on Windows bundled apps.
    
    On Windows bundled apps, CTkScrollableFrame has rendering issues where
    content doesn't display. This class uses a plain tkinter Canvas with
    Scrollbar as a fallback on Windows, while using CTkScrollableFrame
    on macOS/Linux for better appearance.
    
    Usage is similar to CTkScrollableFrame - add widgets directly to this frame.
    """
    
    def __init__(
        self,
        parent,
        fg_color: str = COLORS["bg_primary"],
        scrollbar_button_color: str = COLORS["text_secondary"],
        scrollbar_button_hover_color: str = COLORS["accent"],
        **kwargs
    ):
        """
        Initialize the scrollable frame.
        
        Args:
            parent: Parent widget.
            fg_color: Background color.
            scrollbar_button_color: Scrollbar thumb color.
            scrollbar_button_hover_color: Scrollbar thumb hover color.
        """
        super().__init__(parent, fg_color=fg_color, **kwargs)
        
        self._fg_color = fg_color
        self._use_fallback = _is_windows_bundled()
        
        if self._use_fallback:
            # Windows bundled app: use plain tkinter Canvas + Scrollbar
            self._setup_tk_scrollable(fg_color)
        else:
            # macOS/Linux or non-bundled: use CTkScrollableFrame internally
            self._setup_ctk_scrollable(fg_color, scrollbar_button_color, scrollbar_button_hover_color)
    
    def _setup_tk_scrollable(self, bg_color: str):
        """Set up plain tkinter Canvas with Scrollbar (Windows fallback)."""
        import tkinter as tk
        
        # Create canvas and scrollbar
        self._canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        
        # Create inner frame for content
        self._inner_frame = ctk.CTkFrame(self._canvas, fg_color=bg_color)
        
        # Create window in canvas for the frame
        self._canvas_window = self._canvas.create_window((0, 0), window=self._inner_frame, anchor="nw")
        
        # Configure scrollbar
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        
        # Pack scrollbar and canvas
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        
        # Bind events for scrolling and resizing
        self._inner_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Bind mousewheel scrolling
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        # Store reference to content frame for widget placement
        self._content_frame = self._inner_frame
    
    def _setup_ctk_scrollable(self, bg_color: str, scrollbar_color: str, scrollbar_hover: str):
        """Set up CTkScrollableFrame (macOS/Linux)."""
        self._scrollable = ctk.CTkScrollableFrame(
            self,
            fg_color=bg_color,
            scrollbar_button_color=scrollbar_color,
            scrollbar_button_hover_color=scrollbar_hover
        )
        self._scrollable.pack(fill="both", expand=True)
        
        # Content frame is the scrollable frame itself
        self._content_frame = self._scrollable
        self._canvas = None
    
    def _on_frame_configure(self, event):
        """Update scroll region when inner frame size changes."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        """Resize inner frame width to match canvas."""
        self._canvas.itemconfig(self._canvas_window, width=event.width)
    
    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling."""
        if self._canvas:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def get_content_frame(self) -> ctk.CTkFrame:
        """
        Get the frame where content should be added.
        
        Returns:
            The content frame (CTkFrame) to add widgets to.
        """
        return self._content_frame
    
    def pack_widget(self, widget_class, **kwargs):
        """
        Create and pack a widget into the content frame.
        
        This is a convenience method that handles parent assignment automatically.
        
        Args:
            widget_class: The widget class to instantiate.
            **kwargs: Arguments passed to widget constructor and pack().
        
        Returns:
            The created widget.
        """
        # Separate pack kwargs from widget kwargs
        pack_kwargs = {}
        widget_kwargs = {}
        pack_keys = {'side', 'fill', 'expand', 'padx', 'pady', 'anchor', 'ipadx', 'ipady', 'before', 'after'}
        
        for key, value in kwargs.items():
            if key in pack_keys:
                pack_kwargs[key] = value
            else:
                widget_kwargs[key] = value
        
        # Create widget with content frame as parent
        widget = widget_class(self._content_frame, **widget_kwargs)
        widget.pack(**pack_kwargs)
        
        return widget


def create_scrollable_frame(
    parent,
    fg_color: str = COLORS["bg_primary"],
    scrollbar_button_color: str = COLORS["text_secondary"],
    scrollbar_button_hover_color: str = COLORS["accent"],
    **kwargs
) -> Tuple[ctk.CTkFrame, ctk.CTkFrame]:
    """
    Create a scrollable frame that works on both Windows and macOS.
    
    On Windows bundled apps, this uses a plain tkinter Canvas fallback.
    On macOS/Linux, it uses CTkScrollableFrame with natural scrolling.
    
    Args:
        parent: Parent widget.
        fg_color: Background color.
        scrollbar_button_color: Scrollbar thumb color.
        scrollbar_button_hover_color: Scrollbar thumb hover color.
    
    Returns:
        Tuple of (outer_frame, content_frame) - add widgets to content_frame.
    """
    frame = WindowsCompatibleScrollableFrame(
        parent,
        fg_color=fg_color,
        scrollbar_button_color=scrollbar_button_color,
        scrollbar_button_hover_color=scrollbar_button_hover_color,
        **kwargs
    )
    return frame, frame.get_content_frame()
