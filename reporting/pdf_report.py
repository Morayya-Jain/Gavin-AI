"""PDF report generation using ReportLab."""

import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

import config

logger = logging.getLogger(__name__)


def _format_time(minutes: float) -> str:
    """
    Format time in a human-readable way.
    
    Args:
        minutes: Time in minutes (can be fractional)
        
    Returns:
        Formatted string like "1m 30s" or "45s" or "2h 15m"
    """
    total_seconds = int(minutes * 60)
    
    if total_seconds < 60:
        return f"{total_seconds}s"
    
    hours = total_seconds // 3600
    remaining_seconds = total_seconds % 3600
    mins = remaining_seconds // 60
    secs = remaining_seconds % 60
    
    if hours > 0:
        if secs > 0:
            return f"{hours}h {mins}m {secs}s"
        else:
            return f"{hours}h {mins}m"
    else:
        if secs > 0:
            return f"{mins}m {secs}s"
        else:
            return f"{mins}m"


def generate_report(
    stats: Dict[str, Any],
    summary_data: Dict[str, Any],
    session_id: str,
    start_time: datetime,
    output_dir: Optional[Path] = None
) -> Path:
    """
    Generate a PDF report from session statistics and AI summary.
    
    Args:
        stats: Statistics dictionary from analytics.compute_statistics()
        summary_data: Summary and suggestions from AI summariser
        session_id: Unique session identifier
        start_time: Session start time
        output_dir: Output directory (defaults to config.REPORTS_DIR)
        
    Returns:
        Path to the generated PDF file
    """
    if output_dir is None:
        output_dir = config.REPORTS_DIR
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    filename = f"{session_id}.pdf"
    filepath = output_dir / filename
    
    # Create PDF document
    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # Build the story (content)
    story = []
    styles = getSampleStyleSheet()
    
    # Add custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2C3E50'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#34495E'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    # Title
    story.append(Paragraph("📚 Study Session Report", title_style))
    story.append(Spacer(1, 0.2 * inch))
    
    # Session metadata
    date_str = start_time.strftime("%B %d, %Y")
    time_str = start_time.strftime("%I:%M %p")
    
    metadata = f"<b>Session Date:</b> {date_str}<br/><b>Start Time:</b> {time_str}"
    story.append(Paragraph(metadata, styles['Normal']))
    story.append(Spacer(1, 0.3 * inch))
    
    # Statistics section
    story.append(Paragraph("📊 Session Statistics", heading_style))
    
    # Create statistics table
    stats_data = [
        ['Metric', 'Value'],
        ['Total Duration', _format_time(stats['total_minutes'])],
        ['Focused Time', _format_time(stats['focused_minutes'])],
        ['Time Away', _format_time(stats['away_minutes'])],
        ['Phone Usage', _format_time(stats['phone_minutes'])],
    ]
    
    # Calculate focus percentage
    focus_pct = (stats['focused_minutes'] / stats['total_minutes'] * 100) if stats['total_minutes'] > 0 else 0
    stats_data.append(['Focus Rate', f"{focus_pct:.1f}%"])
    
    stats_table = Table(stats_data, colWidths=[3 * inch, 2.5 * inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498DB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    story.append(stats_table)
    story.append(Spacer(1, 0.3 * inch))
    
    # Timeline section
    story.append(Paragraph("⏱️ Session Timeline", heading_style))
    
    events = stats.get('events', [])
    if events:
        # Limit to most significant events for readability
        display_events = events[:8]
        
        timeline_data = [['Time', 'Activity', 'Duration']]
        for event in display_events:
            timeline_data.append([
                f"{event['start']} - {event['end']}",
                event['type_label'],
                _format_time(event['duration_minutes'])
            ])
        
        if len(events) > 8:
            timeline_data.append(['...', f'{len(events) - 8} more events', '...'])
        
        timeline_table = Table(timeline_data, colWidths=[2.2 * inch, 2 * inch, 1.3 * inch])
        timeline_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2ECC71')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#E8F8F5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#BDC3C7')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        
        story.append(timeline_table)
    else:
        story.append(Paragraph("No events recorded.", styles['Normal']))
    
    story.append(Spacer(1, 0.3 * inch))
    
    # AI Summary section
    story.append(Paragraph("🤖 AI-Powered Insights", heading_style))
    
    summary_text = summary_data.get('summary', 'No summary available.')
    story.append(Paragraph(summary_text, styles['Normal']))
    story.append(Spacer(1, 0.2 * inch))
    
    # Suggestions section
    story.append(Paragraph("💡 Suggestions for Improvement", heading_style))
    
    suggestions = summary_data.get('suggestions', [])
    if suggestions:
        for i, suggestion in enumerate(suggestions, 1):
            bullet_text = f"<b>{i}.</b> {suggestion}"
            story.append(Paragraph(bullet_text, styles['Normal']))
            story.append(Spacer(1, 0.1 * inch))
    else:
        story.append(Paragraph("No suggestions available.", styles['Normal']))
    
    story.append(Spacer(1, 0.3 * inch))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey,
        alignment=TA_CENTER
    )
    
    footer_text = "Generated by AI Study Focus Tracker | Keep up the great work! 🎯"
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(footer_text, footer_style))
    
    # Build PDF
    try:
        doc.build(story)
        logger.info(f"PDF report generated: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise


def generate_test_report():
    """Generate a test report with sample data."""
    from tracking.analytics import compute_statistics
    
    # Sample data
    sample_events = [
        {
            "type": "present",
            "start": "2025-12-09T14:00:00",
            "end": "2025-12-09T14:30:00",
            "duration_seconds": 1800
        },
        {
            "type": "away",
            "start": "2025-12-09T14:30:00",
            "end": "2025-12-09T14:35:00",
            "duration_seconds": 300
        },
        {
            "type": "present",
            "start": "2025-12-09T14:35:00",
            "end": "2025-12-09T14:55:00",
            "duration_seconds": 1200
        },
        {
            "type": "phone_suspected",
            "start": "2025-12-09T14:55:00",
            "end": "2025-12-09T15:00:00",
            "duration_seconds": 300
        }
    ]
    
    stats = compute_statistics(sample_events, 3600)
    
    summary_data = {
        "summary": "Great job staying focused! You maintained excellent concentration for most of the session. "
                  "The brief breaks you took were well-timed and helped maintain your energy.",
        "suggestions": [
            "Try the Pomodoro Technique: 25 minutes of focused work followed by 5-minute breaks.",
            "Keep your phone in another room or use Do Not Disturb mode during study sessions.",
            "Set specific goals at the start of each session to stay motivated.",
            "Take notes by hand instead of on devices to reduce digital distractions.",
            "Schedule your study sessions during your peak energy hours."
        ]
    }
    
    start_time = datetime.now()
    
    filepath = generate_report(
        stats,
        summary_data,
        "test_session",
        start_time
    )
    
    print(f"Test report generated: {filepath}")
    return filepath


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    logging.basicConfig(level=logging.INFO)
    generate_test_report()

