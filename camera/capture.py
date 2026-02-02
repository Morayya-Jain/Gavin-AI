"""Webcam capture and management."""

import cv2
import logging
import sys
import time
import threading
from enum import Enum
from typing import Optional, Iterator, Tuple
import numpy as np
import config

logger = logging.getLogger(__name__)


# Camera permission status constants (mirrors AVAuthorizationStatus)
CAMERA_PERMISSION_NOT_DETERMINED = 0
CAMERA_PERMISSION_RESTRICTED = 1
CAMERA_PERMISSION_DENIED = 2
CAMERA_PERMISSION_AUTHORIZED = 3


class CameraFailureType(Enum):
    """Types of camera access failures for user-friendly error messages."""
    NONE = "none"  # No failure - camera works
    PERMISSION_DENIED = "permission_denied"  # User denied camera permission
    PERMISSION_RESTRICTED = "permission_restricted"  # Restricted by parental controls/MDM
    NO_HARDWARE = "no_hardware"  # No camera hardware detected
    IN_USE = "in_use"  # Camera is being used by another application
    UNKNOWN = "unknown"  # Unknown/generic failure


def get_macos_camera_permission_status() -> int:
    """
    Check the current camera authorization status on macOS.
    
    Returns:
        One of CAMERA_PERMISSION_* constants:
        - NOT_DETERMINED (0): User hasn't been asked yet
        - RESTRICTED (1): Restricted by parental controls/MDM
        - DENIED (2): User explicitly denied permission
        - AUTHORIZED (3): User granted permission
        
    On non-macOS platforms, always returns AUTHORIZED.
    Note: Windows 10+ has camera privacy settings but checking them requires
    additional libraries. Camera errors on Windows will show a helpful message.
    """
    if sys.platform != "darwin":
        return CAMERA_PERMISSION_AUTHORIZED
    
    try:
        import AVFoundation  # type: ignore[import-not-found]
        # AVMediaTypeVideo = "vide"
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_("vide")
        logger.debug(f"macOS camera permission status: {status}")
        return status
    except ImportError:
        logger.warning("AVFoundation not available - assuming camera permission granted")
        return CAMERA_PERMISSION_AUTHORIZED
    except Exception as e:
        logger.error(f"Error checking camera permission: {e}")
        return CAMERA_PERMISSION_AUTHORIZED


def request_macos_camera_permission() -> bool:
    """
    Request camera permission on macOS, ensuring the dialog appears in front.
    
    This function:
    1. Checks if permission is already determined
    2. If not, temporarily hides the app so the permission dialog appears in front
    3. Requests permission using AVFoundation
    4. Waits for the user to respond
    5. Returns the result
    
    Returns:
        True if permission was granted, False otherwise.
        On non-macOS platforms, always returns True.
    """
    if sys.platform != "darwin":
        return True
    
    # Check current status
    status = get_macos_camera_permission_status()
    
    if status == CAMERA_PERMISSION_AUTHORIZED:
        logger.debug("Camera permission already granted")
        return True
    
    if status == CAMERA_PERMISSION_DENIED:
        logger.warning("Camera permission was denied - user must enable in System Settings")
        return False
    
    if status == CAMERA_PERMISSION_RESTRICTED:
        logger.warning("Camera access is restricted (parental controls or MDM)")
        return False
    
    # Status is NOT_DETERMINED - request permission
    logger.info("Requesting camera permission from user...")
    print("[BrainDock] Requesting camera permission...")
    
    try:
        import AVFoundation  # type: ignore[import-not-found]
        
        # Use an event to wait for the async callback
        permission_granted = threading.Event()
        permission_result = [False]  # Use list to allow modification in closure
        
        def permission_callback(granted: bool) -> None:
            """Callback when user responds to permission dialog."""
            permission_result[0] = granted
            permission_granted.set()
            logger.info(f"Camera permission {'granted' if granted else 'denied'} by user")
            print(f"[BrainDock] Camera permission {'granted' if granted else 'denied'}")
        
        # Request permission - this triggers the macOS permission dialog
        # Note: We don't deactivate the app because that must be called from main thread
        # and this function may be called from a background thread (detection loop).
        # The permission dialog will still appear, possibly behind the app window.
        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            "vide",  # AVMediaTypeVideo
            permission_callback
        )
        
        # Wait for user to respond (up to 120 seconds)
        # The dialog will stay open until user clicks Allow or Don't Allow
        permission_granted.wait(timeout=120.0)
        
        return permission_result[0]
        
    except ImportError as e:
        logger.warning(f"PyObjC frameworks not available: {e}")
        # Fall back to letting OpenCV trigger the permission dialog
        return True
    except Exception as e:
        logger.error(f"Error requesting camera permission: {e}")
        # Fall back to letting OpenCV trigger the permission dialog
        return True


