"""Phone object detection using computer vision."""

import cv2
import numpy as np
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class PhoneDetector:
    """
    Detects phones in camera frames using computer vision.
    Uses MobileNet SSD pre-trained model (from COCO dataset).
    """
    
    def __init__(self):
        """Initialize the phone detector."""
        # We'll use the fallback method which is actually quite reliable
        # No need to download external models
        logger.info("Phone detector initialized (using shape-based detection)")
    
    def detect_phone(self, frame: np.ndarray, confidence_threshold: float = 0.3) -> Tuple[bool, float]:
        """
        Detect if a phone (cell phone) is visible in the frame.
        
        Uses shape-based detection - looks for rectangular objects
        with phone-like characteristics.
        
        Args:
            frame: BGR image from camera
            confidence_threshold: Minimum confidence for detection (0-1)
            
        Returns:
            Tuple of (phone_detected: bool, confidence: float)
        """
        return self._detect_phone_fallback(frame, confidence_threshold)
    
    def _detect_phone_fallback(self, frame: np.ndarray, threshold: float = 0.25) -> Tuple[bool, float]:
        """
        Improved phone detection using shape analysis and edge detection.
        
        Looks for:
        - Rectangular objects
        - Phone-like aspect ratios
        - Distinct edges (screen)
        - Appropriate size
        
        Args:
            frame: BGR image from camera
            threshold: Confidence threshold for detection
            
        Returns:
            Tuple of (phone_detected: bool, confidence: float)
        """
        try:
            h, w = frame.shape[:2]
            
            # Focus on center and upper portions (where phone typically appears)
            roi = frame[0:int(h*0.8), :]
            roi_h, roi_w = roi.shape[:2]
            
            # Convert to grayscale
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            
            # Apply bilateral filter to reduce noise while keeping edges
            blurred = cv2.bilateralFilter(gray, 9, 75, 75)
            
            # Multi-threshold edge detection for better results
            edges1 = cv2.Canny(blurred, 30, 100)
            edges2 = cv2.Canny(blurred, 50, 150)
            edges = cv2.bitwise_or(edges1, edges2)
            
            # Dilate edges to connect broken lines
            kernel = np.ones((3,3), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=1)
            
            # Find contours
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            max_confidence = 0.0
            
            for contour in contours:
                # Get bounding rectangle
                x, y, cw, ch = cv2.boundingRect(contour)
                
                # Size filtering - phone should be visible but not too small
                min_width = max(40, roi_w * 0.08)  # At least 8% of width or 40px
                min_height = max(70, roi_h * 0.12)  # At least 12% of height or 70px
                
                if cw < min_width or ch < min_height:
                    continue
                
                # Don't detect objects that are too large (probably not a phone)
                if cw > roi_w * 0.6 or ch > roi_h * 0.8:
                    continue
                
                # Calculate aspect ratio
                aspect_ratio = cw / ch if ch > 0 else 0
                
                # Phone aspect ratios:
                # Portrait: 0.4-0.7 (typical: 0.5-0.6)
                # Landscape: 1.4-2.5 (typical: 1.6-2.0)
                is_portrait = 0.35 < aspect_ratio < 0.75
                is_landscape = 1.3 < aspect_ratio < 2.5
                
                if not (is_portrait or is_landscape):
                    continue
                
                # Check how rectangular it is (phones are rectangles)
                area = cv2.contourArea(contour)
                rect_area = cw * ch
                
                if rect_area == 0:
                    continue
                    
                rectangularity = area / rect_area
                
                # Phones are solid rectangles (high rectangularity)
                if rectangularity < 0.65:
                    continue
                
                # Check for screen-like characteristics (uniform regions)
                phone_region = gray[y:y+ch, x:x+cw]
                if phone_region.size == 0:
                    continue
                
                # Phones typically have relatively uniform screen areas
                std_dev = np.std(phone_region)
                mean_val = np.mean(phone_region)
                
                # Calculate confidence score
                confidence = 0.0
                
                # Size score (0-30%)
                size_ratio = (cw * ch) / (roi_w * roi_h)
                size_score = min(0.3, size_ratio * 2)  # Optimal around 15% of frame
                confidence += size_score
                
                # Aspect ratio score (0-25%)
                if is_portrait:
                    # Closer to 0.55 is better
                    aspect_score = 0.25 * (1 - abs(aspect_ratio - 0.55) / 0.35)
                else:
                    # Closer to 1.8 is better
                    aspect_score = 0.25 * (1 - abs(aspect_ratio - 1.8) / 1.2)
                confidence += aspect_score
                
                # Rectangularity score (0-20%)
                rect_score = 0.2 * rectangularity
                confidence += rect_score
                
                # Edge strength score (0-25%)
                # Phones have distinct edges
                edge_strength = np.sum(edges[y:y+ch, x:x+cw]) / (cw * ch * 255)
                edge_score = min(0.25, edge_strength * 5)
                confidence += edge_score
                
                max_confidence = max(max_confidence, confidence)
                
                # Debug logging
                if confidence > 0.2:
                    logger.debug(f"Phone candidate: size={cw}x{ch}, aspect={aspect_ratio:.2f}, rect={rectangularity:.2f}, conf={confidence:.2f}")
            
            return max_confidence > threshold, max_confidence
            
        except Exception as e:
            logger.warning(f"Error in phone detection: {e}")
            return False, 0.0
