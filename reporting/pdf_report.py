"""PDF report generation using ReportLab."""

import json
import logging
import random
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
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
    PageBreak,
    Image,
    Flowable
)
from io import BytesIO
from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.graphics.shapes import Drawing, Wedge, Polygon, Circle
import math

import config

logger = logging.getLogger(__name__)


def _add_gradient_background(canvas_obj, doc):
    """
    Add a visible gradient background to the page.
    Blue gradient that fades from top to middle of page.
    
    Args:
        canvas_obj: ReportLab canvas object
        doc: Document object
    """
    canvas_obj.saveState()
    
    # Create a smooth gradient from blue to white
    # Fades from top to middle of page
    width, height = letter
    
    # Use a visible blue for better aesthetics
    gradient_color = colors.HexColor('#B8D5E8')  # Original blue
    
    # Create smooth gradient with many steps for seamless blend
    # Goes from top to middle of page (50% of height)
    num_steps = 50  # More steps = smoother gradient
    gradient_height = height * 0.5  # Gradient covers top half of page
    step_height = gradient_height / num_steps
    
    for i in range(num_steps):
        # Calculate alpha that goes from full color to completely transparent
        alpha = 1 - (i / num_steps)
        
        # Create color with decreasing opacity
        color = colors.Color(
            gradient_color.red,
            gradient_color.green,
            gradient_color.blue,
            alpha=alpha * 0.9  # Increased from 0.7 to 0.9 for more visibility
        )
        
        canvas_obj.setFillColor(color)
        y_pos = height - (i * step_height)
        canvas_obj.rect(0, y_pos - step_height, width, step_height, fill=1, stroke=0)
    
    canvas_obj.restoreState()


def _add_header(canvas_obj, doc):
    """
    Add header to each page (currently empty - logo removed).
    
    Args:
        canvas_obj: ReportLab canvas object
        doc: Document object
    """
    # No header content - logo removed
    pass


def _create_first_page_template(canvas_obj, doc):
    """
    Create custom page template for first page with gradient and header.
    
    Args:
        canvas_obj: ReportLab canvas object
        doc: Document object
    """
    _add_gradient_background(canvas_obj, doc)
    _add_header(canvas_obj, doc)


def _create_later_page_template(canvas_obj, doc):
    """
    Create custom page template for later pages with gradient and header.
    Uses smaller top margin for natural content flow.
    
    Args:
        canvas_obj: ReportLab canvas object
        doc: Document object
    """
    _add_gradient_background(canvas_obj, doc)
    _add_header(canvas_obj, doc)


def _format_time_seconds(seconds: float) -> str:
    """
    Format time in seconds to human-readable display.
    
    Truncates (floors) to integer seconds at the end for consistent display.
    This is the ONLY place where float->int conversion should happen for time.
    
    Args:
        seconds: Time in seconds as float
        
    Returns:
        Formatted string like "1m 30s" or "45s" or "2h 15m"
    """
    # Truncate to int at display time only (floor, not round)
    total_seconds = int(seconds)
    
    # Less than 1 minute - show seconds only
    if total_seconds < 60:
        return f"{total_seconds}s"
    
    hours = total_seconds // 3600
    remaining_seconds = total_seconds % 3600
    mins = remaining_seconds // 60
    secs = remaining_seconds % 60
    
    if hours > 0:
        if secs > 0:
            return f"{hours}h {mins}m {secs}s"
        elif mins > 0:
            return f"{hours}h {mins}m"
        else:
            return f"{hours}h"
    else:
        if secs > 0:
            return f"{mins}m {secs}s"
        else:
            return f"{mins}m"


def _format_time(minutes: float) -> str:
    """
    Format time in minutes to human-readable display.
    
    Legacy wrapper that converts minutes to seconds and calls _format_time_seconds.
    
    Args:
        minutes: Time in minutes as float
        
    Returns:
        Formatted string like "1m 30s" or "45s" or "2h 15m"
    """
    return _format_time_seconds(minutes * 60.0)


# Focus category definitions with colors matching the gauge
FOCUS_CATEGORIES = {
    'excellent': {
        'min': 90,
        'max': 100,
        'label': 'excellent',
        'color': '#1B5E20'  # Dark green
    },
    'proficient': {
        'min': 75,
        'max': 89,
        'label': 'proficient',
        'color': '#8BC34A'  # Lime
    },
    'promising': {
        'min': 50,
        'max': 74,
        'label': 'promising',
        'color': '#FFC107'  # Yellow
    },
    'developing': {
        'min': 0,
        'max': 49,
        'label': 'developing',
        'color': '#FF8C00'  # Orange
    }
}


