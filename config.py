"""Configuration settings for BrainDock."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def is_bundled() -> bool:
    """
    Check if the application is running from a PyInstaller bundle.
    
    Returns:
        True if running from a bundled executable, False otherwise.
    """
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_base_dir() -> Path:
    """
    Get the base directory for the application.
    
    For development: Returns the directory containing this file.
    For bundled apps: Returns the directory where the executable is located
                      (for user data) or _MEIPASS (for bundled resources).
    
    Returns:
        Path to the base directory.
    """
    if is_bundled():
        # When bundled, _MEIPASS is where PyInstaller extracts files
        return Path(sys._MEIPASS)
    else:
        # Development mode - directory containing config.py
        return Path(__file__).parent


def get_user_data_dir() -> Path:
    """
    Get the directory for user-writable data (sessions, settings, etc.).
    
    For development: Same as BASE_DIR/data
    For bundled apps: Uses a dedicated folder in the user's home directory
                      to persist data across updates.
    
    Returns:
        Path to the user data directory.
    """
    if is_bundled():
        # Store user data in a consistent location that persists across updates
        if sys.platform == 'darwin':
            # macOS: ~/Library/Application Support/BrainDock
            data_dir = Path.home() / "Library" / "Application Support" / "BrainDock"
        elif sys.platform == 'win32':
            # Windows: %APPDATA%/BrainDock
            appdata = os.environ.get('APPDATA', Path.home())
            data_dir = Path(appdata) / "BrainDock"
        else:
            # Linux: ~/.local/share/BrainDock
            data_dir = Path.home() / ".local" / "share" / "BrainDock"
        
        # Create directory if it doesn't exist
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Fallback to home directory if creation fails
            data_dir = Path.home() / ".braindock"
            data_dir.mkdir(parents=True, exist_ok=True)
        
        return data_dir
    else:
        # Development mode
        return Path(__file__).parent / "data"


# Load environment variables from .env file (only in development)
if not is_bundled():
    load_dotenv()

# Base directory (for bundled resources like assets, data files)
BASE_DIR = get_base_dir()

# User data directory (for writable data like sessions, settings)
USER_DATA_DIR = get_user_data_dir()

# Vision Provider Selection
# Options: "openai" or "gemini"
# Default to "gemini" for bundled builds (cheaper and no rate limits)
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "gemini")

# --- API Key Configuration ---
# For bundled builds, API keys can be embedded at build time.
# The build process injects keys via environment variables before bundling.
# Priority: 1) Environment variable, 2) Bundled key (if any)

# Bundled API keys (injected at build time, DO NOT commit actual keys)
# These are placeholders that get replaced during the build process
_BUNDLED_OPENAI_KEY = os.getenv("BUNDLED_OPENAI_API_KEY", "")
_BUNDLED_GEMINI_KEY = os.getenv("BUNDLED_GEMINI_API_KEY", "")


def _get_api_key(env_var: str, bundled_key: str) -> str:
    """
    Get API key with fallback to bundled key.
    
    Args:
        env_var: Environment variable name to check first.
        bundled_key: Bundled key to use as fallback.
        
    Returns:
        API key string, or empty string if not found.
    """
    # Try environment variable first (allows user override)
    key = os.getenv(env_var, "")
    if key:
        return key
    # Fall back to bundled key
    return bundled_key


# OpenAI Configuration
OPENAI_API_KEY = _get_api_key("OPENAI_API_KEY", _BUNDLED_OPENAI_KEY)
OPENAI_VISION_MODEL = "gpt-4o-mini"  # For image analysis (person/gadget detection)

# Gemini Configuration
GEMINI_API_KEY = _get_api_key("GEMINI_API_KEY", _BUNDLED_GEMINI_KEY)
GEMINI_VISION_MODEL = "gemini-2.0-flash"  # Cheaper alternative to OpenAI

# Camera Configuration
CAMERA_INDEX = 0
CAMERA_WIDE_MODE = True  # Enable wider 16:9 aspect ratio for more desk coverage

# Wide mode resolutions to try (in order of preference)
# These are 16:9 aspect ratio for maximum horizontal coverage
CAMERA_WIDE_RESOLUTIONS = [
    (1280, 720),   # 720p - good balance of quality and performance
    (1920, 1080),  # 1080p - higher quality (more API cost)
    (854, 480),    # Wide 480p fallback
]

# Default resolution (used if wide mode disabled or as fallback)
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
DETECTION_FPS = 0.33  # Frames per second to analyse

# Paths
# Session data goes to user data directory (persists across updates)
DATA_DIR = USER_DATA_DIR / "sessions"
# Save reports directly to user's Downloads folder
REPORTS_DIR = Path.home() / "Downloads"

# Bundled data directory (read-only resources included in the app)
BUNDLED_DATA_DIR = BASE_DIR / "data"

# Ensure user data directories exist
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Handle gracefully if directory creation fails
# Downloads folder always exists, no need to create it

# Event types
EVENT_PRESENT = "present"
EVENT_AWAY = "away"
EVENT_GADGET_SUSPECTED = "gadget_suspected"
EVENT_PAUSED = "paused"  # User manually paused the session
EVENT_SCREEN_DISTRACTION = "screen_distraction"  # Distracting website/app detected

# Monitoring modes
MODE_CAMERA_ONLY = "camera_only"  # Default - only camera monitoring
MODE_SCREEN_ONLY = "screen_only"  # Only screen monitoring (no camera)
MODE_BOTH = "both"  # Camera + screen monitoring

# Screen monitoring settings
SCREEN_CHECK_INTERVAL = 3  # Seconds between screen checks (cheaper than camera)
SCREEN_SETTINGS_FILE = USER_DATA_DIR / "blocklist.json"  # Blocklist persistence (user data)
SCREEN_AI_FALLBACK_ENABLED = False  # Enable AI Vision fallback (costs ~$0.001-0.002 per check)

# Unfocused alert settings
# Alert plays at each of these thresholds (in seconds) when user is unfocused
# After all alerts play, no more until user refocuses
UNFOCUSED_ALERT_TIMES = [20, 60, 120]  # Escalating alerts: 20s, 1min, 2min

# Supportive, non-condemning messages for each alert level
# Each tuple: (badge_text, main_message)
UNFOCUSED_ALERT_MESSAGES = [
    ("Focus paused", "We noticed you stepped away!"),           # 20s - gentle notice
    ("Quick check-in", "We are waiting for you :)"),       # 1min - reassuring
    ("Reminder", "Don't forget to come back ;)"),  # 2min - supportive
]

# How long the alert popup stays visible (seconds)
ALERT_POPUP_DURATION = 10

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # Can override in .env: DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# MVP Usage Limit Settings
# Limits total usage time for trial/demo purposes
MVP_LIMIT_SECONDS = 7200  # Initial time limit in seconds (default: 2 hours)
MVP_EXTENSION_SECONDS = 7200  # Time added per password unlock in seconds (default: 2 hours)
MVP_UNLOCK_PASSWORD = os.getenv("MVP_UNLOCK_PASSWORD", "")  # Password to unlock more time
USAGE_DATA_FILE = USER_DATA_DIR / "usage_data.json"  # User data (persists)

# Stripe Payment Configuration
# Get your keys from: https://dashboard.stripe.com/apikeys
# Bundled Stripe keys (injected at build time)
_BUNDLED_STRIPE_SECRET = os.getenv("BUNDLED_STRIPE_SECRET_KEY", "")
_BUNDLED_STRIPE_PUBLISHABLE = os.getenv("BUNDLED_STRIPE_PUBLISHABLE_KEY", "")
_BUNDLED_STRIPE_PRICE_ID = os.getenv("BUNDLED_STRIPE_PRICE_ID", "")

STRIPE_SECRET_KEY = _get_api_key("STRIPE_SECRET_KEY", _BUNDLED_STRIPE_SECRET)
STRIPE_PUBLISHABLE_KEY = _get_api_key("STRIPE_PUBLISHABLE_KEY", _BUNDLED_STRIPE_PUBLISHABLE)
STRIPE_PRICE_ID = _get_api_key("STRIPE_PRICE_ID", _BUNDLED_STRIPE_PRICE_ID)
PRODUCT_PRICE_DISPLAY = os.getenv("PRODUCT_PRICE_DISPLAY", "One-time payment")  # Display text
# Require Terms of Service acceptance at checkout (must configure T&C URL in Stripe Dashboard first)
STRIPE_REQUIRE_TERMS = os.getenv("STRIPE_REQUIRE_TERMS", "").lower() in ("true", "1", "yes")

# Licensing Configuration
LICENSE_FILE = USER_DATA_DIR / "license.json"  # User's license (persists)
LICENSE_KEYS_FILE = BUNDLED_DATA_DIR / "license_keys.json"  # Bundled valid keys (read-only)
SKIP_LICENSE_CHECK = os.getenv("SKIP_LICENSE_CHECK", "").lower() in ("true", "1", "yes")
