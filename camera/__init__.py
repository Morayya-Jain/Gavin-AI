"""
Camera detection module with provider-agnostic vision detection.

Supports multiple vision providers (OpenAI, Gemini) via factory pattern.
"""

import logging
from typing import TYPE_CHECKING, Optional, Set

import config

if TYPE_CHECKING:
    from camera.base_detector import VisionDetectorProtocol

logger = logging.getLogger(__name__)


def create_vision_detector(enabled_gadgets: Optional[Set[str]] = None) -> "VisionDetectorProtocol":
    """
    Create a vision detector based on the configured provider.
    
    Uses VISION_PROVIDER from config to determine which detector to instantiate.
    Supported providers: "openai" (default), "gemini"
    
    Args:
        enabled_gadgets: Set of gadget type ids to detect as distractions (defaults to config.DEFAULT_ENABLED_GADGETS)
    
    Returns:
        VisionDetectorProtocol: The appropriate vision detector instance
        
    Raises:
        ValueError: If the configured provider is not supported or API key is missing
    """
    provider = config.VISION_PROVIDER.lower()
    
    if provider == "gemini":
        from camera.gemini_detector import GeminiVisionDetector
        logger.info("Using Gemini vision provider")
        return GeminiVisionDetector(enabled_gadgets=enabled_gadgets)
    elif provider == "openai":
        from camera.vision_detector import VisionDetector
        logger.info("Using OpenAI vision provider")
        return VisionDetector(enabled_gadgets=enabled_gadgets)
    else:
        # Unknown provider - log warning and fallback to OpenAI
        from camera.vision_detector import VisionDetector
        logger.warning(f"Unknown vision provider '{provider}', defaulting to OpenAI. "
                      f"Supported providers: 'openai', 'gemini'")
        return VisionDetector(enabled_gadgets=enabled_gadgets)


def get_event_type(detection_state: dict) -> str:
    """
    Determine event type from detection state.
    
    A person must be both present AND at desk (close to camera) to be
    considered focussed. If they're visible but far away (roaming around
    the room), they're treated as away.
    
    Args:
        detection_state: Dictionary with detection results
            - present: Person is visible in frame
            - at_desk: Person is at working distance
            - gadget_suspected: Person is actively using a gadget (phone, tablet, etc.)
        
    Returns:
        Event type string (EVENT_PRESENT, EVENT_AWAY, or EVENT_GADGET_SUSPECTED)
    """
    is_present = detection_state.get("present", False)
    is_at_desk = detection_state.get("at_desk", True)  # Default True for backward compat
    
    # Must be present AND at desk to count as working
    if not is_present or not is_at_desk:
        return config.EVENT_AWAY
    elif detection_state.get("gadget_suspected", False):
        return config.EVENT_GADGET_SUSPECTED
    else:
        return config.EVENT_PRESENT
