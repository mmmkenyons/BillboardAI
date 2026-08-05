"""BillboardAI configuration."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FOLDER = str(OUTPUT_DIR)
HTML_FOLDER = str(OUTPUT_DIR / "html")
CSS_FOLDER = str(OUTPUT_DIR / "css")
ASSETS_FOLDER = str(OUTPUT_DIR / "assets")
JSON_FOLDER = str(OUTPUT_DIR / "json")
IMAGE_FOLDER = str(OUTPUT_DIR / "images")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    " AppleWebKit/537.36 Chrome/126 Safari/537.36"
)

TIMEOUT = 30000

CONFIG = {
    "project_name": "BillboardAI",
    "output_dir": OUTPUT_FOLDER,
}
