"""Sprint 2G: Creative Layout Engine + Artwork MVP tests."""
from __future__ import annotations

import os

import pytest
from PIL import Image

from engine.brand_profile import BrandAsset, BrandProfile
from engine.ad_concept import (
    AdConcept,
    BRAND_DOMINANT,
    MESSAGE_DOMINANT,
    LOCAL_AUTHORITY,
)
from engine.layout import (
    CreativeArtworkRenderer,
    CreativeLayoutEngine,
    CreativeLayoutSpec,
    CreativeQualityChecker,
    CreativeQualityResult,
    FontRegistry,
    LayoutText,
    contain_size,
    contrast_ratio,
    choose_text_on,
    fit_text,
    greedy_wrap,
    rects_overlap,
    relative_luminance,
    resolve_palette,
)
from engine.layout.typography import (
    CTA_BOLD,
    HEADLINE_BOLD,
    PROOF,
    headline_init,
    min_headline_size,
    proof_min_size,
)

ALL_FAMILIES = (BRAND_DOMINANT, MESSAGE_DOMINANT, LOCAL_AUTHORITY)
SIZES = [(752, 300), (552, 400)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(colors=None) -> BrandProfile:
    return BrandProfile(colors=list(colors or ["#1B2A4A", "#F4F4F4"]))


def _concept(
    family=BRAND_DOMINANT,
    headline="Financing Available",
    proofs=("Free Estimates",),
    cta="Call (605) 764-9517",
    logo_asset=None,
) -> AdConcept:
    return AdConcept(
        composition_family=family,
        headline=headline,
        supporting_proof=list(proofs),
        cta=cta,
        logo_asset=logo_asset,
    )


def _logo_asset(tmp_path, width=400, height=120):
    path = str(tmp_path / "logo.png")
    img = Image.new("RGBA", (width, height), (30, 70, 160, 255))
    img.save(path)
    return BrandAsset(
        path=path,
        source_url="https://example.com/logo.png",
        asset_type="logo",
        mime_type="image/png",
        format="PNG",
        width=width,
        height=height,
        aspect_ratio=round(width / height, 6),
        has_alpha=True,
        file_size=1024,
        confidence=0.9,
        quality_score=0.8,
    )


def _rect_area(rect) -> int:
    if rect is None:
        return 0
    x0, y0, x1, y1 = rect
    return max(0, x1 - x0) * max(0, y1 - y0)


# ---------------------------------------------------------------------------
# Models / serialization
# ---------------------------------------------------------------------------

def test_model_serialization_roundtrip():
    spec = CreativeLayoutSpec(
        artwork_width=752,
        artwork_height=300,
        composition_family=BRAND_DOMINANT,
        palette=resolve_palette(["#1B2A4A"]),
        headline=LayoutText(
            kind="headline", text="Financing Available", rect=(10, 10, 400, 80),
            alignment="center", font=HEADLINE_BOLD, font_size=40, max_lines=2,
            lines=("Financing", "Available"), line_height=48,
        ),
        proofs=(),
        cta=None,
        logo=None,
        geometry_valid=True,
    )
    restored = CreativeLayoutSpec.from_dict(spec.to_dict())
    assert restored == spec


def test_contain_size_preserves_aspect():
    assert contain_size(300, 100, 3.0) == (300, 100)
    w, h = contain_size(100, 200, 2.0)
    assert w == 100
    assert h == 50
    assert abs((w / h) - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# Palette / contrast
# ---------------------------------------------------------------------------

def test_contrast_black_on_light():
    assert choose_text_on("#FFFFFF") == "#111111"
    assert contrast_ratio("#111111", "#FFFFFF") >= 4.5


def test_contrast_white_on_dark():
    assert choose_text_on("#111111") == "#F4F4F4"
    assert contrast_ratio("#F4F4F4", "#000000") >= 4.5


def test_relative_luminance_known_values():
    assert relative_luminance("#000000") == 0.0
    assert relative_luminance("#FFFFFF") == 1.0
    assert relative_luminance("#111111") < 0.1


def test_weak_combination_rejected():
    # A mid-grey background forces a black/white pick with good contrast.
    p = resolve_palette(["#888888"])
    ratio = contrast_ratio(p.text, p.background)
    assert ratio >= 4.5
    assert p.text in ("#111111", "#F4F4F4")


def test_palette_prefers_brand_background_when_safe():
    # A strong brand color (navy) becomes the background when contrast supports it.
    p = resolve_palette(["#FFFFFF", "#1B2A4A"])
    assert p.background.upper() == "#1B2A4A"
    assert p.text.upper() == "#F4F4F4"
    assert contrast_ratio(p.text, p.background) >= 4.5
    assert contrast_ratio(p.accent, p.background) >= 3.0


def test_palette_light_brand_background():
    # A light brand color can also become the background with dark text.
    p = resolve_palette(["#DCE6F2"])
    assert p.text.upper() in ("#111111", "#F4F4F4")
    assert contrast_ratio(p.text, p.background) >= 4.5


def test_palette_guaranteed_safe_neutral():
    # Forces safe fallback when brand colors would be too low contrast.
    p = resolve_palette(["#AAAAAA", "#BBBBBB"])
    assert contrast_ratio(p.text, p.background) >= 4.5
    assert contrast_ratio(p.accent, p.background) >= 3.0

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------

def test_font_resolution_and_cache():
    reg = FontRegistry()
    f1 = reg.resolve(HEADLINE_BOLD, 40)
    f2 = reg.resolve(HEADLINE_BOLD, 40)
    assert f1 is f2  # cached
    assert reg.resolve(PROOF, 20) is not None
    assert reg.resolve(CTA_BOLD, 30) is not None


def test_headline_init_ordering():
    assert headline_init(MESSAGE_DOMINANT, 300) > headline_init(LOCAL_AUTHORITY, 300)
    assert headline_init(LOCAL_AUTHORITY, 300) > headline_init(BRAND_DOMINANT, 300)


def test_min_headline_size_floor():
    assert min_headline_size(20) >= 16


# ---------------------------------------------------------------------------
# Text fitting / wrapping
# ---------------------------------------------------------------------------

def test_greedy_wrap_keeps_words_intact():
    reg = FontRegistry()
    font = reg.resolve(HEADLINE_BOLD, 30)
    from PIL import ImageDraw, Image as _I
    draw = ImageDraw.Draw(_I.new("RGB", (752, 300)))
    lines = greedy_wrap("Financing Available", font, 120, draw)
    assert len(lines) > 1
    assert all(l.strip() for l in lines)


def test_headline_single_line_at_max():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(headline="Free Estimates"), _profile(), 752, 300)
    assert spec.geometry_valid
    assert len(spec.headline.lines) == 1
    assert spec.headline.font_size == headline_init(BRAND_DOMINANT, 300)


def test_headline_two_lines_capped():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(
        _concept(
            family=MESSAGE_DOMINANT,
            headline="Financing Available For Your New Roof Today",
        ),
        _profile(), 752, 300,
    )
    assert spec.geometry_valid
    assert len(spec.headline.lines) == 2


def test_headline_never_mutated():
    original = "Greater Sioux Falls"
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(family=LOCAL_AUTHORITY, headline=original), _profile(), 552, 400)
    assert spec.headline.text == original


