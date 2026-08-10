"""BillboardAI Creative Layout layer (Sprint 2G).

Pipeline:
    AdConcept -> CreativeLayoutEngine -> CreativeLayoutSpec
             -> CreativeArtworkRenderer -> rectangular PIL artwork

The layer knows nothing about physical scenes (cart_corral / cart_nose) or
perspective transforms. It outputs a clean rectangular advertisement.
"""
from engine.layout.model import (
    CreativeLayoutSpec,
    LayoutLogo,
    LayoutPalette,
    LayoutText,
    contain_size,
    rect_overlap_area,
    rects_overlap,
)
from engine.layout.contrast import (
    contrast_ratio,
    is_dark,
    relative_luminance,
    resolve_palette,
    choose_text_on,
)
from engine.layout.typography import (
    HEADLINE_BOLD,
    PROOF,
    CTA_BOLD,
    FontRegistry,
    text_height,
    headline_init,
    min_headline_size,
    proof_size,
    cta_size,
)
from engine.layout.text_fit import fit_text, greedy_wrap
from engine.layout.families import Slots, build_slots
from engine.layout.creative_layout import CreativeLayoutEngine, SUPPORTED_FAMILIES
from engine.layout.quality import CreativeQualityChecker, CreativeQualityResult
from engine.layout.artwork_renderer import CreativeArtworkRenderer

__all__ = [
    "CreativeLayoutSpec",
    "LayoutLogo",
    "LayoutPalette",
    "LayoutText",
    "contain_size",
    "rect_overlap_area",
    "rects_overlap",
    "contrast_ratio",
    "is_dark",
    "relative_luminance",
    "resolve_palette",
    "choose_text_on",
    "HEADLINE_BOLD",
    "PROOF",
    "CTA_BOLD",
    "FontRegistry",
    "text_height",
    "headline_init",
    "min_headline_size",
    "proof_size",
    "cta_size",
    "fit_text",
    "greedy_wrap",
    "Slots",
    "build_slots",
    "CreativeLayoutEngine",
    "SUPPORTED_FAMILIES",
    "CreativeQualityChecker",
    "CreativeQualityResult",
    "CreativeArtworkRenderer",
]
