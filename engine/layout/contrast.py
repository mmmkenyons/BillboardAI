"""Deterministic WCAG-style contrast calculations for the Creative Layout layer.

BrandProfile.colors are CANDIDATES, never design instructions. This module selects
a palette (background / field / text / accent) from measurable relative luminance
and contrast ratio.

It prefers a strong brand color as the background when doing so stays readable, and
otherwise falls back to safe neutral black-on-white / white-on-black. A brand
``field`` color provides brand presence in strong color blocks (e.g. a logo panel)
without compromising text contrast.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from engine.layout.model import LayoutPalette

# Safe terminal neutral pairs that always pass WCAG body contrast.
_NEAR_BLACK = "#111111"
_NEAR_WHITE = "#F4F4F4"
_NEUTRAL = ("#FFFFFF", "#000000", "#111111")

BODY_RATIO = 4.5
HEADLINE_RATIO = 3.0
ACCENT_RATIO = 3.0
FIELD_RATIO = 3.0

# Cap neutral contrast so a strong brand color can win the background when safe
# (a brand closer to the cap beats plain white/black by the brand bonus).
_RATIO_CAP = 12.0
_BRAND_BONUS = 0.9


def hex_to_rgb(value: str) -> Optional[Tuple[int, int, int]]:
    """Parse a hex color (3 or 6 hex digits, optional '#') into (r, g, b)."""
    if not value:
        return None
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _linearize(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG-relative luminance of a hex color (0..1)."""
    rgb = hex_to_rgb(color)
    if rgb is None:
        return 0.0
    r, g, b = (_linearize(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colors (>= 1.0)."""
    la = relative_luminance(a)
    lb = relative_luminance(b)
    lighter = max(la, lb)
    darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def is_dark(color: str) -> bool:
    return relative_luminance(color) < 0.5


def choose_text_on(background: str) -> str:
    """Pick _NEAR_BLACK or _NEAR_WHITE text for the given background."""
    black_ratio = contrast_ratio(_NEAR_BLACK, background)
    white_ratio = contrast_ratio(_NEAR_WHITE, background)
    return _NEAR_BLACK if black_ratio >= white_ratio else _NEAR_WHITE


def _dedupe(colors: List[str]) -> List[str]:
    seen = set()
    out = []
    for c in colors:
        key = str(c).strip().upper()
        if key and key not in seen:
            seen.add(key)
            out.append(str(c).strip())
    return out


def _capped(ratio: float) -> float:
    return min(ratio, _RATIO_CAP)


def resolve_palette(colors: Optional[List[str]]) -> LayoutPalette:
    """Select background / field / text / accent from brand color candidates.

    Strategy:
      1. Background: prefer a strong brand color that yields >= BODY_RATIO text
         contrast (capped-ratio + brand bonus beats plain white/black).
      2. Text: black or white chosen by luminance for the selected background.
      3. Accent: a brand color distinct from bg with >= ACCENT_RATIO contrast,
         else falls back to the text color (always safe).
      4. Field: a brand color distinct from bg and accent with >= FIELD_RATIO
         contrast, else falls back to the text color.
    """
    safe_neutrals = ["#FFFFFF", _NEAR_BLACK]
    all_candidates = _dedupe(list(colors or []) + safe_neutrals)
    brand = _dedupe(list(colors or []))

    def _is_brand(c: str) -> bool:
        # A brand color counts as a distinctive background only when it is not a
        # neutral and not near-white (so a passed-in pure white cannot tie with a
        # real brand color like navy).
        upper = c.upper()
        if upper in _NEUTRAL:
            return False
        if relative_luminance(c) >= 0.88:
            return False
        return any(upper == b.upper() for b in brand)

    best_bg = "#FFFFFF"
    best_score = -1.0
    for bg in all_candidates:
        if hex_to_rgb(bg) is None:
            continue
        text = choose_text_on(bg)
        r = contrast_ratio(text, bg)
        if r < BODY_RATIO:
            continue
        score = _capped(r) + (_BRAND_BONUS if _is_brand(bg) else 0.0)
        if score > best_score:
            best_score, best_bg = score, bg
    text = choose_text_on(best_bg)

    accent = text
    best_accent_ratio = -1.0
    for c in brand:
        if hex_to_rgb(c) is None or c.upper() == best_bg.upper():
            continue
        r = contrast_ratio(c, best_bg)
        if r >= ACCENT_RATIO and r > best_accent_ratio:
            best_accent_ratio, accent = r, c

    field = text
    best_field_ratio = -1.0
    for c in brand:
        if hex_to_rgb(c) is None:
            continue
        if c.upper() == best_bg.upper() or c.upper() == accent.upper():
            continue
        r = contrast_ratio(c, best_bg)
        if r >= FIELD_RATIO and r > best_field_ratio:
            best_field_ratio, field = r, c

    return LayoutPalette(background=best_bg, field=field, text=text, accent=accent)
