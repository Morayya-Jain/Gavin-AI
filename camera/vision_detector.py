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
    - Phone usage
    - Other distractions
    
    Much more accurate than hardcoded rules!
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
        self.detection_cache_duration = 1.0  # Cache for 1 second
        
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
                "phone_visible": bool,
                "phone_confidence": float (0-1),
                "distraction_type": str or None,
                "description": str
            }
        """
        # Check cache
        current_time = time.time()
        if use_cache and self.last_detection_result and \
           (current_time - self.last_detection_time) < self.detection_cache_duration:
            return self.last_detection_result
        
        try:
            # Encode frame
            base64_image = self._encode_frame(frame)
            
            # Create prompt - be very explicit about JSON format
            prompt = """You are analyzing a webcam frame for a student focus tracking system.

You MUST respond with ONLY a valid JSON object (no other text before or after).

Analyze the image and return this exact JSON format:
{
  "person_present": true or false,
  "phone_visible": true or false,
  "phone_confidence": 0.0 to 1.0,
  "distraction_type": "phone" or "none",
  "description": "brief description of what you see"
}

Be accurate:
- Only set phone_visible to true if you clearly see a smartphone/mobile phone
- Set person_present to true if you see a person's face or body
- If unsure about phone, set confidence below 0.5

Respond with ONLY the JSON object, nothing else."""
            
            # Call OpenAI Vision API
            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
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
                max_tokens=200,
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
                "phone_visible": result.get("phone_visible", False),
                "phone_confidence": float(result.get("phone_confidence", 0.0)),
                "distraction_type": result.get("distraction_type", "none"),
                "description": result.get("description", "")
            }
            
            # Cache result
            self.last_detection_result = detection_result
            self.last_detection_time = current_time
            
            # Log detection
            if detection_result["phone_visible"]:
                logger.info(f"📱 Phone detected by AI! Confidence: {detection_result['phone_confidence']:.2f}")
            
            return detection_result
            
        except Exception as e:
            logger.error(f"Vision API error: {e}")
            # Return safe default
            return {
                "person_present": True,  # Assume present on error
                "phone_visible": False,
                "phone_confidence": 0.0,
                "distraction_type": "none",
                "description": f"Error: {str(e)}"
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
    
    def detect_phone_usage(self, frame: np.ndarray) -> bool:
        """
        Detect if phone is visible using OpenAI Vision.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if phone detected with high confidence, False otherwise
        """
        result = self.analyze_frame(frame)
        
        # Phone detected if visible AND confidence > threshold
        return result["phone_visible"] and result["phone_confidence"] > 0.5
    
    def get_detection_state(self, frame: np.ndarray) -> Dict[str, bool]:
        """
        Get complete detection state for a frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Dictionary with detection results
        """
        result = self.analyze_frame(frame)
        
        return {
            "present": result["person_present"],
            "phone_suspected": result["phone_visible"] and result["phone_confidence"] > 0.5,
            "distraction_type": result["distraction_type"],
            "ai_description": result["description"]
        }
