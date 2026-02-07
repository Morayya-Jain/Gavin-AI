"""
Tests for core/engine.py — verifies the SessionEngine works
independently of any UI framework.
"""

import sys
import time
import unittest
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.engine import SessionEngine

logger = logging.getLogger(__name__)


class TestSessionEngineInit(unittest.TestCase):
    """Test engine initialisation and default state."""

    def test_init_defaults(self):
        """Engine initialises with sane defaults."""
        engine = SessionEngine()
        self.assertFalse(engine.is_running)
        self.assertFalse(engine.is_paused)
        self.assertFalse(engine.is_locked)
        self.assertEqual(engine.monitoring_mode, config.MODE_CAMERA_ONLY)
        self.assertIsNone(engine.session)
        self.assertIsNone(engine.on_status_change)
        self.assertIsNone(engine.on_session_ended)
        self.assertIsNone(engine.on_error)
        self.assertIsNone(engine.on_alert)

    def test_get_status_idle(self):
        """get_status() returns correct idle state."""
        engine = SessionEngine()
        status = engine.get_status()
        self.assertFalse(status["is_running"])
        self.assertFalse(status["is_paused"])
        self.assertEqual(status["elapsed_seconds"], 0)
        self.assertEqual(status["status"], "idle")

    def test_set_monitoring_mode(self):
        """set_monitoring_mode() accepts valid modes and rejects invalid."""
        engine = SessionEngine()
        engine.set_monitoring_mode(config.MODE_SCREEN_ONLY)
        self.assertEqual(engine.monitoring_mode, config.MODE_SCREEN_ONLY)

        engine.set_monitoring_mode(config.MODE_BOTH)
        self.assertEqual(engine.monitoring_mode, config.MODE_BOTH)

        # Invalid mode is ignored
        engine.set_monitoring_mode("invalid_mode")
        self.assertEqual(engine.monitoring_mode, config.MODE_BOTH)


class TestSessionEngineStartStop(unittest.TestCase):
    """Test session start/stop lifecycle without actual camera/API."""

    def test_double_start_returns_error(self):
        """Starting when already running returns error."""
        engine = SessionEngine()
        engine.is_running = True
        result = engine.start_session()
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "already_running")

    def test_locked_start_returns_error(self):
        """Starting when locked returns time_exhausted error."""
        engine = SessionEngine()
        engine.is_locked = True
        result = engine.start_session()
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "time_exhausted")

    def test_stop_when_not_running(self):
        """Stopping when not running returns gracefully."""
        engine = SessionEngine()
        result = engine.stop_session()
        self.assertFalse(result["success"])
        self.assertIsNone(result["report_path"])

    @patch("core.engine.create_vision_detector")
    @patch("core.engine.CameraCapture")
    def test_start_stop_camera_mode(self, mock_camera_cls, mock_detector_cls):
        """
        Start and stop in camera mode (mocked camera/detector).
        Verifies the lifecycle without real hardware.
        """
        # Mock camera to open successfully then return no frames
        mock_camera = MagicMock()
        mock_camera.is_opened = True
        mock_camera.frame_iterator.return_value = iter([])
        mock_camera.__enter__ = MagicMock(return_value=mock_camera)
        mock_camera.__exit__ = MagicMock(return_value=False)
        mock_camera_cls.return_value = mock_camera

        mock_detector = MagicMock()
        mock_detector_cls.return_value = mock_detector

        engine = SessionEngine()
        engine.set_monitoring_mode(config.MODE_CAMERA_ONLY)

        # Track callbacks
        statuses = []
        engine.on_status_change = lambda s, t: statuses.append((s, t))

        result = engine.start_session()
        self.assertTrue(result["success"])
        self.assertTrue(engine.is_running)

        # Give detection thread time to start and finish (empty iterator)
        time.sleep(0.5)

        result = engine.stop_session()
        self.assertTrue(result["success"])
        self.assertFalse(engine.is_running)

    def test_pause_resume_without_running(self):
        """Pause/resume when not running does nothing."""
        engine = SessionEngine()
        engine.pause_session()
        self.assertFalse(engine.is_paused)
        engine.resume_session()
        self.assertFalse(engine.is_paused)