def _get_focus_category(focus_pct: float) -> Tuple[str, str, str]:
    """
    Determine the focus category based on percentage.
    
    Args:
        focus_pct: Focus percentage (0-100)
        
    Returns:
        Tuple of (category_key, category_label, color_hex)
    """
    if focus_pct >= 90:
        cat = FOCUS_CATEGORIES['excellent']
        return ('excellent', cat['label'], cat['color'])
    elif focus_pct >= 75:
        cat = FOCUS_CATEGORIES['proficient']
        return ('proficient', cat['label'], cat['color'])
    elif focus_pct >= 50:
        cat = FOCUS_CATEGORIES['promising']
        return ('promising', cat['label'], cat['color'])
    else:
        cat = FOCUS_CATEGORIES['developing']
        return ('developing', cat['label'], cat['color'])


def _get_dominant_distraction_type(stats: Optional[Dict[str, Any]] = None) -> str:
    """
    Determine which distraction type was most dominant by percentage.
    
    Analyzes session statistics to find whether phone/gadget usage, being away
    from desk, or screen distractions (wrong apps/websites) was the primary
    distraction during the session.
    
    Args:
        stats: Statistics dictionary from compute_statistics()
        
    Returns:
        One of: 'phone', 'away', 'screen', 'general'
        Returns 'general' if no distractions, stats unavailable, or tie.
    """
    if not stats:
        return 'general'
    
    gadget_secs = stats.get('gadget_seconds', 0)
    away_secs = stats.get('away_seconds', 0)
    screen_secs = stats.get('screen_distraction_seconds', 0)
    
    total_distraction = gadget_secs + away_secs + screen_secs
    
    # No distractions at all - use general statements
    if total_distraction == 0:
        return 'general'
    
    # Calculate percentages
    gadget_pct = (gadget_secs / total_distraction) * 100
    away_pct = (away_secs / total_distraction) * 100
    screen_pct = (screen_secs / total_distraction) * 100
    
    # Find the maximum percentage
    max_pct = max(gadget_pct, away_pct, screen_pct)
    
    # If the dominant one is less than 40%, it's too close - use general
    # This handles cases where distractions are roughly evenly split
    if max_pct < 40:
        return 'general'
    
    # Return the dominant type
    if gadget_pct == max_pct:
        return 'phone'
    elif away_pct == max_pct:
        return 'away'
    else:
        return 'screen'


