"""
Payment Screen for BrainDock - CustomTkinter Edition.

Displays a payment gate before app access, allowing users to:
- Purchase via Stripe Checkout
- Verify previous payment with session ID
"""

import customtkinter as ctk
from tkinter import messagebox
import threading
import logging
import re
import sys
import socket
import time
from pathlib import Path
from typing import Optional, Callable, Union
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from licensing.license_manager import get_license_manager
from licensing.stripe_integration import get_stripe_integration, STRIPE_AVAILABLE
from gui.ui_components import (
    RoundedButton, Card, StyledEntry, COLORS,
    ScalingManager, get_ctk_font, get_font_serif, get_font_sans
)
from gui.font_loader import load_bundled_fonts

logger = logging.getLogger(__name__)


def set_windows_toplevel_icon(window) -> None:
    """
    Set the icon for a Toplevel window on Windows.
    
    On Windows, each Toplevel window needs its icon set explicitly,
    otherwise it shows the default Python/Tk icon.
    
    Args:
        window: The Toplevel or CTkToplevel window
    """
    if sys.platform != 'win32':
        return
    
    icon_locations = []
    
    # Try bundled icon first (PyInstaller), then development paths
    if getattr(sys, 'frozen', False):
        icon_locations.append(Path(sys._MEIPASS) / 'assets' / 'icon.ico')
        icon_locations.append(Path(sys._MEIPASS) / 'icon.ico')
    else:
        icon_locations.append(config.BASE_DIR / 'build' / 'icon.ico')
        icon_locations.append(config.BASE_DIR / 'assets' / 'icon.ico')
    
    for loc in icon_locations:
        if loc.exists():
            try:
                window.iconbitmap(str(loc))
                return
            except Exception as e:
                logger.debug(f"Could not set toplevel icon: {e}")
                break


# PIL for logo image support
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageTk = None

# Use BASE_DIR from config for proper bundled app support
ASSETS_DIR = config.BASE_DIR / "assets"


class LocalPaymentServer:
    """
    Temporary local HTTP server to handle Stripe redirect after payment.
    
    Serves a success page and notifies the app when payment redirect is received.
    Uses 127.0.0.1 instead of localhost for more reliable cross-platform compatibility.
    """
    
    # Default port to try first
    DEFAULT_PORT = 5678
    # Fallback ports to try if default is unavailable
    FALLBACK_PORTS = [5679, 5680, 8765, 8766, 9876, 9877]
    # Use IP address instead of hostname for reliable Windows compatibility
    HOST = '127.0.0.1'
    
    def __init__(self, callback: Callable[[str], None]):
        """
        Initialize the local payment server.
        
        Args:
            callback: Function called with session_id when redirect is received.
        """
        self.callback = callback
        self.port = self._find_available_port()
        self.server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False
        self._session_received = False
    
    def _find_available_port(self) -> int:
        """
        Find an available port for the server.
        
        Tries default port first, then fallbacks, then OS-assigned.
        
        Returns:
            An available port number.
        """
        # Try default port first
        if self._is_port_available(self.DEFAULT_PORT):
            return self.DEFAULT_PORT
        
        # Try fallback ports
        for port in self.FALLBACK_PORTS:
            if self._is_port_available(port):
                return port
        
        # Last resort: let OS assign a port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.HOST, 0))
                return s.getsockname()[1]
        except OSError as e:
            logger.warning(f"Could not get OS-assigned port: {e}")
            # Return default and hope for the best
            return self.DEFAULT_PORT
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available on the host IP."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # Set SO_REUSEADDR to avoid "address already in use" on quick restarts
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.HOST, port))
                return True
        except OSError:
            return False
    
    def get_success_url(self) -> str:
        """Get the URL to use as Stripe's success_url."""
        # Use 127.0.0.1 for reliable cross-platform compatibility
        return f"http://{self.HOST}:{self.port}/success"
    
    def get_cancel_url(self) -> str:
        """Get the URL to use as Stripe's cancel_url."""
        return f"http://{self.HOST}:{self.port}/cancel"
    
    def start(self) -> bool:
        """
        Start the local HTTP server in a background thread.
        
        Returns:
            True if server started successfully, False otherwise.
        """
        if self._running:
            return True
        
        try:
            server_instance = self
            
            class PaymentHandler(BaseHTTPRequestHandler):
                """Handler for payment redirect requests."""
                
                # Increase timeout for slow connections
                timeout = 30
                
                def log_message(self, format, *args):
                    """Suppress default logging."""
                    pass
                
                def do_GET(self):
                    """Handle GET requests."""
                    parsed_path = urlparse(self.path)
                    
                    if parsed_path.path == '/success':
                        query_params = parse_qs(parsed_path.query)
                        session_id = query_params.get('session_id', [None])[0]
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html; charset=utf-8')
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        
                        html = self._get_success_html()
                        self.wfile.write(html.encode('utf-8'))
                        
                        if session_id and not server_instance._session_received:
                            server_instance._session_received = True
                            logger.info(f"Payment redirect received with session: {session_id[:20]}...")
                            threading.Thread(
                                target=server_instance.callback,
                                args=(session_id,),
                                daemon=True
                            ).start()
                    
                    elif parsed_path.path == '/cancel':
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html; charset=utf-8')
                        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                        self.end_headers()
                        
                        html = self._get_cancel_html()
                        self.wfile.write(html.encode('utf-8'))
                    
                    elif parsed_path.path == '/health':
                        # Health check endpoint for debugging
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(b'OK')
                    
                    else:
                        self.send_response(404)
                        self.end_headers()
                
                def _get_success_html(self) -> str:
                    """Generate success page HTML."""
                    return """<!DOCTYPE html>
<html>
<head>
    <title>Payment Successful - BrainDock</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            color: white;
        }
        .container {
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.1);
            border-radius: 16px;
            backdrop-filter: blur(10px);
        }
        .checkmark { font-size: 64px; margin-bottom: 20px; }
        h1 { margin: 0 0 10px 0; font-size: 28px; }
        p { margin: 0; opacity: 0.9; font-size: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="checkmark">&#10003;</div>
        <h1>Payment Successful!</h1>
        <p>You can close this window and return to BrainDock.</p>
        <p style="margin-top: 15px; font-size: 14px; opacity: 0.8;">The app will activate automatically.</p>
    </div>
</body>
</html>"""
                
                def _get_cancel_html(self) -> str:
                    """Generate cancel page HTML."""
                    return """<!DOCTYPE html>
<html>
<head>
    <title>Payment Cancelled - BrainDock</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #6B7280 0%, #4B5563 100%);
            color: white;
        }
        .container {
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.1);
            border-radius: 16px;
            backdrop-filter: blur(10px);
        }
        h1 { margin: 0 0 10px 0; font-size: 28px; }
        p { margin: 0; opacity: 0.9; font-size: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Payment Cancelled</h1>
        <p>You can close this window and return to BrainDock to try again.</p>
    </div>
</body>
</html>"""
            
            # Create server with explicit address binding
            self.server = HTTPServer((self.HOST, self.port), PaymentHandler)
            self.server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.timeout = 2  # Slightly longer timeout for reliability
            self._running = True
            
            def serve():
                """Server loop that can be stopped."""
                while self._running:
                    try:
                        self.server.handle_request()
                    except Exception as e:
                        if self._running:  # Only log if we didn't intentionally stop
                            logger.warning(f"Server handle_request error: {e}")
            
            self._server_thread = threading.Thread(target=serve, daemon=True)
            self._server_thread.start()
            
            # Verify server is actually listening by attempting a quick connection
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.settimeout(1)
                test_sock.connect((self.HOST, self.port))
                test_sock.close()
                logger.info(f"Local payment server started and verified on {self.HOST}:{self.port}")
            except Exception as e:
                logger.warning(f"Server started but connection test failed: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start local payment server: {e}")
            return False
    
    def stop(self):
        """Stop the local HTTP server and wait for thread to finish."""
        self._running = False
        
        if self.server:
            try:
                self.server.server_close()
            except Exception as e:
                logger.warning(f"Error closing server: {e}")
            self.server = None
        
        if self._server_thread is not None and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
        self._server_thread = None
        logger.debug("Local payment server stopped")
    
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running


