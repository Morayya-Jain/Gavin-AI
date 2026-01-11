"""
Determine which detection method to use based on configuration.
"""

import logging
import config

logger = logging.getLogger(__name__)


def get_event_type(detection_state: dict) -> str:
    """
    Determine event type from detection state.
    
    Args:
        detection_state: Dictionary with detection results
        
    Returns:
        Event type string
    """
    if not detection_state.get("present", False):
        return config.EVENT_AWAY
    elif detection_state.get("phone_suspected", False):
        return config.EVENT_PHONE_SUSPECTED
    else:
        return config.EVENT_PRESENT