def ensure_macos_camera_permission() -> Tuple[bool, str, bool]:
    """
    Ensure camera permission is granted on macOS, showing dialog if needed.
    
    This is the main entry point for camera permission handling.
    It checks the current status and either:
    - Returns success if already authorized
    - Requests permission (with dialog appearing in front) if not determined
    - Returns failure with helpful message if denied/restricted
    
    Returns:
        Tuple of (success: bool, message: str, is_first_denial: bool)
        - success: True if camera can be used, False otherwise
        - message: Empty string on success, or helpful error message on failure
        - is_first_denial: True if this is the first time user denied (native dialog was shown)
    """
    if sys.platform != "darwin":
        return True, "", False
    
    status = get_macos_camera_permission_status()
    
    if status == CAMERA_PERMISSION_AUTHORIZED:
        return True, "", False
    
    if status == CAMERA_PERMISSION_DENIED:
        # Already denied before - not a first-time denial
        return False, (
            "Camera access was denied.\n\n"
            "To enable camera access:\n"
            "1. Open System Settings\n"
            "2. Go to Privacy & Security → Camera\n"
            "3. Enable BrainDock\n"
            "4. Restart BrainDock"
        ), False
    
    if status == CAMERA_PERMISSION_RESTRICTED:
        return False, (
            "Camera access is restricted on this device.\n\n"
            "This may be due to parental controls or device management policies."
        ), False
    
    # NOT_DETERMINED - request permission (native macOS dialog will appear)
    granted = request_macos_camera_permission()
    
    if granted:
        return True, "", False
    else:
        # User just denied for the first time (native dialog was shown)
        return False, (
            "Camera access was denied.\n\n"
            "To enable camera access:\n"
            "1. Open System Settings\n"
            "2. Go to Privacy & Security → Camera\n"
            "3. Enable BrainDock\n"
            "4. Restart BrainDock"
        ), True  # is_first_denial = True


