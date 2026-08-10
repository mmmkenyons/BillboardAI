"""Deterministic typography system for the Creative Layout layer.

Role-based font lookup with no brand-font-matching. The FontRegistry resolves a
font for a typographic role (headline_bold / proof / cta_bold), trying in order:
  1. project fonts/ directory (if a font is later bundled there)
  2. the Windows font directory
  3. a bare system font name (resolved by Pillow)
  4. Pillow's default bitmap font only as an emergency fallback

All font sizes scale from the artwork height so the same layout reads
proportionally at e.g. 752x300 and 552x400. Sizes are sized for outdoor
readability: proof is deliberately large (a proof too small to read is omitted
elsewhere), never fine print.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import ImageFont

from engine.ad_concept import BRAND_DOMINANT, LOCAL_AUTHORITY, MESSAGE_DOMINANT

HEADLINE_BOLD = "headline_bold"
PROOF = "proof"
CTA_BOLD = "cta_bold"

ROLE_PRIORITY: Dict[str, List[str]] = {
    HEADLINE_BOLD: ["segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf"],
    CTA_BOLD: ["segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf"],
    PROOF: ["segoeui.ttf", "arial.ttf", "segoeuib.ttf", "arialbd.ttf"],
}


class FontRegistry:
    """Caches and resolves fonts by typographic role."""

    def __init__(self, project_fonts_dir: str = "", windows_fonts_dir: str = "") -> None:
        self._cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        if project_fonts_dir:
            self._project_dir = Path(project_fonts_dir)
        else:
            self._project_dir = self._default_project_fonts_dir()
        self._win_dir = Path(
            windows_fonts_dir or (os.environ.get("WINDIR", "C:/Windows") + "/Fonts")
        )

    @staticmethod
    def _default_project_fonts_dir() -> Path:
        # engine/layout/typography.py -> parents[2] is the repo root.
        return Path(__file__).resolve().parents[2] / "fonts"

    def _candidates(self, name: str) -> List[str]:
        paths: List[str] = []
        if self._project_dir:
            paths.append(str(self._project_dir / name))
        if self._win_dir:
            paths.append(str(self._win_dir / name))
        paths.append(name)
        return paths

    def resolve(self, role: str, size: int) -> ImageFont.FreeTypeFont:
        """Return a cached font for role at size (deterministic)."""
        size = max(1, int(size))
        key = (role, size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        for name in ROLE_PRIORITY.get(role, ROLE_PRIORITY[PROOF]):
            for path in self._candidates(name):
                font = self._try_load(path, size)
                if font is not None:
                    self._cache[key] = font
                    return font

        font = ImageFont.load_default()
        self._cache[key] = font
        return font

    @staticmethod
    def _try_load(path: str, size: int):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            return None


def text_height(font) -> int:
    """Approximate single-line cap height for a loaded font."""
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except Exception:
        return getattr(font, "size", 16) or 16


def headline_init(family: str, height: int) -> int:
    """Target headline size before fitting, scaled to artwork height."""
    h = max(1, int(height))
    if family == MESSAGE_DOMINANT:
        return max(26, round(0.18 * h))
    if family == LOCAL_AUTHORITY:
        return max(22, round(0.14 * h))
    return max(20, round(0.12 * h))  # BRAND_DOMINANT


def min_headline_size(height: int) -> int:
    return max(16, round(0.05 * height))


def proof_size(height: int) -> int:
    return max(14, round(0.05 * height))


def proof_min_size(height: int) -> int:
    return max(12, round(0.04 * height))


def cta_size(height: int) -> int:
    return max(16, round(0.06 * height))


def cta_min_size(height: int) -> int:
    return max(14, round(0.045 * height))
