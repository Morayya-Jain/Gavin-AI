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
from typing import Optional
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
from camera.vision_detector import VisionDetector
from camera import get_event_type
from tracking.session import Session
from tracking.analytics import compute_statistics
from tracking.usage_limiter import get_usage_limiter, UsageLimiter
from reporting.pdf_report import generate_report
from instance_lock import check_single_instance, get_existing_pid
from screen.window_detector import WindowDetector, get_screen_state, get_screen_state_with_ai_fallback
from screen.blocklist import Blocklist, BlocklistManager, PRESET_CATEGORIES

logger = logging.getLogger(__name__)

# --- Theme System ---
# Supports light/dark themes (dark mode prepared for future)
THEMES = {
    "light": {
        "bg_primary": "#FFFFFF",        # Main background (white)
        "bg_secondary": "#F9FAFB",      # Card backgrounds (very light gray)
        "bg_tertiary": "#F3F4F6",       # Hover states, borders
        "bg_card": "#FFFFFF",           # Card background
        "text_primary": "#1F2937",      # Main text (dark gray)
        "text_secondary": "#6B7280",    # Muted text (gray)
        "text_white": "#FFFFFF",        # White text for buttons
        "border": "#9CA3AF",            # Visible borders (medium gray)
        "border_focus": "#3B82F6",      # Focus ring color
        "accent_primary": "#3B82F6",    # Primary accent (blue)
        "accent_warm": "#F59E0B",       # Warm accent for alerts
        "status_focused": "#10B981",    # Green for focused
        "status_away": "#F59E0B",       # Amber for away
        "status_gadget": "#EF4444",     # Red for gadget distraction
        "status_screen": "#8B5CF6",     # Purple for screen distraction
        "status_idle": "#9CA3AF",       # Gray for idle
        "status_paused": "#6B7280",     # Muted gray for paused
        "button_start": "#10B981",      # Green start button
        "button_start_hover": "#059669", # Darker green on hover
        "button_stop": "#EF4444",       # Red stop button
        "button_stop_hover": "#DC2626", # Darker red on hover
        "button_pause": "#6B7280",      # Gray pause button
        "button_pause_hover": "#4B5563", # Darker gray on hover
        "button_resume": "#3B82F6",     # Blue resume button
        "button_resume_hover": "#2563EB", # Darker blue on hover
        "button_settings": "#6B7280",   # Gray for settings
        "button_settings_hover": "#4B5563", # Darker gray on hover
        "time_badge": "#8B5CF6",        # Purple for time remaining
        "time_badge_low": "#F59E0B",    # Orange when time is low
        "time_badge_expired": "#EF4444", # Red when time expired
        "toggle_on": "#3B82F6",         # Blue for enabled toggles
        "toggle_off": "#E5E7EB",        # Light gray for disabled toggles
        "toggle_text_on": "#FFFFFF",    # White text when toggle on
        "toggle_text_off": "#6B7280",   # Gray text when toggle off
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
        "status_away": "#FBBF24",
        "status_gadget": "#F87171",
        "status_screen": "#A78BFA",
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

# Privacy settings file
PRIVACY_FILE = Path(__file__).parent.parent / "data" / ".privacy_accepted"

# Assets directory for logos
ASSETS_DIR = Path(__file__).parent.parent / "assets"

# Base dimensions for scaling (larger default window)
BASE_WIDTH = 900
BASE_HEIGHT = 700
MIN_WIDTH = 600
MIN_HEIGHT = 500


class RoundedFrame(tk.Canvas):
    """
    A frame with rounded corners using Canvas.
    
    Draws a rounded rectangle background and allows placing widgets inside.
    Supports optional border for light theme styling.
    """
    
    def __init__(self, parent, bg_color: str, corner_radius: int = 15, 
                 border_color: str = None, border_width: int = 1, **kwargs):
        """
        Initialize rounded frame.
        
        Args:
            parent: Parent widget
            bg_color: Background color for the rounded rectangle
            corner_radius: Radius of the corners
            border_color: Optional border color (None for no border)
            border_width: Border width in pixels
        """
        # Get parent background for canvas
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        
        super().__init__(parent, highlightthickness=0, bg=parent_bg, **kwargs)
        
        self.bg_color = bg_color
        self.corner_radius = corner_radius
        self.border_color = border_color
        self.border_width = border_width
        self._rect_id = None
        
        # Bind resize to redraw
        self.bind("<Configure>", self._on_resize)
    
    def _on_resize(self, event=None):
        """Redraw the rounded rectangle on resize."""
        self.delete("rounded_bg")
        self.delete("rounded_border")
        
        width = self.winfo_width()
        height = self.winfo_height()
        
        if width > 1 and height > 1:
            self._draw_rounded_rect(0, 0, width, height, self.corner_radius, self.bg_color)
    
    def _draw_rounded_rect(self, x1, y1, x2, y2, radius, color):
        """
        Draw a rounded rectangle with optional border.
        
        Args:
            x1, y1: Top-left corner
            x2, y2: Bottom-right corner
            radius: Corner radius
            color: Fill color
        """
        # Ensure radius isn't larger than half the smallest dimension
        radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
        
        # Draw using polygon with smooth curves
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        
        # Draw border first if specified
        if self.border_color:
            self.create_polygon(
                points,
                fill="",
                outline=self.border_color,
                width=self.border_width,
                smooth=True,
                tags="rounded_border"
            )
        
        self._rect_id = self.create_polygon(
            points, 
            fill=color, 
            smooth=True, 
            tags="rounded_bg"
        )
        
        # Send to back so widgets appear on top
        self.tag_lower("rounded_bg")


class RoundedButton(tk.Canvas):
    """
    A button with rounded corners.
    """
    
    def __init__(
        self, 
        parent, 
        text: str,
        command,
        bg_color: str,
        hover_color: str,
        fg_color: str = "#FFFFFF",
        font: tkfont.Font = None,
        corner_radius: int = 12,
        padx: int = 30,
        pady: int = 12,
        **kwargs
    ):
        """
        Initialize rounded button.
        
        Args:
            parent: Parent widget
            text: Button text
            command: Click callback
            bg_color: Background color
            hover_color: Color on hover
            fg_color: Text color
            font: Text font
            corner_radius: Corner radius
            padx, pady: Internal padding
        """
        self.text = text
        self.command = command
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.fg_color = fg_color
        self.btn_font = font
        self.corner_radius = corner_radius
        self.padx = padx
        self.pady = pady
        self._enabled = True
        
        # Get parent background
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        
        super().__init__(parent, highlightthickness=0, bg=parent_bg, **kwargs)
        
        # Bind events
        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        
        self._current_bg = bg_color
    
    def _on_resize(self, event=None):
        """Redraw button on resize."""
        self._draw_button()
    
    def _draw_button(self):
        """Draw the button with current state."""
        self.delete("all")
        
        width = self.winfo_width()
        height = self.winfo_height()
        
        if width > 1 and height > 1:
            # Draw rounded rectangle background
            radius = min(self.corner_radius, width // 4, height // 2)
            
            points = [
                radius, 0,
                width - radius, 0,
                width, 0,
                width, radius,
                width, height - radius,
                width, height,
                width - radius, height,
                radius, height,
                0, height,
                0, height - radius,
                0, radius,
                0, 0,
            ]
            
            self.create_polygon(
                points,
                fill=self._current_bg,
                smooth=True,
                tags="bg"
            )
            
            # Draw text
            self.create_text(
                width // 2,
                height // 2,
                text=self.text,
                fill=self.fg_color,
                font=self.btn_font,
                tags="text"
            )
    
    def _on_enter(self, event):
        """Mouse enter - show hover state."""
        if self._enabled:
            self._current_bg = self.hover_color
            self._draw_button()
            self.config(cursor="")  # Normal cursor
    
    def _on_leave(self, event):
        """Mouse leave - restore normal state."""
        if self._enabled:
            self._current_bg = self.bg_color
            self._draw_button()
    
    def _on_click(self, event):
        """Handle click."""
        if self._enabled and self.command:
            self.command()
    
    def configure_button(self, **kwargs):
        """
        Configure button properties.
        
        Args:
            text: New button text
            bg_color: New background color
            hover_color: New hover color
            state: tk.NORMAL or tk.DISABLED
        """
        if "text" in kwargs:
            self.text = kwargs["text"]
        if "bg_color" in kwargs:
            self.bg_color = kwargs["bg_color"]
            self._current_bg = kwargs["bg_color"]
        if "hover_color" in kwargs:
            self.hover_color = kwargs["hover_color"]
        if "state" in kwargs:
            self._enabled = (kwargs["state"] != tk.DISABLED)
            if not self._enabled:
                self._current_bg = COLORS["bg_tertiary"]
            else:
                self._current_bg = self.bg_color
        
        self._draw_button()


class RoundedBadge(tk.Canvas):
    """
    A non-interactive badge with rounded corners.
    
    Used for displaying status information like time remaining.
    Supports dynamic text and background color updates.
    """
    
    def __init__(
        self,
        parent,
        text: str,
        bg_color: str,
        fg_color: str = "#FFFFFF",
        font: tkfont.Font = None,
        corner_radius: int = 10,
        padx: int = 16,
        pady: int = 6,
        clickable: bool = False,
        hover_color: str = None,
        **kwargs
    ):
        """
        Initialize rounded badge.
        
        Args:
            parent: Parent widget
            text: Badge text
            bg_color: Background color
            fg_color: Text color
            font: Text font
            corner_radius: Corner radius
            padx, pady: Internal padding
            clickable: Whether badge responds to clicks
            hover_color: Color on hover (only if clickable)
        """
        self.text = text
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.badge_font = font
        self.corner_radius = corner_radius
        self.padx = padx
        self.pady = pady
        self.clickable = clickable
        self.hover_color = hover_color or bg_color
        self._current_bg = bg_color
        self._click_callback = None
        
        # Get parent background
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_primary"]
        
        super().__init__(parent, highlightthickness=0, bg=parent_bg, **kwargs)
        
        # Bind resize
        self.bind("<Configure>", self._on_resize)
        
        # Bind hover/click if clickable
        if clickable:
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)
            self.bind("<Button-1>", self._on_click)
    
    def _on_resize(self, event=None):
        """Redraw badge on resize."""
        self._draw_badge()
    
    def _draw_badge(self):
        """Draw the badge with current state."""
        self.delete("all")
        
        width = self.winfo_width()
        height = self.winfo_height()
        
        if width > 1 and height > 1:
            # Draw rounded rectangle background
            radius = min(self.corner_radius, width // 4, height // 2)
            
            points = [
                radius, 0,
                width - radius, 0,
                width, 0,
                width, radius,
                width, height - radius,
                width, height,
                width - radius, height,
                radius, height,
                0, height,
                0, height - radius,
                0, radius,
                0, 0,
            ]
            
            self.create_polygon(
                points,
                fill=self._current_bg,
                smooth=True,
                tags="bg"
            )
            
            # Draw text
            self.create_text(
                width // 2,
                height // 2,
                text=self.text,
                fill=self.fg_color,
                font=self.badge_font,
                tags="text"
            )
    
    def _on_enter(self, event):
        """Mouse enter - show hover state."""
        if self.clickable:
            self._current_bg = self.hover_color
            self._draw_badge()
    
    def _on_leave(self, event):
        """Mouse leave - restore normal state."""
        if self.clickable:
            self._current_bg = self.bg_color
            self._draw_badge()
    
    def _on_click(self, event):
        """Handle click."""
        if self.clickable and self._click_callback:
            self._click_callback(event)
    
    def bind_click(self, callback):
        """Bind a callback to badge click."""
        self._click_callback = callback
    
    def configure_badge(self, **kwargs):
        """
        Configure badge properties.
        
        Args:
            text: New badge text
            bg_color: New background color
            fg_color: New text color
        """
        if "text" in kwargs:
            self.text = kwargs["text"]
        if "bg_color" in kwargs:
            self.bg_color = kwargs["bg_color"]
            self._current_bg = kwargs["bg_color"]
        if "fg_color" in kwargs:
            self.fg_color = kwargs["fg_color"]
        
        self._draw_badge()


class Tooltip:
    """
    A tooltip that appears when hovering over a widget.
    
    Shows full text on hover, similar to browser tab tooltips.
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
        
        label = tk.Label(
            frame,
            text=self.text,
            bg=self.bg,
            fg=self.fg,
            font=("SF Pro Display", 11),
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
    
    # Consistent font family for the app
    FONT_FAMILY = "SF Pro Display"
    FONT_FAMILY_FALLBACK = "Helvetica Neue"
    
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
        
        # Popup dimensions (compact card)
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
        
        # Window size and positioning - center on screen
        # Update to ensure accurate screen dimensions
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - BASE_WIDTH) // 2
        y = (screen_height - BASE_HEIGHT) // 2
        self.root.geometry(f"{BASE_WIDTH}x{BASE_HEIGHT}+{x}+{y}")
        
        # Enable resizing with minimum size
        self.root.resizable(True, True)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        
        # Track current scale for font adjustments
        self.current_scale = 1.0
        self._last_width = BASE_WIDTH
        self._last_height = BASE_HEIGHT
        
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
        
        # Unfocused alert tracking
        self.unfocused_start_time: Optional[float] = None
        self.alerts_played: int = 0  # Tracks how many alerts have been played (max 3)
        
        # Usage limit tracking
        self.usage_limiter: UsageLimiter = get_usage_limiter()
        self.is_locked: bool = False  # True when time exhausted and app is locked
        
        # UI update lock
        self.ui_lock = threading.Lock()
        
        # Create UI elements
        self._create_fonts()
        self._create_widgets()
        
        # Bind resize event for scaling
        self.root.bind("<Configure>", self._on_resize)
        
        # Bind Enter key to start/stop session
        self.root.bind("<Return>", self._on_enter_key)
        
        # Check privacy acceptance
        self.root.after(100, self._check_privacy)
        
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
            from AppKit import NSApplication, NSAppearance
            
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
    
    def _create_fonts(self):
        """Create custom fonts for the UI with fixed sizes."""
        # Use SF Pro Display for consistent modern look (fallback to Helvetica Neue)
        font_family = "SF Pro Display"
        font_family_mono = "SF Mono"
        
        self.font_title = tkfont.Font(
            family=font_family, size=26, weight="bold"
        )
        
        self.font_timer = tkfont.Font(
            family=font_family_mono, size=36, weight="bold"
        )
        
        self.font_status = tkfont.Font(
            family=font_family, size=15, weight="normal"
        )
        
        self.font_button = tkfont.Font(
            family=font_family, size=14, weight="bold"
        )
        
        self.font_small = tkfont.Font(
            family=font_family, size=11, weight="normal"
        )
        
        self.font_badge = tkfont.Font(
            family=font_family, size=10, weight="bold"
        )
    
    
    def _on_resize(self, event):
        """
        Handle window resize event - scale UI components proportionally.
        
        Note: Font sizes stay fixed. Only buttons and containers scale.
        
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
        width_scale = event.width / BASE_WIDTH
        height_scale = event.height / BASE_HEIGHT
        new_scale = min(width_scale, height_scale)
        
        # Update if scale changed significantly
        if abs(new_scale - self.current_scale) > 0.05:
            self.current_scale = new_scale
            
            # Scale buttons proportionally (but keep minimum size)
            new_btn_width = max(160, int(180 * new_scale))
            new_btn_height = max(46, int(52 * new_scale))
            
            if hasattr(self, 'start_stop_btn'):
                self.start_stop_btn.configure(width=new_btn_width, height=new_btn_height)
                self.start_stop_btn._draw_button()
            
            if hasattr(self, 'pause_btn'):
                self.pause_btn.configure(width=new_btn_width, height=new_btn_height)
                self.pause_btn._draw_button()
            
            # Scale status card height proportionally
            if hasattr(self, 'status_card'):
                new_card_height = max(50, int(60 * new_scale))
                self.status_card.configure(height=new_card_height)
    
    def _get_current_status_color(self) -> str:
        """Get the color for the current status."""
        color_map = {
            "idle": COLORS["status_idle"],
            "focused": COLORS["status_focused"],
            "away": COLORS["status_away"],
            "gadget": COLORS["status_gadget"],
            "screen": COLORS["status_screen"],
            "paused": COLORS["status_paused"],
        }
        return color_map.get(self.current_status, COLORS["status_idle"])
    
    def _create_widgets(self):
        """Create all UI widgets with scalable layout."""
        # Main container using grid for proportional spacing
        self.main_frame = tk.Frame(self.root, bg=COLORS["bg_primary"])
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=50, pady=40)
        
        # Configure grid rows with weights for proportional expansion
        # Row 0: Spacer (expands)
        # Row 1: Title (fixed)
        # Row 2: Spacer (expands)
        # Row 3: Status card (fixed)
        # Row 4: Spacer (expands more)
        # Row 5: Timer (fixed)
        # Row 6: Spacer (expands more)
        # Row 7: Button (fixed)
        # Row 8: Spacer (expands)
        
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, minsize=20, weight=0)   # Top spacer (smaller)
        self.main_frame.grid_rowconfigure(1, weight=0)   # Title
        self.main_frame.grid_rowconfigure(2, weight=1)   # Spacer
        self.main_frame.grid_rowconfigure(8, weight=0)   # Mode selector (added)
        self.main_frame.grid_rowconfigure(3, weight=0)   # Status
        self.main_frame.grid_rowconfigure(4, weight=2)   # Spacer (more weight)
        self.main_frame.grid_rowconfigure(5, weight=0)   # Timer
        self.main_frame.grid_rowconfigure(6, weight=2)   # Spacer (more weight)
        self.main_frame.grid_rowconfigure(7, weight=0)   # Button
        self.main_frame.grid_rowconfigure(8, weight=1)   # Bottom spacer
        
        # --- Title Section with Logo ---
        title_frame = tk.Frame(self.main_frame, bg=COLORS["bg_primary"])
        title_frame.grid(row=1, column=0, sticky="ew", pady=(0, 0))
        
        # Logo with text container (centered)
        logo_title_frame = tk.Frame(title_frame, bg=COLORS["bg_primary"])
        logo_title_frame.pack()
        
        # Load and display logo with text (combined image)
        self.logo_image = None
        self.logo_label = None
        if PIL_AVAILABLE:
            logo_path = ASSETS_DIR / "logo_with_text.png"
            if logo_path.exists():
                try:
                    # Load logo with text
                    img = Image.open(logo_path)
                    
                    # Convert to RGBA if not already (for proper transparency handling)
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    
                    # Crop out empty/transparent space around the logo
                    bbox = img.getbbox()
                    if bbox:
                        img = img.crop(bbox)
                    
                    # Resize proportionally - target height of 50px
                    target_height = 50
                    aspect_ratio = img.width / img.height
                    target_width = int(target_height * aspect_ratio)
                    img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                    self.logo_image = ImageTk.PhotoImage(img)
                    self.logo_label = tk.Label(
                        logo_title_frame,
                        image=self.logo_image,
                        bg=COLORS["bg_primary"]
                    )
                    self.logo_label.pack()
                except Exception as e:
                    logger.warning(f"Could not load logo: {e}")
                    # Fallback to text-only title
                    self.title_label = tk.Label(
                        logo_title_frame,
                        text="BrainDock",
                        font=self.font_title,
                        fg=COLORS["text_primary"],
                        bg=COLORS["bg_primary"]
                    )
                    self.title_label.pack()
            else:
                # Fallback to text-only title if image not found
                self.title_label = tk.Label(
                    logo_title_frame,
                    text="BrainDock",
                    font=self.font_title,
                    fg=COLORS["text_primary"],
                    bg=COLORS["bg_primary"]
                )
                self.title_label.pack()
        else:
            # Fallback to text-only title if PIL not available
            self.title_label = tk.Label(
                logo_title_frame,
                text="BrainDock",
                font=self.font_title,
                fg=COLORS["text_primary"],
                bg=COLORS["bg_primary"]
            )
            self.title_label.pack()
        
        # --- Time Remaining Badge (clickable for details) ---
        self.time_badge_frame = tk.Frame(title_frame, bg=COLORS["bg_primary"])
        self.time_badge_frame.pack(pady=(15, 0))
        
        # Rounded badge for time remaining - subtle style for light theme
        self.time_badge = RoundedBadge(
            self.time_badge_frame,
            text="2h 0m left",
            bg_color=COLORS["bg_secondary"],
            hover_color=COLORS["bg_tertiary"],
            fg_color=COLORS["text_secondary"],
            font=self.font_badge,
            corner_radius=8,
            padx=16,
            pady=6,
            clickable=True,
            width=120,
            height=34
        )
        self.time_badge.pack()
        self.time_badge.bind_click(self._show_usage_details)
        
        # Lockout overlay (hidden by default)
        self.lockout_frame: Optional[tk.Frame] = None
        
        # --- Status Card (Rounded with border) ---
        status_container = tk.Frame(self.main_frame, bg=COLORS["bg_primary"])
        status_container.grid(row=3, column=0, sticky="ew", padx=40)
        
        self.status_card = RoundedFrame(
            status_container,
            bg_color=COLORS["bg_card"],
            corner_radius=12,
            border_color=COLORS["border"],
            border_width=4,
            height=70
        )
        self.status_card.pack(fill=tk.X)
        
        # Status content frame (inside the rounded card)
        self.status_content = tk.Frame(self.status_card, bg=COLORS["bg_card"])
        self.status_content.place(relx=0.5, rely=0.5, anchor="center")
        
        # Status dot (using canvas for round shape)
        self.status_dot = tk.Canvas(
            self.status_content,
            width=14,
            height=14,
            bg=COLORS["bg_card"],
            highlightthickness=0
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 10))
        self._draw_status_dot(COLORS["status_idle"])
        
        self.status_label = tk.Label(
            self.status_content,
            text="Ready to Start",
            font=self.font_status,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"]
        )
        self.status_label.pack(side=tk.LEFT)
        
        # --- Timer Display ---
        timer_frame = tk.Frame(self.main_frame, bg=COLORS["bg_primary"])
        timer_frame.grid(row=5, column=0, sticky="ew")
        
        self.timer_label = tk.Label(
            timer_frame,
            text="00:00:00",
            font=self.font_timer,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        self.timer_label.pack()
        
        self.timer_sub_label = tk.Label(
            timer_frame,
            text="Session Duration",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        self.timer_sub_label.pack(pady=(5, 0))
        
        # --- Button Section ---
        button_frame = tk.Frame(self.main_frame, bg=COLORS["bg_primary"])
        button_frame.grid(row=7, column=0, sticky="ew")
        
        # Pause/Resume Button (Rounded) - hidden initially, appears when session running
        self.pause_btn = RoundedButton(
            button_frame,
            text="Pause Session",
            command=self._toggle_pause,
            bg_color=COLORS["button_pause"],
            hover_color=COLORS["button_pause_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=10,
            width=200,
            height=56
        )
        # Hidden initially - will be shown when session starts
        
        # Start/Stop Button (Rounded) - centered
        self.start_stop_btn = RoundedButton(
            button_frame,
            text="Start Session",
            command=self._toggle_session,
            bg_color=COLORS["button_start"],
            hover_color=COLORS["button_start_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=10,
            width=200,
            height=56
        )
        self.start_stop_btn.pack()
        
        # --- Mode Selector Section (below buttons) ---
        self._create_mode_selector()
    
    def _create_mode_selector(self):
        """
        Create the monitoring mode selector UI.
        
        Allows users to choose between Camera Only, Screen Only, or Both modes.
        Also provides access to blocklist settings.
        """
        # Mode selector container
        self.mode_frame = tk.Frame(self.main_frame, bg=COLORS["bg_primary"])
        self.mode_frame.grid(row=8, column=0, sticky="ew", pady=(25, 0))
        
        # Mode label
        mode_label = tk.Label(
            self.mode_frame,
            text="Monitoring Mode",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        mode_label.pack()
        
        # Mode buttons container
        mode_buttons_frame = tk.Frame(self.mode_frame, bg=COLORS["bg_primary"])
        mode_buttons_frame.pack(pady=(8, 0))
        
        # Create mode toggle buttons
        self.mode_var = tk.StringVar(value=config.MODE_CAMERA_ONLY)
        
        modes = [
            (config.MODE_CAMERA_ONLY, "Camera"),
            (config.MODE_SCREEN_ONLY, "Screen"),
            (config.MODE_BOTH, "Both"),
        ]
        
        self.mode_buttons = {}
        for mode_id, mode_text in modes:
            # Light theme: selected = accent bg with white text, unselected = light bg with gray text
            is_selected = mode_id == self.monitoring_mode
            btn = tk.Label(
                mode_buttons_frame,
                text=mode_text,
                font=self.font_small,
                fg=COLORS["text_white"] if is_selected else COLORS["text_secondary"],
                bg=COLORS["toggle_on"] if is_selected else COLORS["toggle_off"],
                padx=16,
                pady=8,
            )
            btn.pack(side=tk.LEFT, padx=3)
            btn.bind("<Button-1>", lambda e, m=mode_id: self._set_monitoring_mode(m))
            self.mode_buttons[mode_id] = btn
        
        # Settings button (for blocklist management) - text link style
        settings_frame = tk.Frame(self.mode_frame, bg=COLORS["bg_primary"])
        settings_frame.pack(pady=(12, 0))
        
        self.settings_btn = tk.Label(
            settings_frame,
            text="Blocklist Settings",
            font=self.font_small,
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_primary"]
        )
        self.settings_btn.pack()
        self.settings_btn.bind("<Button-1>", lambda e: self._show_blocklist_settings())
        self.settings_btn.bind("<Enter>", lambda e: self.settings_btn.configure(fg=COLORS["status_focused"]))
        self.settings_btn.bind("<Leave>", lambda e: self.settings_btn.configure(fg=COLORS["accent_primary"]))
    
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
                    fg=COLORS["text_white"],
                    bg=COLORS["toggle_on"]
                )
            else:
                btn.configure(
                    fg=COLORS["text_secondary"],
                    bg=COLORS["toggle_off"]
                )
        
        logger.info(f"Monitoring mode set to: {mode}")
    
    def _show_blocklist_settings(self):
        """
        Show the blocklist settings dialog.
        
        Allows users to enable/disable preset categories and add custom patterns.
        """
        # Create settings window (larger to accommodate separate URL/App fields)
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Blocklist Settings")
        settings_window.configure(bg=COLORS["bg_primary"])
        settings_window.geometry("420x700")
        settings_window.resizable(False, False)
        
        # Center on parent window
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 700) // 2
        settings_window.geometry(f"+{x}+{y}")
        
        # Main container with padding
        main_container = tk.Frame(settings_window, bg=COLORS["bg_primary"])
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Title
        title = tk.Label(
            main_container,
            text="Blocklist Settings",
            font=self.font_title,
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_primary"]
        )
        title.pack()
        
        subtitle = tk.Label(
            main_container,
            text="Configure which sites/apps to block",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        subtitle.pack(pady=(5, 15))
        
        # Categories section
        categories_label = tk.Label(
            main_container,
            text="Preset Categories",
            font=self.font_status,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        categories_label.pack(anchor="w")
        
        # Category toggles
        self.category_vars = {}
        categories_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        categories_frame.pack(fill=tk.X, pady=(5, 15))
        
        for cat_id, cat_data in PRESET_CATEGORIES.items():
            var = tk.BooleanVar(value=cat_id in self.blocklist.enabled_categories)
            self.category_vars[cat_id] = var
            
            row = tk.Frame(categories_frame, bg=COLORS["bg_primary"])
            row.pack(fill=tk.X, pady=2)
            
            cb = tk.Checkbutton(
                row,
                text=cat_data["name"],
                variable=var,
                font=self.font_small,
                fg=COLORS["text_primary"],
                bg=COLORS["bg_primary"],
                selectcolor=COLORS["bg_secondary"],
                activebackground=COLORS["bg_primary"],
                activeforeground=COLORS["text_primary"],
                command=lambda c=cat_id, v=var: self._toggle_category(c, v.get())
            )
            cb.pack(side=tk.LEFT)
            
            # Clickable label to show sites in category
            desc = tk.Label(
                row,
                text=f"({len(cat_data['patterns'])} sites)",
                font=self.font_small,
                fg=COLORS["accent_primary"],
                bg=COLORS["bg_primary"]
            )
            desc.pack(side=tk.LEFT, padx=(5, 0))
            # Bind click to show sites popup
            desc.bind("<Button-1>", lambda e, c=cat_id, d=cat_data: self._show_category_sites(c, d))
            desc.bind("<Enter>", lambda e, lbl=desc: lbl.configure(fg=COLORS["accent_warm"]))
            desc.bind("<Leave>", lambda e, lbl=desc: lbl.configure(fg=COLORS["accent_primary"]))
        
        # --- Custom URLs section ---
        urls_label = tk.Label(
            main_container,
            text="Custom URLs/Domains",
            font=self.font_status,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        urls_label.pack(anchor="w", pady=(10, 2))
        
        urls_help = tk.Label(
            main_container,
            text="Add website URLs to block (e.g., example.com)",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        urls_help.pack(anchor="w")
        
        # URLs text area with validation feedback
        urls_frame = tk.Frame(main_container, bg=COLORS["bg_secondary"])
        urls_frame.pack(fill=tk.X, pady=(3, 5))
        
        self.custom_urls_text = tk.Text(
            urls_frame,
            font=self.font_small,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_secondary"],
            insertbackground=COLORS["text_primary"],
            height=3,
            wrap=tk.WORD
        )
        self.custom_urls_text.pack(fill=tk.X, padx=5, pady=5)
        
        # URL validation status label with tooltip for full message
        self.url_validation_label = tk.Label(
            main_container,
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
            main_container,
            text="Custom App Names",
            font=self.font_status,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"]
        )
        apps_label.pack(anchor="w", pady=(8, 2))
        
        apps_help = tk.Label(
            main_container,
            text="Add desktop app names to block (e.g., Steam, Discord)",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_primary"]
        )
        apps_help.pack(anchor="w")
        
        # Apps text area with validation feedback
        apps_frame = tk.Frame(main_container, bg=COLORS["bg_secondary"])
        apps_frame.pack(fill=tk.X, pady=(3, 5))
        
        self.custom_apps_text = tk.Text(
            apps_frame,
            font=self.font_small,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_secondary"],
            insertbackground=COLORS["text_primary"],
            height=3,
            wrap=tk.WORD
        )
        self.custom_apps_text.pack(fill=tk.X, padx=5, pady=5)
        
        # App validation status label with tooltip for full message
        self.app_validation_label = tk.Label(
            main_container,
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
        
        # Bind validation on text change (for real-time feedback)
        self.custom_urls_text.bind("<KeyRelease>", lambda e: self._validate_urls_realtime())
        self.custom_apps_text.bind("<KeyRelease>", lambda e: self._validate_apps_realtime())
        
        # AI Fallback option (advanced) - OFF BY DEFAULT
        ai_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        ai_frame.pack(fill=tk.X, pady=(10, 15))
        
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
            text="⚠️ Takes screenshots - only use if URL detection fails",
            font=self.font_small,
            fg=COLORS["accent_warm"],
            bg=COLORS["bg_primary"]
        )
        ai_help.pack(anchor="w", padx=(20, 0))
        
        # Buttons - centered at bottom
        button_frame = tk.Frame(main_container, bg=COLORS["bg_primary"])
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
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
            corner_radius=8,
            width=150,
            height=44
        )
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        cancel_btn = RoundedButton(
            button_container,
            text="Cancel",
            command=settings_window.destroy,
            bg_color=COLORS["button_pause"],
            hover_color=COLORS["button_pause_hover"],
            fg_color=COLORS["text_white"],
            font=self.font_button,
            corner_radius=8,
            width=100,
            height=44
        )
        cancel_btn.pack(side=tk.LEFT)
    
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
    
    def _show_category_sites(self, category_id: str, cat_data: dict):
        """
        Show a popup with the list of sites in a category.
        
        Args:
            category_id: The category ID
            cat_data: Category data dictionary with patterns
        """
        # Create a small popup window
        sites_popup = tk.Toplevel(self.root)
        sites_popup.title(f"{cat_data['name']} Sites")
        sites_popup.configure(bg=COLORS["bg_primary"])
        sites_popup.geometry("320x320")
        sites_popup.resizable(False, False)
        
        # Center on parent
        sites_popup.transient(self.root)
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 320) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
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
        
        # Check for overlaps with preset categories
        preset_patterns = set()
        for cat_id in self.blocklist.enabled_categories:
            if cat_id in PRESET_CATEGORIES:
                for p in PRESET_CATEGORIES[cat_id]['patterns']:
                    preset_patterns.add(p.lower())
        
        # Filter out URLs that already exist in enabled preset categories
        url_overlaps = []
        final_urls = []
        for url in unique_urls:
            if url in preset_patterns:
                url_overlaps.append(url)
            else:
                final_urls.append(url)
        
        # Filter out Apps that already exist in enabled preset categories
        app_overlaps = []
        final_apps = []
        for app in unique_apps:
            if app.lower() in preset_patterns:
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
            messages.append(f"Removed {len(preset_overlaps)} entry(s) already in preset categories")
        if all_warnings:
            messages.append(f"Note: {len(all_warnings)} warning(s) - entries saved but may need review")
        
        if messages:
            messagebox.showinfo(
                "Blocklist Saved",
                "\n".join(messages) + "\n\nSettings saved successfully."
            )
        
        # Close dialog
        settings_window.destroy()
        
        logger.info(f"Blocklist settings saved (URLs: {len(final_urls)}, Apps: {len(final_apps)}, "
                   f"AI fallback: {self.use_ai_fallback}, "
                   f"duplicates removed: {len(duplicates_removed)}, "
                   f"preset overlaps: {len(preset_overlaps)})")
    
    def _draw_status_dot(self, color: str, emoji: str = None):
        """
        Draw the status indicator dot (circle) or emoji.
        
        Args:
            color: Hex color for the dot (used if no emoji)
            emoji: Optional emoji to show instead of the dot
        """
        self.status_dot.delete("all")
        
        if emoji:
            # Show emoji instead of dot
            self.status_dot.create_text(
                7, 7,  # Center of the 14x14 canvas
                text=emoji,
                font=("SF Pro Display", 10),
                anchor="center"
            )
        else:
            # Draw a perfect circle
            self.status_dot.create_oval(1, 1, 13, 13, fill=color, outline="")
    
    def _check_privacy(self):
        """Check if privacy notice has been accepted, show if not."""
        if not PRIVACY_FILE.exists():
            self._show_privacy_notice()
    
    def _show_privacy_notice(self):
        """Display the privacy notice popup."""
        privacy_text = """BrainDock uses OpenAI's Vision API to monitor your focus sessions.

How it works:
• Camera frames are sent to OpenAI for analysis
• AI detects your presence and gadget distractions
• No video is recorded or stored locally

Privacy:
• OpenAI may retain data for up to 30 days for abuse monitoring
• No data is stored long-term
• All detection happens in real-time

By clicking 'I Understand', you acknowledge this data processing."""
        
        result = messagebox.askokcancel(
            "Privacy Notice",
            privacy_text,
            icon="info"
        )
        
        if result:
            # Save acceptance
            PRIVACY_FILE.parent.mkdir(parents=True, exist_ok=True)
            PRIVACY_FILE.write_text(datetime.now().isoformat())
            logger.info("Privacy notice accepted")
        else:
            # User declined - close app
            self.root.destroy()
    
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
        
        time_text = self.usage_limiter.format_time(int(remaining))
        
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
            badge_color = COLORS["time_badge"]
            text_color = COLORS["text_white"]
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
        self.start_stop_btn.configure_button(state=tk.DISABLED)
    
    def _hide_lockout_overlay(self):
        """Hide the lockout overlay after successful unlock."""
        if self.lockout_frame is not None:
            self.lockout_frame.destroy()
            self.lockout_frame = None
        
        self.is_locked = False
        self._update_time_badge()
        
        # Restore mode selector (hidden when session was running before time exhausted)
        self.mode_frame.grid()
        
        # Re-enable start button and reset UI state
        self.start_stop_btn.configure_button(state=tk.NORMAL)
        self._reset_button_state()
        self._update_status("idle", "Ready to Start")
        
        logger.info("App unlocked - time extension granted")
    
    def _show_password_dialog(self):
        """Show dialog to enter unlock password."""
        # Create dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title("Unlock More Time")
        dialog.configure(bg=COLORS["bg_primary"])
        dialog.resizable(False, False)
        
        # Size and position - center on screen (like main BrainDock UI)
        dialog_width = 350
        dialog_height = 200
        dialog.update_idletasks()
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - dialog_width) // 2
        y = (screen_height - dialog_height) // 2
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
        self.pause_btn.configure_button(
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
        self.pause_btn.configure_button(
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
        if needs_camera and not config.OPENAI_API_KEY:
            messagebox.showerror(
                "API Key Required",
                "OpenAI API key not found!\n\n"
                "Please set OPENAI_API_KEY in your .env file.\n"
                "Get your key from: https://platform.openai.com/api-keys"
            )
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
        
        # Hide mode selector during session
        self.mode_frame.grid_remove()
        
        # Update UI - show both buttons (pause on top, stop below)
        self._update_status("focused", "Booting Up...", emoji="⚡️")
        
        # Repack buttons in correct order: pause on top, stop below with gap
        self.start_stop_btn.pack_forget()  # Remove stop button temporarily
        self.pause_btn.pack(pady=(0, 15))  # Pause button first with gap below
        self.pause_btn.configure_button(
            text="Pause Session",
            bg_color=COLORS["button_pause"],
            hover_color=COLORS["button_pause_hover"]
        )
        self.start_stop_btn.pack()  # Stop button below
        self.start_stop_btn.configure_button(
            text="Stop Session",
            bg_color=COLORS["button_stop"],
            hover_color=COLORS["button_stop_hover"]
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
        
        # Update sub-label to show session mode
        mode_labels = {
            config.MODE_CAMERA_ONLY: "Camera Session",
            config.MODE_SCREEN_ONLY: "Screen Session",
            config.MODE_BOTH: "Camera + Screen Session"
        }
        mode_label = mode_labels.get(self.monitoring_mode, "Session Duration")
        self.timer_sub_label.config(text=mode_label)
        
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
        
        # Wait for detection thread(s) to finish
        if self.detection_thread and self.detection_thread.is_alive():
            self.detection_thread.join(timeout=2.0)
        if self.screen_detection_thread and self.screen_detection_thread.is_alive():
            self.screen_detection_thread.join(timeout=2.0)
        
        # Show mode selector again
        self.mode_frame.grid()
        
        # End session (only if it was actually started after first detection)
        if self.session and self.session_started and self.session_start_time:
            # Calculate and record session duration (excluding paused time)
            # Use full precision until final int conversion for usage tracking
            total_elapsed = (stop_time - self.session_start_time).total_seconds()
            active_duration = int(total_elapsed - self.total_paused_seconds)
            self.usage_limiter.record_usage(active_duration)
            
            self.session.end(stop_time)  # Use the captured stop time
            self.usage_limiter.end_session()
        
        # Hide pause button when session stops
        self.pause_btn.pack_forget()
        
        # Update UI to show generating status
        self._update_status("idle", "Generating Reports...")
        self.start_stop_btn.configure_button(
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
        
        Captures frames from camera and analyzes them using OpenAI Vision API.
        Also handles unfocused alerts at configured thresholds and usage tracking.
        """
        try:
            detector = VisionDetector()
            
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
                            self.session_start_time = datetime.now()
                            self.session_started = True
                            logger.info("First detection complete - session timer started")
                        
                        # Determine event type
                        event_type = get_event_type(detection_state)
                        
                        # Check if user is unfocused (away or on gadget)
                        is_unfocused = event_type in (config.EVENT_AWAY, config.EVENT_GADGET_SUSPECTED)
                        
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
                        
                        # Log event
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
            window_detector = WindowDetector()
            
            # Check permissions on first run
            if not window_detector.check_permission():
                instructions = window_detector.get_permission_instructions()
                self.root.after(0, lambda: self._show_screen_permission_error(instructions))
                return
            
            last_screen_check = time.time()
            
            # For screen-only mode, we need to start the session on first check
            if self.monitoring_mode == config.MODE_SCREEN_ONLY:
                # Start session immediately for screen-only mode
                if not self.session_started:
                    self.session.start()
                    self.session_start_time = datetime.now()
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
                    
                    # Check for distraction
                    if screen_state.get("is_distracted", False):
                        distraction_source = screen_state.get("distraction_source", "Unknown")
                        
                        # Log event
                        if self.session and self.session_started:
                            self.session.log_event(config.EVENT_SCREEN_DISTRACTION)
                        
                        # Determine if it's a website or app distraction
                        # Website: contains a dot and looks like a domain
                        distraction_label = self._get_distraction_label(distraction_source)
                        
                        # Update UI (thread-safe)
                        self.root.after(0, lambda lbl=distraction_label: self._update_status(
                            "screen", lbl
                        ))
                        
                        # Track for alerts (same as camera distraction)
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
                        # Not distracted - only update if screen-only mode or if camera didn't detect distraction
                        if self.monitoring_mode == config.MODE_SCREEN_ONLY:
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
        
        Args:
            instructions: Platform-specific permission instructions
        """
        messagebox.showerror(
            "Screen Monitoring Permission Required",
            f"Screen monitoring cannot access window information.\n\n{instructions}"
        )
        # Stop the session since screen monitoring failed
        if self.is_running and self.monitoring_mode == config.MODE_SCREEN_ONLY:
            self._stop_session()
    
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
            
            # End session with captured stop time
            if self.session and self.session_started and self.session_start_time:
                # Calculate and record session duration (excluding paused time)
                # Use full precision until final int conversion for usage tracking
                total_elapsed = (stop_time - self.session_start_time).total_seconds()
                active_duration = int(total_elapsed - self.total_paused_seconds)
                self.usage_limiter.record_usage(active_duration)
                
                self.session.end(stop_time)
                self.usage_limiter.end_session()
            
            # Hide pause button when session stops
            self.pause_btn.pack_forget()
            
            # Update UI to show generating status
            self._update_status("idle", "Generating Reports...")
            self.start_stop_btn.configure_button(
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
        
        # Schedule UI update on main thread
        self.root.after(0, lambda: self._update_status(status, text))
    
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
        Update the status indicator and label.
        
        Args:
            status: Status type (idle, focused, away, gadget, screen, paused)
            text: Display text
            emoji: Optional emoji to show instead of the colored dot
        """
        with self.ui_lock:
            self.current_status = status
            color = self._get_current_status_color()
            self._draw_status_dot(color, emoji=emoji)
            self.status_label.configure(text=text)
    
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
            # Path to custom alert sound
            sound_file = Path(__file__).parent.parent / "data" / "braindock_alert_sound.mp3"
            
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
                    # Windows - use powershell to play media file
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
        
        # Show notification popup immediately after sound starts
        self.root.after(100, lambda: self._show_alert_popup(badge_text, message))
        
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
        self.start_stop_btn.configure_button(
            text="Start Session",
            bg_color=COLORS["button_start"],
            hover_color=COLORS["button_start_hover"],
            state=tk.NORMAL
        )
        self.timer_label.configure(text="00:00:00")
        self.timer_sub_label.configure(text="Session Duration")
    
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
    
    def _show_camera_error(self):
        """Show camera access error dialog."""
        messagebox.showerror(
            "Camera Error",
            "Failed to access webcam.\n\n"
            "Please check:\n"
            "• Camera is connected\n"
            "• Camera permissions are granted\n"
            "• No other app is using the camera"
        )
        self._reset_button_state()
        self._update_status("idle", "Ready to Start")
    
    def _show_detection_error(self, error: str):
        """
        Show detection error dialog.
        
        Args:
            error: Error message
        """
        messagebox.showerror(
            "Detection Error",
            f"An error occurred during detection:\n\n{error}"
        )
        self._reset_button_state()
        self._update_status("idle", "Ready to Start")
    
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
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=2.0)
            
            # End session and record usage with correct active duration
            if self.session and self.session_started and self.session_start_time:
                total_elapsed = (stop_time - self.session_start_time).total_seconds()
                active_duration = int(total_elapsed - self.total_paused_seconds)
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
        root.withdraw()
        messagebox.showerror(
            "BrainDock Already Running",
            f"Another instance of BrainDock is already running{pid_info}.\n\n"
            "Only one instance can run at a time.\n"
            "Please close the other instance first."
        )
        root.destroy()
        sys.exit(1)
    
    # Check for API key early
    if not config.OPENAI_API_KEY:
        logger.warning("OpenAI API key not found - user will be prompted")
    
    # Create and run GUI
    app = BrainDockGUI()
    app.run()


if __name__ == "__main__":
    main()
