"""Base protocol and shared utilities for vision detectors."""

import json
import logging
import time
import threading
from typing import Protocol, Dict, Any, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


# Default safe result returned on errors/timeouts
DEFAULT_SAFE_RESULT: Dict[str, Any] = {
    "person_present": True,  # Assume present on error (fail-safe)
    "at_desk": True,  # Assume at desk on error
    "gadget_visible": False,  # Don't flag gadgets on error
    "gadget_confidence": 0.0,
    "distraction_type": "none"
}


def get_safe_default_result() -> Dict[str, Any]:
    """
    Get a safe default detection result for error/timeout scenarios.
    
    Returns:
        Dictionary with fail-safe detection values (assumes user is present
        and focussed to avoid false distraction alerts on API errors).
    """
    return DEFAULT_SAFE_RESULT.copy()


def extract_json_from_response(content: str) -> str:
    """
    Extract JSON from API response that may contain markdown or extra text.
    
    Handles common response formats:
    - Pure JSON
    - JSON wrapped in ```json ... ``` code blocks
    - JSON wrapped in ``` ... ``` code blocks
    - JSON embedded in surrounding text
    
    Args:
        content: Raw response content from API
        
    Returns:
        Extracted JSON string (may still need json.loads)
        
    Raises:
        ValueError: If no JSON-like content found
    """
    if not content or not content.strip():
        raise ValueError("Empty response content")
    
    content = content.strip()
    
    # Try to extract JSON from markdown code blocks
    if '```json' in content:
        # Extract JSON from ```json ... ``` block
        try:
            json_part = content.split('```json')[1].split('```')[0].strip()
            return json_part
        except IndexError:
            pass
    
    if '```' in content:
        # Extract from generic ``` ... ``` block
        try:
            json_part = content.split('```')[1].split('```')[0].strip()
            return json_part
        except IndexError:
            pass
    
    # Try to extract JSON object from surrounding text
    # Handle nested braces by finding matching pairs
    if '{' in content and '}' in content:
        try:
            start = content.index('{')
            # Find the matching closing brace by counting nesting
            depth = 0
            end = start
            for i, char in enumerate(content[start:], start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            
            if end > start:
                return content[start:end]
        except ValueError:
            pass
    
    # Return as-is if no transformation needed
    return content


def parse_detection_response(content: str) -> Dict[str, Any]:
    """
    Parse and validate detection response from vision API.
    
    Extracts JSON, parses it, and validates/normalizes the result
    to match expected detection schema.
    
    Args:
        content: Raw API response content
        
    Returns:
        Normalized detection result dictionary
        
    Raises:
        ValueError: If content is empty
        json.JSONDecodeError: If JSON parsing fails
    """
    # Extract JSON from potential markdown wrapping
    json_str = extract_json_from_response(content)
    
    # Parse JSON
    result = json.loads(json_str)
    
    # Normalize and validate result
    # Handle gadget_confidence type safely - API might return string like "high"
    try:
        gadget_confidence = float(result.get("gadget_confidence", 0.0))
    except (ValueError, TypeError):
        gadget_confidence = 0.0
        logger.warning(f"Invalid gadget_confidence value: {result.get('gadget_confidence')}, defaulting to 0.0")
    
    return {
        "person_present": result.get("person_present", False),
        "at_desk": result.get("at_desk", True),  # Default True for backward compat
        "gadget_visible": result.get("gadget_visible", False),
        "gadget_confidence": gadget_confidence,
        "distraction_type": result.get("distraction_type", "none")
    }


class DetectionCache:
    """
    Thread-safe cache for detection results.
    
    Reduces API calls by caching recent results for a configurable duration.
    """
    
    def __init__(self, cache_duration: float = 3.0):
        """
        Initialize detection cache.
        
        Args:
            cache_duration: How long to cache results in seconds (default 3.0)
        """
        self._lock = threading.Lock()
        self._cache_duration = cache_duration
        self._last_result: Optional[Dict[str, Any]] = None
        self._last_time: float = 0.0
    
    def get(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Get cached result if still valid.
        
        Returns:
            Tuple of (is_valid, result). If is_valid is False, result is None.
        """
        current_time = time.time()
        with self._lock:
            if self._last_result is not None and \
               (current_time - self._last_time) < self._cache_duration:
                return True, self._last_result
            return False, None
    
    def set(self, result: Dict[str, Any]) -> None:
        """
        Store a result in the cache.
        
        Args:
            result: Detection result to cache
        """
        with self._lock:
            self._last_result = result
            self._last_time = time.time()
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._last_result = None
            self._last_time = 0.0


def retry_with_backoff(
    func,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,)
):
    """
    Execute a function with exponential backoff retry on transient errors.
    
    Args:
        func: Callable to execute (no arguments)
        max_retries: Maximum number of retry attempts (default 3)
        initial_delay: Initial delay in seconds between retries (default 1.0)
        max_delay: Maximum delay in seconds (default 10.0)
        backoff_factor: Multiplier for delay after each retry (default 2.0)
        retryable_exceptions: Tuple of exception types to retry on
        
    Returns:
        Result from successful function call
        
    Raises:
        Last exception if all retries fail
    """
    import time as time_module  # Local import to avoid name collision
    
    last_exception = None
    delay = initial_delay
    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            
            if attempt < max_retries:
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} after error: {e}. "
                    f"Waiting {delay:.1f}s..."
                )
                time_module.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
            else:
                logger.error(f"All {max_retries} retries failed: {e}")
    
    raise last_exception


class VisionDetectorProtocol(Protocol):
    """
    Protocol defining the interface for vision detectors.
    
    Both OpenAI and Gemini detectors must implement these methods
    to ensure consistent behaviour across providers.
    """
    
    def analyze_frame(self, frame: np.ndarray, use_cache: bool = True) -> Dict[str, Any]:
        """
        Analyse a camera frame for presence and gadget detection.
        
        Args:
            frame: BGR image from camera (numpy array)
            use_cache: Whether to use cached results to reduce API calls
            
        Returns:
            Dictionary with detection results:
            {
                "person_present": bool,
                "at_desk": bool,
                "gadget_visible": bool,
                "gadget_confidence": float (0-1),
                "distraction_type": str
            }
        """
        ...
    
    def detect_presence(self, frame: np.ndarray) -> bool:
        """
        Detect if a person is present in the frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if person detected, False otherwise
        """
        ...
    
    def detect_gadget_usage(self, frame: np.ndarray) -> bool:
        """
        Detect if a gadget is being actively used.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            True if gadget usage detected with high confidence
        """
        ...
    
    def get_detection_state(self, frame: np.ndarray) -> Dict[str, bool]:
        """
        Get complete detection state for a frame.
        
        Args:
            frame: BGR image from camera
            
        Returns:
            Dictionary with detection state:
            {
                "present": bool,
                "at_desk": bool,
                "gadget_suspected": bool,
                "distraction_type": str
            }
        """
        ...
