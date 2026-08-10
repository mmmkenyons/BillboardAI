"""Per-family slot geometry for the Creative Layout MVP (Sprint 2G, polished).

Produces slot rectangles (bounds boxes) for the three implemented families at a
given artwork size. Layouts are deterministic fractional templates with a
wide/portrait branch so a single concept resolves at both 752x300 and 552x400.

Visual polish principles (Sprint 2G visual gate):
  - CTA is a strong full-width bottom band (outdoor callout, not a UI pill).
  - Content is grouped into deliberate blocks (tight gaps) and vertically
    centered, avoiding dispersed floating elements.
  - A brand ``field`` panel backs the logo zone for visual mass.
  - Each family keeps a distinct structure:
      BRAND_DOMINANT   - logo co-dominates in a large brand field; brand-first.
      MESSAGE_DOMINANT - headline overwhelmingly dominant; logo tiny corner.
      LOCAL_AUTHORITY  - geo headline anchor + prominent logo + credibility proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from engine.layout import typography
from engine.layout.model import Rect
from engine.ad_concept import BRAND_DOMINANT, LOCAL_AUTHORITY, MESSAGE_DOMINANT

WIDE_THRESHOLD = 1.6


@dataclass
class Slots:
    logo_rect: Optional[Rect]
    headline_rect: Rect
    proof_rects: List[Rect]
    cta_rect: Optional[Rect]
    field_rect: Optional[Rect]


def _margin(w: int, h: int) -> int:
    return max(12, round(min(w, h) * 0.06))


def _gap(w: int, h: int) -> int:
    return max(6, round(min(w, h) * 0.015))


def _group_gap(w: int, h: int) -> int:
    return max(10, round(min(w, h) * 0.03))


def _headline_reserve(family: str, h: int) -> int:
    return round(typography.headline_init(family, h) * 2.0) + 4


def _proof_reserve(h: int) -> int:
    return round(typography.proof_size(h) * 1.9) + 6


def _cta_reserve(h: int) -> int:
    return round(typography.cta_size(h) * 2.5) + 6


def _content_headline_and_proofs(
    w: int,
    h: int,
    rx0: int,
    ry0: int,
    rx1: int,
    ry1: int,
    family: str,
    n_proofs: int,
    gap: int,
) -> Tuple[Rect, List[Rect]]:
    """Headline + proofs grouped tightly and vertically centered in a region."""
    hh = _headline_reserve(family, h)
    ph = _proof_reserve(h)
    items = [hh] + [ph] * n_proofs
    total = sum(items) + gap * max(0, len(items) - 1)
    y = ry0 + max(0, (ry1 - ry0 - total) // 2)
    headline_rect = (rx0, y, rx1, min(ry1, y + hh))
    y = headline_rect[3] + gap
    proof_rects: List[Rect] = []
    for _ in range(n_proofs):
        proof_rects.append((rx0, y, rx1, min(ry1, y + ph)))
        y += ph + gap
    return headline_rect, proof_rects


def _cta_band(w: int, h: int, has_cta: bool) -> Optional[Rect]:
    if not has_cta:
        return None
    m = _margin(w, h)
    ch = _cta_reserve(h)
    return (m, h - m - ch, w - m, h - m)


def _build_brand_dominant(w: int, h: int, has_logo: bool, n_proofs: int, has_cta: bool) -> Slots:
    m = _margin(w, h)
    gap = _gap(w, h)
    cta = _cta_band(w, h, has_cta)
    ry1 = cta[1] - _group_gap(w, h) if cta else h - m
    if w / h >= WIDE_THRESHOLD:
        cw = w - 2 * m
        colw = round(cw * 0.46) if has_logo else 0
        if has_logo and colw > 0:
            field_rect = (m, m, m + colw, ry1)
            logo_rect = field_rect
            rx0 = m + colw + _group_gap(w, h)
            rx1 = w - m
        else:
            field_rect = None
            logo_rect = None
            rx0, rx1 = m, w - m
        head, proofs = _content_headline_and_proofs(
            w, h, rx0, m, rx1, ry1, BRAND_DOMINANT, n_proofs, gap
        )
        return Slots(logo_rect, head, proofs, cta, field_rect)
    # Portrait: logo-first brand field, then grouped content.
    ch = h - 2 * m
    if has_logo:
        logo_h = round(ch * 0.26)
        field_rect = (m, m, w - m, m + logo_h)
        logo_rect = field_rect
        ry0 = field_rect[3] + _group_gap(w, h)
    else:
        field_rect = None
        logo_rect = None
        ry0 = m
    head, proofs = _content_headline_and_proofs(
        w, h, m, ry0, w - m, ry1, BRAND_DOMINANT, n_proofs, gap
    )
    return Slots(logo_rect, head, proofs, cta, field_rect)


def _build_message_dominant(w: int, h: int, has_logo: bool, n_proofs: int, has_cta: bool) -> Slots:
    m = _margin(w, h)
    gap = _gap(w, h)
    n_proofs = min(n_proofs, 1)  # MESSAGE_DOMINANT proof budget is 1.
    cta = _cta_band(w, h, has_cta)
    ry1 = cta[1] - _group_gap(w, h) if cta else h - m
    logo_rect = None
    field_rect = None
    if has_logo:
        lw = max(48, round((w - 2 * m) * 0.18))
        lh = max(24, round((h - 2 * m) * 0.12))
        logo_rect = (w - m - lw, m, w - m, m + lh)
        hx1 = w - m - lw - _group_gap(w, h)
    else:
        hx1 = w - m
    head, proofs = _content_headline_and_proofs(
        w, h, m, m, hx1, ry1, MESSAGE_DOMINANT, n_proofs, gap
    )
    return Slots(logo_rect, head, proofs, cta, field_rect)


def _build_local_authority(w: int, h: int, has_logo: bool, n_proofs: int, has_cta: bool) -> Slots:
    m = _margin(w, h)
    gap = _gap(w, h)
    cta = _cta_band(w, h, has_cta)
    ry1 = cta[1] - _group_gap(w, h) if cta else h - m
    if w / h >= WIDE_THRESHOLD:
        cw = w - 2 * m
        colw = round(cw * 0.36) if has_logo else 0
        if has_logo and colw > 0:
            field_rect = (m, m, m + colw, ry1)
            logo_rect = field_rect
            rx0 = m + colw + _group_gap(w, h)
            rx1 = w - m
        else:
            field_rect = None
            logo_rect = None
            rx0, rx1 = m, w - m
        head, proofs = _content_headline_and_proofs(
            w, h, rx0, m, rx1, ry1, LOCAL_AUTHORITY, n_proofs, gap
        )
        return Slots(logo_rect, head, proofs, cta, field_rect)
    ch = h - 2 * m
    if has_logo:
        logo_h = round(ch * 0.24)
        field_rect = (m, m, w - m, m + logo_h)
        logo_rect = field_rect
        ry0 = field_rect[3] + _group_gap(w, h)
    else:
        field_rect = None
        logo_rect = None
        ry0 = m
    head, proofs = _content_headline_and_proofs(
        w, h, m, ry0, w - m, ry1, LOCAL_AUTHORITY, n_proofs, gap
    )
    return Slots(logo_rect, head, proofs, cta, field_rect)


_BUILDERS = {
    BRAND_DOMINANT: _build_brand_dominant,
    MESSAGE_DOMINANT: _build_message_dominant,
    LOCAL_AUTHORITY: _build_local_authority,
}


def build_slots(family: str, w: int, h: int, has_logo: bool, n_proofs: int, has_cta: bool) -> Slots:
    """Return slot rectangles for a family at (w, h)."""
    builder = _BUILDERS.get(family)
    if builder is None:
        raise ValueError(f"Composition family '{family}' is not implemented in the MVP.")
    return builder(int(w), int(h), bool(has_logo), int(n_proofs), bool(has_cta))
