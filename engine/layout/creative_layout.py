"""CreativeLayoutEngine: turn AdConcept + BrandProfile + artwork dims into a spec.

This is the ONLY place that translates AdConcept decisions (which elements,
hierarchy, assets) and a brand palette into a resolved rectangular pixel contract
(CreativeLayoutSpec). It is deterministic, never rewrites headline content, and
never reads physical-scene geometry.

Headline handling (per Sprint 2G):
  1 line -> 2 lines -> reduce font size to minimum -> drop proof #2 -> drop
  proof #1 -> reconsider optional logo (family-where-allowed) -> headline_overflow.

Proof handling (visual gate): proofs are fitted at their FULL readable size. A
proof that cannot be rendered large enough to read is OMITTED (never shrunk into
fine print).
"""
from __future__ import annotations

import os
from dataclasses import replace
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from engine.ad_concept import (
    BRAND_DOMINANT,
    LOCAL_AUTHORITY,
    MESSAGE_DOMINANT,
    _logo_usable,
)
from engine.brand_profile import BrandAsset, BrandProfile
from engine.ad_concept import AdConcept
from engine.layout import contrast, families, text_fit, typography
from engine.layout.model import (
    CreativeLayoutSpec,
    LayoutLogo,
    LayoutPalette,
    LayoutText,
    contain_size,
)
from engine.layout.quality import CreativeQualityChecker

SUPPORTED_FAMILIES = (BRAND_DOMINANT, MESSAGE_DOMINANT, LOCAL_AUTHORITY)
MAX_PROOFS = 2

_CLEAR_SPACE_FRACTION = 0.08


