"""
Gavin AI - Desktop GUI Application

A minimal tkinter GUI that wraps the existing detection code,
providing a user-friendly interface for study session tracking.
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

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from camera.capture import CameraCapture
from camera.vision_detector import VisionDetector
from camera import get_event_type
from tracking.session import Session
from tracking.analytics import compute_statistics
from ai.summariser import SessionSummariser
from reporting.pdf_report import generate_full_report

logger = logging.getLogger(__name__)

# --- Color Palette ---
# Soft slate blue theme with warm accents
COLORS = {
    "bg_dark": "#1E293B",           # Soft slate blue background
    "bg_medium": "#334155",         # Card/panel background
    "bg_light": "#475569",          # Lighter panel elements
    "accent_primary": "#38BDF8",    # Sky blue accent
    "accent_warm": "#FB923C",       # Warm orange for alerts
    "text_primary": "#F1F5F9",      # Off-white text
    "text_secondary": "#94A3B8",    # Muted text
    "text_white": "#FFFFFF",        # Pure white for buttons
    "status_focused": "#4ADE80",    # Green for focused
    "status_away": "#FBBF24",       # Amber for away
    "status_phone": "#F87171",      # Red for phone
    "status_idle": "#64748B",       # Gray for idle
    "button_start": "#22C55E",      # Green start button
    "button_start_hover": "#16A34A", # Darker green on hover
    "button_stop": "#EF4444",       # Red stop button
    "button_stop_hover": "#DC2626", # Darker red on hover
}

# Privacy settings file
PRIVACY_FILE = Path(__file__).parent.parent / "data" / ".privacy_accepted"

# Base dimensions for scaling
BASE_WIDTH = 420
BASE_HEIGHT = 420
MIN_WIDTH = 350
MIN_HEIGHT = 380


class RoundedFrame(tk.Canvas):
    """
    A frame with rounded corners using Canvas.
    
    Draws a rounded rectangle background and allows placing widgets inside.
    """
    
    def __init__(self, parent, bg_color: str, corner_radius: int = 15, **kwargs):
        """
        Initialize rounded frame.
        
        Args:
            parent: Parent widget
            bg_color: Background color for the rounded rectangle
            corner_radius: Radius of the corners
        """
        # Get parent background for canvas
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_dark"]
        
        super().__init__(parent, highlightthickness=0, bg=parent_bg, **kwargs)
        
        self.bg_color = bg_color
        self.corner_radius = corner_radius
        self._rect_id = None
        
        # Bind resize to redraw
        self.bind("<Configure>", self._on_resize)
    
    def _on_resize(self, event=None):
        """Redraw the rounded rectangle on resize."""
        self.delete("rounded_bg")
        
        width = self.winfo_width()
        height = self.winfo_height()
        
        if width > 1 and height > 1:
            self._draw_rounded_rect(0, 0, width, height, self.corner_radius, self.bg_color)
    
    def _draw_rounded_rect(self, x1, y1, x2, y2, radius, color):
        """
        Draw a rounded rectangle.
        
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
        parent_bg = parent.cget("bg") if hasattr(parent, "cget") else COLORS["bg_dark"]
        
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
                self._current_bg = COLORS["bg_light"]
            else:
                self._current_bg = self.bg_color
        
        self._draw_button()


