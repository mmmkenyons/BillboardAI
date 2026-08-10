"""Sprint 2H integration tests: Creative Layout -> artwork -> physical mockup.

Covers the full test matrix from the sprint (items 1-18):
    - 3 composition families x 2 physical templates (6 combos)
    - output dimensions match physical scene
    - outside-quad pixels preserved
    - artwork visibly changes inside quad
    - correct artwork target dimensions used / no aspect distortion
    - clear failures: missing scene_template, missing physical template,
      invalid artwork
    - no mutation of BrandProfile / AdConcept
    - deterministic output for identical inputs
    - no physical-template names hardcoded in integration logic

The suite uses the checked-in physical templates (assets/templates/*.json) and
synthetic fixtures; it never depends on the Jim Woods website.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
import cv2
from PIL import Image, ImageDraw

import engine.mockup as mockup
import engine.renderer.renderer as renderer_mod
from engine.ad_concept import (
    AdConcept,
    BRAND_DOMINANT,
    LOCAL_AUTHORITY,
    MESSAGE_DOMINANT,
)
from engine.brand_profile import BrandProfile

FAMILIES = (BRAND_DOMINANT, MESSAGE_DOMINANT, LOCAL_AUTHORITY)
SCENE_TEMPLATES = ("cart_corral", "cart_nose")

# From the checked-in templates.
EXPECTED_ARTWORK_SIZE = {
    "cart_corral": (752, 300),
    "cart_nose": (552, 400),
}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _profile() -> BrandProfile:
    return BrandProfile(
        company_name="Jim Woods Roofing",
        colors=["#1B2A4A", "#F4F4F4"],
        services=["Roofing"],
        differentiators=["Financing Available", "Free Estimates"],
        guarantees=["Manufacturer Warranty"],
        trust_signals=["27 Years in Business"],
    )


def _concept(family: str) -> AdConcept:
    return AdConcept(
        composition_family=family,
        headline="Financing Available",
        supporting_proof=["Free Estimates"],
        cta="Call (605) 764-9517",
    )


def _load_scene(template_name: str) -> Image.Image:
    template = renderer_mod.load_physical_template(template_name)
    return Image.open(template["scene_path"]).convert("RGB")


def _quad(template_name: str) -> list:
    return renderer_mod.load_physical_template(template_name)["billboard_quad"]


def _inside_quad_mask(template_name: str, scene_size) -> np.ndarray:
    """Boolean mask of pixels strictly inside the billboard quad."""
    quad = _quad(template_name)
    mask = Image.new("L", scene_size, 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in quad], fill=255)
    return np.array(mask) > 0


def _outside_quad_mask(template_name: str, scene_size) -> np.ndarray:
    """Boolean mask of pixels strictly outside the quad AND its anti-aliasing halo.

    The perspective warp (lanczos) can bleed ~2px past the mask edge, which the
    sprint explicitly permits ("expected anti-aliasing at the mask boundary").
    Dilating the inside mask by a margin excludes that halo so we assert only
    that genuinely-untouched outside pixels are preserved.
    """
    inside = _inside_quad_mask(template_name, scene_size)
    kernel = np.ones((9, 9), np.uint8)
    dilated = cv2.dilate(inside.astype(np.uint8), kernel).astype(bool)
    return ~dilated


# ---------------------------------------------------------------------------
# 1-11. 6 combos + scene-preservation + artwork dimensions + aspect
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_concept_mockup_combos(tmp_path, family, scene_template):
    """Each family x template renders a valid mockup at scene dimensions."""
    output = tmp_path / f"{family}_{scene_template}.png"
    result = mockup.render_concept_mockup(
        _concept(family), _profile(), scene_template, str(output)
    )
    assert os.path.exists(result)
    img = Image.open(result)
    expected = _load_scene(scene_template).size
    assert img.size == expected, f"{scene_template}: expected {expected}, got {img.size}"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_outside_quad_preserved(tmp_path, family, scene_template):
    """Pixels outside the quad (minus anti-aliasing margin) are unchanged."""
    source = _load_scene(scene_template)
    source_arr = np.array(source)
    output = tmp_path / f"{family}_{scene_template}.png"
    mockup.render_concept_mockup(
        _concept(family), _profile(), scene_template, str(output)
    )
    result_arr = np.array(Image.open(output).convert("RGB"))
    outside = _outside_quad_mask(scene_template, source.size)
    diff = np.abs(result_arr.astype(int) - source_arr.astype(int))
    changed = (diff.sum(axis=2) > 0) & outside
    assert changed.sum() == 0, (
        f"{scene_template}/{family}: {changed.sum()} outside-quad pixels changed"
    )


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_artwork_changes_inside_quad(tmp_path, family, scene_template):
    """The artwork replacement visibly changes pixels inside the quad."""
    source = _load_scene(scene_template)
    source_arr = np.array(source)
    output = tmp_path / f"{family}_{scene_template}.png"
    mockup.render_concept_mockup(
        _concept(family), _profile(), scene_template, str(output)
    )
    result_arr = np.array(Image.open(output).convert("RGB"))
    inside = _inside_quad_mask(scene_template, source.size)
    diff = np.abs(result_arr.astype(int) - source_arr.astype(int)).sum(axis=2)
    changed = (diff > 0) & inside
    assert changed.sum() > 0, f"{scene_template}/{family}: nothing changed inside quad"
@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_artwork_target_dimensions_used(tmp_path, scene_template):
    """The resolved spec uses the template's intended artwork dimensions (no stretch)."""
    spec = mockup.resolve_concept_spec(_concept(BRAND_DOMINANT), _profile(), scene_template)
    expected = EXPECTED_ARTWORK_SIZE[scene_template]
    assert (spec.artwork_width, spec.artwork_height) == expected, (
        f"{scene_template}: expected {expected}, got "
        f"{(spec.artwork_width, spec.artwork_height)}"
    )


