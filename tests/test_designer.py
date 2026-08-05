import os

from designer import generate_billboard


def test_generate_billboard_includes_template_fields():
    scrape_data = {
        "url": "https://example.com",
        "company": "Example Co",
        "headline": "Outstanding Services",
        "metadata": {"description": "A strong local brand."},
        "logo_path": None,
        "screenshot_path": None,
        "brand_colors": ["#112233", "#445566"],
    }

    spec = generate_billboard(scrape_data, template_name="dentist")

    assert spec["template"] == "dentist"
    assert spec["background_color"] == "#E9F7FF"
    assert spec["company"] == "Example Co"
    assert "headline" in spec
    assert spec["font_family"] == "arial.ttf"
