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


def render_spec_from_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Build a renderer spec from a complete render_context contract.

    The GUI path should prefer this over scrape-shaped inputs. Missing
    theme fields fall back to the named template module.
    """
    ctx = dict(context or {})
    template_name = ctx.get("template") or "contractor"
    theme = load_template(template_name)

    fonts_raw = ctx.get("fonts")
    fonts: Dict[str, Any] = fonts_raw if isinstance(fonts_raw, dict) else {}
    layout_raw = ctx.get("layout")
    layout: Dict[str, Any] = layout_raw if isinstance(layout_raw, dict) else {}
    canvas_raw = layout.get("canvas")
    canvas: Dict[str, Any] = canvas_raw if isinstance(canvas_raw, dict) else {}


    company = (
        ctx.get("company_name")
        or ctx.get("company")
        or "Brand"
    )
    headline = ctx.get("headline") or "Make your message unforgettable"
    if len(str(headline)) > 120:
        headline = str(headline)[:117].rstrip() + "..."

    # Preserve explicit None for logo (CLI tests / missing asset) vs empty string.
    if "logo_image" in ctx:
        logo = ctx.get("logo_image")
    elif "logo_path" in ctx:
        logo = ctx.get("logo_path")
    else:
        logo = None
    if logo == "":
        logo = None

    hero = (
        ctx.get("hero_image")
        or ctx.get("background_image")
        or ctx.get("hero_path")
        or ctx.get("screenshot_path")
        or None
    )

    return {
        "template": template_name,
        "selected_template": template_name,
        "canvas": {
            "width": int(canvas.get("width") or 1600),
            "height": int(canvas.get("height") or 900),
        },
        "background_color": ctx.get("background_color") or theme["background_color"],
        "primary_color": ctx.get("primary_color") or theme["primary_color"],
        "accent_color": ctx.get("accent_color") or theme["accent_color"],
        "text_color": ctx.get("text_color") or theme["text_color"],
        "button_color": ctx.get("button_color") or theme["button_color"],
        "font_family": fonts.get("family") or theme["font_family"],
        "layout_style": layout.get("style") or theme["layout_style"],
        "cta_text": ctx.get("cta") or ctx.get("cta_text") or theme["cta_text"],
        "company": company,
        "headline": headline,
        "subtitle": ctx.get("subtitle") or "",
        "logo_path": logo,
        "hero_path": hero,
        "brand_colors": list(ctx.get("brand_colors") or []),
        "source_url": ctx.get("source_url") or ctx.get("url") or "",
    }



def generate_billboard(scrape_data: Dict[str, Any] | None, template_name: str = "contractor") -> Dict[str, Any]:
    """CLI/batch-compatible entry: scrape dict → render spec.

    Internally normalizes toward the render_context contract so GUI and
    CLI share one mapping path.
    """
    if not scrape_data:
        scrape_data = {}
    if template_name == "auto":
        template_name = select_template(scrape_data)

    theme = load_template(template_name)
    meta_raw = scrape_data.get("metadata")
    metadata: Dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}

    company = scrape_data.get("company") or metadata.get("title") or "Brand"
    headline = (
        scrape_data.get("ad_copy")
        or scrape_data.get("headline")
        or metadata.get("description")
        or "Make your message unforgettable"
    )
    subtitle = metadata.get("description") or ""

    logo_path = scrape_data.get("logo_path")
    hero_path = scrape_data.get("hero_url") or scrape_data.get("screenshot_path")
    brand_colors = scrape_data.get("brand_colors") or []

    context = {
        "template": template_name,
        "company_name": company,
        "headline": headline,
        "subtitle": subtitle if subtitle != headline else "",
        "cta": theme.get("cta_text") or "Learn More",
        "logo_image": logo_path,
        "hero_image": hero_path or "",
        "background_image": scrape_data.get("screenshot_path") or hero_path or "",

        "primary_color": theme["primary_color"],
        "secondary_color": theme["background_color"],
        "accent_color": theme["accent_color"],
        "text_color": theme["text_color"],
        "button_color": theme["button_color"],
        "background_color": theme["background_color"],
        "fonts": {"family": theme["font_family"]},
        "layout": {
            "style": theme["layout_style"],
            "canvas": {"width": 1600, "height": 900},
        },
        "brand_colors": brand_colors,
        "source_url": scrape_data.get("url") or "",
        "quality_score": scrape_data.get("quality_score") or 0,
    }
    return render_spec_from_context(context)


