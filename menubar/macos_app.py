"""
BrainDock macOS menu bar application using rumps.

Provides a native macOS menu bar icon with session controls,
mode toggle, dashboard link, report download, and auth.

Auth-gated: if no user is logged in, only Log In / Sign Up / Quit
are shown. All session features require an authenticated account.
"""

import sys
import os
import webbrowser
import logging
from pathlib import Path
from typing import Optional

import rumps

import config
from core.engine import SessionEngine
from sync.supabase_client import BrainDockSync

logger = logging.getLogger(__name__)

# Resolve icon path
_ASSETS_DIR = config.BASE_DIR / "assets"
_ICON_PATH = _ASSETS_DIR / "menu_icon.png"
_FALLBACK_ICON = _ASSETS_DIR / "logo_icon.png"


def _get_icon_path() -> Optional[str]:
    """Get the menu bar icon path, or None to use text title."""
    if _ICON_PATH.exists():
        return str(_ICON_PATH)
    if _FALLBACK_ICON.exists():
        return str(_FALLBACK_ICON)
    return None


class BrainDockMenuBar(rumps.App):
    """macOS menu bar application for BrainDock."""

    def __init__(self) -> None:
        """Initialise the menu bar app, engine, and sync client."""
        icon_path = _get_icon_path()
        super().__init__(
            name="BrainDock",
            icon=icon_path,
            template=True,
            quit_button=None,
        )

        # Core engine (created but not used until authenticated)
        self.engine = SessionEngine()
        self.engine.on_status_change = self._on_status_change
        self.engine.on_session_ended = self._on_session_ended
        self.engine.on_error = self._on_error
        self.engine.on_alert = self._on_alert

        # Sync client
        self.sync = BrainDockSync()

        # --- Create all menu items (reused across rebuilds) ---

        # Status display (non-clickable)
        self.status_item = rumps.MenuItem("Ready to start")
        self.status_item.set_callback(None)

        # Timer display (non-clickable)
        self.timer_item = rumps.MenuItem("")
        self.timer_item.set_callback(None)

        # Session controls
        self.start_stop_item = rumps.MenuItem(
            "Start Session", callback=self._toggle_session
        )
        self.pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self.pause_item.set_callback(None)

        # Mode selection submenu
        self.mode_camera = rumps.MenuItem("Camera", callback=self._set_mode_camera)
        self.mode_screen = rumps.MenuItem("Screen", callback=self._set_mode_screen)
        self.mode_both = rumps.MenuItem("Both", callback=self._set_mode_both)
        self.mode_camera.state = 1
        self.mode_menu = rumps.MenuItem("Mode")
        self.mode_menu.update([self.mode_camera, self.mode_screen, self.mode_both])

        # Utility items
        self.dashboard_item = rumps.MenuItem("Open Dashboard", callback=self._open_dashboard)
        self.report_item = rumps.MenuItem("Download Last Report", callback=self._download_report)

        # Account items
        self.account_item = rumps.MenuItem("")
        self.account_item.set_callback(None)
        self.login_item = rumps.MenuItem("Log In", callback=self._login)
        self.signup_item = rumps.MenuItem("Sign Up", callback=self._signup)
        self.logout_item = rumps.MenuItem("Log Out", callback=self._logout)
        self.quit_item = rumps.MenuItem("Quit BrainDock", callback=self._quit_app)

        # Build the menu based on auth state
        self._build_menu()

    # ------------------------------------------------------------------
    # Menu building (auth-gated)
    # ------------------------------------------------------------------

    def _is_logged_in(self) -> bool:
        """Check if user has a stored auth session."""
        return bool(self.sync.get_stored_email())

    def _build_menu(self) -> None:
        """Build the menu. Only shows session features if logged in."""
        self.menu.clear()

        if self._is_logged_in():
            self._build_authenticated_menu()
        else:
            self._build_unauthenticated_menu()

    def _build_unauthenticated_menu(self) -> None:
        """Menu for users who haven't logged in yet."""
        self.menu.add(rumps.MenuItem("BrainDock", callback=None))
        self.menu.add(rumps.separator)
        self.menu.add(self.login_item)
        self.menu.add(self.signup_item)
        self.menu.add(rumps.separator)
        self.menu.add(self.quit_item)

    def _build_authenticated_menu(self) -> None:
        """Full menu for logged-in users."""
        email = self.sync.get_stored_email()
        self.account_item.title = email

        self.menu.add(self.status_item)
        self.menu.add(self.timer_item)
        self.menu.add(rumps.separator)
        self.menu.add(self.start_stop_item)
        self.menu.add(self.pause_item)
        self.menu.add(rumps.separator)
        self.menu.add(self.mode_menu)
        self.menu.add(rumps.separator)
        self.menu.add(self.dashboard_item)
        self.menu.add(self.report_item)
        self.menu.add(rumps.separator)
        self.menu.add(self.account_item)
        self.menu.add(self.logout_item)
        self.menu.add(rumps.separator)
        self.menu.add(self.quit_item)

    # ------------------------------------------------------------------
    # Timer (polls engine every second)
    # ------------------------------------------------------------------

    @rumps.timer(1)
    def _tick(self, timer) -> None:
        """Poll engine status every second and update timer display."""
        status = self.engine.get_status()

        if status["is_running"]:
            elapsed = status["elapsed_seconds"]
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self.timer_item.title = f"{h:02d}:{m:02d}:{s:02d}"
        else:
            if self.timer_item.title:
                self.timer_item.title = ""

    # ------------------------------------------------------------------
    # Session controls
    # ------------------------------------------------------------------

    def _toggle_session(self, sender) -> None:
        """Start or stop a session."""
        if not self.engine.is_running:
            # Fetch latest settings from cloud before starting
            self._apply_cloud_settings()

            result = self.engine.start_session()
            if result["success"]:
                self.start_stop_item.title = "Stop Session"
                self.pause_item.set_callback(self._toggle_pause)
                self.pause_item.title = "Pause"
                # Disable mode toggle during session
                self.mode_camera.set_callback(None)
                self.mode_screen.set_callback(None)
                self.mode_both.set_callback(None)
            else:
                rumps.alert(
                    title=result.get("error_type", "Error"),
                    message=result.get("error", "Failed to start session"),
                )
        else:
            result = self.engine.stop_session()
            self._reset_to_idle()

            # Upload session data to cloud
            if result.get("session_data") and self.sync.is_available():
                self.sync.upload_session(result["session_data"])

    def _toggle_pause(self, sender) -> None:
        """Pause or resume the session."""
        if self.engine.is_paused:
            self.engine.resume_session()
            self.pause_item.title = "Pause"
        else:
            self.engine.pause_session()
            self.pause_item.title = "Resume"

    def _reset_to_idle(self) -> None:
        """Reset menu items to idle state."""
        self.start_stop_item.title = "Start Session"
        self.pause_item.set_callback(None)
        self.pause_item.title = "Pause"
        self.timer_item.title = ""
        self.status_item.title = "Ready to start"

        # Re-enable mode toggle
        self.mode_camera.set_callback(self._set_mode_camera)
        self.mode_screen.set_callback(self._set_mode_screen)
        self.mode_both.set_callback(self._set_mode_both)

    # ------------------------------------------------------------------
    # Mode selection
    # ------------------------------------------------------------------

    def _set_mode_camera(self, sender) -> None:
        """Switch to camera-only mode."""
        self.engine.set_monitoring_mode(config.MODE_CAMERA_ONLY)
        self.mode_camera.state = 1
        self.mode_screen.state = 0
        self.mode_both.state = 0

    def _set_mode_screen(self, sender) -> None:
        """Switch to screen-only mode."""
        self.engine.set_monitoring_mode(config.MODE_SCREEN_ONLY)
        self.mode_camera.state = 0
        self.mode_screen.state = 1
        self.mode_both.state = 0

    def _set_mode_both(self, sender) -> None:
        """Switch to both (camera + screen) mode."""
        self.engine.set_monitoring_mode(config.MODE_BOTH)
        self.mode_camera.state = 0
        self.mode_screen.state = 0
        self.mode_both.state = 1

    # ------------------------------------------------------------------
    # Utility items
    # ------------------------------------------------------------------

    def _open_dashboard(self, sender) -> None:
        """Open web dashboard in default browser."""
        url = getattr(config, "DASHBOARD_URL", "https://braindock.com/dashboard")
        webbrowser.open(url)

    def _download_report(self, sender) -> None:
        """Open the most recently generated PDF report."""
        report_path = self.engine.get_last_report_path()
        if report_path and report_path.exists():
            os.system(f'open "{report_path}"')
            logger.info(f"Opened report: {report_path}")
        else:
            rumps.alert(
                title="No Report",
                message="No recent report found. Complete a session first.",
            )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _login(self, sender) -> None:
        """Start browser-based login flow."""
        url = getattr(config, "DASHBOARD_URL", "https://braindock.com")
        success = self.sync.login_with_browser(dashboard_url=url)
        if success:
            # Rebuild menu to show full controls
            self._build_menu()
            # Fetch settings now that we're authenticated
            self._apply_cloud_settings()
            # Pre-warm camera
            self.engine.prewarm_camera()
            rumps.notification(
                title="BrainDock",
                subtitle="",
                message="You're now logged in!",
            )
        else:
            rumps.alert(title="Login Failed", message="Could not complete login. Please try again.")

    def _signup(self, sender) -> None:
        """Open signup page in browser."""
        url = getattr(config, "DASHBOARD_URL", "https://braindock.com")
        webbrowser.open(f"{url.rstrip('/')}/auth/signup")

    def _logout(self, sender) -> None:
        """Log out and clear stored tokens."""
        # Stop any running session first
        if self.engine.is_running:
            self.engine.stop_session()

        self.sync.logout()
        # Rebuild menu to show only login/signup
        self._build_menu()
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

            # Update mode checkmarks
            self.mode_camera.state = 1 if mode == config.MODE_CAMERA_ONLY else 0
            self.mode_screen.state = 1 if mode == config.MODE_SCREEN_ONLY else 0
            self.mode_both.state = 1 if mode == config.MODE_BOTH else 0

            blocklist = BrainDockSync.cloud_settings_to_blocklist(settings)
            self.engine.set_blocklist(blocklist)

            logger.info("Cloud settings applied")
        except Exception as e:
            logger.warning(f"Could not apply cloud settings: {e}")

    # ------------------------------------------------------------------
    # Engine callbacks
    # ------------------------------------------------------------------

    def _on_status_change(self, status: str, text: str) -> None:
        """Update status display in menu."""
        self.status_item.title = text

    def _on_session_ended(self, report_path: Optional[Path]) -> None:
        """Handle session end."""
        self._reset_to_idle()
        if report_path:
            rumps.notification(
                title="BrainDock",
                subtitle="Session Complete",
                message=f"Report saved: {report_path.name}",
            )

    def _on_error(self, error_type: str, message: str) -> None:
        """Show error to user."""
        rumps.alert(title=f"Error: {error_type}", message=message)

    def _on_alert(self, level: int, message: str) -> None:
        """Show unfocused alert notification."""
        rumps.notification(
            title="BrainDock",
            subtitle="Focus Reminder",
            message=message,
        )

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def _quit_app(self, sender) -> None:
        """Clean up and quit."""
        if self.engine.is_running:
            result = self.engine.stop_session()
            if result.get("session_data") and self.sync.is_available():
                self.sync.upload_session(result["session_data"])

        self.engine.cleanup()
        rumps.quit_application()
