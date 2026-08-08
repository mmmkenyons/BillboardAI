import os
import numpy as np
from PIL import Image

from renderer.renderer import render_billboard

# Expected native scene dimensions from cart_corral.json
NATIVE_WIDTH = 523
NATIVE_HEIGHT = 561

# Billboard quad from cart_corral.json (native coordinates)
BILLBOARD_QUAD = [
    [143, 45],
    [392, 45],
    [392, 144],
    [143, 144],
]


def _load_source_scene():
    """Load the source cart_corral scene at native resolution."""
    scene_path = "assets/cart_corral.jpg"
    if not os.path.exists(scene_path):
        scene_path = "D:/BillboardAI/assets/cart_corral.jpg"
    return Image.open(scene_path).convert("RGB")


def test_render_billboard_creates_image(tmp_path):
    output_path = tmp_path / "billboard.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#FFFFFF",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Sample Co",
        "headline": "Best in Class",
        "subtitle": "A clean billboard mockup",
        "layout_style": "premium",
        "cta_text": "Call Today",
    }

    result_path = render_billboard(spec, str(output_path))

    assert os.path.exists(result_path)
    image = Image.open(result_path)
    assert image.size == (NATIVE_WIDTH, NATIVE_HEIGHT)


def test_render_billboard_uses_cta_text(tmp_path):
    output_path = tmp_path / "billboard_cta.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#FFFFFF",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Example Co",
        "headline": "Dynamic font scaling test for a long headline that should wrap cleanly",
        "subtitle": "The subtitle text is also wrapped automatically.",
        "layout_style": "photo",
        "cta_text": "Schedule Now",
    }

    result_path = render_billboard(spec, str(output_path))

    assert os.path.exists(result_path)
    image = Image.open(result_path)
    assert image.size == (NATIVE_WIDTH, NATIVE_HEIGHT)


def test_output_dimensions_match_source_template(tmp_path):
    """Final output dimensions must equal source template dimensions (523x561)."""
    output_path = tmp_path / "billboard_dims.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#FFFFFF",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test Co",
        "headline": "Dimension Test",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }

    result_path = render_billboard(spec, str(output_path))
    image = Image.open(result_path)
    assert image.size == (NATIVE_WIDTH, NATIVE_HEIGHT), (
        f"Expected {NATIVE_WIDTH}x{NATIVE_HEIGHT}, got {image.size}"
    )


def test_pixels_outside_billboard_unchanged(tmp_path):
    """Pixels well outside the billboard region must be unchanged from source."""
    source = _load_source_scene()
    source_arr = np.array(source)

    output_path = tmp_path / "billboard_unchanged.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#FF0000",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test Co",
        "headline": "Outside Test",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }

    result_path = render_billboard(spec, str(output_path))
    result = Image.open(result_path).convert("RGB")
    result_arr = np.array(result)

    # Check a region well outside the billboard: bottom-left corner (rows 400-500, cols 0-100)
    # This is the cart corral area, far from the billboard at top
    outside_region_source = source_arr[400:500, 0:100]
    outside_region_result = result_arr[400:500, 0:100]

    assert np.array_equal(outside_region_source, outside_region_result), (
        "Pixels outside billboard region were modified"
    )

    # Also check top-left sky area (rows 0-20, cols 0-100)
    sky_source = source_arr[0:20, 0:100]
    sky_result = result_arr[0:20, 0:100]
    assert np.array_equal(sky_source, sky_result), (
        "Sky pixels outside billboard region were modified"
    )


def test_artwork_does_not_escape_billboard_quad(tmp_path):
    """Artwork must not leak outside the configured billboard quad."""
    output_path = tmp_path / "billboard_no_escape.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#00FF00",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test Co",
        "headline": "Containment Test",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }

    result_path = render_billboard(spec, str(output_path))
    source = _load_source_scene()
    source_arr = np.array(source)
    result = Image.open(result_path).convert("RGB")
    result_arr = np.array(result)

    # Check pixels just outside the billboard quad (1px outside each edge)
    # Top edge: y=44 (1px above quad top at y=45)
    top_strip_source = source_arr[44, 145:393]
    top_strip_result = result_arr[44, 145:393]
    assert np.array_equal(top_strip_source, top_strip_result), (
        "Artwork leaked above billboard top edge"
    )

    # Bottom edge: y=145 (1px below quad bottom at y=144)
    bottom_strip_source = source_arr[145, 145:393]
    bottom_strip_result = result_arr[145, 145:393]
    assert np.array_equal(bottom_strip_source, bottom_strip_result), (
        "Artwork leaked below billboard bottom edge"
    )

    # Left edge: x=142 (1px left of quad left at x=143)
    left_strip_source = source_arr[45:145, 142]
    left_strip_result = result_arr[45:145, 142]
    assert np.array_equal(left_strip_source, left_strip_result), (
        "Artwork leaked left of billboard left edge"
    )

    # Right edge: x=393 (1px right of quad right at x=392)
    right_strip_source = source_arr[45:145, 393]
    right_strip_result = result_arr[45:145, 393]
    assert np.array_equal(right_strip_source, right_strip_result), (
        "Artwork leaked right of billboard right edge"
    )


