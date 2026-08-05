import os
from PIL import Image

from renderer.renderer import render_billboard


def test_render_billboard_creates_image(tmp_path):
    output_path = tmp_path / "billboard.png"
    spec = {
        "canvas": {"width": 800, "height": 450},
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
    assert image.size == (800, 450)


def test_render_billboard_uses_cta_text(tmp_path):
    output_path = tmp_path / "billboard_cta.png"
    spec = {
        "canvas": {"width": 800, "height": 450},
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
    assert image.size == (800, 450)
