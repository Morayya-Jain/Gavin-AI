"""
Menu bar / system tray package for BrainDock.

Provides a cross-platform launcher that picks the right UI:
- macOS: rumps-based native menu bar
- Windows: pystray-based system tray
"""

import sys
import logging

logger = logging.getLogger(__name__)


def run_menubar_app() -> None:
    """Launch the appropriate menu bar app for the current platform."""
    if sys.platform == "darwin":
        from menubar.macos_app import BrainDockMenuBar
        app = BrainDockMenuBar()
        app.run()
    elif sys.platform == "win32":
        from menubar.windows_app import BrainDockTray
        app = BrainDockTray()
        app.run()
    else:
        logger.error("BrainDock menu bar is only supported on macOS and Windows.")
        sys.exit(1)
