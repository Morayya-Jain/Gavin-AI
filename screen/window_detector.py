"""
Window and browser URL detection for screen monitoring.

Provides cross-platform detection of:
- Active window title
- Google Chrome URL (Phase 1 - other browsers to be added later)

Uses platform-native APIs:
- macOS: AppleScript via subprocess
- Windows: pywin32 + ctypes
"""

import sys
import subprocess
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    """Information about the currently active window."""
    app_name: str
    window_title: str
    url: Optional[str] = None  # Only populated for supported browsers
    is_browser: bool = False


class WindowDetector:
    """
    Cross-platform detector for active window information.
    
    Detects the currently focused application, window title,
    and browser URL (Chrome only in Phase 1).
    """
    
    def __init__(self):
        """Initialize the window detector for the current platform."""
        self.platform = sys.platform
        self._permission_checked = False
        self._has_permission = False
        
    def get_active_window(self) -> Optional[WindowInfo]:
        """
        Get information about the currently active window.
        
        Returns:
            WindowInfo with app name, title, and URL (if browser),
            or None if detection fails.
        """
        try:
            if self.platform == "darwin":
                return self._get_active_window_macos()
            elif self.platform == "win32":
                return self._get_active_window_windows()
            else:
                logger.warning(f"Unsupported platform: {self.platform}")
                return None
        except PermissionError as e:
            logger.warning(f"Permission denied getting active window: {e}")
            self._has_permission = False
            return None
        except subprocess.TimeoutExpired as e:
            logger.warning(f"Timeout getting active window: {e}")
            return None
        except OSError as e:
            logger.error(f"OS error getting active window: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting active window: {e}")
            return None
    
    def _get_active_window_macos(self) -> Optional[WindowInfo]:
        """
        Get active window info on macOS using AppleScript.
        
        Returns:
            WindowInfo or None if detection fails.
        """
        # Get active application name and window title
        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            try
                set windowTitle to name of front window of frontApp
            on error
                set windowTitle to ""
            end try
            return appName & "|||" & windowTitle
        end tell
        '''
        
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode != 0:
                # Log the error details for debugging
                logger.warning(f"AppleScript failed with code {result.returncode}: {result.stderr.strip()}")
                
                # Permission error - need Accessibility permission
                stderr_lower = result.stderr.lower()
                if "not allowed" in stderr_lower or "assistive" in stderr_lower or "-10827" in stderr_lower:
                    logger.warning("Accessibility permission required for screen monitoring")
                    self._has_permission = False
                else:
                    # Other error - still treat as permission issue for safety
                    logger.warning("AppleScript failed - treating as permission issue")
                    self._has_permission = False
                return None
            
            self._has_permission = True
            output = result.stdout.strip()
            
            if "|||" in output:
                app_name, window_title = output.split("|||", 1)
            else:
                app_name = output
                window_title = ""
            
            # Check if it's Chrome and get URL
            url = None
            is_browser = app_name.lower() in ["google chrome", "chrome"]
            
            if is_browser:
                url = self._get_chrome_url_macos()
            
            return WindowInfo(
                app_name=app_name,
                window_title=window_title,
                url=url,
                is_browser=is_browser
            )
            
        except subprocess.TimeoutExpired:
            logger.warning("AppleScript timed out getting window info")
            return None
        except Exception as e:
            logger.error(f"Error in macOS window detection: {e}")
            return None
    
    def _get_chrome_url_macos(self) -> Optional[str]:
        """
        Get the current URL from Google Chrome on macOS.
        
        Returns:
            Current tab URL or None if Chrome is not running or error occurs.
        """
        script = '''
        tell application "Google Chrome"
            if (count of windows) > 0 then
                return URL of active tab of front window
            else
                return ""
            end if
        end tell
        '''
        
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                url = result.stdout.strip()
                return url if url else None
            return None
            
        except subprocess.TimeoutExpired:
            logger.warning("AppleScript timed out getting Chrome URL")
            return None
        except Exception as e:
            logger.debug(f"Could not get Chrome URL: {e}")
            return None
    
    def _get_active_window_windows(self) -> Optional[WindowInfo]:
        """
        Get active window info on Windows using pywin32/ctypes.
        
        Returns:
            WindowInfo or None if detection fails.
        """
        try:
            import ctypes
            from ctypes import wintypes
            
            # Get foreground window handle
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            
            if not hwnd:
                return None
            
            # Get window title
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            window_title = buffer.value
            
            # Get process name
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            app_name = self._get_process_name_windows(pid.value)
            
            # Check if it's a Chromium-based browser (Chrome, Edge, etc.)
            # The UI Automation method works for all Chromium browsers
            app_name_lower = app_name.lower()
            is_browser = any(b in app_name_lower for b in ["chrome", "msedge", "edge"])
            url = None
            
            if is_browser:
                url = self._get_chrome_url_windows(hwnd)
            
            return WindowInfo(
                app_name=app_name,
                window_title=window_title,
                url=url,
                is_browser=is_browser
            )
            
        except ImportError:
            logger.warning("pywin32 or ctypes not available on Windows")
            return None
        except Exception as e:
            logger.error(f"Error in Windows window detection: {e}")
            return None
    
    def _get_process_name_windows(self, pid: int) -> str:
        """
        Get process name from PID on Windows.
        
        Args:
            pid: Process ID
            
        Returns:
            Process name or "Unknown"
        """
        try:
            import ctypes
            from ctypes import wintypes
            
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            
            if handle:
                try:
                    buffer = ctypes.create_unicode_buffer(260)
                    size = wintypes.DWORD(260)
                    
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                        path = buffer.value
                        return path.split("\\")[-1].replace(".exe", "")
                finally:
                    kernel32.CloseHandle(handle)
            
            return "Unknown"
            
        except Exception as e:
            logger.debug(f"Could not get process name: {e}")
            return "Unknown"
    
    def _get_chrome_url_windows(self, hwnd: int) -> Optional[str]:
        """
        Get Chrome/Edge URL on Windows using UI Automation.
        
        Uses pywinauto to access the browser's address bar element,
        equivalent to AppleScript on macOS.
        
        Args:
            hwnd: Window handle
            
        Returns:
            URL or None
        """
        try:
            from pywinauto import Application
            
            # Connect to the browser window using UIA backend
            app = Application(backend='uia')
            app.connect(handle=hwnd)
            
            dlg = app.top_window()
            
            # Chrome and Edge address bar has title "Address and search bar"
            try:
                address_bar = dlg.child_window(
                    title="Address and search bar",
                    control_type="Edit"
                )
                url = address_bar.get_value()
                if url:
                    logger.debug(f"Browser URL via UI Automation: {url}")
                    return url
            except Exception as e:
                logger.debug(f"Could not find address bar with primary method: {e}")
            
            # Fallback: Try alternative control names used by some Chromium versions
            try:
                # Some versions use different names
                for title in ["Address and search bar", "Address bar", "Omnibox"]:
                    try:
                        address_bar = dlg.child_window(
                            title=title,
                            control_type="Edit"
                        )
                        url = address_bar.get_value()
                        if url:
                            logger.debug(f"Browser URL via fallback ({title}): {url}")
                            return url
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Fallback address bar search failed: {e}")
            
            return None
            
        except ImportError:
            logger.warning("pywinauto not available - Chrome URL detection disabled on Windows")
            return None
        except Exception as e:
            logger.debug(f"Could not get browser URL via UI Automation: {e}")
            return None
    
    def check_permission(self) -> bool:
        """
        Check if the app has necessary permissions for screen monitoring.
        
        Returns:
            True if permissions are granted, False otherwise.
        """
        if self._permission_checked:
            logger.debug(f"Using cached permission result: {self._has_permission}")
            return self._has_permission
        
        # Try to get window info - this will set _has_permission
        logger.debug("Testing permission by getting active window...")
        window_info = self.get_active_window()
        self._permission_checked = True
        
        if window_info:
            logger.debug(f"Permission check passed, got window: {window_info.app_name}")
        else:
            logger.warning("Permission check failed - could not get active window")
        
        return self._has_permission
    
    def get_permission_instructions(self) -> str:
        """
        Get instructions for enabling screen monitoring permissions.
        
        Returns:
            Platform-specific instructions string.
        """
        if self.platform == "darwin":
            return (
                "Screen monitoring requires TWO permissions:\n\n"
                "1. ACCESSIBILITY permission:\n"
                "   • System Settings → Privacy & Security → Accessibility\n"
                "   • Add BrainDock and enable the checkbox\n\n"
                "2. AUTOMATION permission (System Events):\n"
                "   • System Settings → Privacy & Security → Automation\n"
                "   • Enable 'System Events' under BrainDock\n"
                "   • (This prompt may appear automatically)\n\n"
                "After enabling, RESTART BrainDock."
            )
        elif self.platform == "win32":
            return (
                "Screen monitoring should work automatically on Windows.\n"
                "If you're having issues, try running as Administrator."
            )
        else:
            return f"Screen monitoring is not supported on {self.platform}"


def get_screen_state(blocklist: 'Blocklist') -> Dict[str, Any]:
    """
    Get the current screen state and check for distractions.
    
    This is the main entry point for screen monitoring, similar to
    get_event_type() for camera monitoring.
    
    Args:
        blocklist: Blocklist instance to check against
        
    Returns:
        Dictionary with:
        - is_distracted: bool
        - distraction_source: str or None (URL or app name that matched)
        - app_name: str
        - window_title: str
        - url: str or None
    """
    detector = WindowDetector()
    window_info = detector.get_active_window()
    
    if window_info is None:
        return {
            "is_distracted": False,
            "distraction_source": None,
            "app_name": "Unknown",
            "window_title": "",
            "url": None,
            "error": "Could not detect active window"
        }
    
    # Check if current window/URL matches blocklist
    is_distracted, match_source = blocklist.check_distraction(
        url=window_info.url,
        window_title=window_info.window_title,
        app_name=window_info.app_name
    )
    
    return {
        "is_distracted": is_distracted,
        "distraction_source": match_source,
        "app_name": window_info.app_name,
        "window_title": window_info.window_title,
        "url": window_info.url
    }


def get_screen_state_with_ai_fallback(
    blocklist: 'Blocklist',
    use_ai_fallback: bool = False
) -> Dict[str, Any]:
    """
    Get screen state with optional AI Vision fallback.
    
    This is an enhanced version that can use AI to analyze screenshots
    when local blocklist matching is inconclusive. AI is only called
    as a last resort to minimize API costs.
    
    Args:
        blocklist: Blocklist instance to check against
        use_ai_fallback: If True and local matching is inconclusive, use AI
        
    Returns:
        Dictionary with screen state (same as get_screen_state)
    """
    # First, try local detection
    result = get_screen_state(blocklist)
    
    # If distraction was detected locally, no need for AI
    if result.get("is_distracted"):
        return result
    
    # If AI fallback is disabled, return local result
    if not use_ai_fallback:
        return result
    
    # AI fallback: Take screenshot and analyze
    # Only do this for truly ambiguous cases where we have a browser open
    # but couldn't determine if it's distracting
    window_info = result.get("app_name", "")
    
    # Only use AI for browsers where we couldn't get the URL
    is_browser = any(b in window_info.lower() for b in ["chrome", "safari", "firefox", "edge", "arc"])
    has_no_url = result.get("url") is None
    
    if not (is_browser and has_no_url):
        return result
    
    # Try AI analysis
    try:
        ai_result = _analyze_screen_with_ai()
        if ai_result:
            result["is_distracted"] = ai_result.get("is_distracted", False)
            result["distraction_source"] = ai_result.get("category", None)
            result["ai_analyzed"] = True
    except Exception as e:
        logger.warning(f"AI fallback failed: {e}")
        result["ai_error"] = str(e)
    
    return result


def _analyze_screen_with_ai() -> Optional[Dict[str, Any]]:
    """
    Analyze the current screen using OpenAI Vision API.
    
    Takes a screenshot and sends it to the AI to determine if the
    user is on a distracting site/app. Only returns category, no
    confidential information is extracted.
    
    Returns:
        Dictionary with is_distracted and category, or None if failed
    """
    try:
        import config
        from openai import OpenAI
        
        # Check if API key is available
        if not config.OPENAI_API_KEY:
            logger.warning("No OpenAI API key for AI fallback")
            return None
        
        # Take screenshot
        screenshot_data = _capture_screenshot()
        if not screenshot_data:
            return None
        
        # Call OpenAI Vision API
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        
        response = client.chat.completions.create(
            model=config.OPENAI_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a focus detection assistant. Analyze the screenshot "
                        "and determine if the user is on a distracting website or app. "
                        "Distracting sites include: social media, video streaming, gaming, "
                        "news/entertainment. Respond with JSON only: "
                        '{"is_distracted": true/false, "category": "category name or null"}'
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Is this screen showing a distracting site/app?"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{screenshot_data}",
                                "detail": "low"  # Use low detail to reduce cost
                            }
                        }
                    ]
                }
            ],
            max_tokens=100
        )
        
        # Parse response
        content = response.choices[0].message.content.strip()
        
        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        
        import json
        result = json.loads(content)
        
        logger.info(f"AI screen analysis: {result}")
        return result
        
    except Exception as e:
        logger.error(f"AI screen analysis failed: {e}")
        return None


def _capture_screenshot() -> Optional[str]:
    """
    Capture a screenshot and return as base64-encoded JPEG.
    
    Uses a lower resolution for cost efficiency.
    Imports PIL Image internally as it may not be available on all systems.
    
    Returns:
        Base64-encoded image data, or None if capture failed
    """
    try:
        import base64
        from io import BytesIO
        
        if sys.platform == "darwin":
            # macOS: Use screencapture command
            import subprocess
            import tempfile
            import os
            
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                    temp_path = f.name
                
                # Capture screen to temp file (lower quality for cost)
                subprocess.run(
                    ["screencapture", "-x", "-t", "jpg", "-C", temp_path],
                    capture_output=True,
                    timeout=5
                )
                
                with open(temp_path, "rb") as f:
                    image_data = f.read()
                
                # Resize for cost efficiency
                from PIL import Image
                img = Image.open(BytesIO(image_data))
                img.thumbnail((800, 600), Image.Resampling.LANCZOS)
                
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=70)
                
                return base64.b64encode(buffer.getvalue()).decode("utf-8")
            finally:
                # Always clean up temp file, even on errors
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to clean up temp file: {cleanup_error}")
            
        elif sys.platform == "win32":
            # Windows: Use PIL ImageGrab
            from PIL import ImageGrab, Image
            
            screenshot = ImageGrab.grab()
            screenshot.thumbnail((800, 600), Image.Resampling.LANCZOS)
            
            buffer = BytesIO()
            screenshot.save(buffer, format="JPEG", quality=70)
            
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        else:
            logger.warning(f"Screenshot not supported on {sys.platform}")
            return None
            
    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")
        return None
