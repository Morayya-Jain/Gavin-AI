"""
BrainDock - Desktop GUI Application

A minimal tkinter GUI that wraps the existing detection code,
providing a user-friendly interface for focus session tracking.
"""

import tkinter as tk
from tkinter import messagebox, font as tkfont
import threading
import time
import logging
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

# PIL for logo image support
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from camera.capture import CameraCapture
from camera import get_event_type, create_vision_detector
from tracking.session import Session
from tracking.analytics import compute_statistics, get_focus_percentage
from tracking.usage_limiter import get_usage_limiter, UsageLimiter
from tracking.daily_stats import get_daily_stats_tracker, DailyStatsTracker
from reporting.pdf_report import generate_report
from instance_lock import check_single_instance, get_existing_pid
from screen.window_detector import WindowDetector, get_screen_state, get_screen_state_with_ai_fallback
from screen.blocklist import Blocklist, BlocklistManager, PRESET_CATEGORIES, QUICK_SITES

logger = logging.getLogger(__name__)


# --- macOS Camera Permission Check ---
def check_macos_camera_permission() -> str:
    """
    Check macOS camera authorization status.

    Returns:
        One of: "authorized", "denied", "not_determined", "restricted", "unknown"
    """
    if sys.platform != "darwin":
        return "authorized"  # Non-macOS: assume authorized, let normal flow handle

    try:
        import objc

        # Load AVFoundation framework using objc
        objc.loadBundle(
            'AVFoundation',
            bundle_path='/System/Library/Frameworks/AVFoundation.framework',
            module_globals=globals()
        )

        # Get AVCaptureDevice class from the loaded framework
        AVCaptureDevice = objc.lookUpClass('AVCaptureDevice')

        # AVMediaTypeVideo constant (FourCC code for video)
        AVMediaTypeVideo = "vide"

        # Authorization status values:
        # 0 = AVAuthorizationStatusNotDetermined
        # 1 = AVAuthorizationStatusRestricted
        # 2 = AVAuthorizationStatusDenied
        # 3 = AVAuthorizationStatusAuthorized
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo)

        status_map = {
            0: "not_determined",
            1: "restricted",
            2: "denied",
            3: "authorized"
        }
        return status_map.get(status, "unknown")

    except ImportError:
        logger.debug("PyObjC not available, cannot check camera permission status")
        return "unknown"
    except Exception as e:
        logger.debug(f"Error checking camera permission: {e}")
        return "unknown"


def open_macos_camera_settings():
    """Open macOS System Settings to Privacy & Security > Camera."""
    if sys.platform == "darwin":
        try:
            # macOS Ventura and later use this URL scheme
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"],
                check=True
            )
        except Exception as e:
            logger.error(f"Failed to open System Settings: {e}")
            # Fallback: open System Settings main page
            try:
                subprocess.run(["open", "-a", "System Settings"], check=True)
            except Exception:
                subprocess.run(["open", "-a", "System Preferences"], check=True)


def open_macos_accessibility_settings():
    """Open macOS System Settings to Privacy & Security > Accessibility."""
    if sys.platform == "darwin":
        try:
            # macOS Ventura and later use this URL scheme
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                check=True
            )
        except Exception as e:
            logger.error(f"Failed to open System Settings: {e}")
            # Fallback: open System Settings main page
            try:
                subprocess.run(["open", "-a", "System Settings"], check=True)
            except Exception:
                subprocess.run(["open", "-a", "System Preferences"], check=True)


def check_macos_accessibility_permission() -> bool:
    """
    Check if the app has permission for screen monitoring on macOS.
    
    Screen monitoring needs AppleScript access to System Events (Automation permission).
    AXIsProcessTrusted is NOT required - only Automation permission matters.
    
    Returns:
        True if permission is granted, False otherwise.
    """
    if sys.platform != "darwin":
        return True  # Non-macOS: assume authorized
    
    # The real test: can we actually run AppleScript to get window info?
    # This tests Automation permission which is what we actually need.
    return _test_accessibility_with_applescript()


