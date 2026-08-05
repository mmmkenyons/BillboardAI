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
