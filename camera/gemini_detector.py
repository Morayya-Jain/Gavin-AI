"""Vision-based detection using Google Gemini API."""

import cv2
import numpy as np
import base64
import json
import logging
import time
from typing import Dict, Optional, Any
import threading

import google.generativeai as genai
from PIL import Image
import io

import config

logger = logging.getLogger(__name__)


class GeminiVisionDetector:
    """
    Uses Google Gemini Vision API to detect:
    - Person presence (any body part visible)
    - Desk proximity (very lenient distance-based detection)
    - Gadget usage with position-based rules
    
    Note: Smartwatches/Apple Watches are explicitly EXCLUDED from detection
    as they are not considered distractions (used for time/notifications).
    
    Desk Proximity Detection (LENIENT):
    - at_desk=true if person's upper body fills decent portion of frame
    - at_desk=false if person appears small (less than ~1/3 frame height)
    - Standing briefly near desk, leaning back still counts as at_desk
    
    Gadget Detection Rules (position-based):
    - Device IN HANDS: ALWAYS a distraction (screen state and gaze irrelevant)
    - Device ON TABLE: Only distraction if screen lit AND user looking at it
    - Device face-down or screen off on table: NOT a distraction
    """
    
    def __init__(self, api_key: Optional[str] = None, vision_model: Optional[str] = None):
        """
        Initialize Gemini vision detector.
        
        Args:
            api_key: Gemini API key (defaults to config.GEMINI_API_KEY)
            vision_model: Vision model to use (defaults to config.GEMINI_VISION_MODEL)
        """
        self.api_key = api_key or config.GEMINI_API_KEY
        self.vision_model = vision_model or config.GEMINI_VISION_MODEL
        
        if not self.api_key:
            raise ValueError("Gemini API key required for vision detection! Set GEMINI_API_KEY in .env")
        
        # Configure the Gemini API
        genai.configure(api_key=self.api_key)
        
        # Initialize the model
        self.model = genai.GenerativeModel(
            model_name=self.vision_model,
            generation_config=genai.GenerationConfig(
                temperature=0.3,  # Lower temp for more consistent detection
                max_output_tokens=100,  # Minimal buffer - actual response is ~60 tokens
            )
        )
        
        # Cache for reducing API calls (thread-safe)
        self._cache_lock = threading.Lock()
        self.last_detection_time = 0
        self.last_detection_result = None
        self.detection_cache_duration = 3.0  # Cache for 3 seconds (matches detection interval)
        
        # System prompt (same as OpenAI version for consistency)
        self.system_prompt = self._build_system_prompt()
        
        logger.info(f"Gemini vision detector initialized with {self.vision_model}")
    
    def _frame_to_pil_image(self, frame: np.ndarray) -> Image.Image:
        """
        Convert OpenCV frame to PIL Image for Gemini API.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            PIL Image object
        """
        # Resize to reduce token usage (smaller = cheaper)
        resized = cv2.resize(frame, (640, 480))
        
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        # Convert to PIL Image
        pil_image = Image.fromarray(rgb_frame)
        
        return pil_image
    
    def _build_system_prompt(self) -> str:
        """
        Build the system prompt with all detection rules.
        
        Returns:
            System prompt string with all detection instructions
        """
        return """You are a focus tracking AI analyzing webcam frames. Respond with ONLY valid JSON.

RESPONSE FORMAT (no other text):
{"person_present": true/false, "at_desk": true/false, "gadget_visible": true/false, "gadget_confidence": 0.0-1.0, "distraction_type": "phone"/"tablet"/"controller"/"tv"/"none"}

PRESENCE DETECTION (person_present):
- TRUE: Any human body part visible (face, torso, arms, hands, etc.)
- FALSE: No human visible at all (empty room, only furniture)

DESK PROXIMITY (at_desk) - LENIENT, DISTANCE-BASED:
- TRUE: Person is at or near their desk/work area
  This includes: sitting at desk, leaning back, standing briefly near desk
  Mark TRUE if person's upper body fills a decent portion of the frame
- FALSE: Person appears small/distant (in background, across room, walking away)
  If person appears to fill less than 1/3 of the frame height, mark as away

Face orientation does NOT matter - looking down, sideways, or face out of frame is OK.
When in doubt about distance, lean toward at_desk=true.

GADGET DETECTION - POSITION-BASED RULES:

DEVICE IN HANDS = ALWAYS A DISTRACTION:
If phone/tablet is HELD IN HANDS, it counts as a distraction regardless of:
- Screen state (on, off, dark, lit - doesn't matter)
- Where person is looking (at phone or away - doesn't matter)
- Holding a phone in hands = distraction, period

DEVICE ON TABLE = ONLY if actively viewing:
Phone/tablet on table only counts if BOTH conditions met:
- Screen is visibly lit/glowing AND
- User is clearly looking at it

DETECT AS GADGET (gadget_visible=true):
1. Phone/tablet held in hands (ANY screen state, ANY gaze direction)
2. Game controller actively being gripped
3. Phone on table with lit screen AND user staring at it

DO NOT DETECT (gadget_visible=false):
- Phone lying flat on table (not held)
- Phone on table with screen off
- Phone on table, screen on but user NOT looking at it
- Device face-down on table
- Smartwatch/Apple Watch (never a distraction)
- Person working on computer/laptop
- Unclear rectangular objects (when in doubt, don't detect)

CONFIDENCE:
- Phone clearly held in hands → confidence >= 0.8
- Game controller in hands → confidence >= 0.7
- Lit screen on table, user staring at it → confidence >= 0.6
- Device on table not being looked at → confidence = 0.0

RULES:
- If person_present=false, then at_desk=false
- Phone in hands = automatic detection (screen state irrelevant)
- Phone on table = only detect if screen lit AND user looking"""
    
    def analyze_frame(self, frame: np.ndarray, use_cache: bool = True) -> Dict[str, Any]:
        """
        Analyze frame using Gemini Vision API.
        
        Args:
            frame: BGR image from camera
            use_cache: Whether to use cached results (reduces API calls)
            
        Returns:
            Dictionary with detection results:
            {
                "person_present": bool (any body part visible),
                "at_desk": bool (body parts appear large/close in frame),
                "gadget_visible": bool (device in hands OR on table being looked at),
                "gadget_confidence": float (0-1),
                "distraction_type": str (phone, tablet, controller, tv, or none)
            }
        """
        # Check cache (thread-safe)
        current_time = time.time()
        with self._cache_lock:
            if use_cache and self.last_detection_result is not None and \
               (current_time - self.last_detection_time) < self.detection_cache_duration:
                return self.last_detection_result
        
        try:
            # Convert frame to PIL Image
            pil_image = self._frame_to_pil_image(frame)
            
            # Create the prompt with system instructions and user request
            prompt = f"{self.system_prompt}\n\nAnalyze this frame:"
            
            # Call Gemini Vision API
            response = self.model.generate_content([prompt, pil_image])
            
            # Extract response content
            content = response.text
            
            # Debug log the response
            logger.debug(f"Gemini API raw response: {content[:200] if content else 'EMPTY'}")
            
            if not content or content.strip() == "":
                logger.error("Empty response from Gemini API")
                raise ValueError("Empty response from Gemini Vision API")
            
            # Try to extract JSON if there's extra text
            content = content.strip()
            
            # Sometimes the response has backticks or extra text
            if '```json' in content:
                # Extract JSON from markdown code block
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()
            elif '{' in content and '}' in content:
                # Extract just the JSON part
                start = content.index('{')
                end = content.rindex('}') + 1
                content = content[start:end]
            
            # Parse JSON response
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON. Content: {content[:500]}")
                raise
            
            # Validate and normalize result
            detection_result = {
                "person_present": result.get("person_present", False),
                "at_desk": result.get("at_desk", True),  # Default True for backward compat
                "gadget_visible": result.get("gadget_visible", False),
                "gadget_confidence": float(result.get("gadget_confidence", 0.0)),
                "distraction_type": result.get("distraction_type", "none")
            }
            
            # Cache result (thread-safe)
            with self._cache_lock:
                self.last_detection_result = detection_result
                self.last_detection_time = current_time
            
            # Log detection
            if detection_result["gadget_visible"]:
                logger.info(f"📱 Gadget detected by Gemini! Type: {detection_result['distraction_type']}, Confidence: {detection_result['gadget_confidence']:.2f}")
            
            # Log distance detection (person visible but far from desk)
            if detection_result["person_present"] and not detection_result["at_desk"]:
                logger.info("👤 Person visible but far from desk - marking as away")
            
            return detection_result
            
        except Exception as e:
            logger.error(f"Gemini Vision API error: {e}")
            # Return safe default
            return {
                "person_present": True,  # Assume present on error
                "at_desk": True,  # Assume at desk on error
                "gadget_visible": False,
                "gadget_confidence": 0.0,
                "distraction_type": "none"
            }
    
    def detect_presence(self, frame: np.ndarray) -> bool:
        """
        Detect if person is present using Gemini Vision.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if person detected, False otherwise
        """
        result = self.analyze_frame(frame)
        return result["person_present"]
    
    def detect_gadget_usage(self, frame: np.ndarray) -> bool:
        """
        Detect if a gadget is being used based on position-based rules.
        
        Gadgets include: phones, tablets, game controllers, Nintendo Switch, TV, etc.
        
        Position-based detection rules:
        - Device IN HANDS: Always counts as usage (screen state irrelevant)
        - Device ON TABLE: Only counts if screen lit AND user looking at it
        
        Will count as usage:
        - Phone/tablet held in hands (any screen state)
        - Game controller in hands
        - Phone on table with screen on AND user looking at it
        
        Will NOT count as usage:
        - Phone on table with screen off
        - Phone on table with screen on but user NOT looking at it
        - Device face-down on table
        - Smartwatch/Apple Watch (never a distraction)
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if gadget is being used with high confidence, False otherwise
        """
        result = self.analyze_frame(frame)
        
        # Gadget detected if visible AND confidence > threshold
        return result["gadget_visible"] and result["gadget_confidence"] > 0.5
    
    def get_detection_state(self, frame: np.ndarray) -> Dict[str, bool]:
        """
        Get complete detection state for a frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Dictionary with detection results including:
            - present: Any body part visible in frame
            - at_desk: Body parts appear large/close (distance-based, face-independent)
            - gadget_suspected: Device in hands OR on table being looked at
            - distraction_type: Type of distraction detected (phone, tablet, controller, tv, none)
        """
        result = self.analyze_frame(frame)
        
        return {
            "present": result["person_present"],
            "at_desk": result.get("at_desk", True),  # Default True for backward compat
            "gadget_suspected": result["gadget_visible"] and result["gadget_confidence"] > 0.5,
            "distraction_type": result["distraction_type"]
        }