def test_overflow_failure_geometry_invalid(tmp_path):
    eng = CreativeLayoutEngine()
    spec = eng.resolve(
        _concept(
            headline="An Extremely Long Headline That Simply Cannot Possibly Fit In This Tiny Space",
            proofs=("Free Estimates",),
        ),
        _profile(), 60, 50,
    )
    assert spec.geometry_valid is False
    result = CreativeQualityChecker().validate(spec)
    assert result.checks["headline_overflow"] is False  # overflow detected
    assert result.passed is False


def test_proof_drop_order_preserves_prefix():
    eng = CreativeLayoutEngine()
    concept = _concept(
        family=LOCAL_AUTHORITY,
        proofs=("First Proof", "Second Proof"),
    )
    spec = eng.resolve(concept, _profile(), 552, 400)
    texts = [p.text for p in spec.proofs]
    # Proofs keep their original order and are capped at 2.
    assert set(texts) <= {"First Proof", "Second Proof"}
    if len(texts) == 1:
        assert texts[0] == "First Proof"
    assert len(texts) <= 2


def test_cta_optional_not_fabricated():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(cta=""), _profile(), 752, 300)
    assert spec.cta is None
    result = CreativeQualityChecker().validate(spec)
    assert result.checks["cta_min_size"] is True


def test_cta_rendered_when_provided():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(cta="Call (605) 764-9517"), _profile(), 752, 300)
    assert spec.cta is not None
    assert spec.cta.text == "Call (605) 764-9517"


def test_cta_single_line():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(cta="Call (605) 764-9517"), _profile(), 552, 400)
    assert spec.cta is not None
    assert len(spec.cta.lines) == 1

# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

def test_logo_aspect_preserved(tmp_path):
    asset = _logo_asset(tmp_path, 400, 120)
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(logo_asset=asset), _profile(), 752, 300)
    assert spec.logo is not None
    pw, ph = spec.logo.paste_size
    rendered_aspect = pw / ph
    assert abs(rendered_aspect - asset.aspect_ratio) <= 0.02 * asset.aspect_ratio
    assert CreativeQualityChecker().validate(spec).checks["logo_aspect"] is True