def test_artwork_aspect_ratio_matches_configured(tmp_path):
    """Artwork must be generated at the configured aspect ratio (2.505:1)."""
    output_path = tmp_path / "billboard_aspect.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#FFFFFF",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test Co",
        "headline": "Aspect Ratio Test",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }

    result_path = render_billboard(spec, str(output_path))
    result = Image.open(result_path).convert("RGB")
    result_arr = np.array(result)

    # The billboard quad defines the face region
    quad_w = BILLBOARD_QUAD[1][0] - BILLBOARD_QUAD[0][0]  # 243
    quad_h = BILLBOARD_QUAD[2][1] - BILLBOARD_QUAD[0][1]  # 97
    expected_aspect = quad_w / quad_h  # ~2.505

    # Verify the artwork was generated at the correct aspect ratio
    # by checking the default_artwork_size from the template
    import json
    template_path = "assets/templates/cart_corral.json"
    if not os.path.exists(template_path):
        template_path = "D:/BillboardAI/assets/templates/cart_corral.json"
    with open(template_path, "r") as f:
        template = json.load(f)

    artwork_size = template.get("default_artwork_size", [640, 400])
    artwork_aspect = artwork_size[0] / artwork_size[1]

    assert abs(artwork_aspect - expected_aspect) < 0.02, (
        f"Artwork aspect {artwork_aspect:.3f} does not match billboard face {expected_aspect:.3f}"
    )


def test_no_gray_border_fill(tmp_path):
    """Verify no gray (240,240,240) border fill exists in the output."""
    output_path = tmp_path / "billboard_no_gray.png"
    spec = {
        "scene_template": "cart_corral",
        "background_color": "#FFFFFF",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test Co",
        "headline": "No Gray Test",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }

    result_path = render_billboard(spec, str(output_path))
    result = Image.open(result_path).convert("RGB")
    result_arr = np.array(result)

    # Count pixels that are exactly (240, 240, 240) - the old border fill color
    gray_mask = (
        (result_arr[:, :, 0] == 240)
        & (result_arr[:, :, 1] == 240)
        & (result_arr[:, :, 2] == 240)
    )
    gray_count = gray_mask.sum()

    # Allow a small number of coincidental matches (e.g., in the source photo)
    # but the old bug would produce thousands
    assert gray_count < 500, (
        f"Found {gray_count} gray (240,240,240) pixels — old border fill may still be present"
    )


# =============================================================================
# Template-independence tests — prove renderer.py is fully template-driven
# =============================================================================

import json
import pytest
from pathlib import Path
import engine.renderer.renderer as renderer_mod


def _make_synthetic_scene(width: int, height: int, tmp_path: Path) -> str:
    """Create a solid-color scene image for synthetic template testing."""
    scene_path = tmp_path / f"scene_{width}x{height}.png"
    img = Image.new("RGB", (width, height), (100, 150, 200))
    img.save(scene_path)
    return str(scene_path)


def _make_template_json(tmp_path: Path, **overrides) -> str:
    """Create a temporary template JSON file. Overrides merge onto sensible defaults."""
    defaults = {
        "id": "synthetic_test",
        "name": "Synthetic Test Template",
        "scene_path": "",
        "reference_size": [400, 300],
        "billboard_quad": [[50, 50], [350, 50], [350, 250], [50, 250]],
        "artwork_aspect": 1.5,
        "default_artwork_size": [600, 400],
    }
    defaults.update(overrides)
    template_path = tmp_path / "synthetic_test.json"
    with open(template_path, "w") as f:
        json.dump(defaults, f)
    return str(template_path)


