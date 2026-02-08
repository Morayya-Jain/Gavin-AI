"""
Usage Limiter for BrainDock.

Tracks cumulative usage time (credits) as a local cache of cloud balance.
Cloud (Supabase user_credits) is the source of truth; sync on session start/end.
Includes integrity protection to prevent casual file tampering.
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config
from tracking.analytics import format_duration

logger = logging.getLogger(__name__)

# Salt for integrity hash (obfuscated to prevent easy bypass)
_INTEGRITY_SALT = b"BrainDock_v1_" + b"\x7f\x3a\x9c\x42"


class UsageLimiter:
    """
    Manages usage time (credit hours) as a local cache of cloud balance.

    Cloud is the source of truth; sync_with_cloud() updates local state from
    Supabase user_credits. record_usage() updates both local and cloud.
    """

    def __init__(self) -> None:
        """Initialize the usage limiter and load existing usage data (local cache)."""
        self.data_file: Path = config.USAGE_DATA_FILE
        self._tampered: bool = False  # Set True if integrity check fails
        self._lock = threading.Lock()  # Thread safety for data operations
        self._sync_client: Any = None  # BrainDockSync instance, set by engine
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
                    # Return data with time exhausted (tampered)
                    return {
                        "total_used_seconds": data.get("total_granted_seconds", 0),
                        "total_granted_seconds": data.get("total_granted_seconds", 0),
                        "extensions_granted": 0,
                        "max_extensions": 0,
                        "first_use": data.get("first_use"),
                        "last_session_end": data.get("last_session_end"),
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
                    "total_used_seconds": 0,
                    "total_granted_seconds": 0,
                    "extensions_granted": 0,
                    "max_extensions": 0,
                    "first_use": None,
                    "last_session_end": None,
                }
        
        # File doesn't exist - new user, start at zero (credits come from cloud after sync)
        return {
            "total_used_seconds": 0,
            "total_granted_seconds": 0,
            "extensions_granted": 0,
            "max_extensions": 0,
            "first_use": None,
            "last_session_end": None,
        }
    
    def _save_data(self) -> None:
        """
        Save usage data to JSON file with integrity hash.
        
        Uses atomic write (write to temp file, then rename) to prevent
        data corruption if the app crashes during save.
        """
        try:
            # Ensure parent directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Add integrity hash before saving
            save_data = dict(self.data)
            save_data["_integrity"] = self._compute_integrity_hash(self.data)
            
            # Atomic write: write to temp file, then rename
            # This prevents data corruption if the app crashes during write
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.tmp',
                prefix='usage_',
                dir=self.data_file.parent
            )
            
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(save_data, f, indent=2)
                
                # Atomic rename (POSIX) or replace (cross-platform)
                try:
                    os.replace(temp_path, self.data_file)
                except OSError:
                    # Fallback for systems where replace doesn't work
                    if self.data_file.exists():
                        self.data_file.unlink()
                    os.rename(temp_path, self.data_file)
                
                logger.debug("Saved usage data with integrity hash")
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise
                
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

    def set_sync_client(self, client: Any) -> None:
        """Set the Supabase sync client for cloud credit fetch/record (called by engine)."""
        self._sync_client = client

    def sync_with_cloud(self) -> bool:
        """
        Fetch credit balance from cloud and update local cache.

        Returns:
            True if cloud was reached and local data was updated, False if offline/error.
        """
        if not self._sync_client:
            logger.debug("No sync client — using local cache only")
            return False
        try:
            balance = self._sync_client.get_credit_balance()
            purchased = int(balance.get("total_purchased_seconds", 0))
            cloud_used = int(balance.get("total_used_seconds", 0))
            with self._lock:
                # Cloud is the source of truth for both values
                self.data["total_granted_seconds"] = purchased
                self.data["total_used_seconds"] = cloud_used
                self._save_data()
            logger.debug(f"Synced credits from cloud: {purchased}s purchased, {cloud_used}s used")
            return True
        except Exception as e:
            logger.warning(f"Could not sync credits from cloud: {e}")
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
        Record usage time locally and in cloud (thread-safe).

        Args:
            seconds: Number of seconds to add to total usage. Must be non-negative.

        Raises:
            ValueError: If seconds is negative.
        """
        if seconds < 0:
            raise ValueError("Usage seconds must be non-negative")

        with self._lock:
            if self.data["first_use"] is None:
                self.data["first_use"] = datetime.now().isoformat()
            self.data["total_used_seconds"] += seconds
            self._save_data()
        if self._sync_client:
            if not self._sync_client.record_usage(seconds):
                logger.warning("Failed to record usage to cloud (will use local cache until next sync)")
    
    def end_session(self) -> None:
        """Record the end of a session (thread-safe)."""
        with self._lock:
            self.data["last_session_end"] = datetime.now().isoformat()
            self._save_data()
    
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
