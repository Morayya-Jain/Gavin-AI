"""
Daily statistics tracker for BrainDock.

Tracks cumulative focus and distraction time for the current day.
Automatically resets at midnight. Data is stored locally per device.

PRECISION GUIDELINE:
    All time values (focus_seconds, distraction_seconds, etc.) are stored and
    calculated as FLOATS to preserve full precision. Truncation to int should
    ONLY happen at the final display step (UI formatting, PDF rendering).
    
    This prevents cumulative precision loss across multiple sessions per day.
    Do NOT convert to int during calculations or when saving to storage.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Optional

import config

logger = logging.getLogger(__name__)


class DailyStatsTracker:
    """
    Tracks daily cumulative focus and distraction statistics.
    
    Data is stored locally in a JSON file and resets automatically
    when the date changes (midnight reset).
    
    Note: All time values use floats for precision. Convert to int only at display time.
    """
    
    def __init__(self):
        """Initialize the daily stats tracker and load existing data."""
        # Use USER_DATA_DIR for writable user data (persists across app updates)
        self.data_file: Path = config.USER_DATA_DIR / "daily_stats.json"
        self._lock = threading.Lock()  # Thread safety for data operations
        self.data = self._load_data()
        
        # Check if we need to reset for a new day
        self._check_and_reset_if_new_day()
    
    def _load_data(self) -> Dict[str, Any]:
        """
        Load daily stats from JSON file.
        
        Returns:
            Dict containing daily statistics.
        """
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    logger.debug(f"Loaded daily stats: {data}")
                    return data
            except (json.JSONDecodeError, IOError, OSError, PermissionError) as e:
                logger.warning(f"Failed to load daily stats: {e}. Starting fresh.")
        
        # Default data for new day
        return self._create_empty_day_data()
    
    def _create_empty_day_data(self) -> Dict[str, Any]:
        """Create empty data structure for a new day. Uses floats for precision."""
        return {
            "date": date.today().isoformat(),
            "focus_seconds": 0.0,
            "distraction_seconds": 0.0,
            "away_seconds": 0.0,
            "gadget_seconds": 0.0,
            "screen_distraction_seconds": 0.0
        }
    
    def _save_data(self) -> None:
        """
        Save daily stats to JSON file atomically.
        
        Uses atomic write (write to temp file, then rename) to prevent
        data corruption if the app crashes during save.
        """
        try:
            # Ensure parent directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Atomic write: write to temp file, then rename
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.tmp',
                prefix='daily_stats_',
                dir=self.data_file.parent
            )
            
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(self.data, f, indent=2)
                
                # Atomic rename (POSIX) or replace (cross-platform)
                try:
                    os.replace(temp_path, self.data_file)
                except OSError:
                    # Fallback for systems where replace doesn't work
                    if self.data_file.exists():
                        self.data_file.unlink()
                    os.rename(temp_path, self.data_file)
                
                logger.debug(f"Saved daily stats: {self.data}")
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise
                
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to save daily stats: {e}")
    
    def _check_and_reset_if_new_day(self) -> None:
        """Check if the date has changed and reset stats if needed."""
        today = date.today().isoformat()
        stored_date = self.data.get("date", "")
        
        if stored_date != today:
            logger.info(f"New day detected ({stored_date} -> {today}). Resetting daily stats.")
            self.data = self._create_empty_day_data()
            self._save_data()
    
    def add_session_stats(self, focus_seconds: float, away_seconds: float, 
                          gadget_seconds: float, screen_distraction_seconds: float) -> None:
        """
        Add statistics from a completed session to daily totals (thread-safe).
        
        Uses floats for full precision. Truncation to int happens only at display time.
        
        Args:
            focus_seconds: Time spent focused (present) in seconds (float for precision)
            away_seconds: Time spent away from desk in seconds (float for precision)
            gadget_seconds: Time spent on gadgets (phone, etc.) in seconds (float for precision)
            screen_distraction_seconds: Time spent on distracting websites/apps in seconds (float for precision)
        
        Raises:
            ValueError: If any parameter is negative.
        """
        # Validate non-negative inputs
        if any(x < 0 for x in [focus_seconds, away_seconds, gadget_seconds, screen_distraction_seconds]):
            raise ValueError("All time values must be non-negative")
        
        with self._lock:
            # Check for day change before adding (in case app was left open overnight)
            self._check_and_reset_if_new_day()
            
            # Add to daily totals
            self.data["focus_seconds"] += focus_seconds
            self.data["away_seconds"] += away_seconds
            self.data["gadget_seconds"] += gadget_seconds
            self.data["screen_distraction_seconds"] += screen_distraction_seconds
            
            # Total distractions = away + gadget + screen (NOT paused)
            self.data["distraction_seconds"] = (
                self.data["away_seconds"] + 
                self.data["gadget_seconds"] + 
                self.data["screen_distraction_seconds"]
            )
            
            self._save_data()
            logger.info(f"Added session stats to daily totals. Focus: {focus_seconds}s, "
                       f"Distractions: {away_seconds + gadget_seconds + screen_distraction_seconds}s")
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """
        Get current daily statistics.
        
        Checks for day change before returning to ensure accuracy.
        Thread-safe: Uses lock to prevent race condition at midnight reset.
        
        Returns:
            Dict with focus_seconds, distraction_seconds, and breakdowns.
        """
        with self._lock:
            self._check_and_reset_if_new_day()
            return self.data.copy()
    
    def get_focus_seconds(self) -> float:
        """Get total focused time today in seconds (float for precision)."""
        self._check_and_reset_if_new_day()
        return float(self.data["focus_seconds"])
    
    def get_distraction_seconds(self) -> float:
        """Get total distraction time today in seconds (float for precision)."""
        self._check_and_reset_if_new_day()
        return float(self.data["distraction_seconds"])
    
    def get_focus_rate(self) -> float:
        """
        Calculate today's focus rate.
        
        Focus Rate = focus / (focus + distractions) * 100
        Paused time is NOT included in either value.
        
        Returns:
            Focus percentage (0-100), or 0 if no data.
        """
        self._check_and_reset_if_new_day()
        
        focus = self.data["focus_seconds"]
        distractions = self.data["distraction_seconds"]
        total_active = focus + distractions
        
        if total_active <= 0:
            return 0.0
        
        return (focus / total_active) * 100.0


# Global instance for easy access (thread-safe singleton)
_daily_stats_instance: Optional[DailyStatsTracker] = None
_daily_stats_lock = __import__('threading').Lock()


def get_daily_stats_tracker() -> DailyStatsTracker:
    """
    Get the global DailyStatsTracker instance.
    
    Thread-safe: Uses double-check locking pattern to prevent
    race conditions during initialization.
    
    Returns:
        Singleton DailyStatsTracker instance.
    """
    global _daily_stats_instance
    if _daily_stats_instance is None:
        with _daily_stats_lock:
            # Double-check after acquiring lock
            if _daily_stats_instance is None:
                _daily_stats_instance = DailyStatsTracker()
    return _daily_stats_instance