def _test_accessibility_with_applescript() -> bool:
    """
    Test Accessibility/Automation permission by running a simple AppleScript.
    
    This tests if the app can actually use System Events, which requires
    BOTH Accessibility permission AND Automation permission for System Events.
    
    Returns:
        True if the AppleScript succeeds, False otherwise.
    """
    try:
        # Simple test: try to get the frontmost app name
        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            return name of frontApp
        end tell
        '''
        
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5  # Longer timeout in case permission dialog shows
        )
        
        if result.returncode == 0:
            logger.debug(f"AppleScript test succeeded: {result.stdout.strip()}")
            return True
        else:
            # Check for permission-related errors
            stderr = result.stderr.lower()
            
            # Error codes and messages that indicate permission issues:
            # -10827: not running (often permission-related)
            # -1743: user interaction not allowed
            # -1728: can't get (permission denied)
            # "not allowed assistive access" - Accessibility permission needed
            # "not permitted to send apple events" - Automation permission needed
            
            permission_indicators = [
                "not allowed", "assistive", "-10827", "-1743", "-1728",
                "not permitted", "permission denied", "not authorized"
            ]
            
            is_permission_error = any(ind in stderr for ind in permission_indicators)
            
            if is_permission_error:
                logger.warning(f"Permission denied for AppleScript: {result.stderr.strip()}")
                return False
            
            # Other error - still treat as failure
            logger.warning(f"AppleScript test failed: {result.stderr.strip()}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.warning("AppleScript test timed out - may indicate permission dialog is waiting")
        return False
    except Exception as e:
        logger.warning(f"AppleScript test error: {e}")
        return False


# --- Time Formatting Helpers ---

def format_badge_time(seconds: int) -> str:
    """
    Format seconds for the time remaining badge in top right corner.
    
    Uses full words: "hrs" for hours-only, "hr" with minutes, "min" for minutes.
    
    Args:
        seconds: Number of seconds to format.
        
    Returns:
        Formatted string like "2hrs", "1hr 3min", "30min", "45sec".
    """
    if seconds <= 0:
        return "0 sec"
    
    hours = seconds // 3600
    remaining = seconds % 3600
    mins = remaining // 60
    secs = remaining % 60
    
    if hours > 0 and mins > 0:
        # Hours and minutes: "1hr 30min"
        return f"{hours}hr {mins}min"
    elif hours > 0:
        # Hours only: "2hrs" (plural)
        return f"{hours}hrs"
    elif mins > 0:
        # Minutes only: "30min"
        return f"{mins}min"
    else:
        # Seconds only: "45sec"
        return f"{secs}sec"


def format_stat_time(seconds: float) -> str:
    """
    Format seconds for stat cards (Focus, Distractions).
    
    Uses proper singular/plural forms with spaces.
    
    Args:
        seconds: Number of seconds to format.
        
    Returns:
        Formatted string like "2 hrs 15 min", "45 min", "30 sec", or "0 min".
    """
    total_secs = int(seconds)
    
    if total_secs < 60:
        # Less than a minute - show seconds
        if total_secs == 1:
            return "1 sec"
        else:
            return f"{total_secs} sec"
    
    total_mins = total_secs // 60
    
    if total_mins >= 60:
        hours = total_mins // 60
        mins = total_mins % 60
        hr_unit = "hr" if hours == 1 else "hrs"
        if mins > 0:
            return f"{hours} {hr_unit} {mins} min"
        else:
            return f"{hours} {hr_unit}"
    else:
        return f"{total_mins} min"


# --- Theme System ---
# Supports light/dark themes (dark mode prepared for future)
THEMES = {
    "light": {
        "bg_primary": "#F9F8F4",        # Warm Cream
        "bg_secondary": "#FFFFFF",      # White Cards
        "bg_tertiary": "#F2F0EB",       # Light beige for badges/accents
        "bg_card": "#FFFFFF",           # Card background
        "text_primary": "#1C1C1E",      # Sharp Black
        "text_secondary": "#8E8E93",    # System Gray
        "text_white": "#FFFFFF",        # White text for buttons
        "border": "#E5E5EA",            # Visible borders
        "border_focus": "#1C1C1E",      # Focus ring color
        "accent_primary": "#2C3E50",    # Dark Blue/Grey
        "accent_warm": "#F59E0B",       # Warm accent for alerts
        "status_focused": "#34C759",    # Subtle green for success
        "status_focused_bg": "#D1FAE5", # Light green background
        "status_away": "#F59E0B",       # Amber for away
        "status_away_bg": "#FEF3C7",    # Light amber background
        "status_gadget": "#EF4444",     # Red for gadget distraction
        "status_gadget_bg": "#FEE2E2",  # Light red background
        "status_screen": "#8B5CF6",     # Purple for screen distraction
        "status_screen_bg": "#EDE9FE",  # Light purple background
        "status_idle": "#8E8E93",       # Gray for idle
        "status_paused": "#8E8E93",     # Muted gray for paused
        "button_start": "#1C1C1E",      # Black start button
        "button_start_hover": "#2C3E50", # Dark Grey on hover
        "button_stop": "#EF4444",       # Red stop button
        "button_stop_hover": "#DC2626", # Darker red on hover
        "button_pause": "#8E8E93",      # Gray pause button
        "button_pause_hover": "#6B7280", # Darker gray on hover
        "button_resume": "#2C3E50",     # Dark Blue resume button
        "button_resume_hover": "#3B82F6", # Blue on hover
        "button_settings": "#8E8E93",   # Gray for settings
        "button_settings_hover": "#6B7280", # Darker gray on hover
        "time_badge": "#8B5CF6",        # Purple for time remaining
        "time_badge_low": "#F59E0B",    # Orange when time is low
        "time_badge_expired": "#EF4444", # Red when time expired
        "toggle_on": "#2C3E50",         # Dark Blue for enabled toggles
        "toggle_off": "#E5E5EA",        # Light gray for disabled toggles
        "toggle_text_on": "#FFFFFF",    # White text when toggle on
        "toggle_text_off": "#8E8E93",   # Gray text when toggle off
        
        # New Seraphic Colors
        "shadow_light": "#E5E5EA", 
        "shadow_lighter": "#F2F2F7",
        "badge_bg": "#F2F0EB",
        "badge_text": "#2C3E50"
    },
    # Dark theme prepared for future implementation
    "dark": {
        "bg_primary": "#1F2937",
        "bg_secondary": "#374151",
        "bg_tertiary": "#4B5563",
        "bg_card": "#374151",
        "text_primary": "#F9FAFB",
        "text_secondary": "#9CA3AF",
        "text_white": "#FFFFFF",
        "border": "#4B5563",
        "border_focus": "#60A5FA",
        "accent_primary": "#60A5FA",
        "accent_warm": "#FBBF24",
        "status_focused": "#34D399",
        "status_focused_bg": "#064E3B",  # Dark green background
        "status_away": "#FBBF24",
        "status_away_bg": "#78350F",     # Dark amber background
        "status_gadget": "#F87171",
        "status_gadget_bg": "#7F1D1D",   # Dark red background
        "status_screen": "#A78BFA",
        "status_screen_bg": "#4C1D95",   # Dark purple background
        "status_idle": "#6B7280",
        "status_paused": "#9CA3AF",
        "button_start": "#10B981",
        "button_start_hover": "#059669",
        "button_stop": "#EF4444",
        "button_stop_hover": "#DC2626",
        "button_pause": "#6B7280",
        "button_pause_hover": "#4B5563",
        "button_resume": "#60A5FA",
        "button_resume_hover": "#3B82F6",
        "button_settings": "#6B7280",
        "button_settings_hover": "#4B5563",
        "time_badge": "#A78BFA",
        "time_badge_low": "#FBBF24",
        "time_badge_expired": "#F87171",
        "toggle_on": "#60A5FA",
        "toggle_off": "#4B5563",
        "toggle_text_on": "#FFFFFF",
        "toggle_text_off": "#9CA3AF",
    }
}

# Current theme (light mode default)
current_theme = "light"

def get_colors():
    """Get the current theme's color palette."""
    return THEMES[current_theme]

# Active color palette (for backward compatibility)
COLORS = get_colors()

# --- UI Dimension Constants ---
# Base dimensions for scalable UI elements (at scale 1.0)
# These are multiplied by current_scale during rendering

# Button dimensions (start/stop, pause)
UI_BUTTON_WIDTH = 240
UI_BUTTON_HEIGHT = 64
UI_BUTTON_MIN_WIDTH = 160
UI_BUTTON_MIN_HEIGHT = 46

# Camera card (status display)
UI_CAMERA_CARD_WIDTH = 400
UI_CAMERA_CARD_HEIGHT = 240
UI_CAMERA_CARD_MIN_WIDTH = 280
UI_CAMERA_CARD_MIN_HEIGHT = 168

# Stat card dimensions
UI_STAT_CARD_WIDTH = 280
UI_STAT_CARD_HEIGHT = 120
UI_STAT_CARD_MIN_WIDTH = 200
UI_STAT_CARD_MIN_HEIGHT = 85

# Layout padding values (base values, scaled at runtime)
UI_HEADER_PADDING = 20
UI_MAIN_PADDING = 40
UI_FOOTER_PADDING = 50
UI_TIMER_BOTTOM_PAD = 40
UI_STAT_CARD_GAP = 5

# Assets directory for logos (bundled with app)
ASSETS_DIR = config.BASE_DIR / "assets"

# Import scaling system from ui_components
from gui.ui_components import (
    ScalingManager, 
    REFERENCE_WIDTH, 
    REFERENCE_HEIGHT, 
    MIN_WIDTH, 
    MIN_HEIGHT,
    FONT_BOUNDS,
    get_screen_scale_factor,
    normalize_tk_scaling
)

# Base dimensions for scaling (larger default window) - keep for backward compat
BASE_WIDTH = REFERENCE_WIDTH
BASE_HEIGHT = REFERENCE_HEIGHT


# --- Font System with Fallback ---
# Primary font is SF Pro Display (macOS). Fallbacks are similar-looking sans-serif fonts.
# Font priority order: SF Pro Display > Segoe UI (Windows) > Helvetica Neue > Helvetica > Arial
_available_fonts_cache = None

def _get_available_fonts():
    """
    Get list of available font families on the system.
    Results are cached for performance.
    
    Returns:
        Set of lowercase font family names available on the system.
    """
    global _available_fonts_cache
    if _available_fonts_cache is None:
        try:
            # Create a temporary root if needed to access font families
            temp_root = None
            try:
                # Try to get existing Tk instance
                root = tk._default_root
                if root is None:
                    temp_root = tk.Tk()
                    temp_root.withdraw()
                    root = temp_root
                _available_fonts_cache = {f.lower() for f in tkfont.families()}
            finally:
                if temp_root:
                    temp_root.destroy()
        except Exception:
            _available_fonts_cache = set()
    return _available_fonts_cache


def get_system_font(size: int = 11, weight: str = "normal") -> tuple:
    """
    Get the best available system font with fallback.
    
    Primary font is SF Pro Display (macOS). Falls back to similar-looking
    sans-serif fonts on other platforms (Segoe UI on Windows, then Helvetica).
    
    Args:
        size: Font size in points
        weight: Font weight ("normal" or "bold")
        
    Returns:
        Tuple of (font_family, size, weight) suitable for tkinter
    """
    # Font priority order - SF Pro Display and similar modern sans-serif fonts
    font_priority = [
        "SF Pro Display",      # macOS primary
        "SF Pro Text",         # macOS alternative
        ".SF NS Text",         # macOS system font variant
        "Segoe UI",            # Windows primary (very similar to SF Pro)
        "Helvetica Neue",      # Cross-platform, similar style
        "Helvetica",           # Universal fallback
        "Arial",               # Ultimate fallback (available everywhere)
    ]
    
    available = _get_available_fonts()
    
    for font_name in font_priority:
        if font_name.lower() in available:
            return (font_name, size, weight)
    
    # If nothing found, return Helvetica (tkinter default)
    return ("Helvetica", size, weight)


class RoundedButton(tk.Canvas):
    """Rounded, soft-shadow button for Seraphic theme."""

    def __init__(
        self,
        parent,
        text,
        command=None,
        width=200,
        height=50,
        radius=25,
        bg_color=None,
        hover_color=None,
        fg_color=None,
        text_color=None,
        font=None,
        font_type=None,
        corner_radius=None,
        padx=30,
        pady=12,
        **kwargs
    ):
        """Initialize the button with optional hover and disabled states."""
        # Discard legacy args that shouldn't reach Canvas
        _ = font_type  # Legacy support, intentionally unused
        kwargs.pop("font_type", None)

        # Defaults
        bg_color = bg_color or COLORS["button_start"]
        hover_color = hover_color or bg_color
        fg_color = fg_color or text_color or COLORS["text_white"]
        corner_radius = corner_radius or radius

        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        super().__init__(parent, width=width, height=height, bg=parent_bg, highlightthickness=0, **kwargs)

        self.command = command
        self.radius = corner_radius
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = fg_color
        self.text_str = text
        self.font_obj = font
        self._enabled = True

        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", self._on_resize)

        self.draw()

    def _on_resize(self, event):
        """Redraw on resize."""
        self.draw()

    def draw(self, offset=0):
        """Render the button body, shadow, and label."""
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])

        x1, y1 = 2, 2 + offset
        x2, y2 = w - 2, h - 2 + offset
        r = min(self.radius, h / 2)

        if offset == 0:
            self.create_rounded_rect(x1 + 2, y1 + 4, x2 + 2, y2 + 4, r, fill=COLORS.get("shadow_light", "#E5E5EA"), outline="")

        self.create_rounded_rect(x1, y1, x2, y2, r, fill=self.bg_color, outline=self.bg_color)

        font_to_use = self.font_obj or ("Helvetica", 14, "bold")
        self.create_text(w // 2, h // 2 + offset, text=self.text_str, fill=self.text_color, font=font_to_use)

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        """Draw a rounded rectangle polygon."""
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _on_click(self, event):
        """Handle click when enabled."""
        if self._enabled and self.command:
            self.draw(offset=2)  # Show pressed state before command
            self.update_idletasks()
            self.command()
            # Only redraw if widget still exists (command may have destroyed it)
            if self.winfo_exists():
                self.after(100, lambda: self.draw(offset=0) if self.winfo_exists() else None)

    def _on_enter(self, event):
        """Apply hover color."""
        self.config(cursor="")
        if self._enabled:
            self._original_bg = self.bg_color
            self.bg_color = self.hover_color
            self.draw()

    def _on_leave(self, event):
        """Restore normal color."""
        self.config(cursor="")
        if self._enabled and hasattr(self, "_original_bg"):
            self.bg_color = self._original_bg
            self.draw()

    def configure(self, **kwargs):
        """Update button properties and redraw."""
        if "text" in kwargs:
            self.text_str = kwargs.pop("text")
        if "bg_color" in kwargs:
            self.bg_color = kwargs.pop("bg_color")
        if "hover_color" in kwargs:
            self.hover_color = kwargs.pop("hover_color")
        if "text_color" in kwargs:
            self.text_color = kwargs.pop("text_color")
        if "fg_color" in kwargs:
            self.text_color = kwargs.pop("fg_color")
        if "state" in kwargs:
            self._enabled = kwargs.pop("state") != tk.DISABLED
            if not self._enabled:
                self.bg_color = COLORS["bg_tertiary"]
        super().configure(**kwargs)
        self.draw()


class IconButton(tk.Canvas):
    """
    Rounded icon button with custom-drawn icons.
    
    Supports 'settings' (gear) and 'tutorial' (lightbulb) icons
    with hover effects and scalable sizing.
    """
    
    def __init__(
        self,
        parent,
        icon_type: str,
        command=None,
        size: int = 36,
        bg_color=None,
        hover_color=None,
        icon_color=None,
        corner_radius: int = 8,
        image_path: str = None,
        **kwargs
    ):
        """
        Initialize the icon button.
        
        Args:
            parent: Parent widget
            icon_type: Type of icon ('settings' or 'tutorial')
            command: Callback function when clicked
            size: Button size in pixels (square)
            bg_color: Background color
            hover_color: Background color on hover
            icon_color: Color of the icon
            corner_radius: Radius for rounded corners
            image_path: Optional path to PNG icon file
        """
        # Default colors from theme
        bg_color = bg_color or COLORS.get("bg_secondary", "#FFFFFF")
        hover_color = hover_color or COLORS.get("bg_tertiary", "#F2F0EB")
        icon_color = icon_color or COLORS.get("text_secondary", "#8E8E93")
        
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        super().__init__(parent, width=size, height=size, bg=parent_bg, highlightthickness=0, **kwargs)
        
        self.icon_type = icon_type
        self.command = command
        self.size = size
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.icon_color = icon_color
        self.corner_radius = corner_radius
        self.image_path = image_path
        self._enabled = True
        self._photo_image = None  # Keep reference to prevent GC
        
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", self._on_resize)
        
        self.draw()
    
    def _on_resize(self, event):
        """Redraw on resize."""
        self.size = min(event.width, event.height)
        self.draw()
    
    def draw(self, pressed: bool = False):
        """Render the button background and icon."""
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])
        size = min(w, h)
        
        # Draw rounded rectangle background
        # Only draw background if hovered or pressed (or if bg_color is different from parent/transparent)
        # We check if current bg_color matches the hover_color to detect hover state
        is_hovered = (self.bg_color == self.hover_color)
        
        padding = 2
        offset = 1 if pressed else 0
        x1, y1 = padding, padding + offset
        x2, y2 = size - padding, size - padding + offset
        r = min(self.corner_radius, size / 4)
        
        if is_hovered or pressed:
            self._draw_rounded_rect(x1, y1, x2, y2, r, fill=self.bg_color, outline="")
        
        # Draw the icon
        center_x = size / 2
        center_y = size / 2 + offset
        
        # Try to load image if path provided
        if self.image_path and PIL_AVAILABLE:
            if self._draw_image_icon(center_x, center_y, size):
                return
        
        # Fallback to drawn icons
        icon_size = size * 0.5  # Icon takes 50% of button size
        
        if self.icon_type == "settings":
            self._draw_gear_icon(center_x, center_y, icon_size)
        elif self.icon_type == "tutorial":
            self._draw_lightbulb_icon(center_x, center_y, icon_size)
            
    def _draw_image_icon(self, cx, cy, btn_size):
        """Draw icon from image file."""
        try:
            if not os.path.exists(self.image_path):
                return False
                
            # Load original image if not already loaded or if size changed significantly
            # We reload to ensure high quality scaling
            icon_size = int(btn_size * 0.6)  # Image takes 60% of button
            
            img = Image.open(self.image_path)
            img = img.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
            self._photo_image = ImageTk.PhotoImage(img)
            
            self.create_image(cx, cy, image=self._photo_image)
            return True
        except Exception as e:
            logger.warning(f"Failed to load icon image {self.image_path}: {e}")
            return False
    
    def _draw_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        """Draw a rounded rectangle."""
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1
        ]
        return self.create_polygon(points, smooth=True, **kwargs)
    
    def _draw_gear_icon(self, cx, cy, size):
        """Draw a gear/cog icon."""
        import math
        
        # Increased size for better visibility
        outer_r = size / 1.8
        inner_r = size / 2.6
        hole_r = size / 5
        teeth = 8
        
        # Create gear shape with teeth
        points = []
        for i in range(teeth * 2):
            angle = (i * math.pi / teeth) - (math.pi / 2)
            # Use trapezoidal teeth for a more mechanical look
            # Even indices are outer points, odd are inner
            r = outer_r if i % 2 == 0 else inner_r
            
            # Add slight angle offset for tooth width
            tooth_width_angle = (math.pi / teeth) * 0.4
            
            if i % 2 == 0:
                # Outer tooth edge (two points)
                a1 = angle - tooth_width_angle
                a2 = angle + tooth_width_angle
                points.extend([
                    cx + outer_r * math.cos(a1), cy + outer_r * math.sin(a1),
                    cx + outer_r * math.cos(a2), cy + outer_r * math.sin(a2)
                ])
            else:
                # Inner valley (one point in middle)
                points.extend([
                    cx + inner_r * math.cos(angle), cy + inner_r * math.sin(angle)
                ])
        
        # Draw gear body
        self.create_polygon(points, fill=self.icon_color, outline=self.icon_color, smooth=True)
        
        # Draw center hole
        self.create_oval(
            cx - hole_r, cy - hole_r,
            cx + hole_r, cy + hole_r,
            fill=self.bg_color, outline=self.bg_color
        )
    
    def _draw_lightbulb_icon(self, cx, cy, size):
        """Draw a tutorial icon (Book with exclamation mark)."""
        # Book dimensions
        book_w = size * 0.8
        book_h = size * 0.6
        spine_x = cx
        
        # Draw open book shape (two rounded rectangles meeting at spine)
        # Left page
        self.create_polygon(
            cx, cy - book_h/2,           # Top spine
            cx - book_w/2, cy - book_h/2, # Top left
            cx - book_w/2, cy + book_h/2, # Bottom left
            cx, cy + book_h/2,           # Bottom spine
            fill=self.icon_color, outline=self.icon_color, smooth=True
        )
        
        # Right page
        self.create_polygon(
            cx, cy - book_h/2,           # Top spine
            cx + book_w/2, cy - book_h/2, # Top right
            cx + book_w/2, cy + book_h/2, # Bottom right
            cx, cy + book_h/2,           # Bottom spine
            fill=self.icon_color, outline=self.icon_color, smooth=True
        )
        
        # Draw spine line
        self.create_line(
            cx, cy - book_h/2,
            cx, cy + book_h/2,
            fill=self.bg_color, width=2
        )
        
        # Draw exclamation mark on right page
        excl_x = cx + book_w/4
        excl_top_y = cy - book_h/4
        excl_bot_y = cy + book_h/8
        
        # Line part
        self.create_line(
            excl_x, excl_top_y,
            excl_x, excl_bot_y,
            fill=self.bg_color, width=size*0.08, capstyle=tk.ROUND
        )
        
        # Dot part
        dot_y = cy + book_h/3
        dot_r = size * 0.04
        self.create_oval(
            excl_x - dot_r, dot_y - dot_r,
            excl_x + dot_r, dot_y + dot_r,
            fill=self.bg_color, outline=self.bg_color
        )
    
    def _on_click(self, event):
        """Handle click."""
        if self._enabled and self.command:
            self.draw(pressed=True)
            self.update_idletasks()
            self.command()
            if self.winfo_exists():
                self.after(100, lambda: self.draw(pressed=False) if self.winfo_exists() else None)
    
    def _on_enter(self, event):
        """Apply hover effect."""
        if self._enabled:
            self._original_bg = self.bg_color
            self.bg_color = self.hover_color
            self.draw()
    
    def _on_leave(self, event):
        """Restore normal state."""
        if self._enabled and hasattr(self, "_original_bg"):
            self.bg_color = self._original_bg
            self.draw()
    
    def configure(self, **kwargs):
        """Update button properties."""
        if "size" in kwargs:
            new_size = kwargs.pop("size")
            self.size = new_size
            super().configure(width=new_size, height=new_size)
        if "bg_color" in kwargs:
            self.bg_color = kwargs.pop("bg_color")
        if "hover_color" in kwargs:
            self.hover_color = kwargs.pop("hover_color")
        if "icon_color" in kwargs:
            self.icon_color = kwargs.pop("icon_color")
        super().configure(**kwargs)
        self.draw()


class Card(tk.Canvas):
    """Rounded card container with soft shadow."""

    def __init__(self, parent, width=300, height=150, radius=20, bg_color=None, text=None, text_color=None, font=None):
        """Initialize the card surface."""
        bg_color = bg_color or COLORS["bg_secondary"]
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        super().__init__(parent, width=width, height=height, bg=parent_bg, highlightthickness=0)
        self.radius = radius
        self.bg_color = bg_color
        self.text = text
        self.text_color = text_color
        self.font = font
        self.bind("<Configure>", self._on_resize)
        self.draw()

    def _on_resize(self, event):
        """Redraw on resize."""
        self.draw()

    def draw(self):
        """Render shadow and card surface."""
        # Only delete our internal elements (tagged)
        self.delete("card_bg")
        self.delete("card_text")
        
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])
        r = self.radius
        
        # Draw background with tag "card_bg"
        # Shadow layer - bottom-right offset
        self.create_rounded_rect(5, 6, w - 1, h - 2, r, fill="#D1D1D6", outline="", tags="card_bg")
        # Main card surface
        self.create_rounded_rect(0, 0, w - 6, h - 8, r, fill=self.bg_color, outline="", tags="card_bg")
        
        # Ensure background is at the bottom so it doesn't cover external items
        self.tag_lower("card_bg")
        
        if self.text:
            font_to_use = self.font or ("Helvetica", 12, "bold")
            fill_color = self.text_color or COLORS["text_primary"]
            self.create_text(w // 2, h // 2, text=self.text, fill=fill_color, font=font_to_use, tags="card_text")

    def configure_card(self, text=None, bg_color=None, text_color=None):
        """Update card styling and text."""
        if text is not None:
            self.text = text
        if bg_color is not None:
            self.bg_color = bg_color
        if text_color is not None:
            self.text_color = text_color
        self.draw()

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        """Draw a rounded rectangle polygon."""
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)


class Badge(tk.Canvas):
    """Rounded badge for status and time remaining."""

    def __init__(
        self,
        parent,
        text,
        bg_color=None,
        text_color=None,
        font=None,
        corner_radius=18,
        clickable=False,
        width=120,
        height=36,
        fg_color=None
    ):
        """Initialize the badge surface."""
        bg_color = bg_color or COLORS.get("badge_bg", "#F2F0EB")
        text_color = text_color or fg_color or COLORS.get("badge_text", "#2C3E50")
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        super().__init__(parent, width=width, height=height, bg=parent_bg, highlightthickness=0)
        self.text = text
        self.bg_color = bg_color
        self.text_color = text_color
        self.font = font
        self.corner_radius = corner_radius
        self.clickable = clickable
        self.draw()
        if self.clickable:
            self.bind("<Enter>", lambda e: self.config(cursor=""))
            self.bind("<Leave>", lambda e: self.config(cursor=""))

    def draw(self):
        """Render the badge background and label."""
        self.delete("all")
        w = int(self["width"])
        h = int(self["height"])
        # Small shadow on bottom-right
        self.create_rounded_rect(3, 4, w - 1, h - 1, self.corner_radius, fill="#D8D8DC", outline="")
        # Main badge surface
        self.create_rounded_rect(0, 0, w - 4, h - 5, self.corner_radius, fill=self.bg_color, outline="")
        font_to_use = self.font or ("Helvetica", 12, "bold")
        self.create_text((w - 4) // 2, (h - 5) // 2, text=self.text, fill=self.text_color, font=font_to_use)

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        """Draw a rounded rectangle polygon."""
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)

    def configure_badge(self, text=None, bg_color=None, fg_color=None, font=None):
        """Update badge styling and text."""
        if text:
            self.text = text
        if bg_color:
            self.bg_color = bg_color
        if fg_color:
            self.text_color = fg_color
        if font:
            self.font = font
        self.draw()

    def bind_click(self, callback):
        """Bind a click handler to the badge."""
        self.bind("<Button-1>", lambda e: callback())

    def configure(self, **kwargs):
        """Allow text updates via configure."""
        if "text" in kwargs:
            self.text = kwargs.pop("text")
            self.draw()
        super().configure(**kwargs)

# Alias Badge to RoundedBadge for compatibility if needed, but we updated usage
RoundedBadge = Badge


class Tooltip:
    """
    A tooltip that appears when hovering over a widget.
    
    Shows full text on hover, similar to browser tab tooltips.
    Uses SF Pro Display on macOS with fallback to similar fonts on other platforms.
    """
    
    def __init__(self, widget, text: str = "", bg: str = "#1E293B", fg: str = "#F1F5F9"):
        """
        Initialize tooltip for a widget.
        
        Args:
            widget: The widget to attach tooltip to
            text: Tooltip text (can be updated later)
            bg: Background color
            fg: Text color
        """
        self.widget = widget
        self.text = text
        self.bg = bg
        self.fg = fg
        self.tooltip_window = None
        
        # Bind hover events
        self.widget.bind("<Enter>", self._show_tooltip)
        self.widget.bind("<Leave>", self._hide_tooltip)
        self.widget.bind("<Motion>", self._move_tooltip)
    
    def update_text(self, text: str):
        """Update the tooltip text."""
        self.text = text
        # If tooltip is currently showing, update it
        if self.tooltip_window:
            for child in self.tooltip_window.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(text=text)
    
    def _show_tooltip(self, event=None):
        """Show the tooltip window."""
        if not self.text:
            return
        
        # Create tooltip window
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)  # No window decorations
        self.tooltip_window.wm_attributes("-topmost", True)
        
        # Position near the widget
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        
        # Create tooltip content with padding
        frame = tk.Frame(self.tooltip_window, bg=self.bg, bd=1, relief="solid")
        frame.pack()
        
        # Use system font with fallback (SF Pro Display > Segoe UI > Helvetica)
        tooltip_font = get_system_font(size=11, weight="normal")
        
        label = tk.Label(
            frame,
            text=self.text,
            bg=self.bg,
            fg=self.fg,
            font=tooltip_font,
            padx=8,
            pady=4,
            wraplength=400,  # Wrap long text
            justify="left"
        )
        label.pack()
    
    def _hide_tooltip(self, event=None):
        """Hide the tooltip window."""
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
    
    def _move_tooltip(self, event=None):
        """Move tooltip to follow mouse."""
        if self.tooltip_window:
            x = self.widget.winfo_rootx() + 10
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            self.tooltip_window.wm_geometry(f"+{x}+{y}")


class NotificationPopup:
    """
    A floating notification popup that appears on top of all windows.
    
    Shows supportive messages when the user is unfocused, with auto-dismiss
    after a configurable duration and a manual close button.
    """
    
    # Class-level reference to track active popup (only one at a time)
    _active_popup: Optional['NotificationPopup'] = None
    
    # Consistent font family for the app (Seraphic theme)
    FONT_FAMILY = "Georgia"
    FONT_FAMILY_FALLBACK = "Times New Roman"
    
    def __init__(
        self, 
        parent: tk.Tk, 
        badge_text: str,
        message: str, 
        duration_seconds: int = 10
    ):
        """
        Initialize the notification popup.
        
        Args:
            parent: Parent Tk root window
            badge_text: The badge/pill text (e.g., "Focus paused")
            message: The main message to display
            duration_seconds: How long before auto-dismiss (default 10s)
        """
        # Dismiss any existing popup first
        if NotificationPopup._active_popup is not None:
            NotificationPopup._active_popup.dismiss()
        
        self.parent = parent
        self.badge_text = badge_text
        self.message = message
        self.duration = duration_seconds
        self._dismiss_after_id: Optional[str] = None
        self._is_dismissed = False
        
        # Create the popup window
        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)  # Borderless window
        self.window.attributes('-topmost', True)  # Always on top
        
        # Fixed popup dimensions (no scaling - should remain consistent)
        self.popup_width = 300
        self.popup_height = 215
        
        # On macOS, make the window background transparent for true rounded corners
        if sys.platform == "darwin":
            # Use transparent background
            self.window.attributes('-transparent', True)
            self.window.config(bg='systemTransparent')
        
        # Center on screen
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = (screen_width - self.popup_width) // 2
        y = (screen_height - self.popup_height) // 2
        self.window.geometry(f"{self.popup_width}x{self.popup_height}+{x}+{y}")
        
        # Build the UI
        self._create_ui()
        
        # Start auto-dismiss timer
        self._start_dismiss_timer()
        
        # Register as active popup
        NotificationPopup._active_popup = self
        
        # Aggressively bring notification to front (even when app is in background)
        self._ensure_front()
        
        logger.debug(f"Notification popup shown: {badge_text} - {message}")
    
    def _ensure_front(self):
        """Ensure the notification stays on top of all windows."""
        if self._is_dismissed:
            return
        
        # Lift and focus
        self.window.lift()
        self.window.attributes('-topmost', True)
        
        # On macOS, we need to be more aggressive
        if sys.platform == "darwin":
            self.window.focus_force()
            # Schedule additional lifts to ensure visibility
            self.parent.after(50, self._lift_again)
            self.parent.after(150, self._lift_again)
            self.parent.after(300, self._lift_again)
    
    def _lift_again(self):
        """Lift the window again (called after delays)."""
        if self._is_dismissed:
            return
        try:
            self.window.lift()
            self.window.attributes('-topmost', True)
        except Exception:
            pass
    
    def _get_font(self, size: int, weight: str = "normal") -> tuple:
        """Get font tuple with fallback."""
        return (self.FONT_FAMILY, size, weight)
    
    def _create_ui(self):
        """Build the popup UI matching the reference design."""
        # Colors matching the design exactly
        bg_color = "#FFFFFF"           # White background
        border_color = "#D1D5DB"       # Light gray border for visibility
        text_dark = "#1F2937"          # Dark text for message
        text_muted = "#B0B8C1"         # Light gray for close button
        accent_blue = "#3B82F6"        # Blue color for BrainDock title
        badge_bg = "#F3F4F6"           # Light gray badge background
        badge_border = "#E5E7EB"       # Badge border
        badge_text_color = "#4B5563"   # Dark gray badge text
        dot_color = "#D1D5DB"          # Very light gray dot (subtle)
        corner_radius = 24             # Rounded corners
        border_width = 2               # Border thickness
        
        # Transparent background for macOS, white for others
        if sys.platform == "darwin":
            canvas_bg = 'systemTransparent'
        else:
            canvas_bg = bg_color
        
        # Create canvas for the popup
        self.canvas = tk.Canvas(
            self.window,
            width=self.popup_width,
            height=self.popup_height,
            bg=canvas_bg,
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Draw border first (slightly larger rounded rect behind the background)
        self._draw_smooth_rounded_rect(
            self.canvas,
            0, 0,
            self.popup_width, self.popup_height,
            corner_radius,
            fill=border_color
        )
        
        # Draw main white background with rounded corners (inset by border width)
        self._draw_smooth_rounded_rect(
            self.canvas,
            border_width, border_width,
            self.popup_width - border_width, self.popup_height - border_width,
            corner_radius - border_width,
            fill=bg_color
        )
        
        # BrainDock logo with text
        title_y = 32
        title_x = 28
        
        # Load and display the logo image
        self.logo_image = None  # Keep reference to prevent garbage collection
        logo_path = ASSETS_DIR / "logo_with_text.png"
        
        if logo_path.exists() and Image is not None:
            try:
                img = Image.open(logo_path)
                
                # Get bounding box to crop transparent/empty space
                if img.mode == 'RGBA':
                    bbox = img.getbbox()
                    if bbox:
                        img = img.crop(bbox)
                
                # Scale to fit nicely in the notification header
                # Target height around 24px for the logo
                target_height = 20
                aspect_ratio = img.width / img.height
                target_width = int(target_height * aspect_ratio)
                
                img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                self.logo_image = ImageTk.PhotoImage(img)
                
                # Place logo on canvas
                self.canvas.create_image(
                    title_x, title_y,
                    image=self.logo_image,
                    anchor="w"
                )
                
                # Status dot position based on logo width
                dot_x = title_x + target_width + 8
            except Exception as e:
                logger.warning(f"Could not load notification logo: {e}")
                # Fallback to text
                self.canvas.create_text(
                    title_x, title_y,
                    text="BRAINDOCK",
                    font=self._get_font(14, "bold"),
                    fill=accent_blue,
                    anchor="w"
                )
                dot_x = title_x + 95
        else:
            # Fallback to text if image not available
            self.canvas.create_text(
                title_x, title_y,
                text="BRAINDOCK",
                font=self._get_font(14, "bold"),
                fill=accent_blue,
                anchor="w"
            )
            dot_x = title_x + 95
        
        # Status dot next to logo/title
        dot_size = 7
        self.canvas.create_oval(
            dot_x, title_y - dot_size // 2,
            dot_x + dot_size, title_y + dot_size // 2,
            fill=dot_color,
            outline=""
        )
        
        # Close button with hover background
        close_x = self.popup_width - 32
        close_y = title_y
        close_bg_color = "#F0F4F5"  # Light gray background on hover (RGB 240, 244, 245)
        
        # Background circle for close button (starts as white/invisible, needs fill for events)
        self.close_bg_id = self.canvas.create_oval(
            close_x - 16, close_y - 16,
            close_x + 16, close_y + 16,
            fill=bg_color,  # Same as background (white) so it's invisible but receives events
            outline="",
            tags="close_btn"
        )
        
        # Close button "X"
        self.close_text_id = self.canvas.create_text(
            close_x, close_y,
            text="\u00D7",  # Multiplication sign (cleaner X)
            font=self._get_font(28, "normal"),
            fill=text_muted,
            anchor="center",
            tags="close_btn"
        )
        
        # Store colors for hover events
        self._close_bg_color = close_bg_color
        self._close_bg_normal = bg_color  # White background when not hovering
        self._text_muted = text_muted
        self._text_dark = text_dark
        
        # Bind close button events with background highlight
        self.canvas.tag_bind("close_btn", "<Button-1>", lambda e: self.dismiss())
        self.canvas.tag_bind("close_btn", "<Enter>", self._on_close_hover_enter)
        self.canvas.tag_bind("close_btn", "<Leave>", self._on_close_hover_leave)
        
        # Badge/pill below title
        badge_y = 68
        badge_padding_x = 14
        
        # Measure badge text width (approximate)
        badge_char_width = 7.5
        badge_width = len(self.badge_text) * badge_char_width + badge_padding_x * 2
        badge_height = 28
        
        # Draw badge background (rounded pill)
        self._draw_smooth_rounded_rect(
            self.canvas,
            28, badge_y - badge_height // 2,
            28 + badge_width, badge_y + badge_height // 2,
            badge_height // 2,
            fill=badge_bg,
            outline=badge_border
        )
        
        # Badge text
        self.canvas.create_text(
            28 + badge_width // 2, badge_y,
            text=self.badge_text,
            font=self._get_font(12, "normal"),
            fill=badge_text_color,
            anchor="center"
        )
        
        # Main message text (large, left-aligned)
        message_y = 115
        self.canvas.create_text(
            28, message_y,
            text=self.message,
            font=self._get_font(22, "normal"),
            fill=text_dark,
            anchor="nw",
            width=self.popup_width - 56
        )
    
    def _on_close_hover_enter(self, event):
        """Show gray background on close button hover."""
        self.canvas.itemconfig(self.close_bg_id, fill=self._close_bg_color)
        self.canvas.itemconfig(self.close_text_id, fill=self._text_dark)
    
    def _on_close_hover_leave(self, event):
        """Hide gray background when leaving close button."""
        self.canvas.itemconfig(self.close_bg_id, fill=self._close_bg_normal)
        self.canvas.itemconfig(self.close_text_id, fill=self._text_muted)
    
    def _draw_smooth_rounded_rect(self, canvas, x1, y1, x2, y2, radius, fill="white", outline=""):
        """
        Draw a rounded rectangle using overlapping shapes.
        
        Uses a center rectangle plus corner arcs for clean rounded corners.
        Shapes overlap by 1 pixel to prevent visible seams.
        
        Args:
            canvas: The canvas to draw on
            x1, y1: Top-left corner
            x2, y2: Bottom-right corner
            radius: Corner radius
            fill: Fill color
            outline: Outline color (not used)
        """
        # Draw a single large center rectangle
        canvas.create_rectangle(
            x1 + radius - 1, y1,
            x2 - radius + 1, y2,
            fill=fill, outline=""
        )
        # Left and right strips
        canvas.create_rectangle(
            x1, y1 + radius - 1,
            x1 + radius, y2 - radius + 1,
            fill=fill, outline=""
        )
        canvas.create_rectangle(
            x2 - radius, y1 + radius - 1,
            x2, y2 - radius + 1,
            fill=fill, outline=""
        )
        
        # Draw corner arcs (quarter circles)
        # Top-left
        canvas.create_arc(
            x1, y1, x1 + radius * 2, y1 + radius * 2,
            start=90, extent=90, fill=fill, outline=""
        )
        # Top-right
        canvas.create_arc(
            x2 - radius * 2, y1, x2, y1 + radius * 2,
            start=0, extent=90, fill=fill, outline=""
        )
        # Bottom-left
        canvas.create_arc(
            x1, y2 - radius * 2, x1 + radius * 2, y2,
            start=180, extent=90, fill=fill, outline=""
        )
        # Bottom-right
        canvas.create_arc(
            x2 - radius * 2, y2 - radius * 2, x2, y2,
            start=270, extent=90, fill=fill, outline=""
        )
    
    
    def _start_dismiss_timer(self):
        """Start the auto-dismiss countdown."""
        duration_ms = self.duration * 1000
        self._dismiss_after_id = self.parent.after(duration_ms, self.dismiss)
    
    def dismiss(self):
        """Close and destroy the popup."""
        if self._is_dismissed:
            return
        
        self._is_dismissed = True
        
        # Cancel pending auto-dismiss timer
        if self._dismiss_after_id:
            try:
                self.parent.after_cancel(self._dismiss_after_id)
            except Exception:
                pass
        
        # Destroy window
        try:
            self.window.destroy()
        except Exception:
            pass
        
        # Clear active popup reference
        if NotificationPopup._active_popup is self:
            NotificationPopup._active_popup = None
        
        logger.debug("Notification popup dismissed")


class BrainDockGUI:
    """
    Main GUI application for BrainDock focus tracker.
    
    Provides a clean, scalable interface with:
    - Start/Stop session button
    - Status indicator (Focused / Away / On another gadget)
    - Session timer
    - Auto-generates PDF report on session stop
    """
    
    def __init__(self):
        """Initialize the GUI application."""
        self.root = tk.Tk()
        self.root.title("")  # Empty title - no text in title bar
        self.root.configure(bg=COLORS["bg_primary"])
        
        # Set light appearance on macOS (makes title bar white instead of dark)
        if sys.platform == "darwin":
            self._set_macos_light_mode()
        
        # Initialize scaling manager for responsive UI
        self.scaling_manager = ScalingManager(self.root)
        
        # Calculate initial window size based on screen dimensions
        initial_width, initial_height = self.scaling_manager.get_initial_window_size()
        x, y = self.scaling_manager.get_centered_position(initial_width, initial_height)
        self.root.geometry(f"{initial_width}x{initial_height}+{x}+{y}")
        
        # Enable resizing with minimum size
        self.root.resizable(True, True)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        
        # Calculate and set initial scale based on actual window dimensions
        self.current_scale = self.scaling_manager.calculate_scale(initial_width, initial_height)
        self.scaling_manager.set_scale(self.current_scale)  # Sync scaling manager's internal scale
        self._last_width = initial_width
        self._last_height = initial_height
        
        # State variables
        self.session: Optional[Session] = None
        self.is_running = False
        self.should_stop = threading.Event()
        self.detection_thread: Optional[threading.Thread] = None
        self.screen_detection_thread: Optional[threading.Thread] = None
        self.current_status = "idle"  # idle, focused, away, gadget, screen, paused
        self.session_start_time: Optional[datetime] = None
        self.session_started = False  # Track if first detection has occurred
        
        # Monitoring mode (defaults to camera-only for backward compatibility)
        self.monitoring_mode = config.MODE_CAMERA_ONLY
        self.blocklist_manager = BlocklistManager(config.SCREEN_SETTINGS_FILE)
        self.blocklist = self.blocklist_manager.load()
        self.use_ai_fallback = config.SCREEN_AI_FALLBACK_ENABLED
        
        # Pause state tracking
        self.is_paused = False  # Whether session is currently paused
        self.pause_start_time: Optional[datetime] = None  # When current pause began
        self.total_paused_seconds: float = 0.0  # Accumulated pause time in session (float for precision)
        self.frozen_active_seconds: int = 0  # Frozen timer display value when paused
        
        # Distraction counters for stats
        self.gadget_detection_count = 0
        self.screen_distraction_count = 0
        
        # Unfocused alert tracking
        self.unfocused_start_time: Optional[float] = None
        self.alerts_played: int = 0  # Tracks how many alerts have been played (max 3)
        
        # Usage limit tracking
        self.usage_limiter: UsageLimiter = get_usage_limiter()
        self.is_locked: bool = False  # True when time exhausted and app is locked
        
        # Daily stats tracking (accumulates across sessions, resets at midnight)
        self.daily_stats: DailyStatsTracker = get_daily_stats_tracker()
        
        # UI update lock
        self.ui_lock = threading.Lock()
        
        # Shared detection state for priority resolution (used in "both" mode)
        # These track the latest detection state from each detector
        self._camera_state: Optional[Dict] = None  # Latest camera detection result
        self._screen_state: Optional[Dict] = None  # Latest screen detection result
        self._state_lock = threading.Lock()  # Thread-safe access to detection states
        
        # Create UI elements
        self._create_fonts()
        self._create_widgets()
        
        # Bind resize event for scaling
        self.root.bind("<Configure>", self._on_resize)
        
        # Bind Enter key to start/stop session
        self.root.bind("<Return>", self._on_enter_key)
        
        # Check usage limit status
        self.root.after(200, self._check_usage_limit)
        
        # Update timer periodically
        self._update_timer()
        
        # Update usage display periodically
        self._update_usage_display()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Bring window to front on launch (no special permissions needed)
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))
        self.root.focus_force()
    
    def _set_macos_light_mode(self):
        """
        Set the window appearance to light mode on macOS.
        
        This makes the title bar white instead of dark, matching the light theme.
        Uses PyObjC if available.
        """
        try:
            from AppKit import NSApplication, NSAppearance  # type: ignore[import-not-found]
            
            # Get the shared application instance
            app = NSApplication.sharedApplication()
            
            # Create light mode (Aqua) appearance and apply it
            # 'NSAppearanceNameAqua' is the light mode appearance
            appearance = NSAppearance.appearanceNamed_('NSAppearanceNameAqua')
            app.setAppearance_(appearance)
            
            logger.debug("Set macOS appearance to light mode via PyObjC")
        except ImportError:
            logger.debug("PyObjC not available - title bar will follow system theme")
        except Exception as e:
            logger.debug(f"Could not set macOS light mode: {e}")
    
    def _create_fonts(self, scale: float = None):
        """
        Create custom fonts for the UI with scalable sizes.
        
        Args:
            scale: Optional scale factor. If None, uses current_scale.
        """
        if scale is None:
            scale = self.current_scale
        
        # Seraphic Design Fonts
        font_display = "Georgia"
        font_interface = "Helvetica"
        
        # Helper to get scaled font size with bounds
        def get_scaled_size(font_key: str) -> int:
            base_size, min_size, max_size = FONT_BOUNDS.get(font_key, (14, 11, 18))
            scaled = int(base_size * scale)
            return max(min_size, min(scaled, max_size))
        
        self.font_title = tkfont.Font(
            family=font_display, size=get_scaled_size("title"), weight="bold"
        )
        
        self.font_stat = tkfont.Font(
            family=font_display, size=get_scaled_size("stat"), weight="bold"
        )
        
        self.font_timer = tkfont.Font(
            family=font_display, size=get_scaled_size("timer"), weight="bold"
        )
        
        self.font_status = tkfont.Font(
            family=font_interface, size=get_scaled_size("status"), weight="bold"
        )
        
        self.font_button = tkfont.Font(
            family=font_interface, size=get_scaled_size("button"), weight="bold"
        )
        
        self.font_small = tkfont.Font(
            family=font_interface, size=get_scaled_size("small"), weight="normal"
        )
        
        self.font_badge = tkfont.Font(
            family=font_interface, size=get_scaled_size("badge"), weight="bold"
        )
        
        self.font_caption = tkfont.Font(
            family=font_interface, size=get_scaled_size("caption"), weight="bold"
        )
        
        self.font_body = tkfont.Font(
            family=font_interface, size=get_scaled_size("body"), weight="normal"
        )
    
    
    def _on_resize(self, event):
        """
        Handle window resize event - scale UI components proportionally.
        
        Scales fonts, buttons, padding, and other UI elements based on
        window dimensions while maintaining minimum readable sizes.
        
        Args:
            event: Configure event with new dimensions
        """
        # Only respond to root window resize
        if event.widget != self.root:
            return
        
        # Check if size actually changed
        if event.width == self._last_width and event.height == self._last_height:
            return
        
        self._last_width = event.width
        self._last_height = event.height
        
        # Calculate scale based on both dimensions
        new_scale = self.scaling_manager.calculate_scale(event.width, event.height)
        
        # Update the scaling manager's scale for popup sizing
        self.scaling_manager.set_scale(new_scale)
        
        # Use smaller threshold (3%) for smoother scaling transitions
        if abs(new_scale - self.current_scale) > 0.03:
            self.current_scale = new_scale
            
            # Recreate fonts with new scale
            self._create_fonts(new_scale)
            
            # Scale buttons proportionally (but keep minimum size)
            new_btn_width = max(UI_BUTTON_MIN_WIDTH, int(UI_BUTTON_WIDTH * new_scale))
            new_btn_height = max(UI_BUTTON_MIN_HEIGHT, int(UI_BUTTON_HEIGHT * new_scale))
            
            if hasattr(self, 'start_stop_btn'):
                self.start_stop_btn.configure(width=new_btn_width, height=new_btn_height)
            
            if hasattr(self, 'pause_btn'):
                self.pause_btn.configure(width=new_btn_width, height=new_btn_height)
            
            # Scale icon buttons
            new_icon_size = max(56, int(64 * new_scale))
            if hasattr(self, 'settings_icon_btn'):
                self.settings_icon_btn.configure(size=new_icon_size)
            if hasattr(self, 'tutorial_icon_btn'):
                self.tutorial_icon_btn.configure(size=new_icon_size)
            
            # Scale camera card dimensions
            if hasattr(self, 'camera_card'):
                new_camera_width = max(UI_CAMERA_CARD_MIN_WIDTH, int(UI_CAMERA_CARD_WIDTH * new_scale))
                new_camera_height = max(UI_CAMERA_CARD_MIN_HEIGHT, int(UI_CAMERA_CARD_HEIGHT * new_scale))
                self.camera_card.configure(width=new_camera_width, height=new_camera_height)
                self.camera_card.draw()
            
            # Scale stat cards BEFORE applying fonts (so card["width"] is correct)
            if hasattr(self, 'stat_cards'):
                for card_type, card_data in self.stat_cards.items():
                    if 'card' in card_data:
                        new_card_width = max(UI_STAT_CARD_MIN_WIDTH, int(UI_STAT_CARD_WIDTH * new_scale))
                        new_card_height = max(UI_STAT_CARD_MIN_HEIGHT, int(UI_STAT_CARD_HEIGHT * new_scale))
                        card_data['card'].configure(width=new_card_width, height=new_card_height)
                        # Don't call draw() here - _apply_scaled_fonts() will handle drawing and text creation
            
            # Apply scaled fonts to UI elements (creates stat card text with correct positions)
            self._apply_scaled_fonts()
    
    def _apply_scaled_fonts(self):
        """Apply the scaled fonts to all UI elements that use them."""
        # Update timer label font
        if hasattr(self, 'timer_label'):
            self.timer_label.configure(font=self.font_timer)
        
        # Update timer sub label font
        if hasattr(self, 'timer_sub_label'):
            self.timer_sub_label.configure(font=self.font_caption)
        
        # Update time badge font
        if hasattr(self, 'time_badge'):
            self.time_badge.configure_badge(font=self.font_badge)
        
        # Update camera card status text font
        if hasattr(self, 'camera_card'):
            self.camera_card.font = self.font_status
            self.camera_card.draw()
        
        # Update stat cards fonts
        if hasattr(self, 'stat_cards'):
            for card_type, card_data in self.stat_cards.items():
                if 'card' in card_data:
                    # Redraw card with new fonts
                    card = card_data['card']
                    card.delete("all")
                    card.draw()
                    
                    # Re-create text elements with scaled fonts
                    # Card body has asymmetric padding (2px left, 6px right), so visual center is offset by -2
                    center_x = (int(card["width"]) // 2) - 2
                    
                    # Get title and value based on card type
                    if card_type == "focus":
                        title = "Today's Focus"
                    elif card_type == "distractions":
                        title = "Today's Distractions"
                    else:
                        title = "Today's Focus Rate"
                    
                    # Title
                    card.create_text(
                        center_x, int(30 * self.current_scale), 
                        text=title, 
                        anchor="center", 
                        font=self.font_caption, 
                        fill=COLORS["text_secondary"]
                    )
                    
                    # Main value - store item ID for updates
                    card_data["main"] = card.create_text(
                        center_x, int(72 * self.current_scale), 
                        text="0 sec" if card_type != "rate" else "0%", 
                        anchor="center", 
                        font=self.font_stat, 
                        fill=COLORS["text_primary"]
                    )
    
    def _get_current_status_color(self) -> str:
        """Get the color for the current status."""
        color_map = {
            "idle": COLORS["status_idle"],
            "focused": COLORS["status_focused"],
            "booting": COLORS["status_focused"],  # Green text for booting
            "away": COLORS["status_away"],
            "gadget": COLORS["status_gadget"],
            "screen": COLORS["status_screen"],
            "paused": COLORS["status_paused"],
        }
        return color_map.get(self.current_status, COLORS["status_idle"])
    
    def _get_status_bg_color(self, status: str) -> str:
        """Get the background color for a status (lighter tint of status color)."""
        bg_map = {
            "idle": COLORS["bg_tertiary"],           # Keep grey for idle
            "focused": COLORS["status_focused_bg"],  # Light green
            "booting": COLORS["bg_tertiary"],        # Keep grey for booting
            "away": COLORS["status_away_bg"],        # Light amber
            "gadget": COLORS["status_gadget_bg"],    # Light red
            "screen": COLORS["status_screen_bg"],    # Light purple
            "paused": COLORS["bg_tertiary"],         # Keep grey for paused
        }
        return bg_map.get(status, COLORS["bg_tertiary"])
    
    def _create_widgets(self):
        """Create all UI widgets with scalable layout."""
        # --- Header (Directly in root for corner positioning) ---
        header_frame = tk.Frame(self.root, bg=COLORS["bg_primary"])
        # Reduced padding to move elements closer to corners
        header_frame.pack(fill=tk.X, padx=20, pady=20, side=tk.TOP)

        # Logo (Left)
        logo_frame = tk.Frame(header_frame, bg=COLORS["bg_primary"])
        logo_frame.pack(side=tk.LEFT, anchor="nw", padx=(0, 0))
        
        if PIL_AVAILABLE:
            logo_path = ASSETS_DIR / "logo_with_text.png"
            if logo_path.exists():
                try:
                    img = Image.open(logo_path)
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    
                    # Resize keeping aspect ratio (height 32 - smaller for corner)
                    aspect = img.width / img.height
                    target_height = 32
                    target_width = int(target_height * aspect)
                    img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                    
                    self.logo_image = ImageTk.PhotoImage(img)
                    self.logo_label = tk.Label(header_frame, image=self.logo_image, bg=COLORS["bg_primary"])
                    self.logo_label.pack(side=tk.LEFT)
                except Exception as e:
                    logger.warning(f"Could not load logo: {e}")
                    tk.Label(header_frame, text="BrainDock", font=self.font_title, bg=COLORS["bg_primary"], fg=COLORS["text_primary"]).pack(side=tk.LEFT)
            else:
                tk.Label(header_frame, text="BrainDock", font=self.font_title, bg=COLORS["bg_primary"], fg=COLORS["text_primary"]).pack(side=tk.LEFT)
        else:
            tk.Label(header_frame, text="BrainDock", font=self.font_title, bg=COLORS["bg_primary"], fg=COLORS["text_primary"]).pack(side=tk.LEFT)

        # Usage Badge (Right)
        # Initialize with default time limit, will be updated shortly after
        initial_time = self.usage_limiter.format_time(self.usage_limiter.get_remaining_seconds())
        self.time_badge = Badge(header_frame, text=initial_time, bg_color=COLORS["bg_tertiary"], fg_color=COLORS["text_secondary"], font=self.font_badge, clickable=True)
        self.time_badge.pack(side=tk.RIGHT, anchor="ne")
        self.time_badge.bind_click(self._show_usage_details)

        # --- Main Container ---
        # Using a frame that expands to fill space between header and footer
        main_container = tk.Frame(self.root, bg=COLORS["bg_primary"])
        main_container.pack(expand=True, fill="both", padx=40)
        # Keep legacy reference for overlays
        self.main_frame = main_container

        # Content Centering Frame
        self.content_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        self.content_frame.place(relx=0.5, rely=0.55, anchor="center")

        # --- Split Layout ---
        # Left Panel: Stats (Hidden during session)
        self.stats_container = tk.Frame(self.content_frame, bg=COLORS["bg_primary"])
        self.stats_container.pack(side=tk.LEFT, padx=(0, 40), anchor="n")
        
        # Right Panel: Controls (Always visible, centers when stats hidden)
        self.controls_container = tk.Frame(self.content_frame, bg=COLORS["bg_primary"])
        self.controls_container.pack(side=tk.LEFT, anchor="n")

        # Initialize stat cards dictionary
        self.stat_cards = {}

        # Create structured stat cards in Left Panel (Vertical Stack)
        # Order: Focus, Distractions, Rate (at bottom)
        self._create_stat_card(self.stats_container, 0, "focus")
        self._create_stat_card(self.stats_container, 0, "distractions")
        self._create_stat_card(self.stats_container, 0, "rate")
        
        # Initialize stat cards with today's accumulated values
        self._init_daily_stat_cards()

        # --- Controls Panel Content ---
        
        # Camera Preview Card
        camera_container = tk.Frame(self.controls_container, bg=COLORS["bg_primary"])
        camera_container.pack(pady=(0, self.scaling_manager.scale_padding(40)))
        
        # Camera card now acts as the status display
        # Scale dimensions based on current scale
        camera_width = max(UI_CAMERA_CARD_MIN_WIDTH, int(UI_CAMERA_CARD_WIDTH * self.current_scale))
        camera_height = max(UI_CAMERA_CARD_MIN_HEIGHT, int(UI_CAMERA_CARD_HEIGHT * self.current_scale))
        self.camera_card = Card(
            camera_container, 
            width=camera_width, 
            height=camera_height, 
            bg_color=COLORS["bg_tertiary"],
            text="Ready to Start",
            text_color=COLORS["status_idle"],
            font=self.font_status
        )
        self.camera_card.pack()
        
        # Timer Section
        timer_frame = tk.Frame(self.controls_container, bg=COLORS["bg_primary"])
        timer_frame.pack(pady=(0, 10))

        self.timer_label = tk.Label(timer_frame, text="00:00:00", font=self.font_timer, bg=COLORS["bg_primary"], fg=COLORS["text_primary"], width=10)
        self.timer_label.pack()
        
        self.timer_sub_label = tk.Label(
            timer_frame,
            text="Session Duration",
            font=self.font_caption,
            bg=COLORS["bg_primary"],
            fg=COLORS["text_secondary"]
        )
        self.timer_sub_label.pack(pady=(12, 40))

        # Start Button - scale dimensions based on current scale
        btn_width = max(UI_BUTTON_MIN_WIDTH, int(UI_BUTTON_WIDTH * self.current_scale))
        btn_height = max(UI_BUTTON_MIN_HEIGHT, int(UI_BUTTON_HEIGHT * self.current_scale))
        self.start_stop_btn = RoundedButton(
            timer_frame,
            text="Start Session",
            width=btn_width,
            height=btn_height,
            bg_color=COLORS["button_start"],
            hover_color=COLORS["status_focused"],  # Green hover
            text_color="#FFFFFF",
            font=self.font_button,
            command=self._toggle_session
        )
        self.start_stop_btn.pack(pady=self.scaling_manager.scale_padding(10))
        
        # Pause button (hidden initially)
        self.pause_btn = RoundedButton(
            timer_frame,
            text="Pause Session",
            width=btn_width,
            height=btn_height,
            bg_color=COLORS["button_pause"],
            text_color="#FFFFFF",
            font=self.font_button,
            command=self._toggle_pause
        )
        # Don't pack it yet

        # Mode Toggles
        self._create_mode_selector(timer_frame)

        # --- Footer (Fixed at bottom) ---
        # Icon buttons in corners: settings (left), tutorial (right)
        footer_frame = tk.Frame(self.root, bg=COLORS["bg_primary"])
        # Position icons closer to bottom corners
        footer_frame.pack(side=tk.BOTTOM, pady=20, fill="x", padx=20)
        
        # Scale icon size based on current scale
        icon_size = max(56, int(64 * self.current_scale))
        
        # Settings icon (bottom left)
        settings_icon_path = str(config.BASE_DIR / "assets" / "settings_icon.png")
        self.settings_icon_btn = IconButton(
            footer_frame,
            icon_type="settings",
            command=self._show_blocklist_settings,
            size=icon_size,
            bg_color=COLORS.get("bg_primary", "#F9F8F4"),
            hover_color="#E0E0E0",  # Darker grey for hover
            icon_color=COLORS.get("text_secondary", "#8E8E93"),
            corner_radius=12,  # Slightly rounder for larger size
            image_path=settings_icon_path
        )
        self.settings_icon_btn.pack(side=tk.LEFT, anchor="sw")
        
        # Tutorial icon (bottom right)
        tutorial_icon_path = str(config.BASE_DIR / "assets" / "tutorial_icon.png")
        self.tutorial_icon_btn = IconButton(
            footer_frame,
            icon_type="tutorial",
            command=self._show_tutorial,
            size=icon_size,
            bg_color=COLORS.get("bg_primary", "#F9F8F4"),
            hover_color="#E0E0E0",  # Darker grey for hover
            icon_color=COLORS.get("text_secondary", "#8E8E93"),
            corner_radius=12,  # Slightly rounder for larger size
            image_path=tutorial_icon_path
        )
        self.tutorial_icon_btn.pack(side=tk.RIGHT, anchor="se")
        
        # Status Badge removed - integrated into camera card


    def _create_stat_card(self, parent, col, card_type):
        """Create a minimal stat card with just title and value."""
        wrapper = tk.Frame(parent, bg=COLORS["bg_primary"])
        # Use pack for vertical stacking in stats_container
        wrapper.pack(pady=self.scaling_manager.scale_padding(5))
        
        # Compact card dimensions - scale based on current scale
        card_width = max(UI_STAT_CARD_MIN_WIDTH, int(UI_STAT_CARD_WIDTH * self.current_scale))
        card_height = max(UI_STAT_CARD_MIN_HEIGHT, int(UI_STAT_CARD_HEIGHT * self.current_scale))
        # Card body has asymmetric padding (2px left, 6px right), so visual center is offset by -2
        center_x = (card_width // 2) - 2
        
        card = Card(wrapper, width=card_width, height=card_height)
        card.pack()
        
        # Initialize storage for this card type
        self.stat_cards[card_type] = {"card": card, "wrapper": wrapper}
        
        if card_type == "focus":
            title = "Today's Focus"
            main_val = "0 sec"
            sub_label = "Focused"
            sub_val = "0 sec"
        elif card_type == "distractions":
            title = "Today's Distractions"
            main_val = "0 sec"
            sub_label = "Total"
            sub_val = "0 sec"
        else:  # rate
            title = "Today's Focus Rate"
            main_val = "0%"
            sub_label = ""
            sub_val = ""
        
        # Title (Centered at top) - scale y-position to match card dimensions
        card.create_text(center_x, int(30 * self.current_scale), text=title, anchor="center", font=self.font_caption, fill=COLORS["text_secondary"])
        
        # Main Value (Large, centered) - scale y-position to match card dimensions
        self.stat_cards[card_type]["main"] = card.create_text(
            center_x, int(72 * self.current_scale), text=main_val, anchor="center", font=self.font_stat, fill=COLORS["text_primary"]
        )

    def _init_daily_stat_cards(self):
        """
        Initialize stat cards with today's accumulated values on app startup.
        
        Shows the daily totals from previous sessions today when the app first opens.
        """
        # Get today's accumulated stats
        daily_focus = self.daily_stats.get_focus_seconds()
        daily_distraction = self.daily_stats.get_distraction_seconds()
        daily_rate = self.daily_stats.get_focus_rate()
        
        # Update Focus Card
        if "focus" in self.stat_cards:
            card = self.stat_cards["focus"]["card"]
            card.itemconfigure(self.stat_cards["focus"]["main"], text=format_stat_time(daily_focus))
        
        # Update Distractions Card
        if "distractions" in self.stat_cards:
            card = self.stat_cards["distractions"]["card"]
            card.itemconfigure(self.stat_cards["distractions"]["main"], text=format_stat_time(daily_distraction))
        
        # Update Focus Rate Card
        if "rate" in self.stat_cards:
            card = self.stat_cards["rate"]["card"]
            card.itemconfigure(self.stat_cards["rate"]["main"], text=f"{int(daily_rate)}%")

    def _update_stat_cards(self):
        """
        Update stat card values with TODAY's total stats.
        
        Combines daily accumulated stats (from previous sessions today) 
        with current session's ongoing stats to show daily totals.
        """
        if not self.session or not self.session_started:
            return
            
        # Get current session stats
        current_time = datetime.now()
        events = list(self.session.events)
        
        # Add current ongoing event if exists
        if self.session.current_state and self.session.state_start_time:
            duration = (current_time - self.session.state_start_time).total_seconds()
            events.append({
                "type": self.session.current_state,
                "start": self.session.state_start_time.isoformat(),
                "end": current_time.isoformat(),
                "duration_seconds": duration
            })
            
        # Calculate total duration for current session
        if self.session.start_time:
            total_duration = (current_time - self.session.start_time).total_seconds()
        else:
            total_duration = 0
            
        # Compute current session stats
        session_stats = compute_statistics(events, total_duration)
        
        # Get current session values
        session_focus = session_stats["present_seconds"]
        session_away = session_stats["away_seconds"]
        session_gadget = session_stats["gadget_seconds"]
        session_screen = session_stats.get("screen_distraction_seconds", 0)
        session_distraction = session_away + session_gadget + session_screen
        
        # Get today's accumulated stats (from previous sessions)
        daily_stats = self.daily_stats.get_daily_stats()
        daily_focus = daily_stats["focus_seconds"]
        daily_distraction = daily_stats["distraction_seconds"]
        
        # Calculate TODAY's totals (daily accumulated + current session)
        today_focus = daily_focus + session_focus
        today_distraction = daily_distraction + session_distraction
        today_total_active = today_focus + today_distraction
        
        # Calculate TODAY's focus rate: focus / (focus + distractions) * 100
        # Paused time is NOT included in either value
        if today_total_active > 0:
            today_focus_rate = (today_focus / today_total_active) * 100.0
        else:
            today_focus_rate = 0.0
        
        # --- Update Focus Card (TODAY's total focused time) ---
        if "focus" in self.stat_cards:
            card_data = self.stat_cards["focus"]
            card = card_data["card"]
            card.itemconfigure(card_data["main"], text=format_stat_time(today_focus))
            
        # --- Update Distractions Card (TODAY's total: away + gadget + screen) ---
        if "distractions" in self.stat_cards:
            card_data = self.stat_cards["distractions"]
            card = card_data["card"]
            card.itemconfigure(card_data["main"], text=format_stat_time(today_distraction))

        # --- Update Focus Rate Card (TODAY's rate) ---
        if "rate" in self.stat_cards:
            card_data = self.stat_cards["rate"]
            card = card_data["card"]
            card.itemconfigure(card_data["main"], text=f"{int(today_focus_rate)}%")
    
    def _reset_stat_cards(self):
        """
        Reset stat cards to show today's accumulated totals (before current session).
        
        Called when starting a new session. Shows what's already accumulated today
        from previous sessions, which will then be updated with current session progress.
        """
        # Get today's accumulated stats (from previous sessions)
        daily_focus = self.daily_stats.get_focus_seconds()
        daily_distraction = self.daily_stats.get_distraction_seconds()
        daily_rate = self.daily_stats.get_focus_rate()
        
        if "focus" in self.stat_cards:
            card = self.stat_cards["focus"]["card"]
            card.itemconfigure(self.stat_cards["focus"]["main"], text=format_stat_time(daily_focus))
        
        if "distractions" in self.stat_cards:
            card = self.stat_cards["distractions"]["card"]
            card.itemconfigure(self.stat_cards["distractions"]["main"], text=format_stat_time(daily_distraction))
        
        if "rate" in self.stat_cards:
            card = self.stat_cards["rate"]["card"]
            card.itemconfigure(self.stat_cards["rate"]["main"], text=f"{int(daily_rate)}%")
    
    def _finalize_stat_cards(self):
        """
        Save session stats to daily totals and update stat cards.
        
        Called when a session ends. Saves this session's stats to the daily
        tracker, then displays the new daily totals.
        """
        if not self.session or not self.session_started:
            return
        
        # Compute final session stats from events
        events = list(self.session.events)
        total_duration = self.session.get_duration()
        stats = compute_statistics(events, total_duration)
        
        # Get session values (floats for full precision - truncation at display time only)
        session_focus = float(stats["present_seconds"])
        session_away = float(stats["away_seconds"])
        session_gadget = float(stats["gadget_seconds"])
        session_screen = float(stats.get("screen_distraction_seconds", 0))
        
        # Save this session's stats to daily totals (floats for precision)
        # This accumulates today's progress across all sessions
        self.daily_stats.add_session_stats(
            focus_seconds=session_focus,
            away_seconds=session_away,
            gadget_seconds=session_gadget,
            screen_distraction_seconds=session_screen
        )
        
        # Get the new daily totals (now includes this session)
        daily_focus = self.daily_stats.get_focus_seconds()
        daily_distraction = self.daily_stats.get_distraction_seconds()
        daily_focus_rate = self.daily_stats.get_focus_rate()
        
        # Update stat cards with TODAY's totals
        if "focus" in self.stat_cards:
            card = self.stat_cards["focus"]["card"]
            card.itemconfigure(self.stat_cards["focus"]["main"], text=format_stat_time(daily_focus))
        
        if "distractions" in self.stat_cards:
            card = self.stat_cards["distractions"]["card"]
            card.itemconfigure(self.stat_cards["distractions"]["main"], text=format_stat_time(daily_distraction))
        
        if "rate" in self.stat_cards:
            card = self.stat_cards["rate"]["card"]
            card.itemconfigure(self.stat_cards["rate"]["main"], text=f"{int(daily_focus_rate)}%")
        
        logger.info(f"Session saved to daily stats. Today's totals: "
                   f"Focus={format_stat_time(daily_focus)}, Distractions={format_stat_time(daily_distraction)}, "
                   f"Rate={int(daily_focus_rate)}%")
    
    def _create_mode_selector(self, parent=None):
        """
        Create the monitoring mode selector UI.
        
        Allows users to choose between Camera Only, Screen Only, or Both modes.
        """
        # Mode selector container
        # If parent is provided, use it, otherwise use main_frame (legacy support)
        target_parent = parent if parent else self.main_frame
        
        self.mode_frame = tk.Frame(target_parent, bg=COLORS["bg_primary"])
        if parent:
            self._mode_frame_manager = "pack"
            self._mode_frame_pack_opts = {"pady": 20}
            self.mode_frame.pack(**self._mode_frame_pack_opts)
        else:
            self._mode_frame_manager = "grid"
            self._mode_frame_grid_opts = {"row": 8, "column": 0, "sticky": "ew", "pady": (25, 0)}
            self.mode_frame.grid(**self._mode_frame_grid_opts)
        
        # Mode buttons container
        mode_buttons_frame = tk.Frame(self.mode_frame, bg=COLORS["bg_primary"])
        mode_buttons_frame.pack()
        
        # Create mode toggle buttons
        self.mode_var = tk.StringVar(value=config.MODE_CAMERA_ONLY)
        
        modes = [
            (config.MODE_CAMERA_ONLY, "Camera"),
            (config.MODE_SCREEN_ONLY, "Screen"),
            (config.MODE_BOTH, "Both"),
        ]
        
        self.mode_buttons = {}
        for mode_id, mode_text in modes:
            # Seraphic style: Simple text labels
            is_selected = mode_id == self.monitoring_mode
            
            # Use Label acting as button
            btn = tk.Label(
                mode_buttons_frame,
                text=mode_text,
                font=self.font_caption if is_selected else self.font_small,
                fg=COLORS["text_primary"] if is_selected else COLORS["text_secondary"],
                bg=COLORS["bg_primary"]
            )
            btn.pack(side=tk.LEFT, padx=15)
            btn.bind("<Button-1>", lambda e, m=mode_id: self._set_monitoring_mode(m))
            
            # Add hover effects
            btn.bind("<Enter>", lambda e, b=btn, m=mode_id: self._on_mode_hover(b, m, True))
            btn.bind("<Leave>", lambda e, b=btn, m=mode_id: self._on_mode_hover(b, m, False))
            
            self.mode_buttons[mode_id] = btn

    def _on_mode_hover(self, btn, mode_id, entering):
        """Handle hover effect for mode buttons."""
        is_selected = (mode_id == self.monitoring_mode)
        
        # Determine base font
        base_font = self.font_caption if is_selected else self.font_small
        
        family = base_font.cget("family")
        size = base_font.cget("size")
        weight = base_font.cget("weight")
        
        if entering:
            # Underline on hover
            new_font = (family, size, weight, "underline")
            # Also darken text if not selected
            if not is_selected:
                btn.configure(fg=COLORS["text_primary"])
        else:
            # Normal on leave
            new_font = base_font
            # Restore color if not selected
            if not is_selected:
                btn.configure(fg=COLORS["text_secondary"])
                
        btn.configure(font=new_font)

    def _hide_mode_selector(self):
        """Hide mode selector during active sessions."""
        if not hasattr(self, "mode_frame"):
            return
        manager = self.mode_frame.winfo_manager()
        if manager == "pack" or self._mode_frame_manager == "pack":
            self.mode_frame.pack_forget()
        elif manager == "grid" or self._mode_frame_manager == "grid":
            self.mode_frame.grid_remove()

    def _show_mode_selector(self):
        """Show mode selector when session is stopped."""
        if not hasattr(self, "mode_frame"):
            return
        if self._mode_frame_manager == "pack":
            pack_opts = getattr(self, "_mode_frame_pack_opts", {"pady": 20})
            self.mode_frame.pack(**pack_opts)
        elif self._mode_frame_manager == "grid":
            grid_opts = getattr(self, "_mode_frame_grid_opts", {"row": 8, "column": 0, "sticky": "ew", "pady": (25, 0)})
            self.mode_frame.grid(**grid_opts)
    
    def _set_monitoring_mode(self, mode: str):
        """
        Set the monitoring mode.
        
        Args:
            mode: One of MODE_CAMERA_ONLY, MODE_SCREEN_ONLY, or MODE_BOTH
        """
        # Don't change mode while session is running
        if self.is_running:
            messagebox.showwarning(
                "Session Active",
                "Cannot change monitoring mode while a session is running.\n"
                "Please stop the current session first."
            )
            return
        
        self.monitoring_mode = mode
        self.mode_var.set(mode)
        
        # Update button visuals
        for mode_id, btn in self.mode_buttons.items():
            if mode_id == mode:
                btn.configure(
                    fg=COLORS["text_primary"],
                    font=self.font_caption
                )
            else:
                btn.configure(
                    fg=COLORS["text_secondary"],
                    font=self.font_small
                )
        
        logger.info(f"Monitoring mode set to: {mode}")
    
    def _show_blocklist_settings(self):
        """
        Show the blocklist settings dialog.
        
        Allows users to enable/disable quick block sites and add custom patterns.
        Uses scrolling for content with fixed buttons at the bottom.
        """
        # Create settings window - scale based on current main window size
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Screen Settings")
        settings_window.configure(bg=COLORS["bg_primary"])
        
        # Scale popup size based on the main window's current size
        # Use 85% of main window dimensions, with reasonable min/max bounds
        main_width = self.root.winfo_width()
        main_height = self.root.winfo_height()
        
        popup_width = max(380, min(550, int(main_width * 0.85)))
        popup_height = max(450, min(750, int(main_height * 0.85)))
        
        settings_window.geometry(f"{popup_width}x{popup_height}")
        settings_window.resizable(True, True)
        settings_window.minsize(380, 450)
        
        # Center on parent window
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - popup_width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - popup_height) // 2
        settings_window.geometry(f"+{x}+{y}")
        
        # Main container - holds scrollable area and fixed buttons
        main_container = tk.Frame(settings_window, bg=COLORS["bg_primary"])
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # --- Scrollable content area ---
        # Create canvas with scrollbar for the content
        canvas_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(20, 0))
        
        canvas = tk.Canvas(canvas_frame, bg=COLORS["bg_primary"], highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        
        # Scrollable frame inside canvas
        scrollable_frame = tk.Frame(canvas, bg=COLORS["bg_primary"])
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Make scrollable frame expand to canvas width
        def configure_canvas_width(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", configure_canvas_width)
        
        # Enable smooth mousewheel scrolling (same approach as tutorial popup)
        def _on_mousewheel(event):
            if sys.platform == "darwin":
                # macOS: delta is typically small integers, scroll proportionally
                # Negative delta = scroll down, positive = scroll up
                scroll_amount = -event.delta * 0.01  # Small fraction for smooth scroll
            else:
                # Windows/Linux: delta is typically 120 per notch
                scroll_amount = -event.delta / 120 * 0.05  # Smooth scroll factor
            
            # Get current position and adjust
            current_pos = canvas.yview()[0]
            new_pos = max(0, min(1, current_pos + scroll_amount))
            canvas.yview_moveto(new_pos)
        
        # Bind mousewheel to canvas and scrollable frame
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # Helper to bind mousewheel to all child widgets
        def _bind_mousewheel_to_children(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel_to_children(child)
        
        # Pack canvas and scrollbar
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # --- Content inside scrollable frame ---
        content_padding = tk.Frame(scrollable_frame, bg=COLORS["bg_primary"])
        content_padding.pack(fill=tk.BOTH, expand=True, padx=20)
        
        # Title
        title = tk.Label(
            content_padding,
            text="Screen Settings",
            font=self.font_title,
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_primary"]
        )
        title.pack(pady=(0, 5))
        
        subtitle = tk.Label(
            content_padding,
            text="Configure which sites/apps to notify you about",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        subtitle.pack(pady=(0, 20))
        
        # Quick Select section
        quick_sites_label = tk.Label(
            content_padding,
            text="Quick Select",
            font=("Helvetica", 16, "bold"),
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        quick_sites_label.pack(anchor="w", pady=(0, 10))
        
        # Quick site toggles - two-column layout
        self.quick_site_vars = {}
        quick_sites_frame = tk.Frame(content_padding, bg=COLORS["bg_primary"])
        quick_sites_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Configure two columns with equal weight
        quick_sites_frame.columnconfigure(0, weight=1)
        quick_sites_frame.columnconfigure(1, weight=1)
        
        # Define site order for two-column layout
        # Column 1: instagram, netflix, tiktok
        # Column 2: youtube, reddit, twitter
        site_order = [
            ("instagram", 0, 0),  # (site_id, row, column)
            ("youtube", 0, 1),
            ("netflix", 1, 0),
            ("reddit", 1, 1),
            ("tiktok", 2, 0),
            ("twitter", 2, 1),
        ]
        
        for site_id, row, col in site_order:
            if site_id not in QUICK_SITES:
                continue
            site_data = QUICK_SITES[site_id]
            var = tk.BooleanVar(value=site_id in self.blocklist.enabled_quick_sites)
            self.quick_site_vars[site_id] = var
            
            cb = tk.Checkbutton(
                quick_sites_frame,
                text=site_data["name"],
                variable=var,
                font=("Helvetica", 14),
                fg=COLORS["text_primary"],
                bg=COLORS["bg_primary"],
                selectcolor=COLORS["bg_secondary"],
                activebackground=COLORS["bg_primary"],
                activeforeground=COLORS["text_primary"],
                command=lambda s=site_id, v=var: self._toggle_quick_site(s, v.get())
            )
            cb.grid(row=row, column=col, sticky="w", pady=3, padx=(0, 20))
        
        # --- Custom URLs section ---
        urls_label = tk.Label(
            content_padding,
            text="Custom URLs/Domains",
            font=("Helvetica", 16, "bold"),
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        urls_label.pack(anchor="w", pady=(10, 5))
        
        urls_help = tk.Label(
            content_padding,
            text="Add website URLs to notify you about (e.g., example.com)",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        urls_help.pack(anchor="w", pady=(0, 5))
        
        # URLs text area
        urls_frame = tk.Frame(content_padding, bg=COLORS["bg_secondary"], padx=1, pady=1)
        urls_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.custom_urls_text = tk.Text(
            urls_frame,
            font=self.font_small,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_secondary"],
            insertbackground=COLORS["text_primary"],
            height=3,
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=10,
            pady=10
        )
        self.custom_urls_text.pack(fill=tk.X)
        
        # URL validation status label
        self.url_validation_label = tk.Label(
            content_padding,
            text="",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"],
        )
        self.url_validation_label.pack(anchor="w")
        self.url_validation_tooltip = Tooltip(self.url_validation_label, "")
        
        # Populate with current custom URLs
        if self.blocklist.custom_urls:
            self.custom_urls_text.insert("1.0", "\n".join(self.blocklist.custom_urls))
        
        # --- Custom Apps section ---
        apps_label = tk.Label(
            content_padding,
            text="Custom App Names",
            font=("Helvetica", 16, "bold"),
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        apps_label.pack(anchor="w", pady=(15, 5))
        
        apps_help = tk.Label(
            content_padding,
            text="Add desktop app names to notify you about (e.g., Steam, Discord)",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        apps_help.pack(anchor="w", pady=(0, 5))
        
        # Apps text area
        apps_frame = tk.Frame(content_padding, bg=COLORS["bg_secondary"], padx=1, pady=1)
        apps_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.custom_apps_text = tk.Text(
            apps_frame,
            font=self.font_small,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_secondary"],
            insertbackground=COLORS["text_primary"],
            height=3,
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=10,
            pady=10
        )
        self.custom_apps_text.pack(fill=tk.X)
        
        # App validation status label
        self.app_validation_label = tk.Label(
            content_padding,
            text="",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"],
        )
        self.app_validation_label.pack(anchor="w")
        self.app_validation_tooltip = Tooltip(self.app_validation_label, "")
        
        # Populate with current custom apps
        if self.blocklist.custom_apps:
            self.custom_apps_text.insert("1.0", "\n".join(self.blocklist.custom_apps))
        
        # Bind validation on text change
        self.custom_urls_text.bind("<KeyRelease>", lambda e: self._validate_urls_realtime())
        self.custom_apps_text.bind("<KeyRelease>", lambda e: self._validate_apps_realtime())
        
        # AI Fallback option
        ai_frame = tk.Frame(content_padding, bg=COLORS["bg_primary"])
        ai_frame.pack(fill=tk.X, pady=(15, 20))
        
        self.ai_fallback_var = tk.BooleanVar(value=self.use_ai_fallback)
        ai_cb = tk.Checkbutton(
            ai_frame,
            text="Enable AI Screenshot Analysis (disabled by default)",
            variable=self.ai_fallback_var,
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"],
            selectcolor=COLORS["bg_secondary"],
            activebackground=COLORS["bg_primary"],
            activeforeground=COLORS["text_secondary"],
        )
        ai_cb.pack(anchor="w")
        
        ai_help = tk.Label(
            ai_frame,
            text="⚠️ Takes screenshots - only use if default screen sharing fails",
            font=self.font_small,
            fg=COLORS["accent_warm"],
            bg=COLORS["bg_primary"]
        )
        ai_help.pack(anchor="w", padx=(24, 0))
        
        # --- Fixed buttons at bottom (outside scrollable area) ---
        button_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        button_frame.pack(fill=tk.X, pady=(15, 20), padx=40)
        
        # Center the buttons
        button_container = tk.Frame(button_frame, bg=COLORS["bg_primary"])
        button_container.pack()
        
        save_btn = RoundedButton(
            button_container,
            text="Save Settings",
            command=lambda: self._save_blocklist_settings(settings_window),
            bg_color=COLORS["button_start"],
            hover_color=COLORS["button_start_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=10,
            width=160,
            height=48
        )
        save_btn.pack(side=tk.LEFT, padx=(0, 15))
        
        cancel_btn = RoundedButton(
            button_container,
            text="Cancel",
            command=settings_window.destroy,
            bg_color=COLORS["button_pause"],
            hover_color=COLORS["button_pause_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=10,
            width=110,
            height=48
        )
        cancel_btn.pack(side=tk.LEFT)
        
        # Bind mousewheel to all children in scrollable area
        _bind_mousewheel_to_children(scrollable_frame)
        
        # Window close handler
        settings_window.protocol("WM_DELETE_WINDOW", settings_window.destroy)
    
    def _toggle_category(self, category_id: str, enabled: bool):
        """
        Toggle a blocklist category on/off.
        
        Args:
            category_id: The category to toggle
            enabled: Whether to enable or disable
        """
        if enabled:
            self.blocklist.enable_category(category_id)
        else:
            self.blocklist.disable_category(category_id)
    
    def _toggle_quick_site(self, site_id: str, enabled: bool):
        """
        Toggle a quick block site on/off.
        
        Args:
            site_id: The quick site ID to toggle (e.g., "youtube", "instagram")
            enabled: Whether to enable or disable
        """
        if enabled:
            self.blocklist.enable_quick_site(site_id)
        else:
            self.blocklist.disable_quick_site(site_id)
    
    def _show_category_sites(self, category_id: str, cat_data: dict):
        """
        Show a popup with the list of sites in a category.
        
        Args:
            category_id: The category ID
            cat_data: Category data dictionary with patterns
        """
        # Create a small popup window - scale based on screen size
        sites_popup = tk.Toplevel(self.root)
        sites_popup.title(f"{cat_data['name']} Sites")
        sites_popup.configure(bg=COLORS["bg_primary"])
        
        # Calculate scaled popup size based on screen
        popup_width, popup_height = self.scaling_manager.get_popup_size(320, 320)
        sites_popup.geometry(f"{popup_width}x{popup_height}")
        sites_popup.resizable(False, False)
        
        # Center on parent
        sites_popup.transient(self.root)
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - popup_width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - popup_height) // 2
        sites_popup.geometry(f"+{x}+{y}")
        
        # Make modal to ensure proper event handling
        sites_popup.grab_set()
        sites_popup.focus_set()
        
        # Main container
        container = tk.Frame(sites_popup, bg=COLORS["bg_primary"])
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Title
        title = tk.Label(
            container,
            text=cat_data['name'],
            font=self.font_status,
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_primary"]
        )
        title.pack()
        
        desc = tk.Label(
            container,
            text=cat_data.get('description', ''),
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        desc.pack(pady=(0, 10))
        
        # Sites list using a Listbox
        list_frame = tk.Frame(container, bg=COLORS["bg_secondary"], highlightbackground=COLORS["border"], highlightthickness=1)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # Use Listbox for site listing
        sites_listbox = tk.Listbox(
            list_frame,
            font=self.font_small,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_secondary"],
            selectbackground=COLORS["bg_tertiary"],
            selectforeground=COLORS["text_primary"],
            highlightthickness=0,
            bd=0,
            relief=tk.FLAT
        )
        sites_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Insert all sites
        for pattern in cat_data['patterns']:
            sites_listbox.insert(tk.END, f"  • {pattern}")
        
        # Define close function
        def close_popup():
            sites_popup.grab_release()
            sites_popup.destroy()
        
        # Use RoundedButton for consistent styling
        close_btn = RoundedButton(
            container,
            text="Close",
            command=close_popup,
            bg_color=COLORS["button_settings"],
            hover_color=COLORS["button_settings_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_small,
            corner_radius=10,
            padx=24,
            pady=10
        )
        close_btn.pack(pady=(12, 0))
        # Set explicit size for RoundedButton
        close_btn.configure(width=80, height=36)
        
        # Also close on Escape key
        sites_popup.bind("<Escape>", lambda e: close_popup())
    
    # Common TLDs for URL validation (expandable list)
    VALID_TLDS = {
        # Generic TLDs
        'com', 'org', 'net', 'edu', 'gov', 'mil', 'int',
        # Popular newer TLDs
        'io', 'co', 'app', 'dev', 'ai', 'me', 'tv', 'gg', 'xyz', 'info', 'biz',
        'online', 'site', 'tech', 'cloud', 'pro', 'store', 'shop', 'blog',
        # Country codes (common ones)
        'uk', 'us', 'ca', 'au', 'de', 'fr', 'jp', 'cn', 'in', 'br', 'ru',
        'es', 'it', 'nl', 'se', 'no', 'fi', 'dk', 'pl', 'cz', 'at', 'ch',
        'be', 'ie', 'nz', 'za', 'mx', 'ar', 'cl', 'kr', 'tw', 'hk', 'sg',
        # Common compound TLDs
        'co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.in',
    }
    
    # Comprehensive list of known desktop applications for validation
    # Apps in this list are auto-accepted; unknown apps trigger a warning
    KNOWN_APPS = {
        # ==================== GAMING PLATFORMS & LAUNCHERS ====================
        'steam', 'steam client', 'steam client bootstrapper', 'steam client webhelper',
        'epic games', 'epic games launcher', 'epicgameslauncher',
        'gog galaxy', 'gog', 'gog galaxy 2.0',
        'battle.net', 'blizzard battle.net', 'blizzard',
        'origin', 'ea app', 'ea desktop', 'ea play',
        'ubisoft connect', 'uplay', 'ubisoft',
        'xbox', 'xbox app', 'xbox game bar', 'xbox console companion',
        'playstation', 'playstation now', 'ps now', 'ps remote play',
        'rockstar games launcher', 'rockstar launcher', 'social club',
        'riot client', 'riot games',
        'bethesda.net launcher', 'bethesda launcher',
        'amazon games', 'amazon luna',
        'itch.io', 'itch',
        'humble app', 'humble bundle',
        'geforce now', 'nvidia geforce now',
        'parsec', 'moonlight', 'steam link',
        'playnite', 'launchbox', 'gog galaxy',
        
        # ==================== POPULAR PC GAMES (A-Z) ====================
        # A
        'age of empires', 'age of empires ii', 'age of empires iii', 'age of empires iv',
        'alan wake', 'alan wake 2', 'alien isolation',
        'among us', 'amnesia', 'anno 1800', 'anthem',
        'apex legends', 'ark survival evolved', 'ark survival ascended',
        'arma 3', 'armored core vi', 'assassins creed', 'assassin\'s creed',
        'ashes of creation', 'astroneer', 'atlas',
        # B
        'baldurs gate', 'baldur\'s gate', 'baldurs gate 3', 'baldur\'s gate 3',
        'battlefield', 'battlefield 2042', 'battlefield v', 'battlefield 1',
        'beat saber', 'besiege', 'bioshock', 'bioshock infinite',
        'black desert', 'black desert online', 'bdo',
        'black myth wukong', 'blasphemous', 'brawlhalla',
        'borderlands', 'borderlands 3', 'borderlands 2',
        # C
        'call of duty', 'cod', 'warzone', 'warzone 2', 'modern warfare', 'mw2', 'mw3',
        'call of duty black ops', 'black ops', 'cold war',
        'candy crush', 'celeste', 'chivalry 2',
        'cities skylines', 'cities skylines ii', 'cities skylines 2',
        'civilization', 'civilization vi', 'civilization v', 'civ 6', 'civ 5', 'sid meiers civilization',
        'control', 'counter-strike', 'counter strike', 'cs2', 'csgo', 'cs go', 'cs:go',
        'crash bandicoot', 'crysis', 'cuphead', 'cyberpunk', 'cyberpunk 2077',
        # D
        'dark souls', 'dark souls iii', 'dark souls remastered', 'dark souls 3',
        'dayz', 'dead by daylight', 'dead cells', 'dead island', 'dead space',
        'death stranding', 'deep rock galactic', 'destiny', 'destiny 2',
        'detroit become human', 'deus ex', 'devil may cry', 'dmc5',
        'diablo', 'diablo iv', 'diablo iii', 'diablo ii', 'diablo 4', 'diablo 3', 'diablo 2',
        'dirt rally', 'disco elysium', 'dishonored', 'divinity original sin',
        'doom', 'doom eternal', 'dota', 'dota 2', 'dragon age', 'dying light',
        # E
        'elden ring', 'elite dangerous', 'escape from tarkov', 'tarkov',
        'euro truck simulator', 'ets2', 'eve online',
        # F
        'factorio', 'fallout', 'fallout 4', 'fallout 76', 'fallout new vegas',
        'far cry', 'far cry 6', 'far cry 5', 'farming simulator', 'fs22', 'fs25',
        'fifa', 'fifa 24', 'ea sports fc', 'fc 24', 'fc 25',
        'final fantasy', 'final fantasy xiv', 'ffxiv', 'ff14', 'final fantasy xvi',
        'flight simulator', 'microsoft flight simulator', 'msfs', 'msfs 2020',
        'for honor', 'fortnite', 'forza', 'forza horizon', 'forza horizon 5', 'forza motorsport',
        'frostpunk', 'frostpunk 2',
        # G
        'genshin impact', 'genshin', 'ghost of tsushima', 'ghostwire tokyo',
        'god of war', 'gow', 'godfall', 'gotham knights',
        'grand theft auto', 'gta', 'gta v', 'gta 5', 'gta iv', 'gta online', 'gta vi',
        'grounded', 'guild wars', 'guild wars 2', 'gw2',
        # H
        'hades', 'hades ii', 'hades 2', 'half-life', 'half life', 'half-life 2', 'half-life alyx',
        'halo', 'halo infinite', 'halo master chief collection', 'halo mcc',
        'hearts of iron', 'hoi4', 'hearts of iron iv', 'helldivers', 'helldivers 2',
        'heroes of the storm', 'hots', 'hi-fi rush', 'hitman', 'hitman 3',
        'hogwarts legacy', 'hollow knight', 'silksong', 'honkai star rail', 'hsr',
        'horizon zero dawn', 'horizon forbidden west', 'hunt showdown',
        # I
        'insurgency', 'insurgency sandstorm', 'it takes two',
        # J
        'just cause', 'just cause 4',
        # K
        'kenshi', 'kerbal space program', 'ksp', 'ksp2', 'kingdom come deliverance',
        'knockout city',
        # L
        'last epoch', 'league of legends', 'lol', 'left 4 dead', 'l4d2',
        'lego star wars', 'lethal company', 'lies of p',
        'life is strange', 'little nightmares', 'lost ark',
        # M
        'madden', 'madden nfl', 'manor lords', 'marvel snap',
        'marvels spider-man', 'spider-man', 'mass effect', 'mass effect legendary',
        'medal of honor', 'metro exodus', 'minecraft', 'minecraft java', 'minecraft bedrock',
        'minecraft dungeons', 'monster hunter', 'monster hunter world', 'monster hunter rise',
        'mordhau', 'mortal kombat', 'mk11', 'mk1', 'mount and blade', 'bannerlord',
        # N
        'naraka bladepoint', 'nba 2k', 'nba 2k24', 'nba 2k25',
        'need for speed', 'nfs', 'nfs heat', 'nfs unbound',
        'new world', 'nier automata', 'nier replicant', 'nioh', 'nioh 2',
        'no mans sky', 'no man\'s sky',
        # O
        'osu', 'osu!', 'outer wilds', 'outlast', 'overwatch', 'overwatch 2', 'ow2',
        # P
        'paladins', 'palworld', 'path of exile', 'poe', 'poe 2', 'path of exile 2',
        'payday', 'payday 2', 'payday 3', 'persona', 'persona 5', 'persona 3',
        'phantasy star online', 'pso2', 'phasmophobia',
        'pillars of eternity', 'planet coaster', 'planet zoo',
        'playerunknowns battlegrounds', 'pubg', 'portal', 'portal 2',
        'prey', 'project zomboid', 'pyre',
        # R
        'rainbow six', 'rainbow six siege', 'r6', 'r6s', 'ready or not',
        'red dead redemption', 'red dead redemption 2', 'rdr2', 'red dead online',
        'remnant', 'remnant 2', 'remnant from the ashes',
        'resident evil', 're4', 'resident evil 4', 'resident evil village',
        'returnal', 'rimworld', 'ring of elysium', 'risk of rain', 'risk of rain 2',
        'roblox', 'rocket league', 'rust',
        # S
        'satisfactory', 'scarlet nexus', 'sea of thieves', 'sekiro',
        'shadow of the tomb raider', 'shatterline', 'sifu',
        'sim city', 'simcity', 'sims', 'the sims', 'sims 4', 'the sims 4',
        'ski safari', 'skyrim', 'elder scrolls', 'elder scrolls online', 'eso',
        'slime rancher', 'smite', 'sniper elite',
        'snowrunner', 'sons of the forest', 'soulcalibur', 'space engineers',
        'spellbreak', 'spider-man remastered', 'spiritfarer', 'spore',
        'squad', 'star citizen', 'star wars battlefront', 'star wars jedi',
        'starcraft', 'starcraft 2', 'sc2', 'starfield', 'stardew valley',
        'stellaris', 'stray', 'street fighter', 'sf6', 'street fighter 6',
        'subnautica', 'suicide squad', 'super people', 'surviving mars',
        # T
        'tales of arise', 'team fortress', 'tf2', 'team fortress 2',
        'tekken', 'tekken 8', 'terraria', 'the binding of isaac', 'isaac',
        'the crew', 'the division', 'division 2', 'the elder scrolls',
        'the finals', 'the forest', 'the outer worlds',
        'the quarry', 'the surge', 'the walking dead', 'the witcher',
        'witcher', 'witcher 3', 'the witcher 3', 'titanfall', 'titanfall 2',
        'tomb raider', 'torchlight', 'total war', 'total war warhammer',
        'trackmania', 'tribes', 'tropico', 'tunic', 'two point hospital',
        # U
        'ultrakill', 'undertale', 'unravel',
        # V
        'v rising', 'valheim', 'valorant', 'vampire survivors',
        'vampyr', 'vermintide', 'vermintide 2', 'vigor',
        # W
        'warframe', 'warhammer', 'warhammer 40000', 'warhammer vermintide',
        'warthunder', 'war thunder', 'watch dogs', 'watch dogs 2', 'watch dogs legion',
        'waven', 'wolfenstein', 'world of tanks', 'wot',
        'world of warcraft', 'wow', 'world of warships', 'wows', 'wwe 2k',
        # X
        'xcom', 'xcom 2',
        # Y
        'yakuza', 'like a dragon',
        # Z
        'zenless zone zero', 'zzz', 'zombie army',
        
        # ==================== NINTENDO GAMES (Popular on PC via emulation) ====================
        'nintendo switch', 'switch', 'yuzu', 'ryujinx', 'cemu', 'dolphin',
        'zelda', 'breath of the wild', 'tears of the kingdom', 'totk', 'botw',
        'mario', 'super mario', 'mario kart', 'mario odyssey',
        'pokemon', 'pokémon', 'animal crossing', 'splatoon', 'smash bros',
        'super smash bros', 'metroid', 'metroid dread', 'fire emblem',
        'kirby', 'luigi mansion', 'paper mario', 'xenoblade',
        
        # ==================== COMMUNICATION & MESSAGING ====================
        'discord', 'slack', 'microsoft teams', 'teams', 'zoom', 'zoom meeting',
        'skype', 'skype for business', 'google meet', 'google chat',
        'whatsapp', 'whatsapp desktop', 'telegram', 'telegram desktop',
        'signal', 'signal desktop', 'messenger', 'facebook messenger',
        'wechat', 'weixin', 'line', 'viber', 'kakaotalk',
        'element', 'matrix', 'mattermost', 'rocket.chat', 'zulip',
        'webex', 'cisco webex', 'gotomeeting', 'goto meeting',
        'bluejeans', 'ring central', 'flock', 'twist', 'chanty',
        'facetime', 'imessage', 'messages', 'mail',
        
        # ==================== WEB BROWSERS ====================
        'chrome', 'google chrome', 'google', 'firefox', 'mozilla firefox',
        'safari', 'microsoft edge', 'edge', 'opera', 'opera gx',
        'brave', 'brave browser', 'vivaldi', 'arc', 'arc browser',
        'chromium', 'tor', 'tor browser', 'waterfox', 'librewolf',
        'duckduckgo', 'duckduckgo browser', 'samsung internet',
        'maxthon', 'uc browser', 'yandex browser', 'orion',
        'floorp', 'zen browser', 'thorium',
        
        # ==================== PRODUCTIVITY & OFFICE ====================
        # Microsoft Office
        'microsoft word', 'word', 'microsoft excel', 'excel',
        'microsoft powerpoint', 'powerpoint', 'microsoft outlook', 'outlook',
        'microsoft onenote', 'onenote', 'microsoft access', 'access',
        'microsoft publisher', 'publisher', 'microsoft project', 'project',
        'microsoft visio', 'visio', 'microsoft 365', 'office 365', 'office',
        # Google Workspace
        'google docs', 'google sheets', 'google slides', 'google drive',
        'google calendar', 'google keep', 'google forms', 'google sites',
        # Apple iWork
        'pages', 'numbers', 'keynote', 'notes', 'reminders', 'calendar',
        # LibreOffice
        'libreoffice', 'libreoffice writer', 'libreoffice calc',
        'libreoffice impress', 'libreoffice draw', 'libreoffice base',
        # Other office suites
        'openoffice', 'wps office', 'wps', 'onlyoffice', 'calligra',
        'softmaker office', 'freeoffice', 'polaris office',
        
        # ==================== NOTE-TAKING & KNOWLEDGE MANAGEMENT ====================
        'notion', 'obsidian', 'evernote', 'bear', 'apple notes',
        'roam research', 'roam', 'logseq', 'craft', 'ulysses',
        'notability', 'goodnotes', 'simplenote', 'standard notes',
        'joplin', 'trilium', 'anytype', 'mem', 'reflect',
        'remnote', 'tana', 'capacities', 'heptabase', 'scrintal',
        'workflowy', 'dynalist', 'mindnode', 'mindmeister', 'xmind',
        'miro', 'mural', 'figjam', 'whimsical', 'lucidchart',
        'ia writer', 'byword', 'writeroom', 'scrivener', 'final draft',
        
        # ==================== TASK & PROJECT MANAGEMENT ====================
        'todoist', 'things', 'things 3', 'omnifocus', 'ticktick',
        'any.do', 'microsoft to do', 'to do', 'reminders',
        'trello', 'asana', 'monday', 'monday.com', 'clickup',
        'jira', 'linear', 'height', 'shortcut', 'clubhouse',
        'basecamp', 'wrike', 'smartsheet', 'teamwork', 'airtable',
        'notion calendar', 'fantastical', 'busycal', 'calendly',
        'clockify', 'toggl', 'toggl track', 'harvest', 'everhour',
        'rescuetime', 'time doctor', 'desktime', 'timely',
        
        # ==================== DEVELOPMENT & CODING ====================
        # IDEs & Editors
        'visual studio', 'visual studio code', 'vs code', 'vscode', 'code',
        'xcode', 'intellij', 'intellij idea', 'pycharm', 'webstorm',
        'phpstorm', 'rubymine', 'rider', 'clion', 'goland', 'datagrip',
        'android studio', 'eclipse', 'netbeans', 'codeblocks', 'code blocks',
        'sublime text', 'sublime', 'atom', 'brackets', 'notepad++',
        'vim', 'neovim', 'nvim', 'emacs', 'spacemacs', 'doom emacs',
        'nano', 'bbedit', 'textmate', 'coda', 'nova', 'zed',
        'fleet', 'lapce', 'helix', 'cursor', 'windsurf',
        # Terminals
        'terminal', 'iterm', 'iterm2', 'hyper', 'warp', 'alacritty',
        'kitty', 'wezterm', 'tabby', 'terminus', 'windows terminal',
        'powershell', 'cmd', 'command prompt', 'git bash', 'cmder',
        'putty', 'moba xterm', 'mobaxterm', 'securecrt', 'zssh',
        # Version Control
        'github', 'github desktop', 'gitkraken', 'sourcetree', 'fork',
        'tower', 'git', 'git gui', 'gitx', 'smartgit', 'sublime merge',
        'gitlab', 'bitbucket', 'azure devops', 'gitea', 'gogs',
        # Database Tools
        'dbeaver', 'tableplus', 'sequel pro', 'sequel ace', 'datagrip',
        'navicat', 'heidisql', 'mysql workbench', 'pgadmin', 'mongodb compass',
        'redis desktop', 'redisinsight', 'robo 3t', 'studio 3t',
        'sqlitebrowser', 'db browser', 'adminer', 'phpmyadmin',
        'azure data studio', 'sql server management studio', 'ssms',
        # API & Debugging
        'postman', 'insomnia', 'paw', 'hoppscotch', 'httpie',
        'charles', 'charles proxy', 'fiddler', 'wireshark', 'proxyman',
        'rest client', 'thunder client', 'rapidapi',
        # Containers & DevOps
        'docker', 'docker desktop', 'podman', 'rancher', 'portainer',
        'kubernetes', 'minikube', 'lens', 'k9s', 'kubectl',
        'vagrant', 'virtualbox', 'vmware', 'vmware fusion', 'parallels',
        'terraform', 'ansible', 'jenkins', 'circleci', 'github actions',
        # Other Dev Tools
        'figma', 'sketch', 'zeplin', 'abstract', 'invision',
        'storybook', 'chromatic', 'percy', 'browserstack',
        'ngrok', 'localtunnel', 'tailscale', 'zerotier',
        
        # ==================== DESIGN & CREATIVE ====================
        # Adobe Creative Cloud
        'photoshop', 'adobe photoshop', 'illustrator', 'adobe illustrator',
        'indesign', 'adobe indesign', 'premiere', 'premiere pro', 'adobe premiere',
        'after effects', 'adobe after effects', 'animate', 'adobe animate',
        'dreamweaver', 'adobe dreamweaver', 'xd', 'adobe xd',
        'lightroom', 'adobe lightroom', 'lightroom classic',
        'audition', 'adobe audition', 'character animator',
        'dimension', 'adobe dimension', 'fresco', 'adobe fresco',
        'acrobat', 'adobe acrobat', 'acrobat reader', 'adobe reader',
        'bridge', 'adobe bridge', 'media encoder', 'adobe media encoder',
        'substance', 'substance painter', 'substance designer',
        'creative cloud', 'adobe creative cloud',
        # Affinity
        'affinity designer', 'affinity photo', 'affinity publisher',
        # Other Design
        'figma', 'sketch', 'canva', 'gimp', 'inkscape', 'krita',
        'coreldraw', 'corel painter', 'paintshop pro', 'paint.net',
        'pixelmator', 'pixelmator pro', 'procreate', 'procreate dreams',
        'vectornator', 'linearity curve', 'gravit designer', 'lunacy',
        'penpot', 'mypaint', 'artrage', 'clip studio', 'clip studio paint',
        'medibang', 'fire alpaca', 'sai', 'paint tool sai',
        'aseprite', 'piskel', 'pyxel edit', 'graphics gale',
        # 3D & Motion
        'blender', 'cinema 4d', 'c4d', 'maya', 'autodesk maya',
        '3ds max', 'autodesk 3ds max', 'houdini', 'zbrush', 'mudbox',
        'modo', 'lightwave', 'sketchup', 'rhino', 'rhinoceros',
        'fusion 360', 'solidworks', 'autocad', 'revit',
        'unreal engine', 'unreal editor', 'unity', 'unity hub',
        'godot', 'godot engine', 'gamemaker', 'game maker studio',
        'rpg maker', 'construct', 'defold', 'cocos',
        'twinmotion', 'lumion', 'enscape', 'v-ray', 'keyshot',
        'marvelous designer', 'substance 3d', 'spline', 'cavalry',
        'rive', 'lottie', 'bodymovin', 'principle', 'origami studio',
        
        # ==================== VIDEO & STREAMING ====================
        # Video Editing
        'final cut', 'final cut pro', 'imovie', 'davinci resolve', 'davinci',
        'premiere pro', 'premiere rush', 'avid', 'avid media composer',
        'hitfilm', 'filmora', 'wondershare filmora', 'camtasia',
        'screenflow', 'movavi', 'vegas pro', 'sony vegas', 'magix vegas',
        'openshot', 'shotcut', 'kdenlive', 'olive', 'lightworks',
        'kapwing', 'clipchamp', 'veed', 'descript', 'riverside',
        # Screen Recording & Streaming
        'obs', 'obs studio', 'streamlabs', 'streamlabs obs', 'slobs',
        'xsplit', 'xsplit broadcaster', 'vmix', 'wirecast',
        'streamelements', 'twitch studio', 'lightstream',
        'loom', 'screencastify', 'screenpal', 'snagit', 'droplr',
        'cleanshot', 'cleanshot x', 'monosnap', 'lightshot', 'greenshot',
        'kap', 'gif brewery', 'giphy capture', 'licecap', 'screentogif',
        'nvidia shadowplay', 'shadowplay', 'geforce experience',
        'amd relive', 'radeon software', 'xbox game bar',
        # Media Players
        'vlc', 'vlc media player', 'iina', 'mpv', 'mpc-hc',
        'pot player', 'potplayer', 'kmplayer', 'gom player',
        'quicktime', 'quicktime player', 'windows media player',
        'plex', 'plex media player', 'kodi', 'jellyfin', 'emby',
        'infuse', 'movist', 'elmedia', 'mplayerx',
        # Video Streaming Apps
        'netflix', 'youtube', 'youtube music', 'amazon prime video', 'prime video',
        'disney+', 'disney plus', 'hulu', 'hbo max', 'max',
        'apple tv', 'apple tv+', 'peacock', 'paramount+', 'paramount plus',
        'crunchyroll', 'funimation', 'hidive', 'vrv',
        'twitch', 'twitch app', 'kick', 'rumble',
        'vimeo', 'dailymotion', 'bilibili',
        
        # ==================== AUDIO & MUSIC ====================
        # DAWs
        'logic', 'logic pro', 'logic pro x', 'garageband',
        'ableton', 'ableton live', 'fl studio', 'fruity loops',
        'pro tools', 'avid pro tools', 'cubase', 'nuendo',
        'studio one', 'presonus studio one', 'reaper', 'reason',
        'bitwig', 'bitwig studio', 'audacity', 'ardour',
        'lmms', 'mixcraft', 'bandlab', 'soundtrap',
        # Audio Editing
        'adobe audition', 'audition', 'izotope rx', 'rx',
        'sound forge', 'wavelab', 'ocenaudio', 'fission',
        'twisted wave', 'amadeus pro', 'acoustica',
        # Music Players
        'spotify', 'apple music', 'itunes', 'music',
        'tidal', 'deezer', 'amazon music', 'youtube music',
        'pandora', 'soundcloud', 'audiomack', 'bandcamp',
        'qobuz', 'foobar2000', 'musicbee', 'winamp',
        'clementine', 'strawberry', 'rhythmbox', 'amarok',
        'vox', 'swinsian', 'doppler', 'plexamp',
        # Podcasts
        'pocket casts', 'overcast', 'castro', 'apple podcasts',
        'spotify podcasts', 'google podcasts', 'stitcher',
        'anchor', 'riverside.fm', 'zencastr', 'squadcast',
        
        # ==================== UTILITIES & SYSTEM ====================
        # File Management
        'finder', 'file explorer', 'explorer', 'path finder', 'forklift',
        'transmit', 'cyberduck', 'filezilla', 'commander one',
        'total commander', 'double commander', 'directory opus',
        'the unarchiver', 'winrar', 'winzip', '7-zip', '7zip',
        'peazip', 'bandizip', 'keka', 'archiver', 'betterzip',
        # Cloud Storage
        'dropbox', 'google drive', 'icloud', 'icloud drive',
        'onedrive', 'microsoft onedrive', 'box', 'box drive',
        'mega', 'sync', 'pcloud', 'tresorit', 'spideroak',
        'nextcloud', 'owncloud', 'seafile', 'syncthing',
        # Password Managers
        '1password', 'lastpass', 'bitwarden', 'dashlane',
        'keepass', 'keepassxc', 'enpass', 'roboform',
        'nordpass', 'keeper', 'zoho vault', 'myki',
        # VPNs
        'nordvpn', 'expressvpn', 'surfshark', 'protonvpn', 'proton vpn',
        'cyberghost', 'private internet access', 'pia',
        'mullvad', 'windscribe', 'tunnelbear', 'hotspot shield',
        'ivpn', 'vyprvpn', 'strongvpn', 'ipvanish',
        # System Utilities
        'cleanmymac', 'cleanmymac x', 'ccleaner', 'bleachbit',
        'malwarebytes', 'avast', 'avg', 'bitdefender', 'norton',
        'kaspersky', 'eset', 'sophos', 'trend micro', 'mcafee',
        'little snitch', 'lulu', 'radio silence', 'tripmode',
        'bartender', 'vanilla', 'dozer', 'hidden bar',
        'alfred', 'raycast', 'launchbar', 'quicksilver', 'spotlight',
        'hazel', 'keyboard maestro', 'bettertouchtool', 'karabiner',
        'rectangle', 'magnet', 'spectacle', 'moom', 'divvy',
        'cheatsheet', 'one switch', 'contexts', 'witch',
        'istat menus', 'stats', 'menumeters', 'monitorcontrol',
        'amphetamine', 'caffeine', 'lungo', 'theine',
        'time machine', 'carbon copy cloner', 'superduper', 'chronosync',
        'disk utility', 'disk drill', 'data rescue', 'recuva',
        'activity monitor', 'task manager', 'process monitor', 'htop',
        'app cleaner', 'appcleaner', 'app zapper', 'apptrap',
        'pdf expert', 'preview', 'adobe reader', 'foxit reader',
        'skim', 'pdf pen', 'pdf element', 'nitro pdf',
        # Screenshot & Clipboard
        'screenshot', 'snipping tool', 'greenshot', 'sharex',
        'paste', 'clipboard manager', 'copy clip', 'maccy',
        'flycut', 'copied', 'pastebot', 'ditto',
        
        # ==================== READING & REFERENCE ====================
        'kindle', 'amazon kindle', 'apple books', 'books',
        'calibre', 'kobo', 'nook', 'google play books',
        'pocket', 'instapaper', 'readwise', 'matter',
        'reeder', 'netnewswire', 'feedly', 'inoreader',
        'flipboard', 'news', 'apple news', 'google news',
        'wikipedia', 'stack overflow', 'medium', 'substack',
        'dictionary', 'thesaurus', 'translate', 'google translate',
        'deepl', 'linguee', 'reverso', 'wordreference',
        
        # ==================== FINANCE & BUSINESS ====================
        'quickbooks', 'quicken', 'mint', 'ynab', 'personal capital',
        'xero', 'freshbooks', 'wave', 'zoho books', 'sage',
        'excel', 'google sheets', 'numbers', 'airtable',
        'salesforce', 'hubspot', 'pipedrive', 'zoho crm',
        'stripe', 'square', 'paypal', 'venmo', 'wise',
        'coinbase', 'binance', 'kraken', 'robinhood', 'webull',
        'trading view', 'tradingview', 'thinkorswim', 'metatrader',
        'bloomberg', 'reuters', 'yahoo finance',
        
        # ==================== EDUCATION & LEARNING ====================
        'duolingo', 'babbel', 'rosetta stone', 'busuu', 'memrise',
        'anki', 'quizlet', 'flashcards', 'brainscape',
        'khan academy', 'coursera', 'udemy', 'edx', 'skillshare',
        'linkedin learning', 'pluralsight', 'codecademy', 'datacamp',
        'brilliant', 'masterclass', 'domestika', 'ted',
        'wolfram alpha', 'wolfram', 'mathematica', 'matlab',
        'geogebra', 'desmos', 'symbolab', 'photomath',
        'grammarly', 'hemingway', 'languagetool', 'prowritingaid',
        'zotero', 'mendeley', 'endnote', 'paperpile', 'citavi',
        
        # ==================== HEALTH & WELLNESS ====================
        'headspace', 'calm', 'insight timer', 'ten percent happier',
        'waking up', 'balance', 'shine', 'aura',
        'strava', 'nike run club', 'runkeeper', 'mapmyrun',
        'myfitnesspal', 'lose it', 'noom', 'lifesum',
        'fitbit', 'garmin connect', 'apple health', 'health',
        'sleep cycle', 'pillow', 'autosleep', 'sleepwatch',
        'zero', 'fastic', 'life fasting', 'window',
        'streaks', 'habitica', 'habitify', 'habit tracker',
        
        # ==================== SOCIAL MEDIA ====================
        'twitter', 'x', 'tweetdeck', 'tweetbot', 'twitterrific',
        'facebook', 'instagram', 'threads', 'snapchat',
        'tiktok', 'pinterest', 'tumblr', 'reddit',
        'linkedin', 'clubhouse', 'mastodon', 'bluesky',
        'buffer', 'hootsuite', 'later', 'sprout social',
        
        # ==================== PHOTOGRAPHY ====================
        'lightroom', 'lightroom classic', 'capture one', 'luminar',
        'darktable', 'rawtherapee', 'digikam', 'acdsee',
        'photos', 'google photos', 'amazon photos', 'flickr',
        'snapseed', 'vsco', 'polarr', 'darkroom',
        'photomechanic', 'photo mechanic', 'bridge', 'photo booth',
        
        # ==================== EMULATORS ====================
        'retroarch', 'dolphin', 'cemu', 'yuzu', 'ryujinx',
        'ppsspp', 'desmume', 'melonds', 'citra', 'pcsx2',
        'rpcs3', 'xenia', 'mame', 'epsxe', 'snes9x',
        'zsnes', 'mgba', 'visualboy advance', 'vba',
        'dosbox', 'wine', 'crossover', 'parallels', 'bootcamp',
        'bluestacks', 'noxplayer', 'ldplayer', 'memu',
        
        # ==================== MISC APPS ====================
        'home', 'homekit', 'apple home', 'google home', 'alexa',
        'philips hue', 'nanoleaf', 'ring', 'nest',
        'maps', 'apple maps', 'google maps', 'waze',
        'uber', 'lyft', 'doordash', 'ubereats', 'grubhub',
        'airbnb', 'booking', 'expedia', 'tripadvisor',
        'weather', 'carrot weather', 'dark sky', 'weatherbug',
        'clock', 'timer', 'stopwatch', 'world clock',
        'calculator', 'pcalc', 'soulver', 'numi', 'calca',
        'compass', 'measure', 'magnifier', 'level',
        'voice memos', 'just press record', 'ferrite', 'recorder',
        'contacts', 'cardhop', 'address book',
        'system preferences', 'settings', 'control panel',
        'app store', 'mac app store', 'microsoft store', 'play store',
        'safari technology preview', 'xcode', 'testflight',
        'simulator', 'ios simulator', 'android emulator',
    }
    
    def _validate_url_pattern(self, url: str) -> tuple:
        """
        Validate a custom URL/domain pattern with layered checks.
        
        Uses format validation, TLD checking, and optional DNS lookup.
        Never crashes - returns safe defaults on any error.
        
        Args:
            url: The URL/domain to validate
            
        Returns:
            Tuple of (is_valid, error_or_warning_message, is_warning)
            - is_valid: True if pattern should be accepted
            - error_or_warning_message: Error message or warning text
            - is_warning: True if it's a warning (still valid), False if error
        """
        import re
        import socket
        
        try:
            url = url.strip().lower()
            
            # Must be at least 3 characters
            if len(url) < 3:
                return False, f"'{url}' is too short (min 3 characters)", False
            
            # Must not be too long
            if len(url) > 253:
                return False, f"'{url}' is too long (max 253 characters)", False
            
            # Basic format check - must look like a domain
            # Valid: letters, numbers, dots, hyphens, colons (for ://x.com style)
            if not re.match(r'^[a-z0-9:][a-z0-9._\-:/]*[a-z0-9]$', url):
                return False, f"'{url}' contains invalid characters for a URL", False
            
            # Must contain a dot (required for domain)
            if '.' not in url:
                return False, f"'{url}' doesn't look like a URL - needs a domain extension (e.g., .com)", False
            
            # Extract domain for TLD checking
            # Handle cases like "://x.com" or "subdomain.example.com"
            domain = url
            if '://' in domain:
                domain = domain.split('://')[-1]
            if '/' in domain:
                domain = domain.split('/')[0]
            
            # Check TLD (last part after dot)
            parts = domain.split('.')
            if len(parts) >= 2:
                # Check for compound TLDs first (e.g., co.uk)
                potential_compound = '.'.join(parts[-2:])
                tld = parts[-1]
                
                if potential_compound not in self.VALID_TLDS and tld not in self.VALID_TLDS:
                    return False, f"'{url}' has invalid domain extension '.{tld}'", False
            
            # Warn about overly generic patterns
            generic_terms = {'app', 'web', 'the', 'new', 'my', 'get', 'go'}
            domain_name = parts[0] if parts else ''
            if domain_name in generic_terms:
                return True, f"'{url}' is generic and may cause false positives", True
            
            # DNS lookup (optional, with timeout and graceful fallback)
            dns_result = self._dns_lookup_with_fallback(domain)
            if not dns_result[0]:
                # DNS failed - return as warning, still allow
                return True, dns_result[1], True
            
            return True, "", False
            
        except Exception as e:
            logger.error(f"URL validation error for '{url}': {e}")
            return False, f"Validation error: {e}", False
    
    def _dns_lookup_with_fallback(self, domain: str) -> tuple:
        """
        Attempt DNS lookup with graceful fallback on network issues.
        
        Args:
            domain: The domain to look up
            
        Returns:
            Tuple of (success, message)
            - success: True if domain is plausible (verified or network unavailable)
            - message: Status message
        """
        import socket
        
        try:
            # Set a short timeout to avoid blocking UI
            original_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(2.0)
            
            try:
                socket.getaddrinfo(domain, 80)
                return True, "Domain verified"
            finally:
                socket.setdefaulttimeout(original_timeout)
                
        except socket.gaierror:
            # DNS lookup failed - domain likely doesn't exist
            return False, f"Domain '{domain}' may not exist (DNS lookup failed)"
        except socket.timeout:
            # Network timeout - fall back gracefully
            logger.warning(f"DNS lookup timeout for {domain} - accepting based on format")
            return True, "Could not verify (network timeout) - accepted based on format"
        except OSError as e:
            # Network unavailable (e.g., no Wi-Fi)
            logger.warning(f"Network error during DNS lookup for {domain}: {e}")
            return True, "Could not verify (network unavailable) - accepted based on format"
        except Exception as e:
            # Any other error - don't crash, accept with warning
            logger.warning(f"DNS lookup error for {domain}: {e}")
            return True, "Could not verify (error) - accepted based on format"
    
    def _validate_app_pattern(self, app_name: str) -> tuple:
        """
        Validate a custom app name pattern.
        
        Requires EXACT match (case-insensitive) against KNOWN_APPS list.
        Unknown apps trigger a warning, under 3 chars is invalid.
        Never crashes - returns safe defaults on any error.
        
        Args:
            app_name: The app name to validate
            
        Returns:
            Tuple of (is_valid, error_or_warning_message, is_warning)
            - is_valid: True if pattern should be accepted
            - error_or_warning_message: Error message or warning text
            - is_warning: True if it's a warning (still valid), False if error
        """
        import re
        
        try:
            app_name = app_name.strip()
            
            # Must be at least 3 characters (reject very short inputs)
            if len(app_name) < 3:
                return False, f"'{app_name}' is too short (min 3 characters)", False
            
            # Must not be too long
            if len(app_name) > 50:
                return False, f"'{app_name}' is too long (max 50 characters)", False
            
            # Check if it looks like a URL (redirect to URL field)
            if '.' in app_name and app_name.count('.') <= 3:
                # Could be a domain - check if it ends with a TLD
                parts = app_name.lower().split('.')
                if len(parts) >= 2 and parts[-1] in self.VALID_TLDS:
                    return False, f"'{app_name}' looks like a URL - add it to the URLs field instead", False
            
            # Only allow characters actually used in real app names:
            # - Letters, numbers, spaces (basic)
            # - Hyphen: "Half-Life", "Counter-Strike"
            # - Plus: "Disney+", "Apple TV+"
            # - Apostrophe: "Baldur's Gate", "Assassin's Creed"
            # - Colon: "Call of Duty: Warzone"
            # - Ampersand: "AT&T", "Barnes & Noble"
            # - Parentheses: "VLC (64-bit)"
            # NOT allowed: dots, underscores, @, #, $, %, *, !, etc.
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\s\-\+\'\:\&\(\)]*[a-zA-Z0-9\+\'\)]?$', app_name):
                return False, f"'{app_name}' contains invalid characters - only letters, numbers, spaces, and common symbols (- + ' : & ( )) allowed", False
            
            # Warn about patterns that look like mistyped URLs
            if app_name.lower().endswith(('.com', '.org', '.net', '.io')):
                return True, f"'{app_name}' looks like it might be a URL", True
            
            # Check if this is a known app - EXACT MATCH ONLY (case-insensitive)
            app_lower = app_name.lower()
            if app_lower in self.KNOWN_APPS:
                # Exact match with known app - accept without warning
                return True, "", False
            
            # Unknown app - warn but allow
            # No partial matching - must be exact match to be recognized
            return True, f"'{app_name}' is not a recognized app - please verify the name", True
            
        except Exception as e:
            logger.error(f"App validation error for '{app_name}': {e}")
            return False, f"Validation error: {e}", False
    
    def _validate_pattern(self, pattern: str) -> tuple:
        """
        Legacy validation method - routes to appropriate validator.
        
        Kept for backward compatibility.
        
        Args:
            pattern: The pattern to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Determine if it's a URL or app name based on content
        if '.' in pattern:
            is_valid, msg, _ = self._validate_url_pattern(pattern)
        else:
            is_valid, msg, _ = self._validate_app_pattern(pattern)
        
        return is_valid, msg
    
    def _validate_urls_realtime(self):
        """
        Validate URLs in real-time as user types.
        Updates the validation label with status/warnings.
        """
        try:
            urls_text = self.custom_urls_text.get("1.0", tk.END).strip()
            if not urls_text:
                self.url_validation_label.config(text="", fg=COLORS["text_secondary"])
                return
            
            urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
            errors = []
            warnings = []
            valid_count = 0
            
            for url in urls:
                is_valid, msg, is_warning = self._validate_url_pattern(url)
                if not is_valid:
                    errors.append(msg)
                elif is_warning and msg:
                    warnings.append(msg)
                else:
                    valid_count += 1
            
            # Update label with status and tooltip with full message
            if errors:
                short_text = f"❌ {len(errors)} invalid: {errors[0][:40]}..."
                full_text = "Invalid URLs:\n• " + "\n• ".join(errors)
                self.url_validation_label.config(text=short_text, fg=COLORS["status_gadget"])
                self.url_validation_tooltip.update_text(full_text)
            elif warnings:
                short_text = f"⚠️ {len(warnings)} warning(s): {warnings[0][:35]}..."
                full_text = "Warnings:\n• " + "\n• ".join(warnings)
                self.url_validation_label.config(text=short_text, fg=COLORS["accent_warm"])
                self.url_validation_tooltip.update_text(full_text)
            elif valid_count > 0:
                self.url_validation_label.config(
                    text=f"✓ {valid_count} URL(s) valid",
                    fg=COLORS["status_focused"]  # Green
                )
                self.url_validation_tooltip.update_text("")
            else:
                self.url_validation_label.config(text="", fg=COLORS["text_secondary"])
                self.url_validation_tooltip.update_text("")
                
        except Exception as e:
            logger.error(f"Error in real-time URL validation: {e}")
            self.url_validation_label.config(text="", fg=COLORS["text_secondary"])
            self.url_validation_tooltip.update_text("")
    
    def _validate_apps_realtime(self):
        """
        Validate app names in real-time as user types.
        Updates the validation label with status/warnings.
        """
        try:
            apps_text = self.custom_apps_text.get("1.0", tk.END).strip()
            if not apps_text:
                self.app_validation_label.config(text="", fg=COLORS["text_secondary"])
                return
            
            apps = [a.strip() for a in apps_text.split("\n") if a.strip()]
            errors = []
            warnings = []
            valid_count = 0
            
            for app in apps:
                is_valid, msg, is_warning = self._validate_app_pattern(app)
                if not is_valid:
                    errors.append(msg)
                elif is_warning and msg:
                    warnings.append(msg)
                else:
                    valid_count += 1
            
            # Update label with status and tooltip with full message
            if errors:
                short_text = f"❌ {len(errors)} invalid: {errors[0][:40]}..."
                full_text = "Invalid apps:\n• " + "\n• ".join(errors)
                self.app_validation_label.config(text=short_text, fg=COLORS["status_gadget"])
                self.app_validation_tooltip.update_text(full_text)
            elif warnings:
                short_text = f"⚠️ {len(warnings)} warning(s): {warnings[0][:35]}..."
                full_text = "Warnings:\n• " + "\n• ".join(warnings)
                self.app_validation_label.config(text=short_text, fg=COLORS["accent_warm"])
                self.app_validation_tooltip.update_text(full_text)
            elif valid_count > 0:
                self.app_validation_label.config(
                    text=f"✓ {valid_count} app(s) valid",
                    fg=COLORS["status_focused"]  # Green
                )
                self.app_validation_tooltip.update_text("")
            else:
                self.app_validation_label.config(text="", fg=COLORS["text_secondary"])
                self.app_validation_tooltip.update_text("")
                
        except Exception as e:
            logger.error(f"Error in real-time app validation: {e}")
            self.app_validation_label.config(text="", fg=COLORS["text_secondary"])
            self.app_validation_tooltip.update_text("")
    
    def _save_blocklist_settings(self, settings_window: tk.Toplevel):
        """
        Save blocklist settings and close the dialog.
        Validates URLs and apps separately, handles duplicates gracefully.
        
        Args:
            settings_window: The settings window to close
        """
        # --- Process URLs ---
        urls_text = self.custom_urls_text.get("1.0", tk.END).strip()
        raw_urls = [u.strip().lower() for u in urls_text.split("\n") if u.strip()]
        
        valid_urls = []
        invalid_urls = []
        url_warnings = []
        
        for url in raw_urls:
            is_valid, msg, is_warning = self._validate_url_pattern(url)
            if not is_valid:
                invalid_urls.append(msg)
            else:
                valid_urls.append(url)
                if is_warning and msg:
                    url_warnings.append(msg)
        
        # --- Process Apps ---
        apps_text = self.custom_apps_text.get("1.0", tk.END).strip()
        raw_apps = [a.strip() for a in apps_text.split("\n") if a.strip()]
        
        valid_apps = []
        invalid_apps = []
        app_warnings = []
        
        for app in raw_apps:
            is_valid, msg, is_warning = self._validate_app_pattern(app)
            if not is_valid:
                invalid_apps.append(msg)
            else:
                valid_apps.append(app)
                if is_warning and msg:
                    app_warnings.append(msg)
        
        # If there are invalid entries, show error and don't save
        all_invalid = invalid_urls + invalid_apps
        if all_invalid:
            error_msg = "Some entries are invalid:\n\n" + "\n".join(all_invalid[:5])
            if len(all_invalid) > 5:
                error_msg += f"\n... and {len(all_invalid) - 5} more"
            error_msg += "\n\nPlease fix these and try again."
            messagebox.showerror("Invalid Entries", error_msg)
            return  # Don't close dialog, let user fix
        
        # Remove duplicates within URLs (case-insensitive)
        seen_urls = set()
        unique_urls = []
        url_duplicates = []
        
        for url in valid_urls:
            if url not in seen_urls:
                seen_urls.add(url)
                unique_urls.append(url)
            else:
                url_duplicates.append(url)
        
        # Remove duplicates within Apps (case-sensitive for app names)
        seen_apps = set()
        unique_apps = []
        app_duplicates = []
        
        for app in valid_apps:
            app_lower = app.lower()
            if app_lower not in seen_apps:
                seen_apps.add(app_lower)
                unique_apps.append(app)
            else:
                app_duplicates.append(app)
        
        # Check for overlaps with enabled quick sites
        quick_site_patterns = set()
        for site_id in self.blocklist.enabled_quick_sites:
            if site_id in QUICK_SITES:
                for p in QUICK_SITES[site_id]['patterns']:
                    quick_site_patterns.add(p.lower())
        
        # Filter out URLs that already exist in enabled quick sites
        url_overlaps = []
        final_urls = []
        for url in unique_urls:
            if url in quick_site_patterns:
                url_overlaps.append(url)
            else:
                final_urls.append(url)
        
        # Filter out Apps that already exist in enabled quick sites
        app_overlaps = []
        final_apps = []
        for app in unique_apps:
            if app.lower() in quick_site_patterns:
                app_overlaps.append(app)
            else:
                final_apps.append(app)
        
        # Update blocklist with validated, deduplicated entries
        self.blocklist.custom_urls = final_urls
        self.blocklist.custom_apps = final_apps
        
        # Update AI fallback setting
        self.use_ai_fallback = self.ai_fallback_var.get()
        
        # Save to file
        self.blocklist_manager.save(self.blocklist)
        
        # Prepare feedback messages
        messages = []
        duplicates_removed = url_duplicates + app_duplicates
        preset_overlaps = url_overlaps + app_overlaps
        all_warnings = url_warnings + app_warnings
        
        if duplicates_removed:
            messages.append(f"Removed {len(duplicates_removed)} duplicate(s)")
        if preset_overlaps:
            messages.append(f"Removed {len(preset_overlaps)} entry(s) already in quick block sites")
        if all_warnings:
            messages.append(f"Note: {len(all_warnings)} warning(s) - entries saved but may need review")
        
        if messages:
            messagebox.showinfo(
                "Screen Settings Saved",
                "\n".join(messages) + "\n\nSettings saved successfully."
            )
        
        # Close dialog
        settings_window.destroy()
        
        logger.info(f"Blocklist settings saved (URLs: {len(final_urls)}, Apps: {len(final_apps)}, "
                   f"AI fallback: {self.use_ai_fallback}, "
                   f"duplicates removed: {len(duplicates_removed)}, "
                   f"preset overlaps: {len(preset_overlaps)})")
    
    def _show_tutorial(self):
        """
        Show the tutorial popup explaining how to use BrainDock.
        
        Displays a scrollable guide with icons and text descriptions covering:
        - Starting a session
        - Status indicators
        - Timer
        - Monitoring modes
        - Pause/Resume
        - Reports
        """
        # Create tutorial window - scale based on screen size
        tutorial_window = tk.Toplevel(self.root)
        tutorial_window.title("How to Use BrainDock")
        tutorial_window.configure(bg=COLORS["bg_primary"])
        
        # Calculate scaled popup size with minimum height to ensure buttons visible
        window_width, window_height = self.scaling_manager.get_popup_size(
            680, 640, min_width=480, min_height=520
        )
        tutorial_window.geometry(f"{window_width}x{window_height}")
        tutorial_window.resizable(False, False)
        
        # Center on parent window
        tutorial_window.transient(self.root)
        tutorial_window.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - window_width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - window_height) // 2
        tutorial_window.geometry(f"+{x}+{y}")
        
        # Main container with padding
        main_container = tk.Frame(tutorial_window, bg=COLORS["bg_primary"])
        main_container.pack(fill=tk.BOTH, expand=True, padx=30, pady=25)
        
        # Header
        title = tk.Label(
            main_container,
            text="How to Use BrainDock",
            font=self.font_title,
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_primary"]
        )
        title.pack()
        
        subtitle = tk.Label(
            main_container,
            text="Your AI-powered focus companion",
            font=self.font_body,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        subtitle.pack(pady=(8, 25))
        
        # Scrollable content area
        canvas_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        content_width = 600
        canvas = tk.Canvas(
            canvas_frame,
            bg=COLORS["bg_primary"],
            highlightthickness=0,
            width=content_width
        )
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=COLORS["bg_primary"])
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=content_width)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Enable smooth mousewheel scrolling (pixel-based, not unit-based)
        def _on_mousewheel(event):
            # Get current scroll position and total scrollable height
            # Use yview to scroll by a small fraction for smooth scrolling
            if sys.platform == "darwin":
                # macOS: delta is typically small integers, scroll proportionally
                # Negative delta = scroll down, positive = scroll up
                scroll_amount = -event.delta * 0.01  # Small fraction for smooth scroll
            else:
                # Windows/Linux: delta is typically 120 per notch
                scroll_amount = -event.delta / 120 * 0.05  # Smooth scroll factor
            
            # Get current position and adjust
            current_pos = canvas.yview()[0]
            new_pos = current_pos + scroll_amount
            # Clamp to valid range [0, 1]
            new_pos = max(0, min(1, new_pos))
            canvas.yview_moveto(new_pos)
        
        # Bind to canvas and scrollable frame directly (not bind_all)
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # Bind to all children as they're created
        def _bind_mousewheel_to_widget(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel_to_widget(child)
        
        # Store the bind function for later use after content is created
        self._tutorial_bind_mousewheel = _bind_mousewheel_to_widget
        self._tutorial_canvas = canvas
        self._tutorial_on_mousewheel = _on_mousewheel
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Tutorial sections data (icon, title, description)
        tutorial_sections = [
            (
                "\u25B6",  # Play triangle
                COLORS["button_start"],
                "Start a Session",
                "Click the 'Start Session' button to begin your focus session. "
                "BrainDock will always help you stay on track."
            ),
            (
                "\u25CF",  # Filled circle (status dot)
                COLORS["status_focused"],
                "Stay Focused",
                "The status indicator shows your current state:\n"
                "\u2022 Green = Focused and on task\n"
                "\u2022 Orange = Away from desk\n"
                "\u2022 Red = Gadget distraction\n"
                "\u2022 Purple = Screen distraction"
            ),
            (
                "\U0001F4A1",  # Lightbulb emoji
                COLORS["accent_warm"],
                "Best Results",
                "For best results, we recommend only one person stays in the camera frame "
                "during your session. Multiple people may affect accuracy."
            ),
            (
                "\u2699",  # Gear/settings
                COLORS["text_secondary"],
                "Choose Your Mode",
                "Select how BrainDock helps you focus:\n"
                "\u2022 Camera: Uses your device camera and AI to notice distractions\n"
                "\u2022 Screen: Checks current open window for distracting apps/websites\n"
                "\u2022 Both: Camera and screen combined"
            ),
            (
                "\u23F1",  # Stopwatch
                COLORS["accent_primary"],
                "See Your Time",
                "The timer displays your session duration. See how long you have been "
                "focused and aim to improve your quality focus time each session."
            ),
            (
                "\u23F8",  # Pause symbol
                COLORS["button_pause"],
                "Pause Anytime",
                "Click 'Pause Session' if you need to step away. Your timer and session is paused "
                "and you can resume whenever you are ready."
            ),
            (
                "\u2193",  # Down arrow (download)
                COLORS["accent_warm"],
                "Get Your Report",
                "When you stop your session, a PDF report is automatically saved to "
                "your Downloads folder with your focus statistics and a session summary."
            ),
        ]
        
        # Create tutorial sections
        for i, (icon, icon_color, section_title, description) in enumerate(tutorial_sections):
            section_frame = tk.Frame(scrollable_frame, bg=COLORS["bg_primary"])
            section_frame.pack(fill=tk.X, pady=(0, 20))
            
            # Icon and title row
            header_frame = tk.Frame(section_frame, bg=COLORS["bg_primary"])
            header_frame.pack(fill=tk.X, anchor="w")
            
            # Fixed-width container for icon to ensure consistent alignment
            icon_container = tk.Frame(header_frame, bg=COLORS["bg_primary"], width=32, height=28)
            icon_container.pack(side=tk.LEFT, padx=(0, 8))
            icon_container.pack_propagate(False)  # Prevent container from shrinking
            
            # Icon label - use system font with fallback
            icon_font = get_system_font(size=20, weight="normal")
            icon_label = tk.Label(
                icon_container,
                text=icon,
                font=icon_font,
                fg=icon_color,
                bg=COLORS["bg_primary"]
            )
            icon_label.place(relx=0.5, rely=0.5, anchor="center")  # Center icon in container
            
            # Section title
            title_label = tk.Label(
                header_frame,
                text=section_title,
                font=self.font_status,
                fg=COLORS["text_primary"],
                bg=COLORS["bg_primary"]
            )
            title_label.pack(side=tk.LEFT)
            
            # Description using Text widget for better line spacing
            # Estimate lines needed: chars / approx width in chars
            # Font size 14 approx 8px width -> 560px / 8px = 70 chars
            # We use width=65 to be safe
            
            desc_text = tk.Text(
                section_frame,
                font=self.font_body,
                fg=COLORS["text_secondary"],
                bg=COLORS["bg_primary"],
                bd=0,
                highlightthickness=0,
                wrap=tk.WORD,
                width=65,
                spacing2=6,  # Line spacing
                spacing3=5,  # Paragraph spacing
                cursor="arrow"
            )
            desc_text.insert("1.0", description)
            
            # Calculate height based on content using font measurement
            # Available width: Window(680) - MainPad(60) - TextPad(32) - Scrollbar(20) = 568
            available_width = 560  # Use 560 for safety
            
            num_lines = 0
            for paragraph in description.split('\n'):
                if not paragraph:
                    num_lines += 1
                    continue
                    
                current_line_width = 0
                lines_in_paragraph = 1
                
                for word in paragraph.split():
                    word_width = self.font_body.measure(word + " ")
                    if current_line_width + word_width <= available_width:
                        current_line_width += word_width
                    else:
                        lines_in_paragraph += 1
                        current_line_width = word_width
                
                num_lines += lines_in_paragraph
            
            desc_text.configure(height=num_lines, state="disabled")
            desc_text.pack(fill=tk.X, pady=(8, 0), padx=(43, 0))  # Slightly indented from title
            
            # Bind mousewheel to the text widget
            desc_text.bind("<MouseWheel>", _on_mousewheel)
            
        # Bind mousewheel to all widgets in the scrollable frame
        self._tutorial_bind_mousewheel(scrollable_frame)
        
        # Footer with "Got it" button
        footer_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        footer_frame.pack(fill=tk.X, pady=(15, 0))
        
        got_it_btn = RoundedButton(
            footer_frame,
            text="Got it!",
            command=lambda: self._close_tutorial(tutorial_window, canvas),
            bg_color=COLORS["button_start"],
            hover_color=COLORS["button_start_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=10,
            width=120,
            height=44
        )
        got_it_btn.pack()
        
        logger.debug("Tutorial popup opened")
    
    def _close_tutorial(self, tutorial_window: tk.Toplevel, canvas: tk.Canvas):
        """
        Close the tutorial popup and cleanup.
        
        Args:
            tutorial_window: The tutorial window to close
            canvas: The canvas widget (unused, kept for compatibility)
        """
        # Clean up references
        self._tutorial_bind_mousewheel = None
        self._tutorial_canvas = None
        self._tutorial_on_mousewheel = None
        tutorial_window.destroy()
        logger.debug("Tutorial popup closed")
    
    def _check_usage_limit(self):
        """Check if usage time is exhausted and show lockout if needed."""
        if self.usage_limiter.is_time_exhausted():
            self.is_locked = True
            self._show_lockout_overlay()
            logger.info("App locked - usage time exhausted")
        else:
            self.is_locked = False
            self._update_time_badge()
    
    def _update_usage_display(self):
        """Update the time badge display periodically."""
        if not self.is_locked:
            self._update_time_badge()
        
        # Calculate actual remaining time (same as badge display)
        base_remaining = self.usage_limiter.get_remaining_seconds()
        if self.is_running and self.session_started and self.session_start_time:
            session_elapsed = int((datetime.now() - self.session_start_time).total_seconds())
            remaining = max(0, base_remaining - session_elapsed)
        else:
            remaining = base_remaining
        
        # Determine update interval based on actual remaining time
        if self.is_running:
            if remaining <= 10:
                # Update every second when time is very low
                update_interval = 1000
            elif remaining <= 60:
                # Update every 2 seconds when under a minute
                update_interval = 2000
            else:
                # Normal: every 5 seconds during session
                update_interval = 5000
        else:
            # When not running, update less frequently
            update_interval = 30000
        
        self.root.after(update_interval, self._update_usage_display)
    
    def _update_time_badge(self):
        """Update the time remaining badge text and color."""
        # Get base remaining time from usage limiter
        base_remaining = self.usage_limiter.get_remaining_seconds()
        
        # If session is running, subtract current session's elapsed active time
        if self.is_running and self.session_started and self.session_start_time:
            # When paused, use frozen value - don't recalculate
            if self.is_paused:
                active_elapsed = self.frozen_active_seconds
            else:
                # Calculate active time (total elapsed minus all paused time)
                elapsed = (datetime.now() - self.session_start_time).total_seconds()
                active_elapsed = int(elapsed - self.total_paused_seconds)
            
            remaining = max(0, base_remaining - active_elapsed)
        else:
            remaining = base_remaining
        
        time_text = format_badge_time(int(remaining))
        
        # Determine badge color based on remaining time
        # Use white text on colored backgrounds for better contrast
        if remaining <= 0:
            badge_color = COLORS["time_badge_expired"]
            text_color = COLORS["text_white"]
            time_text = "Time expired"
        elif remaining <= 600:  # 10 minutes or less
            badge_color = COLORS["time_badge_expired"]
            text_color = COLORS["text_white"]
            time_text = f"{time_text} left"
        elif remaining <= 1800:  # 30 minutes or less
            badge_color = COLORS["time_badge_low"]
            text_color = COLORS["text_white"]
            time_text = f"{time_text} left"
        else:
            badge_color = COLORS.get("badge_bg", COLORS["bg_tertiary"])
            text_color = COLORS.get("badge_text", COLORS["text_secondary"])
            time_text = f"{time_text} left"
        
        self.time_badge.configure_badge(text=time_text, bg_color=badge_color, fg_color=text_color)
    
    def _show_usage_details(self, event=None):
        """Show a popup with detailed usage information."""
        summary = self.usage_limiter.get_status_summary()
        
        # Add extension info
        if self.usage_limiter.is_time_exhausted():
            summary += "\n\nClick 'Request More Time' to unlock additional usage."
        
        messagebox.showinfo("Usage Details", summary)
    
    def _show_lockout_overlay(self):
        """Show the lockout overlay when time is exhausted."""
        if self.lockout_frame is not None:
            return  # Already showing
        
        # Create overlay frame that covers the main content
        self.lockout_frame = tk.Frame(
            self.main_frame,
            bg=COLORS["bg_primary"]
        )
        self.lockout_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        # Center content
        content_frame = tk.Frame(self.lockout_frame, bg=COLORS["bg_primary"])
        content_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        # Expired icon/text
        expired_label = tk.Label(
            content_frame,
            text="⏱️",
            font=tkfont.Font(size=48),
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        expired_label.pack(pady=(0, 10))
        
        title_label = tk.Label(
            content_frame,
            text="Time Exhausted",
            font=self.font_title,
            fg=COLORS["time_badge_expired"],
            bg=COLORS["bg_primary"]
        )
        title_label.pack(pady=(0, 10))
        
        message_label = tk.Label(
            content_frame,
            text="Your trial time has run out.\nRequest more time to continue using BrainDock.",
            font=self.font_status,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"],
            justify="center"
        )
        message_label.pack(pady=(0, 20))
        
        # Request More Time button
        request_btn = RoundedButton(
            content_frame,
            text="Request More Time",
            command=self._show_password_dialog,
            bg_color=COLORS["accent_primary"],
            hover_color="#0EA5E9",
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=10,
            width=200,
            height=52
        )
        request_btn.pack()
        
        # Update badge to show expired state
        self._update_time_badge()
        
        # Disable start button
        self.start_stop_btn.configure(state=tk.DISABLED)
    
    def _hide_lockout_overlay(self):
        """Hide the lockout overlay after successful unlock."""
        if self.lockout_frame is not None:
            self.lockout_frame.destroy()
            self.lockout_frame = None
        
        self.is_locked = False
        self._update_time_badge()
        
        # Restore mode selector (hidden when session was running before time exhausted)
        self._show_mode_selector()
        
        # Re-enable start button and reset UI state
        self.start_stop_btn.configure(state=tk.NORMAL)
        self._reset_button_state()
        self._update_status("idle", "Ready to Start")
        
        logger.info("App unlocked - time extension granted")
    
    def _show_password_dialog(self):
        """Show dialog to enter unlock password."""
        # Create dialog window - scale based on screen size
        dialog = tk.Toplevel(self.root)
        dialog.title("Unlock More Time")
        dialog.configure(bg=COLORS["bg_primary"])
        dialog.resizable(False, False)
        
        # Size and position - scale based on screen and center
        dialog_width, dialog_height = self.scaling_manager.get_popup_size(350, 200)
        dialog.update_idletasks()
        x, y = self.scaling_manager.get_centered_position(dialog_width, dialog_height)
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # Make modal
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Content
        content = tk.Frame(dialog, bg=COLORS["bg_primary"])
        content.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)
        
        title = tk.Label(
            content,
            text="Enter Password",
            font=self.font_status,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        title.pack(pady=(0, 5))
        
        extension_time = self.usage_limiter.format_time(config.MVP_EXTENSION_SECONDS)
        subtitle = tk.Label(
            content,
            text=f"Enter the unlock password to add {extension_time} more",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        subtitle.pack(pady=(0, 15))
        
        # Password entry
        password_var = tk.StringVar()
        password_entry = tk.Entry(
            content,
            textvariable=password_var,
            show="•",
            font=self.font_status,
            width=25
        )
        password_entry.pack(pady=(0, 10))
        password_entry.focus_set()
        
        # Error label (hidden initially)
        error_label = tk.Label(
            content,
            text="",
            font=self.font_small,
            fg=COLORS["time_badge_expired"],
            bg=COLORS["bg_primary"]
        )
        error_label.pack(pady=(0, 10))
        
        def try_unlock():
            """Attempt to unlock with entered password."""
            password = password_var.get()
            
            if not password:
                error_label.configure(text="Please enter a password")
                return
            
            if self.usage_limiter.validate_password(password):
                # Grant extension
                extension_seconds = self.usage_limiter.grant_extension()
                extension_time = self.usage_limiter.format_time(extension_seconds)
                dialog.destroy()
                self._hide_lockout_overlay()
                messagebox.showinfo(
                    "Time Added",
                    f"{extension_time} has been added to your account.\n\n"
                    f"New balance: {self.usage_limiter.format_time(self.usage_limiter.get_remaining_seconds())}"
                )
            else:
                error_label.configure(text="Incorrect password")
                password_var.set("")
                password_entry.focus_set()
        
        # Bind Enter key
        password_entry.bind("<Return>", lambda e: try_unlock())
        
        # Buttons frame
        btn_frame = tk.Frame(content, bg=COLORS["bg_primary"])
        btn_frame.pack(fill=tk.X)
        
        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            command=dialog.destroy,
            font=self.font_small,
            width=10
        )
        cancel_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        unlock_btn = tk.Button(
            btn_frame,
            text="Unlock",
            command=try_unlock,
            font=self.font_small,
            width=10
        )
        unlock_btn.pack(side=tk.RIGHT)
    
    def _on_enter_key(self, event=None):
        """
        Handle Enter key press to start/stop session.
        
        Args:
            event: Key event (unused but required for binding)
        """
        # Don't toggle if locked or if focus is on an Entry widget (e.g., password dialog)
        if self.is_locked:
            return
        
        # Check if focus is on an Entry widget (don't intercept typing)
        focused_widget = self.root.focus_get()
        if isinstance(focused_widget, tk.Entry):
            return
        
        self._toggle_session()
    
    def _toggle_session(self):
        """Toggle between starting and stopping a session."""
        if not self.is_running:
            self._start_session()
        else:
            self._stop_session()
    
    def _toggle_pause(self):
        """Toggle between pausing and resuming a session."""
        if not self.is_paused:
            self._pause_session()
        else:
            self._resume_session()
    
    def _pause_session(self):
        """
        Pause the current session INSTANTLY.
        
        Logs a pause event, freezes the timer at the exact moment, and stops API calls.
        Uses int() truncation to floor the value (32.9s becomes 32s, not 33s).
        Forces immediate UI update to prevent any visual lag.
        """
        if not self.is_running or self.is_paused:
            return
        
        # CRITICAL: Set is_paused FIRST to prevent any timer updates from racing
        self.is_paused = True
        
        # Capture exact pause moment
        self.pause_start_time = datetime.now()
        
        # Calculate and freeze the active seconds at this exact moment
        # int() truncates (floors) - so 32.9s becomes 32s, not 33s
        if self.session_start_time:
            elapsed = (self.pause_start_time - self.session_start_time).total_seconds()
            self.frozen_active_seconds = int(elapsed - self.total_paused_seconds)
        
        # Log the pause event in the session
        if self.session and self.session_started:
            self.session.log_event(config.EVENT_PAUSED)
        
        # Reset unfocused alert tracking (shouldn't alert while paused)
        self.unfocused_start_time = None
        self.alerts_played = 0
        
        # Update UI instantly with frozen value
        self._update_status("paused", "Paused")
        self.pause_btn.configure(
            text="Resume Session",
            bg_color=COLORS["button_resume"],
            hover_color=COLORS["button_resume_hover"]
        )
        
        # Display frozen timer value immediately
        hours = self.frozen_active_seconds // 3600
        minutes = (self.frozen_active_seconds % 3600) // 60
        secs = self.frozen_active_seconds % 60
        self.timer_label.configure(text=f"{hours:02d}:{minutes:02d}:{secs:02d}")
        
        # FORCE IMMEDIATE UI REFRESH - ensures display updates before any other events
        self.root.update_idletasks()
        
        # Update usage badge
        self._update_time_badge()
        
        logger.info("Session paused")
        print(f"⏸ Session paused ({self.pause_start_time.strftime('%I:%M %p')})")
    
    def _resume_session(self):
        """
        Resume the paused session.
        
        Calculates pause duration with full precision, logs return to present state.
        """
        if not self.is_running or not self.is_paused:
            return
        
        resume_time = datetime.now()
        
        # Calculate pause duration with full precision (no rounding)
        if self.pause_start_time:
            pause_duration = (resume_time - self.pause_start_time).total_seconds()
            self.total_paused_seconds += pause_duration
        
        self.is_paused = False
        self.pause_start_time = None
        self.frozen_active_seconds = 0  # Clear frozen value
        
        # Log return to present state in the session
        if self.session and self.session_started:
            self.session.log_event(config.EVENT_PRESENT)
        
        # Update UI
        self._update_status("focused", "Focused")
        self.pause_btn.configure(
            text="Pause Session",
            bg_color=COLORS["button_pause"],
            hover_color=COLORS["button_pause_hover"]
        )
        
        logger.info("Session resumed")
        print(f"▶ Session resumed ({resume_time.strftime('%I:%M %p')})")
    
    def _start_session(self):
        """Start a new focus session."""
        # Check if locked due to usage limit
        if self.is_locked:
            messagebox.showwarning(
                "Time Exhausted",
                "Your trial time has run out.\n\n"
                "Click 'Request More Time' to unlock additional usage."
            )
            return
        
        # Check if there's enough time remaining
        if self.usage_limiter.is_time_exhausted():
            self.is_locked = True
            self._show_lockout_overlay()
            return
        
        # Verify API key exists (only required for camera modes)
        needs_camera = self.monitoring_mode in (config.MODE_CAMERA_ONLY, config.MODE_BOTH)
        if needs_camera:
            # Check for the correct API key based on vision provider
            if config.VISION_PROVIDER == "gemini":
                if not config.GEMINI_API_KEY:
                    messagebox.showerror(
                        "API Key Required",
                        "Gemini API key not found!\n\n"
                        "Please set GEMINI_API_KEY in your .env file.\n"
                        "Get your key from: https://aistudio.google.com/apikey"
                    )
                    return
            else:
                if not config.OPENAI_API_KEY:
                    messagebox.showerror(
                        "API Key Required",
                        "OpenAI API key not found!\n\n"
                        "Please set OPENAI_API_KEY in your .env file.\n"
                        "Get your key from: https://platform.openai.com/api-keys"
                    )
                    return

            # Check macOS camera permission status before trying to open camera
            if sys.platform == "darwin":
                permission_status = check_macos_camera_permission()
                if permission_status == "denied":
                    # Permission was previously denied - show dialog to guide user
                    self._show_camera_permission_denied()
                    return
                elif permission_status == "restricted":
                    # Restricted by parental controls or device policy
                    messagebox.showerror(
                        "Camera Restricted",
                        "Camera access is restricted on this device.\n\n"
                        "This may be due to parental controls or device policy.\n"
                        "Please check with your administrator."
                    )
                    return
                # For "not_determined", "authorized", or "unknown" - proceed normally
                # "not_determined" will trigger the macOS permission prompt when camera opens

        # Pre-check screen (Accessibility) permission for screen modes
        needs_screen = self.monitoring_mode in (config.MODE_SCREEN_ONLY, config.MODE_BOTH)
        if needs_screen and sys.platform == "darwin":
            logger.info("Checking Accessibility permission for screen monitoring...")
            has_permission = check_macos_accessibility_permission()
            logger.info(f"Accessibility permission check result: {has_permission}")
            
            if not has_permission:
                # Permission not granted - show dialog
                logger.warning("Accessibility/Automation permission not granted, showing dialog")
                result = messagebox.askyesno(
                    "Screen Monitoring Permission Required",
                    "Screen monitoring requires these permissions:\n\n"
                    "1. ACCESSIBILITY:\n"
                    "   Privacy & Security → Accessibility\n"
                    "   Add BrainDock and enable checkbox\n\n"
                    "2. AUTOMATION (System Events):\n"
                    "   Privacy & Security → Automation\n"
                    "   Enable 'System Events' under BrainDock\n\n"
                    "After enabling both, RESTART BrainDock.\n\n"
                    "Would you like to open System Settings?"
                )
                if result:
                    open_macos_accessibility_settings()
                return

        # Initialize session (but don't start yet - wait for first detection)
        self.session = Session()
        self.session_started = False  # Will start on first detection
        self.session_start_time = None  # Timer starts after bootup
        self.is_running = True
        self.should_stop.clear()
        
        # Reset pause state for new session
        self.is_paused = False
        self.pause_start_time = None
        self.total_paused_seconds = 0.0
        self.frozen_active_seconds = 0
        
        # Reset unfocused alert tracking for new session
        self.unfocused_start_time = None
        self.alerts_played = 0
        
        # Reset distraction counters
        self.gadget_detection_count = 0
        self.screen_distraction_count = 0
        
        # Reset shared detection state for new session
        with self._state_lock:
            self._camera_state = None
            self._screen_state = None
        
        # Reset stat cards to zero values (clear any stale data from previous session)
        self._reset_stat_cards()
        
        # --- Layout Transition: Active State ---
        # Hide stats panel (Left)
        self.stats_container.pack_forget()
        
        # Hide mode selector (Camera/Screen/Both buttons)
        self._hide_mode_selector()
        
        # Center controls panel (Right)
        # Since stats are gone, controls_container is the only child of content_frame.
        # content_frame uses place(anchor="center"), so it will shrink to fit controls and re-center.
        # We just need to ensure controls_container is packed correctly.
        self.controls_container.pack(side=tk.TOP, anchor="center")
        
        # Update sub-label to show session mode
        mode_labels = {
            config.MODE_CAMERA_ONLY: "Camera Session",
            config.MODE_SCREEN_ONLY: "Screen Session",
            config.MODE_BOTH: "Camera + Screen Session"
        }
        mode_label = mode_labels.get(self.monitoring_mode, "Session Duration")
        self.timer_sub_label.config(text=mode_label)
        
        # Update UI - show both buttons (pause on top, stop below)
        self._update_status("booting", "⚡️ Booting Up...", emoji="⚡️")
        
        # Repack buttons in correct order: pause on top, stop below with gap
        self.start_stop_btn.pack_forget()  # Remove stop button temporarily
        self.pause_btn.pack(pady=(0, 15))  # Pause button first with gap below
        self.pause_btn.configure(
            text="Pause Session",
            bg_color=COLORS["button_pause"],
            hover_color=COLORS["button_pause_hover"]
        )
        self.start_stop_btn.pack()  # Stop button below
        self.start_stop_btn.configure(
            text="Stop Session",
            bg_color=COLORS["button_stop"],
            hover_color=COLORS["button_stop_hover"]  # Explicit red hover for stop
        )
        
        # Start appropriate detection thread(s) based on monitoring mode
        if self.monitoring_mode == config.MODE_CAMERA_ONLY:
            # Camera only mode (existing behavior)
            self.detection_thread = threading.Thread(
                target=self._detection_loop,
                daemon=True
            )
            self.detection_thread.start()
        elif self.monitoring_mode == config.MODE_SCREEN_ONLY:
            # Screen only mode
            self.detection_thread = threading.Thread(
                target=self._screen_detection_loop,
                daemon=True
            )
            self.detection_thread.start()
        else:
            # Both camera and screen monitoring
            self.detection_thread = threading.Thread(
                target=self._detection_loop,
                daemon=True
            )
            self.detection_thread.start()
            
            self.screen_detection_thread = threading.Thread(
                target=self._screen_detection_loop,
                daemon=True
            )
            self.screen_detection_thread.start()
        
        logger.info(f"Session started via GUI (mode: {self.monitoring_mode})")
    
    def _stop_session(self):
        """Stop the current session INSTANTLY and auto-generate report."""
        if not self.is_running:
            return
        
        # Capture stop time IMMEDIATELY when user clicks stop
        stop_time = datetime.now()
        
        # If paused, finalize the pause duration before stopping (full precision)
        if self.is_paused and self.pause_start_time:
            pause_duration = (stop_time - self.pause_start_time).total_seconds()
            self.total_paused_seconds += pause_duration
            self.is_paused = False
            self.pause_start_time = None
        
        # Signal thread to stop
        self.should_stop.set()
        self.is_running = False
        
        # Wait for detection thread(s) to finish and clean up references
        if self.detection_thread and self.detection_thread.is_alive():
            self.detection_thread.join(timeout=2.0)
        self.detection_thread = None  # Clean up reference for garbage collection
        
        if self.screen_detection_thread and self.screen_detection_thread.is_alive():
            self.screen_detection_thread.join(timeout=2.0)
        self.screen_detection_thread = None  # Clean up reference for garbage collection
        
        # Show mode selector again
        self._show_mode_selector()
        
        # --- Layout Transition: Idle State ---
        # Restore stats panel (Left)
        # We need to repack both to ensure correct order
        self.controls_container.pack_forget()
        
        self.stats_container.pack(side=tk.LEFT, padx=(0, 40), anchor="n")
        self.controls_container.pack(side=tk.LEFT, anchor="n")
        
        # Reset sub-label to default
        self.timer_sub_label.config(text="Session Duration")
        
        # End session (only if it was actually started after first detection)
        if self.session and self.session_started and self.session_start_time:
            # Calculate and record session duration (excluding paused time)
            # Use full precision until final int conversion for usage tracking
            total_elapsed = (stop_time - self.session_start_time).total_seconds()
            active_duration = int(total_elapsed - self.total_paused_seconds)
            # Ensure at least 1 second is recorded for any valid session
            active_duration = max(1, active_duration)
            self.usage_limiter.record_usage(active_duration)
            
            self.session.end(stop_time)  # Use the captured stop time
            self.usage_limiter.end_session()
            
            # Update stat cards with final values (ensures stats are accurate, not 1s stale)
            self._finalize_stat_cards()
        
        # Hide pause button when session stops
        self.pause_btn.pack_forget()
        
        # Update UI to show generating status
        self._update_status("idle", "Generating Reports...")
        self.start_stop_btn.configure(
            text="Generating...",
            state=tk.DISABLED
        )
        self.root.update()
        
        # Update time badge after session ends
        self._update_time_badge()
        
        logger.info("Session stopped via GUI")
        
        # Auto-generate report
        self._generate_report()
    
    def _detection_loop(self):
        """
        Main detection loop running in a separate thread.
        
        Captures frames from camera and analyzes them using Vision API.
        Also handles unfocused alerts at configured thresholds and usage tracking.
        """
        try:
            detector = create_vision_detector()
            
            with CameraCapture() as camera:
                if not camera.is_opened:
                    self.root.after(0, lambda: self._show_camera_error())
                    return
                
                last_detection_time = time.time()
                
                for frame in camera.frame_iterator():
                    if self.should_stop.is_set():
                        break
                    
                    # Skip all detection when paused (no API calls)
                    if self.is_paused:
                        time.sleep(0.1)  # Sleep longer when paused to reduce CPU
                        continue
                    
                    # Throttle detection to configured FPS
                    current_time = time.time()
                    time_since_detection = current_time - last_detection_time
                    
                    # Note: Time exhaustion is checked in _update_timer to stay in sync with display
                    
                    if time_since_detection >= (1.0 / config.DETECTION_FPS):
                        # Perform detection using OpenAI Vision
                        detection_state = detector.get_detection_state(frame)
                        
                        # Re-check stop signal after detection (API call takes 2-3 seconds)
                        # User may have clicked Stop during this time
                        if self.should_stop.is_set():
                            break
                        
                        # Also check if paused during detection (user may have paused during API call)
                        if self.is_paused:
                            continue
                        
                        # Start session on first successful detection (eliminates bootup time)
                        if not self.session_started:
                            self.session.start()
                            # IMPORTANT: Use the SAME start time as session for consistency
                            # This ensures GUI timer matches PDF report duration exactly
                            self.session_start_time = self.session.start_time
                            self.session_started = True
                            logger.info("First detection complete - session timer started")
                        
                        # Store camera detection state for priority resolution
                        with self._state_lock:
                            self._camera_state = detection_state
                        
                        # Get raw camera event type (for gadget counter tracking)
                        raw_camera_event = get_event_type(detection_state)
                        
                        # Determine final event type based on monitoring mode
                        if self.monitoring_mode == config.MODE_BOTH:
                            # In "both" mode, use priority resolution
                            event_type = self._resolve_priority_status()
                        else:
                            # In camera-only mode, use raw camera event
                            event_type = raw_camera_event
                        
                        # Check for state change to gadget distraction (increment counter)
                        # Use raw camera event to track actual gadget detections
                        if self.session and raw_camera_event == config.EVENT_GADGET_SUSPECTED:
                            if self.session.current_state != config.EVENT_GADGET_SUSPECTED:
                                self.gadget_detection_count += 1
                        
                        # Check if user is unfocused (based on priority-resolved event)
                        is_unfocused = event_type in (
                            config.EVENT_AWAY, 
                            config.EVENT_GADGET_SUSPECTED,
                            config.EVENT_SCREEN_DISTRACTION
                        )
                        
                        if is_unfocused:
                            # Start tracking if not already
                            if self.unfocused_start_time is None:
                                self.unfocused_start_time = current_time
                                self.alerts_played = 0
                                logger.debug("Started tracking unfocused time")
                            
                            # Check if we should play an alert
                            unfocused_duration = current_time - self.unfocused_start_time
                            alert_times = config.UNFOCUSED_ALERT_TIMES
                            
                            # Play alert if duration exceeds next threshold (and we haven't played all 3)
                            if (self.alerts_played < len(alert_times) and 
                                unfocused_duration >= alert_times[self.alerts_played]):
                                self._play_unfocused_alert()
                                self.alerts_played += 1
                        else:
                            # User is focused - reset tracking
                            if self.unfocused_start_time is not None:
                                logger.debug("User refocused - resetting alert tracking")
                            self.unfocused_start_time = None
                            self.alerts_played = 0
                        
                        # Log event (priority-resolved in "both" mode)
                        if self.session:
                            self.session.log_event(event_type)
                        
                        # Update UI status (thread-safe)
                        self._update_detection_status(event_type)
                        
                        last_detection_time = current_time
                    
                    # Small sleep to prevent CPU overload
                    time.sleep(0.05)
                    
        except Exception as e:
            logger.error(f"Detection loop error: {e}")
            self.root.after(0, lambda: self._show_detection_error(str(e)))
    
    def _screen_detection_loop(self):
        """
        Screen monitoring detection loop running in a separate thread.
        
        Checks active window and browser URL against the blocklist.
        Does NOT use AI API calls - purely local pattern matching.
        """
        try:
            logger.info("Screen detection loop starting...")
            window_detector = WindowDetector()
            
            # Check permissions on first run
            logger.debug("Checking screen monitoring permission...")
            if not window_detector.check_permission():
                logger.warning("Screen monitoring permission check failed")
                instructions = window_detector.get_permission_instructions()
                self.root.after(0, lambda: self._show_screen_permission_error(instructions))
                return
            
            logger.info("Screen monitoring permission granted, starting detection loop")
            
            last_screen_check = time.time()
            
            # For screen-only mode, we need to start the session on first check
            if self.monitoring_mode == config.MODE_SCREEN_ONLY:
                # Start session immediately for screen-only mode
                if not self.session_started:
                    self.session.start()
                    # IMPORTANT: Use the SAME start time as session for consistency
                    # This ensures GUI timer matches PDF report duration exactly
                    self.session_start_time = self.session.start_time
                    self.session_started = True
                    logger.info("Screen-only mode - session timer started")
                    # Update UI to show focused status
                    self.root.after(0, lambda: self._update_status("focused", "Focused"))
            
            while not self.should_stop.is_set():
                # Skip when paused
                if self.is_paused:
                    time.sleep(0.1)
                    continue
                
                current_time = time.time()
                time_since_check = current_time - last_screen_check
                
                if time_since_check >= config.SCREEN_CHECK_INTERVAL:
                    # Get current screen state (with optional AI fallback)
                    if self.use_ai_fallback:
                        screen_state = get_screen_state_with_ai_fallback(
                            self.blocklist,
                            use_ai_fallback=True
                        )
                    else:
                        screen_state = get_screen_state(self.blocklist)
                    
                    if self.should_stop.is_set():
                        break
                    
                    if self.is_paused:
                        continue
                    
                    # Store screen state for priority resolution
                    with self._state_lock:
                        self._screen_state = screen_state
                    
                    # Track screen distraction count (regardless of priority resolution)
                    is_screen_distracted = screen_state.get("is_distracted", False)
                    if is_screen_distracted and self.session and self.session_started:
                        if self.session.current_state != config.EVENT_SCREEN_DISTRACTION:
                            self.screen_distraction_count += 1
                    
                    # Determine final event type based on monitoring mode
                    if self.monitoring_mode == config.MODE_BOTH:
                        # In "both" mode, use priority resolution
                        # The camera loop handles logging, so we only update UI here
                        # when screen state changes and could affect the priority
                        event_type = self._resolve_priority_status()
                        
                        # Update UI based on priority-resolved event
                        if event_type == config.EVENT_SCREEN_DISTRACTION:
                            distraction_source = screen_state.get("distraction_source", "Unknown")
                            distraction_label = self._get_distraction_label(distraction_source)
                            self.root.after(0, lambda lbl=distraction_label: self._update_status(
                                "screen", lbl
                            ))
                        # Note: In "both" mode, camera loop handles logging and other UI updates
                        # Screen loop only needs to update UI when screen distraction has priority
                        
                    elif self.monitoring_mode == config.MODE_SCREEN_ONLY:
                        # In screen-only mode, handle logging and UI directly
                        if is_screen_distracted:
                            distraction_source = screen_state.get("distraction_source", "Unknown")
                            
                            # Log event
                            if self.session and self.session_started:
                                self.session.log_event(config.EVENT_SCREEN_DISTRACTION)
                            
                            # Determine if it's a website or app distraction
                            distraction_label = self._get_distraction_label(distraction_source)
                            
                            # Update UI (thread-safe)
                            self.root.after(0, lambda lbl=distraction_label: self._update_status(
                                "screen", lbl
                            ))
                            
                            # Track for alerts
                            if self.unfocused_start_time is None:
                                self.unfocused_start_time = current_time
                                self.alerts_played = 0
                                logger.debug("Started tracking screen distraction time")
                            
                            # Check for escalating alerts
                            unfocused_duration = current_time - self.unfocused_start_time
                            alert_times = config.UNFOCUSED_ALERT_TIMES
                            
                            if (self.alerts_played < len(alert_times) and
                                unfocused_duration >= alert_times[self.alerts_played]):
                                self._play_unfocused_alert()
                                self.alerts_played += 1
                        else:
                            # Not distracted in screen-only mode
                            if self.session and self.session_started:
                                self.session.log_event(config.EVENT_PRESENT)
                            self.root.after(0, lambda: self._update_status("focused", "Focused"))
                            
                            # Reset alert tracking
                            if self.unfocused_start_time is not None:
                                logger.debug("Screen refocused - resetting alert tracking")
                            self.unfocused_start_time = None
                            self.alerts_played = 0
                    
                    last_screen_check = current_time
                
                # Small sleep to prevent CPU overload
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Screen detection loop error: {e}")
            self.root.after(0, lambda: self._show_detection_error(f"Screen monitoring: {str(e)}"))
    
    def _show_screen_permission_error(self, instructions: str):
        """
        Show an error message when screen monitoring permissions are missing.
        Uses simple messagebox.askyesno() style like the PDF popup.
        
        Args:
            instructions: Platform-specific permission instructions
        """
        # Reset UI first
        self._reset_to_idle_state()
        self._update_status("idle", "Ready to Start")
        
        if sys.platform == "darwin":
            result = messagebox.askyesno(
                "Accessibility Permission Required",
                "Screen monitoring requires Accessibility permission.\n\n"
                "To enable:\n"
                "1. Open System Settings\n"
                "2. Go to Privacy & Security → Accessibility\n"
                "3. Enable BrainDock in the list\n"
                "4. Restart BrainDock\n\n"
                "Would you like to open System Settings?"
            )
            
            if result:
                open_macos_accessibility_settings()
        else:
            messagebox.showerror(
                "Screen Monitoring Permission Required",
                f"Screen monitoring cannot access window information.\n\n{instructions}"
            )
    
    def _handle_time_exhausted(self):
        """
        Handle time exhaustion during a running session.
        
        Stops the session, generates PDF report, then shows lockout overlay.
        """
        # Capture stop time immediately
        stop_time = datetime.now()
        
        # Stop the current session
        if self.is_running:
            # If paused, finalize the pause duration before stopping (full precision)
            if self.is_paused and self.pause_start_time:
                pause_duration = (stop_time - self.pause_start_time).total_seconds()
                self.total_paused_seconds += pause_duration
                self.is_paused = False
                self.pause_start_time = None
            
            self.should_stop.set()
            self.is_running = False
            
            # Wait for detection thread(s) to finish and clean up references
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=2.0)
            self.detection_thread = None  # Clean up reference for garbage collection
            
            if self.screen_detection_thread and self.screen_detection_thread.is_alive():
                self.screen_detection_thread.join(timeout=2.0)
            self.screen_detection_thread = None  # Clean up reference for garbage collection
            
            # End session with captured stop time
            if self.session and self.session_started and self.session_start_time:
                # Calculate and record session duration (excluding paused time)
                # Use full precision until final int conversion for usage tracking
                total_elapsed = (stop_time - self.session_start_time).total_seconds()
                active_duration = int(total_elapsed - self.total_paused_seconds)
                # Ensure at least 1 second is recorded for any valid session
                active_duration = max(1, active_duration)
                self.usage_limiter.record_usage(active_duration)
                
                self.session.end(stop_time)
                self.usage_limiter.end_session()
                
                # Update stat cards with final values
                self._finalize_stat_cards()
            
            # Hide pause button when session stops
            self.pause_btn.pack_forget()
            
            # Update UI to show generating status
            self._update_status("idle", "Generating Reports...")
            self.start_stop_btn.configure(
                text="Generating...",
                state=tk.DISABLED
            )
            self.root.update()
            
            logger.info("Session stopped due to time exhaustion - generating report")
            
            # Generate PDF report before lockout
            self._generate_report_for_lockout()
        
        # Show lockout
        self.is_locked = True
        self._show_lockout_overlay()
        
        # Notify user (after report generation so they know report was saved)
        messagebox.showwarning(
            "Time Exhausted",
            "Your trial time has run out.\n\n"
            "Your session report has been saved to Downloads.\n\n"
            "Click 'Request More Time' to unlock additional usage."
        )
    
    def _generate_report_for_lockout(self):
        """
        Generate PDF report when session ends due to time exhaustion.
        
        Similar to _generate_report but without prompting to open the file.
        """
        if not self.session or not self.session_started:
            self._reset_button_state()
            return
        
        try:
            # Compute statistics
            stats = compute_statistics(
                self.session.events,
                self.session.get_duration()
            )
            
            # Generate PDF (combined summary + logs)
            report_path = generate_report(
                stats,
                self.session.session_id,
                self.session.start_time,
                self.session.end_time
            )
            
            # Reset UI
            self._reset_button_state()
            
            logger.info(f"Report generated (time exhausted): {report_path}")
            
        except Exception as e:
            logger.error(f"Report generation failed during lockout: {e}")
            self._reset_button_state()
    
    def _resolve_priority_status(self) -> str:
        """
        Resolve the current status based on priority rules.
        
        Priority order (highest to lowest):
        1. Paused - User manually paused session
        2. Away - Person not present or not at working distance
        3. Screen distraction - On a distracting app/website
        4. Gadget - Actively using phone/tablet/controller
        5. Focused - Present at desk, no distractions (default)
        
        Returns:
            Event type constant representing the prioritized status
        """
        with self._state_lock:
            # Priority 1: Paused (absolute highest priority)
            if self.is_paused:
                return config.EVENT_PAUSED
            
            # Priority 2: Away (from camera detection)
            if self._camera_state:
                camera_event = get_event_type(self._camera_state)
                if camera_event == config.EVENT_AWAY:
                    return config.EVENT_AWAY
            
            # Priority 3: Screen distraction
            if self._screen_state and self._screen_state.get("is_distracted"):
                return config.EVENT_SCREEN_DISTRACTION
            
            # Priority 4: Gadget (from camera detection)
            if self._camera_state:
                camera_event = get_event_type(self._camera_state)
                if camera_event == config.EVENT_GADGET_SUSPECTED:
                    return config.EVENT_GADGET_SUSPECTED
            
            # Priority 5: Focused (default - person present, no distractions)
            return config.EVENT_PRESENT
    
    def _update_detection_status(self, event_type: str):
        """
        Update the status display based on detection result.
        
        Args:
            event_type: Type of event detected
        """
        status_map = {
            config.EVENT_PRESENT: ("focused", "Focused"),
            config.EVENT_AWAY: ("away", "Away from Desk"),
            config.EVENT_GADGET_SUSPECTED: ("gadget", "On another gadget"),
            config.EVENT_SCREEN_DISTRACTION: ("screen", "Screen distraction"),
        }
        
        status, text = status_map.get(event_type, ("idle", "Unknown"))
        
        # Schedule UI update on main thread (capture values to avoid closure issues)
        self.root.after(0, lambda s=status, t=text: self._update_status(s, t))
    
    def _get_distraction_label(self, distraction_source: str) -> str:
        """
        Determine the appropriate label for a distraction source.
        
        Args:
            distraction_source: The pattern that triggered the distraction
            
        Returns:
            Formatted label like "Website: example.com" or "App: Steam"
        """
        # Common TLDs that indicate a website
        website_indicators = (
            '.com', '.org', '.net', '.edu', '.gov', '.io', '.co', '.tv',
            '.gg', '.app', '.dev', '.me', '.info', '.biz', '.xyz',
            '://'  # URL protocol indicator
        )
        
        source = distraction_source or "Unknown"
        source_lower = source.lower()
        
        # Check if it looks like a website/URL
        is_website = any(indicator in source_lower for indicator in website_indicators)
        
        # Format the label
        if is_website:
            prefix = "Website"
            display_source = source  # Keep websites as-is
        else:
            prefix = "App"
            # Capitalize app names properly (first letter of each word)
            display_source = source.title()
        
        # Truncate if too long
        if len(display_source) > 18:
            return f"{prefix}: {display_source[:18]}..."
        else:
            return f"{prefix}: {display_source}"
    
    def _update_status(self, status: str, text: str, emoji: str = None):
        """
        Update the status badge with matching background color.
        
        Args:
            status: Status type (idle, focused, away, gadget, screen, paused)
            text: Display text
            emoji: Optional emoji to show instead of the colored dot (unused now)
        """
        with self.ui_lock:
            self.current_status = status
            fg_color = self._get_current_status_color()
            bg_color = self._get_status_bg_color(status)
            
            # Update camera card instead of badge (no prefix)
            if hasattr(self, 'camera_card'):
                self.camera_card.configure_card(
                    text=text,
                    text_color=fg_color,
                    bg_color=bg_color
                )
    
    def _update_timer(self):
        """
        Update the timer display frequently for instant pause feel.
        
        Timer updates every 100ms for smooth display and instant pause response.
        Usage badge and other expensive operations update every second.
        """
        if self.is_running and self.session_start_time:
            # When paused, use frozen value - don't recalculate
            if self.is_paused:
                active_seconds = self.frozen_active_seconds
            else:
                # Calculate active time (total elapsed minus all paused time)
                elapsed = (datetime.now() - self.session_start_time).total_seconds()
                active_seconds = int(elapsed - self.total_paused_seconds)
            
            hours = active_seconds // 3600
            minutes = (active_seconds % 3600) // 60
            secs = active_seconds % 60
            
            time_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
            self.timer_label.configure(text=time_str)
            
            # Only check usage limits and update badge every second (not every 100ms)
            # This reduces overhead while keeping timer display smooth
            if not self.is_paused and not self.is_locked:
                # Track when we last did expensive operations
                current_second = active_seconds
                if not hasattr(self, '_last_usage_check_second'):
                    self._last_usage_check_second = -1
                
                if current_second != self._last_usage_check_second:
                    self._last_usage_check_second = current_second
                    self._update_time_badge()
                    self._update_stat_cards()
                    
                    # Check if time exhausted
                    base_remaining = self.usage_limiter.get_remaining_seconds()
                    actual_remaining = base_remaining - active_seconds
                    if actual_remaining <= 0:
                        logger.warning("Usage time exhausted during session")
                        self._handle_time_exhausted()
                        return  # Don't schedule next update, session is ending
        
        # Schedule next update at 100ms for smooth display and instant pause response
        self.root.after(100, self._update_timer)
    
    def _play_unfocused_alert(self):
        """
        Play the custom BrainDock alert sound and show notification popup.
        
        Uses the custom MP3 file in data/braindock_alert_sound.mp3
        Cross-platform playback:
        - macOS: afplay (native MP3 support)
        - Windows: start command with default media player
        - Linux: mpg123 or ffplay
        
        Also displays a supportive notification popup that auto-dismisses.
        """
        # Get the alert data for this level (badge_text, message)
        alert_index = self.alerts_played  # 0, 1, or 2
        badge_text, message = config.UNFOCUSED_ALERT_MESSAGES[alert_index]
        
        def play_sound():
            # Path to custom alert sound (bundled with app)
            # Windows uses WAV (Media.SoundPlayer only supports WAV)
            # macOS/Linux use MP3
            if sys.platform == "win32":
                sound_file = config.BUNDLED_DATA_DIR / "braindock_alert_sound.wav"
            else:
                sound_file = config.BUNDLED_DATA_DIR / "braindock_alert_sound.mp3"
            
            if not sound_file.exists():
                logger.warning(f"Alert sound file not found: {sound_file}")
                return
            
            try:
                if sys.platform == "darwin":
                    # macOS - afplay supports MP3
                    subprocess.Popen(
                        ["afplay", str(sound_file)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                elif sys.platform == "win32":
                    # Windows - use powershell to play WAV file
                    subprocess.Popen(
                        ["powershell", "-c", f'(New-Object Media.SoundPlayer "{sound_file}").PlaySync()'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    # Linux - try mpg123 first, fallback to ffplay
                    try:
                        subprocess.Popen(
                            ["mpg123", "-q", str(sound_file)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                    except FileNotFoundError:
                        subprocess.Popen(
                            ["ffplay", "-nodisp", "-autoexit", str(sound_file)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
            except Exception as e:
                logger.debug(f"Sound playback error: {e}")
        
        # Play sound first (synchronously start the process)
        play_sound()
        
        # Show notification popup immediately after sound starts (capture values)
        self.root.after(100, lambda b=badge_text, m=message: self._show_alert_popup(b, m))
        
        logger.info(f"Unfocused alert #{self.alerts_played + 1} played")
    
    def _show_alert_popup(self, badge_text: str, message: str):
        """
        Display the notification popup with badge and message.
        
        Args:
            badge_text: The badge/pill text (e.g., "Focus paused")
            message: The main supportive message to show
        """
        try:
            NotificationPopup(
                self.root,
                badge_text=badge_text,
                message=message,
                duration_seconds=config.ALERT_POPUP_DURATION
            )
        except Exception as e:
            logger.error(f"Failed to show notification popup: {e}")
    
    def _dismiss_alert_popup(self):
        """Dismiss any active notification popup when user refocuses."""
        if NotificationPopup._active_popup is not None:
            NotificationPopup._active_popup.dismiss()
            logger.debug("Dismissed alert popup - user refocused")
    
    def _generate_report(self):
        """Generate PDF report for the completed session."""
        if not self.session or not self.session_started:
            # No session or session never got first detection
            self._reset_button_state()
            self._update_status("idle", "Ready to Start")
            if not self.session_started:
                messagebox.showinfo(
                    "No Session Data",
                    "Session was stopped before any detection occurred.\n"
                    "No report generated."
                )
            return
        
        try:
            # Compute statistics
            stats = compute_statistics(
                self.session.events,
                self.session.get_duration()
            )
            
            # Generate PDF (combined summary + logs)
            report_path = generate_report(
                stats,
                self.session.session_id,
                self.session.start_time,
                self.session.end_time
            )
            
            # Reset UI
            self._reset_button_state()
            self._update_status("idle", "Report Generated!")
            
            # Show success and offer to open report
            result = messagebox.askyesno(
                "Report Generated",
                f"Report saved to:\n\n"
                f"{report_path.name}\n\n"
                f"Location: {report_path.parent}\n\n"
                "Would you like to open the report?"
            )
            
            if result:
                self._open_file(report_path)
            
            # Reset status after showing dialog
            self._update_status("idle", "Ready to Start")
            
            logger.info(f"Report generated: {report_path}")
            
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            self._reset_button_state()
            self._update_status("idle", "Ready to Start")
            messagebox.showerror(
                "Report Error",
                f"Failed to generate report:\n{str(e)}"
            )
    
    def _reset_button_state(self):
        """Reset the button to its initial state."""
        self.start_stop_btn.configure(
            text="Start Session",
            bg_color=COLORS["button_start"],
            hover_color=COLORS["status_focused"],
            state=tk.NORMAL
        )
        self.timer_label.configure(text="00:00:00")
        self.timer_sub_label.configure(text="Session Duration")
    
    def _reset_to_idle_state(self):
        """
        Fully reset the UI to idle state.
        
        Used when session fails to start (e.g., camera permission denied).
        Resets all UI elements that were changed during session start attempt.
        """
        # Reset running state
        self.is_running = False
        self.session_started = False
        self.session = None
        self.should_stop.clear()
        
        # Reset pause state
        self.is_paused = False
        self.pause_start_time = None
        self.total_paused_seconds = 0.0
        self.frozen_active_seconds = 0
        
        # Hide pause button (was shown during session start)
        self.pause_btn.pack_forget()
        
        # Show mode selector (was hidden during session start)
        self._show_mode_selector()
        
        # Restore stats panel layout
        self.controls_container.pack_forget()
        self.stats_container.pack(side=tk.LEFT, padx=(0, 40), anchor="n")
        self.controls_container.pack(side=tk.LEFT, anchor="n")
        
        # Reset button state
        self._reset_button_state()
    
    def _open_file(self, filepath: Path):
        """
        Open a file with the system's default application.
        
        Args:
            filepath: Path to the file to open
        """
        try:
            if sys.platform == "darwin":  # macOS
                subprocess.run(["open", str(filepath)], check=True)
            elif sys.platform == "win32":  # Windows
                os.startfile(str(filepath))
            else:  # Linux
                subprocess.run(["xdg-open", str(filepath)], check=True)
        except Exception as e:
            logger.error(f"Failed to open file: {e}")

    def _show_camera_permission_denied(self):
        """
        Show dialog when macOS camera permission was previously denied.
        Uses simple messagebox.askyesno() style like the PDF popup.
        """
        result = messagebox.askyesno(
            "Camera Permission Required",
            "Camera access was denied.\n\n"
            "BrainDock needs camera access for focus tracking.\n\n"
            "To enable:\n"
            "1. Open System Settings\n"
            "2. Go to Privacy & Security → Camera\n"
            "3. Enable BrainDock in the list\n"
            "4. Restart BrainDock\n\n"
            "Would you like to open System Settings?"
        )
        
        if result:
            open_macos_camera_settings()

    def _show_camera_error(self):
        """Show camera access error dialog with platform-specific instructions."""
        # Fully reset UI to idle state (including pause button, stats panel, etc.)
        self._reset_to_idle_state()
        self._update_status("idle", "Ready to Start")
        
        if sys.platform == "darwin":
            # macOS-specific - use askyesno like PDF popup
            result = messagebox.askyesno(
                "Camera Permission Required",
                "Failed to access webcam.\n\n"
                "On macOS, you need to grant camera permission:\n\n"
                "1. Open System Settings\n"
                "2. Go to Privacy & Security → Camera\n"
                "3. Enable BrainDock in the list\n"
                "4. Restart BrainDock\n\n"
                "Would you like to open System Settings?"
            )
            
            if result:
                open_macos_camera_settings()
        else:
            message = (
                "Failed to access webcam.\n\n"
                "Please check:\n"
                "• Camera is connected\n"
                "• Camera permissions are granted\n"
                "• No other app is using the camera"
            )
            messagebox.showerror("Camera Error", message)
    
    def _show_detection_error(self, error: str):
        """
        Show detection error dialog.
        
        Args:
            error: Error message
        """
        # Fully reset UI to idle state (including pause button, stats panel, etc.)
        self._reset_to_idle_state()
        self._update_status("idle", "Ready to Start")
        messagebox.showerror(
            "Detection Error",
            f"An error occurred during detection:\n\n{error}"
        )
    
    def _on_close(self):
        """Handle window close event."""
        if self.is_running:
            result = messagebox.askyesno(
                "Session Active",
                "A session is currently running.\n\n"
                "Would you like to stop the session and exit?\n"
                "(Report will be generated)"
            )
            if not result:
                return
            
            # Capture stop time immediately
            stop_time = datetime.now()
            
            # If paused, finalize the pause duration before stopping
            if self.is_paused and self.pause_start_time:
                pause_duration = (stop_time - self.pause_start_time).total_seconds()
                self.total_paused_seconds += pause_duration
                self.is_paused = False
                self.pause_start_time = None
            
            # Stop session
            self.should_stop.set()
            self.is_running = False
            
            # Wait for detection thread(s) to finish and clean up references
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=2.0)
            self.detection_thread = None  # Clean up reference for garbage collection
            
            if self.screen_detection_thread and self.screen_detection_thread.is_alive():
                self.screen_detection_thread.join(timeout=2.0)
            self.screen_detection_thread = None  # Clean up reference for garbage collection
            
            # End session and record usage with correct active duration
            if self.session and self.session_started and self.session_start_time:
                total_elapsed = (stop_time - self.session_start_time).total_seconds()
                active_duration = int(total_elapsed - self.total_paused_seconds)
                # Ensure at least 1 second is recorded for any valid session
                active_duration = max(1, active_duration)
                self.usage_limiter.record_usage(active_duration)
                self.session.end(stop_time)
                self.usage_limiter.end_session()
            elif self.session:
                self.session.end(stop_time)
        
        self.root.destroy()
    
    def run(self):
        """Start the GUI application main loop."""
        logger.info("Starting BrainDock GUI")
        self.root.mainloop()


def main():
    """Entry point for the GUI application."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format=config.LOG_FORMAT
    )
    
    # Suppress noisy third-party logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Check for existing instance (single instance enforcement)
    if not check_single_instance():
        existing_pid = get_existing_pid()
        pid_info = f" (PID: {existing_pid})" if existing_pid else ""
        
        # Show error dialog
        root = tk.Tk()
        normalize_tk_scaling(root)  # Normalize for consistent font rendering
        root.withdraw()
        messagebox.showerror(
            "BrainDock Already Running",
            f"Another instance of BrainDock is already running{pid_info}.\n\n"
            "Only one instance can run at a time.\n"
            "Please close the other instance first."
        )
        root.destroy()
        sys.exit(1)
    
    # Check license before showing main app
    from gui.payment_screen import check_and_show_payment_screen
    from licensing.license_manager import get_license_manager
    
    license_manager = get_license_manager()
    
    if not license_manager.is_licensed() and not config.SKIP_LICENSE_CHECK:
        # Create a temporary root window for payment screen
        # Use same dimensions as main GUI
        payment_root = tk.Tk()
        normalize_tk_scaling(payment_root)  # Normalize for consistent font rendering
        payment_root.title("BrainDock - Activate License")
        payment_root.configure(bg=COLORS["bg_primary"])
        
        # Set size and center the window (same as main GUI)
        # Use ScalingManager for proper screen dimension handling
        scaling_mgr = ScalingManager(payment_root)
        initial_width, initial_height = scaling_mgr.get_initial_window_size()
        x, y = scaling_mgr.get_centered_position(initial_width, initial_height)
        payment_root.geometry(f"{initial_width}x{initial_height}+{x}+{y}")
        
        # Set minimum size like main GUI
        payment_root.minsize(MIN_WIDTH, MIN_HEIGHT)
        
        # Make window pop to front
        payment_root.lift()
        payment_root.attributes('-topmost', True)
        payment_root.after(100, lambda: payment_root.attributes('-topmost', False))
        payment_root.focus_force()
        
        # Track if license was activated
        license_activated = [False]  # Use list to allow modification in closure
        
        def on_license_activated():
            """Callback when license is activated."""
            license_activated[0] = True
            payment_root.destroy()
        
        # Show payment screen
        check_and_show_payment_screen(payment_root, on_license_activated)
        
        # Run the payment screen event loop
        payment_root.mainloop()
        
        # If license wasn't activated (user closed window), exit
        if not license_activated[0]:
            logger.info("Payment screen closed without activation - exiting")
            sys.exit(0)
    
    # Check for API key early (based on configured vision provider)
    if config.VISION_PROVIDER == "gemini":
        if not config.GEMINI_API_KEY:
            logger.warning("Gemini API key not found - user will be prompted")
    else:
        if not config.OPENAI_API_KEY:
            logger.warning("OpenAI API key not found - user will be prompted")
    
    # Create and run GUI
    app = BrainDockGUI()
    app.run()


if __name__ == "__main__":
    main()