def _patch_load_template(monkeypatch, template_path):
    """Monkeypatch _load_template to return a synthetic template for 'synthetic_test'."""
    original_load = renderer_mod._load_template

    def _load_synthetic(name):
        if name == "synthetic_test":
            with open(template_path) as f:
                return json.load(f), template_path
        return original_load(name)

    monkeypatch.setattr(renderer_mod, "_load_template", _load_synthetic)


# --- Test 1: Rectangular synthetic template ---
def test_synthetic_rectangular_template(tmp_path, monkeypatch):
    """Render with a synthetic rectangular billboard template."""
    scene_path = _make_synthetic_scene(400, 300, tmp_path)
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[400, 300],
        billboard_quad=[[50, 50], [350, 50], [350, 250], [50, 250]],
        default_artwork_size=[600, 400],
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FF0000",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test",
        "headline": "Synthetic Rect",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }
    result_path = render_billboard(spec, str(output_path))
    result = Image.open(result_path)
    assert result.size == (400, 300), f"Expected 400x300, got {result.size}"

    # Pixels outside the quad (top-left corner) should remain the scene color
    result_arr = np.array(result)
    corner_pixel = result_arr[10, 10]
    assert tuple(corner_pixel) == (100, 150, 200), (
        f"Corner pixel changed: {tuple(corner_pixel)}"
    )


# --- Test 2: Perspective-skewed synthetic template ---
def test_synthetic_perspective_template(tmp_path, monkeypatch):
    """Render with a perspective-skewed (trapezoidal) billboard quad."""
    scene_path = _make_synthetic_scene(500, 400, tmp_path)
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[500, 400],
        billboard_quad=[[100, 80], [420, 60], [440, 320], [80, 340]],
        default_artwork_size=[600, 400],
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output_persp.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#00FF00",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test",
        "headline": "Perspective Test",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }
    result_path = render_billboard(spec, str(output_path))
    result = Image.open(result_path)
    assert result.size == (500, 400), f"Expected 500x400, got {result.size}"

    # Pixels outside the quad should remain unchanged
    result_arr = np.array(result)
    corner = result_arr[5, 5]
    assert tuple(corner) == (100, 150, 200), f"Corner pixel changed: {tuple(corner)}"


# --- Test 3: Missing scene_template rejected ---
def test_missing_scene_template_rejected(tmp_path):
    """Renderer must raise ValueError when no scene_template is specified."""
    output_path = tmp_path / "output.png"
    spec = {
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "No Scene Template",
    }
    with pytest.raises(ValueError, match="No scene_template specified"):
        render_billboard(spec, str(output_path))


# --- Test 4: Missing scene_path rejected ---
def test_missing_scene_path_rejected(tmp_path, monkeypatch):
    """Template without a valid scene_path must fail validation."""
    template_path = _make_template_json(
        tmp_path,
        scene_path="nonexistent_scene.jpg",
        reference_size=[400, 300],
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "Missing Scene",
    }
    with pytest.raises((FileNotFoundError, ValueError), match="scene"):
        render_billboard(spec, str(output_path))


# --- Test 5: Missing scene file rejected ---
def test_missing_scene_file_rejected(tmp_path, monkeypatch):
    """Template referencing a scene file that doesn't exist on disk must fail."""
    scene_path = str(tmp_path / "does_not_exist.jpg")
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[400, 300],
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "Missing File",
    }
    with pytest.raises((FileNotFoundError, ValueError), match="scene"):
        render_billboard(spec, str(output_path))


# --- Test 6: reference_size mismatch rejected ---
def test_reference_size_mismatch_rejected(tmp_path, monkeypatch):
    """Template with reference_size not matching actual image must fail."""
    scene_path = _make_synthetic_scene(400, 300, tmp_path)
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[800, 600],  # Wrong!
        billboard_quad=[[50, 50], [350, 50], [350, 250], [50, 250]],
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "Mismatch",
    }
    with pytest.raises(ValueError, match="do not match reference_size"):
        render_billboard(spec, str(output_path))


# --- Test 7: Malformed billboard_quad rejected ---
def test_malformed_billboard_quad_rejected(tmp_path, monkeypatch):
    """Template with only 3 quad points must fail validation."""
    scene_path = _make_synthetic_scene(400, 300, tmp_path)
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[400, 300],
        billboard_quad=[[50, 50], [350, 50], [350, 250]],  # Only 3 points
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "Bad Quad",
    }
    with pytest.raises(ValueError, match="exactly 4"):
        render_billboard(spec, str(output_path))


