"""
Usage Limiter for BrainDock MVP.

Tracks cumulative usage time across sessions and enforces a time limit.
Users can unlock additional time by entering a secret password.

Includes basic integrity protection to prevent casual file tampering.
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from tracking.analytics import format_duration

logger = logging.getLogger(__name__)

# Salt for integrity hash (obfuscated to prevent easy bypass)
_INTEGRITY_SALT = b"BrainDock_v1_" + b"\x7f\x3a\x9c\x42"


class UsageLimiter:
    """
    Manages MVP usage time limits.
    
    Tracks total usage time across all sessions and provides methods
    to check remaining time, record usage, and unlock additional time
    via password authentication.
    
    Includes integrity protection to detect file tampering.
    """
    
    def __init__(self):
        """Initialize the usage limiter and load existing usage data."""
        self.data_file: Path = config.USAGE_DATA_FILE
        self._tampered: bool = False  # Set True if integrity check fails
        self.data = self._load_data()
    
    def _compute_integrity_hash(self, data: dict) -> str:
        """
        Compute integrity hash for usage data.
        
        Args:
            data: Usage data dictionary (without _integrity field).
            
        Returns:
            Hex string of the integrity hash.
        """
        # Create a canonical string representation of the data
        canonical = json.dumps({
            "total_used_seconds": data.get("total_used_seconds", 0),
            "total_granted_seconds": data.get("total_granted_seconds", 0),
            "extensions_granted": data.get("extensions_granted", 0),
            "first_use": data.get("first_use"),
        }, sort_keys=True)
        
        # Compute HMAC-like hash with salt
        hash_input = _INTEGRITY_SALT + canonical.encode('utf-8')
        return hashlib.sha256(hash_input).hexdigest()[:16]
    
    def _verify_integrity(self, data: dict) -> bool:
        """
        Verify the integrity hash of loaded data.
        
        Args:
            data: Loaded data dictionary with _integrity field.
            
        Returns:
            True if integrity check passes, False otherwise.
        """
        stored_hash = data.get("_integrity")
        if not stored_hash:
            # No integrity hash - might be old data format, allow it
            # but mark for re-save with hash
            return True
        
        computed_hash = self._compute_integrity_hash(data)
        return stored_hash == computed_hash
        
    def _load_data(self) -> dict:
        """
        Load usage data from JSON file with integrity verification.
        
        Returns:
            Dict containing usage tracking data.
        """
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                # Verify data integrity
                if not self._verify_integrity(data):
                    logger.warning("Usage data integrity check failed - possible tampering")
                    self._tampered = True
                    # Return data with time exhausted (user must use password)
                    return {
                        "total_used_seconds": config.MVP_LIMIT_SECONDS,
                        "total_granted_seconds": config.MVP_LIMIT_SECONDS,
                        "extensions_granted": 0,
                        "max_extensions": 3,
                        "first_use": data.get("first_use"),
                        "last_session_end": data.get("last_session_end")
                    }
                
                # Ensure max_extensions field exists (migration for older files)
                if "max_extensions" not in data:
                    data["max_extensions"] = 3
                
                logger.debug(f"Loaded usage data: {data}")
                return data
                
            except (json.JSONDecodeError, IOError, OSError, PermissionError) as e:
                logger.warning(f"Failed to load usage data: {e}")
                # File exists but couldn't be read - treat as tampering
                self._tampered = True
                return {
                    "total_used_seconds": config.MVP_LIMIT_SECONDS,
                    "total_granted_seconds": config.MVP_LIMIT_SECONDS,
                    "extensions_granted": 0,
                    "max_extensions": 3,
                    "first_use": None,
                    "last_session_end": None
                }
        
        # File doesn't exist - new user, grant initial time
        return {
            "total_used_seconds": 0,
            "total_granted_seconds": config.MVP_LIMIT_SECONDS,
            "extensions_granted": 0,
            "max_extensions": 3,
            "first_use": None,
            "last_session_end": None
        }
    
    def _save_data(self) -> None:
        """Save usage data to JSON file with integrity hash."""
        try:
            # Ensure parent directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Add integrity hash before saving
            save_data = dict(self.data)
            save_data["_integrity"] = self._compute_integrity_hash(self.data)
            
            with open(self.data_file, 'w') as f:
                json.dump(save_data, f, indent=2)
            logger.debug(f"Saved usage data with integrity hash")
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to save usage data: {e}")
    
    def reload_data(self, force_trust: bool = False) -> bool:
        """
        Reload usage data from file.
        
        Useful for detecting external changes to the usage data file.
        In development mode (SKIP_LICENSE_CHECK=true), bypasses integrity check.
        
        Args:
            force_trust: If True, trust the file data even if integrity check fails.
                        Automatically enabled in dev mode.
        
        Returns:
            True if data was reloaded and time is now available, False otherwise.
        """
        # In dev mode, always trust the file
        dev_mode = getattr(config, 'SKIP_LICENSE_CHECK', False)
        should_trust = force_trust or dev_mode
        
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                # Verify integrity unless in dev mode or force_trust
                if not should_trust and not self._verify_integrity(data):
                    logger.debug("Reload: integrity check failed, keeping current state")
                    return False
                
                # Update data
                old_remaining = self.get_remaining_seconds()
                self.data = data
                self._tampered = False  # Clear tampered state on successful reload
                new_remaining = self.get_remaining_seconds()
                
                logger.debug(f"Reloaded usage data: {old_remaining}s -> {new_remaining}s remaining")
                
                # Return True if time is now available
                return new_remaining > 0
                
            except (json.JSONDecodeError, IOError, OSError, PermissionError) as e:
                logger.warning(f"Failed to reload usage data: {e}")
                return False
        
        return False
    
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
    
    def get_max_extensions(self) -> int:
        """
        Get maximum allowed extensions.
        
        Returns:
            Maximum number of extensions allowed for this user.
        """
        return self.data.get("max_extensions", 3)
    
    def can_grant_extension(self) -> bool:
        """
        Check if another extension can be granted.
        
        Returns:
            True if extensions_granted < max_extensions, False otherwise.
        """
        return self.data["extensions_granted"] < self.data.get("max_extensions", 3)
    
    def get_remaining_extensions(self) -> int:
        """
        Get number of extensions remaining.
        
        Returns:
            Number of extensions still available.
        """
        max_ext = self.data.get("max_extensions", 3)
        used_ext = self.data["extensions_granted"]
        return max(0, max_ext - used_ext)
    
    def is_time_exhausted(self) -> bool:
        """
        Check if usage time is exhausted.
        
        Returns:
            True if no time remaining, False otherwise.
        """
        return self.get_remaining_seconds() <= 0
    
    def was_tampered(self) -> bool:
        """
        Check if data tampering was detected.
        
        Returns:
            True if integrity check failed on load, False otherwise.
        """
        return self._tampered
    
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
        
        Also clears any tampered state and re-saves with valid integrity hash.
        Respects the max_extensions limit.
        
        Returns:
            Number of seconds added, or 0 if extension limit reached.
        """
        # Check if extension limit reached
        if not self.can_grant_extension():
            logger.warning(f"Extension limit reached ({self.get_extensions_count()}/{self.get_max_extensions()})")
            return 0
        
        extension_seconds = config.MVP_EXTENSION_SECONDS
        
        # Clear tampered state - user has legitimately authenticated
        if self._tampered:
            logger.info("Clearing tampered state after successful password authentication")
            self._tampered = False
        
        self.data["total_granted_seconds"] += extension_seconds
        self.data["extensions_granted"] += 1
        self._save_data()
        
        logger.info(f"Granted {extension_seconds}s extension. "
                   f"Total granted: {self.data['total_granted_seconds']}s "
                   f"({self.get_extensions_count()}/{self.get_max_extensions()} extensions used)")
        
        return extension_seconds
    
    def format_time(self, seconds: int, full_precision: bool = False) -> str:
        """
        Format seconds as human-readable time string.
        
        Delegates to the canonical format_duration() function from analytics.
        
        Args:
            seconds: Number of seconds.
            full_precision: If True, always show all non-zero time components
                           including seconds even when hours > 0. Default False
                           for compact display (omits seconds when hours present).
            
        Returns:
            Formatted string like "1 hr 30 mins" or "45 mins" or "30 secs".
            With full_precision: "1 hr 30 mins 45 secs" or "2 hrs 0 mins 0 secs".
        """
        return format_duration(float(seconds), full_precision=full_precision)
    
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


# Global instance for easy access (thread-safe singleton)
_limiter_instance: Optional[UsageLimiter] = None
_limiter_lock = __import__('threading').Lock()


def get_usage_limiter() -> UsageLimiter:
    """
    Get the global UsageLimiter instance.
    
    Thread-safe: Uses double-check locking pattern to prevent
    race conditions during initialization.
    
    Returns:
        Singleton UsageLimiter instance.
    """
    global _limiter_instance
    if _limiter_instance is None:
        with _limiter_lock:
            # Double-check after acquiring lock
            if _limiter_instance is None:
                _limiter_instance = UsageLimiter()
    return _limiter_instance
