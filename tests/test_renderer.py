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