def _load_focus_statements() -> Dict[str, Any]:
    """
    Load pre-computed focus statements from JSON file.
    
    Returns:
        Dictionary with nested category structure:
        {category: {subcategory: [statements]}, emojis: {...}}
    """
    # Import config for bundled data directory path
    import config
    statements_path = config.BUNDLED_DATA_DIR / 'focus_statements.json'
    try:
        with open(statements_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading focus statements: {e}")
        # Return fallback statements with nested structure
        return {
            'excellent': {'general': ['Your focus rate of {percentage}% is excellent - keep it up!']},
            'proficient': {'general': ['Your focus rate of {percentage}% is proficient - you\'re on the right track!']},
            'promising': {'general': ['Your focus rate of {percentage}% is promising - keep building your focus skills!']},
            'developing': {'general': ['Your focus rate of {percentage}% is developing - you can improve with practice!']}
        }


def _get_random_focus_statement(
    focus_pct: float,
    stats: Optional[Dict[str, Any]] = None
) -> Tuple[str, str, str]:
    """
    Get a random focus statement based on focus percentage and dominant distraction.
    
    Selects a statement from the appropriate category (based on focus %) and
    subcategory (based on dominant distraction type: phone, away, screen, or general).
    
    Args:
        focus_pct: Focus percentage (0-100)
        stats: Optional statistics dictionary for determining dominant distraction
        
    Returns:
        Tuple of (statement_text, category_label, color_hex)
    """
    category_key, category_label, color = _get_focus_category(focus_pct)
    distraction_type = _get_dominant_distraction_type(stats)
    statements_data = _load_focus_statements()
    
    # Get the category data (now a dict with subcategories)
    category_data = statements_data.get(category_key, {})
    
    # Handle both old flat structure (list) and new nested structure (dict)
    if isinstance(category_data, list):
        # Old format: flat list of statements
        category_statements = category_data
    else:
        # New format: nested {subcategory: [statements]}
        # Try to get statements for the dominant distraction type
        category_statements = category_data.get(distraction_type, [])
        
        # Fallback to 'general' if no statements for this distraction type
        if not category_statements:
            category_statements = category_data.get('general', [])
        
        # Final fallback if still no statements
        if not category_statements:
            # Try to get any available subcategory
            for subcat in ['general', 'phone', 'away', 'screen']:
                category_statements = category_data.get(subcat, [])
                if category_statements:
                    break
    
    # Ultimate fallback
    if not category_statements:
        category_statements = [f'Your focus rate of {{percentage}}% is {category_label}.']
    
    # Pick a random statement
    statement_template = random.choice(category_statements)
    
    # Format the percentage (remove .0 if whole number)
    pct_str = f"{int(focus_pct)}" if focus_pct == int(focus_pct) else f"{focus_pct:.1f}"
    statement = statement_template.replace('{percentage}', pct_str)
    
    return (statement, category_label, color)


def _create_focus_statement_paragraph(
    focus_pct: float,
    stats: Optional[Dict[str, Any]] = None
) -> Paragraph:
    """
    Create a paragraph with the focus statement, with category word and percentage highlighted.
    
    Both the category keyword (e.g., "excellent") and percentage are displayed in 
    the category color with a larger font size for emphasis.
    
    Args:
        focus_pct: Focus percentage (0-100)
        stats: Optional statistics dictionary for determining dominant distraction
        
    Returns:
        ReportLab Paragraph object with colored and enlarged category word and percentage
    """
    statement, category_label, color = _get_random_focus_statement(focus_pct, stats)
    
    # Format percentage string for matching
    pct_str = f"{int(focus_pct)}" if focus_pct == int(focus_pct) else f"{focus_pct:.1f}"
    
    # Highlighted style: colored, bold, same font size as text, always capitalized
    capitalized_label = category_label.capitalize()
    
    # Create highlighted version of category label (always capitalized, colored, bold)
    colored_label_cap = f'<font color="{color}"><b>{capitalized_label}</b></font>'
    
    # Create highlighted percentage (with % symbol, colored, bold)
    colored_pct = f'<font color="{color}"><b>{pct_str}%</b></font>'
    
    # Replace the category label with the capitalized colored version
    # Handle both lowercase mid-sentence and already capitalized versions
    colored_statement = statement.replace(f' {category_label}', f' {colored_label_cap}')
    colored_statement = colored_statement.replace(f'{capitalized_label} ', f'{colored_label_cap} ')
    
    # Replace the percentage with the colored version
    colored_statement = colored_statement.replace(f'{pct_str}%', colored_pct)
    
    # Create paragraph style for the statement with increased word spacing
    statement_style = ParagraphStyle(
        'FocusStatement',
        fontName='Times-Italic',
        fontSize=14,
        textColor=colors.HexColor('#2C3E50'),
        alignment=TA_CENTER,
        leading=18,   # Comfortable line height
        wordSpace=3   # Increased spacing between words
    )
    
    return Paragraph(colored_statement, statement_style)


def _get_random_focus_emoji(focus_pct: float) -> str:
    """
    Get a random emoji based on the focus percentage category.
    
    Args:
        focus_pct: Focus percentage (0-100)
        
    Returns:
        A face emoji corresponding to the focus category
    """
    category_key, _, _ = _get_focus_category(focus_pct)
    statements_data = _load_focus_statements()
    
    # Get emojis for this category (fallback to neutral face)
    emojis = statements_data.get('emojis', {}).get(category_key, ['😐'])
    
    return random.choice(emojis)


def _get_emoji_font_paths() -> list:
    """
    Get a list of emoji font paths to try, ordered by platform preference.
    
    Returns:
        List of tuples: (font_path, size) to try in order
    """
    import platform
    system = platform.system()
    
    # Default size for scalable fonts (reduced to prevent overflow)
    default_size = 40
    
    # Platform-specific font configurations
    # Format: (font_path, size) - size is important for bitmap fonts like Apple Color Emoji
    
    if system == 'Darwin':  # macOS
        return [
            # Apple Color Emoji - bitmap font, only supports fixed sizes
            ('/System/Library/Fonts/Apple Color Emoji.ttc', 40),
            ('/System/Library/Fonts/Apple Color Emoji.ttc', 32),
            ('/System/Library/Fonts/Apple Color Emoji.ttc', 24),
        ]
    
    elif system == 'Windows':
        return [
            # Segoe UI Emoji - Windows 10/11 default emoji font
            ('C:\\Windows\\Fonts\\seguiemj.ttf', default_size),
            # Alternative paths
            ('seguiemj.ttf', default_size),  # Let system find it
            # Older Windows might have different emoji support
            ('C:\\Windows\\Fonts\\segoe ui emoji.ttf', default_size),
        ]
    
    else:  # Linux and others
        return [
            # Noto Color Emoji - most common on Linux
            # Ubuntu/Debian
            ('/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf', default_size),
            # Fedora/RHEL
            ('/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf', default_size),
            # Arch Linux
            ('/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf', default_size),
            # Generic noto path
            ('/usr/share/fonts/noto/NotoColorEmoji.ttf', default_size),
            # Twitter Color Emoji (alternative on some systems)
            ('/usr/share/fonts/truetype/twitter-color-emoji/TwitterColorEmoji-SVGinOT.ttf', default_size),
            # Twemoji
            ('/usr/share/fonts/truetype/twemoji/Twemoji.ttf', default_size),
            # JoyPixels/EmojiOne
            ('/usr/share/fonts/joypixels/JoyPixels.ttf', default_size),
        ]


def _create_focus_emoji_image(focus_pct: float) -> Optional[Table]:
    """
    Create a centered emoji image for the focus category.
    
    Renders the emoji using platform-specific color emoji fonts.
    Supports macOS (Apple Color Emoji), Windows (Segoe UI Emoji),
    and Linux (Noto Color Emoji, Twitter Emoji, etc.).
    
    Returns None if no emoji font is available (no fallback).
    
    Args:
        focus_pct: Focus percentage (0-100)
        
    Returns:
        ReportLab Table containing the centered emoji image, or None if unavailable
    """
    emoji = _get_random_focus_emoji(focus_pct)
    
    # Default size (will be updated if font loads successfully)
    emoji_size = 40
    
    # Try to load emoji font (platform-specific order)
    font = None
    font_configs = _get_emoji_font_paths()
    
    for font_path, size in font_configs:
        try:
            font = ImageFont.truetype(font_path, size)
            emoji_size = size  # Update to the size that worked
            logger.debug(f"Loaded emoji font: {font_path} at size {size}")
            break
        except (OSError, IOError) as e:
            logger.debug(f"Could not load font {font_path}: {e}")
            continue
    
    # If no emoji font found, don't display anything
    if not font:
        logger.info("No emoji font available - skipping emoji display")
        return None
    
    # Create image with transparent background
    img_size = int(emoji_size * 1.2)
    img = PILImage.new('RGBA', (img_size, img_size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # Calculate position to center the emoji
    bbox = draw.textbbox((0, 0), emoji, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (img_size - text_width) // 2
    y = (img_size - text_height) // 2 - bbox[1]
    
    # Draw the emoji with color support
    draw.text((x, y), emoji, font=font, embedded_color=True)
    
    # Convert PIL image to bytes
    img_buffer = BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    # Create ReportLab image
    rl_image = Image(img_buffer, width=emoji_size, height=emoji_size)
    
    # Wrap in a table to center it (width matches card content area: 6.2 inch - 40px padding)
    table = Table([[rl_image]], colWidths=[5.65 * inch])
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (0, 0), 10),
        ('BOTTOMPADDING', (0, 0), (0, 0), 10),
    ]))
    table.hAlign = 'CENTER'
    
    return table


