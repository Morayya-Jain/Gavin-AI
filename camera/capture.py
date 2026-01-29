"""Webcam capture and management."""

import cv2
import logging
import sys
import time
import threading
from typing import Optional, Iterator, Tuple
import numpy as np
import config

logger = logging.getLogger(__name__)


# Camera permission status constants (mirrors AVAuthorizationStatus)
CAMERA_PERMISSION_NOT_DETERMINED = 0
CAMERA_PERMISSION_RESTRICTED = 1
CAMERA_PERMISSION_DENIED = 2
CAMERA_PERMISSION_AUTHORIZED = 3


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
        self.camera_index = camera_index or config.CAMERA_INDEX
        self.width = width or config.FRAME_WIDTH
        self.height = height or config.FRAME_HEIGHT
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_opened = False
        self.permission_error: Optional[str] = None  # Stores permission error message if any
        self.is_first_denial: bool = False  # True if user just denied permission for the first time
    
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
                    return False
            
            print(f"[BrainDock] Opening camera at index {self.camera_index}...")
            self.cap = cv2.VideoCapture(self.camera_index)
            print(f"[BrainDock] VideoCapture created, isOpened={self.cap.isOpened()}")
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open camera at index {self.camera_index}")
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
            # Important: On macOS, when the camera permission dialog first appears,
            # cap.read() may fail while the user is still responding to the dialog.
            # We retry many times with delays to give the user unlimited time to respond.
            # 120 attempts * 0.5s = 60 seconds max wait time for permission dialog
            max_read_attempts = 120 if sys.platform == "darwin" else 3
            read_delay = 0.5  # Wait between retries to give user time to respond to dialog
            
            print(f"[BrainDock] Attempting to read frame (this triggers macOS permission dialog)...")
            for attempt in range(max_read_attempts):
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    print(f"[BrainDock] Frame read successful on attempt {attempt + 1}!")
                    break
                    
                if attempt < max_read_attempts - 1:
                    if attempt % 10 == 0:  # Log every 5 seconds
                        print(f"[BrainDock] Waiting for camera permission (attempt {attempt + 1}/{max_read_attempts})...")
                        logger.debug(f"Waiting for camera access (attempt {attempt + 1}/{max_read_attempts})...")
                    time.sleep(read_delay)
            
            if not ret or test_frame is None:
                logger.error("Camera opened but cannot read frames - permission may be denied")
                self.cap.release()
                return False
            
            self.is_opened = True
            props = self.get_properties()
            logger.info(f"Camera opened at {props.get('width')}x{props.get('height')}")
            return True
            
        except Exception as e:
            logger.error(f"Error opening camera: {e}")
            return False
    
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

