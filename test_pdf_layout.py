#!/usr/bin/env python3
"""
Test script to generate a PDF with worst-case layout:
- All possible rows in the statistics table
- Focus percentage that triggers a long two-line statement
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from reporting import pdf_report
from reporting.pdf_report import generate_report
import config

# Monkey-patch to force a very long focus statement
_original_get_random_focus_statement = pdf_report._get_random_focus_statement

def _long_focus_statement(focus_pct, stats=None):
    """Return an extra-long focus statement to test layout overflow."""
    category_key, category_label, color = pdf_report._get_focus_category(focus_pct)
    pct_str = f"{int(focus_pct)}" if focus_pct == int(focus_pct) else f"{focus_pct:.1f}"
    
    # Very long statement that will definitely wrap to multiple lines
    statement = (
        f"With a {category_label} focus rate of {pct_str}%, you demonstrated remarkable dedication "
        f"to staying on task throughout your study session today, keep up the excellent work!"
    )
    return (statement, category_label, color)

pdf_report._get_random_focus_statement = _long_focus_statement

def main():
    """Generate a test PDF with maximum content to verify page 1 fit."""
    
    # Create mock events with ALL event types to maximize table rows
    # Using times that result in non-zero values for each category
    events = [
        {
            'type': 'present',
            'type_label': 'Focussed',
            'start': '10:00:00 AM',
            'end': '10:05:30 AM',
            'duration_seconds': 330  # 5m 30s
        },
        {
            'type': 'away',
            'type_label': 'Away from Desk',
            'start': '10:05:30 AM',
            'end': '10:08:15 AM',
            'duration_seconds': 165  # 2m 45s
        },
        {
            'type': 'present',
            'type_label': 'Focussed',
            'start': '10:08:15 AM',
            'end': '10:15:00 AM',
            'duration_seconds': 405  # 6m 45s
        },
        {
            'type': 'gadget_suspected',
            'type_label': 'Gadget Usage',
            'start': '10:15:00 AM',
            'end': '10:17:30 AM',
            'duration_seconds': 150  # 2m 30s
        },
        {
            'type': 'present',
            'type_label': 'Focussed',
            'start': '10:17:30 AM',
            'end': '10:25:00 AM',
            'duration_seconds': 450  # 7m 30s
        },
        {
            'type': 'screen_distraction',
            'type_label': 'Screen Distraction',
            'start': '10:25:00 AM',
            'end': '10:28:45 AM',
            'duration_seconds': 225  # 3m 45s
        },
        {
            'type': 'paused',
            'type_label': 'Paused',
            'start': '10:28:45 AM',
            'end': '10:33:00 AM',
            'duration_seconds': 255  # 4m 15s
        },
        {
            'type': 'present',
            'type_label': 'Focussed',
            'start': '10:33:00 AM',
            'end': '10:40:00 AM',
            'duration_seconds': 420  # 7m
        },
        {
            'type': 'away',
            'type_label': 'Away from Desk',
            'start': '10:40:00 AM',
            'end': '10:42:30 AM',
            'duration_seconds': 150  # 2m 30s
        },
        {
            'type': 'present',
            'type_label': 'Focussed',
            'start': '10:42:30 AM',
            'end': '10:50:00 AM',
            'duration_seconds': 450  # 7m 30s
        },
    ]
    
    # Calculate totals
    present_secs = sum(e['duration_seconds'] for e in events if e['type'] == 'present')
    away_secs = sum(e['duration_seconds'] for e in events if e['type'] == 'away')
    gadget_secs = sum(e['duration_seconds'] for e in events if e['type'] == 'gadget_suspected')
    screen_secs = sum(e['duration_seconds'] for e in events if e['type'] == 'screen_distraction')
    paused_secs = sum(e['duration_seconds'] for e in events if e['type'] == 'paused')
    
    active_secs = present_secs + away_secs + gadget_secs + screen_secs
    total_secs = active_secs + paused_secs
    
    # Focus percentage - use a value that triggers "promising" category (50-74%)
    # which tends to have longer statements
    focus_pct = (present_secs / active_secs) * 100 if active_secs > 0 else 0
    
    print(f"Present: {present_secs}s ({present_secs/60:.1f}m)")
    print(f"Away: {away_secs}s ({away_secs/60:.1f}m)")
    print(f"Gadget: {gadget_secs}s ({gadget_secs/60:.1f}m)")
    print(f"Screen: {screen_secs}s ({screen_secs/60:.1f}m)")
    print(f"Paused: {paused_secs}s ({paused_secs/60:.1f}m)")
    print(f"Active: {active_secs}s ({active_secs/60:.1f}m)")
    print(f"Total: {total_secs}s ({total_secs/60:.1f}m)")
    print(f"Focus: {focus_pct:.1f}%")
    
    # Create stats dictionary
    stats = {
        'present_seconds': present_secs,
        'away_seconds': away_secs,
        'gadget_seconds': gadget_secs,
        'screen_distraction_seconds': screen_secs,
        'paused_seconds': paused_secs,
        'active_seconds': active_secs,
        'total_seconds': total_secs,
        'focus_percentage': focus_pct,
        'events': events
    }
    
    # Generate session ID and times
    session_id = "Test Layout - All Rows"
    start_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(seconds=total_secs)
    
    # Output to Downloads folder
    output_dir = Path.home() / "Downloads"
    
    print(f"\nGenerating PDF to: {output_dir}")
    
    # Generate the report
    pdf_path = generate_report(
        stats=stats,
        session_id=session_id,
        start_time=start_time,
        end_time=end_time,
        output_dir=output_dir
    )
    
    print(f"\nPDF generated: {pdf_path}")
    print("\nPlease check that:")
    print("1. All rows appear in the Summary Statistics table")
    print("2. The focus card (gauge + statement) fits entirely on page 1")
    print("3. Session Logs start on page 2")
    
    # Open the PDF (macOS)
    import subprocess
    subprocess.run(['open', str(pdf_path)])

if __name__ == '__main__':
    main()