def _draw_focus_gauge(focus_pct: float) -> Drawing:
    """
    Create a semicircular gauge visualization for focus percentage.
    
    The gauge has 4 colored zones (no labels - legend is separate):
    - 0-49%: Developing (orange)
    - 50-74%: Promising (yellow)
    - 75-89%: Proficient (lime)
    - 90-100%: Excellent (dark green)
    
    The drawing's bottom edge aligns with the semicircle's flat base.
    
    Args:
        focus_pct: Focus percentage (0-100)
        
    Returns:
        ReportLab Drawing object containing the gauge
    """
    # Scale factor - slightly bigger (0.9 = 90% of original size)
    scale = 0.9
    
    # Gauge dimensions
    outer_radius = int(100 * scale)
    inner_radius = int(50 * scale)  # Slightly thicker gauge band
    width = int(250 * scale)  # Width to fit the gauge
    height = outer_radius  # Height = radius, so flat base is at y=0
    center_x = width / 2
    center_y = 0  # Center at bottom - semicircle goes UP from here
    
    drawing = Drawing(width, height)
    
    # Zone definitions: (start_pct, end_pct, color)
    zones = [
        (0, 49, colors.HexColor('#FF8C00')),      # Orange
        (49, 75, colors.HexColor('#FFC107')),     # Yellow
        (75, 90, colors.HexColor('#8BC34A')),     # Lime
        (90, 100, colors.HexColor('#1B5E20')),    # Dark green
    ]
    
    # Draw each zone as a wedge (arc segment)
    for start_pct, end_pct, color in zones:
        # Convert percentage to angle (180° = 0%, 0° = 100%)
        start_angle = 180 - (end_pct * 1.8)
        end_angle = 180 - (start_pct * 1.8)
        
        # Draw outer wedge
        wedge = Wedge(
            center_x, center_y,
            outer_radius,
            start_angle, end_angle,
            fillColor=color,
            strokeColor=colors.white,
            strokeWidth=int(2 * scale)
        )
        drawing.add(wedge)
        
        # Draw inner wedge (to create hollow arc effect)
        inner_wedge = Wedge(
            center_x, center_y,
            inner_radius,
            start_angle, end_angle,
            fillColor=colors.white,
            strokeColor=None,
            strokeWidth=0
        )
        drawing.add(inner_wedge)
    
    # Draw the needle
    needle_angle = 180 - (focus_pct * 1.8)
    needle_angle_rad = math.radians(needle_angle)
    needle_length = inner_radius + int(20 * scale)
    
    # Needle tip
    tip_x = center_x + needle_length * math.cos(needle_angle_rad)
    tip_y = center_y + needle_length * math.sin(needle_angle_rad)
    
    # Needle base (small triangle for visibility)
    base_offset = int(6 * scale)
    base_angle_left = math.radians(needle_angle + 90)
    base_angle_right = math.radians(needle_angle - 90)
    
    base_left_x = center_x + base_offset * math.cos(base_angle_left)
    base_left_y = center_y + base_offset * math.sin(base_angle_left)
    base_right_x = center_x + base_offset * math.cos(base_angle_right)
    base_right_y = center_y + base_offset * math.sin(base_angle_right)
    
    needle = Polygon(
        [tip_x, tip_y, base_left_x, base_left_y, base_right_x, base_right_y],
        fillColor=colors.HexColor('#2C3E50'),
        strokeColor=colors.HexColor('#1A252F'),
        strokeWidth=1
    )
    drawing.add(needle)
    
    # Draw center circle (needle pivot)
    center_circle = Circle(
        center_x, center_y, int(8 * scale),
        fillColor=colors.HexColor('#2C3E50'),
        strokeColor=colors.white,
        strokeWidth=int(2 * scale)
    )
    drawing.add(center_circle)
    
    return drawing


