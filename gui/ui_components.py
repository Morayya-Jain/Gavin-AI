import tkinter as tk
from tkinter import font as tkfont
from typing import Dict, Tuple, Optional
import sys

# --- Scaling System ---

# Reference dimensions (design target - the original design resolution)
REFERENCE_WIDTH = 1300
REFERENCE_HEIGHT = 950

# Minimum window dimensions (larger minimum for readability)
MIN_WIDTH = 800
MIN_HEIGHT = 680

# Font scaling bounds (base_size: (min_size, max_size))
FONT_BOUNDS = {
    "timer": (64, 36, 80),      # Base 64pt, min 36, max 80
    "stat": (28, 18, 36),       # Base 28pt, min 18, max 36
    "title": (24, 16, 32),      # Base 24pt, min 16, max 32
    "status": (24, 16, 32),     # Base 24pt, min 16, max 32
    "body": (14, 11, 18),       # Base 14pt, min 11, max 18
    "button": (14, 11, 18),     # Base 14pt, min 11, max 18
    "small": (12, 10, 16),      # Base 12pt, min 10, max 16
    "badge": (12, 10, 16),      # Base 12pt, min 10, max 16
    "caption": (12, 10, 16),    # Base 12pt, min 10, max 16
}


def _is_bundled() -> bool:
    """Check if running from a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def normalize_tk_scaling(root: tk.Tk) -> None:
    """
    Normalize tk scaling for consistent font rendering across terminal and bundled apps.
    
    On macOS, bundled apps with NSHighResolutionCapable report different DPI
    than terminal apps, causing fonts to render at incorrect sizes. This function
    detects the environment and sets tk scaling to ensure consistent rendering.
    
    MUST be called before creating any fonts or widgets.
    
    Args:
        root: The root Tkinter window (before any widgets are created).
    """
    if sys.platform != "darwin":
        return  # Only needed on macOS
    
    root.update_idletasks()
    
    try:
        # Get the current tk scaling factor
        current_scaling = root.tk.call('tk', 'scaling')
        
        # Get the actual DPI reported by the system
        dpi = root.winfo_fpixels('1i')
        
        # Standard macOS DPI is 72 points per inch
        # On Retina displays, DPI can be 144 or higher
        # Terminal apps typically report 72 DPI with tk scaling ~1.0
        # Bundled apps with NSHighResolutionCapable may report higher DPI
        
        if _is_bundled():
            # For bundled apps, normalize to standard macOS scaling
            # This ensures fonts render at the same size as in terminal
            # Target: tk scaling of 1.0 with 72 DPI baseline
            if dpi > 100:
                # Retina display detected - bundled app reports physical DPI
                # Set tk scaling to 1.0 for consistent font rendering
                # (fonts are specified in points and should render correctly at 1.0)
                root.tk.call('tk', 'scaling', 1.0)
            else:
                # Non-Retina or DPI already normalized
                # Ensure scaling is 1.0 for consistency
                if current_scaling != 1.0:
                    root.tk.call('tk', 'scaling', 1.0)
        # For terminal apps, leave scaling unchanged (already correct)
        
    except Exception:
        pass  # If detection fails, leave tk defaults unchanged


class ScalingManager:
    """
    Centralized scaling manager for responsive GUI elements.
    
    Handles screen detection, scale factor calculation, and provides
    utilities for scaling dimensions, fonts, and padding.
    """
    
    def __init__(self, root: tk.Tk):
        """
        Initialize the scaling manager.
        
        Args:
            root: The root Tkinter window.
        """
        self.root = root
        self._current_scale = 1.0
        self._screen_width = 0
        self._screen_height = 0
        self._fonts: Dict[str, tkfont.Font] = {}
        
        # Normalize tk scaling for consistent font rendering (bundled vs terminal)
        # This MUST happen before any fonts or screen measurements
        normalize_tk_scaling(root)
        
        # Detect screen size
        self._detect_screen_size()
    
    def _detect_screen_size(self):
        """
        Detect the current screen dimensions for window sizing.
        
        After normalize_tk_scaling() sets tk scaling to 1.0, screen dimensions
        should be reported consistently. We only apply additional normalization
        if we detect physical pixels on Retina displays in bundled apps.
        
        Note: normalize_tk_scaling() must be called before this method.
        """
        self.root.update_idletasks()
        
        # Get raw screen dimensions
        raw_width = self.root.winfo_screenwidth()
        raw_height = self.root.winfo_screenheight()
        
        # On macOS bundled apps, screen dimensions may still be in physical pixels
        # even after tk scaling normalization. Detect and convert if needed.
        if sys.platform == "darwin" and _is_bundled():
            try:
                # Get the tk scaling factor (should be 1.0 after normalization)
                tk_scaling = self.root.tk.call('tk', 'scaling')
                
                # Get actual DPI
                dpi = self.root.winfo_fpixels('1i')
                
                # If width suggests physical pixels on Retina (>2000 for most Macs)
                # and we're in a bundled app, normalize to logical pixels
                if raw_width > 2000 and dpi > 100:
                    scale_factor = dpi / 72.0
                    raw_width = int(raw_width / scale_factor)
                    raw_height = int(raw_height / scale_factor)
            except Exception:
                pass  # Use raw values if detection fails
        
        self._screen_width = raw_width
        self._screen_height = raw_height
    
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
        
        Returns:
            Tuple of (width, height) for the initial window size.
        """
        # Target 75% of screen width, 80% of screen height
        # But cap at reference dimensions for larger screens
        target_width = min(int(self._screen_width * 0.75), REFERENCE_WIDTH)
        target_height = min(int(self._screen_height * 0.8), REFERENCE_HEIGHT)
        
        # Ensure minimum size
        target_width = max(target_width, MIN_WIDTH)
        target_height = max(target_height, MIN_HEIGHT)
        
        return target_width, target_height
    
    def get_centered_position(self, width: int, height: int) -> Tuple[int, int]:
        """
        Calculate the centered position for a window.
        
        Args:
            width: Window width.
            height: Window height.
        
        Returns:
            Tuple of (x, y) position to center the window.
        """
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
            threshold: Minimum scale change to trigger update (default 2% for smoother scaling).
        
        Returns:
            True if scale changed significantly, False otherwise.
        """
        new_scale = self.calculate_scale(window_width, window_height)
        
        # Update if scale changed beyond threshold (smaller = smoother)
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
            # Default to body font if key not found
            font_key = "body"
        
        base_size, min_size, max_size = FONT_BOUNDS[font_key]
        scaled_size = int(base_size * self._current_scale)
        
        # Clamp to bounds
        return max(min_size, min(scaled_size, max_size))
    
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
        
        Args:
            base_width: Base popup width.
            base_height: Base popup height.
            use_window_scale: If True, scale based on current window. If False, use screen.
            min_width: Optional minimum width to prevent content clipping.
            min_height: Optional minimum height to prevent buttons being hidden.
        
        Returns:
            Tuple of (width, height) for the popup.
        """
        if use_window_scale:
            # Use the current window scale for popup sizing
            # This ensures popups match the current main window size
            popup_scale = max(self._current_scale, 0.6)  # Minimum 60%
        else:
            # Scale based on screen size relative to 1920x1080
            popup_scale = min(
                self._screen_width / 1920,
                self._screen_height / 1080,
                1.0
            )
            popup_scale = max(popup_scale, 0.6)
        
        width = int(base_width * popup_scale)
        height = int(base_height * popup_scale)
        
        # Enforce minimum dimensions to prevent content clipping
        if min_width is not None:
            width = max(width, min_width)
        if min_height is not None:
            height = max(height, min_height)
        
        return width, height
    
    def get_popup_fonts_scale(self) -> float:
        """
        Get the scale factor to use for popup fonts.
        
        Returns:
            Scale factor for popup fonts (based on current window scale).
        """
        return max(self._current_scale, 0.7)  # Minimum 70% for readability


