"""Typed data contracts for the BillboardAI Creative Layout layer (Sprint 2G).

These are PURE DATA objects with no physical-scene coordinates and no Pillow
drawing logic. They describe a resolved rectangular advertisement composition so
the artifact renderer and the quality checker can consume one deterministic
contract.

CreativeLayoutSpec is produced by CreativeLayoutEngine from an AdConcept +
BrandProfile + requested artwork dimensions. It separates AdConcept decisions
(which elements / hierarchy) from the pixel contract (where / size / color /
type).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

Rect = Tuple[int, int, int, int]  # x0, y0, x1, y1


def contain_size(avail_w: int, avail_h: int, aspect: float) -> Tuple[int, int]:
    """Return (w, h) that fits inside avail_w x avail_h preserving aspect."""
    if avail_w <= 0 or avail_h <= 0:
        return (0, 0)
    if aspect is None or aspect <= 0:
        return (int(avail_w), int(avail_h))
    w = float(avail_w)
    h = w / aspect
    if h > avail_h:
        h = float(avail_h)
        w = h * aspect
    return int(w), int(h)


def rect_overlap_area(a: Rect, b: Rect) -> int:
    """Intersection area of two rects; 0 when they do not overlap."""
    x = min(a[2], b[2]) - max(a[0], b[0])
    y = min(a[3], b[3]) - max(a[1], b[1])
    if x <= 0 or y <= 0:
        return 0
    return x * y


def rects_overlap(a: Rect, b: Rect) -> bool:
    return rect_overlap_area(a, b) > 0


@dataclass(frozen=True)
class LayoutText:
    """A resolved text element: content, geometry, and typography.

    ``lines`` holds the measured, wrapped lines so the drawer never re-measures
    (avoiding fit/draw drift) and the quality checker can verify them.
    """

    kind: str  # "headline" | "proof" | "cta"
    text: str
    rect: Rect
    alignment: str  # "left" | "center" | "right"
    font: str  # typographic role key, e.g. "headline_bold"
    font_size: int
    max_lines: int
    lines: Tuple[str, ...] = ()
    line_height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "rect": list(self.rect),
            "alignment": self.alignment,
            "font": self.font,
            "font_size": self.font_size,
            "max_lines": self.max_lines,
            "lines": list(self.lines),
            "line_height": self.line_height,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LayoutText":
        if not isinstance(data, dict):
            data = {}
        rect = data.get("rect") or (0, 0, 0, 0)
        lines = data.get("lines") or []
        return cls(
            kind=str(data.get("kind", "")),
            text=str(data.get("text", "")),
            rect=tuple(int(v) for v in rect)[:4],
            alignment=str(data.get("alignment", "center")),
            font=str(data.get("font", "proof")),
            font_size=int(data.get("font_size", 0) or 0),
            max_lines=int(data.get("max_lines", 1) or 1),
            lines=tuple(str(v) for v in lines),
            line_height=int(data.get("line_height", 0) or 0),
        )


@dataclass(frozen=True)
class LayoutLogo:
    """A resolved, aspect-preserving logo placement."""

    path: str
    rect: Rect
    source_aspect: float
    alignment: str = "center"
    paste_size: Optional[Tuple[int, int]] = None  # actual contained w,h

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "rect": list(self.rect),
            "source_aspect": self.source_aspect,
            "alignment": self.alignment,
            "paste_size": list(self.paste_size) if self.paste_size else None,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LayoutLogo":
        if not isinstance(data, dict):
            data = {}
        rect = data.get("rect") or (0, 0, 0, 0)
        ps = data.get("paste_size")
        return cls(
            path=str(data.get("path", "")),
            rect=tuple(int(v) for v in rect)[:4],
            source_aspect=float(data.get("source_aspect", 0.0) or 0.0),
            alignment=str(data.get("alignment", "center")),
            paste_size=(tuple(int(v) for v in ps)[:2] if ps else None),
        )


@dataclass(frozen=True)
class LayoutPalette:
    background: str
    text: str
    accent: str
    field: str = "#FFFFFF"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "background": self.background,
            "text": self.text,
            "accent": self.accent,
            "field": self.field,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LayoutPalette":
        if not isinstance(data, dict):
            data = {}
        return cls(
            background=str(data.get("background", "#FFFFFF")),
            text=str(data.get("text", "#111111")),
            accent=str(data.get("accent", "#111111")),
            field=str(data.get("field", "#FFFFFF")),
        )


@dataclass(frozen=True)
class CreativeLayoutSpec:
    """The complete, resolved rectangular advertisement contract.

    Drawn onto a PIL image of exactly (artwork_width, artwork_height). No
    physical-scene geometry lives here.
    """

    artwork_width: int
    artwork_height: int
    composition_family: str
    palette: LayoutPalette
    headline: Optional[LayoutText]
    proofs: Tuple[LayoutText, ...]
    cta: Optional[LayoutText]
    logo: Optional[LayoutLogo]
    field_rect: Optional[Rect] = None
    geometry_valid: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artwork_width": self.artwork_width,
            "artwork_height": self.artwork_height,
            "composition_family": self.composition_family,
            "palette": self.palette.to_dict(),
            "headline": self.headline.to_dict() if self.headline else None,
            "proofs": [p.to_dict() for p in self.proofs],
            "cta": self.cta.to_dict() if self.cta else None,
            "logo": self.logo.to_dict() if self.logo else None,
            "field_rect": list(self.field_rect) if self.field_rect else None,
            "geometry_valid": self.geometry_valid,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CreativeLayoutSpec":
        if not isinstance(data, dict):
            data = {}
        proofs = data.get("proofs") or []
        headline_raw = data.get("headline")
        cta_raw = data.get("cta")
        logo_raw = data.get("logo")
        field_raw = data.get("field_rect")
        return cls(
            artwork_width=int(data.get("artwork_width", 0) or 0),
            artwork_height=int(data.get("artwork_height", 0) or 0),
            composition_family=str(data.get("composition_family", "")),
            palette=LayoutPalette.from_dict(data.get("palette")),
            headline=(
                LayoutText.from_dict(headline_raw)
                if isinstance(headline_raw, dict)
                else None
            ),
            proofs=tuple(LayoutText.from_dict(p) for p in proofs),
            cta=LayoutText.from_dict(cta_raw) if isinstance(cta_raw, dict) else None,
            logo=LayoutLogo.from_dict(logo_raw) if isinstance(logo_raw, dict) else None,
            field_rect=(
                tuple(int(v) for v in field_raw)[:4] if isinstance(field_raw, list) else None
            ),
            geometry_valid=bool(data.get("geometry_valid", False)),
        )