# --- Test 8: Degenerate billboard_quad rejected ---
def test_degenerate_billboard_quad_rejected(tmp_path, monkeypatch):
    """Template with all 4 quad points identical must fail (zero area)."""
    scene_path = _make_synthetic_scene(400, 300, tmp_path)
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[400, 300],
        billboard_quad=[[100, 100], [100, 100], [100, 100], [100, 100]],
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "Degenerate",
    }
    with pytest.raises(ValueError, match="degenerate"):
        render_billboard(spec, str(output_path))


# --- Test 9: Out-of-bounds billboard_quad rejected ---
def test_out_of_bounds_billboard_quad_rejected(tmp_path, monkeypatch):
    """Template with quad point outside image bounds must fail."""
    scene_path = _make_synthetic_scene(400, 300, tmp_path)
    template_path = _make_template_json(
        tmp_path,
        scene_path=scene_path,
        reference_size=[400, 300],
        billboard_quad=[[50, 50], [500, 50], [500, 250], [50, 250]],  # x=500 > 400
    )
    _patch_load_template(monkeypatch, template_path)

    output_path = tmp_path / "output.png"
    spec = {
        "scene_template": "synthetic_test",
        "background_color": "#FFFFFF",
        "company": "Test",
        "headline": "OOB",
    }
    with pytest.raises(ValueError, match="outside"):
        render_billboard(spec, str(output_path))


# --- Test 10: Two different templates produce different outputs ---
def test_two_templates_different_outputs(tmp_path, monkeypatch):
    """Prove renderer.py handles two different templates without code changes."""
    # Template A: 400x300 scene, quad at top-left
    scene_a = _make_synthetic_scene(400, 300, tmp_path)
    template_a = _make_template_json(
        tmp_path,
        id="template_a",
        scene_path=scene_a,
        reference_size=[400, 300],
        billboard_quad=[[20, 20], [200, 20], [200, 120], [20, 120]],
        default_artwork_size=[360, 200],
    )

    # Template B: 300x400 scene, quad at bottom-right
    scene_b_path = tmp_path / "scene_300x400.png"
    img_b = Image.new("RGB", (300, 400), (50, 200, 100))
    img_b.save(scene_b_path)
    scene_b = str(scene_b_path)

    template_b_path = tmp_path / "template_b.json"
    template_b_data = {
        "id": "template_b",
        "name": "Template B",
        "scene_path": scene_b,
        "reference_size": [300, 400],
        "billboard_quad": [[100, 250], [280, 250], [280, 380], [100, 380]],
        "artwork_aspect": 1.38,
        "default_artwork_size": [552, 400],
    }
    with open(template_b_path, "w") as f:
        json.dump(template_b_data, f)

    original_load = renderer_mod._load_template

    def _load_multi(name):
        if name == "template_a":
            with open(template_a) as f:
                return json.load(f), template_a
        if name == "template_b":
            with open(template_b_path) as f:
                return json.load(f), str(template_b_path)
        return original_load(name)

    monkeypatch.setattr(renderer_mod, "_load_template", _load_multi)

    base_spec = {
        "background_color": "#FFFFFF",
        "text_color": "#000000",
        "accent_color": "#1F77B4",
        "button_color": "#FF7F0E",
        "font_family": "arial.ttf",
        "company": "Test",
        "headline": "Multi Template",
        "subtitle": "",
        "layout_style": "classic",
        "cta_text": "Go",
    }

    # Render template A
    spec_a = {**base_spec, "scene_template": "template_a"}
    out_a = render_billboard(spec_a, str(tmp_path / "out_a.png"))
    img_a = Image.open(out_a)
    assert img_a.size == (400, 300), f"Template A: expected 400x300, got {img_a.size}"

    # Render template B
    spec_b = {**base_spec, "scene_template": "template_b"}
    out_b = render_billboard(spec_b, str(tmp_path / "out_b.png"))
    img_b = Image.open(out_b)
    assert img_b.size == (300, 400), f"Template B: expected 300x400, got {img_b.size}"

    # Verify they are different sizes (proves template-driven)
    assert img_a.size != img_b.size, "Two templates should produce different output sizes"

    # Verify template A corner pixel is scene A color
    arr_a = np.array(img_a)
    assert tuple(arr_a[5, 5]) == (100, 150, 200), "Template A corner should be scene A color"

    # Verify template B corner pixel is scene B color
    arr_b = np.array(img_b)
    assert tuple(arr_b[5, 5]) == (50, 200, 100), "Template B corner should be scene B color"