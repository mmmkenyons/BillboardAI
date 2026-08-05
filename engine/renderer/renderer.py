"""BillboardAI rendering module."""

import os
from typing import Dict, List

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


def _load_font(font_name: str, size: int):
    try:
        return ImageFont.truetype(font_name, size)
    except OSError:
        return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return [""]

    lines = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font_name: str, max_width: int, max_size: int, min_size: int = 18) -> tuple[ImageFont.ImageFont, List[str]]:
    for size in range(max_size, min_size - 1, -2):
        font = _load_font(font_name, size)
        lines = _wrap_text(draw, text, font, max_width)
        if all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines) and len(lines) <= 5:
            return font, lines
    fallback_font = _load_font(font_name, min_size)
    return fallback_font, _wrap_text(draw, text, fallback_font, max_width)


def _apply_hero_effects(hero: Image.Image) -> Image.Image:
    hero = hero.filter(ImageFilter.GaussianBlur(radius=1.8))
    enhancer = ImageEnhance.Brightness(hero)
    hero = enhancer.enhance(1.05)
    noise = Image.effect_noise(hero.size, 8).convert("RGB")
    hero = Image.blend(hero, noise, 0.04)
    return hero.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))


def _draw_shadow(base: Image.Image, offset: int = 20, radius: int = 20) -> None:
    alpha = base.split()[-1] if base.mode == "RGBA" else None
    if alpha is None:
        return
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", base.size, (0, 0, 0, 120))
    shadow.paste(shadow_layer, (offset, offset), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=radius))
    base.alpha_composite(shadow)


def _draw_reflection(base: Image.Image, area: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = area
    reflection = base.crop(area).transpose(Image.FLIP_TOP_BOTTOM)
    reflection = reflection.crop((0, 0, x2 - x1, int((y2 - y1) * 0.35)))
    mask = Image.new("L", reflection.size, 0)
    gradient = Image.linear_gradient("L").resize(reflection.size)
    mask = Image.composite(mask, gradient, gradient)
    base.paste(reflection, (x1, y2 + 10), mask)


def _apply_perspective(image: Image.Image) -> Image.Image:
    width, height = image.size
    shift = int(width * 0.03)
    coeffs = [1, 0, 0, 0.02, 1, -int(height * 0.05), 0, 0]
    warped = image.transform((width, height), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    warped = warped.filter(ImageFilter.GaussianBlur(radius=0.2))
    return warped


def render_billboard(spec: Dict[str, any], output_path: str) -> str:
    width = spec.get("canvas", {}).get("width", 1600)
    height = spec.get("canvas", {}).get("height", 900)
    background_color = spec.get("background_color", "#FFFFFF")
    text_color = spec.get("text_color", "#111111")
    accent_color = spec.get("accent_color", "#1F77B4")
    button_color = spec.get("button_color", "#FF7F0E")
    layout_style = spec.get("layout_style", "classic")
    cta_text = spec.get("cta_text", "Learn More")

    base = Image.new("RGB", (width, height), background_color)
    draw = ImageDraw.Draw(base)

    hero_path = spec.get("hero_path")
    hero_exists = hero_path and os.path.exists(hero_path)

    hero_height = int(height * 0.48) if hero_exists else 0
    if hero_exists:
        try:
            hero = Image.open(hero_path).convert("RGB")
            hero = hero.resize((width, hero_height), Image.LANCZOS)
            if layout_style == "photo":
                hero = _apply_hero_effects(hero)
            hero = _apply_perspective(hero)
            base.paste(hero, (0, 0))
            if layout_style == "photo":
                overlay = Image.new("RGBA", (width, hero_height), (0, 0, 0, 110))
                base.paste(overlay, (0, 0), overlay)
        except OSError:
            hero_exists = False
            hero_height = 0

    panel_y = hero_height
    draw.rectangle([0, panel_y, width, height], fill=background_color)

    card_fill = background_color
    if layout_style == "white":
        card_fill = "#FFFFFF"
    elif layout_style == "premium":
        card_fill = "#F8F1E6"

    card_margin = 60
    card_top = panel_y + 30 if hero_exists else 40
    card_bottom = height - 40
    card_rect = [card_margin, card_top, width - card_margin, card_bottom]

    if layout_style in {"premium", "white", "photo"}:
        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rectangle([card_rect[0] + 14, card_rect[1] + 14, card_rect[2] + 14, card_rect[3] + 14], fill=(0, 0, 0, 80))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
        base = Image.alpha_composite(base.convert("RGBA"), shadow).convert("RGB")

    draw.rectangle(card_rect, fill=card_fill)

    if hero_exists and layout_style == "photo":
        _draw_reflection(base, (0, 0, width, hero_height))

    company_font = _load_font(spec.get("font_family", "arial.ttf"), 52)
    headline_font, headline_lines = _fit_text(draw, spec.get("headline", "Make your message unforgettable"), spec.get("font_family", "arial.ttf"), width - 2 * (card_margin + 20), 72)
    subtitle_font, subtitle_lines = _fit_text(draw, spec.get("subtitle", ""), spec.get("font_family", "arial.ttf"), width - 2 * (card_margin + 20), 34)
    badge_font = _load_font(spec.get("font_family", "arial.ttf"), 28)

    text_x = card_margin + 40
    text_y = card_top + 40

    if hero_exists and layout_style == "photo":
        text_y = 60
        draw.text((text_x, text_y), spec.get("company", "Brand"), font=company_font, fill="#FFFFFF")
    else:
        text_y = card_top + 40
        draw.text((text_x, text_y), spec.get("company", "Brand"), font=company_font, fill=accent_color)

    company_height = draw.textbbox((0, 0), spec.get("company", "Brand"), font=company_font)[3]
    text_y += company_height + 14

    for line in headline_lines:
        draw.text((text_x, text_y), line, font=headline_font, fill=text_color)
        text_y += draw.textbbox((0, 0), line, font=headline_font)[3] - draw.textbbox((0, 0), line, font=headline_font)[1] + 10

    if subtitle_lines and any(line.strip() for line in subtitle_lines):
        for line in subtitle_lines:
            draw.text((text_x, text_y), line, font=subtitle_font, fill=text_color)
            text_y += draw.textbbox((0, 0), line, font=subtitle_font)[3] - draw.textbbox((0, 0), line, font=subtitle_font)[1] + 8

    button_box = [text_x, text_y + 20, text_x + 340, text_y + 82]
    draw.rectangle(button_box, fill=button_color, outline=None)
    draw.text((text_x + 24, text_y + 26), cta_text, font=badge_font, fill="#FFFFFF")

    logo_path = spec.get("logo_path")
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((220, 110), Image.LANCZOS)
            logo_position = (width - logo.width - 60, card_top + 40)
            base.paste(logo, logo_position, logo)
        except OSError:
            pass

    base.save(output_path)
    return output_path
