"""Webcam capture and management."""

import cv2
import logging
from typing import Optional, Iterator, Tuple
import numpy as np
import config

logger = logging.getLogger(__name__)


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
        
        Returns:
            True if camera opened successfully, False otherwise.
        """
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            
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

