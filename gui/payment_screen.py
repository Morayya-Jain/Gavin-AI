"""
Payment Screen for BrainDock.

Displays a payment gate before app access, allowing users to:
- Purchase via Stripe Checkout
- Verify previous payment with session ID
"""

import tkinter as tk
from tkinter import messagebox, font as tkfont
import threading
import logging
import sys
import socket
import time
from pathlib import Path
from typing import Optional, Callable
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from licensing.license_manager import get_license_manager
from licensing.stripe_integration import get_stripe_integration, STRIPE_AVAILABLE
from gui.ui_components import (
    RoundedButton, Card, StyledEntry, COLORS, FONTS,
    ScalingManager, REFERENCE_WIDTH, REFERENCE_HEIGHT, MIN_WIDTH, MIN_HEIGHT
)

logger = logging.getLogger(__name__)

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
    """
    
    # Default port to try first
    DEFAULT_PORT = 5678
    
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
        
        Returns:
            An available port number.
        """
        # Try default port first
        if self._is_port_available(self.DEFAULT_PORT):
            return self.DEFAULT_PORT
        
        # Find a random available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', 0))
            return s.getsockname()[1]
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return True
        except OSError:
            return False
    
    def get_success_url(self) -> str:
        """
        Get the URL to use as Stripe's success_url.
        
        Returns:
            The local success URL with session_id placeholder.
        """
        return f"http://localhost:{self.port}/success"
    
    def get_cancel_url(self) -> str:
        """
        Get the URL to use as Stripe's cancel_url.
        
        Returns:
            The local cancel URL.
        """
        return f"http://localhost:{self.port}/cancel"
    
    def start(self) -> bool:
        """
        Start the local HTTP server in a background thread.
        
        Returns:
            True if server started successfully, False otherwise.
        """
        if self._running:
            return True
        
        try:
            # Create request handler with reference to this server instance
            server_instance = self
            
            class PaymentHandler(BaseHTTPRequestHandler):
                """Handler for payment redirect requests."""
                
                def log_message(self, format, *args):
                    """Suppress default logging."""
                    pass
                
                def do_GET(self):
                    """Handle GET requests."""
                    parsed_path = urlparse(self.path)
                    
                    if parsed_path.path == '/success':
                        # Extract session_id from query params
                        query_params = parse_qs(parsed_path.query)
                        session_id = query_params.get('session_id', [None])[0]
                        
                        # Send success response
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        
                        html = self._get_success_html()
                        self.wfile.write(html.encode('utf-8'))
                        
                        # Notify callback if we got a session_id
                        if session_id and not server_instance._session_received:
                            server_instance._session_received = True
                            logger.info(f"Payment redirect received with session: {session_id[:20]}...")
                            # Call callback in a separate thread to not block response
                            threading.Thread(
                                target=server_instance.callback,
                                args=(session_id,),
                                daemon=True
                            ).start()
                    
                    elif parsed_path.path == '/cancel':
                        # Payment was cancelled
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        
                        html = self._get_cancel_html()
                        self.wfile.write(html.encode('utf-8'))
                    
                    else:
                        # Unknown path
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
        .checkmark {
            font-size: 64px;
            margin-bottom: 20px;
        }
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
            
            # Create and start server
            self.server = HTTPServer(('localhost', self.port), PaymentHandler)
            self.server.timeout = 1  # Allow periodic checks
            self._running = True
            
            def serve():
                """Server loop that can be stopped."""
                while self._running:
                    self.server.handle_request()
            
            self._server_thread = threading.Thread(target=serve, daemon=True)
            self._server_thread.start()
            
            logger.info(f"Local payment server started on port {self.port}")
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
        
        # Wait for server thread to finish (with timeout to avoid deadlock)
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
    
    def __init__(self, root: tk.Tk, on_success: Callable[[], None]):
        """
        Initialize the payment screen.
        
        Args:
            root: The root Tkinter window.
            on_success: Callback to invoke when license is activated.
        """
        self.root = root
        self.on_success = on_success
        self.license_manager = get_license_manager()
        self.stripe = get_stripe_integration()
        
        # Initialize scaling manager for responsive UI
        self.scaling_manager = ScalingManager(self.root)
        
        # Calculate scale factor based on screen dimensions
        self._calculate_scale()
        
        # Create scaled fonts
        self._create_fonts()
        
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
        self._payment_detected = False  # Prevent duplicate activations
        
        # Payment ready state (payment confirmed, waiting for user to return to app)
        self._payment_ready = False
        self._payment_session_id: Optional[str] = None
        self._payment_info: Optional[dict] = None
        
        # Polling configuration
        self._poll_interval = 3  # seconds between polls
        self._poll_timeout = 600  # 10 minutes max polling time
        
        # UI references
        self.main_frame: Optional[tk.Frame] = None
        self.verify_button: Optional[RoundedButton] = None
        self.session_entry: Optional[StyledEntry] = None
        self.logo_image = None  # Keep reference to prevent garbage collection
        self.btn_pay: Optional[RoundedButton] = None
        
        self._setup_ui()
        
        # Bind focus event to detect when user returns to app
        self.root.bind("<FocusIn>", self._on_window_focus)
    
    def _clear_entry_feedback(self, event=None):
        """Clear entry feedback when user types."""
        if self.session_entry:
            self.session_entry.clear_error()
    
    def _calculate_scale(self):
        """
        Calculate the scale factor based on screen dimensions.
        
        Uses a reference of 1920x1080 for scale calculations.
        """
        self.screen_scale = min(
            self.scaling_manager.screen_width / 1920,
            self.scaling_manager.screen_height / 1080,
            1.0
        )
        # Minimum 65% scale for payment screen to ensure readability
        self.screen_scale = max(self.screen_scale, 0.65)
    
    def _create_fonts(self):
        """
        Create scaled fonts for the payment screen UI.
        
        Scales fonts based on the calculated screen_scale factor.
        """
        # Font families
        font_display = "Georgia"
        font_interface = "Helvetica"
        
        # Base font sizes and their bounds (base, min, max)
        font_bounds = {
            "heading": (24, 16, 28),
            "body": (14, 11, 16),
            "body_bold": (14, 11, 16),
            "small": (12, 10, 14),
            "caption": (12, 10, 14),
            "input": (14, 11, 16),
        }
        
        def get_scaled_size(font_key: str) -> int:
            """Get scaled font size within bounds."""
            base_size, min_size, max_size = font_bounds.get(font_key, (14, 11, 16))
            scaled = int(base_size * self.screen_scale)
            return max(min_size, min(scaled, max_size))
        
        # Create font objects
        self.font_heading = tkfont.Font(
            family=font_display, size=get_scaled_size("heading"), weight="bold"
        )
        self.font_body = tkfont.Font(
            family=font_interface, size=get_scaled_size("body"), weight="normal"
        )
        self.font_body_bold = tkfont.Font(
            family=font_interface, size=get_scaled_size("body_bold"), weight="bold"
        )
        self.font_small = tkfont.Font(
            family=font_interface, size=get_scaled_size("small"), weight="normal"
        )
        self.font_caption = tkfont.Font(
            family=font_interface, size=get_scaled_size("caption"), weight="bold"
        )
        self.font_input = tkfont.Font(
            family=font_interface, size=get_scaled_size("input"), weight="normal"
        )
    
    def _scale_dimension(self, base_value: int, min_value: Optional[int] = None) -> int:
        """
        Scale a dimension by the screen scale factor.
        
        Args:
            base_value: The base dimension value.
            min_value: Optional minimum value (won't go below this).
        
        Returns:
            Scaled dimension value.
        """
        scaled = int(base_value * self.screen_scale)
        if min_value is not None:
            return max(scaled, min_value)
        return scaled
    
    def _scale_padding(self, base_padding: int) -> int:
        """
        Scale padding/margin by the screen scale factor.
        
        Args:
            base_padding: The base padding value.
        
        Returns:
            Scaled padding value (minimum 2).
        """
        return max(2, int(base_padding * self.screen_scale))

    def _setup_ui(self):
        """Set up the payment screen UI."""
        
        # Configure root window
        self.root.configure(bg=COLORS["bg"])
        
        # Main container
        self.main_frame = tk.Frame(self.root, bg=COLORS["bg"])
        self.main_frame.pack(fill="both", expand=True)
        
        # Center Container
        self.center_container = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.center_container.place(relx=0.5, rely=0.5, anchor="center")

        # Scaled padding values
        header_bottom_pad = self._scale_padding(38)
        
        # Header (Logo)
        header_frame = tk.Frame(self.center_container, bg=COLORS["bg"])
        header_frame.pack(fill="x", pady=(0, header_bottom_pad))
        
        # Load and display logo (scaled)
        logo_loaded = False
        if PIL_AVAILABLE:
            logo_path = ASSETS_DIR / "logo_with_text.png"
            if logo_path.exists():
                try:
                    img = Image.open(logo_path)
                    
                    # Convert to RGBA if not already
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    
                    # Resize with scaling
                    base_logo_height = 65
                    h = self._scale_dimension(base_logo_height, min_value=45)
                    aspect = img.width / img.height
                    img = img.resize((int(h * aspect), h), Image.Resampling.LANCZOS)
                    self.logo_image = ImageTk.PhotoImage(img)
                    
                    logo_label = tk.Label(
                        header_frame,
                        image=self.logo_image,
                        bg=COLORS["bg"]
                    )
                    logo_label.pack()
                    logo_loaded = True
                except Exception as e:
                    logger.warning(f"Could not load logo: {e}")
        
        # Fallback to text title if logo couldn't be loaded
        if not logo_loaded:
            title_label = tk.Label(
                header_frame,
                text="BrainDock",
                font=self.font_heading,
                fg=COLORS["text_primary"],
                bg=COLORS["bg"]
            )
            title_label.pack()
        
        # Main Card Container - scale based on screen size
        # Card is just a visual background - content should never be clipped
        base_card_width, base_card_height = 550, 380
        self.card_width = self._scale_dimension(base_card_width, min_value=400)
        self.card_height = self._scale_dimension(base_card_height, min_value=300)
        
        self.card_bg = Card(self.center_container, width=self.card_width, height=self.card_height, radius=28, bg_color=COLORS["surface"])
        self.card_bg.pack()
        
        # Inner Frame for widgets (placed on top of the card canvas)
        # NO fixed height - frame sizes to content, card is just decorative background
        inner_padding = self._scale_padding(30)
        self.inner_frame = tk.Frame(self.center_container, bg=COLORS["surface"])
        self.inner_frame.place(in_=self.card_bg, relx=0.5, y=inner_padding, anchor="n", width=self.card_width-inner_padding*2)
        
        # Scaled padding values (reduced for small screen compatibility)
        title_top_pad = self._scale_padding(10)
        title_bottom_pad = self._scale_padding(8)
        price_bottom_pad = self._scale_padding(12)
        btn_pad = self._scale_padding(6)
        divider_top_pad = self._scale_padding(14)
        divider_bottom_pad = self._scale_padding(8)
        section_pad = self._scale_padding(12)
        row_pad = self._scale_padding(12)
        
        # 1. Title Section
        tk.Label(
            self.inner_frame, 
            text="Activate Session", 
            font=self.font_heading, 
            bg=COLORS["surface"], 
            fg=COLORS["text_primary"]
        ).pack(pady=(title_top_pad, title_bottom_pad))
        
        price_text = "AUD 1.99"
        if hasattr(config, 'PRODUCT_PRICE_DISPLAY'):
            price_text = config.PRODUCT_PRICE_DISPLAY.split(" - ")[0] if " - " in config.PRODUCT_PRICE_DISPLAY else config.PRODUCT_PRICE_DISPLAY

        # Price label - unified styling, no hyphen
        tk.Label(
            self.inner_frame, 
            text=f"{price_text} · One-Time Payment", 
            font=self.font_body, 
            bg=COLORS["surface"], 
            fg=COLORS["text_secondary"]
        ).pack(pady=(0, price_bottom_pad))
        
        # 2. Primary Action (Purchase) - scaled button
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
            font_type="body_bold",
            command=self._on_purchase_click
        )
        self.btn_pay.pack(pady=btn_pad)
        
        # Stripe availability warning
        if not STRIPE_AVAILABLE:
            stripe_warning = tk.Label(
                self.inner_frame,
                text="(Stripe SDK not installed)",
                font=self.font_small,
                fg=COLORS["status_gadget"],
                bg=COLORS["surface"]
            )
            stripe_warning.pack(pady=(0, self._scale_padding(10)))
        elif not self.stripe.is_available():
            stripe_warning = tk.Label(
                self.inner_frame,
                text="(Payment not configured)",
                font=self.font_small,
                fg=COLORS["status_gadget"],
                bg=COLORS["surface"]
            )
            stripe_warning.pack(pady=(0, self._scale_padding(10)))
        
        # 3. Divider
        div_frame = tk.Frame(self.inner_frame, bg=COLORS["surface"])
        div_frame.pack(fill="x", pady=(divider_top_pad, divider_bottom_pad), padx=section_pad)
        
        tk.Frame(div_frame, bg=COLORS["border"], height=1).pack(side="left", fill="x", expand=True)
        tk.Label(
            div_frame, 
            text="OR", 
            font=self.font_small, 
            bg=COLORS["surface"], 
            fg=COLORS["text_secondary"], 
            padx=section_pad
        ).pack(side="left")
        tk.Frame(div_frame, bg=COLORS["border"], height=1).pack(side="left", fill="x", expand=True)
        
        # 4. Stripe Session ID Section (always visible)
        tk.Label(
            self.inner_frame, 
            text="(Already paid?) Verify with Stripe session ID", 
            font=self.font_body, 
            bg=COLORS["surface"], 
            fg=COLORS["text_secondary"], 
            anchor="w"
        ).pack(fill="x", pady=(section_pad, btn_pad), padx=section_pad)
        
        verify_row = tk.Frame(self.inner_frame, bg=COLORS["surface"])
        verify_row.pack(fill="x", padx=section_pad)
        
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
            font_type="caption",
            command=self._on_verify_payment
        )
        self.verify_button.pack(side="right", anchor="n")
        
        self.session_entry = StyledEntry(verify_row, placeholder="cs_live_...")
        self.session_entry.canvas.configure(height=verify_btn_height)
        self.session_entry.pack(side="left", fill="x", expand=True, padx=(0, self._scale_padding(10)), anchor="n")
        self.session_entry.bind_return(self._on_verify_payment)
        self.session_entry.entry.bind("<Key>", self._clear_entry_feedback, add="+")
        
        # Skip for development (only if configured)
        if getattr(config, 'SKIP_LICENSE_CHECK', False):
            skip_font_size = max(8, int(10 * self.screen_scale))
            skip_label = tk.Label(
                self.center_container,
                text="[Development Mode - Click to Skip]",
                font=tkfont.Font(size=skip_font_size, underline=True),
                fg=COLORS["text_secondary"],
                bg=COLORS["bg"]
            )
            skip_label.pack(pady=(self._scale_padding(20), 0))
            skip_label.bind("<Button-1>", lambda e: self._skip_for_dev())
    
    def _update_status(self, message: str, is_error: bool = False, is_success: bool = False):
        """
        Update the status message via the session entry's inline display.
        
        Args:
            message: Status message to display.
            is_error: Whether this is an error message (red text + red border).
            is_success: Whether this is a success message (green text + green border).
        """
        if not self.session_entry:
            return
        
        if is_error:
            self.session_entry.show_error(message)
        elif is_success:
            self.session_entry.show_success(message)
        else:
            # Info/status messages: grey text, no border change
            self.session_entry.show_info(message)
    
    def _start_payment_polling(self, session_id: str):
        """
        Start background polling to check payment status.
        
        Polls the Stripe API every few seconds to detect when payment
        is completed. Stops after timeout or when payment is detected.
        
        Args:
            session_id: The Stripe session ID to poll for.
        """
        with self._polling_lock:
            if self._polling_active:
                return  # Already polling
            
            self._polling_active = True
            self._payment_detected = False
        
        def poll_loop():
            """Background polling loop."""
            start_time = time.time()
            
            while True:
                # Thread-safe check of polling state
                with self._polling_lock:
                    if not self._polling_active or self._payment_ready:
                        break
                
                elapsed = time.time() - start_time
                
                # Check timeout
                if elapsed >= self._poll_timeout:
                    logger.warning("Payment polling timed out after 10 minutes")
                    with self._polling_lock:
                        self._polling_active = False
                    # Update UI from main thread
                    self.root.after(0, lambda: self._update_status(
                        "Payment check timed out. Click 'Already paid? Verify manually' if you paid.",
                        is_error=True
                    ))
                    break
                
                # Check payment status
                try:
                    is_paid, info = self.stripe.verify_session(session_id)
                    
                    if is_paid:
                        logger.info("Payment detected via polling - waiting for user to return to app")
                        with self._polling_lock:
                            self._polling_active = False
                            # Store payment info for when user returns to app
                            self._payment_ready = True
                            self._payment_session_id = session_id
                            self._payment_info = info
                        # Update status to confirm payment
                        self.root.after(0, lambda: self._update_status(
                            "Payment successful!",
                            is_success=True
                        ))
                        break
                    
                except Exception as e:
                    logger.warning(f"Polling error (will retry): {e}")
                
                # Wait before next poll (check stop flag periodically)
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
        
        # Wait for polling thread to finish (with timeout to avoid deadlock)
        if self._polling_thread is not None and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=2.0)
        self._polling_thread = None
        logger.debug("Payment polling stopped")
    
    def _on_redirect_received(self, session_id: str):
        """
        Handle redirect callback from local server.
        
        Called when Stripe redirects to our local success page.
        
        Args:
            session_id: The session ID from the redirect.
        """
        with self._polling_lock:
            if self._payment_detected or self._payment_ready:
                return  # Already handled
        
        logger.info(f"Redirect received for session {session_id[:20]}...")
        
        # Verify payment and mark as ready (activation happens when user returns)
        def verify_payment():
            is_paid, info = self.stripe.verify_session(session_id)
            if is_paid:
                with self._polling_lock:
                    self._payment_ready = True
                    self._payment_session_id = session_id
                    self._payment_info = info
                logger.info("Payment verified via redirect")
                self.root.after(0, lambda: self._update_status(
                    "Payment successful!",
                    is_success=True
                ))
            else:
                self.root.after(0, lambda: self._update_status(
                    "Payment verification failed", is_error=True
                ))
        
        threading.Thread(target=verify_payment, daemon=True).start()
    
    def _on_window_focus(self, event):
        """
        Handle window focus event (user Command-Tabs back to app).
        
        If payment has been confirmed, this triggers the activation.
        
        Args:
            event: The focus event.
        """
        # Only process focus on the main window, not child widgets
        if event.widget != self.root:
            return
        
        # Check if payment is ready and waiting for activation (thread-safe)
        # We atomically check ready flag AND payment_detected to prevent races
        with self._polling_lock:
            # Double-check: skip if already detected/activated by another path
            if self._payment_detected:
                return
            
            if self._payment_ready and self._payment_session_id and self._payment_info:
                logger.info("User returned to app - activating license")
                # Set payment_detected HERE while holding lock to prevent races
                # This ensures only one code path can proceed to activation
                self._payment_detected = True
                self._payment_ready = False
                session_id = self._payment_session_id
                payment_info = self._payment_info
                # Clear stored payment info since we're activating
                self._payment_session_id = None
                self._payment_info = None
            else:
                return  # No payment ready
        
        # Trigger activation (outside lock to avoid holding it too long)
        self._complete_activation(session_id, payment_info)
    
    def _complete_activation(self, session_id: str, info: dict):
        """
        Complete the license activation process.
        
        This method assumes the caller has already set _payment_detected = True
        (either via lock or atomically). It handles cleanup and license activation.
        
        Args:
            session_id: The session ID that was paid.
            info: Payment information from Stripe.
        """
        # Stop polling and local server
        self._stop_payment_polling()
        if self._local_server:
            self._local_server.stop()
            self._local_server = None
        
        # Activate license
        email = info.get("customer_email")
        payment_intent = info.get("payment_intent")
        
        self.license_manager.activate_with_stripe(
            session_id=session_id,
            payment_intent=payment_intent,
            email=email
        )
        
        # Include "session id" in message to route to input field
        self._update_status("Session ID verified! Starting app...", is_success=True)
        logger.info("License activated via automatic payment detection")
        
        # Delay slightly to show success message, then enter app
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
            
            self._update_status("Opening payment page...")
            
            # Start local server for redirect handling
            self._local_server = LocalPaymentServer(callback=self._on_redirect_received)
            server_started = self._local_server.start()
            
            # Get URLs for Stripe (use local server if started, otherwise fallback)
            if server_started:
                success_url = self._local_server.get_success_url()
                cancel_url = self._local_server.get_cancel_url()
                logger.info(f"Using local redirect server on port {self._local_server.port}")
            else:
                # Fallback to generic URLs if server failed
                success_url = None
                cancel_url = None
                logger.warning("Local server failed to start, using default URLs")
            
            # Open Stripe checkout in background thread
            def open_checkout():
                try:
                    logger.info("Starting Stripe checkout session creation...")
                    session_id, error = self.stripe.open_checkout(
                        success_url=success_url,
                        cancel_url=cancel_url
                    )
                    logger.info(f"Checkout result: session_id={session_id is not None}, error={error}")
                    
                    # Update UI from main thread
                    self.root.after(0, lambda: self._handle_checkout_result(session_id, error))
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logger.error(f"Error in open_checkout thread: {e}")
                    logger.error(f"Full traceback:\n{error_details}")
                    # Include traceback info in error message for debugging
                    error_msg = f"{type(e).__name__}: {e}"
                    self.root.after(0, lambda: self._handle_checkout_result(None, error_msg))
            
            thread = threading.Thread(target=open_checkout, daemon=True)
            thread.start()
            
        except Exception as e:
            logger.error(f"Error in _on_purchase_click: {e}")
            self._update_status(f"Error: {e}", is_error=True)
    
    def _handle_checkout_result(self, session_id: Optional[str], error: Optional[str]):
        """
        Handle the result of opening Stripe checkout.
        
        Args:
            session_id: The checkout session ID if successful.
            error: Error message if failed.
        """
        if error and not session_id:
            self._update_status(f"Error: {error}", is_error=True)
            # Stop local server if it was started
            if self._local_server:
                self._local_server.stop()
                self._local_server = None
            return
        
        if session_id:
            self._pending_session_id = session_id
            self._waiting_for_payment = True
            
            # Start background polling for payment detection
            self._start_payment_polling(session_id)
            
            if error:
                # Browser failed but we have session ID
                self._update_status(error, is_error=True)
            else:
                # Normal flow - show waiting message
                self._update_status("Complete payment in browser.")
    
    def _on_verify_payment(self):
        """Handle verify payment button click."""
        session_id = self.session_entry.get().strip() if self.session_entry else ""
        
        if not session_id:
            self._update_status("Please enter a session ID", is_error=True)
            return
        
        if not self.stripe.is_available():
            self._update_status("Cannot verify - Stripe not configured", is_error=True)
            return
        
        # Verify in background thread
        def verify():
            is_paid, info = self.stripe.verify_session(session_id)
            self.root.after(0, lambda: self._handle_verify_result(session_id, is_paid, info))
        
        thread = threading.Thread(target=verify, daemon=True)
        thread.start()
    
    def _handle_verify_result(self, session_id: str, is_paid: bool, info: dict):
        """
        Handle the result of payment verification.
        
        Args:
            session_id: The session ID that was verified.
            is_paid: Whether payment was successful.
            info: Additional session information.
        """
        if is_paid:
            # Activate license
            email = info.get("customer_email")
            payment_intent = info.get("payment_intent")
            
            self.license_manager.activate_with_stripe(
                session_id=session_id,
                payment_intent=payment_intent,
                email=email
            )
            
            # Include "session id" in message to route to input field
            self._update_status("Session ID verified! Starting app...", is_success=True)
            
            # Delay slightly to show success message
            self.root.after(1000, self._activation_success)
        else:
            error = info.get("error", "Payment not completed")
            # Include "session id" in message to route to input field
            self._update_status("Invalid session ID", is_error=True)
    
    def _activation_success(self):
        """Handle successful license activation."""
        # Unbind focus event
        try:
            self.root.unbind("<FocusIn>")
        except Exception:
            pass
        
        # Clear payment state
        self._payment_ready = False
        self._payment_session_id = None
        self._payment_info = None
        
        # Stop any active polling/server
        self._stop_payment_polling()
        if self._local_server:
            self._local_server.stop()
            self._local_server = None
        
        # Destroy payment screen
        if self.main_frame:
            self.main_frame.destroy()
        
        # Call success callback
        if self.on_success:
            self.on_success()
    
    def _skip_for_dev(self):
        """Skip license check for development."""
        logger.warning("License check skipped for development")
        self._activation_success()
    
    def destroy(self):
        """Clean up the payment screen."""
        # Unbind focus event
        try:
            self.root.unbind("<FocusIn>")
        except Exception:
            pass
        
        # Clear payment state
        self._payment_ready = False
        self._payment_session_id = None
        self._payment_info = None
        
        # Stop payment polling
        self._stop_payment_polling()
        
        # Stop local server
        if self._local_server:
            self._local_server.stop()
            self._local_server = None
        
        # Destroy UI
        if self.main_frame:
            self.main_frame.destroy()
            self.main_frame = None


def check_and_show_payment_screen(
    root: tk.Tk,
    on_licensed: Callable[[], None]
) -> bool:
    """
    Check license status and show payment screen if needed.
    
    Args:
        root: The root Tkinter window.
        on_licensed: Callback when license is valid (either existing or newly activated).
        
    Returns:
        True if license is already valid (no payment screen shown),
        False if payment screen is displayed.
    """
    # Check for dev skip flag
    if getattr(config, 'SKIP_LICENSE_CHECK', False):
        logger.info("License check skipped (SKIP_LICENSE_CHECK=true)")
        return True
    
    # Check existing license
    license_manager = get_license_manager()
    
    if license_manager.is_licensed():
        logger.info("Valid license found")
        return True
    
    # Show payment screen
    logger.info("No valid license - showing payment screen")
    PaymentScreen(root, on_licensed)
    return False
