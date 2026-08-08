"""Asset normalizer for BillboardAI.

Validates downloaded files as real raster images and produces BrandAsset
metadata with canonical file extensions.

Actual file content is authoritative — URL suffix and Content-Type are
never trusted blindly.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from PIL import Image, UnidentifiedImageError

from ..brand_profile import BrandAsset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical extension mapping (PIL format name → canonical extension)
# ---------------------------------------------------------------------------
CANONICAL_EXTENSION: dict[str, str] = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tiff",
    "ICO": ".ico",
}

# MIME types we accept as visual raster images
SUPPORTED_MIME_PREFIXES: tuple[str, ...] = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/x-tiff",
    "image/vnd.microsoft.icon",
    "image/x-icon",
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class NormalizationError(Exception):
    """Raised when a downloaded file cannot be validated as a visual asset."""


def normalize_asset(
    file_path: str,
    source_url: str,
    content_type: Optional[str] = None,
    asset_type: str = "generic",
) -> Optional[BrandAsset]:
    """Validate a downloaded file and return BrandAsset metadata.

    Returns ``None`` when the file is not a supported raster image.
    The caller should treat ``None`` as "skip this candidate" — it is
    not a crash-worthy error.

    Raises ``NormalizationError`` only for truly unexpected conditions
    (e.g. the file disappeared between download and validation).
    """
    if not file_path or not os.path.isfile(file_path):
        logger.debug("normalize_asset: file not found %s", file_path)
        return None

    file_size = _safe_file_size(file_path)
    if file_size == 0:
        logger.debug("normalize_asset: zero-byte file %s", file_path)
        return None

    # --- content-based image detection ----------------------------------
    try:
        with Image.open(file_path) as img:
            # Force PIL to actually load pixel data so we catch truncated files
            img.load()

            fmt: str = img.format or ""
            width: int = img.width or 0
            height: int = img.height or 0

            if not fmt or width == 0 or height == 0:
                logger.debug("normalize_asset: no format or zero dimensions in %s", file_path)
                return None

            # Check that the format maps to a canonical extension we support
            canonical_ext = CANONICAL_EXTENSION.get(fmt.upper())
            if canonical_ext is None:
                logger.debug(
                    "normalize_asset: unsupported PIL format %r in %s", fmt, file_path
                )
                return None

            mime_type = _detect_mime(img, content_type)
            has_alpha = _detect_alpha(img)
            aspect_ratio = round(width / height, 6) if height else 0.0

    except UnidentifiedImageError:
        logger.debug("normalize_asset: PIL cannot identify %s", file_path)
        return None
    except Exception:
        logger.warning("normalize_asset: unexpected error reading %s", file_path, exc_info=True)
        return None

    # --- canonical rename -----------------------------------------------
    normalized_path = _rename_to_canonical(file_path, canonical_ext)

    return BrandAsset(
        path=normalized_path,
        source_url=source_url,
        asset_type=asset_type,
        mime_type=mime_type,
        format=fmt.upper(),
        width=width,
        height=height,
        aspect_ratio=aspect_ratio,
        has_alpha=has_alpha,
        file_size=file_size,
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_file_size(path: str) -> int:
    """Return file size in bytes, or 0 on error."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _detect_mime(img: Image.Image, content_type: Optional[str]) -> str:
    """Determine the best MIME type from PIL format and optional Content-Type.

    PIL's ``get_format_mimetype()`` is preferred; Content-Type is only a
    fallback when PIL cannot determine the MIME.
    """
    fmt = (img.format or "").upper()
    try:
        from PIL.Image import MIME as PIL_MIME
        return PIL_MIME.get(fmt, "")
    except ImportError:
        pass

    # Fallback: use Content-Type if it looks like an image
    if content_type and any(
        content_type.lower().startswith(p) for p in SUPPORTED_MIME_PREFIXES
    ):
        return content_type.lower()
    return ""


def _detect_alpha(img: Image.Image) -> bool:
    """Return True if the image has a real alpha channel."""
    mode = (img.mode or "").upper()
    if mode in ("RGBA", "PA", "LA"):
        return True
    if mode == "P" and "transparency" in (img.info or {}):
        return True
    return False


def _rename_to_canonical(original_path: str, canonical_ext: str) -> str:
    """Rename *original_path* so its extension matches *canonical_ext*.

    If the extension already matches, the file is left as-is.
    Collisions are avoided by appending a counter (e.g. ``_1``).
    """
    current_ext = os.path.splitext(original_path)[1].lower()
    if current_ext == canonical_ext.lower():
        return original_path

    base = os.path.splitext(original_path)[0]
    candidate = base + canonical_ext

    # Avoid overwriting an existing file
    if os.path.normcase(candidate) == os.path.normcase(original_path):
        return original_path

    counter = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{counter}{canonical_ext}"
        counter += 1

    try:
        os.rename(original_path, candidate)
        logger.info("Renamed %s → %s", os.path.basename(original_path), os.path.basename(candidate))
    except OSError:
        logger.warning("Could not rename %s → %s", original_path, candidate)
        return original_path

    return candidate