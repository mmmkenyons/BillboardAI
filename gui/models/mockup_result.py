"""Data model describing the result of a mockup generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MockupResult:
    """The outcome of a mockup generation request.

    Fields are populated by the engine bridge after a generation run.
    Unavailable information is left blank rather than invented.
    """

    success: bool = False
    message: str = ""
    website: str = ""
    output_path: str = ""
    preview_path: str = ""
    upload_url: str = ""

    # Content fields produced by the engine (populated later).
    company_name: str = ""
    logo_path: str = ""
    headline: str = ""
    cta: str = ""
    quality_score: float = 0.0

    # Metadata.
    elapsed_time: float = 0.0
    warnings: list = field(default_factory=list)
    created_at: datetime | None = None
    extra: dict = field(default_factory=dict)
    capture_error: str = ""  # For ScreenshotValidationError details