def get_screen_scale_factor(root: tk.Tk) -> float:
    """
    Get a scale factor based on screen size (utility function).
    
    Args:
        root: Tkinter root window.
    
    Returns:
        Scale factor relative to 1920x1080.
    """
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    
    # Normalize for Retina displays on macOS bundled apps
    if sys.platform == "darwin" and _is_bundled() and screen_width > 2000:
        try:
            dpi = root.winfo_fpixels('1i')
            if dpi > 100:
                scale_factor = dpi / 72.0
                screen_width = int(screen_width / scale_factor)
                screen_height = int(screen_height / scale_factor)
        except Exception:
            pass
    
    scale = min(screen_width / 1920, screen_height / 1080, 1.0)
    return max(scale, 0.6)  # Minimum 60% scale


# --- Design System Constants (Seraphic Focus) ---
COLORS = {
    "bg": "#F9F8F4",          # Warm Cream
    "surface": "#FFFFFF",      # White Cards
    "text_primary": "#1C1C1E", # Sharp Black
    "text_secondary": "#8E8E93", # System Gray
    "accent": "#2C3E50",       # Dark Blue/Grey
    "button_bg": "#1C1C1E",    # Black for primary actions
    "button_bg_hover": "#333333", # Dark grey for hover
    "button_text": "#FFFFFF",
    "border": "#E5E5EA",
    "shadow_light": "#E5E5EA", 
    "shadow_lighter": "#F2F2F7",
    "success": "#34C759",      # Subtle green
    "input_bg": "#F2F0EB",     # Light beige for inputs
    "link": "#2C3E50",          # Link color
    "status_gadget": "#EF4444", # Red for errors
    "button_start": "#34C759",  # Green for success/start
    "button_start_hover": "#2DB84C"
}

