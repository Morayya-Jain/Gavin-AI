"""
SessionEngine — Core detection orchestration engine for BrainDock.

Extracted from gui/app.py. Contains ALL business logic for session
management, camera/screen detection loops, alert tracking, and
report generation.

This module has ZERO UI dependencies — no tkinter, no customtkinter,
no GUI imports whatsoever. The menu bar app (or any future UI) calls
engine methods and receives updates via callbacks.

Callbacks:
    on_status_change(status: str, text: str)
    on_session_ended(report_path: Optional[Path])
    on_error(error_type: str, message: str)
    on_alert(level: int, message: str)
"""

import sys
import json
import time
import threading
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Callable

import config
from camera.capture import CameraCapture, CameraFailureType
from camera import get_event_type, create_vision_detector
from tracking.session import Session
from tracking.analytics import compute_statistics
from tracking.usage_limiter import get_usage_limiter, UsageLimiter
from tracking.daily_stats import get_daily_stats_tracker, DailyStatsTracker
from reporting.pdf_report import generate_report
from screen.window_detector import WindowDetector, get_screen_state, get_screen_state_with_ai_fallback
from screen.blocklist import Blocklist, BlocklistManager

from core.permissions import (
    check_macos_camera_permission,
    check_macos_accessibility_permission,
    check_windows_screen_permission,
)

logger = logging.getLogger(__name__)

# Path to persist the last generated report path across app restarts
_LAST_REPORT_FILE = config.USER_DATA_DIR / "last_report.json"


