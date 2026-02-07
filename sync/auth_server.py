"""
Local HTTP callback server for browser-based authentication.

Works like Cursor / VS Code OAuth: starts a temporary localhost
server, opens the browser to the BrainDock website login page,
and captures auth tokens when the website redirects back.

Flow:
1. Start http.server on localhost:<random_port>
2. Open browser to <website>/auth/desktop?port=<port>
3. User logs in on website
4. Website redirects to http://localhost:<port>/auth/callback?access_token=...
5. Server captures tokens and returns success HTML
6. Server shuts down

Works identically on macOS and Windows.
"""

import json
import logging
import socket
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# Timeout for waiting for the callback (seconds)
_AUTH_TIMEOUT = 300  # 5 minutes


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Module-level storage for the auth result (shared between handler and caller)
_auth_result: Dict = {}
_auth_received = threading.Event()

# Success page shown in the browser after login
_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>BrainDock — Logged In</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; justify-content: center; align-items: center;
            height: 100vh; margin: 0;
            background: #0f172a; color: #e2e8f0;
        }
        .card {
            text-align: center; padding: 3rem;
            background: #1e293b; border-radius: 16px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.3);
            max-width: 400px;
        }
        h1 { color: #22d3ee; margin-bottom: 0.5rem; }
        p { color: #94a3b8; line-height: 1.6; }
    </style>
</head>
<body>
    <div class="card">
        <h1>You're logged in!</h1>
        <p>You can close this tab and return to BrainDock.</p>
    </div>
</body>
</html>"""


class _AuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler that captures auth callback tokens."""

    def do_GET(self) -> None:
        """Handle GET request from the website redirect."""
        global _auth_result

        parsed = urlparse(self.path)

        if parsed.path == "/auth/callback":
            params = parse_qs(parsed.query)

            access_token = params.get("access_token", [None])[0]
            refresh_token = params.get("refresh_token", [None])[0]
            email = params.get("email", [None])[0]

            if access_token and refresh_token:
                _auth_result = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "email": email or "",
                }
                logger.info(f"Auth callback received for: {email or 'unknown'}")

                # Send success response
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_SUCCESS_HTML.encode("utf-8"))
            else:
                _auth_result = {}
                logger.warning("Auth callback missing tokens")
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Missing auth tokens. Please try logging in again.")

            # Signal that we received the callback
            _auth_received.set()

        elif parsed.path == "/health":
            # Health check endpoint
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args) -> None:
        """Suppress default HTTP log messages (use our logger instead)."""
        logger.debug(f"Auth server: {format % args}")


def run_auth_callback_server(website_url: str = "https://thebraindock.com") -> Optional[Dict]:
    """
    Run the local auth callback server and open the browser.

    Blocks until the callback is received or timeout is reached.

    Args:
        website_url: Base URL of the BrainDock website.

    Returns:
        Dict with access_token, refresh_token, email on success.
        None on timeout or failure.
    """
    global _auth_result, _auth_received

    # Reset state
    _auth_result = {}
    _auth_received.clear()

    port = _find_free_port()
    server = HTTPServer(("127.0.0.1", port), _AuthCallbackHandler)
    server.timeout = 1  # Check for shutdown every second

    logger.info(f"Auth callback server started on port {port}")

    # Run server in background thread
    def _serve() -> None:
        while not _auth_received.is_set():
            server.handle_request()

    server_thread = threading.Thread(target=_serve, daemon=True)
    server_thread.start()

    # Open browser to the website login page
    login_url = f"{website_url.rstrip('/')}/auth/desktop?port={port}"
    logger.info(f"Opening browser for login: {login_url}")
    webbrowser.open(login_url)

    # Wait for callback with timeout
    received = _auth_received.wait(timeout=_AUTH_TIMEOUT)

    # Shutdown server
    try:
        server.shutdown()
    except Exception:
        pass

    if received and _auth_result.get("access_token"):
        logger.info("Browser login completed successfully")
        return dict(_auth_result)
    else:
        logger.warning("Browser login timed out or failed")
        return None