class CreativeLayoutEngine:
    """Resolves a CreativeLayoutSpec from an AdConcept for a requested artwork size."""

    def __init__(self, registry: "Optional[typography.FontRegistry]" = None) -> None:
        self._registry = registry or typography.FontRegistry()
        self._checker = CreativeQualityChecker(self._registry)

    def resolve(
        self,
        concept: AdConcept,
        profile: BrandProfile,
        width: int,
        height: int,
    ) -> CreativeLayoutSpec:
        """Return a resolved spec at (width, height).

        Raises ValueError for unsupported families or invalid dimensions.
        """
        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            raise ValueError("Artwork dimensions must be positive.")
        if concept is None:
            raise ValueError("A concept is required to resolve a layout.")
        family = concept.composition_family or ""
        if family not in SUPPORTED_FAMILIES:
            raise ValueError(
                f"Composition family '{family}' is not implemented in the MVP "
                f"(implemented: {', '.join(SUPPORTED_FAMILIES)})."
            )

        colors = profile.colors if profile is not None else []
        palette = contrast.resolve_palette(colors)

        logo_asset = self._usable_logo(concept)
        headline_text = (concept.headline or "").strip()
        proofs = [p.strip() for p in (concept.supporting_proof or []) if p.strip()][:MAX_PROOFS]
        cta_text = (concept.cta or "").strip()
        has_cta = bool(cta_text)

        draw = ImageDraw.Draw(Image.new("RGB", (width, height)))

        # Drop order: keep as much as possible first; proofs fall back last-to-first.
        proof_counts = list(range(len(proofs), -1, -1))
        # Logo is essential for BRAND_DOMINANT / LOCAL_AUTHORITY; optional for MESSAGE.
        logo_modes: List[Tuple[bool, bool]] = [(True, True)]
        if family == MESSAGE_DOMINANT:
            logo_modes = [(True, True), (True, False)]

        for n_proofs in proof_counts:
            for use_logo, _ in logo_modes:
                spec = self._compose(
                    concept=concept,
                    family=family,
                    palette=palette,
                    width=width,
                    height=height,
                    headline_text=headline_text,
                    proofs=proofs,
                    n_proofs=n_proofs,
                    cta_text=cta_text,
                    has_cta=has_cta,
                    logo_asset=logo_asset if use_logo else None,
                    draw=draw,
                )
                if spec is not None:
                    return spec

        # All attempts overflowed: return a failing spec with headline present.
        return self._overflow_spec(width, height, family, palette, headline_text, has_cta)

    # ------------------------------------------------------------------

    def _usable_logo(self, concept: AdConcept) -> Optional[BrandAsset]:
        asset = concept.logo_asset
        if asset is None or not _logo_usable(asset):
            return None
        if not asset.path or not os.path.exists(asset.path):
            return None
        return asset

    @staticmethod
    def _logo_paste_size(asset: BrandAsset, rect):
        x0, y0, x1, y1 = rect
        rw = (x1 - x0)
        rh = (y1 - y0)
        clear = max(2, round(min(rw, rh) * _CLEAR_SPACE_FRACTION))
        avail_w = max(1, rw - 2 * clear)
        avail_h = max(1, rh - 2 * clear)
        aspect = asset.aspect_ratio
        if not aspect or aspect <= 0:
            aspect = (asset.width / asset.height) if asset.height else 1.0
        return contain_size(avail_w, avail_h, float(aspect))

    def _compose(
        self,
        concept: AdConcept,
        family: str,
        palette: LayoutPalette,
        width: int,
        height: int,
        headline_text: str,
        proofs: List[str],
        n_proofs: int,
        cta_text: str,
        has_cta: bool,
        logo_asset: Optional[BrandAsset],
        draw: ImageDraw.ImageDraw,
    ) -> Optional[CreativeLayoutSpec]:
        has_logo = logo_asset is not None
        n_proofs = min(n_proofs, len(proofs), MAX_PROOFS)
        slots = families.build_slots(family, width, height, has_logo, n_proofs, has_cta)

        # Headline (never mutated; max 2 lines; hard minimum size).
        hl_max = typography.headline_init(family, height)
        hl_min = typography.min_headline_size(height)
        hl_fit = text_fit.fit_text(
            headline_text, typography.HEADLINE_BOLD, self._registry,
            slots.headline_rect, hl_max, hl_min, 2, draw,
        )
        if hl_fit is None:
            return None  # headline overflow
        headline = LayoutText(
            kind="headline", text=headline_text, rect=slots.headline_rect,
            alignment="center", font=typography.HEADLINE_BOLD,
            font_size=hl_fit.font_size, max_lines=2,
            lines=hl_fit.lines, line_height=hl_fit.line_height,
        )

        # Proofs: fit at FULL readable size; a proof that cannot fit is omitted.
        proof_items: List[LayoutText] = []
        p_size = typography.proof_size(height)
        for i, ptext in enumerate(proofs[:n_proofs]):
            pf = text_fit.fit_text(
                ptext, typography.PROOF, self._registry, slots.proof_rects[i],
                p_size, p_size, 1, draw,
            )
            if pf is None:
                continue
            proof_items.append(
                LayoutText(
                    kind="proof", text=ptext, rect=slots.proof_rects[i],
                    alignment="center", font=typography.PROOF,
                    font_size=pf.font_size, max_lines=1,
                    lines=pf.lines, line_height=pf.line_height,
                )
            )

        # CTA: conditional - rendered only when the AdConcept supplied one.
        cta = None
        cta_rect = slots.cta_rect
        if has_cta and cta_rect is not None:
            c_size = typography.cta_size(height)
            c_min = typography.cta_min_size(height)
            cf = text_fit.fit_text(
                cta_text, typography.CTA_BOLD, self._registry, cta_rect,
                c_size, c_min, 1, draw,
            )
            if cf is not None:
                cta = LayoutText(
                    kind="cta", text=cta_text, rect=cta_rect,
                    alignment="center", font=typography.CTA_BOLD,
                    font_size=cf.font_size, max_lines=1,
                    lines=cf.lines, line_height=cf.line_height,
                )

        # Logo (aspect-preserving contain; no crop, no stretch).
        logo = None
        if has_logo and slots.logo_rect is not None:
            paste = self._logo_paste_size(logo_asset, slots.logo_rect)
            logo = LayoutLogo(
                path=logo_asset.path, rect=slots.logo_rect,
                source_aspect=float(logo_asset.aspect_ratio or 1.0),
                alignment="center", paste_size=paste,
            )

        spec = CreativeLayoutSpec(
            artwork_width=width, artwork_height=height, composition_family=family,
            palette=palette, headline=headline, proofs=tuple(proof_items),
            cta=cta, logo=logo, field_rect=slots.field_rect, geometry_valid=True,
        )
        result = self._checker.validate(spec)
        return replace(spec, geometry_valid=result.passed)

    def _overflow_spec(
        self,
        width: int,
        height: int,
        family: str,
        palette: LayoutPalette,
        headline_text: str,
        has_cta: bool,
    ) -> CreativeLayoutSpec:
        headline = LayoutText(
            kind="headline", text=headline_text, rect=(0, 0, 0, 0),
            alignment="center", font=typography.HEADLINE_BOLD,
            font_size=0, max_lines=2, lines=(), line_height=0,
        )
        return CreativeLayoutSpec(
            artwork_width=width, artwork_height=height, composition_family=family,
            palette=palette, headline=headline, proofs=(), cta=None, logo=None,
            field_rect=None, geometry_valid=False,
        )
