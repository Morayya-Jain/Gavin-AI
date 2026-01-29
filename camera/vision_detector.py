"""Vision-based detection using OpenAI Vision API."""

import cv2
import numpy as np
import base64
import json
import logging
import time
from typing import Dict, Optional, Any
import threading

from openai import OpenAI

import config

logger = logging.getLogger(__name__)


class VisionDetector:
    """
    Uses OpenAI Vision API (GPT-4o/GPT-4o-mini with vision) to detect:
    - Person presence (any body part visible)
    - Desk proximity (distance-based, not face-dependent)
    - Active gadget usage (phones, tablets, game controllers, Nintendo Switch, TV, etc.)
    
    Note: Smartwatches/Apple Watches are explicitly EXCLUDED from detection
    as they are not considered distractions (used for time/notifications).
    
    Desk Proximity Detection:
    - Based on how LARGE body parts appear in frame (distance estimation)
    - Face orientation does NOT matter - looking down, sideways, or out of frame is OK
    - If body is close to camera = at_desk, regardless of face visibility
    
    Gadget Detection Rules (position-based):
    - Device IN HANDS: Always a distraction (screen state irrelevant)
    - Device ON TABLE: Only distraction if screen lit AND user looking at it
    - Device face-down or screen off on table: NOT a distraction
    """
    
    def __init__(self, api_key: Optional[str] = None, vision_model: str = "gpt-4o-mini"):
        """
        Initialize vision detector.
        
        Args:
            api_key: OpenAI API key (defaults to config.OPENAI_API_KEY)
            vision_model: Vision model to use (gpt-4o-mini or gpt-4o)
        """
        self.api_key = api_key or config.OPENAI_API_KEY
        self.vision_model = vision_model
        
        if not self.api_key:
            raise ValueError("OpenAI API key required for vision detection!")
        
        self.client = OpenAI(api_key=self.api_key)
        
        # Cache for reducing API calls (thread-safe)
        self._cache_lock = threading.Lock()
        self.last_detection_time = 0
        self.last_detection_result = None
        self.detection_cache_duration = 3.0  # Cache for 3 seconds (matches detection interval)
        
        # System prompt for caching (static instructions - OpenAI caches these)
        self.system_prompt = self._build_system_prompt()
        
        logger.info(f"Vision detector initialized with {vision_model}")
    
    def _encode_frame(self, frame: np.ndarray) -> str:
        """
        Encode frame to base64 for OpenAI API.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Base64 encoded JPEG string
        """
        # Resize to reduce token usage (smaller = cheaper)
        resized = cv2.resize(frame, (640, 480))
        
        # Encode as JPEG
        _, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        
        # Convert to base64
        base64_image = base64.b64encode(buffer).decode('utf-8')
        
        return base64_image
    
    def _build_system_prompt(self) -> str:
        """
        Build the system prompt with all detection rules.
        
        This is separated so OpenAI can cache it across requests,
        reducing input token costs by up to 50% on subsequent calls.
        
        Returns:
            System prompt string with all detection instructions
        """
        return """You are a focus tracking AI analyzing webcam frames. Respond with ONLY valid JSON.

RESPONSE FORMAT (no other text):
{"person_present": true/false, "at_desk": true/false, "gadget_visible": true/false, "gadget_confidence": 0.0-1.0, "distraction_type": "phone"/"tablet"/"controller"/"tv"/"none"}

PRESENCE DETECTION (person_present):
- TRUE: Any human body part visible (face, torso, arms, hands, etc.)
- FALSE: No human visible at all (empty room, only furniture)

DESK PROXIMITY (at_desk) - DISTANCE-BASED, NOT FACE-DEPENDENT:
- TRUE: Body parts appear in frame at reasonable working distance
  Person sitting at desk, even if leaning back slightly, looking down, or face out of frame
  Be LENIENT - if person is clearly at their desk area, mark as at_desk=true
- FALSE: Person appears VERY small/distant (clearly in background, far across room)
  Only mark FALSE if person is obviously far away (tiny silhouette, walking in far background)

Face orientation does NOT matter - looking down, sideways, or face out of frame is OK.
When in doubt, mark at_desk=true if person seems to be in their desk area.

GADGET DETECTION - VERY STRICT to minimize false positives:

MANDATORY REQUIREMENT FOR PHONES/TABLETS:
The screen MUST be visibly LIT/GLOWING to count as in use!
A dark/black/off screen = NOT in use, even if held in hands.

DETECT AS GADGET (gadget_visible=true) ONLY WHEN:
1. Phone/tablet: Screen is VISIBLY LIT (glowing, showing content) AND held in hands
2. Game controller: Actively being gripped in gaming position
3. Phone on table: Screen VISIBLY LIT AND user clearly staring at it

DO NOT DETECT (gadget_visible=false) - BE STRICT:
- Phone with dark/black/off screen (even if in hands)
- Phone screen facing away from camera (can't confirm it's on)
- Person looking down with no visible lit screen
- Hands near phone on table (near ≠ using)
- Phone lying flat on table (regardless of screen state)
- Any rectangular object that MIGHT be a phone but unclear
- Device face-down
- Smartwatch/Apple Watch (never a distraction)
- Person working on computer/laptop
- ANY uncertainty - when in doubt, do NOT detect

KEY: You must see a GLOWING/LIT screen to confirm phone/tablet usage.
Dark screens, unclear objects, or uncertain situations = gadget_visible=false

CONFIDENCE:
- Lit screen clearly visible in hands → confidence >= 0.7
- Lit screen on table, user staring at it → confidence >= 0.6
- Screen not clearly lit or any doubt → confidence below 0.3

RULES:
- If person_present=false, then at_desk=false
- Default to gadget_visible=false unless you are CERTAIN
- False negatives are acceptable, false positives are NOT"""
    
    def analyze_frame(self, frame: np.ndarray, use_cache: bool = True) -> Dict[str, Any]:
        """
        Analyze frame using OpenAI Vision API.
        
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
        
        Note:
            at_desk uses DISTANCE-BASED detection - if body parts appear large in frame,
            person is at desk. Face orientation does NOT matter (looking down, sideways,
            or face out of frame is still "at desk" if body is close).
            
            gadget_visible uses POSITION-BASED rules:
            - Device IN HANDS: Always True (screen state irrelevant)
            - Device ON TABLE: Only True if screen lit AND user looking at it
            - Device face-down or screen off on table: Always False
        """
        # Check cache (thread-safe)
        current_time = time.time()
        with self._cache_lock:
            if use_cache and self.last_detection_result is not None and \
               (current_time - self.last_detection_time) < self.detection_cache_duration:
                return self.last_detection_result
        
        try:
            # Encode frame
            base64_image = self._encode_frame(frame)
            
            # Call OpenAI Vision API with system message for prompt caching
            # System message is cached by OpenAI, reducing costs on subsequent calls
            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Analyze this frame:"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "low"  # Use low detail to save tokens
                                }
                            }
                        ]
                    }
                ],
                max_tokens=100,  # Minimal buffer - actual response is ~60 tokens
                temperature=0.3,  # Lower temp for more consistent detection
                timeout=30.0  # Prevent indefinite hangs on network issues
            )
            
            # Extract response content
            content = response.choices[0].message.content
            
            # Debug log the response
            logger.debug(f"Vision API raw response: {content[:200] if content else 'EMPTY'}")
            
            if not content or content.strip() == "":
                logger.error("Empty response from Vision API")
                raise ValueError("Empty response from OpenAI Vision API")
            
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
                logger.info(f"📱 Gadget detected by AI! Type: {detection_result['distraction_type']}, Confidence: {detection_result['gadget_confidence']:.2f}")
            
            # Log distance detection (person visible but far from desk)
            if detection_result["person_present"] and not detection_result["at_desk"]:
                logger.info("👤 Person visible but far from desk - marking as away")
            
            return detection_result
            
        except Exception as e:
            logger.error(f"Vision API error: {e}")
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
        Detect if person is present using OpenAI Vision.
        
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
