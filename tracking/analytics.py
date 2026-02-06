"""Analytics for computing session statistics from events."""

from typing import Dict, List, Any
from datetime import datetime
import config


def format_duration(seconds: float, full_precision: bool = False) -> str:
    """
    Format duration in seconds to human-readable string.
    
    This is the canonical time formatting function. All calculations should
    use float seconds for precision, with truncation to int happening ONLY
    here at display time.
    
    Args:
        seconds: Duration in seconds (float for precision, truncated to int for display)
        full_precision: If True, always show all non-zero time components
                       including seconds even when hours > 0. Default False
                       for compact display (omits seconds when hours present).
    
    Returns:
        Formatted string like "1 min 30 secs", "45 secs", "2 hrs 15 mins", or with full_precision
        "1 hr 30 mins 45 secs", "2 hrs 0 mins 0 secs"
    
    Examples:
        >>> format_duration(90)
        "1 min 30 secs"
        >>> format_duration(3725)
        "1 hr 2 mins"
        >>> format_duration(3725, full_precision=True)
        "1 hr 2 mins 5 secs"
        >>> format_duration(0)
        "0 sec"
    """
    # Truncate to int at display time only (floor, not round)
    total_seconds = int(seconds) if seconds >= 0 else 0
    
    hours = total_seconds // 3600
    remaining_seconds = total_seconds % 3600
    mins = remaining_seconds // 60
    secs = remaining_seconds % 60
    
    parts = []
    
    if hours > 0:
        hr_unit = "hr" if hours == 1 else "hrs"
        parts.append(f"{hours} {hr_unit}")
    
    if mins > 0 or (full_precision and hours > 0):
        # Show minutes if non-zero, or if full_precision and hours exist
        min_unit = "min" if mins == 1 else "mins"
        parts.append(f"{mins} {min_unit}")
    
    if secs > 0 or full_precision:
        # Show seconds if non-zero, or always if full_precision
        if hours == 0 or full_precision:
            sec_unit = "sec" if secs == 1 else "secs"
            parts.append(f"{secs} {sec_unit}")
    
    return " ".join(parts) if parts else "0 sec"


def compute_statistics(events: List[Dict[str, Any]], total_duration: float) -> Dict[str, Any]:
    """
    Compute statistics from a list of session events.
    
    All calculations use floats for full precision. Truncation to int
    happens ONLY at final display time in the PDF report.
    
    Args:
        events: List of event dictionaries with type, start, end, and duration
        total_duration: Total session duration in seconds (for reference only)
        
    Returns:
        Dictionary containing statistics (seconds as floats for precision)
    """
    # Initialize counters as floats for full precision
    present_seconds = 0.0
    away_seconds = 0.0
    gadget_seconds = 0.0
    screen_distraction_seconds = 0.0
    paused_seconds = 0.0
    
    # Sum up durations by event type using full float precision
    for event in events:
        duration = float(event.get("duration_seconds", 0))
        event_type = event.get("type")
        
        if event_type == config.EVENT_PRESENT:
            present_seconds += duration
        elif event_type == config.EVENT_AWAY:
            away_seconds += duration
        elif event_type == config.EVENT_GADGET_SUSPECTED:
            gadget_seconds += duration
        elif event_type == config.EVENT_SCREEN_DISTRACTION:
            screen_distraction_seconds += duration
        elif event_type == config.EVENT_PAUSED:
            paused_seconds += duration
    
    # Calculate derived values (floats for precision)
    # Screen distraction counts as active time (user is at desk, just distracted)
    active_seconds = present_seconds + away_seconds + gadget_seconds + screen_distraction_seconds
    distracted_seconds = away_seconds + gadget_seconds + screen_distraction_seconds
    total_seconds = active_seconds + paused_seconds
    
    # Consolidate events for timeline (keeps float precision)
    consolidated = consolidate_events(events)
    
    # Return float seconds - truncation happens at PDF display time only
    return {
        "total_seconds": total_seconds,
        "present_seconds": present_seconds,
        "away_seconds": away_seconds,
        "gadget_seconds": gadget_seconds,
        "screen_distraction_seconds": screen_distraction_seconds,
        "paused_seconds": paused_seconds,
        "active_seconds": active_seconds,
        "distracted_seconds": distracted_seconds,
        # Legacy minute values for backward compatibility
        "total_minutes": total_seconds / 60.0,
        "focused_minutes": present_seconds / 60.0,
        "away_minutes": away_seconds / 60.0,
        "gadget_minutes": gadget_seconds / 60.0,
        "screen_distraction_minutes": screen_distraction_seconds / 60.0,
        "paused_minutes": paused_seconds / 60.0,
        "present_minutes": present_seconds / 60.0,
        "events": consolidated
    }