class TestSessionEnginePauseResume(unittest.TestCase):
    """Test pause/resume logic."""

    def test_pause_sets_state(self):
        """Pausing sets is_paused and freezes active seconds."""
        engine = SessionEngine()
        engine.is_running = True
        engine.session_started = True
        engine.session = MagicMock()
        engine.session_start_time = engine.session.start_time = (
            __import__("datetime").datetime.now()
        )

        engine.pause_session()
        self.assertTrue(engine.is_paused)
        self.assertIsNotNone(engine.pause_start_time)

    def test_resume_clears_state(self):
        """Resuming clears pause state and accumulates paused time."""
        engine = SessionEngine()
        engine.is_running = True
        engine.is_paused = True
        engine.session_started = True
        engine.session = MagicMock()
        engine.pause_start_time = __import__("datetime").datetime.now()

        engine.resume_session()
        self.assertFalse(engine.is_paused)
        self.assertIsNone(engine.pause_start_time)
        self.assertGreaterEqual(engine.total_paused_seconds, 0)


class TestPriorityResolution(unittest.TestCase):
    """Test the _resolve_priority_status method."""

    def test_away_beats_screen_distraction(self):
        """Away has higher priority than screen distraction."""
        engine = SessionEngine()
        # get_event_type uses "present" and "at_desk" keys
        engine._camera_state = {
            "present": False, "at_desk": False,
            "gadget_suspected": False,
        }
        engine._screen_state = {"is_distracted": True}
        result = engine._resolve_priority_status()
        self.assertEqual(result, config.EVENT_AWAY)

    def test_screen_beats_gadget(self):
        """Screen distraction beats gadget when person is present."""
        engine = SessionEngine()
        engine._camera_state = {
            "present": True, "at_desk": True,
            "gadget_suspected": True,
        }
        engine._screen_state = {"is_distracted": True}
        result = engine._resolve_priority_status()
        self.assertEqual(result, config.EVENT_SCREEN_DISTRACTION)

    def test_focused_default(self):
        """Default is focused when no distractions."""
        engine = SessionEngine()
        engine._camera_state = {
            "present": True, "at_desk": True,
            "gadget_suspected": False,
        }
        engine._screen_state = {"is_distracted": False}
        result = engine._resolve_priority_status()
        self.assertEqual(result, config.EVENT_PRESENT)

    def test_paused_highest_priority(self):
        """Paused overrides everything."""
        engine = SessionEngine()
        engine.is_paused = True
        engine._camera_state = {
            "present": False, "at_desk": False,
            "gadget_suspected": True,
        }
        engine._screen_state = {"is_distracted": True}
        result = engine._resolve_priority_status()
        self.assertEqual(result, config.EVENT_PAUSED)


class TestGetDistractionLabel(unittest.TestCase):
    """Test the _get_distraction_label static method."""

    def test_website_label(self):
        """Domains are labelled as Website."""
        label = SessionEngine._get_distraction_label("instagram.com")
        self.assertTrue(label.startswith("Website:"))

    def test_app_label(self):
        """Non-domains are labelled as App."""
        label = SessionEngine._get_distraction_label("steam")
        self.assertTrue(label.startswith("App:"))

    def test_long_source_truncated(self):
        """Sources longer than 18 chars are truncated."""
        label = SessionEngine._get_distraction_label("a" * 30 + ".com")
        self.assertIn("...", label)


class TestLastReportPath(unittest.TestCase):
    """Test last report path persistence."""

    def test_no_report_returns_none(self):
        """get_last_report_path returns None when no report saved."""
        engine = SessionEngine()
        # The actual result depends on file state, but should not crash
        result = engine.get_last_report_path()
        self.assertTrue(result is None or isinstance(result, Path))


class TestCallbackPattern(unittest.TestCase):
    """Test that callbacks are invoked correctly."""

    def test_status_change_callback(self):
        """_notify_status_change calls the callback."""
        engine = SessionEngine()
        calls = []
        engine.on_status_change = lambda s, t: calls.append((s, t))
        engine._notify_status_change("focused", "Focussed")
        self.assertEqual(calls, [("focused", "Focussed")])
        self.assertEqual(engine.current_status, "focused")

    def test_error_callback(self):
        """_notify_error calls the callback."""
        engine = SessionEngine()
        calls = []
        engine.on_error = lambda t, m: calls.append((t, m))
        engine._notify_error("test_error", "Something broke")
        self.assertEqual(calls, [("test_error", "Something broke")])

    def test_callback_exception_swallowed(self):
        """Broken callbacks don't crash the engine."""
        engine = SessionEngine()
        engine.on_status_change = lambda s, t: 1 / 0  # Raises ZeroDivisionError
        # Should not raise
        engine._notify_status_change("idle", "Ready")
        self.assertEqual(engine.current_status, "idle")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
