"""
Platform-specific permission checks for BrainDock.

Extracted from gui/app.py — these functions check camera and
screen monitoring permissions on macOS and Windows. They have
zero UI dependencies (no tkinter, no messagebox).
"""

import sys
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# macOS Camera
# ---------------------------------------------------------------------------

def check_macos_camera_permission() -> str:
    """
    Check macOS camera authorization status via AVFoundation.

    Returns:
        One of: "authorized", "denied", "not_determined", "restricted", "unknown"
    """
    if sys.platform != "darwin":
        return "authorized"

    try:
        import objc

        objc.loadBundle(
            'AVFoundation',
            bundle_path='/System/Library/Frameworks/AVFoundation.framework',
            module_globals=globals()
        )

        AVCaptureDevice = objc.lookUpClass('AVCaptureDevice')
        AVMediaTypeVideo = "vide"

        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo)

        status_map = {
            0: "not_determined",
            1: "restricted",
            2: "denied",
            3: "authorized",
        }
        return status_map.get(status, "unknown")

    except ImportError:
        logger.debug("PyObjC not available, cannot check camera permission status")
        return "unknown"
    except Exception as e:
        logger.debug(f"Error checking camera permission: {e}")
        return "unknown"


def open_macos_camera_settings() -> None:
    """Open macOS System Settings to Privacy & Security > Camera."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"],
            check=True, timeout=10,
        )
    except Exception as e:
        logger.error(f"Failed to open System Settings: {e}")
        try:
            subprocess.run(["open", "-a", "System Settings"], check=True, timeout=10)
        except Exception:
            subprocess.run(["open", "-a", "System Preferences"], check=True, timeout=10)


# ---------------------------------------------------------------------------
# macOS Accessibility / Automation
# ---------------------------------------------------------------------------

def check_macos_accessibility_permission() -> bool:
    """
    Check if the app has Automation permission for screen monitoring on macOS.

    Tests by running a simple AppleScript that queries System Events.

    Returns:
        True if permission is granted, False otherwise.
    """
    if sys.platform != "darwin":
        return True
    return _test_accessibility_with_applescript()


def _test_accessibility_with_applescript() -> bool:
    """
    Test Accessibility/Automation permission by running a simple AppleScript.

    Returns:
        True if the AppleScript succeeds, False otherwise.
    """
    try:
        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            return name of frontApp
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )

        if result.returncode == 0:
            logger.debug(f"AppleScript test succeeded: {result.stdout.strip()}")
            return True

        stderr = result.stderr.lower()
        permission_indicators = [
            "not allowed", "assistive", "-10827", "-1743", "-1728",
            "not permitted", "permission denied", "not authorized",
        ]
        is_permission_error = any(ind in stderr for ind in permission_indicators)

        if is_permission_error:
            logger.warning(f"Permission denied for AppleScript: {result.stderr.strip()}")
        else:
            logger.warning(f"AppleScript test failed: {result.stderr.strip()}")
        return False

    except subprocess.TimeoutExpired:
        logger.warning("AppleScript test timed out — may indicate permission dialog is waiting")
        return False
    except Exception as e:
        logger.warning(f"AppleScript test error: {e}")
        return False


def open_macos_accessibility_settings() -> None:
    """Open macOS System Settings to Privacy & Security > Accessibility."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=True, timeout=10,
        )
    except Exception as e:
        logger.error(f"Failed to open System Settings: {e}")
        try:
            subprocess.run(["open", "-a", "System Settings"], check=True, timeout=10)
        except Exception:
            subprocess.run(["open", "-a", "System Preferences"], check=True, timeout=10)


# ---------------------------------------------------------------------------
# Windows Camera
# ---------------------------------------------------------------------------

def check_windows_camera_permission() -> str:
    """
    Check Windows camera permission by attempting a quick capture test.

    Returns:
        One of: "authorized", "denied", "unknown"
    """
    if sys.platform != "win32":
        return "authorized"

    cap = None
    try:
        import cv2

        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = None
            logger.debug("Windows camera check: VideoCapture failed to open")
            return "denied"

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ret, frame = cap.read()
        cap.release()
        cap = None

        if ret and frame is not None:
            logger.debug("Windows camera check: Camera access authorized")
            return "authorized"
        else:
            logger.debug("Windows camera check: Could not read frame — likely permission denied")
            return "denied"

    except Exception as e:
        logger.debug(f"Windows camera check error: {e}")
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        return "unknown"


def open_windows_camera_settings() -> None:
    """Open Windows Settings to Privacy & Security > Camera."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["cmd", "/c", "start", "ms-settings:privacy-webcam"],
            check=True, shell=False,
        )
        logger.info("Opened Windows Camera privacy settings")
    except Exception as e:
        logger.error(f"Failed to open Windows Settings: {e}")
        try:
            import os
            os.startfile("ms-settings:privacy-webcam")
        except Exception as fallback_error:
            logger.error(f"Fallback also failed: {fallback_error}")


# ---------------------------------------------------------------------------
# Windows Screen Monitoring
# ---------------------------------------------------------------------------

def check_windows_screen_permission() -> bool:
    """
    Check if screen monitoring works on Windows by testing window access.

    Returns:
        True if screen monitoring works, False otherwise.
    """
    if sys.platform != "win32":
        return True
    return _test_windows_screen_access()


def _test_windows_screen_access() -> bool:
    """
    Test Windows screen access by attempting to get the foreground window.

    Returns:
        True if window detection succeeds, False otherwise.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            logger.warning("Windows screen test: No foreground window found")
            return False

        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        result = user32.GetWindowTextW(hwnd, buffer, length + 1)

        if result == 0 and length > 0:
            logger.warning("Windows screen test: Could not get window title")
            return False

        pid = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if thread_id == 0:
            logger.warning("Windows screen test: Could not get process ID")
            return False

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)

        if handle:
            try:
                proc_buffer = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(260)
                if kernel32.QueryFullProcessImageNameW(handle, 0, proc_buffer, ctypes.byref(size)):
                    process_name = proc_buffer.value.split("\\")[-1]
                    logger.debug(f"Windows screen test passed: window='{buffer.value}', process='{process_name}'")
                    return True
                else:
                    logger.debug(f"Windows screen test: Got window '{buffer.value}' but not process name")
                    return True
            finally:
                kernel32.CloseHandle(handle)
        else:
            logger.debug(f"Windows screen test: Got window title '{buffer.value}' (process access limited)")
            return True

    except Exception as e:
        logger.warning(f"Windows screen test error: {e}")
        return False
