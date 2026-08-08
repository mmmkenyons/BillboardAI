"""Brand asset data model for BillboardAI.

BrandAsset represents a VALIDATED visual image asset with real image metadata.
It is NOT used for arbitrary downloaded files — only for confirmed raster images.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


@dataclass
class BrandAsset:
    """A validated visual brand asset with real image metadata.

    Only instantiate after content-based validation confirms the file
    is a supported raster image (PNG, JPEG, WEBP, etc.).

    Attributes:
        path: Absolute or relative filesystem path to the normalized file.
        source_url: Original download URL.
        asset_type: Semantic role (e.g. "logo", "hero", "generic").
        mime_type: Detected MIME type (e.g. "image/png").
        format: Detected image format (e.g. "PNG", "JPEG", "WEBP").
        width: Image width in pixels.
        height: Image height in pixels.
        aspect_ratio: width / height as a float.
        has_alpha: Whether the image has an alpha/transparency channel.
        file_size: File size in bytes.
        quality_score: Reserved for future ranking (default 0.0).
        selection_score: Reserved for future ranking (default 0.0).
        confidence: Confidence in this asset being a valid brand asset (0.0-1.0).
    """

    path: str
    source_url: str
    asset_type: str = "generic"
    mime_type: str = ""
    format: str = ""
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    has_alpha: bool = False
    file_size: int = 0
    quality_score: float = 0.0
    selection_score: float = 0.0
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary for JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BrandAsset:
        """Deserialize from a dictionary."""
        # Filter to only known fields to be forward-compatible
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)