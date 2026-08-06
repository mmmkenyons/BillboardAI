"""BillboardAI design spec generator."""

from importlib import import_module
from typing import Any, Dict, Optional


class BillboardDesignError(Exception):
    pass


def load_template(template_name: str) -> Dict[str, Any]:
    try:
        module = import_module(f"templates.{template_name}")
    except ModuleNotFoundError as exc:
        raise BillboardDesignError(f"Unknown template '{template_name}'") from exc

    return {
        "template_name": getattr(module, "TEMPLATE_NAME", template_name),
        "background_color": getattr(module, "BACKGROUND_COLOR", "#FFFFFF"),
        "primary_color": getattr(module, "PRIMARY_COLOR", "#222222"),
        "accent_color": getattr(module, "ACCENT_COLOR", "#1F77B4"),
        "text_color": getattr(module, "TEXT_COLOR", "#111111"),
        "button_color": getattr(module, "BUTTON_COLOR", "#FF7F0E"),
        "font_family": getattr(module, "FONT_FAMILY", "arial.ttf"),
        "layout_style": getattr(module, "LAYOUT_STYLE", "classic"),
        "cta_text": getattr(module, "CTA_TEXT", "Learn More"),
    }


def select_template(scrape_data: Dict[str, Any], avoid: Optional[list[str]] = None) -> str:
    avoid = avoid or []
    source_text = " ".join(
        str(value)
        for value in [
            scrape_data.get("company", ""),
            scrape_data.get("headline", ""),
            scrape_data.get("ad_copy", ""),
            scrape_data.get("metadata", {}).get("title", ""),
            scrape_data.get("metadata", {}).get("description", ""),
            scrape_data.get("metadata", {}).get("keywords", ""),
        ]
        if value
    ).lower()

    keywords = {
        "dentist": ["dentist", "dental", "smile", "teeth", "oral", "orthodontic", "clinic"],
        "realtor": ["real estate", "realtor", "property", "home", "house", "listing", "agent", "mortgage", "condo"],
        "contractor": ["roof", "construction", "remodel", "contractor", "builders", "plumbing", "electrician", "service", "repair"],
    }

    scores = {name: 0 for name in keywords}
    for name, words in keywords.items():
        for word in words:
            if word in source_text:
                scores[name] += 5

    if scrape_data.get("quality_score", 0) >= 80 and scrape_data.get("hero_url"):
        scores["realtor"] += 5

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    for template_name, score in ranked:
        if template_name not in avoid and score >= 0:
            return template_name

    return "contractor"


def generate_billboard(scrape_data: Dict[str, Any], template_name: str = "contractor") -> Dict[str, Any]:
    if template_name == "auto":
        template_name = select_template(scrape_data)

    theme = load_template(template_name)

    company = scrape_data.get("company") or scrape_data.get("metadata", {}).get("title") or "Brand"
    headline = scrape_data.get("ad_copy") or scrape_data.get("headline") or scrape_data.get("metadata", {}).get("description") or "Make your message unforgettable"
    subtitle = scrape_data.get("metadata", {}).get("description") or ""
    logo_path = scrape_data.get("logo_path")
    hero_path = scrape_data.get("hero_url") or scrape_data.get("screenshot_path")
    brand_colors = scrape_data.get("brand_colors") or []

    if len(headline) > 120:
        headline = headline[:117].rstrip() + "..."

    selected_template = template_name
    return {
        "template": selected_template,
        "selected_template": selected_template,
        "canvas": {"width": 1600, "height": 900},
        "background_color": theme["background_color"],
        "primary_color": theme["primary_color"],
        "accent_color": theme["accent_color"],
        "text_color": theme["text_color"],
        "button_color": theme["button_color"],
        "font_family": theme["font_family"],
        "layout_style": theme["layout_style"],
        "cta_text": theme["cta_text"],
        "company": company,
        "headline": headline,
        "subtitle": subtitle,
        "logo_path": logo_path,
        "hero_path": hero_path,
        "brand_colors": brand_colors,
        "source_url": scrape_data.get("url"),
    }