def _create_focus_legend_table() -> Table:
    """
    Create a legend table showing the focus level zones with colors, percentages and labels.
    Sized to match the gauge proportionally.
    
    Returns:
        ReportLab Table object containing the legend
    """
    # Zone definitions: (range_text, label, color)
    zones = [
        ('90-100%', 'Excellent', colors.HexColor('#1B5E20')),
        ('75-89%', 'Proficient', colors.HexColor('#8BC34A')),
        ('50-74%', 'Promising', colors.HexColor('#FFC107')),
        ('0-49%', 'Developing', colors.HexColor('#FF8C00')),
    ]
    
    # Build legend table data
    legend_data = []
    for range_text, label, color in zones:
        # Create a small colored box using a mini-table (slightly bigger)
        color_cell = Table([['']], colWidths=[14], rowHeights=[14])
        color_cell.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), color),
            ('BOX', (0, 0), (0, 0), 0.5, colors.HexColor('#333333')),
        ]))
        legend_data.append([color_cell, range_text, label])
    
    # Create the legend table (slightly bigger)
    legend_table = Table(legend_data, colWidths=[0.3 * inch, 0.8 * inch, 0.95 * inch])
    
    # Build table style with color-coded text
    legend_style = [
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (1, 0), (1, -1), 'Times-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Times-Roman'),
        ('FONTSIZE', (1, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (1, 0), (1, -1), 8),
        ('LEFTPADDING', (2, 0), (2, -1), 4),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E0E6ED')),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#E0E6ED')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFB')),
    ]
    
    # Add color coding for percentage column
    zone_colors = [
        colors.HexColor('#1B5E20'),  # Excellent - dark green
        colors.HexColor('#8BC34A'),  # Proficient - lime
        colors.HexColor('#FFC107'),  # Promising - yellow
        colors.HexColor('#FF8C00'),  # Developing - orange
    ]
    for i, color in enumerate(zone_colors):
        legend_style.append(('TEXTCOLOR', (1, i), (1, i), color))
    
    legend_table.setStyle(TableStyle(legend_style))
    
    return legend_table


def _create_gauge_with_legend(focus_pct: float) -> Table:
    """
    Create a centered table containing the focus gauge and its legend side by side.
    The flat base of the gauge semicircle aligns with the bottom of the legend table.
    
    Args:
        focus_pct: Focus percentage (0-100)
        
    Returns:
        ReportLab Table object with gauge and legend
    """
    gauge = _draw_focus_gauge(focus_pct)
    legend = _create_focus_legend_table()
    
    # Create table with gauge on left, spacer, legend on right
    data = [[gauge, '', legend]]
    
    # Table with appropriate column widths (gauge, gap, legend)
    table = Table(data, colWidths=[2.8 * inch, 0.5 * inch, 2.1 * inch])
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),  # Align at bottom - gauge base matches legend bottom
    ]))
    
    return table


