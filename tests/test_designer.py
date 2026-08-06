import os

from designer import generate_billboard, select_template


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
    assert spec["layout_style"] == "white"
    assert spec["cta_text"] == "Book Now"


def test_logo_path_does_not_fall_back_to_screenshot():
    """When no logo is found, logo_path should be None, not screenshot_path."""
    scrape_data = {
        "url": "https://example.com",
        "company": "Example Co",
        "logo_path": None,
        "screenshot_path": "/fake/screenshot.png",
        "hero_url": None,
    }

    spec = generate_billboard(scrape_data, template_name="contractor")

    assert spec["logo_path"] is None
    assert spec["hero_path"] == "/fake/screenshot.png"


def test_logo_path_uses_real_logo_when_available():
    """When a logo exists, it should be used as logo_path, not screenshot."""
    scrape_data = {
        "company": "TNR Roofing",
        "logo_path": "/fake/logo.png",
        "screenshot_path": "/fake/screenshot.png",
        "hero_url": "/fake/hero.png",
    }

    spec = generate_billboard(scrape_data, template_name="contractor")

    assert spec["logo_path"] == "/fake/logo.png"


def test_auto_template_selection_uses_realtor():
    scrape_data = {
        "company": "Example Realty",
        "headline": "Find your dream home today",
        "ad_copy": "Trusted local real estate agents with the best listings.",
        "metadata": {"description": "Real estate specialists"},
        "logo_path": None,
        "screenshot_path": None,
        "brand_colors": ["#112233", "#445566"],
        "quality_score": 85,
        "hero_url": "https://example.com/hero.jpg",
    }

    selected = select_template(scrape_data)
    assert selected == "realtor"

    spec = generate_billboard(scrape_data, template_name="auto")
    assert spec["template"] == "realtor"
    assert spec["selected_template"] == "realtor"
    assert spec["layout_style"] == "premium"
