"""Data model describing the result of a mockup generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MockupResult:
    """The outcome of a mockup generation request.

    Fields are placeholders for the data the GUI will need once the engine
    pipeline is wired up. They default to empty/neutral values so the model
    can be constructed before any real generation happens.
    """

    success: bool = False
    message: str = ""
    output_path: str = ""

    # Content fields produced by the engine (populated later).
    company_name: str = ""
    logo_path: str = ""
    headline: str = ""
    cta: str = ""
    quality_score: float = 0.0

    # Metadata.
    created_at: datetime | None = None
    extra: dict = field(default_factory=dict)