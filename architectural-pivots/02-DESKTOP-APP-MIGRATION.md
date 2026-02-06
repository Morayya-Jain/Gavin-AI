# Phase 2: Desktop App Migration (Menu Bar Agent)

> **Prerequisites:**
> - Read `00-MIGRATION-OVERVIEW.md` for full context
> - Phase 1 (Backend & Auth) must be **complete and tested** before starting this phase
>
> **This phase is the HIGHEST-RISK piece.** The current `gui/app.py` (6,681 lines) has business logic tangled with UI code. This document provides a detailed extraction plan to minimize risk.

---

## Table of Contents

1. [Overview](#overview)
2. [Critical Rule: Extract Before Delete](#critical-rule-extract-before-delete)
3. [Step 1: Analyze gui/app.py — Business Logic vs UI](#step-1-analyze-guiapppy--business-logic-vs-ui)
4. [Step 2: Create core/engine.py](#step-2-create-coreenginepy)
5. [Step 3: Build the Menu Bar App](#step-3-build-the-menu-bar-app)
6. [Step 4: Add Auth Flow](#step-4-add-auth-flow)
7. [Step 5: Add Settings Sync](#step-5-add-settings-sync)
8. [Step 6: Add Session Upload](#step-6-add-session-upload)
9. [Step 7: Offline Fallback Behavior](#step-7-offline-fallback-behavior)
10. [Step 8: Update Entry Point and Config](#step-8-update-entry-point-and-config)
11. [Step 9: Update Dependencies](#step-9-update-dependencies)
12. [Step 10: Update Build Scripts](#step-10-update-build-scripts)
13. [Step 11: Clean Up — Delete Old GUI Files](#step-11-clean-up--delete-old-gui-files)
14. [Testing Checklist](#testing-checklist)
15. [Rollback Plan](#rollback-plan)

---

## Overview

**What this phase does:**
- Extracts detection orchestration from `gui/app.py` into a clean `core/engine.py`
- Replaces the entire CustomTkinter GUI with a macOS menu bar icon (`rumps`) and Windows system tray (`pystray`)
- Adds Supabase auth flow (login via browser)
- Adds settings sync (fetch blocklist/preferences from Supabase on session start)
- Adds session upload (push session data to Supabase on session end)
- Removes ~10,000 lines of GUI code, adds ~800-1,200 lines of engine + menu bar code

**Estimated effort:** 5–7 days

**What you'll have at the end:** A minimal menu bar app that runs focus tracking sessions, generates PDF reports, syncs with the cloud, and has zero desktop GUI.

---

## Critical Rule: Extract Before Delete

**NEVER delete GUI code until the business logic it contains has been cleanly extracted into `core/engine.py` and tested independently.**

The current `gui/app.py` is a monolith where business logic is deeply interleaved with UI code. For example, `_start_session()` (lines 5169–5383) mixes:
- Session initialization (business logic)
- Camera permission checks (business logic)
- Screen permission checks (business logic)
- API key validation (business logic)
- Pause state reset (business logic)
- Button text changes (UI)
- Layout transitions (UI)
- Label updates (UI)
- Button repacking (UI)

**The extraction must happen BEFORE the menu bar app is built.** The correct sequence is:

1. Create `core/engine.py` with all business logic extracted
2. **Test `core/engine.py` independently** (write a simple test script that calls `engine.start_session()` and `engine.stop_session()`)
3. Build the menu bar app that calls `core/engine.py`
4. Verify menu bar app works end-to-end
5. THEN and ONLY THEN delete the old GUI files

---

## Step 1: Analyze gui/app.py — Business Logic vs UI

Here's a detailed breakdown of what's in `gui/app.py` (6,681 lines) and where each piece goes:

### Pure Business Logic (Extract to core/engine.py)

| Method/Section | Lines | What It Does | Priority |
|---------------|-------|-------------|----------|
| `check_macos_camera_permission()` | 72–162 | macOS camera authorization check | HIGH — needed before camera sessions |
| `check_macos_accessibility_permission()` | ~164–200 | macOS accessibility check for screen monitoring | HIGH |
| `check_windows_screen_permission()` | ~200–250 | Windows screen access check | HIGH |
| `open_macos_accessibility_settings()` | ~250–280 | Opens macOS System Settings | MEDIUM |
| `_prewarm_camera_async()` | 1954+ | Camera pre-warming in background thread | MEDIUM — nice optimization |
| `_detection_loop()` | 5467–5625 | **Core camera detection loop** (threading, Vision API, event logging, alert tracking, gadget temporal filtering) | **CRITICAL** |
| `_screen_detection_loop()` | 5627–5810 | **Core screen monitoring loop** (threading, blocklist checking, event logging) | **CRITICAL** |
| `_resolve_priority_status()` | Somewhere in class | Priority resolution when both camera + screen are active | HIGH |
| `_start_session()` business logic | 5169–5383 | Session init, permission checks, thread spawning | **CRITICAL** |
| `_stop_session()` business logic | 5385–5465 | Thread cleanup, session end, usage recording | **CRITICAL** |
| `_pause_session()` business logic | 5080–5132 | Pause state tracking, event logging | HIGH |
| `_resume_session()` business logic | 5134–5167 | Resume state, event logging | HIGH |
| `_generate_report()` core logic | 6205–6262 | Statistics computation, PDF generation | HIGH |
| `_play_unfocused_alert()` | In class | Audio alert playback | MEDIUM |
| `_handle_time_exhausted()` | 5814+ | Usage limit enforcement | MEDIUM |
| Alert tracking state | In `__init__` | `unfocused_start_time`, `alerts_played`, consecutive gadget counters | HIGH |

### Pure UI Code (Delete — replaced by menu bar)

| Section | Lines | What It Does |
|---------|-------|-------------|
| `RoundedButton` class | 698–824 | Canvas-based rounded button widget |
| `IconButton` class | 825–1117 | Canvas button with drawn icons (gear, lightbulb) |
| `Card` class | 1118–1177 | Stat card widget |
| `Badge` class | 1178–1287 | Status badge/pill widget |
| `Tooltip` class | 1288–1381 | Hover tooltip widget |
| `NotificationPopup` class | 1382–1783 | Unfocused alert overlay window |
| `BrainDockGUI.__init__` UI setup | 1799–1900+ | Window creation, CustomTkinter setup, DPI, colors |
| `_setup_main_app()` | Long method | All widget creation (header, buttons, cards, mode selector) |
| Settings popup | ~2600–3500 | 600+ lines of blocklist settings UI |
| Tutorial popup | ~4400–4700 | 275+ lines of how-to-use popup |
| `_update_status()` | 6014–6035 | Status badge text/color update |
| `_update_timer()` | 6036+ | Timer label update |
| `_update_stat_cards()` | 2616+ | Daily stats card updates |
| `_reset_button_state()` | 6264–6273 | Button text/color reset |
| `_reset_to_idle_state()` | 6275–6306 | Full UI reset |
| Lockout overlay | 4800+ | Usage limit lockout UI |
| All layout constants | Top of file | `COLORS`, `MIN_WIDTH`, `MIN_HEIGHT`, etc. |

### Shared Code (Used by both but needs separation)

| Section | What To Do |
|---------|-----------|
| State variables in `__init__` (`is_running`, `should_stop`, `session`, etc.) | Move to `core/engine.py` as engine state |
| `_state_lock`, `_camera_state`, `_screen_state` | Move to engine (thread-safe state management) |
| `blocklist_manager`, `blocklist` initialization | Move to engine (loaded from Supabase or local cache) |
| `usage_limiter`, `daily_stats` initialization | Move to engine (unchanged behavior) |
| `monitoring_mode` | Move to engine (set by menu bar before start) |

---

## Step 2: Create core/engine.py

This is the most important file in the migration. It contains all detection orchestration logic extracted from `gui/app.py`.

### Engine Architecture

```python
# core/engine.py — Detection orchestration engine
#
# This module contains ALL business logic previously in gui/app.py.
# It has ZERO UI dependencies — no tkinter, no customtkinter, no GUI imports.
# The menu bar app (or any future UI) calls engine methods.

class SessionEngine:
    """
    Core session management engine.
    
    Handles:
    - Session lifecycle (start, stop, pause, resume)
    - Camera detection loop (background thread)
    - Screen detection loop (background thread)
    - Priority resolution (camera + screen combined mode)
    - Unfocused alert tracking
    - Usage limit enforcement
    - Report generation
    - Settings management (blocklist, gadget preferences)
    
    Callbacks:
    - on_status_change(status: str, text: str) — called when detection status changes
    - on_timer_tick(elapsed_seconds: int) — called every second with active duration
    - on_session_ended(report_path: Optional[Path]) — called when session stops
    - on_error(error_type: str, message: str) — called on errors (camera, permissions, etc.)
    - on_alert(level: int, message: str) — called for unfocused alerts
    """
    
    def __init__(self):
        # Detection state (from gui/app.py __init__)
        # Thread management
        # Pause state
        # Alert tracking
        # Usage limiter
        # Daily stats
        pass
    
    def set_monitoring_mode(self, mode: str):
        """Set monitoring mode: 'camera_only', 'screen_only', 'both'"""
        pass
    
    def set_blocklist(self, blocklist):
        """Set blocklist configuration (from Supabase or local cache)"""
        pass
    
    def start_session(self) -> dict:
        """
        Start a new focus session.
        
        Returns:
            {"success": bool, "error": str | None, "error_type": str | None}
            error_type: "camera_denied", "camera_restricted", "no_api_key", 
                       "screen_permission", "time_exhausted", "already_running"
        """
        # Permission checks (extracted from _start_session)
        # Session initialization
        # Thread spawning
        pass
    
    def stop_session(self) -> dict:
        """
        Stop the current session and generate report.
        
        Returns:
            {"success": bool, "report_path": Optional[Path], "session_data": Optional[dict]}
            session_data contains summary for Supabase upload
        """
        # Thread cleanup (extracted from _stop_session)
        # Session end
        # Report generation
        # Return session data for cloud sync
        pass
    
    def pause_session(self):
        """Pause the current session."""
        pass
    
    def resume_session(self):
        """Resume the current session."""
        pass
    
    def get_status(self) -> dict:
        """
        Get current engine status.
        
        Returns:
            {"is_running": bool, "is_paused": bool, "status": str, 
             "elapsed_seconds": int, "monitoring_mode": str}
        """
        pass
    
    def check_time_remaining(self) -> dict:
        """
        Check usage time remaining.
        
        Returns:
            {"remaining_seconds": int, "is_exhausted": bool, "extensions_used": int}
        """
        pass
    
    def get_last_report_path(self) -> Optional[Path]:
        """
        Get the path to the most recently generated report.
        Persisted across app restarts via a local file.
        
        Returns:
            Path to the PDF, or None if no report exists.
        """
        pass
    
    def cleanup(self):
        """Clean up resources (call before app quit)."""
        pass
```

### Timer Tick Mechanism

> **Important:** The current GUI timer works via `self.root.after(1000, self._update_timer)` — a tkinter-specific repeating callback. With tkinter removed, there is no built-in timer mechanism. The engine needs its own approach.

**Recommended approach:** The engine does NOT run its own timer thread. Instead, the menu bar app polls `engine.get_status()` on its own schedule:

- **macOS (rumps):** Use the `@rumps.timer(1)` decorator to call `engine.get_status()` every second and update the menu bar timer display.
- **Windows (pystray):** `pystray` doesn't have a built-in timer. Use a background `threading.Timer` or `time.sleep(1)` loop in a daemon thread to poll `engine.get_status()` and update the tray tooltip.

This keeps the engine purely passive (no UI awareness) and lets each platform handle its own update frequency.

### "Download Last Report" Persistence

The menu bar has a "Download Last Report" item. After a session ends and the app restarts, the engine needs to know the path to the last generated report. The engine should:

1. After generating a report, write the path to a local file: `config.USER_DATA_DIR / "last_report.json"`
2. `get_last_report_path()` reads this file and returns the path
3. If the PDF file no longer exists (user deleted it), return `None`
4. The menu bar's "Download Last Report" calls `engine.get_last_report_path()` and opens it, or shows "No recent report" if `None`

### Callback Pattern

The engine uses callbacks instead of direct UI updates. This decouples it from any specific UI:

```python
class SessionEngine:
    def __init__(self):
        # Callbacks — set by the menu bar app
        self.on_status_change = None   # (status: str, text: str) -> None
        self.on_timer_tick = None      # (elapsed_seconds: int) -> None
        self.on_session_ended = None   # (report_path: Optional[Path]) -> None
        self.on_error = None           # (error_type: str, message: str) -> None
        self.on_alert = None           # (level: int, message: str) -> None

    def _notify_status_change(self, status: str, text: str):
        """Thread-safe status notification."""
        if self.on_status_change:
            self.on_status_change(status, text)
```

### What Gets Extracted (Line-by-Line Reference)

From `gui/app.py` → `core/engine.py`:

| gui/app.py Section | Lines | Becomes in engine.py |
|---|---|---|
| State variables (`__init__`) | 1864–1910 | `SessionEngine.__init__()` state attributes |
| `_detection_loop()` | 5467–5625 | `SessionEngine._detection_loop()` — replace `self.root.after(0, ...)` with callback calls |
| `_screen_detection_loop()` | 5627–5810 | `SessionEngine._screen_detection_loop()` — same callback replacement |
| `_start_session()` lines 5171–5310 | Business logic only | `SessionEngine.start_session()` — return error dict instead of showing messagebox |
| `_start_session()` lines 5311–5383 | Thread spawning | `SessionEngine.start_session()` — thread creation |
| `_stop_session()` lines 5385–5465 | Thread cleanup + session end | `SessionEngine.stop_session()` — return session data |
| `_pause_session()` lines 5080–5110 | State tracking | `SessionEngine.pause_session()` |
| `_resume_session()` lines 5134–5167 | State tracking | `SessionEngine.resume_session()` |
| `_generate_report()` lines 6219–6232 | Stats + PDF | `SessionEngine._generate_report()` — return path |
| `_resolve_priority_status()` | All | `SessionEngine._resolve_priority_status()` |
| `_play_unfocused_alert()` | All | `SessionEngine._play_unfocused_alert()` — call on_alert callback |
| `check_macos_camera_permission()` | 72–162 | Move to `core/permissions.py` (standalone function) |
| `check_macos_accessibility_permission()` | ~164–200 | Move to `core/permissions.py` |
| `check_windows_screen_permission()` | ~200–250 | Move to `core/permissions.py` |

### Key Transformation: Removing UI Calls

Every `self.root.after(0, ...)` call in the detection loops becomes a callback:

**Before (gui/app.py):**
```python
# Inside _detection_loop
self.root.after(0, lambda: self._update_status("focused", "Focussed"))
```

**After (core/engine.py):**
```python
# Inside _detection_loop
self._notify_status_change("focused", "Focussed")
```

Every `messagebox.showerror(...)` becomes an error return or callback:

**Before:**
```python
messagebox.showerror("API Key Required", "Gemini API key not found!")
return
```

**After:**
```python
return {"success": False, "error": "Gemini API key not found!", "error_type": "no_api_key"}
```

---

## Step 3: Build the Menu Bar App

### macOS: Using rumps

```python
# menubar/macos_app.py
import rumps
from core.engine import SessionEngine

class BrainDockMenuBar(rumps.App):
    """macOS menu bar application for BrainDock."""
    
    def __init__(self):
        super().__init__(
            name="BrainDock",
            icon="assets/menu_icon.png",  # 22x22 or 44x44 (Retina) PNG
            quit_button=None  # Custom quit to handle cleanup
        )
        
        self.engine = SessionEngine()
        
        # Set engine callbacks
        self.engine.on_status_change = self._on_status_change
        self.engine.on_timer_tick = self._on_timer_tick
        self.engine.on_session_ended = self._on_session_ended
        self.engine.on_error = self._on_error
        
        # Build menu structure
        self.status_item = rumps.MenuItem("● Ready to start", callback=None)
        self.status_item.set_callback(None)  # Non-clickable
        
        self.timer_item = rumps.MenuItem("", callback=None)
        
        self.start_stop_item = rumps.MenuItem("▶ Start Session", callback=self.toggle_session)
        self.pause_item = rumps.MenuItem("⏸ Pause", callback=self.toggle_pause)
        self.pause_item.set_callback(None)  # Hidden initially
        
        # Mode selection
        self.mode_camera = rumps.MenuItem("Camera", callback=self.set_mode_camera)
        self.mode_screen = rumps.MenuItem("Screen", callback=self.set_mode_screen)
        self.mode_both = rumps.MenuItem("Both", callback=self.set_mode_both)
        self.mode_camera.state = 1  # Checked by default
        
        self.mode_menu = rumps.MenuItem("Mode")
        self.mode_menu.update([self.mode_camera, self.mode_screen, self.mode_both])
        
        # Utility items
        self.dashboard_item = rumps.MenuItem("Open Dashboard →", callback=self.open_dashboard)
        self.report_item = rumps.MenuItem("Download Last Report", callback=self.download_report)
        
        # Account
        self.account_item = rumps.MenuItem("user@email.com", callback=None)
        self.logout_item = rumps.MenuItem("Log Out", callback=self.logout)
        self.quit_item = rumps.MenuItem("Quit BrainDock", callback=self.quit_app)
        
        # Assemble menu
        self.menu = [
            self.status_item,
            self.timer_item,
            None,  # Separator
            self.start_stop_item,
            self.pause_item,
            None,
            self.mode_menu,
            None,
            self.dashboard_item,
            self.report_item,
            None,
            self.account_item,
            self.logout_item,
            self.quit_item,
        ]
    
    def toggle_session(self, sender):
        """Start or stop a session."""
        if not self.engine.is_running:
            result = self.engine.start_session()
            if result["success"]:
                self.start_stop_item.title = "■ Stop Session"
                self.pause_item.set_callback(self.toggle_pause)
            else:
                rumps.alert(
                    title=result.get("error_type", "Error"),
                    message=result.get("error", "Failed to start session")
                )
        else:
            result = self.engine.stop_session()
            self.start_stop_item.title = "▶ Start Session"
            self.pause_item.set_callback(None)
    
    # ... additional callback methods ...
    
    def open_dashboard(self, sender):
        """Open web dashboard in browser."""
        import webbrowser
        webbrowser.open("https://braindock.com/dashboard")
    
    def quit_app(self, sender):
        """Clean up and quit."""
        if self.engine.is_running:
            self.engine.stop_session()
        self.engine.cleanup()
        rumps.quit_application()
```

### Windows: Using pystray

```python
# menubar/windows_app.py
import sys
import threading
import webbrowser
import pystray
from PIL import Image
from core.engine import SessionEngine

class BrainDockTray:
    """Windows system tray application for BrainDock."""
    
    def __init__(self):
        self.engine = SessionEngine()
        
        # Set engine callbacks
        self.engine.on_status_change = self._on_status_change
        self.engine.on_session_ended = self._on_session_ended
        self.engine.on_error = self._on_error
        
        # Load tray icon (use .ico on Windows for best quality)
        self.icon_image = Image.open("assets/menu_icon.png")
        
        # Build menu
        self.icon = pystray.Icon(
            name="BrainDock",
            icon=self.icon_image,
            title="BrainDock - Ready",
            menu=self._build_menu()
        )
        
        # Start timer thread for updating tooltip/status during sessions
        self._timer_running = True
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
    
    def _build_menu(self):
        """Build the tray context menu (right-click on Windows)."""
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: self._get_status_text(),
                None, enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "■ Stop Session" if self.engine.is_running else "▶ Start Session",
                self.toggle_session
            ),
            pystray.MenuItem(
                lambda item: "▶ Resume" if self.engine.is_paused else "⏸ Pause",
                self.toggle_pause,
                visible=lambda item: self.engine.is_running
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Mode", pystray.Menu(
                pystray.MenuItem("Camera", self.set_mode_camera, checked=lambda item: self.engine.monitoring_mode == "camera_only"),
                pystray.MenuItem("Screen", self.set_mode_screen, checked=lambda item: self.engine.monitoring_mode == "screen_only"),
                pystray.MenuItem("Both", self.set_mode_both, checked=lambda item: self.engine.monitoring_mode == "both"),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Dashboard →", self.open_dashboard),
            pystray.MenuItem("Download Last Report", self.download_report),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit BrainDock", self.quit_app),
        )
    
    def _timer_loop(self):
        """Background thread to update tray tooltip with session timer."""
        import time
        while self._timer_running:
            if self.engine.is_running:
                status = self.engine.get_status()
                elapsed = status.get("elapsed_seconds", 0)
                h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
                self.icon.title = f"BrainDock - {h:02d}:{m:02d}:{s:02d}"
            time.sleep(1)
    
    def _on_status_change(self, status: str, text: str):
        """Update tray tooltip on status change."""
        self.icon.title = f"BrainDock - {text}"
    
    def toggle_session(self, icon, item):
        """Start or stop a session."""
        if not self.engine.is_running:
            result = self.engine.start_session()
            if not result["success"]:
                # pystray has no built-in dialogs — use Windows notification balloon
                self.icon.notify(result.get("error", "Failed to start"), "BrainDock Error")
        else:
            self.engine.stop_session()
    
    def toggle_pause(self, icon, item):
        """Pause or resume session."""
        if self.engine.is_paused:
            self.engine.resume_session()
        else:
            self.engine.pause_session()
    
    def open_dashboard(self, icon, item):
        """Open web dashboard in browser."""
        webbrowser.open("https://braindock.com/dashboard")
    
    def quit_app(self, icon, item):
        """Clean up and quit."""
        self._timer_running = False
        if self.engine.is_running:
            self.engine.stop_session()
        self.engine.cleanup()
        self.icon.stop()
    
    def run(self):
        """Start the tray application."""
        self._timer_thread.start()
        self.icon.run()
```

### Windows-Specific Notes

**Differences from macOS menu bar:**
- **Right-click menu:** On Windows, the tray menu opens on right-click (not left-click like macOS). Left-click could optionally show a small popup window.
- **No dynamic menu item text updates:** `pystray` uses lambda functions for dynamic text (e.g., `lambda item: "Stop" if running else "Start"`). The menu re-evaluates these each time it opens.
- **Tooltip for timer:** Windows tray icons have hover tooltips (`icon.title`). The timer updates via a background thread, so hovering the icon shows the current session time.
- **Notifications:** `pystray` supports Windows notification balloons via `icon.notify()`. Use these for errors and alerts instead of dialog boxes.
- **Auth code input:** `pystray` has no built-in input dialogs. For the login code prompt, use a minimal `tkinter.simpledialog.askstring()` (tkinter is included with Python and doesn't require CustomTkinter). Alternatively, tell the user to paste the code on the website and have the app poll for it.
- **No Dock equivalent to hide:** Windows tray apps don't appear in the taskbar by default when using pystray. If the user launches the `.exe` while the tray is already running, `instance_lock.py` handles this (shows "already running" and exits).

### Cross-Platform Entry Point

```python
# menubar/__init__.py
import sys

def run_menubar_app():
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
        print("BrainDock menu bar is only supported on macOS and Windows.")
        sys.exit(1)
```

### Note on rumps Maintenance Status

`rumps` (v0.4.0) was last released in October 2022 and is not actively maintained. While it works on current macOS versions (up to macOS 15), there is a risk that future macOS updates could break compatibility with no upstream fix available.

**Mitigation:**
- `pystray` is cross-platform (works on macOS too) and is more actively maintained. If `rumps` breaks on a future macOS version, swap to `pystray` for macOS as well. The engine's callback-based architecture means changing the menu bar library requires only rewriting `menubar/macos_app.py` (~150 lines), not the engine.
- Alternatively, `rumps` is a thin wrapper around `PyObjC` — if it breaks, the fix is usually small and can be patched locally.

### Menu Bar / Tray Icon Design

**macOS (menu bar):**
- **Size:** 22x22 pixels (44x44 for Retina/HiDPI)
- **Format:** PNG with transparency
- **Style:** Monochrome (black on light, white on dark) — macOS menu bar convention
- **Template image:** Set `template=True` in rumps so macOS automatically handles dark/light mode
- **States:** Consider 3 icon variants using different template images:
  - Default (idle): Standard brain/dock icon
  - Active (tracking): Same icon with a small green dot indicator
  - Paused: Same icon with yellow/amber indicator

**Windows (system tray):**
- **Size:** 16x16 pixels (32x32 for high-DPI displays). Windows auto-scales from larger icons.
- **Format:** `.ico` file preferred (supports multiple resolutions in one file: 16x16, 32x32, 48x48). PNG also works via Pillow but `.ico` gives the best quality.
- **Style:** Can be full-color (Windows tray icons are not restricted to monochrome)
- **States:** Change the icon image at runtime via `self.icon.icon = new_image` for idle/tracking/paused states

**Create these icon assets:**
- `assets/menu_icon.png` — macOS template image (monochrome, 44x44)
- `assets/tray_icon.ico` — Windows tray icon (multi-resolution .ico)
- `assets/tray_icon_active.ico` — Windows active state (optional)

### Platform-Specific App Behavior

**macOS: No Dock Icon (LSUIElement)**

The app should NOT show in the Dock. This is controlled by `LSUIElement` in `Info.plist`:

```xml
<key>LSUIElement</key>
<true/>
```

When the user opens BrainDock from Applications folder or Spotlight:
- The menu bar icon activates (if not already running)
- No window opens, no Dock icon appears
- The menu bar dropdown is the only interface
- If already running, `instance_lock.py` detects this and exits silently (or activates the existing menu bar)

This is standard behavior for apps like Bartender, Rectangle, iStat Menus.

**Windows: No Taskbar Window**

The app runs as a system tray icon only — no taskbar window. This is the default behavior with pystray (no window is created). PyInstaller's `--noconsole` flag ensures no terminal window appears either.

When the user launches BrainDock from Start Menu, Desktop shortcut, or File Explorer:
- The system tray icon appears (bottom-right, near the clock)
- No window opens, no taskbar entry
- Right-click the tray icon to see the menu
- If already running, `instance_lock.py` detects this and shows a brief notification ("BrainDock is already running in the system tray") then exits

**Optional: Run at startup.** The Windows installer can add a registry entry to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` so BrainDock starts automatically when the user logs in. This is common for tray apps and should be an opt-in checkbox during installation.

---

## Step 4: Add Auth Flow

### Supabase Python Client Setup

```python
# sync/supabase_client.py
from supabase import create_client, Client
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

class BrainDockSync:
    """Handles authentication and data sync with Supabase."""
    
    def __init__(self, supabase_url: str, supabase_key: str):
        # Use the existing platform-specific user data directory from config.py
        # macOS: ~/Library/Application Support/BrainDock/
        # Windows: %APPDATA%/BrainDock/
        # Linux: ~/.local/share/BrainDock/
        import config
        self.data_dir = config.USER_DATA_DIR
        self.auth_file = self.data_dir / "auth.json"
        self.settings_cache_file = self.data_dir / "settings_cache.json"
        
        self.client: Client = create_client(supabase_url, supabase_key)
        self._load_stored_session()
    
    def _load_stored_session(self):
        """Load stored auth tokens if they exist."""
        if self.auth_file.exists():
            try:
                data = json.loads(self.auth_file.read_text())
                self.client.auth.set_session(
                    data["access_token"],
                    data["refresh_token"]
                )
                logger.info(f"Loaded stored session for {data.get('email', 'unknown')}")
            except Exception as e:
                logger.warning(f"Failed to load stored session: {e}")
    
    def _save_session(self, session):
        """Save auth tokens to local storage."""
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "user_id": session.user.id,
            "email": session.user.email,
            "expires_at": session.expires_at
        }
        self.auth_file.write_text(json.dumps(data, indent=2))
    
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated."""
        try:
            user = self.client.auth.get_user()
            return user is not None
        except Exception:
            return False
    
    def get_user_email(self) -> str:
        """Get current user's email."""
        try:
            user = self.client.auth.get_user()
            return user.user.email if user else ""
        except Exception:
            return ""
    
    def login_with_email(self, email: str, password: str) -> dict:
        """Login with email and password."""
        try:
            result = self.client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            self._save_session(result.session)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def logout(self):
        """Sign out and clear stored tokens."""
        try:
            self.client.auth.sign_out()
        except Exception:
            pass
        if self.auth_file.exists():
            self.auth_file.unlink()
    
    def check_subscription(self) -> dict:
        """Check if user has active subscription."""
        try:
            result = self.client.table("subscriptions") \
                .select("status, subscription_tiers(name, features)") \
                .eq("status", "active") \
                .single() \
                .execute()
            
            if result.data:
                tier = result.data.get("subscription_tiers", {})
                return {
                    "has_access": True,
                    "tier": tier.get("name", "starter"),
                    "features": tier.get("features", {})
                }
            return {"has_access": False, "tier": "none", "features": {}}
        except Exception as e:
            logger.warning(f"Failed to check subscription: {e}")
            return {"has_access": False, "tier": "unknown", "features": {}}
```

### Auth Flow in Menu Bar

When the app launches:
1. Check if `auth.json` exists and contains valid tokens
2. If yes → show user email in menu, proceed normally
3. If no → show "Log In" menu item instead of session controls

When user clicks "Log In":
1. Open `https://braindock.com/auth/login?source=desktop` in browser
2. User logs in on the website (email/password or Google OAuth)
3. Website displays a short-lived linking code (e.g., "ABCD-1234")
4. User enters the code in the desktop app's prompt (e.g., via `rumps.Window` input dialog)
5. App exchanges the code for Supabase session tokens via a secure API call
6. App stores tokens locally and refreshes menu

> **Note:** This matches the manual code entry flow documented in `01-BACKEND-AND-AUTH.md` and recommended as Option C in `03-WEB-DASHBOARD-MIGRATION.md`. See those documents for the full auth flow and security rationale.

### Device Registration

On first successful auth, register the device:

```python
def register_device(self):
    """Register this device with the user's account."""
    import sys
    import hashlib
    import platform
    import uuid
    from datetime import datetime, timezone
    
    # Generate machine ID (same logic as existing license_manager.py)
    mac = uuid.getnode()
    machine_id = hashlib.sha256(str(mac).encode()).hexdigest()[:32]
    
    device_name = platform.node() or "Unknown Device"
    os_name = sys.platform
    
    self.client.table("devices").upsert({
        "user_id": self.client.auth.get_user().user.id,
        "machine_id": machine_id,
        "device_name": device_name,
        "os": os_name,
        "app_version": "2.0.0",
        # Use Python datetime, not SQL "now()" — the Supabase client sends JSON,
        # so SQL functions like now() are treated as literal strings
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,machine_id").execute()
```

---

## Step 5: Add Settings Sync

Settings are fetched from Supabase **once, at session start**. This keeps costs at zero and avoids continuous polling.

```python
# In sync/supabase_client.py

def fetch_settings(self) -> dict:
    """
    Fetch user settings and blocklist from Supabase.
    Called once at session start.
    
    Returns:
        {
            "monitoring_mode": "camera_only",
            "enabled_gadgets": ["phone"],
            "vision_provider": "gemini",
            "blocklist": {
                "quick_blocks": {"instagram": True, ...},
                "categories": {"social_media": True, ...},
                "custom_urls": ["example.com"],
                "custom_apps": ["Discord"]
            }
        }
    """
    try:
        # Fetch user settings
        settings_result = self.client.table("user_settings") \
            .select("*").single().execute()
        
        # Fetch blocklist config
        blocklist_result = self.client.table("blocklist_configs") \
            .select("*").single().execute()
        
        settings = settings_result.data or {}
        blocklist = blocklist_result.data or {}
        
        result = {
            "monitoring_mode": settings.get("monitoring_mode", "camera_only"),
            "enabled_gadgets": settings.get("enabled_gadgets", ["phone"]),
            "vision_provider": settings.get("vision_provider", "gemini"),
            "blocklist": {
                "quick_blocks": blocklist.get("quick_blocks", {}),
                "categories": blocklist.get("categories", {}),
                "custom_urls": blocklist.get("custom_urls", []),
                "custom_apps": blocklist.get("custom_apps", []),
            }
        }
        
        # Cache locally for offline fallback
        self._cache_settings(result)
        
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch settings from cloud, using cache: {e}")
        return self._load_cached_settings()

def _cache_settings(self, settings: dict):
    """Cache settings locally for offline use."""
    self.settings_cache_file.parent.mkdir(parents=True, exist_ok=True)
    self.settings_cache_file.write_text(json.dumps(settings, indent=2))

def _load_cached_settings(self) -> dict:
    """Load cached settings (offline fallback)."""
    if self.settings_cache_file.exists():
        return json.loads(self.settings_cache_file.read_text())
    # Return defaults if no cache exists
    return {
        "monitoring_mode": "camera_only",
        "enabled_gadgets": ["phone"],
        "vision_provider": "gemini",
        "blocklist": {"quick_blocks": {}, "categories": {}, "custom_urls": [], "custom_apps": []}
    }
```

### Converting Cloud Blocklist to Local Blocklist Object

The engine needs a `Blocklist` object (from `screen/blocklist.py`). The sync client converts the Supabase data:

> **IMPORTANT: Verify the actual `Blocklist` constructor before implementing.** The field names and types below are based on analysis of the `Blocklist` dataclass in `screen/blocklist.py`, but the actual constructor signature may differ. Check the dataclass definition for exact field names, required vs optional fields, and whether it expects `set` vs `list` types. The `BlocklistManager.load()` method in `screen/blocklist.py` shows how `Blocklist` objects are currently constructed from local JSON.

```python
from screen.blocklist import Blocklist

def cloud_settings_to_blocklist(settings: dict) -> Blocklist:
    """Convert cloud settings dict to a Blocklist object for the engine."""
    bl = settings.get("blocklist", {})
    # NOTE: Verify these field names match the actual Blocklist dataclass
    return Blocklist(
        quick_blocks=bl.get("quick_blocks", {}),
        categories=bl.get("categories", {}),
        custom_urls=set(bl.get("custom_urls", [])),
        custom_apps=set(bl.get("custom_apps", [])),
        enabled_gadgets=set(settings.get("enabled_gadgets", ["phone"]))
    )
```

---

## Step 6: Add Session Upload

After a session ends, push summary data to Supabase:

```python
# In sync/supabase_client.py

def upload_session(self, session_data: dict) -> bool:
    """
    Upload completed session data to Supabase.
    Called after session ends and report is generated.
    
    Args:
        session_data: {
            "session_name": "BrainDock Monday 2.45PM",
            "start_time": "2024-01-15T14:45:00+11:00",
            "end_time": "2024-01-15T15:30:00+11:00",
            "duration_seconds": 2700,
            "active_seconds": 2400,
            "paused_seconds": 300,
            "monitoring_mode": "camera_only",
            "summary_stats": { ... },
            "events": [ ... ]  # Optional: individual events
        }
    
    Returns:
        True if upload succeeded, False otherwise.
    """
    try:
        user = self.client.auth.get_user()
        if not user:
            logger.warning("Not authenticated, skipping session upload")
            return False
        
        # Insert session
        session_result = self.client.table("sessions").insert({
            "user_id": user.user.id,
            "session_name": session_data.get("session_name"),
            "start_time": session_data["start_time"],
            "end_time": session_data["end_time"],
            "duration_seconds": session_data["duration_seconds"],
            "active_seconds": session_data["active_seconds"],
            "paused_seconds": session_data.get("paused_seconds", 0),
            "monitoring_mode": session_data["monitoring_mode"],
            "summary_stats": session_data.get("summary_stats", {}),
        }).execute()
        
        session_id = session_result.data[0]["id"]
        
        # Optional: upload individual events for detailed web dashboard
        events = session_data.get("events", [])
        if events:
            event_rows = [
                {
                    "session_id": session_id,
                    "event_type": e["type"],
                    "start_time": e["start_time"],
                    "end_time": e.get("end_time"),
                    "duration_seconds": e.get("duration"),
                }
                for e in events
            ]
            self.client.table("session_events").insert(event_rows).execute()
        
        logger.info(f"Session uploaded to cloud: {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload session: {e}")
        # Session data is still saved locally (JSON) — no data loss
        return False
```

---

## Step 7: Offline Fallback Behavior

Different monitoring modes handle offline differently:

| Mode | Internet Down | Behavior |
|------|--------------|----------|
| **Camera Only** | Vision API unreachable | Gentle notification: "Camera detection paused — no internet." Session continues but no events are logged. When internet returns, detection resumes automatically. |
| **Screen Only** | Doesn't need internet | Works completely normally. Screen monitoring is 100% local (window title + blocklist matching). |
| **Both** | Vision API unreachable | Falls back silently to screen-only mode. Notification: "Camera paused — continuing with screen monitoring." When internet returns, camera detection resumes. |

**Settings:** Use cached `settings_cache.json` if Supabase is unreachable at session start. The cache is always updated on successful fetch.

**Session upload:** If upload fails after session end, the session data remains in local JSON (existing `tracking/session.py` behavior). A background retry can be attempted next time the app is online. Data is never lost.

### Implementation in Engine

```python
# In core/engine.py, inside _detection_loop:

try:
    detection_state = detector.get_detection_state(frame)
except Exception as api_error:
    # Vision API failed (likely no internet)
    if not self._api_offline_notified:
        self._notify_status_change("offline", "Camera paused — no internet")
        self._api_offline_notified = True
    
    # In "both" mode, let screen monitoring continue
    if self.monitoring_mode == config.MODE_BOTH:
        time.sleep(5)  # Back off, retry periodically
        continue
    else:
        # Camera-only mode — wait and retry
        time.sleep(10)
        continue
```

---

## Step 8: Update Entry Point and Config

### main.py Changes

```python
# main.py — Updated entry point for menu bar app
# Replace GUI launch with menu bar launch

def main():
    """Main entry point."""
    # Single instance check (keep existing)
    check_single_instance()
    
    # Parse arguments
    if "--cli" in sys.argv:
        main_cli()  # Keep CLI mode
    else:
        main_menubar()  # Replace main_gui()

def main_menubar():
    """Launch the menu bar application."""
    from menubar import run_menubar_app
    run_menubar_app()
```

### config.py Changes

**Add:**
```python
# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
```

**Remove (no longer needed):**
```python
# These are no longer used — payments handled via website/Supabase
# STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_PRICE_ID, etc.
# PRODUCT_PRICE_DISPLAY, STRIPE_REQUIRE_TERMS
```

**Keep unchanged:**
Everything related to Vision APIs, camera, detection, events, paths, usage limits.

---

## Step 9: Update Dependencies

### requirements.txt Changes

**Add:**
```
rumps>=0.4.0; sys_platform == 'darwin'
pystray>=0.19.0; sys_platform == 'win32'
supabase>=2.0.0
```

**Remove:**
```
customtkinter>=5.2.0
stripe>=7.0.0
```

**Keep all others unchanged** (opencv-python, openai, google-generativeai, reportlab, etc.)

### Full Updated requirements.txt

```
opencv-python>=4.8.0
openai>=1.0.0
google-generativeai>=0.8.0
reportlab>=4.0.0
python-dotenv>=1.0.0
pillow>=10.0.0
supabase>=2.0.0
rumps>=0.4.0; sys_platform == 'darwin'
pystray>=0.19.0; sys_platform == 'win32'
pyobjc-framework-Cocoa>=10.0; sys_platform == 'darwin'
pyobjc-framework-AVFoundation>=10.0; sys_platform == 'darwin'
pywinauto>=0.6.8; sys_platform == 'win32'
comtypes>=1.2.0; sys_platform == 'win32'
tzdata; sys_platform == 'win32'
```

---

## Step 10: Update Build Scripts

### macOS Build (build/build_macos.sh)

Key changes:
- Set `LSUIElement = true` in Info.plist (no Dock icon)
- Remove CustomTkinter from PyInstaller bundle
- Add rumps to PyInstaller bundle
- Smaller bundle size expected (~50-70MB vs ~99MB)
- Update entitlements.plist if needed for menu bar app

### PyInstaller Spec (build/braindock.spec)

- Remove `gui/` from data files
- Add `menubar/` and `core/` to data files
- Remove CustomTkinter hidden imports
- Add rumps/pystray hidden imports
- Update icon for menu bar (template icon)

### Windows Build (build/build_windows.ps1 and installer.iss)

Key changes:
- Remove CustomTkinter from PyInstaller bundle
- Add pystray to PyInstaller bundle (hidden import: `pystray._win32`)
- Use `--noconsole` flag (no terminal window when running)
- Bundle `.ico` format icon for Windows system tray (pystray prefers `.ico` on Windows)
- Smaller bundle size expected
- Update Inno Setup script (`installer.iss`) to:
  - Install to `C:\Program Files\BrainDock\` (or user choice)
  - Create Start Menu shortcut
  - Optionally add to Windows startup (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` registry key) so the tray icon runs on login
  - Register uninstaller
- Ensure `instance_lock.py` works correctly on Windows (file locking behavior differs from macOS)

---

## Step 11: Clean Up — Delete Old GUI Files

**ONLY do this after the menu bar app is fully working and tested.**

Files to delete:
- `gui/app.py` (6,681 lines)
- `gui/ui_components.py` (1,396 lines)
- `gui/payment_screen.py` (1,456 lines)
- `gui/font_loader.py` (248 lines)
- `gui/__init__.py`
- `licensing/stripe_integration.py` (860 lines)

Files to keep in `licensing/`:
- `licensing/license_manager.py` — Update to check Supabase instead of local-only (or keep as fallback)

**Consider keeping the `gui/` folder in a separate git branch for reference** before deleting.

---

## New File Structure After Migration

```
braindock/
├── main.py                    # Entry point (launches menu bar)
├── config.py                  # Configuration (updated: add Supabase, remove Stripe/GUI)
├── instance_lock.py           # Single-instance enforcement (unchanged)
│
├── core/                      # NEW — Extracted business logic
│   ├── __init__.py
│   ├── engine.py              # Session orchestration (extracted from gui/app.py)
│   └── permissions.py         # Platform permission checks (extracted from gui/app.py)
│
├── menubar/                   # NEW — Menu bar application
│   ├── __init__.py            # Platform detection + launcher
│   ├── macos_app.py           # rumps-based macOS menu bar
│   └── windows_app.py         # pystray-based Windows system tray
│
├── sync/                      # NEW — Cloud sync
│   ├── __init__.py
│   └── supabase_client.py     # Auth, settings fetch, session upload
│
├── camera/                    # UNCHANGED
├── tracking/                  # UNCHANGED
├── screen/                    # UNCHANGED
├── reporting/                 # UNCHANGED
├── licensing/                 # MODIFIED (license_manager.py updated for Supabase)
├── data/                      # UNCHANGED
├── assets/                    # UPDATED (add menu bar icons)
├── build/                     # UPDATED (build scripts for menu bar app)
└── tests/                     # UPDATED (add engine tests)
```

---

## Testing Checklist

### Engine Tests (core/engine.py)

- [ ] `engine.start_session()` returns success with camera mode (camera accessible)
- [ ] `engine.start_session()` returns appropriate error with camera denied
- [ ] `engine.start_session()` returns appropriate error with no API key
- [ ] `engine.stop_session()` returns session data with statistics
- [ ] `engine.pause_session()` / `engine.resume_session()` work correctly
- [ ] Detection loop runs and calls `on_status_change` callback
- [ ] Screen detection loop runs in screen-only mode
- [ ] Both modes run simultaneously with correct priority resolution
- [ ] Usage limiter still works (2-hour limit)
- [ ] PDF report generates correctly

### Menu Bar Tests

- [ ] macOS: Menu bar icon appears when app launches
- [ ] macOS: No Dock icon appears (LSUIElement)
- [ ] macOS: Opening from Applications activates menu bar (no window)
- [ ] Windows: System tray icon appears
- [ ] Click icon shows dropdown menu with all items
- [ ] Start Session → status updates, timer runs
- [ ] Stop Session → report generates, status returns to idle
- [ ] Pause/Resume → works correctly
- [ ] Mode toggle → changes monitoring mode
- [ ] "Open Dashboard" opens browser to website
- [ ] "Download Last Report" generates/opens PDF
- [ ] Quit properly cleans up (stops session if running)

### Auth Tests

- [ ] First launch shows "Log In" prompt
- [ ] Login via browser flow → tokens stored
- [ ] Subsequent launches → auto-authenticated
- [ ] Subscription check → correctly identifies paid/unpaid user
- [ ] Logout → clears tokens, shows "Log In" again
- [ ] Device registration → device appears in Supabase

### Sync Tests

- [ ] Settings fetched from Supabase on session start
- [ ] Blocklist from cloud applied correctly to screen monitoring
- [ ] Session data uploaded to Supabase after session ends
- [ ] Offline: cached settings used when Supabase unreachable
- [ ] Offline: session data saved locally when upload fails

### Existing Functionality Tests

- [ ] All existing unit tests pass (`python -m unittest tests.test_session`, etc.)
- [ ] Camera detection quality unchanged
- [ ] Screen monitoring accuracy unchanged
- [ ] PDF report format and content unchanged
- [ ] Statistics math still adds up (present + away + gadget + screen + paused = total)

---

## Rollback Plan

Since this phase modifies the desktop app significantly:

1. **Git branch.** Work on a dedicated `feature/menubar-migration` branch. The `main` branch retains the full GUI app.
2. **Keep gui/ in branch history.** Don't delete GUI files until menu bar is proven. Even after deletion, they're recoverable from git history.
3. **Parallel testing.** During development, both the old GUI app and new menu bar app can coexist (different entry points). Test the menu bar app while the GUI still works.
4. **Gradual rollout.** Consider shipping the menu bar version as a beta alongside the existing GUI version. Users can choose which to download.
