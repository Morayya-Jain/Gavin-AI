"""Test PDF report generation with random stats."""

import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from reporting.pdf_report import generate_report


def generate_random_stats() -> dict:
    """
    Generate random statistics for testing PDF report generation.
    
    Creates realistic-looking session data with random durations
    and events for testing purposes.
    
    Returns:
        Dictionary with stats matching the expected format
    """
    # Random total session duration between 10 and 120 minutes
    total_minutes = random.uniform(10, 120)
    
    # Random distribution of time (ensuring they add up to total)
    # Generate random ratios and normalize
    present_ratio = random.uniform(0.3, 0.9)
    away_ratio = random.uniform(0, 0.3)
    phone_ratio = 1 - present_ratio - away_ratio
    
    # Ensure phone_ratio is non-negative
    if phone_ratio < 0:
        phone_ratio = 0
        # Renormalize
        total_ratio = present_ratio + away_ratio
        present_ratio /= total_ratio
        away_ratio /= total_ratio
    
    present_minutes = total_minutes * present_ratio
    away_minutes = total_minutes * away_ratio
    phone_minutes = total_minutes * phone_ratio
    
    # Generate random events
    events = _generate_random_events(total_minutes)
    
    return {
        'present_minutes': present_minutes,
        'away_minutes': away_minutes,
        'phone_minutes': phone_minutes,
        'total_minutes': total_minutes,
        'events': events
    }


def _generate_random_events(total_minutes: float) -> list:
    """
    Generate random events for the session log.
    
    Args:
        total_minutes: Total session duration in minutes
        
    Returns:
        List of event dictionaries
    """
    events = []
    event_types = [
        ('present', 'Present at Desk'),
        ('away', 'Away from Desk'),
        ('phone_suspected', 'Phone Usage')
    ]
    
    # Start time for events
    current_time = datetime.now().replace(second=0, microsecond=0)
    remaining_minutes = total_minutes
    
    # Generate between 3 and 10 random events
    num_events = random.randint(3, 10)
    
    for i in range(num_events):
        if remaining_minutes <= 0:
            break
        
        # Random duration for this event (at least 0.5 min, at most remaining)
        max_duration = min(remaining_minutes, 30)
        duration = random.uniform(0.5, max(0.5, max_duration))
        
        # Last event gets remaining time
        if i == num_events - 1:
            duration = remaining_minutes
        
        # Random event type (weighted towards present)
        weights = [0.6, 0.2, 0.2]  # present, away, phone
        event_type, type_label = random.choices(event_types, weights=weights)[0]
        
        start_time = current_time
        end_time = current_time + timedelta(minutes=duration)
        
        events.append({
            'start': start_time.strftime('%I:%M%p').lstrip('0'),
            'end': end_time.strftime('%I:%M%p').lstrip('0'),
            'type': event_type,
            'type_label': type_label,
            'duration_minutes': duration
        })
        
        current_time = end_time
        remaining_minutes -= duration
    
    return events


def test_pdf_generation():
    """
    Test that PDF report generation works with random stats.
    
    Creates a PDF in a temporary directory and verifies it was created.
    """
    # Generate random stats
    stats = generate_random_stats()
    
    # Create session ID with timestamp
    session_id = f"Test-Report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Use temp directory for output
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        
        # Generate the report
        start_time = datetime.now() - timedelta(minutes=stats['total_minutes'])
        end_time = datetime.now()
        
        filepath = generate_report(
            stats=stats,
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            output_dir=output_dir
        )
        
        # Verify PDF was created
        assert filepath.exists(), f"PDF was not created at {filepath}"
        assert filepath.suffix == '.pdf', "Output file is not a PDF"
        assert filepath.stat().st_size > 0, "PDF file is empty"
        
        print(f"✓ PDF generated successfully: {filepath.name}")
        print(f"  Size: {filepath.stat().st_size:,} bytes")
        print(f"  Focus rate: {stats['present_minutes'] / stats['total_minutes'] * 100:.1f}%")
        print(f"  Events: {len(stats['events'])}")


def test_pdf_all_categories():
    """
    Test PDF generation for each focus category to verify colored statements.
    
    Generates PDFs with focus rates in each category:
    - Grand (90-100%)
    - Promising (75-89%)
    - Developing (50-74%)
    - Needs Focus (0-49%)
    """
    categories = [
        ('grand', 0.95),          # 95% focus
        ('promising', 0.80),      # 80% focus
        ('developing', 0.60),     # 60% focus
        ('needs_focus', 0.30),    # 30% focus
    ]
    
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        
        for category_name, focus_ratio in categories:
            # Create stats with specific focus ratio
            total_minutes = 60  # 1 hour session
            present_minutes = total_minutes * focus_ratio
            away_minutes = total_minutes * (1 - focus_ratio) * 0.5
            phone_minutes = total_minutes * (1 - focus_ratio) * 0.5
            
            stats = {
                'present_minutes': present_minutes,
                'away_minutes': away_minutes,
                'phone_minutes': phone_minutes,
                'total_minutes': total_minutes,
                'events': _generate_random_events(total_minutes)
            }
            
            session_id = f"Test-{category_name.title()}-{datetime.now().strftime('%H%M%S')}"
            start_time = datetime.now() - timedelta(minutes=total_minutes)
            end_time = datetime.now()
            
            filepath = generate_report(
                stats=stats,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                output_dir=output_dir
            )
            
            assert filepath.exists(), f"PDF for {category_name} was not created"
            print(f"✓ {category_name.upper()} ({focus_ratio*100:.0f}% focus): {filepath.name}")


def create_sample_pdf(output_path: Path = None) -> Path:
    """
    Create a sample PDF with random stats for manual inspection.
    
    Args:
        output_path: Optional custom output directory.
                     Defaults to ~/Downloads/
    
    Returns:
        Path to the generated PDF
    """
    if output_path is None:
        output_path = Path.home() / 'Downloads'
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Generate random stats
    stats = generate_random_stats()
    
    # Create session ID
    session_id = f"Sample-Report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Generate the report
    start_time = datetime.now() - timedelta(minutes=stats['total_minutes'])
    end_time = datetime.now()
    
    filepath = generate_report(
        stats=stats,
        session_id=session_id,
        start_time=start_time,
        end_time=end_time,
        output_dir=output_path
    )
    
    print(f"Sample PDF created: {filepath}")
    print(f"Focus rate: {stats['present_minutes'] / stats['total_minutes'] * 100:.1f}%")
    
    return filepath


if __name__ == '__main__':
    import sys
    
    print("=" * 50)
    print("PDF Report Generation Tests")
    print("=" * 50)
    print()
    
    # Run basic test
    print("1. Testing basic PDF generation with random stats...")
    test_pdf_generation()
    print()
    
    # Run category tests
    print("2. Testing all focus categories...")
    test_pdf_all_categories()
    print()
    
    # Create sample PDF if requested
    if '--sample' in sys.argv:
        print("3. Creating sample PDF in Downloads folder...")
        create_sample_pdf()
    else:
        print("Tip: Run with --sample to create a PDF in ~/Downloads/ for inspection")
    
    print()
    print("=" * 50)
    print("All tests passed!")
    print("=" * 50)
