"""Vision-based detection using OpenAI Vision API."""

import cv2
import numpy as np
import base64
import logging
import socket
from typing import Dict, Optional, Any

import openai
from openai import OpenAI

import config
from camera.base_detector import (
    get_safe_default_result,
    parse_detection_response,
    DetectionCache,
    retry_with_backoff
)

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
        
        # Thread-safe cache for reducing API calls
        self._cache = DetectionCache(cache_duration=3.0)  # Cache for 3 seconds
        
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
{"person_present": true/false, "at_desk": true/false, "gadget_visible": true/false, "gadget_confidence": 0.0-1.0, "distraction_type": "phone"/"tablet"/"controller"/"tv"/"wearable"/"none"}

PRESENCE DETECTION (person_present):
- TRUE: Any human body part visible (face, torso, arms, hands, etc.)
- FALSE: No human visible at all (empty room, only furniture)

DESK PROXIMITY (at_desk) - LENIENT, DISTANCE-BASED:
- TRUE: Person is at or near their desk/work area (sitting, leaning back, standing briefly)
- FALSE: Person appears small/distant (in background, across room)
When in doubt, lean toward at_desk=true.

=== CRITICAL: SMARTWATCH/WEARABLE EXCLUSION ===
NEVER flag smartwatches or wearables as distractions!

Visual identification of WEARABLES (NOT distractions):
- Small device (1-2 inches) worn ON THE WRIST, attached to arm with a band
- Round or square face, similar size to a traditional watch
- Apple Watch, Fitbit, Galaxy Watch, any fitness tracker
- If device is ON THE WRIST/ARM = it's a wearable, NOT a phone

If you see a wrist-worn device: distraction_type="wearable", gadget_visible=false

=== PHONE/TABLET IDENTIFICATION ===
Visual identification of PHONES (5-7 inch rectangular devices):
- Held in ONE or BOTH HANDS, not attached to body
- Larger than a watch, smaller than a tablet
- Typically held in portrait or landscape orientation

Visual identification of TABLETS (8+ inch devices):
- Large rectangular screen held in hands or propped up
- iPad, Android tablet, e-reader

GADGET DETECTION RULES:

PHONE/TABLET IN HANDS = DISTRACTION:
- Device held in hands (not on wrist) = gadget_visible=true
- Screen state doesn't matter (on/off/dark)
- Gaze direction doesn't matter

PHONE/TABLET ON TABLE = Only if actively viewing:
- Screen visibly lit AND user clearly looking at it

DETECT (gadget_visible=true, confidence >= 0.8):
1. Phone held in hands (5-7 inch device, not wrist-worn)
2. Tablet held in hands (8+ inch device)
3. Game controller being gripped

DETECT with lower confidence (0.6-0.7):
- Phone on table with lit screen AND user staring at it

DO NOT DETECT (gadget_visible=false):
- Wrist-worn devices (watches, fitness trackers) - use distraction_type="wearable"
- Phone lying on table (not in hands)
- Phone on table with screen off
- Device face-down
- Person working on computer/laptop
- Unclear objects (when in doubt, don't detect)

RULES:
- If person_present=false, then at_desk=false
- Wrist-worn device = NEVER a distraction (wearable type)
- Phone in hands = distraction (not wrist = not a watch)"""
    
    def analyze_frame(self, frame: np.ndarray, use_cache: bool = True) -> Dict[str, Any]:
        """
        Analyse frame using OpenAI Vision API.
        
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
        if use_cache:
            is_valid, cached_result = self._cache.get()
            if is_valid and cached_result is not None:
                return cached_result
        
        try:
            # Encode frame
            base64_image = self._encode_frame(frame)
            
            # Define the API call function for retry logic
            def make_api_call():
                return self.client.chat.completions.create(
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
            
            # Call OpenAI Vision API with retry for transient errors
            # Matches Gemini detector behaviour for consistency
            # Includes socket errors for network issues (DNS, connection failures)
            response = retry_with_backoff(
                make_api_call,
                max_retries=2,
                initial_delay=1.0,
                retryable_exceptions=(
                    openai.APIConnectionError,
                    openai.APITimeoutError,
                    openai.RateLimitError,
                    openai.InternalServerError,  # Server-side errors are retryable
                    ConnectionError,
                    TimeoutError,
                    socket.timeout,
                    socket.gaierror,  # DNS lookup failures
                    OSError,  # Covers various network-related OS errors
                )
            )
            
            # Extract response content
            content = response.choices[0].message.content
            
            # Debug log the response
            logger.debug(f"Vision API raw response: {content[:200] if content else 'EMPTY'}")
            
            if not content or content.strip() == "":
                logger.error("Empty response from Vision API")
                raise ValueError("Empty response from OpenAI Vision API")
            
            # Parse and validate response using shared utility
            detection_result = parse_detection_response(content)
            
            # Cache result (thread-safe)
            self._cache.set(detection_result)
            
            # Log detection
            if detection_result["gadget_visible"]:
                logger.info(f"📱 Gadget detected by AI! Type: {detection_result['distraction_type']}, Confidence: {detection_result['gadget_confidence']:.2f}")
            
            # Log distance detection (person visible but far from desk)
            if detection_result["person_present"] and not detection_result["at_desk"]:
                logger.info("👤 Person visible but far from desk - marking as away")
            
            return detection_result
            
        except openai.APITimeoutError as e:
            logger.warning(f"OpenAI Vision API timeout: {e}")
            return get_safe_default_result()
        except openai.AuthenticationError as e:
            # Authentication errors are not transient - log at ERROR level
            logger.error(f"OpenAI API authentication error - check API key: {e}")
            return get_safe_default_result()
        except openai.APIConnectionError as e:
            logger.warning(f"OpenAI API connection error: {e}")
            return get_safe_default_result()
        except openai.RateLimitError as e:
            logger.warning(f"OpenAI API rate limit reached: {e}")
            return get_safe_default_result()
        except Exception as e:
            logger.error(f"Vision API error: {e}")
            return get_safe_default_result()
    
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
    
    def get_detection_state(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Get complete detection state for a frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Dictionary with detection results including:
            - present: Any body part visible in frame
            - at_desk: Body parts appear large/close (distance-based, face-independent)
            - gadget_suspected: Device in hands OR on table being looked at (excludes wearables)
            - gadget_confidence: Raw confidence score (0-1) for hybrid filtering
            - distraction_type: Type of distraction detected (phone, tablet, controller, tv, wearable, none)
        """
        result = self.analyze_frame(frame)
        
        # Get raw values
        gadget_visible = result["gadget_visible"]
        gadget_confidence = result["gadget_confidence"]
        distraction_type = result["distraction_type"]
        
        # Filter out wearables - they are never distractions
        # Even if AI detects something, if it's classified as "wearable", ignore it
        is_wearable = distraction_type == "wearable"
        
        # Gadget is suspected only if:
        # 1. Gadget is visible with sufficient confidence (>0.5)
        # 2. It's NOT a wearable (smartwatch, fitness tracker)
        gadget_suspected = (
            gadget_visible 
            and gadget_confidence > 0.5 
            and not is_wearable
        )
        
        return {
            "present": result["person_present"],
            "at_desk": result.get("at_desk", True),  # Default True for backward compat
            "gadget_suspected": gadget_suspected,
            "gadget_confidence": gadget_confidence,  # Raw confidence for hybrid filtering
            "distraction_type": distraction_type
        }
