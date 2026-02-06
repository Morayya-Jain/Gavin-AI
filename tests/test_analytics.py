"""Unit tests for analytics module."""

import unittest
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tracking.analytics import (
    compute_statistics,
    consolidate_events,
    get_focus_percentage,
    generate_summary_text
)
import config


class TestAnalytics(unittest.TestCase):
    """Test cases for analytics functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create sample events for testing
        base_time = datetime.now()
        
        self.sample_events = [
            {
                "type": config.EVENT_PRESENT,
                "start": base_time.isoformat(),
                "end": (base_time + timedelta(minutes=30)).isoformat(),
                "duration_seconds": 1800  # 30 minutes
            },
            {
                "type": config.EVENT_AWAY,
                "start": (base_time + timedelta(minutes=30)).isoformat(),
                "end": (base_time + timedelta(minutes=35)).isoformat(),
                "duration_seconds": 300  # 5 minutes
            },
            {
                "type": config.EVENT_PRESENT,
                "start": (base_time + timedelta(minutes=35)).isoformat(),
                "end": (base_time + timedelta(minutes=50)).isoformat(),
                "duration_seconds": 900  # 15 minutes
            },
            {
                "type": config.EVENT_GADGET_SUSPECTED,
                "start": (base_time + timedelta(minutes=50)).isoformat(),
                "end": (base_time + timedelta(minutes=55)).isoformat(),
                "duration_seconds": 300  # 5 minutes
            },
            {
                "type": config.EVENT_PRESENT,
                "start": (base_time + timedelta(minutes=55)).isoformat(),
                "end": (base_time + timedelta(minutes=60)).isoformat(),
                "duration_seconds": 300  # 5 minutes
            }
        ]
        
        # Total: 60 minutes
        # Present: 30 + 15 + 5 = 50 minutes
        # Away: 5 minutes
        # Gadget: 5 minutes
        # Focussed: 50 minutes (gadget tracked separately)
        self.total_duration = 3600  # 60 minutes in seconds
    
    def test_compute_statistics_basic(self):
        """Test basic statistics computation."""
        stats = compute_statistics(self.sample_events, self.total_duration)
        
        self.assertEqual(stats["total_minutes"], 60.0)
        self.assertEqual(stats["present_minutes"], 50.0)
        self.assertEqual(stats["away_minutes"], 5.0)
        self.assertEqual(stats["gadget_minutes"], 5.0)
        self.assertEqual(stats["focused_minutes"], 50.0)
    
    def test_compute_statistics_empty_events(self):
        """Test statistics with no events."""
        stats = compute_statistics([], 3600)
        
        # With no events, all durations sum to 0 (total_duration param is reference only)
        self.assertEqual(stats["total_minutes"], 0.0)
        self.assertEqual(stats["focused_minutes"], 0.0)
        self.assertEqual(stats["away_minutes"], 0.0)
        self.assertEqual(stats["gadget_minutes"], 0.0)
    
    def test_consolidate_events(self):
        """Test event consolidation."""
        # Create events with consecutive similar types
        base_time = datetime.now()
        events = [
            {
                "type": config.EVENT_PRESENT,
                "start": base_time.isoformat(),
                "end": (base_time + timedelta(minutes=10)).isoformat(),
                "duration_seconds": 600
            },
            {
                "type": config.EVENT_PRESENT,
                "start": (base_time + timedelta(minutes=10)).isoformat(),
                "end": (base_time + timedelta(minutes=20)).isoformat(),
                "duration_seconds": 600
            },
            {
                "type": config.EVENT_AWAY,
                "start": (base_time + timedelta(minutes=20)).isoformat(),
                "end": (base_time + timedelta(minutes=25)).isoformat(),
                "duration_seconds": 300
            }
        ]
        
        consolidated = consolidate_events(events)
        
        # Should consolidate two consecutive "present" events into one
        self.assertEqual(len(consolidated), 2)
        self.assertEqual(consolidated[0]["type"], config.EVENT_PRESENT)
        self.assertEqual(consolidated[0]["duration_minutes"], 20.0)
        self.assertEqual(consolidated[1]["type"], config.EVENT_AWAY)
        self.assertEqual(consolidated[1]["duration_minutes"], 5.0)
    
    def test_consolidate_events_empty(self):
        """Test consolidation with empty event list."""
        consolidated = consolidate_events([])
        self.assertEqual(len(consolidated), 0)
    
    def test_consolidate_events_formatting(self):
        """Test that consolidated events have proper formatting."""
        consolidated = consolidate_events(self.sample_events)
        
        for event in consolidated:
            self.assertIn("type", event)
            self.assertIn("type_label", event)
            self.assertIn("start", event)
            self.assertIn("end", event)
            self.assertIn("duration_minutes", event)
            
            # Check time format (should be like "02:30 PM")
            self.assertIn(":", event["start"])
            self.assertIn(" ", event["start"])
    
    def test_get_focus_percentage(self):
        """Test focus percentage calculation."""
        stats = compute_statistics(self.sample_events, self.total_duration)
        focus_pct = get_focus_percentage(stats)
        
        # 50 minutes focussed out of 60 total = 83.33%
        self.assertAlmostEqual(focus_pct, 83.33, places=2)
    
    def test_get_focus_percentage_zero_duration(self):
        """Test focus percentage with zero duration."""
        stats = {"total_minutes": 0, "focused_minutes": 0}
        focus_pct = get_focus_percentage(stats)
        self.assertEqual(focus_pct, 0.0)
    
    def test_generate_summary_text(self):
        """Test summary text generation."""
        stats = compute_statistics(self.sample_events, self.total_duration)
        summary = generate_summary_text(stats)
        
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)
        self.assertIn("Session Summary", summary)
        self.assertIn("Total Duration", summary)
        self.assertIn("Focussed Time", summary)
    
    def test_summary_text_quality_messages(self):
        """Test that summary includes quality assessment."""
        # Test high focus (80%+)
        high_focus_events = [
            {
                "type": config.EVENT_PRESENT,
                "start": datetime.now().isoformat(),
                "end": (datetime.now() + timedelta(minutes=80)).isoformat(),
                "duration_seconds": 4800
            }
        ]
        stats = compute_statistics(high_focus_events, 5400)  # 90 minutes
        summary = generate_summary_text(stats)
        self.assertIn("Excellent", summary)
        
        # Test low focus (< 40%)
        low_focus_events = [
            {
                "type": config.EVENT_PRESENT,
                "start": datetime.now().isoformat(),
                "end": (datetime.now() + timedelta(minutes=20)).isoformat(),
                "duration_seconds": 1200
            },
            {
                "type": config.EVENT_AWAY,
                "start": (datetime.now() + timedelta(minutes=20)).isoformat(),
                "end": (datetime.now() + timedelta(minutes=60)).isoformat(),
                "duration_seconds": 2400
            }
        ]
        stats = compute_statistics(low_focus_events, 3600)
        summary = generate_summary_text(stats)
        self.assertIn("interruptions", summary)
    
    def test_statistics_includes_events(self):
        """Test that compute_statistics includes consolidated events."""
        stats = compute_statistics(self.sample_events, self.total_duration)
        
        self.assertIn("events", stats)
        self.assertIsInstance(stats["events"], list)
        self.assertGreater(len(stats["events"]), 0)


if __name__ == "__main__":
    unittest.main()