def test_missing_logo_omitted_gracefully(tmp_path):
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(logo_asset=None), _profile(), 752, 300)
    assert spec.logo is None
    assert spec.geometry_valid
    img = CreativeArtworkRenderer().render(spec)
    assert img.size == (752, 300)


def test_logo_renders_contained(tmp_path):
    asset = _logo_asset(tmp_path, 400, 120)
    eng = CreativeLayoutEngine()
    spec = eng.resolve(
        _concept(family=BRAND_DOMINANT, logo_asset=asset), _profile(), 752, 300
    )
    img = CreativeArtworkRenderer().render(spec)
    assert img.size == (752, 300)


# ---------------------------------------------------------------------------
# Bounds / overlap / quality
# ---------------------------------------------------------------------------

def test_element_bounds_within_canvas():
    eng = CreativeLayoutEngine()
    checker = CreativeQualityChecker()
    for fam in ALL_FAMILIES:
        for w, h in SIZES:
            spec = eng.resolve(_concept(family=fam), _profile(), w, h)
            res = checker.validate(spec)
            assert res.checks["all_within_canvas"] is True, (fam, w, h)
            assert res.checks["bounds_non_degenerate"] is True


def test_overlap_validation_flags_bad_spec(tmp_path):
    asset = _logo_asset(tmp_path)
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(logo_asset=asset), _profile(), 752, 300)
    # Force an overlap by reusing the logo rect for the headline.
    bad = CreativeLayoutSpec(
        artwork_width=752, artwork_height=300, composition_family=BRAND_DOMINANT,
        palette=spec.palette, headline=spec.headline, proofs=(), cta=spec.cta,
        logo=spec.logo, geometry_valid=False,
    )
    # Override the headline rect to collide with the logo rect.
    colliding = CreativeLayoutSpec.from_dict(bad.to_dict())
    colliding = CreativeLayoutSpec(
        artwork_width=752, artwork_height=300, composition_family=BRAND_DOMINANT,
        palette=colliding.palette,
        headline=LayoutText(
            kind="headline", text=colliding.headline.text,
            rect=colliding.logo.rect, alignment="center",
            font=colliding.headline.font, font_size=colliding.headline.font_size,
            max_lines=2, lines=colliding.headline.lines,
            line_height=colliding.headline.line_height,
        ),
        proofs=(), cta=colliding.cta, logo=colliding.logo, geometry_valid=False,
    )
    res = CreativeQualityChecker().validate(colliding)
    assert res.checks["no_overlap"] is False
    assert rects_overlap(colliding.headline.rect, colliding.logo.rect) is True


def test_quality_result_valid():
    eng = CreativeLayoutEngine()
    checker = CreativeQualityChecker()
    for fam in ALL_FAMILIES:
        for w, h in SIZES:
            spec = eng.resolve(_concept(family=fam), _profile(), w, h)
            res = checker.validate(spec)
            assert res.passed is True, (fam, w, h, res.notes)
            assert isinstance(res.score, float) and res.score >= 99.0
            assert res.checks["headline_min_size"] is True
            assert res.checks["no_empty_text"] is True
            assert res.checks["text_fits"] is True
            assert res.checks["no_clipping"] is True


# ---------------------------------------------------------------------------
# Families / sizes / determinism
# ---------------------------------------------------------------------------

def test_three_families_resolve_and_render(tmp_path):
    asset = _logo_asset(tmp_path)
    eng = CreativeLayoutEngine()
    renderer = CreativeArtworkRenderer()
    for fam in ALL_FAMILIES:
        for w, h in SIZES:
            spec = eng.resolve(_concept(family=fam, logo_asset=asset), _profile(), w, h)
            assert spec.geometry_valid is True, (fam, w, h)
            assert spec.composition_family == fam
            img = renderer.render(spec)
            assert img.size == (w, h)


def test_family_structural_differentiation(tmp_path):
    asset = _logo_asset(tmp_path)
    eng = CreativeLayoutEngine()
    fonts = {}
    logo_areas = {}
    for fam in ALL_FAMILIES:
        spec = eng.resolve(
            _concept(family=fam, headline="Headline", logo_asset=asset), _profile(), 752, 300
        )
        fonts[fam] = spec.headline.font_size
        logo_areas[fam] = _rect_area(spec.logo.rect) if spec.logo else 0
    # MESSAGE_DOMINANT = biggest headline; LOCAL > BRAND.
    assert fonts[MESSAGE_DOMINANT] > fonts[LOCAL_AUTHORITY]
    assert fonts[LOCAL_AUTHORITY] > fonts[BRAND_DOMINANT]
    # BRAND_DOMINANT gives the logo major territory vs MESSAGE's tiny corner mark.
    assert logo_areas[BRAND_DOMINANT] > logo_areas[MESSAGE_DOMINANT]