class RoundedBoxFlowable(Flowable):
    """
    A flowable that wraps content in a rounded rectangle container.
    
    Draws a rounded rectangle background/border and places content inside.
    """
    
    def __init__(
        self,
        content: list,
        width: float,
        bg_color: str = '#F4F8FB',
        border_color: str = '#D0DDE8',
        border_width: float = 1.5,
        corner_radius: int = 15,
        padding: int = 20,
        padding_top: int = None,
        padding_bottom: int = None
    ):
        """
        Initialize rounded box flowable.
        
        Args:
            content: List of flowables to render inside the box
            width: Width of the container
            bg_color: Background color (hex)
            border_color: Border color (hex)
            border_width: Border stroke width
            corner_radius: Radius of rounded corners
            padding: Internal padding (used for left/right, and as default for top/bottom)
            padding_top: Top padding (overrides padding if set)
            padding_bottom: Bottom padding (overrides padding if set)
        """
        Flowable.__init__(self)
        self.content = content
        self.box_width = width
        self.bg_color = colors.HexColor(bg_color)
        self.border_color = colors.HexColor(border_color)
        self.border_width = border_width
        self.corner_radius = corner_radius
        self.padding = padding
        self.padding_top = padding_top if padding_top is not None else padding
        self.padding_bottom = padding_bottom if padding_bottom is not None else padding
        self._content_height = 0
    
    def wrap(self, available_width, available_height):
        """
        Calculate the size of this flowable.
        
        Args:
            available_width: Maximum available width
            available_height: Maximum available height
            
        Returns:
            Tuple of (width, height) needed for this flowable
        """
        # Calculate total content height
        self._content_height = 0
        for item in self.content:
            w, h = item.wrap(self.box_width - 2 * self.padding, available_height)
            self._content_height += h
        
        # Total height includes top and bottom padding
        total_height = self._content_height + self.padding_top + self.padding_bottom
        
        self.width = self.box_width
        self.height = total_height
        
        return (self.width, self.height)
    
    def draw(self):
        """
        Draw the rounded box and its content.
        """
        canvas = self.canv
        
        # Draw the rounded rectangle background
        canvas.saveState()
        canvas.setFillColor(self.bg_color)
        canvas.setStrokeColor(self.border_color)
        canvas.setLineWidth(self.border_width)
        canvas.roundRect(
            0, 0,
            self.box_width, self.height,
            self.corner_radius,
            fill=1, stroke=1
        )
        canvas.restoreState()
        
        # Draw content from top to bottom
        y_position = self.height - self.padding_top
        
        for item in self.content:
            # Get the item's dimensions
            w, h = item.wrap(self.box_width - 2 * self.padding, self.height)
            
            # Move down by the item's height
            y_position -= h
            
            # Draw the item
            item.drawOn(canvas, self.padding, y_position)


def _create_focus_card(
    focus_pct: float,
    stats: Optional[Dict[str, Any]] = None
) -> RoundedBoxFlowable:
    """
    Create a rounded card containing the focus gauge, legend, statement, and emoji.
    
    Groups all focus visualization elements into a visually cohesive container
    with rounded corners, background, and border styling. The statement is
    customized based on the dominant distraction type from session stats.
    
    Args:
        focus_pct: Focus percentage (0-100)
        stats: Optional statistics dictionary for customizing the statement
        
    Returns:
        RoundedBoxFlowable containing all focus elements in a styled card
    """
    # Create the individual components
    gauge_with_legend = _create_gauge_with_legend(focus_pct)
    focus_statement = _create_focus_statement_paragraph(focus_pct, stats)
    
    # Build content list (gauge, spacer, centered statement)
    content = [
        gauge_with_legend,
        Spacer(1, 0.35 * inch),  # More space to push statement down for better centering
        focus_statement,
    ]
    
    # Create the rounded box container (slightly wider and taller)
    card = RoundedBoxFlowable(
        content=content,
        width=6.5 * inch,
        bg_color='#F4F8FB',      # Light blue-gray background
        border_color='#A8C0D4',  # More visible border (darker blue-gray)
        border_width=3,          # Noticeable border thickness
        corner_radius=15,
        padding=25,              # Increased padding for larger card
        padding_bottom=30        # More bottom padding for vertical centering
    )
    
    return card


