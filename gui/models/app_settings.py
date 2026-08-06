"""Application-level settings model for the BillboardAI GUI."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

# Default output location shown in the UI. The user can override this via
# the folder picker; the GUI does not depend on the CLI/engine config.
DEFAULT_OUTPUT_FOLDER = "output"

# Where lightweight app settings are persisted.
_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "resources" / "app_settings.json"


@dataclass
class AppSettings:
    """User-facing application settings persisted to a lightweight JSON file.

    Tracks the last opened project so the app can offer a restore prompt
    on startup without scanning the filesystem.
    """

    default_output_folder: str = DEFAULT_OUTPUT_FOLDER
    theme: str = "dark"
    last_project_path: str = ""
    recent_urls: list = field(default_factory=list)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "AppSettings":
        """Load settings from disk. Returns defaults if file is missing."""
        settings_path = Path(path) if path else _SETTINGS_PATH
        try:
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                return cls(**data)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not load app settings: %s", exc)
        return cls()

    def save(self, path: str | os.PathLike | None = None) -> None:
        """Persist settings to disk."""
        settings_path = Path(path) if path else _SETTINGS_PATH
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(asdict(self), indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Could not save app settings: %s", exc)

    def update_last_project(self, project_path: str) -> None:
        """Set the last opened project path and persist immediately."""
        self.last_project_path = project_path
        self.save()
