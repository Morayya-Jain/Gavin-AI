"""
Daily statistics tracker for BrainDock.

Tracks cumulative focus and distraction time for the current day.
Automatically resets at midnight. Data is stored locally per device.
"""

import json
import logging
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
    """
    
    def __init__(self):
        """Initialize the daily stats tracker and load existing data."""
        # Use USER_DATA_DIR for writable user data (persists across app updates)
        self.data_file: Path = config.USER_DATA_DIR / "daily_stats.json"
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
        """Create empty data structure for a new day."""
        return {
            "date": date.today().isoformat(),
            "focus_seconds": 0,
            "distraction_seconds": 0,
            "away_seconds": 0,
            "gadget_seconds": 0,
            "screen_distraction_seconds": 0
        }
    
    def _save_data(self) -> None:
        """Save daily stats to JSON file."""
        try:
            # Ensure parent directory exists
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            logger.debug(f"Saved daily stats: {self.data}")
        except IOError as e:
            logger.error(f"Failed to save daily stats: {e}")
    
    def _check_and_reset_if_new_day(self) -> None:
        """Check if the date has changed and reset stats if needed."""
        today = date.today().isoformat()
        stored_date = self.data.get("date", "")
        
        if stored_date != today:
            logger.info(f"New day detected ({stored_date} -> {today}). Resetting daily stats.")
            self.data = self._create_empty_day_data()
            self._save_data()
    
    def add_session_stats(self, focus_seconds: int, away_seconds: int, 
                          gadget_seconds: int, screen_distraction_seconds: int) -> None:
        """
        Add statistics from a completed session to daily totals.
        
        Args:
            focus_seconds: Time spent focused (present) in seconds
            away_seconds: Time spent away from desk in seconds
            gadget_seconds: Time spent on gadgets (phone, etc.) in seconds
            screen_distraction_seconds: Time spent on distracting websites/apps in seconds
        
        Raises:
            ValueError: If any parameter is negative.
        """
        # Validate non-negative inputs
        if any(x < 0 for x in [focus_seconds, away_seconds, gadget_seconds, screen_distraction_seconds]):
            raise ValueError("All time values must be non-negative")
        
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
        
        Returns:
            Dict with focus_seconds, distraction_seconds, and breakdowns.
        """
        self._check_and_reset_if_new_day()
        return self.data.copy()
    
    def get_focus_seconds(self) -> int:
        """Get total focused time today in seconds."""
        self._check_and_reset_if_new_day()
        return self.data["focus_seconds"]
    
    def get_distraction_seconds(self) -> int:
        """Get total distraction time today in seconds."""
        self._check_and_reset_if_new_day()
        return self.data["distraction_seconds"]
    
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


# Global instance for easy access
_daily_stats_instance: Optional[DailyStatsTracker] = None


def get_daily_stats_tracker() -> DailyStatsTracker:
    """
    Get the global DailyStatsTracker instance.
    
    Returns:
        Singleton DailyStatsTracker instance.
    """
    global _daily_stats_instance
    if _daily_stats_instance is None:
        _daily_stats_instance = DailyStatsTracker()
    return _daily_stats_instance