@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_no_aspect_distortion(tmp_path, scene_template):
    """Artwork is rendered at the intended aspect; not squeezed into a different ratio."""
    spec = mockup.resolve_concept_spec(_concept(BRAND_DOMINANT), _profile(), scene_template)
    template = renderer_mod.load_physical_template(scene_template)
    intended = tuple(int(v) for v in template["default_artwork_size"])
    assert (spec.artwork_width, spec.artwork_height) == intended
    assert abs(
        (spec.artwork_width / spec.artwork_height) - (intended[0] / intended[1])
    ) < 1e-6


# ---------------------------------------------------------------------------
# 12-14. Clear failures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_missing_scene_template_fails_clearly(tmp_path, scene_template):
    """A missing/empty scene_template must raise a clear error."""
    with pytest.raises(ValueError, match="scene_template"):
        mockup.render_concept_mockup(
            _concept(BRAND_DOMINANT), _profile(), "", str(tmp_path / "x.png")
        )


def test_missing_physical_template_fails_clearly(tmp_path):
    """An unknown physical template must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Template not found"):
        mockup.render_concept_mockup(
            _concept(BRAND_DOMINANT), _profile(), "does_not_exist", str(tmp_path / "x.png")
        )


def test_invalid_artwork_fails_clearly(tmp_path):
    """An unsupported composition family must raise a clear ValueError."""
    bad = AdConcept(composition_family="NOT_A_FAMILY", headline="x")
    with pytest.raises(ValueError, match="not implemented"):
        mockup.render_concept_mockup(bad, _profile(), "cart_corral", str(tmp_path / "x.png"))


def test_none_concept_fails_clearly(tmp_path):
    """A missing concept must raise a clear ValueError."""
    with pytest.raises(ValueError, match="concept is required"):
        mockup.render_concept_mockup(None, _profile(), "cart_corral", str(tmp_path / "x.png"))
# ---------------------------------------------------------------------------
# 15-16. No mutation of inputs
# ---------------------------------------------------------------------------

def _snapshot(obj):
    return obj.to_dict()


@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_does_not_mutate_profile_or_concept(tmp_path, scene_template):
    import copy

    profile = _profile()
    concept = _concept(LOCAL_AUTHORITY)
    profile_before = copy.deepcopy(_snapshot(profile))
    concept_before = copy.deepcopy(_snapshot(concept))

    mockup.render_concept_mockup(
        concept, profile, scene_template, str(tmp_path / "x.png")
    )

    assert _snapshot(profile) == profile_before, "BrandProfile was mutated"
    assert _snapshot(concept) == concept_before, "AdConcept was mutated"


# ---------------------------------------------------------------------------
# 17. Deterministic output
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scene_template", SCENE_TEMPLATES)
def test_deterministic_output(tmp_path, scene_template):
    """Identical inputs produce byte-identical mockups."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    mockup.render_concept_mockup(
        _concept(MESSAGE_DOMINANT), _profile(), scene_template, str(a)
    )
    mockup.render_concept_mockup(
        _concept(MESSAGE_DOMINANT), _profile(), scene_template, str(b)
    )
    assert np.array_equal(np.array(Image.open(a)), np.array(Image.open(b)))
# ---------------------------------------------------------------------------
# 18. No physical-template names hardcoded in integration logic
# ---------------------------------------------------------------------------

def test_no_template_names_hardcoded_in_mockup_logic():
    """mockup.py must not hardcode cart_corral / cart_nose / Kroger / carts."""
    src_path = Path(mockup.__file__)
    source = src_path.read_text(encoding="utf-8")
    for forbidden in ("cart_corral", "cart_nose", "Kroger", "grocery cart"):
        assert forbidden not in source, f"mockup.py hardcodes '{forbidden}'"


def test_synthetic_template_works_through_mockup(tmp_path, monkeypatch):
    """A synthetic template (arbitrary name) renders through the same path — proving
    the integration layer is generic and template-name independent."""
    scene = tmp_path / "scene.png"
    Image.new("RGB", (400, 300), (100, 150, 200)).save(scene)

    template_path = tmp_path / "synthetic_template.json"
    template_data = {
        "id": "synthetic_template",
        "name": "Synthetic",
        "scene_path": str(scene),
        "reference_size": [400, 300],
        "billboard_quad": [[50, 50], [350, 50], [350, 250], [50, 250]],
        "artwork_aspect": 1.5,
        "default_artwork_size": [600, 400],
    }
    with open(template_path, "w") as f:
        json.dump(template_data, f)

    original_load = renderer_mod._load_template

    def _load_synthetic(name):
        if name == "synthetic_template":
            with open(template_path) as f:
                return json.load(f), str(template_path)
        return original_load(name)

    monkeypatch.setattr(renderer_mod, "_load_template", _load_synthetic)

    output = tmp_path / "out.png"
    mockup.render_concept_mockup(
        _concept(BRAND_DOMINANT), _profile(), "synthetic_template", str(output)
    )
    img = Image.open(output)
    assert img.size == (400, 300)
    # Spec resolves at the synthetic template's intended artwork size.
    spec = mockup.resolve_concept_spec(
        _concept(BRAND_DOMINANT), _profile(), "synthetic_template"
    )
    assert (spec.artwork_width, spec.artwork_height) == (600, 400)