class GavinGUI:
    """
    Main GUI application for Gavin AI study tracker.
    
    Provides a clean, scalable interface with:
    - Start/Stop session button
    - Status indicator (Focused / Away / Phone Detected)
    - Session timer
    - Auto-generates PDF report on session stop
    """
    
    def __init__(self):
        """Initialize the GUI application."""
        self.root = tk.Tk()
        self.root.title("Gavin AI")
        self.root.configure(bg=COLORS["bg_dark"])
        
        # Window size and positioning - center on screen
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
        self.current_status = "idle"  # idle, focused, away, phone
        self.session_start_time: Optional[datetime] = None
        
        # UI update lock
        self.ui_lock = threading.Lock()
        
        # Create UI elements
        self._create_fonts()
        self._create_widgets()
        
        # Bind resize event for scaling
        self.root.bind("<Configure>", self._on_resize)
        
        # Check privacy acceptance
        self.root.after(100, self._check_privacy)
        
        # Update timer periodically
        self._update_timer()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _create_fonts(self):
        """Create custom fonts for the UI with fixed sizes."""
        # Use system fonts - sizes are fixed and don't scale
        self.font_title = tkfont.Font(
            family="Helvetica Neue", size=26, weight="bold"
        )
        
        self.font_timer = tkfont.Font(
            family="Menlo", size=36, weight="bold"
        )
        
        self.font_status = tkfont.Font(
            family="Helvetica", size=15, weight="normal"
        )
        
        self.font_button = tkfont.Font(
            family="Helvetica", size=14, weight="bold"
        )
        
        self.font_small = tkfont.Font(
            family="Helvetica", size=11, weight="normal"
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
            
            # Scale button proportionally (but keep minimum size)
            if hasattr(self, 'start_stop_btn'):
                new_btn_width = max(140, int(160 * new_scale))
                new_btn_height = max(40, int(44 * new_scale))
                self.start_stop_btn.configure(width=new_btn_width, height=new_btn_height)
                self.start_stop_btn._draw_button()
            
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
            "phone": COLORS["status_phone"],
        }
        return color_map.get(self.current_status, COLORS["status_idle"])
    
    def _create_widgets(self):
        """Create all UI widgets with scalable layout."""
        # Main container using grid for proportional spacing
        self.main_frame = tk.Frame(self.root, bg=COLORS["bg_dark"])
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)
        
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
        self.main_frame.grid_rowconfigure(0, weight=1)   # Top spacer
        self.main_frame.grid_rowconfigure(1, weight=0)   # Title
        self.main_frame.grid_rowconfigure(2, weight=1)   # Spacer
        self.main_frame.grid_rowconfigure(3, weight=0)   # Status
        self.main_frame.grid_rowconfigure(4, weight=2)   # Spacer (more weight)
        self.main_frame.grid_rowconfigure(5, weight=0)   # Timer
        self.main_frame.grid_rowconfigure(6, weight=2)   # Spacer (more weight)
        self.main_frame.grid_rowconfigure(7, weight=0)   # Button
        self.main_frame.grid_rowconfigure(8, weight=1)   # Bottom spacer
        
        # --- Title Section ---
        title_frame = tk.Frame(self.main_frame, bg=COLORS["bg_dark"])
        title_frame.grid(row=1, column=0, sticky="ew")
        
        self.title_label = tk.Label(
            title_frame,
            text="GAVIN AI",
            font=self.font_title,
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_dark"]
        )
        self.title_label.pack()
        
        self.subtitle_label = tk.Label(
            title_frame,
            text="Study Focus Tracker",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_dark"]
        )
        self.subtitle_label.pack()
        
        # --- Status Card (Rounded) ---
        status_container = tk.Frame(self.main_frame, bg=COLORS["bg_dark"])
        status_container.grid(row=3, column=0, sticky="ew", padx=10)
        
        self.status_card = RoundedFrame(
            status_container,
            bg_color=COLORS["bg_medium"],
            corner_radius=12,
            height=60
        )
        self.status_card.pack(fill=tk.X)
        
        # Status content frame (inside the rounded card)
        self.status_content = tk.Frame(self.status_card, bg=COLORS["bg_medium"])
        self.status_content.place(relx=0.5, rely=0.5, anchor="center")
        
        # Status dot (using canvas for round shape)
        self.status_dot = tk.Canvas(
            self.status_content,
            width=14,
            height=14,
            bg=COLORS["bg_medium"],
            highlightthickness=0
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 10))
        self._draw_status_dot(COLORS["status_idle"])
        
        self.status_label = tk.Label(
            self.status_content,
            text="Ready to Start",
            font=self.font_status,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_medium"]
        )
        self.status_label.pack(side=tk.LEFT)
        
        # --- Timer Display ---
        timer_frame = tk.Frame(self.main_frame, bg=COLORS["bg_dark"])
        timer_frame.grid(row=5, column=0, sticky="ew")
        
        self.timer_label = tk.Label(
            timer_frame,
            text="00:00:00",
            font=self.font_timer,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_dark"]
        )
        self.timer_label.pack()
        
        self.timer_sub_label = tk.Label(
            timer_frame,
            text="Session Duration",
            font=self.font_small,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_dark"]
        )
        self.timer_sub_label.pack(pady=(5, 0))
        
        # --- Button Section ---
        button_frame = tk.Frame(self.main_frame, bg=COLORS["bg_dark"])
        button_frame.grid(row=7, column=0, sticky="ew")
        
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
            width=160,
            height=44
        )
        self.start_stop_btn.pack()
        
    
    def _draw_status_dot(self, color: str):
        """
        Draw the status indicator dot (circle).
        
        Args:
            color: Hex color for the dot
        """
        self.status_dot.delete("all")
        # Draw a perfect circle
        self.status_dot.create_oval(1, 1, 13, 13, fill=color, outline="")
    
    def _check_privacy(self):
        """Check if privacy notice has been accepted, show if not."""
        if not PRIVACY_FILE.exists():
            self._show_privacy_notice()
    
    def _show_privacy_notice(self):
        """Display the privacy notice popup."""
        privacy_text = """Gavin AI uses OpenAI's Vision API to monitor your study sessions.

How it works:
• Camera frames are sent to OpenAI for analysis
• AI detects your presence and phone usage
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
    
    def _toggle_session(self):
        """Toggle between starting and stopping a session."""
        if not self.is_running:
            self._start_session()
        else:
            self._stop_session()
    
    def _start_session(self):
        """Start a new study session."""
        # Verify API key exists
        if not config.OPENAI_API_KEY:
            messagebox.showerror(
                "API Key Required",
                "OpenAI API key not found!\n\n"
                "Please set OPENAI_API_KEY in your .env file.\n"
                "Get your key from: https://platform.openai.com/api-keys"
            )
            return
        
        # Initialize session
        self.session = Session()
        self.session.start()
        self.session_start_time = datetime.now()
        self.is_running = True
        self.should_stop.clear()
        
        # Update UI
        self._update_status("focused", "Monitoring...")
        self.start_stop_btn.configure_button(
            text="Stop Session",
            bg_color=COLORS["button_stop"],
            hover_color=COLORS["button_stop_hover"]
        )
        
        # Start detection thread
        self.detection_thread = threading.Thread(
            target=self._detection_loop,
            daemon=True
        )
        self.detection_thread.start()
        
        logger.info("Session started via GUI")
    
    def _stop_session(self):
        """Stop the current session and auto-generate report."""
        if not self.is_running:
            return
        
        # Signal thread to stop
        self.should_stop.set()
        self.is_running = False
        
        # Wait for detection thread to finish
        if self.detection_thread and self.detection_thread.is_alive():
            self.detection_thread.join(timeout=2.0)
        
        # End session
        if self.session:
            self.session.end()
        
        # Update UI to show generating status
        self._update_status("idle", "Generating Reports...")
        self.start_stop_btn.configure_button(
            text="Generating...",
            state=tk.DISABLED
        )
        self.root.update()
        
        logger.info("Session stopped via GUI")
        
        # Auto-generate report
        self._generate_report()
    
    def _detection_loop(self):
        """
        Main detection loop running in a separate thread.
        
        Captures frames from camera and analyzes them using OpenAI Vision API.
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
                    
                    # Throttle detection to configured FPS
                    current_time = time.time()
                    time_since_detection = current_time - last_detection_time
                    
                    if time_since_detection >= (1.0 / config.DETECTION_FPS):
                        # Perform detection using OpenAI Vision
                        detection_state = detector.get_detection_state(frame)
                        
                        # Determine event type
                        event_type = get_event_type(detection_state)
                        
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
    
    def _update_detection_status(self, event_type: str):
        """
        Update the status display based on detection result.
        
        Args:
            event_type: Type of event detected
        """
        status_map = {
            config.EVENT_PRESENT: ("focused", "Focused"),
            config.EVENT_AWAY: ("away", "Away from Desk"),
            config.EVENT_PHONE_SUSPECTED: ("phone", "Phone Detected"),
        }
        
        status, text = status_map.get(event_type, ("idle", "Unknown"))
        
        # Schedule UI update on main thread
        self.root.after(0, lambda: self._update_status(status, text))
    
    def _update_status(self, status: str, text: str):
        """
        Update the status indicator and label.
        
        Args:
            status: Status type (idle, focused, away, phone)
            text: Display text
        """
        with self.ui_lock:
            self.current_status = status
            color = self._get_current_status_color()
            self._draw_status_dot(color)
            self.status_label.configure(text=text)
    
    def _update_timer(self):
        """Update the timer display every second."""
        if self.is_running and self.session_start_time:
            elapsed = datetime.now() - self.session_start_time
            total_seconds = int(elapsed.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            self.timer_label.configure(text=time_str)
        
        # Schedule next update
        self.root.after(1000, self._update_timer)
    
    def _generate_report(self):
        """Generate PDF report for the completed session."""
        if not self.session:
            self._reset_button_state()
            return
        
        try:
            # Compute statistics
            stats = compute_statistics(
                self.session.events,
                self.session.get_duration()
            )
            
            # Generate AI summary
            summariser = SessionSummariser()
            summary_data = summariser.generate_summary(stats)
            
            # Save session
            self.session.save()
            
            # Generate PDF
            summary_path, logs_path = generate_full_report(
                stats,
                summary_data,
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
                f"Reports saved to:\n\n"
                f"Summary: {summary_path.name}\n"
                f"Logs: {logs_path.name}\n\n"
                f"Location: {summary_path.parent}\n\n"
                "Would you like to open the summary report?"
            )
            
            if result:
                self._open_file(summary_path)
            
            # Reset status after showing dialog
            self._update_status("idle", "Ready to Start")
            
            logger.info(f"Report generated: {summary_path}")
            
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
            # Stop session (will generate report)
            self.should_stop.set()
            self.is_running = False
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=2.0)
            if self.session:
                self.session.end()
        
        self.root.destroy()
    
    def run(self):
        """Start the GUI application main loop."""
        logger.info("Starting Gavin AI GUI")
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
    
    # Check for API key early
    if not config.OPENAI_API_KEY:
        logger.warning("OpenAI API key not found - user will be prompted")
    
    # Create and run GUI
    app = GavinGUI()
    app.run()


if __name__ == "__main__":
    main()
