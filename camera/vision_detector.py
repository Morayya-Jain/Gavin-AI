"""Vision-based detection using OpenAI Vision API."""

import cv2
import numpy as np
import base64
import logging
from typing import Dict, Optional, List
from openai import OpenAI
import config
import time

logger = logging.getLogger(__name__)


class VisionDetector:
    """
    Uses OpenAI Vision API (GPT-4o/GPT-4o-mini with vision) to detect:
    - Person presence
    - Active gadget usage (phones, tablets, iPads, game controllers, Nintendo Switch, TV, etc.)
    - Other distractions
    
    Note: Smartwatches/Apple Watches are explicitly EXCLUDED from detection
    as they are not considered distractions (used for time/notifications).
    
    Much more accurate than hardcoded rules!
    
    Important: Gadget detection only triggers when BOTH conditions are met:
    1. Person's attention/gaze is directed AT the gadget
    2. Gadget screen/display is ON or device is actively being used
    
    Position (on desk vs. in hands) doesn't matter - it's about attention and engagement.
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
        
        # Cache for reducing API calls
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

DESK PROXIMITY (at_desk):
TRUE: Face/upper body clearly visible, at typical webcam working distance
FALSE: Person small/distant, roaming in background, far from desk

GADGET DETECTION - ONLY detect if BOTH conditions met:
1. Device screen ON or actively being used
2. Person's eyes/attention directed AT the gadget

Gadgets: phones, tablets, game controllers, Nintendo Switch, Steam Deck, TV

DO NOT detect if:
- Person looking elsewhere (not at device)
- Device screen OFF/face-down
- Person focused on work (computer, book)
- Controller just sitting on desk
- Smartwatch/Apple Watch (NOT a distraction - used for time/notifications)

RULES:
- person_present=true if any body part visible (even far away)
- If unsure about gadget usage, set confidence below 0.5
- If person_present=false, set at_desk=false"""
    
    def analyze_frame(self, frame: np.ndarray, use_cache: bool = True) -> Dict[str, any]:
        """
        Analyze frame using OpenAI Vision API.
        
        Args:
            frame: BGR image from camera
            use_cache: Whether to use cached results (reduces API calls)
            
        Returns:
            Dictionary with detection results:
            {
                "person_present": bool,
                "at_desk": bool (person is at working distance from camera),
                "gadget_visible": bool (attention + device active, position irrelevant),
                "gadget_confidence": float (0-1),
                "distraction_type": str (phone, tablet, controller, tv, or none)
            }
        
        Note:
            at_desk is True when person is at typical working distance (face/upper body
            clearly visible). False when person is far away/roaming in background.
            
            gadget_visible only returns True when BOTH conditions are met:
            1. Person's attention/gaze is directed AT the gadget
            2. Gadget is actively being used (screen ON or engaged with device)
            
            Position doesn't matter - gadget can be on desk or in hands.
            What matters is attention + active engagement.
        """
        # Check cache
        current_time = time.time()
        if use_cache and self.last_detection_result and \
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
                temperature=0.3  # Lower temp for more consistent detection
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
            import json
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
            
            # Cache result
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
        Detect if a gadget is being ACTIVELY USED (not just visible).
        
        Gadgets include: phones, tablets, game controllers, Nintendo Switch, TV, etc.
        
        Active usage requires BOTH:
        1. Person's attention/gaze directed AT the gadget
        2. Gadget is active (screen ON or device being used)
        
        Position irrelevant - gadget can be:
        - On desk (if person looking at it and it's active)
        - In hands (if person engaged with it)
        
        Will NOT count as usage:
        - Gadget on desk but person looking at computer/elsewhere
        - Gadget screen OFF or put away
        - Gadget visible but not being actively engaged with
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if gadget is being actively used with high confidence, False otherwise
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
            - present: Person is visible in frame
            - at_desk: Person is at working distance (not roaming far away)
            - gadget_suspected: Person is actively using a gadget (phone, tablet, controller, etc.)
            - distraction_type: Type of distraction detected (phone, tablet, controller, tv, none)
        """
        result = self.analyze_frame(frame)
        
        return {
            "present": result["person_present"],
            "at_desk": result.get("at_desk", True),  # Default True for backward compat
            "gadget_suspected": result["gadget_visible"] and result["gadget_confidence"] > 0.5,
            "distraction_type": result["distraction_type"]
        }
