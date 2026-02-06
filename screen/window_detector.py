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
    page_title: Optional[str] = None  # Extracted page title from browser window


# Comprehensive list of browser process names (lowercase for matching)
# Maps process name patterns to browser display names
BROWSER_PROCESS_NAMES = {
    # Chromium-based
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "edge": "Microsoft Edge",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "arc": "Arc",
    "chromium": "Chromium",
    # Firefox-based
    "firefox": "Firefox",
    "waterfox": "Waterfox",
    "librewolf": "LibreWolf",
    # Safari
    "safari": "Safari",
    # Other
    "thorium": "Thorium",
    "floorp": "Floorp",
    "zen": "Zen Browser",
}

# Window title suffixes used by browsers (for extraction)
BROWSER_TITLE_SUFFIXES = [
    " - Google Chrome",
    " - Chrome",
    " — Mozilla Firefox",
    " - Firefox",
    " - Microsoft Edge",
    " - Edge",
    " - Brave",
    " - Opera",
    " - Vivaldi",
    " - Arc",
    " - Safari",
    " - Chromium",
    " — Firefox",  # Different dash character
    " – Google Chrome",  # En dash
    " – Firefox",
    " – Microsoft Edge",
]


class WindowDetector:
    """
    Cross-platform detector for active window information.
    
    Detects the currently focussed application, window title,
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
                timeout=5  # Increased from 2s for slower systems under load
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
            
            # Check if it's a browser using comprehensive list
            app_name_lower = app_name.lower()
            is_browser = self._is_browser_process(app_name_lower)
            url = None
            page_title = None
            
            if is_browser:
                # Try to get URL (works for Chrome/Safari/Arc)
                url = self._get_browser_url_macos(app_name_lower)
                
                # Extract page title from window title as fallback
                page_title = self._extract_page_title_from_window(window_title)
            
            return WindowInfo(
                app_name=app_name,
                window_title=window_title,
                url=url,
                is_browser=is_browser,
                page_title=page_title
            )
            
        except subprocess.TimeoutExpired:
            logger.warning("AppleScript timed out getting window info")
            return None
        except Exception as e:
            logger.error(f"Error in macOS window detection: {e}")
            return None
    
    def _get_browser_url_macos(self, app_name_lower: str) -> Optional[str]:
        """
        Get the current URL from various browsers on macOS.
        
        Supports Chrome, Safari, Firefox, Arc, Edge, Brave, and other browsers
        via AppleScript.
        
        Args:
            app_name_lower: Lowercase application name
            
        Returns:
            Current tab URL or None if browser is not running or error occurs.
        """
        # Determine the correct AppleScript based on browser
        script = None
        
        if "chrome" in app_name_lower or "google chrome" in app_name_lower:
            script = '''
            tell application "Google Chrome"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                else
                    return ""
                end if
            end tell
            '''
        elif "safari" in app_name_lower:
            script = '''
            tell application "Safari"
                if (count of windows) > 0 then
                    return URL of front document
                else
                    return ""
                end if
            end tell
            '''
        elif "firefox" in app_name_lower:
            # Firefox doesn't support AppleScript URL access directly
            # Fall back to window title extraction
            return None
        elif "arc" in app_name_lower:
            script = '''
            tell application "Arc"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                else
                    return ""
                end if
            end tell
            '''
        elif "edge" in app_name_lower or "msedge" in app_name_lower:
            script = '''
            tell application "Microsoft Edge"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                else
                    return ""
                end if
            end tell
            '''
        elif "brave" in app_name_lower:
            script = '''
            tell application "Brave Browser"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                else
                    return ""
                end if
            end tell
            '''
        elif "opera" in app_name_lower:
            script = '''
            tell application "Opera"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                else
                    return ""
                end if
            end tell
            '''
        elif "vivaldi" in app_name_lower:
            script = '''
            tell application "Vivaldi"
                if (count of windows) > 0 then
                    return URL of active tab of front window
                else
                    return ""
                end if
            end tell
            '''
        
        if not script:
            logger.debug(f"No AppleScript support for browser: {app_name_lower}")
            return None
        
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5  # Increased from 2s for slower systems under load
            )
            
            if result.returncode == 0:
                url = result.stdout.strip()
                return url if url else None
            return None
            
        except subprocess.TimeoutExpired:
            logger.warning(f"AppleScript timed out getting URL for {app_name_lower}")
            return None
        except Exception as e:
            logger.debug(f"Could not get browser URL: {e}")
            return None
    
    def _get_active_window_windows(self) -> Optional[WindowInfo]:
        """
        Get active window info on Windows using ctypes (standard library).
        
        Uses only ctypes for basic detection (no external dependencies).
        pywinauto is optional and only used for browser URL extraction.
        For browsers, extracts page title from window title as fallback.
        
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
                logger.debug("Windows: No foreground window found")
                self._has_permission = False
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
            
            # Successfully got window info - mark permission as granted
            self._has_permission = True
            
            # Check if it's a browser using comprehensive list
            app_name_lower = app_name.lower()
            is_browser = self._is_browser_process(app_name_lower)
            url = None
            page_title = None
            
            if is_browser:
                # Try to get URL (works with pywinauto or ctypes UI Automation)
                url = self._get_browser_url_windows(hwnd, app_name_lower)
                # Extract page title from window title as fallback
                page_title = self._extract_page_title_from_window(window_title)
                logger.debug(f"Windows browser detected: {app_name}, url={url is not None}, page_title='{page_title}'")
            
            return WindowInfo(
                app_name=app_name,
                window_title=window_title,
                url=url,
                is_browser=is_browser,
                page_title=page_title
            )
            
        except ImportError as e:
            logger.warning(f"ctypes not available on Windows: {e}")
            self._has_permission = False
            return None
        except OSError as e:
            # OS-level error (e.g., access denied)
            logger.warning(f"OS error in Windows window detection: {e}")
            self._has_permission = False
            return None
        except Exception as e:
            logger.error(f"Error in Windows window detection: {e}")
            self._has_permission = False
            return None
    
    def _is_browser_process(self, process_name_lower: str) -> bool:
        """
        Check if a process name corresponds to a known browser.
        
        Args:
            process_name_lower: Lowercase process name
            
        Returns:
            True if it's a known browser
        """
        for browser_key in BROWSER_PROCESS_NAMES.keys():
            if browser_key in process_name_lower:
                return True
        return False
    
    def _extract_page_title_from_window(self, window_title: str) -> Optional[str]:
        """
        Extract the page title from a browser window title.
        
        Browser windows typically show: "Page Title - Browser Name"
        For example: "YouTube - Google Chrome"
        
        Args:
            window_title: Full window title
            
        Returns:
            Extracted page title or None
        """
        if not window_title:
            return None
        
        # Try to remove known browser suffixes
        for suffix in BROWSER_TITLE_SUFFIXES:
            if window_title.endswith(suffix):
                page_title = window_title[:-len(suffix)].strip()
                if page_title:
                    return page_title
        
        # Fallback: Try splitting by common separators
        # Most browsers use " - " or " — " as separator
        for separator in [" - ", " — ", " – ", " | "]:
            if separator in window_title:
                parts = window_title.rsplit(separator, 1)
                if len(parts) == 2:
                    # The page title is usually on the left
                    page_title = parts[0].strip()
                    if page_title:
                        return page_title
        
        return None
    
    def _get_browser_url_windows(self, hwnd: int, app_name_lower: str) -> Optional[str]:
        """
        Get browser URL on Windows using multiple methods.
        
        Tries UI Automation (pywinauto) first, then falls back to
        ctypes-based UI Automation if available.
        
        Args:
            hwnd: Window handle
            app_name_lower: Lowercase app name for browser-specific handling
            
        Returns:
            URL or None
        """
        # Method 1: Try pywinauto (most reliable for Chromium browsers)
        url = self._get_url_via_pywinauto(hwnd, app_name_lower)
        if url:
            return url
        
        # Method 2: Try ctypes-based UI Automation (no external dependencies)
        url = self._get_url_via_uiautomation_ctypes(hwnd)
        if url:
            return url
        
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
    
    def _get_url_via_pywinauto(self, hwnd: int, app_name_lower: str) -> Optional[str]:
        """
        Get browser URL on Windows using pywinauto UI Automation.
        
        Works with Chromium-based browsers (Chrome, Edge, Brave, etc.)
        and Firefox.
        
        Args:
            hwnd: Window handle
            app_name_lower: Lowercase app name for browser-specific handling
            
        Returns:
            URL or None
        """
        try:
            from pywinauto import Application
            
            # Connect to the browser window using UIA backend
            app = Application(backend='uia')
            app.connect(handle=hwnd)
            
            dlg = app.top_window()
            
            # Different browsers use different address bar names
            # Chromium-based: "Address and search bar", "Address bar", "Omnibox"
            # Firefox: uses a toolbar with an edit control
            
            address_bar_names = [
                "Address and search bar",  # Chrome, Edge
                "Address bar",             # Some Chromium variants
                "Omnibox",                 # Chrome internal name
                "Search or enter address", # Firefox
                "Search with Google or enter address",  # Firefox variant
                "URL Bar",                 # Some browsers
                "Navigation toolbar",      # Firefox fallback
            ]
            
            # Try each address bar name
            for bar_name in address_bar_names:
                try:
                    address_bar = dlg.child_window(
                        title=bar_name,
                        control_type="Edit"
                    )
                    url = address_bar.get_value()
                    if url:
                        # Clean up URL if needed
                        url = url.strip()
                        logger.debug(f"Browser URL via pywinauto ({bar_name}): {url}")
                        return url
                except Exception:
                    continue
            
            # Firefox fallback: Try to find any Edit control in the toolbar area
            if "firefox" in app_name_lower:
                try:
                    # Firefox has the URL in a ComboBox or Edit control
                    for control_type in ["Edit", "ComboBox"]:
                        try:
                            edits = dlg.children(control_type=control_type)
                            for edit in edits:
                                try:
                                    value = edit.get_value() if hasattr(edit, 'get_value') else None
                                    if value and ('.' in value or '://' in value):
                                        logger.debug(f"Firefox URL found: {value}")
                                        return value.strip()
                                except Exception:
                                    continue
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Firefox URL fallback failed: {e}")
            
            return None
            
        except ImportError:
            # pywinauto not installed - this is fine, we have fallbacks
            logger.debug("pywinauto not available - trying alternative methods")
            return None
        except Exception as e:
            logger.debug(f"Could not get browser URL via pywinauto: {e}")
            return None
    
    def _get_url_via_uiautomation_ctypes(self, hwnd: int) -> Optional[str]:
        """
        Get browser URL using ctypes-based UI Automation (no external dependencies).
        
        This is a lightweight fallback that uses Windows UI Automation COM interfaces
        directly through ctypes. Less reliable than pywinauto but works without
        additional dependencies.
        
        Args:
            hwnd: Window handle
            
        Returns:
            URL or None
        """
        try:
            import ctypes
            from ctypes import wintypes
            import comtypes
            from comtypes import client as comclient
            
            # Try to use UI Automation via COM
            try:
                # Create UI Automation instance
                uia = comclient.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}")
                
                # Get element from window handle
                element = uia.ElementFromHandle(hwnd)
                if not element:
                    return None
                
                # Find the address bar (Edit control with specific patterns)
                # This is a simplified search - may not work for all browsers
                condition = uia.CreatePropertyCondition(30003, 50004)  # ControlType = Edit
                
                edit_elements = element.FindAll(4, condition)  # TreeScope.Descendants
                
                if edit_elements:
                    for i in range(edit_elements.Length):
                        try:
                            edit = edit_elements.GetElement(i)
                            name = edit.CurrentName
                            
                            # Check if this looks like an address bar
                            if name and any(x in name.lower() for x in ["address", "url", "search", "omnibox"]):
                                # Get the value pattern
                                try:
                                    value_pattern = edit.GetCurrentPattern(10002)  # ValuePattern
                                    if value_pattern:
                                        url = value_pattern.CurrentValue
                                        if url and ('.' in url or '://' in url):
                                            logger.debug(f"URL via ctypes UI Automation: {url}")
                                            return url.strip()
                                except Exception:
                                    pass
                        except Exception:
                            continue
                
                return None
                
            except Exception as e:
                logger.debug(f"COM-based UI Automation failed: {e}")
                return None
                
        except ImportError:
            # comtypes not available - this is fine
            logger.debug("comtypes not available for UI Automation")
            return None
        except Exception as e:
            logger.debug(f"ctypes UI Automation error: {e}")
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
                "Screen monitoring cannot access window information.\n\n"
                "Possible solutions:\n"
                "1. Run BrainDock as Administrator\n"
                "   (Right-click → Run as administrator)\n\n"
                "2. Check if antivirus is blocking the app\n\n"
                "3. If running in a virtual machine,\n"
                "   try running on the host system\n\n"
                "For now, try using Camera Only mode."
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
        - page_title: str or None (extracted browser page title)
        - is_browser: bool
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
            "page_title": None,
            "is_browser": False,
            "error": "Could not detect active window"
        }
    
    # Check if current window/URL matches blocklist
    # Pass page_title for browsers where URL might not be available
    is_distracted, match_source = blocklist.check_distraction(
        url=window_info.url,
        window_title=window_info.window_title,
        app_name=window_info.app_name,
        page_title=window_info.page_title
    )
    
    return {
        "is_distracted": is_distracted,
        "distraction_source": match_source,
        "app_name": window_info.app_name,
        "window_title": window_info.window_title,
        "url": window_info.url,
        "page_title": window_info.page_title,
        "is_browser": window_info.is_browser
    }


def get_screen_state_with_ai_fallback(
    blocklist: 'Blocklist',
    use_ai_fallback: bool = False
) -> Dict[str, Any]:
    """
    Get screen state with optional AI Vision fallback.
    
    This is an enhanced version that can use AI to analyse screenshots
    when local blocklist matching is inconclusive. AI is only called
    as a last resort to minimise API costs.
    
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
    
    # AI fallback: Take screenshot and analyse
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
    Analyse the current screen using OpenAI Vision API.
    
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