def generate_report(
    stats: Dict[str, Any],
    session_id: str,
    start_time: datetime,
    end_time: Optional[datetime] = None,
    output_dir: Optional[Path] = None
) -> Path:
    """
    Generate a combined PDF report with summary statistics and all session logs.
    
    Page 1: Title, metadata, Summary Statistics table
    Page 2+: Full session logs (all events, no truncation)
    
    Args:
        stats: Statistics dictionary from analytics.compute_statistics()
        session_id: Unique session identifier
        start_time: Session start time
        end_time: Session end time (optional)
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
    
    # Create PDF document with custom template
    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=letter,
        rightMargin=60,
        leftMargin=60,
        topMargin=45,  # Reduced from 60 to move content up
        bottomMargin=60
    )
    
    # Build the story (content)
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles with Georgia-like font (Times-Roman)
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName='Times-Bold',
        fontSize=28,
        textColor=colors.HexColor('#2C3E50'),
        spaceAfter=20,
        spaceBefore=20,
        alignment=TA_LEFT,
        leading=34
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName='Times-Italic',
        fontSize=12,
        textColor=colors.HexColor('#7F8C8D'),
        spaceAfter=30,
        alignment=TA_LEFT
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontName='Times-Bold',
        fontSize=18,
        textColor=colors.HexColor('#34495E'),
        spaceAfter=20,
        spaceBefore=20,
        alignment=TA_LEFT,
        leading=24
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontName='Times-Roman',
        fontSize=12,
        textColor=colors.HexColor('#2C3E50'),
        leading=17,
        spaceAfter=8
    )
    
    # ===== PAGE 1: Title + Summary Statistics =====
    
    # Title - replaced with logo
    logo_path = config.BASE_DIR / 'assets' / 'logo_with_text.png'
    if logo_path.exists():
        try:
            # Calculate aspect ratio to maintain proportions
            with PILImage.open(logo_path) as img:
                orig_w, orig_h = img.size
                aspect = orig_w / orig_h
                
                # Target height reduced further (was 0.85 inch)
                target_h = 0.65 * inch
                target_w = target_h * aspect
                
                # Create ReportLab Image
                logo = Image(str(logo_path), width=target_w, height=target_h)
                logo.hAlign = 'LEFT'  # Align left like the original title
                
                # Add spacer before logo to bring it down slightly
                story.append(Spacer(1, 0.1 * inch))
                story.append(logo)
                story.append(Spacer(1, 25))  # Spacing after logo
        except Exception as e:
            logger.error(f"Error loading logo for report: {e}")
            # Fallback to text if logo fails
            story.append(Paragraph("Focus Session Report", title_style))
    else:
        # Fallback if logo file missing
        story.append(Paragraph("Focus Session Report", title_style))
    
    # Session metadata as subtitle with date and time range
    date_str = start_time.strftime("%B %d, %Y")
    start_time_str = start_time.strftime("%I:%M%p").lstrip('0').replace(' ', '')
    
    if end_time:
        end_time_str = end_time.strftime("%I:%M%p").lstrip('0').replace(' ', '')
        metadata = f"{date_str} from {start_time_str} - {end_time_str}"
    else:
        metadata = f"{date_str} from {start_time_str} - {start_time_str}"
    
    story.append(Paragraph(metadata, subtitle_style))
    
    # Statistics section
    story.append(Paragraph("Summary Statistics", heading_style))
    
    # Get raw values in seconds (floats for precision)
    # Use new fields if available, fall back to minutes * 60 for backward compat
    if 'present_seconds' in stats:
        present_secs = stats['present_seconds']
        away_secs = stats['away_seconds']
        gadget_secs = stats['gadget_seconds']
        screen_distraction_secs = stats.get('screen_distraction_seconds', 0)
        paused_secs = stats['paused_seconds']
        active_secs = stats['active_seconds']  # = present + away + gadget + screen_distraction
    else:
        # Legacy fallback
        present_secs = stats.get('present_minutes', 0) * 60.0
        away_secs = stats.get('away_minutes', 0) * 60.0
        gadget_secs = stats.get('gadget_minutes', 0) * 60.0
        screen_distraction_secs = stats.get('screen_distraction_minutes', 0) * 60.0
        paused_secs = stats.get('paused_minutes', 0) * 60.0
        active_secs = present_secs + away_secs + gadget_secs + screen_distraction_secs
    
    # Calculate focus percentage: present / active_time
    # This is guaranteed to be 0-100% since active_time = present + away + gadget + screen_distraction
    if active_secs > 0:
        focus_pct = (present_secs / active_secs) * 100.0
    else:
        focus_pct = 0.0
    
    # Clamp to 0-100 for safety (floating point edge cases)
    focus_pct = min(100.0, max(0.0, focus_pct))
    
    # Format focus percentage - use int if it's a whole number
    focus_pct_int = int(focus_pct)
    if abs(focus_pct - focus_pct_int) < 0.05:  # Close enough to whole number
        focus_pct_str = f"{focus_pct_int}%"
    else:
        focus_pct_str = f"{focus_pct:.1f}%"
    
    # Build table data, only including rows with non-zero values
    # Use _format_time_seconds for display (values are already truncated ints from analytics)
    stats_data = [['Category', 'Duration']]
    
    # Track which rows we add for color coding later
    row_types = []
    
    # Add rows only if they have at least 1 second (already truncated to int)
    if present_secs > 0:
        stats_data.append(['Focussed', _format_time_seconds(present_secs)])
        row_types.append('present')
    
    if away_secs > 0:
        stats_data.append(['Away from Desk', _format_time_seconds(away_secs)])
        row_types.append('away')
    
    if gadget_secs > 0:
        stats_data.append(['Gadget Usage', _format_time_seconds(gadget_secs)])
        row_types.append('gadget')
    
    if screen_distraction_secs > 0:
        stats_data.append(['Screen Distraction', _format_time_seconds(screen_distraction_secs)])
        row_types.append('screen')
    
    # Add paused time row only if > 0 (will be styled in italic grey)
    if paused_secs > 0:
        stats_data.append(['Paused', _format_time_seconds(paused_secs)])
        row_types.append('paused')
    
    # Always add Active Time (= present + away + gadget) and Focus Rate
    stats_data.append(['Active Time', _format_time_seconds(active_secs)])
    row_types.append('active')
    stats_data.append(['Focus Rate', focus_pct_str])
    row_types.append('focus')
    
    stats_table = Table(stats_data, colWidths=[3.0 * inch, 3.0 * inch])
    
    # Build table style dynamically based on which rows are present
    table_style = [
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 13),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        # Data rows - background applied BEFORE header to ensure proper layering
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFB')),
        ('FONTNAME', (0, 1), (0, -1), 'Times-Roman'),
        ('FONTNAME', (1, 1), (1, -1), 'Times-Roman'),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('TOPPADDING', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
        # Remove the LINEBELOW under header - it can cause pixel bleeding
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#E0E6ED')),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2C3E50')),
    ]
    
    # Apply colors dynamically based on which rows exist
    for i, row_type in enumerate(row_types, 1):  # Start at 1 to skip header
        if row_type == 'present':
            table_style.append(('TEXTCOLOR', (0, i), (0, i), colors.HexColor('#1B7A3D')))
        elif row_type in ['away', 'gadget']:
            table_style.append(('TEXTCOLOR', (0, i), (0, i), colors.HexColor('#C62828')))
        elif row_type == 'screen':
            # Screen distraction in purple
            table_style.append(('TEXTCOLOR', (0, i), (0, i), colors.HexColor('#7C3AED')))
        elif row_type == 'paused':
            # Paused row: grey text (normal font, not italic)
            table_style.append(('TEXTCOLOR', (0, i), (1, i), colors.HexColor('#7F8C8D')))
        elif row_type in ['active', 'focus']:
            # Make Active Time and Focus Rate bold in both columns
            table_style.append(('FONTNAME', (0, i), (0, i), 'Times-Bold'))
            table_style.append(('FONTNAME', (1, i), (1, i), 'Times-Bold'))
    
    stats_table.setStyle(TableStyle(table_style))
    
    story.append(stats_table)
    
    # Add focus visualization card (gauge, legend, statement, emoji in a rounded container)
    # Pass stats to customize the statement based on dominant distraction type
    story.append(Spacer(1, 0.4 * inch))
    focus_card = _create_focus_card(focus_pct, stats)
    
    # Center the focus card using a wrapper table
    centered_card = Table([[focus_card]], colWidths=[6.2 * inch])
    centered_card.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
    ]))
    story.append(centered_card)
    
    # ===== PAGE 2+: Session Logs =====
    
    # Force logs to start on second page
    story.append(PageBreak())
    story.append(Spacer(1, 0.1 * inch))
    
    # Logs heading
    story.append(Paragraph("Session Logs", heading_style))
    
    # Get all events
    events = stats.get('events', [])
    
    if events:
        # Filter out events with 0 duration (durations are already truncated to int)
        def get_duration_seconds(e):
            if 'duration_seconds' in e:
                return e['duration_seconds']
            return int(e.get('duration_minutes', 0) * 60)
        
        # Only show events with at least 1 second
        non_zero_events = [e for e in events if get_duration_seconds(e) > 0]
        
        if non_zero_events:
            # Build table with ALL events (no limit)
            timeline_data = [['Time', 'Activity', 'Duration']]
            for event in non_zero_events:
                duration_secs = get_duration_seconds(event)
                timeline_data.append([
                    f"{event['start']} - {event['end']}",
                    event['type_label'],
                    _format_time_seconds(duration_secs)
                ])
            
            timeline_table = Table(timeline_data, colWidths=[2.4 * inch, 2.2 * inch, 1.4 * inch])
            
            # Build table style
            logs_table_style = [
                # Header
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                # Data rows
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFB')),
                ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('TOPPADDING', (0, 1), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
                # Remove LINEBELOW under header - can cause pixel bleeding
                ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#E0E6ED')),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#2C3E50')),
            ]
            
            # Add styling for each event type
            for i, event in enumerate(non_zero_events, 1):
                event_type = event.get('type', '')
                if event_type == 'present':
                    # Focused row: normal font, green text for activity column
                    logs_table_style.append(('TEXTCOLOR', (1, i), (1, i), colors.HexColor('#1B7A3D')))
                elif event_type in ['away', 'gadget_suspected']:
                    logs_table_style.append(('TEXTCOLOR', (1, i), (1, i), colors.HexColor('#C62828')))
                elif event_type == 'screen_distraction':
                    # Screen distraction row: purple text for activity column
                    logs_table_style.append(('TEXTCOLOR', (1, i), (1, i), colors.HexColor('#7C3AED')))
                elif event_type == 'paused':
                    # Paused row: italic grey text for entire row
                    logs_table_style.append(('FONTNAME', (0, i), (-1, i), 'Times-Italic'))
                    logs_table_style.append(('TEXTCOLOR', (0, i), (-1, i), colors.HexColor('#7F8C8D')))
            
            timeline_table.setStyle(TableStyle(logs_table_style))
            story.append(timeline_table)
        else:
            story.append(Paragraph("No events recorded.", body_style))
    else:
        story.append(Paragraph("No events recorded.", body_style))
    
    story.append(Spacer(1, 0.5 * inch))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName='Times-Italic',
        fontSize=9,
        textColor=colors.HexColor('#95A5A6'),
        alignment=TA_CENTER
    )
    
    footer_text = "Generated by BrainDock"
    story.append(Paragraph(footer_text, footer_style))
    
    # Build PDF with custom page template
    try:
        doc.build(story, onFirstPage=_create_first_page_template, onLaterPages=_create_later_page_template)
        logger.info(f"PDF report generated: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise
