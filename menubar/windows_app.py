"""
BrainDock Windows system tray application using pystray.

Provides a Windows tray icon with session controls, mode toggle,
dashboard link, report download, and auth.
"""

import os
import sys
import time
import webbrowser
import logging
import threading
from pathlib import Path
from typing import Optional

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
    # Create a simple fallback icon (16x16 teal square)
    img = Image.new("RGBA", (16, 16), (34, 211, 238, 255))
    return img


class BrainDockTray:
    """Windows system tray application for BrainDock."""

    def __init__(self) -> None:
        """Initialise the tray app, engine, and sync client."""
        # Core engine
        self.engine = SessionEngine()
        self.engine.on_status_change = self._on_status_change
        self.engine.on_session_ended = self._on_session_ended
        self.engine.on_error = self._on_error
        self.engine.on_alert = self._on_alert

        # Sync client
        self.sync = BrainDockSync()

        # Status text (updated by callbacks)
        self._status_text: str = "Ready to start"

        # Load icon
        self._icon_image = _load_icon_image()

        # Build tray icon
        self.icon = pystray.Icon(
            name="BrainDock",
            icon=self._icon_image,
            title="BrainDock — Ready",
            menu=self._build_menu(),
        )

        # Timer thread for updating tooltip during sessions
        self._timer_running: bool = True
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)

        # Pre-warm camera
        self.engine.prewarm_camera()

        # Apply cloud settings
        self._apply_cloud_settings()

    # ------------------------------------------------------------------
    # Menu construction (rebuilt dynamically via lambdas)
    # ------------------------------------------------------------------

    def _build_menu(self) -> pystray.Menu:
        """Build the tray context menu."""
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
                    "Camera",
                    self._set_mode_camera,
                    checked=lambda item: self.engine.monitoring_mode == config.MODE_CAMERA_ONLY,
                ),
                pystray.MenuItem(
                    "Screen",
                    self._set_mode_screen,
                    checked=lambda item: self.engine.monitoring_mode == config.MODE_SCREEN_ONLY,
                ),
                pystray.MenuItem(
                    "Both",
                    self._set_mode_both,
                    checked=lambda item: self.engine.monitoring_mode == config.MODE_BOTH,
                ),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Dashboard", self._open_dashboard),
            pystray.MenuItem("Download Last Report", self._download_report),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: self.sync.get_stored_email() or "Not logged in",
                None, enabled=False,
            ),
            pystray.MenuItem(
                "Log Out" if self.sync.is_authenticated() else "Log In",
                self._toggle_auth,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit BrainDock", self._quit_app),
        )

    # ------------------------------------------------------------------
    # Timer loop (background thread)
    # ------------------------------------------------------------------

    def _timer_loop(self) -> None:
        """Background thread to update tray tooltip with session timer."""
        while self._timer_running:
            if self.engine.is_running:
                status = self.engine.get_status()
                elapsed = status.get("elapsed_seconds", 0)
                h = elapsed // 3600
                m = (elapsed % 3600) // 60
                s = elapsed % 60
                self.icon.title = f"BrainDock — {h:02d}:{m:02d}:{s:02d}"
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

            # Upload session data
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
        url = getattr(config, "DASHBOARD_URL", "https://braindock.com/dashboard")
        webbrowser.open(url)

    def _download_report(self, icon, item) -> None:
        """Open the most recently generated PDF report."""
        report_path = self.engine.get_last_report_path()
        if report_path and report_path.exists():
            os.startfile(str(report_path))
            logger.info(f"Opened report: {report_path}")
        else:
            self.icon.notify("No recent report found. Complete a session first.", "BrainDock")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _toggle_auth(self, icon, item) -> None:
        """Log in or out depending on current state."""
        if self.sync.is_authenticated():
            self.sync.logout()
            self.icon.notify("Logged out successfully.", "BrainDock")
        else:
            self._login()

    def _login(self) -> None:
        """Start browser-based login flow."""
        url = getattr(config, "DASHBOARD_URL", "https://braindock.com")
        success = self.sync.login_with_browser(dashboard_url=url)
        if success:
            self.icon.notify("You're now logged in!", "BrainDock")
        else:
            self.icon.notify("Login failed. Please try again.", "BrainDock Error")

    # ------------------------------------------------------------------
    # Cloud settings
    # ------------------------------------------------------------------

    def _apply_cloud_settings(self) -> None:
        """Fetch settings from cloud and apply to engine."""
        if not self.sync.is_available():
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
        self.icon.notify(message, f"BrainDock Error")

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
        self._timer_thread.start()
        self.icon.run()
