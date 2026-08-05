"""BillboardAI design spec generator."""

from importlib import import_module
from typing import Any, Dict


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
    }


def generate_billboard(scrape_data: Dict[str, Any], template_name: str = "contractor") -> Dict[str, Any]:
    theme = load_template(template_name)

    company = scrape_data.get("company") or scrape_data.get("metadata", {}).get("title") or "Brand"
    headline = scrape_data.get("headline") or scrape_data.get("metadata", {}).get("description") or "Make your message unforgettable"
    subtitle = scrape_data.get("metadata", {}).get("description", "")
    logo_path = scrape_data.get("logo_path") or scrape_data.get("screenshot_path")
    hero_path = scrape_data.get("hero_url") or scrape_data.get("screenshot_path")
    brand_colors = scrape_data.get("brand_colors") or []

    if len(headline) > 120:
        headline = headline[:117].rstrip() + "..."

    return {
        "template": template_name,
        "canvas": {"width": 1600, "height": 900},
        "background_color": theme["background_color"],
        "primary_color": theme["primary_color"],
        "accent_color": theme["accent_color"],
        "text_color": theme["text_color"],
        "button_color": theme["button_color"],
        "font_family": theme["font_family"],
        "company": company,
        "headline": headline,
        "subtitle": subtitle,
        "logo_path": logo_path,
        "hero_path": hero_path,
        "brand_colors": brand_colors,
        "source_url": scrape_data.get("url"),
    }
