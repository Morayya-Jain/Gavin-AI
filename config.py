"""Configuration settings for the Focus Tracker application."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).parent

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"  # For text summaries
OPENAI_VISION_MODEL = "gpt-4o-mini"  # For image analysis (person/phone detection)
OPENAI_MAX_RETRIES = 3
OPENAI_RETRY_DELAY = 1  # seconds

# Vision API settings
VISION_DETECTION_INTERVAL = 1.0  # Analyze frames every N seconds (to save costs)
PHONE_CONFIDENCE_THRESHOLD = 0.5  # Confidence threshold for phone detection

# Detection thresholds
FACE_DETECTION_CONFIDENCE = 0.5
AWAY_GRACE_PERIOD_SECONDS = 5  # How long before marking as "away"
PHONE_DETECTION_ANGLE_THRESHOLD = 25  # degrees (head tilt down) - Legacy, still used in scoring
PHONE_DETECTION_DURATION_SECONDS = 2  # How long distraction must persist
DISTRACTION_SCORE_THRESHOLD = 35  # Score 0-100, >35 = distracted (more sensitive!)
STATE_CHANGE_DEBOUNCE_SECONDS = 2  # Prevent rapid state changes

# Camera Configuration
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
DETECTION_FPS = 1  # Analyze 1 frame per second for performance

# Paths
DATA_DIR = BASE_DIR / "data" / "sessions"
REPORTS_DIR = BASE_DIR / "reports"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Event types
EVENT_PRESENT = "present"
EVENT_AWAY = "away"
EVENT_PHONE_SUSPECTED = "phone_suspected"

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

