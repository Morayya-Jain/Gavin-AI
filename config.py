"""Configuration settings for Gavin AI."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).parent

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_VISION_MODEL = "gpt-4o-mini"  # For image analysis (person/phone detection)

# Vision API settings
VISION_DETECTION_INTERVAL = 1.0  # Analyze frames every N seconds (to save costs)
PHONE_CONFIDENCE_THRESHOLD = 0.5  # Confidence threshold for phone detection

# Detection thresholds
FACE_DETECTION_CONFIDENCE = 0.5
AWAY_GRACE_PERIOD_SECONDS = 3  # How long before marking as "away"
PHONE_DETECTION_ANGLE_THRESHOLD = 25  # degrees (head tilt down) - Legacy, still used in scoring
PHONE_DETECTION_DURATION_SECONDS = 3  # How long distraction must persist
DISTRACTION_SCORE_THRESHOLD = 35  # Score 0-100, >35 = distracted (more sensitive!)
STATE_CHANGE_DEBOUNCE_SECONDS = 3  # Prevent rapid state changes

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
DETECTION_FPS = 0.333  # Frames per second to analyse

# Paths
DATA_DIR = BASE_DIR / "data" / "sessions"
# Save reports directly to user's Downloads folder
REPORTS_DIR = Path.home() / "Downloads"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Downloads folder always exists, no need to create it

# Event types
EVENT_PRESENT = "present"
EVENT_AWAY = "away"
EVENT_PHONE_SUSPECTED = "phone_suspected"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # Can override in .env: DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

