"""BillboardAI rendering module."""

import os
from typing import Dict

from PIL import Image, ImageDraw, ImageFont


def _load_font(font_name: str, size: int):
    try:
        return ImageFont.truetype(font_name, size)
    except OSError:
        return ImageFont.load_default()


def render_billboard(spec: Dict[str, any], output_path: str) -> str:
    width = spec.get("canvas", {}).get("width", 1600)
    height = spec.get("canvas", {}).get("height", 900)
    background_color = spec.get("background_color", "#FFFFFF")
    text_color = spec.get("text_color", "#111111")
    accent_color = spec.get("accent_color", "#1F77B4")
    button_color = spec.get("button_color", "#FF7F0E")

    base = Image.new("RGB", (width, height), background_color)
    draw = ImageDraw.Draw(base)

    company_font = _load_font(spec.get("font_family", "arial.ttf"), 56)
    headline_font = _load_font(spec.get("font_family", "arial.ttf"), 74)
    subtitle_font = _load_font(spec.get("font_family", "arial.ttf"), 32)
    badge_font = _load_font(spec.get("font_family", "arial.ttf"), 28)

    hero_path = spec.get("hero_path")
    if hero_path and os.path.exists(hero_path):
        try:
            hero = Image.open(hero_path).convert("RGB")
            hero = hero.resize((width, int(height * 0.5)), Image.LANCZOS)
            base.paste(hero, (0, 0))
        except OSError:
            pass

    draw.rectangle([0, int(height * 0.55), width, height], fill=background_color)
    draw.text((80, 40), spec.get("company", "Brand"), font=company_font, fill=accent_color)

    headline = spec.get("headline", "Make your message unforgettable")
    draw.text((80, 130), headline, font=headline_font, fill=text_color)

    subtitle = spec.get("subtitle", "")
    if subtitle:
        draw.text((80, 230), subtitle, font=subtitle_font, fill=text_color)

    button_box = [80, 320, 420, 390]
    draw.rectangle(button_box, fill=button_color)
    draw.text((100, 330), "Learn More", font=badge_font, fill="#FFFFFF")

    logo_path = spec.get("logo_path")
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((250, 120), Image.LANCZOS)
            base.paste(logo, (width - logo.width - 80, 80), logo)
        except OSError:
            pass

    base.save(output_path)
    return output_path
