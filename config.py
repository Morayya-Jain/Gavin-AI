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
        # Use getattr for proper typing (sys._MEIPASS is a private attribute)
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        # Fallback (shouldn't happen if is_bundled() is True)
        return Path(__file__).parent
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
            # Use proper fallback if APPDATA is not set (rare but possible)
            appdata = os.environ.get('APPDATA')
            if appdata:
                data_dir = Path(appdata) / "BrainDock"
            else:
                # Proper fallback to standard Windows location
                data_dir = Path.home() / "AppData" / "Roaming" / "BrainDock"
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
    # Explicitly load from the project root (where config.py lives)
    # This ensures .env is found regardless of current working directory
    _env_path = Path(__file__).parent / ".env"
    load_dotenv(_env_path)

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
# The build process creates bundled_keys.py with the actual key values.
# Priority: 1) Environment variable, 2) Bundled key module, 3) Empty string

# Try to import bundled keys (generated at build time)
_bundled_keys_available = False
try:
    import bundled_keys
    _BUNDLED_OPENAI_KEY = bundled_keys.get_key("OPENAI_API_KEY")
    _BUNDLED_GEMINI_KEY = bundled_keys.get_key("GEMINI_API_KEY")
    _bundled_keys_available = True
except ImportError:
    # Development mode or bundled_keys not available
    # Fall back to environment variables (old method, for backwards compatibility)
    _BUNDLED_OPENAI_KEY = os.getenv("BUNDLED_OPENAI_API_KEY", "")
    _BUNDLED_GEMINI_KEY = os.getenv("BUNDLED_GEMINI_API_KEY", "")


def _validate_api_key_format(key: str, key_type: str) -> bool:
    """
    Validate API key format to catch configuration errors early.
    
    Args:
        key: The API key to validate.
        key_type: Type of key ("openai", "gemini", "stripe_secret", "stripe_publishable")
        
    Returns:
        True if key format is valid, False otherwise.
    """
    if not key:
        return False
    
    # Check minimum length
    if len(key) < 10:
        return False
    
    # Check expected prefixes for known key types
    expected_prefixes = {
        "openai": "sk-",
        "gemini": "AI",  # Gemini keys typically start with AI
        "stripe_secret": ("sk_live_", "sk_test_", "rk_live_", "rk_test_"),
        "stripe_publishable": ("pk_live_", "pk_test_"),
    }
    
    if key_type in expected_prefixes:
        prefix = expected_prefixes[key_type]
        if isinstance(prefix, tuple):
            return any(key.startswith(p) for p in prefix)
        return key.startswith(prefix)
    
    return True  # Unknown key type - accept any format


def _get_api_key(env_var: str, bundled_key: str, key_type: str = "") -> str:
    """
    Get API key with fallback to bundled key.
    
    Args:
        env_var: Environment variable name to check first.
        bundled_key: Bundled key to use as fallback.
        key_type: Optional key type for format validation logging.
        
    Returns:
        API key string, or empty string if not found.
    """
    # Try environment variable first (allows user override)
    key = os.getenv(env_var, "")
    if key:
        # Log warning if format looks wrong (doesn't prevent usage)
        if key_type and not _validate_api_key_format(key, key_type):
            import logging
            logging.getLogger(__name__).warning(
                f"{env_var} may have invalid format for {key_type} key"
            )
        return key
    # Fall back to bundled key
    return bundled_key


# OpenAI Configuration
OPENAI_API_KEY = _get_api_key("OPENAI_API_KEY", _BUNDLED_OPENAI_KEY, "openai")
OPENAI_VISION_MODEL = "gpt-4o-mini"  # For image analysis (person/gadget detection)

# Gemini Configuration
GEMINI_API_KEY = _get_api_key("GEMINI_API_KEY", _BUNDLED_GEMINI_KEY, "gemini")
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

# Save reports to user's Downloads folder (with fallback)
def _get_reports_dir() -> Path:
    """Get the reports directory with fallback if Downloads doesn't exist."""
    downloads = Path.home() / "Downloads"
    if downloads.exists() and downloads.is_dir():
        return downloads
    # Fallback to Documents or home directory
    documents = Path.home() / "Documents"
    if documents.exists() and documents.is_dir():
        return documents
    # Last resort: user data directory
    return USER_DATA_DIR / "reports"

REPORTS_DIR = _get_reports_dir()

# Bundled data directory (read-only resources included in the app)
BUNDLED_DATA_DIR = BASE_DIR / "data"

# Ensure user data directories exist
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    import logging
    logging.getLogger(__name__).error(f"Failed to create data directory {DATA_DIR}: {e}")
# Downloads folder always exists, no need to create it

# Event types
EVENT_PRESENT = "present"
EVENT_AWAY = "away"
EVENT_GADGET_SUSPECTED = "gadget_suspected"
EVENT_PAUSED = "paused"  # User manually paused the session
EVENT_SCREEN_DISTRACTION = "screen_distraction"  # Distracting website/app detected

# Gadget detection presets (user can enable/disable which gadgets count as distractions)
GADGET_PRESETS = {
    "phone": {"name": "Phone", "description": "Smartphones (5-7 inch devices)"},
    "tablet": {"name": "Tablet / iPad", "description": "Tablets and iPads (8+ inch)"},
    "controller": {"name": "Game Controller", "description": "PS5, Xbox, generic controllers"},
    "tv": {"name": "TV / TV Remote", "description": "Television and remote control usage"},
    "nintendo_switch": {"name": "Nintendo Switch", "description": "Nintendo Switch handheld/docked"},
    "smartwatch": {"name": "Smartwatch", "description": "Apple Watch, Fitbit, Galaxy Watch"},
}
DEFAULT_ENABLED_GADGETS = {"phone"}  # Only phone enabled by default

# Monitoring modes
MODE_CAMERA_ONLY = "camera_only"  # Default - only camera monitoring
MODE_SCREEN_ONLY = "screen_only"  # Only screen monitoring (no camera)
MODE_BOTH = "both"  # Camera + screen monitoring

# Screen monitoring settings
SCREEN_CHECK_INTERVAL = 3  # Seconds between screen checks (cheaper than camera)
SCREEN_SETTINGS_FILE = USER_DATA_DIR / "blocklist.json"  # Blocklist persistence (user data)
SCREEN_AI_FALLBACK_ENABLED = False  # Enable AI Vision fallback (costs ~$0.001-0.002 per check)

# Unfocussed alert settings
# Alert plays at each of these thresholds (in seconds) when user is unfocussed
# After all alerts play, no more until user refocusses
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

# Supabase Configuration (auth, settings sync, session upload)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# Web dashboard URL (opened by "Open Dashboard" menu item)
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://braindock.com")

# Licensing Configuration (offline fallback — Supabase is the primary source)
LICENSE_FILE = USER_DATA_DIR / "license.json"  # User's license (persists)
SKIP_LICENSE_CHECK = os.getenv("SKIP_LICENSE_CHECK", "").lower() in ("true", "1", "yes")
