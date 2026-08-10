"""Creative quality validation for the Creative Layout layer.

Mechanical correctness (hard checks) is kept separate from visual-utility
warnings. Hard checks must pass for a spec to be render-ready; visual-utility
minimums (proof size, logo presence, headline weight, CTA weight) are also hard so
a mechanically correct but under-filled ad does not score 100/100. A soft
occupancy warning reports excessive dead space. Not an ML score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw

from engine.ad_concept import BRAND_DOMINANT, LOCAL_AUTHORITY, MESSAGE_DOMINANT
from engine.layout import contrast, typography
from engine.layout.model import (
    CreativeLayoutSpec,
    LayoutText,
    rect_overlap_area,
    rects_overlap,
)

LOGO_ASPECT_TOLERANCE = 0.02

# Logo must meaningfully fill its allotted field (at least half of one field
# dimension) when the family requires a prominent logo. MESSAGE_DOMINANT keeps
# its logo intentionally smaller (not enforced).
LOGO_FILL_MIN = 0.5

# Minimum CTA band area ratio (rect area / canvas area) when a CTA exists.
CTA_WEIGHT_MIN = 0.03
# Minimum headline font size as a fraction of artwork height (visual weight).
HEADLINE_WEIGHT_FRAC = 0.09
# Occupancy (union of content rects / canvas) below this triggers a dead-space warning.
OCCUPANCY_WARN = 0.22


def _rect_area(r) -> int:
    if r is None:
        return 0
    x0, y0, x1, y1 = r
    return max(0, x1 - x0) * max(0, y1 - y0)


@dataclass
class CreativeQualityResult:
    passed: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": dict(self.checks),
            "metrics": dict(self.metrics),
            "score": self.score,
            "notes": list(self.notes),
            "warnings": list(self.warnings),
        }


class CreativeQualityChecker:
    def __init__(self, registry: "Optional[typography.FontRegistry]" = None) -> None:
        self._registry = registry or typography.FontRegistry()

    def _empty_draw(self, spec: CreativeLayoutSpec) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(Image.new("RGB", (spec.artwork_width, spec.artwork_height)))

    def _lines_fit(self, draw, lt: LayoutText) -> bool:
        if not lt.lines or not lt.text.strip():
            return False
        font = self._registry.resolve(lt.font, lt.font_size)
        x0, y0, x1, y1 = lt.rect
        for line in lt.lines:
            if draw.textlength(line, font=font) > (x1 - x0) + 1:
                return False
        line_height = typography.text_height(font)
        total = line_height * len(lt.lines)
        return total <= (y1 - y0) + 1

    def _within_canvas(self, spec: CreativeLayoutSpec, rect) -> bool:
        if rect is None:
            return True
        w, h = spec.artwork_width, spec.artwork_height
        x0, y0, x1, y1 = rect
        return 0 <= x0 <= x1 <= w and 0 <= y0 <= y1 <= h

    def validate(self, spec: CreativeLayoutSpec) -> CreativeQualityResult:
        checks: Dict[str, bool] = {}
        notes: List[str] = []
        warnings: List[str] = []

        text_ratio = contrast.contrast_ratio(spec.palette.text, spec.palette.background)

        # Headline present.
        checks["headline_present"] = bool(
            spec.headline is not None and spec.headline.text.strip()
        )

        # All element rects within canvas.
        rects = [spec.headline.rect if spec.headline else None]
        rects += [p.rect for p in spec.proofs]
        if spec.cta:
            rects.append(spec.cta.rect)
        if spec.logo:
            rects.append(spec.logo.rect)
        if spec.field_rect:
            rects.append(spec.field_rect)
        present = [r for r in rects if r is not None]
        checks["all_within_canvas"] = all(self._within_canvas(spec, r) for r in present)
        checks["bounds_non_degenerate"] = bool(
            present and all(r[0] < r[2] and r[1] < r[3] for r in present)
        )

        # No unintended overlaps. The brand field panel deliberately backs the
        # logo (identical rect), so it is excluded from overlap bookkeeping.
        overlap_rects = [r for r in present if r is not spec.field_rect]
        overlap = False
        for i in range(len(overlap_rects)):
            for j in range(i + 1, len(overlap_rects)):
                if rects_overlap(overlap_rects[i], overlap_rects[j]):
                    overlap = True
                    break
        checks["no_overlap"] = not overlap

        # Text fits assigned rects / no clipping.
        fits = True
        if spec.headline and spec.headline.text.strip():
            fits = fits and self._lines_fit(self._empty_draw(spec), spec.headline)
        for p in spec.proofs:
            fits = fits and self._lines_fit(self._empty_draw(spec), p)
        if spec.cta and spec.cta.text.strip():
            fits = fits and self._lines_fit(self._empty_draw(spec), spec.cta)
        checks["text_fits"] = fits
        checks["no_clipping"] = fits

        # Headline overflow.
        ho = bool(
            spec.headline is None
            or not spec.headline.text.strip()
            or not spec.headline.lines
            or not fits_with_headline(spec)
        )
        checks["headline_overflow"] = not ho

        # Minimum readable sizes.
        min_hl = typography.min_headline_size(spec.artwork_height)
        hl_sized = bool(
            spec.headline and spec.headline.font_size >= min_hl and spec.headline.lines
        )
        checks["headline_min_size"] = hl_sized

        if spec.cta and spec.cta.text.strip():
            min_cta = typography.cta_min_size(spec.artwork_height)
            checks["cta_min_size"] = bool(spec.cta.font_size >= min_cta)
        else:
            checks["cta_min_size"] = True  # conditional

        # Contrast.
        checks["contrast_body"] = text_ratio >= contrast.BODY_RATIO
        checks["contrast_headline"] = text_ratio >= contrast.HEADLINE_RATIO
        accent_ratio = contrast.contrast_ratio(spec.palette.accent, spec.palette.background)
        checks["contrast_accent"] = accent_ratio >= contrast.ACCENT_RATIO
        if spec.cta and spec.cta.text.strip():
            on_accent = contrast.choose_text_on(spec.palette.accent)
            checks["cta_on_accent"] = (
                contrast.contrast_ratio(on_accent, spec.palette.accent)
                >= contrast.HEADLINE_RATIO
            )
        else:
            checks["cta_on_accent"] = True

        # Logo aspect preservation.
        checks["logo_aspect"] = self._check_logo_aspect(spec)

        # Information budget.
        checks["proof_count"] = len(spec.proofs) <= 2

        # No empty rendered text elements.
        empty_text = bool(
            (spec.headline and not spec.headline.text.strip())
            or any(not p.text.strip() for p in spec.proofs)
            or (spec.cta and not spec.cta.text.strip())
        )
        checks["no_empty_text"] = not empty_text

        # --- Visual-utility minimums (deterministic) -------------------------
        # Proof large enough to read (proofs are fitted at full size or omitted).
        proof_min = typography.proof_min_size(spec.artwork_height)
        checks["proof_min_size"] = all(p.font_size >= proof_min for p in spec.proofs)

        # Headline uses meaningful visual weight.
        checks["headline_visual_weight"] = bool(
            spec.headline
            and spec.headline.font_size
            >= HEADLINE_WEIGHT_FRAC * spec.artwork_height
        )

        # CTA minimum visual weight (band area) when a CTA exists.
        if spec.cta and spec.cta.text.strip():
            canvas_area = spec.artwork_width * spec.artwork_height
            cta_ratio = _rect_area(spec.cta.rect) / max(1, canvas_area)
            checks["cta_visual_weight"] = (
                cta_ratio >= CTA_WEIGHT_MIN and spec.cta.font_size >= typography.cta_min_size(spec.artwork_height)
            )
        else:
            checks["cta_visual_weight"] = True  # conditional

        # Logo must meaningfully fill its allotted field where prominence is required.
        fam = spec.composition_family
        if spec.logo and fam in (BRAND_DOMINANT, LOCAL_AUTHORITY):
            paste = spec.logo.paste_size
            x0, y0, x1, y1 = spec.logo.rect
            fw = max(1, x1 - x0)
            fh = max(1, y1 - y0)
            fill = max(paste[0] / fw, paste[1] / fh) if paste else 0.0
            checks["logo_visual_presence"] = fill >= LOGO_FILL_MIN
        else:
            checks["logo_visual_presence"] = True  # not enforced

        # --- Occupancy warning (soft, not a hard gate) -----------------------
        canvas_area = max(1, spec.artwork_width * spec.artwork_height)
        union = 0.0
        for r in present:
            union += _rect_area(r)
        occupancy = min(1.0, union / canvas_area)
        if occupancy < OCCUPANCY_WARN:
            warnings.append(f"low_content_occupancy={occupancy:.2f}")

        metrics = {
            "text_contrast": round(text_ratio, 3),
            "accent_contrast": round(accent_ratio, 3),
            "headline_font_size": float(spec.headline.font_size if spec.headline else 0),
            "proof_count": float(len(spec.proofs)),
            "cta_present": float(bool(spec.cta)),
            "content_occupancy": round(occupancy, 3),
        }

        passed = all(checks.values())
        score = round(100.0 * sum(1 for v in checks.values() if v) / max(1, len(checks)), 1)
        for name, ok in checks.items():
            if not ok:
                notes.append(name)

        return CreativeQualityResult(
            passed=passed, checks=checks, metrics=metrics, score=score,
            notes=notes, warnings=warnings,
        )

    def _check_logo_aspect(self, spec: CreativeLayoutSpec) -> bool:
        if spec.logo is None:
            return True  # no logo -> nothing to violate
        paste = spec.logo.paste_size
        if not paste or spec.logo.source_aspect <= 0:
            return True
        pw, ph = paste
        if ph <= 0 or pw <= 0:
            return False
        rendered_aspect = pw / ph
        # Allow a small adaptive slack for integer rounding of the paste size
        # (most visible on small logos where a 1px rounding is proportionally large).
        rounding = 2.0 / max(1, min(pw, ph))
        tolerance = max(LOGO_ASPECT_TOLERANCE * spec.logo.source_aspect, rounding)
        return abs(rendered_aspect - spec.logo.source_aspect) <= tolerance


def fits_with_headline(spec: CreativeLayoutSpec) -> bool:
    """Helper: whether the headline text actually fits its rect at its size."""
    if spec.headline is None or not spec.headline.lines:
        return False
    checker = CreativeQualityChecker()
    draw = checker._empty_draw(spec)
    font = checker._registry.resolve(spec.headline.font, spec.headline.font_size)
    x0, y0, x1, y1 = spec.headline.rect
    for line in spec.headline.lines:
        if draw.textlength(line, font=font) > (x1 - x0) + 1:
            return False
    line_height = typography.text_height(font)
    return line_height * len(spec.headline.lines) <= (y1 - y0) + 1
