"""Application-level settings model for the GUI."""

from __future__ import annotations

from dataclasses import dataclass, field

# Default output location shown in the UI. The user can override this via
# the folder picker; the GUI does not depend on the CLI/engine config.
DEFAULT_OUTPUT_FOLDER = "output"


@dataclass
class AppSettings:
    """User-facing application settings.

    Placeholder model; values will be persisted/loaded once settings
    functionality is implemented.
    """

    default_output_folder: str = "output"
    theme: str = "dark"
    recent_urls: list = field(default_factory=list)