"""Presence and phone usage detection using MediaPipe and Computer Vision."""

import cv2
import mediapipe as mp
import numpy as np
import logging
from typing import Dict, Optional
import config
from camera.phone_detector import PhoneDetector

logger = logging.getLogger(__name__)


class PresenceDetector:
    """
    Detects student presence and phone usage.
    
    - Presence: Using MediaPipe face detection
    - Phone: Using computer vision object detection (no head tilt/eye gaze)
    """
    
    def __init__(self):
        """Initialize MediaPipe solutions and phone detector."""
        # Face detection for presence
        self.mp_face_detection = mp.solutions.face_detection
        self.face_detection = self.mp_face_detection.FaceDetection(
            model_selection=0,  # 0 for short range (< 2m)
            min_detection_confidence=config.FACE_DETECTION_CONFIDENCE
        )
        
        # Phone detector using computer vision
        self.phone_detector = PhoneDetector()
        
        # State tracking
        self.phone_frame_count = 0
        self.phone_detections = []  # Rolling window of phone detections
    
    def __del__(self):
        """Clean up MediaPipe resources."""
        self.face_detection.close()
    
    def detect_presence(self, frame: np.ndarray) -> bool:
        """
        Detect if a face is present in the frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if face detected, False otherwise
        """
        # Convert BGR to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Process with face detection
        results = self.face_detection.process(rgb_frame)
        
        # Check if any faces detected
        if results.detections:
            return True
        
        return False
    
    def detect_phone_usage(self, frame: np.ndarray) -> bool:
        """
        Detect if a phone is visible in the frame using computer vision.
        
        This uses actual object detection to find phones in the camera view.
        NO head tilt, NO eye gaze, NO behavioral analysis - just looks for phone object.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if phone detected in frame, False otherwise
        """
        try:
            # Detect phone in frame
            phone_detected, confidence = self.phone_detector.detect_phone(frame)
            
            # Keep rolling window of last 5 detections
            self.phone_detections.append((phone_detected, confidence))
            if len(self.phone_detections) > 5:
                self.phone_detections.pop(0)
            
            # Count how many recent frames had phone
            recent_detections = sum(1 for detected, _ in self.phone_detections if detected)
            avg_confidence = sum(conf for _, conf in self.phone_detections) / len(self.phone_detections) if self.phone_detections else 0
            
            # Log detection info - more frequently for debugging
            if len(self.phone_detections) % 5 == 0:
                if recent_detections > 0:
                    logger.info(f"📱 Phone detection: {recent_detections}/5 frames, confidence: {avg_confidence:.2f}")
                else:
                    logger.debug(f"No phone: {recent_detections}/5 frames, confidence: {avg_confidence:.2f}")
            
            # If phone detected in majority of recent frames
            if recent_detections >= 3:  # 3 out of 5 frames
                self.phone_frame_count += 1
                if self.phone_frame_count == 1:
                    logger.info(f"📱 Phone detected in frame! Confidence: {confidence:.2f}")
            else:
                if self.phone_frame_count > 0:
                    logger.info(f"✓ Phone no longer visible")
                self.phone_frame_count = 0
            
            # Need sustained detection
            threshold_frames = config.PHONE_DETECTION_DURATION_SECONDS * config.DETECTION_FPS
            
            return self.phone_frame_count >= threshold_frames
            
        except Exception as e:
            logger.warning(f"Error in phone detection: {e}")
            return False
    
    def get_detection_state(self, frame: np.ndarray) -> Dict[str, bool]:
        """
        Get complete detection state for a frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Dictionary with 'present' and 'phone_suspected' booleans
        """
        present = self.detect_presence(frame)
        phone_suspected = False
        
        # Only check for phone if person is present
        if present:
            phone_suspected = self.detect_phone_usage(frame)
        
        return {
            "present": present,
            "phone_suspected": phone_suspected
        }
    
    def determine_event_type(self, detection_state: Dict[str, bool]) -> str:
        """
        Determine the event type from detection state.
        
        Priority:
        1. Phone suspected (if present)
        2. Away (if not present)
        3. Present (default when present)
        
        Args:
            detection_state: Dictionary from get_detection_state
            
        Returns:
            Event type string (present, away, phone_suspected)
        """
        if not detection_state["present"]:
            return config.EVENT_AWAY
        elif detection_state["phone_suspected"]:
            return config.EVENT_PHONE_SUSPECTED
        else:
            return config.EVENT_PRESENT


def visualize_detection(
    frame: np.ndarray,
    detection_state: Dict[str, bool]
) -> np.ndarray:
    """
    Draw detection state on frame for debugging/visualization.
    
    Args:
        frame: Input frame
        detection_state: Detection state dictionary
        
    Returns:
        Frame with visualization overlay
    """
    frame_copy = frame.copy()
    
    # Status text
    if not detection_state["present"]:
        status = "AWAY"
        color = (0, 0, 255)  # Red
    elif detection_state["phone_suspected"]:
        status = "PHONE DETECTED"
        color = (0, 165, 255)  # Orange
    else:
        status = "PRESENT"
        color = (0, 255, 0)  # Green
    
    # Draw status box
    cv2.rectangle(frame_copy, (10, 10), (300, 60), (0, 0, 0), -1)
    cv2.putText(
        frame_copy,
        status,
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        color,
        2
    )
    
    return frame_copy
