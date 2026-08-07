"""BillboardAI configuration."""

from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FOLDER = str(OUTPUT_DIR)
HTML_FOLDER = str(OUTPUT_DIR / "html")
CSS_FOLDER = str(OUTPUT_DIR / "css")
ASSETS_FOLDER = str(OUTPUT_DIR / "assets")
JSON_FOLDER = str(OUTPUT_DIR / "json")
IMAGE_FOLDER = str(OUTPUT_DIR / "images")
DEBUG_FOLDER = str(OUTPUT_DIR / "debug")  # For rejected screenshots and diagnostics

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    " AppleWebKit/537.36 Chrome/126 Safari/537.36"
)

TIMEOUT = 30000

# Screenshot validation & debug
DEBUG = os.getenv("BILLBOARD_DEBUG", "false").lower() in ("true", "1", "yes")
SCREENSHOT_VARIANCE_THRESHOLD = 10.0
MIN_STDDEV = 5.0
MIN_DIMENSION = 300
DEBUG_REJECTED_FOLDER = str(Path(DEBUG_FOLDER) / "rejected")
RETRY_STRATEGIES = ["networkidle", "load"]  # Order for retries

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

SMARTLEAD_FIELDS = [
    "First Name",
    "Last Name",
    "Email",
    "Company",
    "Website",
    "Custom_Image",
    "Headline",
    "Quality Score",
    "Quality Label",
    "Vision Score",
    "Vision Label",
]

BATCH_STATUS_FILE = str(OUTPUT_DIR / "batch_status.json")

CONFIG = {
    "project_name": "BillboardAI",
    "output_dir": OUTPUT_FOLDER,
    "debug": DEBUG,
}

# Expose all for * imports and direct access (config.VAR)
__all__ = [
    "BASE_DIR", "OUTPUT_DIR", "OUTPUT_FOLDER", "HTML_FOLDER", "CSS_FOLDER",
    "ASSETS_FOLDER", "JSON_FOLDER", "IMAGE_FOLDER", "DEBUG_FOLDER",
    "USER_AGENT", "TIMEOUT", "DEBUG", "SCREENSHOT_VARIANCE_THRESHOLD",
    "MIN_STDDEV", "MIN_DIMENSION", "DEBUG_REJECTED_FOLDER", "RETRY_STRATEGIES",
    "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
    "SMARTLEAD_FIELDS", "BATCH_STATUS_FILE", "CONFIG",
]