def consolidate_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Consolidate consecutive similar events and format for timeline.
    
    This merges consecutive events of the same type to reduce noise
    and creates a cleaner timeline view.
    
    Keeps float precision - truncation happens at PDF display time only.
    
    Args:
        events: List of raw event dictionaries
        
    Returns:
        List of consolidated events with readable format
    """
    if not events:
        return []
    
    consolidated = []
    current_event = None
    
    for event in events:
        event_type = event.get("type")
        start_time = event.get("start")
        end_time = event.get("end")
        # Keep full float precision
        duration = float(event.get("duration_seconds", 0))
        
        # If this is the same type as current, extend the current event
        if current_event and current_event["type"] == event_type:
            current_event["end"] = end_time
            current_event["duration_seconds"] += duration
        else:
            # Save previous event if exists
            if current_event:
                try:
                    consolidated.append(_format_event(current_event))
                except ValueError as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Skipping malformed event: {e}")
            
            # Start new event
            current_event = {
                "type": event_type,
                "start": start_time,
                "end": end_time,
                "duration_seconds": duration
            }
    
    # Don't forget the last event
    if current_event:
        try:
            consolidated.append(_format_event(current_event))
        except ValueError as e:
            import logging
            logging.getLogger(__name__).warning(f"Skipping malformed event during consolidation: {e}")
    
    return consolidated


def _format_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format an event for display with human-readable times and durations.
    
    Keeps float precision - truncation happens at PDF display time only.
    
    Args:
        event: Event dictionary with start, end, type, and duration (float)
        
    Returns:
        Formatted event dictionary with duration_seconds as float
        
    Raises:
        ValueError: If date strings are malformed (logged and re-raised)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        start = datetime.fromisoformat(event["start"])
        end = datetime.fromisoformat(event["end"])
    except (ValueError, TypeError) as e:
        logger.warning(f"Malformed date in event: start={event.get('start')}, end={event.get('end')}, error={e}")
        raise ValueError(f"Malformed date in event: {e}") from e
    
    # Keep full float precision
    duration_seconds = float(event["duration_seconds"])
    
    # Create readable event type labels
    type_labels = {
        config.EVENT_PRESENT: "Focussed",
        config.EVENT_AWAY: "Away",
        config.EVENT_GADGET_SUSPECTED: "Gadget Usage",
        config.EVENT_SCREEN_DISTRACTION: "Screen Distraction",
        config.EVENT_PAUSED: "Paused"
    }
    
    return {
        "type": event["type"],
        "type_label": type_labels.get(event["type"], event["type"]),
        "start": start.strftime("%I:%M %p"),
        "end": end.strftime("%I:%M %p"),
        "duration_seconds": duration_seconds,  # Float for precision
        "duration_minutes": duration_seconds / 60.0  # For backward compatibility
    }


def get_focus_percentage(stats: Dict[str, Any]) -> float:
    """
    Calculate focus percentage from statistics.
    
    Focus rate = present / active_time, where active_time = present + away + gadget + screen_distraction.
    Paused time is completely excluded from both numerator and denominator.
    This ensures the focus rate is always between 0% and 100%.
    
    Args:
        stats: Statistics dictionary from compute_statistics (values are floats)
        
    Returns:
        Focus percentage (0-100), never exceeds 100%. Returns 0.0 for invalid/empty stats.
    """
    # Handle None or empty stats
    if not stats:
        return 0.0
    
    try:
        # Use int seconds from stats (convert to float for division)
        if "active_seconds" in stats:
            active_time = float(stats.get("active_seconds", 0) or 0)
            present_time = float(stats.get("present_seconds", 0) or 0)
        else:
            # Legacy fallback (includes screen_distraction if present)
            screen_distraction = float(stats.get("screen_distraction_minutes", 0) or 0)
            active_time = (float(stats.get("present_minutes", 0) or 0) + 
                           float(stats.get("away_minutes", 0) or 0) + 
                           float(stats.get("gadget_minutes", 0) or 0) +
                           screen_distraction) * 60.0
            present_time = float(stats.get("present_minutes", 0) or 0) * 60.0
        
        # Guard against division by zero or negative values
        if active_time <= 0:
            return 0.0
        
        # Focus rate = present / active (guaranteed 0-100%)
        focus_pct = (present_time / active_time) * 100.0
        
        # Clamp to 0-100 for safety (handles any floating point edge cases)
        # Log warning if clamping is needed (indicates potential data issue)
        if focus_pct < 0.0 or focus_pct > 100.0:
            import logging
            logging.getLogger(__name__).warning(
                f"Focus percentage out of range ({focus_pct:.2f}%), clamping to 0-100. "
                f"present_time={present_time}, active_time={active_time}"
            )
        return min(100.0, max(0.0, focus_pct))
    except (TypeError, ValueError) as e:
        # If any conversion fails, return safe default
        return 0.0


def generate_summary_text(stats: Dict[str, Any]) -> str:
    """
    Generate a simple text summary of the session.
    
    This is a fallback summary in case OpenAI API is not available.
    Uses raw seconds and converts to display format at the end.
    
    Args:
        stats: Statistics dictionary from compute_statistics
        
    Returns:
        Human-readable summary string
    """
    # Get values in seconds (new format) or convert from minutes (legacy)
    if "active_seconds" in stats:
        active_secs = stats["active_seconds"]
        present_secs = stats["present_seconds"]
        away_secs = stats["away_seconds"]
        gadget_secs = stats["gadget_seconds"]
        screen_distraction_secs = stats.get("screen_distraction_seconds", 0)
        paused_secs = stats["paused_seconds"]
    else:
        present_secs = stats.get("present_minutes", 0) * 60
        away_secs = stats.get("away_minutes", 0) * 60
        gadget_secs = stats.get("gadget_minutes", 0) * 60
        screen_distraction_secs = stats.get("screen_distraction_minutes", 0) * 60
        paused_secs = stats.get("paused_minutes", 0) * 60
        active_secs = present_secs + away_secs + gadget_secs + screen_distraction_secs
    
    focus_pct = get_focus_percentage(stats)
    
    # Format active time as duration
    total_secs = int(active_secs + paused_secs)
    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    
    if hours > 0:
        duration_str = f"{hours}h {minutes}m"
    else:
        duration_str = f"{minutes}m"
    
    # Format individual times
    def fmt_mins(secs):
        return f"{secs / 60:.1f}"
    
    summary = f"""Session Summary:
Total Duration: {duration_str}
Focussed Time: {fmt_mins(present_secs)} minutes ({focus_pct:.1f}%)
Away Time: {fmt_mins(away_secs)} minutes
Gadget Usage: {fmt_mins(gadget_secs)} minutes
"""
    
    # Only show screen distraction time if > 0
    if screen_distraction_secs > 0:
        summary += f"Screen Distraction: {fmt_mins(screen_distraction_secs)} minutes\n"
    
    # Only show paused time if > 0
    if paused_secs > 0:
        summary += f"Paused Time: {fmt_mins(paused_secs)} minutes\n"
    
    summary += "\n"
    
    # Add simple observation
    if focus_pct >= 80:
        summary += "Excellent focus! You stayed on task for most of the session."
    elif focus_pct >= 60:
        summary += "Good session! You maintained decent focus with some breaks."
    elif focus_pct >= 40:
        summary += "Fair session. Consider minimising distractions for better focus."
    else:
        summary += "This session had many interruptions. Try to find a quieter space."
    
    return summary

