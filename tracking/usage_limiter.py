"""
Usage Limiter for BrainDock MVP.

Tracks cumulative usage time across sessions and enforces a time limit.
Users can unlock additional time by entering a secret password.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)


class UsageLimiter:
    """
    Manages MVP usage time limits.
    
    Tracks total usage time across all sessions and provides methods
    to check remaining time, record usage, and unlock additional time
    via password authentication.
    """
    
    def __init__(self):
        """Initialize the usage limiter and load existing usage data."""
        self.data_file: Path = config.USAGE_DATA_FILE
        self.data = self._load_data()
        
    def _load_data(self) -> dict:
        """
        Load usage data from JSON file.
        
        Returns:
            Dict containing usage tracking data.
        """
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    logger.debug(f"Loaded usage data: {data}")
                    return data
            except (json.JSONDecodeError, IOError, OSError, PermissionError) as e:
                logger.warning(f"Failed to load usage data: {e}. Starting fresh.")
        
        # Default data for new users
        return {
            "total_used_seconds": 0,
            "total_granted_seconds": config.MVP_LIMIT_SECONDS,
            "extensions_granted": 0,
            "first_use": None,
            "last_session_end": None
        }
    
    def _save_data(self) -> None:
        """Save usage data to JSON file."""
        try:
            # Ensure parent directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            logger.debug(f"Saved usage data: {self.data}")
        except IOError as e:
            logger.error(f"Failed to save usage data: {e}")
    
    def get_remaining_seconds(self) -> int:
        """
        Get remaining usage time in seconds.
        
        Returns:
            Number of seconds remaining (clamped to 0 minimum).
        """
        remaining = self.data["total_granted_seconds"] - self.data["total_used_seconds"]
        return max(0, remaining)
    
    def get_total_granted_seconds(self) -> int:
        """
        Get total granted time in seconds.
        
        Returns:
            Total seconds granted (initial + extensions).
        """
        return self.data["total_granted_seconds"]
    
    def get_total_used_seconds(self) -> int:
        """
        Get total used time in seconds.
        
        Returns:
            Total seconds used across all sessions.
        """
        return self.data["total_used_seconds"]
    
    def get_extensions_count(self) -> int:
        """
        Get number of time extensions granted.
        
        Returns:
            Number of times user has unlocked additional time.
        """
        return self.data["extensions_granted"]
    
    def is_time_exhausted(self) -> bool:
        """
        Check if usage time is exhausted.
        
        Returns:
            True if no time remaining, False otherwise.
        """
        return self.get_remaining_seconds() <= 0
    
    def record_usage(self, seconds: int) -> None:
        """
        Record usage time.
        
        Args:
            seconds: Number of seconds to add to total usage. Must be non-negative.
        
        Raises:
            ValueError: If seconds is negative.
        """
        if seconds < 0:
            raise ValueError("Usage seconds must be non-negative")
        
        if self.data["first_use"] is None:
            self.data["first_use"] = datetime.now().isoformat()
        
        self.data["total_used_seconds"] += seconds
        self._save_data()
    
    def end_session(self) -> None:
        """Record the end of a session."""
        self.data["last_session_end"] = datetime.now().isoformat()
        self._save_data()
    
    def validate_password(self, password: str) -> bool:
        """
        Validate the unlock password.
        
        Args:
            password: Password entered by user.
            
        Returns:
            True if password is correct, False otherwise.
        """
        correct_password = config.MVP_UNLOCK_PASSWORD
        
        # If no password is configured, don't allow unlocking
        if not correct_password:
            logger.warning("No MVP_UNLOCK_PASSWORD configured in .env")
            return False
        
        return password == correct_password
    
    def grant_extension(self) -> int:
        """
        Grant a time extension (after password validation).
        
        Returns:
            Number of seconds added.
        """
        extension_seconds = config.MVP_EXTENSION_SECONDS
        self.data["total_granted_seconds"] += extension_seconds
        self.data["extensions_granted"] += 1
        self._save_data()
        
        logger.info(f"Granted {extension_seconds}s extension. "
                   f"Total granted: {self.data['total_granted_seconds']}s")
        
        return extension_seconds
    
    def format_time(self, seconds: int, full_precision: bool = False) -> str:
        """
        Format seconds as human-readable time string.
        
        Args:
            seconds: Number of seconds.
            full_precision: If True, always show all non-zero time components
                           including seconds even when hours > 0. Default False
                           for compact display (omits seconds when hours present).
            
        Returns:
            Formatted string like "1h 30m" or "45m" or "30s".
            With full_precision: "1h 30m 45s" or "2h 0m 0s".
        """
        if seconds < 0:
            return "0s"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or (full_precision and hours > 0):
            # Show minutes if non-zero, or if full_precision and hours exist
            parts.append(f"{minutes}m")
        if secs > 0 or full_precision:
            # Show seconds if non-zero, or always if full_precision
            if hours == 0 or full_precision:
                parts.append(f"{secs}s")
        
        return " ".join(parts) if parts else "0s"
    
    def get_status_summary(self) -> str:
        """
        Get a summary of usage status with full time precision.
        
        Returns:
            Human-readable status string with exact time values.
        """
        remaining = self.get_remaining_seconds()
        used = self.get_total_used_seconds()
        granted = self.get_total_granted_seconds()
        extensions = self.get_extensions_count()
        
        # Use full_precision=True for detailed popup display
        summary = (
            f"Time remaining: {self.format_time(remaining, full_precision=True)}\n"
            f"Time used: {self.format_time(used, full_precision=True)}\n"
            f"Total granted: {self.format_time(granted, full_precision=True)}"
        )
        
        if extensions > 0:
            summary += f"\nExtensions: {extensions}"
        
        return summary


# Global instance for easy access
_limiter_instance: Optional[UsageLimiter] = None


def get_usage_limiter() -> UsageLimiter:
    """
    Get the global UsageLimiter instance.
    
    Returns:
        Singleton UsageLimiter instance.
    """
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = UsageLimiter()
    return _limiter_instance