class PaymentScreen:
    """
    Full-screen payment gate displayed before app access.
    
    Shows purchase options and payment verification status.
    """
    
    def __init__(self, root: ctk.CTk, on_success: Callable[[], None]):
        """
        Initialize the payment screen.
        
        Args:
            root: The root CustomTkinter window.
            on_success: Callback to invoke when license is activated.
        """
        self.root = root
        self.on_success = on_success
        self.license_manager = get_license_manager()
        self.stripe = get_stripe_integration()
        
        # Load bundled fonts
        load_bundled_fonts()
        
        # Initialize scaling manager for responsive UI
        self.scaling_manager = ScalingManager(self.root)
        
        # Card sizing constants - FIXED aspect ratio (width:height = 550:395 ≈ 1.39:1)
        # These must be defined before _calculate_scale() which uses them
        self._card_aspect_ratio = 550 / 395
        self._card_max_width = 550
        self._card_max_height = 395
        self._card_min_width = 380
        self._card_min_height = int(380 / self._card_aspect_ratio)  # ~273
        
        # Calculate scale factor based on expected card size
        self._calculate_scale()
        
        # Pending session for verification
        self._pending_session_id: Optional[str] = None
        
        # Track if we're waiting for payment
        self._waiting_for_payment = False
        
        # Local server for handling Stripe redirect
        self._local_server: Optional[LocalPaymentServer] = None
        
        # Polling state (protected by _polling_lock for thread safety)
        self._polling_lock = threading.Lock()
        self._polling_active = False
        self._polling_thread: Optional[threading.Thread] = None
        self._payment_detected = False
        
        # Payment ready state
        self._payment_ready = False
        self._payment_session_id: Optional[str] = None
        self._payment_info: Optional[dict] = None
        
        # Polling configuration
        self._poll_interval = 3
        self._poll_timeout = 600
        
        # Main thread payment checker (Windows compatibility)
        # On Windows, root.after() from background threads can be unreliable.
        # This checker runs in the main thread and monitors payment state.
        self._main_checker_id: Optional[str] = None
        self._main_checker_interval = 500  # Check every 500ms
        
        # UI references
        self.main_frame: Optional[ctk.CTkFrame] = None
        self.verify_button: Optional[RoundedButton] = None
        self.session_entry: Optional[StyledEntry] = None
        self.logo_image = None
        self.btn_pay: Optional[RoundedButton] = None
        self.card_bg: Optional[ctk.CTkFrame] = None
        self.center_container: Optional[ctk.CTkFrame] = None
        
        # Card resize tracking
        self._last_card_size: Optional[tuple] = None
        
        self._setup_ui()
        
        # Bind resize handler after UI setup
        self.root.after(100, self._initialize_responsive_card)
        
        # Bind focus events to detect when user returns to app
        # Use both <Activate> (reliable on macOS) and <FocusIn> (fallback)
        self.root.bind("<Activate>", self._on_window_focus)
        self.root.bind("<FocusIn>", self._on_window_focus)
    
    def _clear_entry_feedback(self, event=None):
        """Clear entry feedback when user types."""
        if self.session_entry:
            self.session_entry.clear_error()
    
    def _calculate_scale(self):
        """
        Calculate the scale factor based on expected card size.
        
        Content scale is derived from how much the card shrinks from its
        maximum size, ensuring inner elements scale proportionally to prevent
        clipping on smaller screens.
        """
        # Get window dimensions (may not be realized yet, use screen as fallback)
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        
        if window_width < 100 or window_height < 100:
            # Window not yet realized, estimate from screen size
            window_width = int(self.scaling_manager.screen_width * 0.4)
            window_height = int(self.scaling_manager.screen_height * 0.5)
        
        # Calculate available space for card
        available_width = window_width - 80   # Horizontal margins
        available_height = window_height - 160  # Logo + vertical margins
        
        # Determine card width that fits while maintaining aspect ratio
        # Try fitting by width first
        card_width_by_width = available_width
        card_height_by_width = card_width_by_width / self._card_aspect_ratio
        
        # If height doesn't fit, constrain by height instead
        if card_height_by_width > available_height:
            card_width = available_height * self._card_aspect_ratio
        else:
            card_width = card_width_by_width
        
        # Clamp to min/max bounds
        card_width = max(self._card_min_width, min(card_width, self._card_max_width))
        
        # Scale content based on card size relative to maximum
        self.screen_scale = card_width / self._card_max_width
        
        # Platform-specific minimum scale to ensure readability
        if sys.platform == "darwin":
            self.screen_scale = max(self.screen_scale, 0.65)
        else:
            # Windows/Linux: Higher minimum to account for DPI scaling
            self.screen_scale = max(self.screen_scale, 0.75)
    
    def _scale_dimension(self, base_value: int, min_value: Optional[int] = None) -> int:
        """Scale a dimension by the screen scale factor."""
        scaled = int(base_value * self.screen_scale)
        if min_value is not None:
            return max(scaled, min_value)
        return scaled
    
    def _scale_padding(self, base_padding: int) -> int:
        """Scale padding/margin by the screen scale factor."""
        return max(2, int(base_padding * self.screen_scale))
    
    def _initialize_responsive_card(self):
        """
        Initialize responsive card sizing with fixed aspect ratio.
        
        Sets up the card to maintain a consistent width:height ratio
        regardless of window size.
        """
        if not self.card_bg:
            return
        
        # Force geometry update
        self.root.update_idletasks()
        
        # Enable fixed sizing for responsive behavior
        self.card_bg.pack_propagate(False)
        
        # Calculate and apply initial size based on current window
        self._update_card_size()
        
        # Bind to window resize events
        self.root.bind("<Configure>", self._on_window_configure, add="+")
    
    def _calculate_card_size(self) -> tuple:
        """
        Calculate card size maintaining a fixed aspect ratio.
        
        The card always maintains the same width:height ratio (550:395 ≈ 1.39:1)
        regardless of window dimensions. It scales between minimum and maximum
        bounds while preserving this ratio.
        
        Returns:
            Tuple of (width, height) with consistent aspect ratio.
        """
        # Get current window size
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        
        # Fallback if window not yet sized
        if window_width < 100 or window_height < 100:
            window_width = int(self.scaling_manager.screen_width * 0.4)
            window_height = int(self.scaling_manager.screen_height * 0.5)
        
        # Available space for card (accounting for margins and logo)
        available_width = window_width - 80    # Horizontal margins
        available_height = window_height - 160  # Logo + vertical margins
        
        # Calculate the largest card that fits while maintaining aspect ratio
        # Try fitting by width
        card_width_by_width = available_width
        card_height_by_width = card_width_by_width / self._card_aspect_ratio
        
        # If that height exceeds available space, constrain by height instead
        if card_height_by_width > available_height:
            card_height = available_height
            card_width = card_height * self._card_aspect_ratio
        else:
            card_width = card_width_by_width
            card_height = card_height_by_width
        
        # Clamp to maximum bounds (card doesn't grow beyond max)
        if card_width > self._card_max_width:
            card_width = self._card_max_width
            card_height = self._card_max_height
        
        # Clamp to minimum bounds (maintains ratio at minimum too)
        if card_width < self._card_min_width:
            card_width = self._card_min_width
            card_height = self._card_min_height
        
        return int(card_width), int(card_height)
    
    def _update_card_size(self):
        """Update the card size based on current window dimensions."""
        if not self.card_bg:
            return
        
        new_width, new_height = self._calculate_card_size()
        
        # Only update if size changed significantly (avoid jitter)
        if self._last_card_size:
            old_w, old_h = self._last_card_size
            if abs(new_width - old_w) < 3 and abs(new_height - old_h) < 3:
                return
        
        self._last_card_size = (new_width, new_height)
        self.card_bg.configure(width=new_width, height=new_height)
    
    def _on_window_configure(self, event):
        """Handle window configure (resize) events."""
        # Only respond to root window resize, not child widget events
        if event.widget != self.root:
            return
        
        # Debounce rapid resize events
        if hasattr(self, '_resize_after_id'):
            self.root.after_cancel(self._resize_after_id)
        
        self._resize_after_id = self.root.after(50, self._update_card_size)

    def _setup_ui(self):
        """Set up the payment screen UI."""
        
        # Configure root window
        self.root.configure(fg_color=COLORS["bg"])
        
        # Main container
        self.main_frame = ctk.CTkFrame(self.root, fg_color=COLORS["bg"])
        self.main_frame.pack(fill="both", expand=True)
        
        # Center Container
        self.center_container = ctk.CTkFrame(self.main_frame, fg_color=COLORS["bg"])
        self.center_container.place(relx=0.5, rely=0.5, anchor="center")

        # Scaled padding values
        header_bottom_pad = self._scale_padding(38)
        
        # Header (Logo)
        header_frame = ctk.CTkFrame(self.center_container, fg_color=COLORS["bg"])
        header_frame.pack(fill="x", pady=(0, header_bottom_pad))
        
        # Load and display logo (scaled)
        logo_loaded = False
        if PIL_AVAILABLE:
            logo_path = ASSETS_DIR / "logo_with_text.png"
            if logo_path.exists():
                try:
                    img = Image.open(logo_path)
                    
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    
                    base_logo_height = 65
                    h = self._scale_dimension(base_logo_height, min_value=45)
                    aspect = img.width / img.height
                    img = img.resize((int(h * aspect), h), Image.Resampling.LANCZOS)
                    
                    # Create CTkImage for high-DPI support
                    self.logo_image = ctk.CTkImage(
                        light_image=img,
                        dark_image=img,
                        size=(int(h * aspect), h)
                    )
                    
                    logo_label = ctk.CTkLabel(
                        header_frame,
                        image=self.logo_image,
                        text="",
                        fg_color="transparent"
                    )
                    logo_label.pack()
                    logo_loaded = True
                except Exception as e:
                    logger.warning(f"Could not load logo: {e}")
        
        # Fallback to text title if logo couldn't be loaded
        if not logo_loaded:
            title_label = ctk.CTkLabel(
                header_frame,
                text="BrainDock",
                font=get_ctk_font("heading", self.screen_scale),
                text_color=COLORS["text_primary"],
                fg_color="transparent"
            )
            title_label.pack()
        
        # Main Card Container - initially let content determine size
        # Size will be made responsive after layout via _initialize_responsive_card
        self.card_bg = ctk.CTkFrame(
            self.center_container,
            corner_radius=28,
            fg_color=COLORS["surface"]
        )
        self.card_bg.pack()
        
        # Outer padding frame - fills the card with padding margins
        inner_padding = self._scale_padding(30)
        self._card_padding_frame = ctk.CTkFrame(self.card_bg, fg_color=COLORS["surface"])
        self._card_padding_frame.pack(fill="both", expand=True, padx=inner_padding, pady=inner_padding)
        
        # Calculate content width (card width minus padding on both sides)
        # This gives inner_frame a fixed width for content that uses fill="x"
        content_width = self._scale_dimension(self._card_max_width - 60, min_value=320)
        
        # Inner Frame (content wrapper) - centered within the padding frame
        # This ensures content is vertically centered, distributing any extra space evenly
        # above and below (handles platform-specific font rendering differences)
        self.inner_frame = ctk.CTkFrame(
            self._card_padding_frame, 
            fg_color=COLORS["surface"],
            width=content_width
        )
        self.inner_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        # Scaled padding values
        title_top_pad = self._scale_padding(10)
        title_bottom_pad = self._scale_padding(8)
        price_bottom_pad = self._scale_padding(12)
        btn_pad = self._scale_padding(6)
        divider_top_pad = self._scale_padding(14)
        divider_bottom_pad = self._scale_padding(8)
        section_pad = self._scale_padding(12)
        
        # 1. Title Section
        ctk.CTkLabel(
            self.inner_frame, 
            text="Activate Session", 
            font=get_ctk_font("heading", self.screen_scale),
            text_color=COLORS["text_primary"],
            fg_color="transparent"
        ).pack(pady=(title_top_pad, title_bottom_pad))
        
        price_text = "AUD 1.99"
        if hasattr(config, 'PRODUCT_PRICE_DISPLAY'):
            price_text = config.PRODUCT_PRICE_DISPLAY.split(" - ")[0] if " - " in config.PRODUCT_PRICE_DISPLAY else config.PRODUCT_PRICE_DISPLAY

        ctk.CTkLabel(
            self.inner_frame, 
            text=f"{price_text} · One-Time Payment", 
            font=get_ctk_font("body", self.screen_scale),
            text_color=COLORS["text_secondary"],
            fg_color="transparent"
        ).pack(pady=(0, price_bottom_pad))
        
        # 2. Primary Action (Purchase)
        btn_width = self._scale_dimension(200, min_value=160)
        btn_height = self._scale_dimension(55, min_value=44)
        self.btn_pay = RoundedButton(
            self.inner_frame, 
            text="Pay via Card", 
            width=btn_width, 
            height=btn_height, 
            bg_color=COLORS["button_bg"], 
            hover_color=COLORS["button_bg_hover"],
            text_color="#FFFFFF", 
            font=get_ctk_font("body_bold", self.screen_scale),
            command=self._on_purchase_click
        )
        self.btn_pay.pack(pady=btn_pad)
        
        # Stripe availability warning
        if not STRIPE_AVAILABLE:
            stripe_warning = ctk.CTkLabel(
                self.inner_frame,
                text="(Stripe SDK not installed)",
                font=get_ctk_font("small", self.screen_scale),
                text_color=COLORS["status_gadget"],
                fg_color="transparent"
            )
            stripe_warning.pack(pady=(0, self._scale_padding(10)))
        elif not self.stripe.is_available():
            stripe_warning = ctk.CTkLabel(
                self.inner_frame,
                text="(Payment not configured)",
                font=get_ctk_font("small", self.screen_scale),
                text_color=COLORS["status_gadget"],
                fg_color="transparent"
            )
            stripe_warning.pack(pady=(0, self._scale_padding(10)))
        
        # 3. Divider (using grid for consistent cross-platform alignment)
        div_frame = ctk.CTkFrame(self.inner_frame, fg_color="transparent")
        div_frame.pack(fill="x", pady=(divider_top_pad, divider_bottom_pad), padx=section_pad)
        
        # Configure grid columns: lines expand equally, OR text stays fixed
        div_frame.grid_columnconfigure(0, weight=1)
        div_frame.grid_columnconfigure(1, weight=0)
        div_frame.grid_columnconfigure(2, weight=1)
        
        # Left line - centered vertically in its cell
        left_line = ctk.CTkFrame(div_frame, fg_color=COLORS["border"], height=1)
        left_line.grid(row=0, column=0, sticky="ew", pady=0)
        
        # OR label - centered by default in grid
        or_label = ctk.CTkLabel(
            div_frame, 
            text="OR", 
            font=get_ctk_font("small", self.screen_scale),
            text_color=COLORS["text_secondary"],
            fg_color="transparent"
        )
        or_label.grid(row=0, column=1, padx=section_pad)
        
        # Right line - centered vertically in its cell
        right_line = ctk.CTkFrame(div_frame, fg_color=COLORS["border"], height=1)
        right_line.grid(row=0, column=2, sticky="ew", pady=0)
        
        # 4. Stripe Session ID Section
        ctk.CTkLabel(
            self.inner_frame, 
            text="(Already paid?) Verify with Stripe session ID", 
            font=get_ctk_font("body", self.screen_scale),
            text_color=COLORS["text_secondary"],
            fg_color="transparent",
            anchor="w"
        ).pack(fill="x", pady=(section_pad, btn_pad), padx=section_pad)
        
        verify_row = ctk.CTkFrame(self.inner_frame, fg_color="transparent")
        verify_row.pack(fill="x", padx=section_pad, pady=(0, self._scale_padding(8)))
        
        # Scaled verify button
        verify_btn_width = self._scale_dimension(100, min_value=80)
        verify_btn_height = self._scale_dimension(44, min_value=36)
        self.verify_button = RoundedButton(
            verify_row, 
            text="Verify", 
            width=verify_btn_width, 
            height=verify_btn_height, 
            radius=12,
            bg_color=COLORS["button_bg"], 
            hover_color=COLORS["button_bg_hover"],
            font=get_ctk_font("button", self.screen_scale),
            command=self._on_verify_payment
        )
        self.verify_button.pack(side="right", anchor="n")
        
        self.session_entry = StyledEntry(verify_row, placeholder="cs_live_...", height=verify_btn_height)
        self.session_entry.pack(side="left", fill="both", expand=True, padx=(0, self._scale_padding(10)))
        self.session_entry.bind_return(self._on_verify_payment)
        self.session_entry.entry.bind("<Key>", self._clear_entry_feedback, add="+")
        
        # Skip for development (only if configured)
        if getattr(config, 'SKIP_LICENSE_CHECK', False):
            skip_font_size = max(8, int(10 * self.screen_scale))
            skip_label = ctk.CTkLabel(
                self.center_container,
                text="[Development Mode - Click to Skip]",
                font=get_ctk_font("small", self.screen_scale),
                text_color=COLORS["text_secondary"],
                fg_color="transparent"
            )
            skip_label.pack(pady=(self._scale_padding(20), 0))
            skip_label.bind("<Button-1>", lambda e: self._skip_for_dev())
    
    def _update_status(self, message: str, is_error: bool = False, is_success: bool = False, persistent: bool = False):
        """
        Update the status message via the session entry's inline display.
        
        Args:
            message: The status message to display.
            is_error: Show as error (red).
            is_success: Show as success (green).
            persistent: If True, message won't be cleared by typing.
        """
        if not self.session_entry:
            return
        
        if is_error:
            self.session_entry.show_error(message)
        elif is_success:
            self.session_entry.show_success(message)
        else:
            self.session_entry.show_info(message, persistent=persistent)
    
    def _start_main_thread_checker(self):
        """
        Start the main-thread payment checker.
        
        This is a safety mechanism for Windows where root.after() calls from
        background threads may not execute reliably. The checker runs in the
        main thread and monitors the payment state flags set by background
        polling.
        
        On macOS this is redundant but harmless - the background thread's
        root.after() calls will typically trigger activation first.
        """
        # Cancel any existing checker
        self._stop_main_thread_checker()
        
        def check_payment_state():
            """Periodic check for payment completion in main thread."""
            # Check if payment is ready (set by background polling)
            session_id = None
            payment_info = None
            should_activate = False
            
            with self._polling_lock:
                # Already activated - stop checking
                if self._payment_detected:
                    logger.debug("Main thread checker: already activated, stopping")
                    return
                
                # Payment ready - proceed with activation
                if self._payment_ready and self._payment_session_id and self._payment_info:
                    logger.info("Main thread checker detected payment - activating")
                    self._payment_detected = True
                    self._payment_ready = False
                    session_id = self._payment_session_id
                    payment_info = self._payment_info
                    self._payment_session_id = None
                    self._payment_info = None
                    should_activate = True
            
            if should_activate:
                # Update status and complete activation
                self._update_status("Payment successful!", is_success=True)
                self.root.after(1500, lambda: self._complete_activation(session_id, payment_info))
                return
            
            # Continue checking if still waiting for payment
            with self._polling_lock:
                still_polling = self._polling_active
            
            if still_polling:
                self._main_checker_id = self.root.after(
                    self._main_checker_interval,
                    check_payment_state
                )
            else:
                logger.debug("Main thread checker: polling stopped, stopping checker")
        
        # Start the checker
        self._main_checker_id = self.root.after(
            self._main_checker_interval,
            check_payment_state
        )
        logger.debug("Started main thread payment checker")
    
    def _stop_main_thread_checker(self):
        """Stop the main-thread payment checker."""
        if self._main_checker_id is not None:
            try:
                self.root.after_cancel(self._main_checker_id)
            except Exception:
                pass
            self._main_checker_id = None
            logger.debug("Stopped main thread payment checker")
    
    def _start_payment_polling(self, session_id: str):
        """Start background polling to check payment status."""
        with self._polling_lock:
            if self._polling_active:
                return
            
            self._polling_active = True
            self._payment_detected = False
        
        # Start main thread checker as Windows safety net
        self._start_main_thread_checker()
        
        def poll_loop():
            """Background polling loop."""
            start_time = time.time()
            
            while True:
                with self._polling_lock:
                    if not self._polling_active or self._payment_ready:
                        break
                
                elapsed = time.time() - start_time
                
                if elapsed >= self._poll_timeout:
                    logger.warning("Payment polling timed out after 10 minutes")
                    with self._polling_lock:
                        self._polling_active = False
                    self.root.after(0, lambda: self._update_status(
                        "Payment check timed out. Click 'Already paid? Verify manually' if you paid.",
                        is_error=True
                    ))
                    break
                
                try:
                    is_paid, info = self.stripe.verify_session(session_id)
                    
                    if is_paid:
                        logger.info("Payment detected via polling - waiting for user to return")
                        with self._polling_lock:
                            self._polling_active = False
                            self._payment_ready = True
                            self._payment_session_id = session_id
                            self._payment_info = info
                        self.root.after(0, lambda: self._update_status(
                            "Payment successful!",
                            is_success=True
                        ))
                        # Schedule auto-activation after delay so user can see success message
                        # This handles case where user already Command-tabbed to app before
                        # verification completed - no need to wait for another focus event
                        self.root.after(1500, self._try_auto_activate)
                        break
                    
                except Exception as e:
                    logger.warning(f"Polling error (will retry): {e}")
                
                for _ in range(int(self._poll_interval * 10)):
                    with self._polling_lock:
                        if not self._polling_active:
                            break
                    time.sleep(0.1)
            
            logger.debug("Payment polling stopped")
        
        self._polling_thread = threading.Thread(target=poll_loop, daemon=True)
        self._polling_thread.start()
        logger.info(f"Started payment polling for session {session_id[:20]}...")
    
    def _stop_payment_polling(self):
        """Stop the background payment polling and wait for thread to finish."""
        with self._polling_lock:
            self._polling_active = False
        
        # Stop main thread checker
        self._stop_main_thread_checker()
        
        if self._polling_thread is not None and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=2.0)
        self._polling_thread = None
        logger.debug("Payment polling stopped")
    
    def _on_redirect_received(self, session_id: str):
        """Handle redirect callback from local server."""
        with self._polling_lock:
            if self._payment_detected or self._payment_ready:
                return
        
        logger.info(f"Redirect received for session {session_id[:20]}...")
        
        def verify_payment():
            is_paid, info = self.stripe.verify_session(session_id)
            if is_paid:
                with self._polling_lock:
                    self._payment_ready = True
                    self._payment_session_id = session_id
                    self._payment_info = info
                logger.info("Payment verified via redirect - waiting for user to return")
                self.root.after(0, lambda: self._update_status(
                    "Payment successful!",
                    is_success=True
                ))
                # Schedule auto-activation after delay so user can see success message
                # This handles case where user already Command-tabbed to app before
                # verification completed - no need to wait for another focus event
                self.root.after(1500, self._try_auto_activate)
            else:
                self.root.after(0, lambda: self._update_status(
                    "Payment verification failed", is_error=True
                ))
        
        threading.Thread(target=verify_payment, daemon=True).start()
    
    def _on_window_focus(self, event):
        """Handle window focus event (user Command-Tabs back to app)."""
        # Don't filter by event.widget - focus can go to any child widget when
        # user returns to app. The _payment_detected flag handles deduplication.
        
        # Atomically check and set state to prevent race conditions
        session_id = None
        payment_info = None
        should_activate = False
        
        with self._polling_lock:
            if self._payment_detected:
                return
            
            if self._payment_ready and self._payment_session_id and self._payment_info:
                logger.info("User returned to app - activating license")
                self._payment_detected = True
                self._payment_ready = False
                session_id = self._payment_session_id
                payment_info = self._payment_info
                self._payment_session_id = None
                self._payment_info = None
                should_activate = True
        
        # Complete activation outside lock to avoid potential deadlocks
        # State has been atomically captured, so this is thread-safe
        if should_activate:
            self._complete_activation(session_id, payment_info)
    
    def _try_auto_activate(self):
        """
        Try to automatically complete activation after payment verification.
        
        Called after showing 'Payment successful!' message, with a delay to
        allow user to see the message. This handles the case where user
        Command-tabs to the app before payment verification completes -
        when verification finishes, the app proceeds automatically without
        requiring another focus event.
        """
        # Atomically check and set state to prevent race conditions
        session_id = None
        payment_info = None
        should_activate = False
        
        with self._polling_lock:
            # Already activated via focus event - nothing to do
            if self._payment_detected:
                return
            
            # Payment not ready yet - shouldn't happen but guard anyway
            if not (self._payment_ready and self._payment_session_id and self._payment_info):
                return
            
            # Proceed with activation
            logger.info("Auto-activating license after payment verification")
            self._payment_detected = True
            self._payment_ready = False
            session_id = self._payment_session_id
            payment_info = self._payment_info
            self._payment_session_id = None
            self._payment_info = None
            should_activate = True
        
        # Complete activation outside lock to avoid potential deadlocks
        if should_activate:
            self._complete_activation(session_id, payment_info)
    
    def _complete_activation(self, session_id: str, info: dict):
        """Complete the license activation process."""
        self._stop_payment_polling()
        if self._local_server:
            self._local_server.stop()
            self._local_server = None
        
        email = info.get("customer_email")
        payment_intent = info.get("payment_intent")
        
        self.license_manager.activate_with_stripe(
            session_id=session_id,
            payment_intent=payment_intent,
            email=email
        )
        
        self._update_status("Session ID verified! Starting app...", is_success=True)
        logger.info("License activated via automatic payment detection")
        
        self.root.after(1500, self._activation_success)
    
    def _on_purchase_click(self):
        """Handle purchase button click."""
        try:
            if not self.stripe.is_available():
                self._update_status("Payment system not configured", is_error=True)
                messagebox.showerror(
                    "Payment Not Available",
                    "The payment system is not configured.\n\n"
                    "Please contact support."
                )
                return
            
            self._update_status("Opening payment page...", persistent=True)
            
            self._local_server = LocalPaymentServer(callback=self._on_redirect_received)
            server_started = self._local_server.start()
            
            if server_started:
                success_url = self._local_server.get_success_url()
                cancel_url = self._local_server.get_cancel_url()
                logger.info(f"Using local redirect server on port {self._local_server.port}")
            else:
                success_url = None
                cancel_url = None
                logger.warning("Local server failed to start, using default URLs")
            
            def open_checkout():
                try:
                    logger.info("Starting Stripe checkout session creation...")
                    session_id, error = self.stripe.open_checkout(
                        success_url=success_url,
                        cancel_url=cancel_url
                    )
                    logger.info(f"Checkout result: session_id={session_id is not None}, error={error}")
                    
                    self.root.after(0, lambda: self._handle_checkout_result(session_id, error))
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logger.error(f"Error in open_checkout thread: {e}")
                    logger.error(f"Full traceback:\n{error_details}")
                    error_msg = f"{type(e).__name__}: {e}"
                    self.root.after(0, lambda: self._handle_checkout_result(None, error_msg))
            
            thread = threading.Thread(target=open_checkout, daemon=True)
            thread.start()
            
        except Exception as e:
            logger.error(f"Error in _on_purchase_click: {e}")
            self._update_status(f"Error: {e}", is_error=True)
    
    def _handle_checkout_result(self, session_id: Optional[str], error: Optional[str]):
        """Handle the result of opening Stripe checkout."""
        if error and not session_id:
            self._update_status(f"Error: {error}", is_error=True)
            if self._local_server:
                self._local_server.stop()
                self._local_server = None
            return
        
        if session_id:
            self._pending_session_id = session_id
            self._waiting_for_payment = True
            
            self._start_payment_polling(session_id)
            
            if error:
                # Check if browser failed to open (contains URL to copy)
                if "Could not open browser" in error and "http" in error:
                    self._show_url_copy_dialog(error)
                else:
                    self._update_status(error, is_error=True)
            else:
                self._update_status("Complete payment in browser.", persistent=True)
    
    def _show_url_copy_dialog(self, error_message: str):
        """
        Show a dialog when browser fails to open, allowing user to copy the URL.
        
        Args:
            error_message: The error message containing the URL.
        """
        # Extract URL from error message
        url_match = re.search(r'(https?://[^\s]+)', error_message)
        checkout_url = url_match.group(1) if url_match else None
        
        if not checkout_url:
            self._update_status("Browser failed to open", is_error=True)
            return
        
        # Create a simple dialog
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Open Payment Link")
        dialog.geometry("500x220")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Set window icon for Windows (each Toplevel needs this explicitly)
        set_windows_toplevel_icon(dialog)
        
        # Center the dialog on parent window
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 220) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Configure dialog appearance
        dialog.configure(fg_color=COLORS["surface"])
        
        # Message
        msg_label = ctk.CTkLabel(
            dialog,
            text="Could not open browser automatically.\nPlease copy this link and paste it in your browser:",
            font=get_ctk_font("body", self.screen_scale),
            text_color=COLORS["text_primary"],
            fg_color="transparent",
            justify="center"
        )
        msg_label.pack(pady=(20, 15))
        
        # URL display (selectable entry)
        url_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg"], corner_radius=8)
        url_frame.pack(fill="x", padx=20, pady=(0, 15))
        
        url_entry = ctk.CTkEntry(
            url_frame,
            font=get_ctk_font("small", self.screen_scale),
            text_color=COLORS["text_primary"],
            fg_color="transparent",
            border_width=0,
            height=36
        )
        url_entry.pack(fill="x", padx=10, pady=8)
        url_entry.insert(0, checkout_url)
        url_entry.configure(state="readonly")
        
        # Button frame
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        def copy_url():
            """Copy URL to clipboard."""
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(checkout_url)
                self.root.update()  # Required for clipboard to work
                copy_btn.configure(text="Copied!")
                dialog.after(1500, lambda: copy_btn.configure(text="Copy Link"))
            except Exception as e:
                logger.warning(f"Failed to copy to clipboard: {e}")
        
        def close_dialog():
            """Close the dialog."""
            dialog.destroy()
            self._update_status("Paste link in browser to pay.", persistent=True)
        
        copy_btn = RoundedButton(
            btn_frame,
            text="Copy Link",
            width=120,
            height=40,
            bg_color=COLORS["button_bg"],
            hover_color=COLORS["button_bg_hover"],
            font=get_ctk_font("button", self.screen_scale),
            command=copy_url
        )
        copy_btn.pack(side="left", expand=True)
        
        close_btn = RoundedButton(
            btn_frame,
            text="Close",
            width=120,
            height=40,
            bg_color=COLORS["border"],
            hover_color=COLORS["text_secondary"],
            font=get_ctk_font("button", self.screen_scale),
            command=close_dialog
        )
        close_btn.pack(side="right", expand=True)
        
        # Update status to inform user
        self._update_status("Copy payment link from dialog.", persistent=True)
    
    def _on_verify_payment(self):
        """Handle verify payment button click."""
        session_id = self.session_entry.get().strip() if self.session_entry else ""
        
        if not session_id:
            self._update_status("Please enter a session ID", is_error=True)
            return
        
        if not self.stripe.is_available():
            self._update_status("Cannot verify - Stripe not configured", is_error=True)
            return
        
        def verify():
            is_paid, info = self.stripe.verify_session(session_id)
            self.root.after(0, lambda: self._handle_verify_result(session_id, is_paid, info))
        
        thread = threading.Thread(target=verify, daemon=True)
        thread.start()
    
    def _handle_verify_result(self, session_id: str, is_paid: bool, info: dict):
        """Handle the result of payment verification."""
        if is_paid:
            email = info.get("customer_email")
            payment_intent = info.get("payment_intent")
            
            self.license_manager.activate_with_stripe(
                session_id=session_id,
                payment_intent=payment_intent,
                email=email
            )
            
            self._update_status("Session ID verified! Starting app...", is_success=True)
            
            self.root.after(1000, self._activation_success)
        else:
            self._update_status("Invalid session ID", is_error=True)
    
    def _activation_success(self):
        """Handle successful license activation."""
        try:
            self.root.unbind("<Activate>")
            self.root.unbind("<FocusIn>")
            self.root.unbind("<Configure>")
        except Exception:
            pass
        
        # Cancel any pending callbacks
        if hasattr(self, '_resize_after_id'):
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass
        
        # Stop main thread checker explicitly (also done in _stop_payment_polling)
        self._stop_main_thread_checker()
        
        self._payment_ready = False
        self._payment_session_id = None
        self._payment_info = None
        
        self._stop_payment_polling()
        if self._local_server:
            self._local_server.stop()
            self._local_server = None
        
        if self.main_frame:
            self.main_frame.destroy()
        
        if self.on_success:
            self.on_success()
    
    def _skip_for_dev(self):
        """Skip license check for development."""
        logger.warning("License check skipped for development")
        self._activation_success()
    
    def destroy(self):
        """Clean up the payment screen."""
        try:
            self.root.unbind("<Activate>")
            self.root.unbind("<FocusIn>")
            self.root.unbind("<Configure>")
        except Exception:
            pass
        
        # Cancel any pending callbacks
        if hasattr(self, '_resize_after_id'):
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass
        
        # Stop main thread checker explicitly (also done in _stop_payment_polling)
        self._stop_main_thread_checker()
        
        self._payment_ready = False
        self._payment_session_id = None
        self._payment_info = None
        
        self._stop_payment_polling()
        
        if self._local_server:
            self._local_server.stop()
            self._local_server = None
        
        if self.main_frame:
            self.main_frame.destroy()
            self.main_frame = None


def check_and_show_payment_screen(
    root: Union[ctk.CTk, "tk.Tk"],
    on_licensed: Callable[[], None]
) -> bool:
    """
    Check license status and show payment screen if needed.
    
    Args:
        root: The root CustomTkinter or Tkinter window.
        on_licensed: Callback when license is valid.
        
    Returns:
        True if license is already valid (no payment screen shown),
        False if payment screen is displayed.
    """
    if getattr(config, 'SKIP_LICENSE_CHECK', False):
        logger.info("License check skipped (SKIP_LICENSE_CHECK=true)")
        return True
    
    license_manager = get_license_manager()
    
    if license_manager.is_licensed():
        logger.info("Valid license found")
        return True
    
    logger.info("No valid license - showing payment screen")
    PaymentScreen(root, on_licensed)
    return False