def test_both_artwork_sizes():
    eng = CreativeLayoutEngine()
    for w, h in SIZES:
        spec = eng.resolve(_concept(), _profile(), w, h)
        assert (spec.artwork_width, spec.artwork_height) == (w, h)
        assert CreativeQualityChecker().validate(spec).passed is True


def test_deterministic_spec():
    eng = CreativeLayoutEngine()
    a = eng.resolve(_concept(), _profile(), 752, 300)
    b = eng.resolve(_concept(), _profile(), 752, 300)
    assert a.to_dict() == b.to_dict()


def test_deterministic_pixel_output(tmp_path):
    eng = CreativeLayoutEngine()
    asset = _logo_asset(tmp_path)
    renderer = CreativeArtworkRenderer()
    spec = eng.resolve(_concept(logo_asset=asset), _profile(), 552, 400)
    img1 = renderer.render(spec)
    img2 = renderer.render(spec)
    assert img1.tobytes() == img2.tobytes()


# ---------------------------------------------------------------------------
# Visual-utility minimums (Sprint 2G visual gate)
# ---------------------------------------------------------------------------

def test_proof_rendered_at_full_readable_size():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(), _profile(), 752, 300)
    assert spec.geometry_valid
    for proof in spec.proofs:
        assert proof.font_size >= proof_min_size(300)


def test_proof_omitted_when_cannot_render_large_enough():
    # A proof too long to fit one line at full size must be omitted, not shrunk.
    eng = CreativeLayoutEngine()
    spec = eng.resolve(
        _concept(
            family=MESSAGE_DOMINANT,
            proofs=("An Extremely Long Proof Statement That Absolutely Cannot Fit Anywhere",),
        ),
        _profile(), 552, 400,
    )
    assert spec.geometry_valid
    assert len(spec.proofs) == 0


def test_portrait_prefers_one_strong_proof_by_dropping_second():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(
        _concept(family=LOCAL_AUTHORITY, proofs=("First", "Second")),
        _profile(), 552, 400,
    )
    assert spec.geometry_valid
    assert len(spec.proofs) <= 2
    if spec.proofs:
        assert spec.proofs[0].text == "First"


def test_cta_rendered_as_full_width_band():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(), _profile(), 752, 300)
    assert spec.cta is not None
    # Band spans the content width (near full canvas), not a small centered pill.
    x0, y0, x1, y1 = spec.cta.rect
    assert (x1 - x0) > 0.8 * spec.artwork_width
    res = CreativeQualityChecker().validate(spec)
    assert res.checks["cta_visual_weight"] is True


def test_headline_visual_weight_passes():
    eng = CreativeLayoutEngine()
    for fam in ALL_FAMILIES:
        spec = eng.resolve(_concept(family=fam), _profile(), 752, 300)
        res = CreativeQualityChecker().validate(spec)
        assert res.checks["headline_visual_weight"] is True, fam


def test_logo_visual_presence_when_required(tmp_path):
    asset = _logo_asset(tmp_path)
    eng = CreativeLayoutEngine()
    for fam in (BRAND_DOMINANT, LOCAL_AUTHORITY):
        spec = eng.resolve(_concept(family=fam, logo_asset=asset), _profile(), 752, 300)
        res = CreativeQualityChecker().validate(spec)
        assert res.checks["logo_visual_presence"] is True, fam


def test_occupancy_warning_on_dead_space():
    eng = CreativeLayoutEngine()
    spec = eng.resolve(_concept(), _profile(), 752, 300)
    res = CreativeQualityChecker().validate(spec)
    # A full/filled composition should not warn about dead space.
    assert "content_occupancy" in res.metrics
    assert res.metrics["content_occupancy"] > 0.2


def test_quality_score_penalizes_visual_underuse():
    # A spec with a headline far below the visual-weight minimum scores < 100.
    eng = CreativeLayoutEngine()
    base = eng.resolve(_concept(), _profile(), 752, 300)
    weak = CreativeLayoutSpec(
        artwork_width=752, artwork_height=300, composition_family=BRAND_DOMINANT,
        palette=base.palette,
        headline=LayoutText(
            kind="headline", text=base.headline.text, rect=base.headline.rect,
            alignment="center", font=base.headline.font,
            font_size=int(0.07 * 300), max_lines=2, lines=base.headline.lines,
            line_height=base.headline.line_height,
        ),
        proofs=base.proofs, cta=base.cta,
        logo=base.logo if base.logo else None,
        field_rect=base.field_rect,
    )
    res = CreativeQualityChecker().validate(weak)
    assert res.checks["headline_min_size"] is True
    assert res.checks["headline_visual_weight"] is False
    assert res.score < 100.0