class SessionEngine:
    """
    Core session management engine.

    Handles:
    - Session lifecycle (start, stop, pause, resume)
    - Camera detection loop (background thread)
    - Screen detection loop (background thread)
    - Priority resolution (camera + screen combined mode)
    - Unfocused alert tracking and sound playback
    - Usage limit enforcement
    - Report generation
    - Settings management (blocklist, gadget preferences)

    The engine does NOT run its own timer. The menu bar app polls
    get_status() on its own schedule (rumps @timer or pystray thread).
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        """Initialise the session engine with default state."""
        # Session state
        self.session: Optional[Session] = None
        self.is_running: bool = False
        self.should_stop: threading.Event = threading.Event()
        self.detection_thread: Optional[threading.Thread] = None
        self.screen_detection_thread: Optional[threading.Thread] = None
        self.current_status: str = "idle"
        self.session_start_time: Optional[datetime] = None
        self.session_started: bool = False

        # Monitoring mode
        self.monitoring_mode: str = config.MODE_CAMERA_ONLY
        self.blocklist_manager: BlocklistManager = BlocklistManager(config.SCREEN_SETTINGS_FILE)
        self.blocklist: Blocklist = self.blocklist_manager.load()
        self.use_ai_fallback: bool = config.SCREEN_AI_FALLBACK_ENABLED

        # Pause state
        self.is_paused: bool = False
        self.pause_start_time: Optional[datetime] = None
        self.total_paused_seconds: float = 0.0
        self.frozen_active_seconds: int = 0

        # Distraction counters
        self.gadget_detection_count: int = 0
        self.screen_distraction_count: int = 0

        # Unfocused alert tracking
        self.unfocused_start_time: Optional[float] = None
        self.alerts_played: int = 0

        # Usage limit tracking
        self.usage_limiter: UsageLimiter = get_usage_limiter()
        self.is_locked: bool = False

        # Daily stats
        self.daily_stats: DailyStatsTracker = get_daily_stats_tracker()

        # Shared detection state for priority resolution ("both" mode)
        self._camera_state: Optional[Dict] = None
        self._screen_state: Optional[Dict] = None
        self._state_lock: threading.Lock = threading.Lock()

        # Hybrid temporal filtering for gadget detection
        self._consecutive_borderline_count: int = 0
        self._last_gadget_confidence: float = 0.0

        # Camera pre-warm flag (Windows DirectShow optimisation)
        self._camera_warmed: bool = False

        # ---- Callbacks (set by the menu bar / tray app) ----
        self.on_status_change: Optional[Callable[[str, str], None]] = None
        self.on_session_ended: Optional[Callable[[Optional[Path]], None]] = None
        self.on_error: Optional[Callable[[str, str], None]] = None
        self.on_alert: Optional[Callable[[int, str], None]] = None

        # Validate audio files on init
        self._validate_audio_files()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_sync_client(self, client) -> None:
        """Set the Supabase sync client on the usage limiter for credit fetch/record."""
        self.usage_limiter.set_sync_client(client)

    def set_monitoring_mode(self, mode: str) -> None:
        """
        Set the monitoring mode.

        Args:
            mode: One of config.MODE_CAMERA_ONLY, MODE_SCREEN_ONLY, MODE_BOTH.
        """
        if mode in (config.MODE_CAMERA_ONLY, config.MODE_SCREEN_ONLY, config.MODE_BOTH):
            self.monitoring_mode = mode
            logger.info(f"Monitoring mode set to: {mode}")
        else:
            logger.warning(f"Invalid monitoring mode ignored: {mode}")

    def set_blocklist(self, blocklist: Blocklist) -> None:
        """
        Set blocklist configuration (from Supabase or local cache).

        Args:
            blocklist: A Blocklist instance for screen monitoring.
        """
        self.blocklist = blocklist
        logger.info("Blocklist updated on engine")

    def start_session(self) -> Dict:
        """
        Start a new focus session.

        Returns:
            {"success": bool, "error": str | None, "error_type": str | None}
            error_type values: "time_exhausted", "already_running",
                "no_api_key", "camera_denied", "camera_restricted",
                "screen_permission"
        """
        # Already running?
        if self.is_running:
            return {"success": False, "error": "Session already running", "error_type": "already_running"}

        # Sync credits from cloud so we have latest balance (e.g. after buying hours on website)
        self.usage_limiter.sync_with_cloud()

        # Usage limit check (credits / hours remaining)
        if self.is_locked:
            return {
                "success": False,
                "error": "No hours remaining. Purchase more at thebraindock.com",
                "error_type": "time_exhausted",
            }
        if self.usage_limiter.is_time_exhausted():
            self.is_locked = True
            return {
                "success": False,
                "error": "No hours remaining. Purchase more at thebraindock.com",
                "error_type": "time_exhausted",
            }

        # API key checks (camera modes only)
        needs_camera = self.monitoring_mode in (config.MODE_CAMERA_ONLY, config.MODE_BOTH)
        if needs_camera:
            if config.VISION_PROVIDER == "gemini":
                if not config.GEMINI_API_KEY:
                    return {
                        "success": False,
                        "error": "Gemini API key not found. Set GEMINI_API_KEY in your .env file.",
                        "error_type": "no_api_key",
                    }
            else:
                if not config.OPENAI_API_KEY:
                    return {
                        "success": False,
                        "error": "OpenAI API key not found. Set OPENAI_API_KEY in your .env file.",
                        "error_type": "no_api_key",
                    }

            # macOS camera permission pre-check
            if sys.platform == "darwin":
                perm = check_macos_camera_permission()
                if perm == "denied":
                    return {
                        "success": False,
                        "error": "Camera permission denied. Grant access in System Settings > Privacy & Security > Camera.",
                        "error_type": "camera_denied",
                    }
                if perm == "restricted":
                    return {
                        "success": False,
                        "error": "Camera access is restricted on this device (parental controls or MDM).",
                        "error_type": "camera_restricted",
                    }

        # Screen permission pre-check
        needs_screen = self.monitoring_mode in (config.MODE_SCREEN_ONLY, config.MODE_BOTH)
        if needs_screen:
            if sys.platform == "darwin":
                if not check_macos_accessibility_permission():
                    return {
                        "success": False,
                        "error": (
                            "Screen monitoring requires Accessibility and Automation permissions.\n"
                            "Enable both in System Settings > Privacy & Security, then restart BrainDock."
                        ),
                        "error_type": "screen_permission",
                    }
            elif sys.platform == "win32":
                if not check_windows_screen_permission():
                    return {
                        "success": False,
                        "error": (
                            "Screen monitoring cannot access window information.\n"
                            "Try running BrainDock as Administrator."
                        ),
                        "error_type": "screen_permission",
                    }

        # --- All checks passed — initialise session ---
        self.session = Session()
        self.session_started = False
        self.session_start_time = None
        self.is_running = True
        self.should_stop.clear()

        # Reset pause state
        self.is_paused = False
        self.pause_start_time = None
        self.total_paused_seconds = 0.0
        self.frozen_active_seconds = 0

        # Reset alert tracking
        self.unfocused_start_time = None
        self.alerts_played = 0

        # Reset distraction counters
        self.gadget_detection_count = 0
        self.screen_distraction_count = 0

        # Reset shared detection state
        with self._state_lock:
            self._camera_state = None
            self._screen_state = None

        # Reset temporal filtering
        self._consecutive_borderline_count = 0
        self._last_gadget_confidence = 0.0

        # Notify UI of bootup
        self._notify_status_change("booting", "Booting Up...")

        # Spawn detection thread(s)
        if self.monitoring_mode == config.MODE_CAMERA_ONLY:
            self.detection_thread = threading.Thread(target=self._detection_loop, daemon=True)
            self.detection_thread.start()

        elif self.monitoring_mode == config.MODE_SCREEN_ONLY:
            self.detection_thread = threading.Thread(target=self._screen_detection_loop, daemon=True)
            self.detection_thread.start()

        else:  # MODE_BOTH
            self.detection_thread = threading.Thread(target=self._detection_loop, daemon=True)
            self.detection_thread.start()
            self.screen_detection_thread = threading.Thread(target=self._screen_detection_loop, daemon=True)
            self.screen_detection_thread.start()

        logger.info(f"Session started (mode: {self.monitoring_mode})")
        return {"success": True, "error": None, "error_type": None}

    def stop_session(self) -> Dict:
        """
        Stop the current session and generate report.

        Returns:
            {"success": bool, "report_path": Optional[Path], "session_data": Optional[dict]}
        """
        if not self.is_running:
            return {"success": False, "report_path": None, "session_data": None}

        stop_time = datetime.now()

        # Finalise pause duration if paused
        if self.is_paused and self.pause_start_time:
            pause_duration = (stop_time - self.pause_start_time).total_seconds()
            self.total_paused_seconds += pause_duration
            self.is_paused = False
            self.pause_start_time = None

        # Signal threads to stop
        self.should_stop.set()
        self.is_running = False

        # Wait for threads
        self._join_threads()

        # End session and record usage
        session_data = None
        if self.session and self.session_started and self.session_start_time:
            total_elapsed = (stop_time - self.session_start_time).total_seconds()
            active_duration = max(1, int(total_elapsed - self.total_paused_seconds))
            self.usage_limiter.record_usage(active_duration)
            self.session.end(stop_time)
            self.usage_limiter.end_session()

            # Prepare session data for cloud upload
            session_data = self._build_session_data(active_duration)

        # Generate report
        report_path = self._generate_report()

        # Notify UI
        self._notify_status_change("idle", "Ready to Start")
        if self.on_session_ended:
            self.on_session_ended(report_path)

        logger.info("Session stopped")
        return {"success": True, "report_path": report_path, "session_data": session_data}

    def pause_session(self) -> None:
        """
        Pause the current session instantly.

        Freezes the timer, logs a pause event, and stops API calls.
        """
        if not self.is_running or self.is_paused:
            return

        self.is_paused = True
        self.pause_start_time = datetime.now()

        # Freeze active seconds at exact moment (int truncation = floor)
        if self.session_start_time:
            elapsed = (self.pause_start_time - self.session_start_time).total_seconds()
            self.frozen_active_seconds = int(elapsed - self.total_paused_seconds)

        # Log pause event
        if self.session and self.session_started:
            self.session.log_event(config.EVENT_PAUSED)

        # Reset alert tracking (shouldn't alert while paused)
        self.unfocused_start_time = None
        self.alerts_played = 0

        self._notify_status_change("paused", "Paused")
        logger.info("Session paused")

    def resume_session(self) -> None:
        """Resume a paused session."""
        if not self.is_running or not self.is_paused:
            return

        resume_time = datetime.now()

        if self.pause_start_time:
            self.total_paused_seconds += (resume_time - self.pause_start_time).total_seconds()

        self.is_paused = False
        self.pause_start_time = None
        self.frozen_active_seconds = 0

        if self.session and self.session_started:
            self.session.log_event(config.EVENT_PRESENT)

        self._notify_status_change("focused", "Focussed")
        logger.info("Session resumed")

    def get_status(self) -> Dict:
        """
        Get current engine status (polled by the menu bar / tray app).

        Returns:
            dict with keys: is_running, is_paused, status, elapsed_seconds,
            monitoring_mode, is_locked.
        """
        elapsed = 0
        if self.is_running and self.session_start_time:
            if self.is_paused:
                elapsed = self.frozen_active_seconds
            else:
                total = (datetime.now() - self.session_start_time).total_seconds()
                elapsed = int(total - self.total_paused_seconds)

        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "status": self.current_status,
            "elapsed_seconds": elapsed,
            "monitoring_mode": self.monitoring_mode,
            "is_locked": self.is_locked,
        }

    def check_time_remaining(self) -> Dict:
        """
        Check usage time remaining.

        Returns:
            {"remaining_seconds": int, "is_exhausted": bool, "extensions_used": int}
        """
        remaining = self.usage_limiter.get_remaining_seconds()

        # Subtract current session active time
        if self.is_running and self.session_start_time and not self.is_paused:
            total = (datetime.now() - self.session_start_time).total_seconds()
            active = int(total - self.total_paused_seconds)
            remaining -= active

        return {
            "remaining_seconds": max(0, remaining),
            "is_exhausted": remaining <= 0,
            "extensions_used": getattr(self.usage_limiter, "extensions_used", 0),
        }

    def get_last_report_path(self) -> Optional[Path]:
        """
        Get the path to the most recently generated report.

        Persisted across app restarts via a local JSON file.

        Returns:
            Path to the PDF, or None if no report exists or file was deleted.
        """
        try:
            if _LAST_REPORT_FILE.exists():
                data = json.loads(_LAST_REPORT_FILE.read_text())
                path = Path(data.get("path", ""))
                if path.exists():
                    return path
        except Exception as e:
            logger.debug(f"Could not read last report path: {e}")
        return None

    def prewarm_camera(self) -> None:
        """
        Pre-warm camera in a background thread (Windows DirectShow optimisation).

        On Windows, the first camera open takes 5-10 seconds due to DirectShow
        initialisation. Pre-warming eliminates this delay when the user starts.
        """
        if self._camera_warmed or sys.platform != "win32":
            return

        def _prewarm() -> None:
            try:
                logger.debug("Pre-warming camera (background)...")
                import cv2
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if cap.isOpened():
                    ret, _ = cap.read()
                    cap.release()
                    self._camera_warmed = True
                    logger.debug(f"Camera pre-warmed successfully (frame read: {ret})")
                else:
                    cap.release()
                    logger.debug("Camera pre-warm: could not open camera")
            except Exception as e:
                logger.debug(f"Camera pre-warm failed (non-critical): {e}")

        threading.Thread(target=_prewarm, daemon=True).start()

    def cleanup(self) -> None:
        """Clean up resources. Call before app quit."""
        if self.is_running:
            self.stop_session()
        logger.info("Engine cleanup complete")

    # ------------------------------------------------------------------
    # Detection loops (run in background threads)
    # ------------------------------------------------------------------

    def _detection_loop(self) -> None:
        """
        Main camera detection loop.

        Captures frames and analyses them via Vision API. Handles temporal
        filtering, alert tracking, and priority resolution.
        """
        try:
            detector = create_vision_detector(enabled_gadgets=self.blocklist.enabled_gadgets)

            with CameraCapture() as camera:
                if not camera.is_opened:
                    self._handle_camera_error(camera.failure_type, camera.permission_error)
                    return

                last_detection_time = time.time()

                for frame in camera.frame_iterator():
                    if self.should_stop.is_set():
                        break

                    # Skip detection when paused
                    if self.is_paused:
                        time.sleep(0.1)
                        continue

                    current_time = time.time()
                    time_since_detection = current_time - last_detection_time

                    # Check for time exhaustion
                    self._check_time_exhaustion()

                    if time_since_detection >= (1.0 / config.DETECTION_FPS):
                        detection_state = detector.get_detection_state(frame)

                        # Re-check stop/pause after API call (takes 2-3 seconds)
                        if self.should_stop.is_set():
                            break
                        if self.is_paused:
                            continue

                        # Start session on first successful detection
                        if not self.session_started:
                            self.session.start()
                            self.session_start_time = self.session.start_time
                            self.session_started = True
                            logger.info("First detection complete — session timer started")

                        # Apply hybrid temporal filtering for gadget detection
                        detection_state = self._apply_gadget_filtering(detection_state)

                        # Store camera state for priority resolution
                        with self._state_lock:
                            self._camera_state = detection_state

                        raw_camera_event = get_event_type(detection_state)

                        # Determine final event type
                        if self.monitoring_mode == config.MODE_BOTH:
                            event_type = self._resolve_priority_status()
                        else:
                            event_type = raw_camera_event

                        # Track gadget detection count
                        if self.session and raw_camera_event == config.EVENT_GADGET_SUSPECTED:
                            if self.session.current_state != config.EVENT_GADGET_SUSPECTED:
                                self.gadget_detection_count += 1

                        # Handle unfocused alerts
                        self._track_unfocused_alerts(event_type, current_time)

                        # Log event
                        if self.session:
                            self.session.log_event(event_type)

                        # Update status via callback
                        self._update_detection_status(event_type)

                        last_detection_time = current_time

                    time.sleep(0.05)

        except (KeyboardInterrupt, SystemExit):
            logger.info("Detection loop interrupted by shutdown signal")
        except Exception as e:
            logger.error(f"Detection loop error: {e}")
            self._notify_error("detection_error", str(e))

    def _screen_detection_loop(self) -> None:
        """
        Screen monitoring detection loop.

        Checks active window and browser URL against the blocklist.
        No AI API calls — purely local pattern matching.
        """
        try:
            logger.info("Screen detection loop starting...")
            window_detector = WindowDetector()

            if not window_detector.check_permission():
                logger.warning("Screen monitoring permission check failed")
                instructions = window_detector.get_permission_instructions()
                self._notify_error("screen_permission", instructions)
                # Reset state since detection can't run
                self.is_running = False
                self._notify_status_change("idle", "Ready to Start")
                return

            logger.info("Screen monitoring permission granted, starting detection loop")
            last_screen_check = time.time()

            # Screen-only mode: start session immediately
            if self.monitoring_mode == config.MODE_SCREEN_ONLY and not self.session_started:
                self.session.start()
                self.session_start_time = self.session.start_time
                self.session_started = True
                logger.info("Screen-only mode — session timer started")
                self._notify_status_change("focused", "Focussed")

            while not self.should_stop.is_set():
                if self.is_paused:
                    time.sleep(0.1)
                    continue

                current_time = time.time()
                if current_time - last_screen_check >= config.SCREEN_CHECK_INTERVAL:
                    # Get screen state
                    if self.use_ai_fallback:
                        screen_state = get_screen_state_with_ai_fallback(
                            self.blocklist, use_ai_fallback=True
                        )
                    else:
                        screen_state = get_screen_state(self.blocklist)

                    if self.should_stop.is_set():
                        break
                    if self.is_paused:
                        continue

                    # Store for priority resolution
                    with self._state_lock:
                        self._screen_state = screen_state

                    is_screen_distracted = screen_state.get("is_distracted", False)

                    # Track distraction count
                    if is_screen_distracted and self.session and self.session_started:
                        if self.session.current_state != config.EVENT_SCREEN_DISTRACTION:
                            self.screen_distraction_count += 1

                    # Determine event type
                    if self.monitoring_mode == config.MODE_BOTH:
                        event_type = self._resolve_priority_status()
                        if event_type == config.EVENT_SCREEN_DISTRACTION:
                            source = screen_state.get("distraction_source", "Unknown")
                            label = self._get_distraction_label(source)
                            self._notify_status_change("screen", label)

                    elif self.monitoring_mode == config.MODE_SCREEN_ONLY:
                        if is_screen_distracted:
                            source = screen_state.get("distraction_source", "Unknown")
                            label = self._get_distraction_label(source)

                            if self.session and self.session_started:
                                self.session.log_event(config.EVENT_SCREEN_DISTRACTION)

                            self._notify_status_change("screen", label)
                            self._track_unfocused_alerts(config.EVENT_SCREEN_DISTRACTION, current_time)
                        else:
                            if self.session and self.session_started:
                                self.session.log_event(config.EVENT_PRESENT)
                            self._notify_status_change("focused", "Focussed")

                            # Reset alert tracking
                            if self.unfocused_start_time is not None:
                                logger.debug("Screen refocussed — resetting alert tracking")
                            self.unfocused_start_time = None
                            self.alerts_played = 0

                    last_screen_check = current_time

                time.sleep(0.1)

        except (KeyboardInterrupt, SystemExit):
            logger.info("Screen detection loop interrupted by shutdown signal")
        except Exception as e:
            logger.error(f"Screen detection loop error: {e}")
            self._notify_error("detection_error", f"Screen monitoring: {e}")

    # ------------------------------------------------------------------
    # Priority resolution and status helpers
    # ------------------------------------------------------------------

    def _resolve_priority_status(self) -> str:
        """
        Resolve current status using priority rules (for "both" mode).

        Priority (highest first):
        1. Paused   2. Away   3. Screen distraction
        4. Gadget   5. Focussed (default)

        Returns:
            Event type constant.
        """
        with self._state_lock:
            if self.is_paused:
                return config.EVENT_PAUSED

            if self._camera_state:
                camera_event = get_event_type(self._camera_state)
                if camera_event == config.EVENT_AWAY:
                    return config.EVENT_AWAY

            if self._screen_state and self._screen_state.get("is_distracted"):
                return config.EVENT_SCREEN_DISTRACTION

            if self._camera_state:
                camera_event = get_event_type(self._camera_state)
                if camera_event == config.EVENT_GADGET_SUSPECTED:
                    return config.EVENT_GADGET_SUSPECTED

            return config.EVENT_PRESENT

    def _update_detection_status(self, event_type: str) -> None:
        """
        Map event type to a human-readable status and notify via callback.

        Args:
            event_type: Detection event type constant.
        """
        status_map = {
            config.EVENT_PRESENT: ("focused", "Focussed"),
            config.EVENT_AWAY: ("away", "Away from Desk"),
            config.EVENT_GADGET_SUSPECTED: ("gadget", "On another gadget"),
            config.EVENT_SCREEN_DISTRACTION: ("screen", "Screen distraction"),
        }
        status, text = status_map.get(event_type, ("idle", "Unknown"))
        self._notify_status_change(status, text)

    @staticmethod
    def _get_distraction_label(distraction_source: str) -> str:
        """
        Format a distraction source for display.

        Args:
            distraction_source: Pattern that triggered the distraction.

        Returns:
            Label like "Website: example.com" or "App: Steam".
        """
        website_indicators = (
            '.com', '.org', '.net', '.edu', '.gov', '.io', '.co', '.tv',
            '.gg', '.app', '.dev', '.me', '.info', '.biz', '.xyz', '://',
        )
        source = distraction_source or "Unknown"
        source_lower = source.lower()

        is_website = any(ind in source_lower for ind in website_indicators)
        prefix = "Website" if is_website else "App"
        display = source if is_website else source.title()

        if len(display) > 18:
            return f"{prefix}: {display[:18]}..."
        return f"{prefix}: {display}"

    # ------------------------------------------------------------------
    # Gadget temporal filtering
    # ------------------------------------------------------------------

    def _apply_gadget_filtering(self, detection_state: Dict) -> Dict:
        """
        Apply hybrid temporal filtering for gadget detection.

        High confidence (>0.75): immediate.
        Borderline (0.5-0.75): require 2 consecutive detections.

        Args:
            detection_state: Raw detection result from Vision API.

        Returns:
            Possibly-modified detection_state with gadget_suspected suppressed.
        """
        gadget_confidence = detection_state.get("gadget_confidence", 0.0)
        raw_gadget = detection_state.get("gadget_suspected", False)

        if raw_gadget:
            if gadget_confidence > 0.75:
                self._consecutive_borderline_count = 0
                self._last_gadget_confidence = gadget_confidence
                logger.debug(f"High confidence gadget detection: {gadget_confidence:.2f}")
            else:
                self._consecutive_borderline_count += 1
                self._last_gadget_confidence = gadget_confidence
                if self._consecutive_borderline_count >= 2:
                    logger.debug(
                        f"Borderline gadget confirmed after {self._consecutive_borderline_count} consecutive detections"
                    )
                else:
                    detection_state = dict(detection_state)
                    detection_state["gadget_suspected"] = False
                    logger.debug(
                        f"Borderline gadget ({gadget_confidence:.2f}) — waiting "
                        f"({self._consecutive_borderline_count}/2)"
                    )
        else:
            if self._consecutive_borderline_count > 0:
                logger.debug("No gadget detected — resetting borderline counter")
            self._consecutive_borderline_count = 0
            self._last_gadget_confidence = 0.0

        return detection_state

    # ------------------------------------------------------------------
    # Alert tracking and sound playback
    # ------------------------------------------------------------------

    def _track_unfocused_alerts(self, event_type: str, current_time: float) -> None:
        """
        Track unfocused duration and trigger escalating alerts.

        Args:
            event_type: Current resolved event type.
            current_time: time.time() timestamp.
        """
        is_unfocused = event_type in (
            config.EVENT_AWAY,
            config.EVENT_GADGET_SUSPECTED,
            config.EVENT_SCREEN_DISTRACTION,
        )

        if is_unfocused:
            if self.unfocused_start_time is None:
                self.unfocused_start_time = current_time
                self.alerts_played = 0
                logger.debug("Started tracking unfocussed time")

            unfocused_duration = current_time - self.unfocused_start_time
            alert_times = config.UNFOCUSED_ALERT_TIMES

            if (self.alerts_played < len(alert_times) and
                    unfocused_duration >= alert_times[self.alerts_played]):
                self._play_unfocused_alert()
                self.alerts_played += 1
        else:
            if self.unfocused_start_time is not None:
                logger.debug("User refocussed — resetting alert tracking")
            self.unfocused_start_time = None
            self.alerts_played = 0

    def _play_unfocused_alert(self) -> None:
        """
        Play the BrainDock alert sound and notify via callback.

        Cross-platform: macOS (afplay), Windows (winsound), Linux (mpg123/ffplay).
        """
        alert_index = self.alerts_played
        badge_text, message = config.UNFOCUSED_ALERT_MESSAGES[alert_index]

        # Play sound in background
        def _play_sound() -> None:
            if sys.platform == "win32":
                sound_file = config.BUNDLED_DATA_DIR / "braindock_alert_sound.wav"
            else:
                sound_file = config.BUNDLED_DATA_DIR / "braindock_alert_sound.mp3"

            if not sound_file.exists():
                logger.warning(f"Alert sound file not found: {sound_file}")
                return

            try:
                if sys.platform == "darwin":
                    subprocess.Popen(
                        ["afplay", str(sound_file)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    )
                elif sys.platform == "win32":
                    try:
                        import winsound
                        winsound.PlaySound(
                            str(sound_file),
                            winsound.SND_FILENAME | winsound.SND_ASYNC,
                        )
                    except Exception as e:
                        logger.debug(f"winsound failed, using PowerShell: {e}")
                        subprocess.Popen(
                            ["powershell", "-c",
                             f'(New-Object Media.SoundPlayer "{sound_file}").PlaySync()'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                else:
                    try:
                        subprocess.Popen(
                            ["mpg123", "-q", str(sound_file)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    except FileNotFoundError:
                        subprocess.Popen(
                            ["ffplay", "-nodisp", "-autoexit", str(sound_file)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
            except Exception as e:
                logger.warning(f"Sound playback error: {e}")

        threading.Thread(target=_play_sound, daemon=True).start()

        # Notify UI via callback
        if self.on_alert:
            self.on_alert(alert_index, message)

        logger.info(f"Unfocussed alert #{alert_index + 1} played")

    # ------------------------------------------------------------------
    # Time exhaustion handling
    # ------------------------------------------------------------------

    def _check_time_exhaustion(self) -> None:
        """
        Check if usage time has been exhausted during a running session.

        If exhausted, triggers session stop and lockout.
        """
        if not self.is_running or self.is_paused or self.is_locked:
            return
        if not self.session_start_time:
            return

        base_remaining = self.usage_limiter.get_remaining_seconds()
        total = (datetime.now() - self.session_start_time).total_seconds()
        active = int(total - self.total_paused_seconds)
        actual_remaining = base_remaining - active

        if actual_remaining <= 0:
            logger.warning("Usage time exhausted during session")
            self._handle_time_exhausted()

    def _handle_time_exhausted(self) -> None:
        """
        Handle time exhaustion: stop session, generate report, set locked.
        """
        stop_time = datetime.now()

        if self.is_running:
            if self.is_paused and self.pause_start_time:
                self.total_paused_seconds += (stop_time - self.pause_start_time).total_seconds()
                self.is_paused = False
                self.pause_start_time = None

            self.should_stop.set()
            self.is_running = False
            self._join_threads()

            if self.session and self.session_started and self.session_start_time:
                total_elapsed = (stop_time - self.session_start_time).total_seconds()
                active_duration = max(1, int(total_elapsed - self.total_paused_seconds))
                self.usage_limiter.record_usage(active_duration)
                self.session.end(stop_time)
                self.usage_limiter.end_session()

            report_path = self._generate_report()
            logger.info("Session stopped due to time exhaustion — report generated")

            if self.on_session_ended:
                self.on_session_ended(report_path)

        self.is_locked = True
        self._notify_status_change("locked", "No Hours Remaining")

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_report(self) -> Optional[Path]:
        """
        Generate a PDF report for the completed session.

        Returns:
            Path to the generated PDF, or None if generation failed.
        """
        if not self.session or not self.session_started:
            logger.info("No session data — skipping report generation")
            return None

        try:
            stats = compute_statistics(
                self.session.events,
                self.session.get_duration(),
            )
            report_path = generate_report(
                stats,
                self.session.session_id,
                self.session.start_time,
                self.session.end_time,
            )

            # Persist for "Download Last Report"
            self._save_last_report_path(report_path)

            logger.info(f"Report generated: {report_path}")
            return report_path

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            self._notify_error("report_error", str(e))
            return None

    def _save_last_report_path(self, path: Path) -> None:
        """Persist the last report path for retrieval after restart."""
        try:
            _LAST_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _LAST_REPORT_FILE.write_text(json.dumps({"path": str(path)}))
        except Exception as e:
            logger.debug(f"Could not save last report path: {e}")

    # ------------------------------------------------------------------
    # Session data builder (for cloud upload)
    # ------------------------------------------------------------------

    def _build_session_data(self, active_duration: int) -> Dict:
        """
        Build session summary dict for Supabase upload.

        Args:
            active_duration: Active time in seconds (excluding pauses).

        Returns:
            dict suitable for sync/supabase_client.upload_session().
        """
        if not self.session:
            return {}

        stats = compute_statistics(
            self.session.events,
            self.session.get_duration(),
        )

        events_list = []
        for evt in self.session.events:
            events_list.append({
                "type": evt.get("type", ""),
                "start_time": evt.get("start_time", ""),
                "end_time": evt.get("end_time", ""),
                "duration": evt.get("duration", 0),
            })

        return {
            "session_name": self.session.session_id,
            "start_time": self.session.start_time.isoformat() if self.session.start_time else "",
            "end_time": self.session.end_time.isoformat() if self.session.end_time else "",
            "duration_seconds": self.session.get_duration(),
            "active_seconds": active_duration,
            "paused_seconds": int(self.total_paused_seconds),
            "monitoring_mode": self.monitoring_mode,
            "summary_stats": stats,
            "events": events_list,
        }

    # ------------------------------------------------------------------
    # Camera error handling
    # ------------------------------------------------------------------

    def _handle_camera_error(
        self,
        failure_type: "CameraFailureType" = CameraFailureType.UNKNOWN,
        failure_message: Optional[str] = None,
    ) -> None:
        """
        Handle camera open failure by notifying via error callback.

        Args:
            failure_type: Type of camera failure.
            failure_message: Detailed error message.
        """
        self.is_running = False
        self._notify_status_change("idle", "Ready to Start")

        error_messages = {
            CameraFailureType.NO_HARDWARE: (
                "camera_no_hardware",
                failure_message or "No camera detected. Please connect a webcam and restart BrainDock.",
            ),
            CameraFailureType.IN_USE: (
                "camera_in_use",
                failure_message or "Camera is being used by another application. Close other camera apps and try again.",
            ),
            CameraFailureType.PERMISSION_RESTRICTED: (
                "camera_restricted",
                failure_message or "Camera access is restricted on this device (enterprise policy or parental controls).",
            ),
            CameraFailureType.PERMISSION_DENIED: (
                "camera_denied",
                failure_message or "Camera permission denied. Grant access in system settings.",
            ),
        }

        error_type, msg = error_messages.get(
            failure_type,
            ("camera_error", failure_message or "Camera access failed. Check system settings."),
        )
        self._notify_error(error_type, msg)

    # ------------------------------------------------------------------
    # Callback helpers
    # ------------------------------------------------------------------

    def _notify_status_change(self, status: str, text: str) -> None:
        """Thread-safe status change notification."""
        self.current_status = status
        if self.on_status_change:
            try:
                self.on_status_change(status, text)
            except Exception as e:
                logger.debug(f"on_status_change callback error: {e}")

    def _notify_error(self, error_type: str, message: str) -> None:
        """Notify of an error via callback."""
        if self.on_error:
            try:
                self.on_error(error_type, message)
            except Exception as e:
                logger.debug(f"on_error callback error: {e}")

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    def _join_threads(self) -> None:
        """Wait for detection threads to finish and clean up references."""
        if self.detection_thread and self.detection_thread.is_alive():
            self.detection_thread.join(timeout=2.0)
            if self.detection_thread.is_alive():
                logger.warning("Detection thread did not stop within timeout")
        self.detection_thread = None

        if self.screen_detection_thread and self.screen_detection_thread.is_alive():
            self.screen_detection_thread.join(timeout=2.0)
            if self.screen_detection_thread.is_alive():
                logger.warning("Screen detection thread did not stop within timeout")
        self.screen_detection_thread = None

    # ------------------------------------------------------------------
    # Audio file validation
    # ------------------------------------------------------------------

    def _validate_audio_files(self) -> None:
        """Validate that required audio files exist for alert sounds."""
        if sys.platform == "win32":
            sound_file = config.BUNDLED_DATA_DIR / "braindock_alert_sound.wav"
            expected_format = "WAV"
        else:
            sound_file = config.BUNDLED_DATA_DIR / "braindock_alert_sound.mp3"
            expected_format = "MP3"

        if not sound_file.exists():
            logger.warning(
                f"Alert sound file not found: {sound_file}. "
                f"Audio alerts will be disabled. Expected {expected_format} for {sys.platform}."
            )
        else:
            logger.debug(f"Audio file validated: {sound_file}")

        # Cross-check for bundled builds
        if getattr(sys, 'frozen', False):
            wav = config.BUNDLED_DATA_DIR / "braindock_alert_sound.wav"
            mp3 = config.BUNDLED_DATA_DIR / "braindock_alert_sound.mp3"
            if not wav.exists():
                logger.warning(f"WAV audio file missing from bundle: {wav}")
            if not mp3.exists():
                logger.warning(f"MP3 audio file missing from bundle: {mp3}")