FONTS = {
    "display": ("Georgia", 32, "bold"),
    "heading": ("Georgia", 24, "bold"),
    "subheading": ("Georgia", 18),
    "body": ("Helvetica", 14),
    "body_bold": ("Helvetica", 14, "bold"),
    "caption": ("Helvetica", 12, "bold"),
    "small": ("Helvetica", 12),
    "input": ("Helvetica", 14)
}

class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command=None, width=200, height=50, radius=25, bg_color=COLORS["button_bg"], hover_color=None, text_color=COLORS["button_text"], font_type="body_bold", canvas_bg=None):
        # Use parent's background color if not specified, fallback to surface color
        if canvas_bg is None:
            try:
                canvas_bg = parent.cget("bg")
            except (tk.TclError, AttributeError):
                canvas_bg = COLORS["surface"]
        
        super().__init__(parent, width=width, height=height, bg=canvas_bg, highlightthickness=0)
        self.command = command
        self.radius = radius
        self.bg_color = bg_color
        self.hover_color = hover_color or bg_color
        self.text_color = text_color
        self.text_str = text
        self.font_type = font_type
        self._original_bg = bg_color
        self._canvas_bg = canvas_bg
        
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        
        self.draw()

    def draw(self, offset=0):
        self.delete("all")
        w = int(self["width"])
        h = int(self["height"])
        
        # Try to use actual size if available
        if self.winfo_width() > 1: w = self.winfo_width()
        if self.winfo_height() > 1: h = self.winfo_height()

        x1, y1 = 2, 2 + offset
        x2, y2 = w - 2, h - 2 + offset
        r = self.radius
        
        if r > h/2: r = h/2
        
        # Shadow
        if offset == 0:
            self.create_rounded_rect(x1+2, y1+4, x2+2, y2+4, r, fill=COLORS["shadow_light"], outline="")

        # Body
        self.create_rounded_rect(x1, y1, x2, y2, r, fill=self.bg_color, outline=self.bg_color)
        
        # Text
        self.create_text(w//2, h//2 + offset, text=self.text_str, fill=self.text_color, font=FONTS[self.font_type])

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text_str = kwargs.pop("text")
        if "bg_color" in kwargs:
            self.bg_color = kwargs.pop("bg_color")
            self._original_bg = self.bg_color
        if "hover_color" in kwargs:
            self.hover_color = kwargs.pop("hover_color")
        if "text_color" in kwargs:
            self.text_color = kwargs.pop("text_color")
            
        super().configure(**kwargs)
        self.draw()

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _on_click(self, event):
        if self.command:
            self.command()
        self.draw(offset=2)
        self.after(100, lambda: self.draw(offset=0))

    def _on_enter(self, event):
        self.bg_color = self.hover_color
        self.draw()

    def _on_leave(self, event):
        self.bg_color = self._original_bg
        self.draw()

class Card(tk.Canvas):
    def __init__(self, parent, width=300, height=150, radius=20, bg_color=COLORS["surface"]):
        super().__init__(parent, width=width, height=height, bg=COLORS["bg"], highlightthickness=0)
        self.radius = radius
        self.bg_color = bg_color
        self.draw()

    def draw(self):
        self.delete("all")
        w = int(self["width"])
        h = int(self["height"])
        r = self.radius
        
        # Soft Shadow
        self.create_rounded_rect(4, 8, w-4, h-4, r, fill=COLORS["shadow_lighter"], outline="")
        
        # Card Body
        self.create_rounded_rect(2, 2, w-6, h-6, r, fill=self.bg_color, outline=COLORS["shadow_lighter"])

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)

