"""
BrainDock Windows system tray application using pystray.

Provides a Windows tray icon with session controls, mode toggle,
dashboard link, report download, and auth.

Auth-gated: if no user is logged in, only Log In / Sign Up / Quit
are shown. All session features require an authenticated account.
"""

import os
import sys
import time
import webbrowser
import logging
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import pystray
from PIL import Image

import config
from core.engine import SessionEngine
from sync.supabase_client import BrainDockSync

logger = logging.getLogger(__name__)

# Resolve icon path
_ASSETS_DIR = config.BASE_DIR / "assets"
_ICON_PATH = _ASSETS_DIR / "tray_icon.ico"
_FALLBACK_PNG = _ASSETS_DIR / "logo_icon.png"


def _load_icon_image() -> Image.Image:
    """Load the tray icon image."""
    if _ICON_PATH.exists():
        return Image.open(str(_ICON_PATH))
    if _FALLBACK_PNG.exists():
        return Image.open(str(_FALLBACK_PNG))
    # Simple fallback icon (16x16 teal square)
    return Image.new("RGBA", (16, 16), (34, 211, 238, 255))


class BrainDockTray:
    """Windows system tray application for BrainDock."""

    def __init__(self) -> None:
        """Initialise the tray app, engine, and sync client."""
        # Core engine (created but not used until authenticated)
        self.engine = SessionEngine()
        self.engine.on_status_change = self._on_status_change
        self.engine.on_session_ended = self._on_session_ended
        self.engine.on_error = self._on_error
        self.engine.on_alert = self._on_alert

        # Sync client
        self.sync = BrainDockSync()

        # Status text
        self._status_text: str = "Ready to start"

        # Load icon
        self._icon_image = _load_icon_image()

        # Build tray icon
        self.icon = pystray.Icon(
            name="BrainDock",
            icon=self._icon_image,
            title="BrainDock",
            menu=self._build_menu(),
        )

        # Timer thread for updating tooltip during sessions and checking pending deep link
        self._timer_running: bool = True
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)

        # Pending deep link file (when another instance received braindock:// and handed off)
        self._pending_deeplink_file: Path = config.USER_DATA_DIR / "pending_deeplink.txt"

    # ------------------------------------------------------------------
    # Menu building (auth-gated)
    # ------------------------------------------------------------------

    def _is_logged_in(self) -> bool:
        """Check if user has a stored auth session."""
        return bool(self.sync.get_stored_email())

    def _build_menu(self) -> pystray.Menu:
        """Build the tray menu. Only shows session features if logged in."""
        if self._is_logged_in():
            return self._build_authenticated_menu()
        return self._build_unauthenticated_menu()

    def _build_unauthenticated_menu(self) -> pystray.Menu:
        """Menu for users who haven't logged in yet."""
        return pystray.Menu(
            pystray.MenuItem("BrainDock", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Log In", self._login),
            pystray.MenuItem("Sign Up", self._signup),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit BrainDock", self._quit_app),
        )

    def _build_authenticated_menu(self) -> pystray.Menu:
        """Full menu for logged-in users."""
        return pystray.Menu(
            # Status (non-clickable)
            pystray.MenuItem(
                lambda item: self._status_text,
                None, enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            # Start / Stop
            pystray.MenuItem(
                lambda item: "Stop Session" if self.engine.is_running else "Start Session",
                self._toggle_session,
            ),
            # Pause / Resume (visible only during session)
            pystray.MenuItem(
                lambda item: "Resume" if self.engine.is_paused else "Pause",
                self._toggle_pause,
                visible=lambda item: self.engine.is_running,
            ),
            pystray.Menu.SEPARATOR,
            # Mode submenu
            pystray.MenuItem("Mode", pystray.Menu(
                pystray.MenuItem(
                    "Camera", self._set_mode_camera,
                    checked=lambda item: self.engine.monitoring_mode == config.MODE_CAMERA_ONLY,
                ),
                pystray.MenuItem(
                    "Screen", self._set_mode_screen,
                    checked=lambda item: self.engine.monitoring_mode == config.MODE_SCREEN_ONLY,
                ),
                pystray.MenuItem(
                    "Both", self._set_mode_both,
                    checked=lambda item: self.engine.monitoring_mode == config.MODE_BOTH,
                ),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Dashboard", self._open_dashboard),
            pystray.MenuItem("Download Last Report", self._download_report),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: self.sync.get_stored_email() or "Account",
                None, enabled=False,
            ),
            pystray.MenuItem("Log Out", self._logout),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit BrainDock", self._quit_app),
        )

    def _rebuild_menu(self) -> None:
        """Rebuild the tray menu (after login/logout)."""
        self.icon.menu = self._build_menu()

    def _code_from_braindock_url(self, url_string: str) -> Optional[str]:
        """Parse braindock://callback?code=XXX and return the code, or None."""
        if not url_string or not url_string.strip().startswith("braindock://"):
            return None
        parsed = urlparse(url_string.strip())
        qs = parse_qs(parsed.query)
        codes = qs.get("code")
        return codes[0].strip() if codes and codes[0].strip() else None

    def _process_braindock_url(self, url_string: str) -> bool:
        """Exchange code from braindock:// URL and rebuild menu. Returns True if login succeeded."""
        code = self._code_from_braindock_url(url_string)
        if not code:
            return False
        result = self.sync.exchange_linking_code(code)
        if not result.get("success"):
            logger.warning("Exchange linking code failed: %s", result.get("error"))
            return False
        self._rebuild_menu()
        self._apply_cloud_settings()
        self.engine.prewarm_camera()
        self.icon.notify("You're now logged in!", "BrainDock")
        return True

    def _process_pending_deeplink(self) -> None:
        """If a pending deep link file exists (from second instance), process it and delete file."""
        if not self._pending_deeplink_file.exists():
            return
        try:
            url_string = self._pending_deeplink_file.read_text().strip()
            self._pending_deeplink_file.unlink()
            if self._process_braindock_url(url_string):
                logger.info("Processed pending deep link login")
            else:
                self.icon.notify("Login failed. Please try again.", "BrainDock Error")
        except Exception as e:
            logger.warning("Failed to process pending deep link: %s", e)
            try:
                self._pending_deeplink_file.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Timer loop (background thread)
    # ------------------------------------------------------------------

    def _timer_loop(self) -> None:
        """Background thread: update tray tooltip; check for pending deep link."""
        while self._timer_running:
            if self.engine.is_running:
                status = self.engine.get_status()
                elapsed = status.get("elapsed_seconds", 0)
                h = elapsed // 3600
                m = (elapsed % 3600) // 60
                s = elapsed % 60
                self.icon.title = f"BrainDock — {h:02d}:{m:02d}:{s:02d}"
            self._process_pending_deeplink()
            time.sleep(1)

    # ------------------------------------------------------------------
    # Session controls
    # ------------------------------------------------------------------

    def _toggle_session(self, icon, item) -> None:
        """Start or stop a session."""
        if not self.engine.is_running:
            self._apply_cloud_settings()

            result = self.engine.start_session()
            if not result["success"]:
                self.icon.notify(
                    result.get("error", "Failed to start session"),
                    "BrainDock Error",
                )
        else:
            result = self.engine.stop_session()
            if result.get("session_data") and self.sync.is_available():
                self.sync.upload_session(result["session_data"])

    def _toggle_pause(self, icon, item) -> None:
        """Pause or resume session."""
        if self.engine.is_paused:
            self.engine.resume_session()
        else:
            self.engine.pause_session()

    # ------------------------------------------------------------------
    # Mode selection
    # ------------------------------------------------------------------

    def _set_mode_camera(self, icon, item) -> None:
        """Switch to camera-only mode."""
        self.engine.set_monitoring_mode(config.MODE_CAMERA_ONLY)

    def _set_mode_screen(self, icon, item) -> None:
        """Switch to screen-only mode."""
        self.engine.set_monitoring_mode(config.MODE_SCREEN_ONLY)

    def _set_mode_both(self, icon, item) -> None:
        """Switch to both mode."""
        self.engine.set_monitoring_mode(config.MODE_BOTH)

    # ------------------------------------------------------------------
    # Utility items
    # ------------------------------------------------------------------

    def _open_dashboard(self, icon, item) -> None:
        """Open web dashboard in browser."""
        url = getattr(config, "DASHBOARD_URL", "https://thebraindock.com/dashboard")
        webbrowser.open(url)

    def _download_report(self, icon, item) -> None:
        """Open the most recently generated PDF report."""
        report_path = self.engine.get_last_report_path()
        if report_path and report_path.exists():
            os.startfile(str(report_path))
        else:
            self.icon.notify("No recent report found. Complete a session first.", "BrainDock")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _login(self, icon, item) -> None:
        """Start browser-based login flow (deep link when bundled, localhost callback in dev)."""
        url = getattr(config, "DASHBOARD_URL", "https://thebraindock.com")
        base = url.rstrip("/")
        if config.is_bundled():
            # Bundled app: open site; website redirects to braindock://callback?code=...
            webbrowser.open(f"{base}/auth/login/?source=desktop")
            self.icon.notify("Complete login in the browser; the app will update when done.", "BrainDock")
            return
        # Development: localhost callback server
        success = self.sync.login_with_browser(dashboard_url=url)
        if success:
            self._rebuild_menu()
            self._apply_cloud_settings()
            self.engine.prewarm_camera()
            self.icon.notify("You're now logged in!", "BrainDock")
        else:
            self.icon.notify("Login failed. Please try again.", "BrainDock Error")

    def _signup(self, icon, item) -> None:
        """Open signup page in browser."""
        url = getattr(config, "DASHBOARD_URL", "https://thebraindock.com")
        webbrowser.open(f"{url.rstrip('/')}/auth/signup/")

    def _logout(self, icon, item) -> None:
        """Log out and clear stored tokens."""
        if self.engine.is_running:
            self.engine.stop_session()
        self.sync.logout()
        self._rebuild_menu()
        self.icon.title = "BrainDock"
        logger.info("User logged out")

    # ------------------------------------------------------------------
    # Cloud settings (only called when authenticated)
    # ------------------------------------------------------------------

    def _apply_cloud_settings(self) -> None:
        """Fetch settings from cloud and apply to engine."""
        if not self.sync.is_available() or not self._is_logged_in():
            return
        try:
            settings = self.sync.fetch_settings()
            mode = settings.get("monitoring_mode", self.engine.monitoring_mode)
            self.engine.set_monitoring_mode(mode)

            blocklist = BrainDockSync.cloud_settings_to_blocklist(settings)
            self.engine.set_blocklist(blocklist)
            logger.info("Cloud settings applied")
        except Exception as e:
            logger.warning(f"Could not apply cloud settings: {e}")

    # ------------------------------------------------------------------
    # Engine callbacks
    # ------------------------------------------------------------------

    def _on_status_change(self, status: str, text: str) -> None:
        """Update status text and tooltip."""
        self._status_text = text
        if not self.engine.is_running:
            self.icon.title = "BrainDock — Ready"

    def _on_session_ended(self, report_path: Optional[Path]) -> None:
        """Handle session end notification."""
        self._status_text = "Ready to start"
        self.icon.title = "BrainDock — Ready"
        if report_path:
            self.icon.notify(f"Report saved: {report_path.name}", "Session Complete")

    def _on_error(self, error_type: str, message: str) -> None:
        """Show error notification."""
        self.icon.notify(message, "BrainDock Error")

    def _on_alert(self, level: int, message: str) -> None:
        """Show unfocused alert notification."""
        self.icon.notify(message, "BrainDock — Focus Reminder")

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def _quit_app(self, icon, item) -> None:
        """Clean up and quit."""
        self._timer_running = False
        if self.engine.is_running:
            result = self.engine.stop_session()
            if result.get("session_data") and self.sync.is_available():
                self.sync.upload_session(result["session_data"])
        self.engine.cleanup()
        self.icon.stop()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the tray application."""
        # Process braindock:// from argv (e.g. app launched by clicking auth callback link)
        for arg in sys.argv[1:]:
            if arg.strip().startswith("braindock://"):
                self._process_braindock_url(arg)
                break
        self._timer_thread.start()
        self.icon.run()