class CameraCapture:
    """
    Manages webcam capture with context manager support.
    
    Provides a clean interface for opening, reading frames from,
    and closing the webcam.
    """
    
    def __init__(self, camera_index: int = None, width: int = None, height: int = None):
        """
        Initialize camera capture.
        
        Args:
            camera_index: Camera device index (default from config)
            width: Frame width in pixels (default from config)
            height: Frame height in pixels (default from config)
        """
        # Use explicit None check - 0 is a valid camera index!
        self.camera_index = camera_index if camera_index is not None else config.CAMERA_INDEX
        self.width = width if width is not None else config.FRAME_WIDTH
        self.height = height if height is not None else config.FRAME_HEIGHT
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_opened = False
        self.permission_error: Optional[str] = None  # Stores permission error message if any
        self.is_first_denial: bool = False  # True if user just denied permission for the first time
        self.failure_type: CameraFailureType = CameraFailureType.NONE  # Type of failure for specific error handling
    
    def __enter__(self) -> 'CameraCapture':
        """Context manager entry - open the camera."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the camera."""
        self.close()
    
    def open(self) -> bool:
        """
        Open the camera device.
        
        Automatically attempts wide mode (16:9) for more desk coverage.
        If camera doesn't support wide resolutions, falls back to standard 640x480.
        
        On macOS, this method first ensures camera permission is granted,
        showing the system permission dialog in front of the app if needed.
        
        Returns:
            True if camera opened successfully, False otherwise.
        """
        try:
            # On macOS, ensure camera permission before trying to open
            # This shows the permission dialog in front of the app window
            if sys.platform == "darwin":
                permission_granted, error_message, is_first_denial = ensure_macos_camera_permission()
                if not permission_granted:
                    logger.error(f"Camera permission not granted: {error_message}")
                    self.permission_error = error_message  # Store for GUI to display
                    self.is_first_denial = is_first_denial  # Track if this was first-time denial
                    # Determine failure type based on the error message
                    if "restricted" in error_message.lower():
                        self.failure_type = CameraFailureType.PERMISSION_RESTRICTED
                    else:
                        self.failure_type = CameraFailureType.PERMISSION_DENIED
                    return False
            
            print(f"[BrainDock] Opening camera at index {self.camera_index}...")
            # Use DirectShow backend on Windows for faster initialization
            # Fall back to default backend if DirectShow fails (some cameras don't support it)
            if sys.platform == "win32":
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    logger.info("DirectShow backend failed, trying default backend...")
                    self.cap = cv2.VideoCapture(self.camera_index)
            else:
                self.cap = cv2.VideoCapture(self.camera_index)
            print(f"[BrainDock] VideoCapture created, isOpened={self.cap.isOpened()}")
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open camera at index {self.camera_index}")
                # Release the capture object to prevent resource leak
                self.cap.release()
                self.cap = None
                
                # Determine the failure type by trying to detect available cameras
                failure_type, error_msg = self._diagnose_camera_failure()
                self.failure_type = failure_type
                self.permission_error = error_msg
                
                return False
            
            # Standard fallback resolution (4:3)
            STANDARD_WIDTH, STANDARD_HEIGHT = 640, 480
            
            # Try wide mode resolutions if enabled
            if getattr(config, 'CAMERA_WIDE_MODE', True):
                resolutions = getattr(config, 'CAMERA_WIDE_RESOLUTIONS', [(1280, 720)])
                wide_mode_success = False
                
                for width, height in resolutions:
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                    actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    
                    # Check if camera accepted this resolution (within 10% tolerance)
                    if actual_w >= width * 0.9 and actual_h >= height * 0.9:
                        logger.info(f"Wide mode enabled: {actual_w}x{actual_h}")
                        wide_mode_success = True
                        break
                    else:
                        logger.debug(f"Resolution {width}x{height} not supported, "
                                   f"camera returned {actual_w}x{actual_h}")
                
                # If no wide resolution worked, fall back to standard
                if not wide_mode_success:
                    logger.info("Wide mode not supported by camera, reverting to standard 640x480")
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, STANDARD_WIDTH)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STANDARD_HEIGHT)
            else:
                # Wide mode disabled, use standard resolution
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, STANDARD_WIDTH)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STANDARD_HEIGHT)
            
            # Verify camera actually works by reading a test frame
            # On macOS, isOpened() can return True even without camera permission
            # The permission prompt only appears when we try to read a frame
            #
            # Retry strategy by platform:
            # - macOS: Long wait (60s) for permission dialog response
            # - Windows: Fast initial retries (camera often ready immediately if pre-warmed),
            #            then slower retries for cold-start scenarios
            # - Linux: Quick retries, cameras usually respond fast
            if sys.platform == "darwin":
                max_read_attempts = 120  # 60 seconds for permission dialog
                read_delays = [0.5] * 120  # Consistent 0.5s delays
            elif sys.platform == "win32":
                # Windows: Fast initial attempts (0.05s), then gradually slower
                # This handles both warmed cameras (instant) and cold starts (~5s)
                # Total max wait: ~8 seconds (but usually <1s if pre-warmed)
                read_delays = (
                    [0.05] * 5 +   # 5 fast attempts (0.25s total)
                    [0.1] * 5 +    # 5 medium attempts (0.5s total)  
                    [0.2] * 10 +   # 10 slower attempts (2s total)
                    [0.5] * 10     # 10 slow attempts (5s total)
                )
                max_read_attempts = len(read_delays)
            else:
                max_read_attempts = 5
                read_delays = [0.3] * 5  # Linux: quick retries
            
            if sys.platform == "darwin":
                print(f"[BrainDock] Requesting camera access...")
                print(f"[BrainDock] If a permission dialog appears, please click 'OK' or 'Allow'")
            else:
                logger.debug(f"[BrainDock] Reading first frame...")
            
            permission_dialog_shown = False
            for attempt in range(max_read_attempts):
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    if sys.platform == "darwin" and attempt > 0:
                        print(f"[BrainDock] Camera access granted! Starting session...")
                    else:
                        logger.debug(f"[BrainDock] Camera ready (attempt {attempt + 1})")
                    break
                    
                if attempt < max_read_attempts - 1:
                    # Provide helpful feedback while waiting
                    if sys.platform == "darwin":
                        if attempt == 0:
                            # First failure - permission dialog likely showing
                            permission_dialog_shown = True
                            logger.info("Waiting for user to respond to camera permission dialog...")
                        elif attempt == 20:  # ~10 seconds
                            print("[BrainDock] Still waiting for camera permission...")
                            print("[BrainDock] Please click 'Allow' in the system dialog")
                        elif attempt == 60:  # ~30 seconds
                            print("[BrainDock] Camera permission dialog may be behind other windows")
                            print("[BrainDock] Check your taskbar/dock for the permission prompt")
                        elif attempt % 20 == 0 and attempt > 60:
                            elapsed_secs = sum(read_delays[:attempt])
                            print(f"[BrainDock] Waiting for camera access ({elapsed_secs:.0f}s elapsed)...")
                    else:
                        # Windows/Linux: only log after several failed attempts
                        if attempt == 10:
                            logger.debug("Camera initializing (cold start)...")
                    
                    time.sleep(read_delays[attempt])
            
            if not ret or test_frame is None:
                logger.error("Camera opened but cannot read frames - permission may be denied")
                self.cap.release()
                self.cap = None
                
                # Frame read failed after camera opened - likely permission issue
                # On macOS, this means user denied permission or it timed out
                if sys.platform == "darwin":
                    self.failure_type = CameraFailureType.PERMISSION_DENIED
                    self.permission_error = (
                        "Camera access was denied.\n\n"
                        "To enable camera access:\n"
                        "1. Open System Settings\n"
                        "2. Go to Privacy & Security → Camera\n"
                        "3. Enable BrainDock\n"
                        "4. Restart BrainDock"
                    )
                elif sys.platform == "win32":
                    # On Windows, could be permission or in-use issue
                    self.failure_type = CameraFailureType.IN_USE
                    self.permission_error = (
                        "Camera may be in use by another application.\n\n"
                        "Please close other apps using the camera (Zoom, Teams, etc.) "
                        "and try again.\n\n"
                        "If problem persists, check Windows Privacy settings."
                    )
                else:
                    self.failure_type = CameraFailureType.UNKNOWN
                    self.permission_error = "Unable to read from camera."
                
                return False
            
            self.is_opened = True
            props = self.get_properties()
            logger.info(f"Camera opened at {props.get('width')}x{props.get('height')}")
            return True
            
        except Exception as e:
            logger.error(f"Error opening camera: {e}")
            self.failure_type = CameraFailureType.UNKNOWN
            self.permission_error = f"Unexpected error accessing camera: {str(e)}"
            return False
    
    def _diagnose_camera_failure(self) -> Tuple[CameraFailureType, str]:
        """
        Diagnose the reason for camera failure by checking available devices.
        
        Tries to determine if the failure is due to:
        - No hardware: No cameras detected on the system
        - In use: Camera exists but is being used by another app
        - Permission denied: OS-level permission restriction
        
        Returns:
            Tuple of (CameraFailureType, error_message)
        """
        # Try to enumerate available cameras
        available_cameras = self._count_available_cameras()
        
        if available_cameras == 0:
            # No cameras detected at all
            logger.info("No camera hardware detected on this system")
            return CameraFailureType.NO_HARDWARE, (
                "No camera detected.\n\n"
                "Please check:\n"
                "• Your webcam is connected\n"
                "• Camera drivers are installed\n"
                "• Camera is not disabled in Device Manager (Windows)\n"
                "  or System Information (macOS)"
            )
        
        # Camera hardware exists but we can't access it
        if sys.platform == "win32":
            # On Windows, most likely causes are permission or in-use
            # Try a quick re-open to see if it's a transient in-use issue
            test_cap = cv2.VideoCapture(self.camera_index)
            if test_cap.isOpened():
                # Camera opened this time - was temporarily in use
                test_cap.release()
                return CameraFailureType.IN_USE, (
                    "Camera is being used by another application.\n\n"
                    "Please close any apps that might be using the camera:\n"
                    "• Video conferencing (Zoom, Teams, Meet)\n"
                    "• Other camera apps\n"
                    "• Browser tabs with camera access\n\n"
                    "Then try again."
                )
            test_cap.release()
            
            # Still can't open - likely permission
            return CameraFailureType.PERMISSION_DENIED, (
                "Camera access failed.\n\n"
                "This may be due to Windows Privacy settings:\n"
                "1. Open Settings\n"
                "2. Go to Privacy & Security → Camera\n"
                "3. Ensure 'Camera access' is On\n"
                "4. Ensure 'Let apps access your camera' is On\n"
                "5. Restart BrainDock"
            )
        
        elif sys.platform == "darwin":
            # On macOS, if we got here, permission check already passed
            # Most likely camera is in use by another app
            return CameraFailureType.IN_USE, (
                "Camera is being used by another application.\n\n"
                "Please close any apps that might be using the camera:\n"
                "• Video conferencing (Zoom, Teams, FaceTime)\n"
                "• Photo Booth\n"
                "• Browser tabs with camera access\n\n"
                "Then try again."
            )
        
        else:
            # Linux or other
            return CameraFailureType.UNKNOWN, (
                "Failed to access webcam.\n\n"
                "Please check:\n"
                "• Camera is connected\n"
                "• Camera permissions are granted\n"
                "• No other app is using the camera"
            )
    
    def _count_available_cameras(self) -> int:
        """
        Count the number of available cameras on the system.
        
        Returns:
            Number of cameras detected (may be approximate)
        """
        # OpenCV doesn't have a direct way to enumerate cameras
        # We'll try opening camera indices 0-3 as a heuristic
        count = 0
        for i in range(4):
            try:
                if sys.platform == "win32":
                    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                else:
                    cap = cv2.VideoCapture(i)
                
                if cap.isOpened():
                    count += 1
                    cap.release()
                else:
                    cap.release()
                    # On some systems, indices aren't contiguous
                    # Continue checking a few more indices
            except Exception:
                continue
        
        return count
    
    def close(self) -> None:
        """Close the camera and release resources."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None  # Prevent double-release on subsequent calls
            self.is_opened = False
            logger.info("Camera closed")
    
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read a single frame from the camera.
        
        Returns:
            Tuple of (success: bool, frame: numpy array or None)
        """
        if not self.is_opened or self.cap is None:
            logger.warning("Attempted to read from closed camera")
            return False, None
        
        try:
            ret, frame = self.cap.read()
            
            if not ret:
                logger.warning("Failed to read frame from camera")
                return False, None
            
            return True, frame
            
        except Exception as e:
            logger.error(f"Error reading frame: {e}")
            return False, None
    
    def frame_iterator(self) -> Iterator[np.ndarray]:
        """
        Create an iterator that yields frames continuously.
        
        Yields:
            numpy arrays containing frame data
            
        Example:
            with CameraCapture() as camera:
                for frame in camera.frame_iterator():
                    # Process frame
                    pass
        """
        while self.is_opened:
            success, frame = self.read_frame()
            
            if not success or frame is None:
                logger.warning("Failed to get frame, stopping iterator")
                break
            
            yield frame
    
    def get_properties(self) -> dict:
        """
        Get current camera properties.
        
        Returns:
            Dictionary containing camera properties like width, height, fps.
        """
        if not self.is_opened or self.cap is None:
            return {}
        
        return {
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": self.cap.get(cv2.CAP_PROP_FPS),
            "backend": self.cap.getBackendName()
        }


def test_camera() -> bool:
    """
    Test if camera is available and working.
    
    Returns:
        True if camera test successful, False otherwise.
    """
    try:
        with CameraCapture() as camera:
            success, frame = camera.read_frame()
            
            if success and frame is not None:
                logger.info("Camera test successful")
                return True
            else:
                logger.error("Camera test failed - could not read frame")
                return False
                
    except Exception as e:
        logger.error(f"Camera test failed with exception: {e}")
        return False


if __name__ == "__main__":
    # Simple test when run directly
    logging.basicConfig(level=logging.INFO)
    
    print("Testing camera...")
    if test_camera():
        print("✓ Camera is working!")
        
        # Try to capture a few frames
        print("\nCapturing 5 frames...")
        with CameraCapture() as camera:
            props = camera.get_properties()
            print(f"Camera properties: {props}")
            
            for i, frame in enumerate(camera.frame_iterator()):
                if i >= 5:
                    break
                print(f"  Frame {i+1}: {frame.shape}")
        
        print("✓ Frame capture successful!")
    else:
        print("✗ Camera test failed!")