class StyledEntry(tk.Frame):
    def __init__(self, parent, placeholder="", width=200):
        super().__init__(parent, bg=COLORS["surface"])
        self.placeholder = placeholder
        self.radius = 12  # Slightly rounded corners
        
        # Canvas for the input area (replacing Frame container)
        self.canvas = tk.Canvas(self, bg=COLORS["surface"], height=50, highlightthickness=0)
        self.canvas.pack(fill="x")
        
        # Entry widget
        self.entry = tk.Entry(self.canvas, font=FONTS["input"], bg=COLORS["input_bg"], 
                            fg=COLORS["text_primary"], relief="flat", highlightthickness=0,
                            insertbackground=COLORS["text_primary"])  # Black cursor
        
        # Initial draw will happen on configure, but we need to create the window item once
        self.entry_window = self.canvas.create_window(0, 0, window=self.entry, anchor="nw")
        
        self.entry.insert(0, placeholder)
        self.entry.config(fg=COLORS["text_secondary"])
        
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<Key>", self._on_key_press)
        
        # Error label - always packed to reserve space, empty text when no error
        self.error_label = tk.Label(self, text=" ", font=("Helvetica", 11), fg=COLORS["status_gadget"], 
                                   bg=COLORS["surface"], anchor="w", wraplength=300, justify="left", height=1)
        self.error_label.pack(fill="x", pady=(2, 0))
        
        self.command = None
        self._has_feedback = False
        self.current_border_color = COLORS["input_bg"] # Default invisible border
        
        # Bind resize event
        self.canvas.bind("<Configure>", self._draw)

    def _draw(self, event=None):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        
        # Avoid drawing if too small
        if w < 20: return
            
        self.canvas.delete("bg_rect")
        
        # Draw rounded background
        # Tag it 'bg_rect' so we can delete/update it
        self.create_rounded_rect(2, 2, w-2, h-2, self.radius, fill=COLORS["input_bg"], outline=self.current_border_color, width=2, tags="bg_rect")
        
        # Ensure entry is on top
        self.canvas.tag_lower("bg_rect")
        
        # Position entry
        # Padding: x=15, y=10 (approximate centering)
        entry_h = self.entry.winfo_reqheight()
        entry_y = (h - entry_h) // 2
        self.canvas.coords(self.entry_window, 15, entry_y)
        self.canvas.itemconfigure(self.entry_window, width=w-30)

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def show_error(self, message):
        self.error_label.config(text=message, fg=COLORS["status_gadget"])
        self.current_border_color = COLORS["status_gadget"]
        self._draw()
        self._has_feedback = True

    def show_success(self, message):
        self.error_label.config(text=message, fg=COLORS["button_start"])
        self.current_border_color = COLORS["button_start"]
        self._draw()
        self._has_feedback = True
        
    def show_info(self, message):
        self.error_label.config(text=message, fg=COLORS["text_secondary"])
        self.current_border_color = COLORS["accent"]
        self._draw()
        self._has_feedback = True

    def clear_error(self):
        self.error_label.config(text=" ")  # Keep space reserved
        # If focused, show accent border, else default
        if self.entry.focus_get() == self.entry:
            self.current_border_color = COLORS["accent"]
        else:
            self.current_border_color = COLORS["input_bg"]
        self._draw()
        self._has_feedback = False

    def _on_focus_in(self, event):
        # Don't clear error on focus in, wait for typing
        if self.entry.get() == self.placeholder:
            self.entry.delete(0, "end")
            self.entry.config(fg=COLORS["text_primary"])
        self.current_border_color = COLORS["accent"]
        self._draw()
        
    def _on_key_press(self, event):
        self.clear_error()

    def _on_focus_out(self, event):
        if not self.entry.get():
            self.entry.insert(0, self.placeholder)
            self.entry.config(fg=COLORS["text_secondary"])
        # Only reset border if no feedback is showing
        if not self._has_feedback:
            self.current_border_color = COLORS["input_bg"]
            self._draw()
        
    def _on_return(self, event):
        if self.command:
            self.command()

    def get(self):
        val = self.entry.get()
        return "" if val == self.placeholder else val
        
    def bind_return(self, command):
        self.command = command
        
    def delete(self, first, last=None):
        self.entry.delete(first, last)
        
    def insert(self, index, string):
        self.entry.insert(index, string)
