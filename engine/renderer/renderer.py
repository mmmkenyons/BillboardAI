"""BillboardAI rendering module.

Implements scene-based billboard rendering per Sprint 4C requirements.
Preserves RenderContext contract, reuses existing helpers where possible.
Uses cart_corral template for natural composite with perspective warp.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from engine.config import DEBUG, DEBUG_FOLDER, OUTPUT_DIR

logger = logging.getLogger(__name__)


def _load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(font_name, size)
    except OSError:
        return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> List[str]:
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


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font_name: str, max_width: int, max_size: int, min_size: int = 18) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, List[str]]:
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
    reflection = base.crop(area).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    reflection = reflection.crop((0, 0, x2 - x1, int((y2 - y1) * 0.35)))
    mask = Image.new("L", reflection.size, 0)
    gradient = Image.linear_gradient("L").resize(reflection.size)
    mask = Image.composite(mask, gradient, gradient)
    base.paste(reflection, (x1, y2 + 10), mask)


def _apply_perspective(image: Image.Image) -> Image.Image:
    """Legacy helper - kept for compatibility with existing tests."""
    width, height = image.size
    coeffs = [1, 0, 0, 0.02, 1, -int(height * 0.05), 0, 0]
    warped = image.transform((width, height), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
    warped = warped.filter(ImageFilter.GaussianBlur(radius=0.2))
    return warped


def _load_template(template_name: str = "cart_corral") -> tuple[Dict[str, Any], str]:
    """Load template definition (scene, quad, dimensions).

    Returns:
        (template_dict, resolved_template_path)
    """
    template_path = Path("assets/templates") / f"{template_name}.json"
    if not template_path.exists():
        # Fallback to cart_corral
        template_path = Path("assets/templates/cart_corral.json")
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f), str(template_path)


def _generate_artwork(spec: Dict[str, Any], size: Tuple[int, int]) -> Image.Image:
    """Generate advertisement artwork using existing design logic (reused from old renderer).
    Uses hero_path (website screenshot) as input asset inside the ad, not as background.
    """
    width, height = size
    background_color = spec.get("background_color", "#FFFFFF")
    text_color = spec.get("text_color", "#111111")
    accent_color = spec.get("accent_color", "#1F77B4")
    button_color = spec.get("button_color", "#FF7F0E")
    layout_style = spec.get("layout_style", "classic")
    cta_text = spec.get("cta_text", "Learn More")

    artwork = Image.new("RGB", (width, height), background_color)
    draw = ImageDraw.Draw(artwork)

    hero_path = spec.get("hero_path")
    hero_exists = isinstance(hero_path, str) and os.path.exists(hero_path)
    hero_height = int(height * 0.4) if hero_exists else 0

    if hero_exists:
        try:
            assert isinstance(hero_path, str)
            hero = Image.open(hero_path).convert("RGB")
            hero = hero.resize((width, hero_height), Image.Resampling.LANCZOS)
            if layout_style == "photo":
                hero = _apply_hero_effects(hero)
            hero = _apply_perspective(hero)  # Reuse legacy for hero strip
            artwork.paste(hero, (0, 0))
            if layout_style == "photo":
                overlay = Image.new("RGBA", (width, hero_height), (0, 0, 0, 80))
                artwork.paste(overlay, (0, 0), overlay)
        except OSError:
            hero_exists = False
            hero_height = 0

    panel_y = hero_height
    draw.rectangle([0, panel_y, width, height], fill=background_color)

    card_margin = 40
    card_top = panel_y + 20
    card_bottom = height - 30
    card_rect = [card_margin, card_top, width - card_margin, card_bottom]

    card_fill = "#F8F8F8" if layout_style in ("premium", "white") else background_color
    draw.rectangle(card_rect, fill=card_fill, outline="#DDDDDD", width=2)

    company_font = _load_font(spec.get("font_family", "arial.ttf"), 36)
    headline_font, headline_lines = _fit_text(
        draw, spec.get("headline", "Make your message unforgettable"), spec.get("font_family", "arial.ttf"),
        width - 2 * (card_margin + 20), 48, min_size=24
    )
    subtitle_font, subtitle_lines = _fit_text(
        draw, spec.get("subtitle", ""), spec.get("font_family", "arial.ttf"),
        width - 2 * (card_margin + 20), 24, min_size=16
    )
    badge_font = _load_font(spec.get("font_family", "arial.ttf"), 20)

    text_x = card_margin + 30
    text_y = card_top + 30

    draw.text((text_x, text_y), spec.get("company", "Brand"), font=company_font, fill=accent_color)
    company_height = draw.textbbox((0, 0), spec.get("company", "Brand"), font=company_font)[3]
    text_y += company_height + 10

    for line in headline_lines:
        draw.text((text_x, text_y), line, font=headline_font, fill=text_color)
        text_y += draw.textbbox((0, 0), line, font=headline_font)[3] - draw.textbbox((0, 0), line, font=headline_font)[1] + 8

    if subtitle_lines and any(line.strip() for line in subtitle_lines):
        for line in subtitle_lines:
            draw.text((text_x, text_y), line, font=subtitle_font, fill=text_color)
            text_y += draw.textbbox((0, 0), line, font=subtitle_font)[3] - draw.textbbox((0, 0), line, font=subtitle_font)[1] + 6

    button_box = [text_x, text_y + 15, text_x + 220, text_y + 55]
    draw.rectangle(button_box, fill=button_color, outline=None)
    draw.text((text_x + 20, text_y + 22), cta_text, font=badge_font, fill="#FFFFFF")

    logo_path = spec.get("logo_path")
    if isinstance(logo_path, str) and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((140, 70), Image.Resampling.LANCZOS)
            logo_position = (width - logo.width - 30, card_top + 20)
            artwork.paste(logo, logo_position, logo)
        except OSError:
            pass

    return artwork


def _perspective_transform_pil(
    src_img: Image.Image,
    dst_quad: List[List[int]],
    output_size: Tuple[int, int],
    debug: bool = False,
) -> Image.Image:
    """Real four-point perspective transform using OpenCV homography.

    Maps the source artwork rectangle onto the destination billboard quad
    via cv2.getPerspectiveTransform + cv2.warpPerspective.

    Returns RGBA image with transparent pixels outside the quad.
    """
    src_w, src_h = src_img.size
    out_w, out_h = output_size

    # Source: artwork rectangle corners (top-left, top-right, bottom-right, bottom-left)
    src_pts = np.array(
        [
            [0, 0],
            [src_w - 1, 0],
            [src_w - 1, src_h - 1],
            [0, src_h - 1],
        ],
        dtype=np.float32,
    )
    # Destination: billboard quad (same corner order: TL, TR, BR, BL)
    dst_pts = np.array(dst_quad, dtype=np.float32)

    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)

    if debug:
        print(f"DEBUG: perspective source size: {src_w}x{src_h}")
        print(f"DEBUG: perspective dst quad: {dst_quad}")
        print(f"DEBUG: perspective matrix:\n{matrix}")

    # Convert PIL RGB -> OpenCV BGR
    src_bgr = cv2.cvtColor(np.array(src_img), cv2.COLOR_RGB2BGR)

    # Warp RGB channels onto output-sized canvas (black fill outside quad)
    warped_bgr = cv2.warpPerspective(
        src_bgr,
        matrix,
        (out_w, out_h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)

    # Warp alpha mask (white inside quad, transparent outside)
    alpha_src = np.full((src_h, src_w), 255, dtype=np.uint8)
    alpha_warped = cv2.warpPerspective(
        alpha_src,
        matrix,
        (out_w, out_h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    # Combine into RGBA
    warped_rgba = np.dstack([warped_rgb, alpha_warped])
    return Image.fromarray(warped_rgba, "RGBA")


def _save_debug(image: Image.Image, name: str, debug_dir: Path) -> None:
    """Save debug artifact."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / name
    image.save(path)
    print(f"DEBUG: Saved {path}")


def render_billboard(spec: Dict[str, Any], output_path: str) -> str:
    """Main renderer - loads scene/template at native resolution, generates artwork,
    warps into billboard quad, composites. Output matches source scene dimensions exactly.
    """
    if not output_path:
        output_path = str(OUTPUT_DIR / "billboard.png")

    debug_enabled = DEBUG or os.getenv("BILLBOARD_DEBUG", "0") in ("1", "true", "yes")
    debug_dir = Path(DEBUG_FOLDER or str(OUTPUT_DIR / "debug"))

    # 1. Load template (scene + placement)
    template_name = spec.get("template") or spec.get("selected_template") or "cart_corral"
    template, template_path = _load_template(template_name)
    logger.info("Renderer template path: %s", template_path)
    logger.info("Renderer reference_size: %s", template.get("reference_size"))
    logger.info("Renderer billboard_quad: %s", template.get("billboard_quad"))
    scene_path = template.get("scene_path", "assets/cart_corral.jpg")
    if not os.path.exists(scene_path):
        scene_path = "assets/cart_corral.jpg"  # fallback

    # Load scene at native resolution — no resize, no crop, no fit
    scene = Image.open(scene_path).convert("RGB")
    scene_size = scene.size
    if debug_enabled:
        print(f"DEBUG: scene size (native): {scene_size}")
        _save_debug(scene, "01_scene.png", debug_dir)

    # 2. Generate artwork at configured working resolution
    default_size = template.get("default_artwork_size", (640, 400))
    artwork_size = (int(default_size[0]), int(default_size[1]))
    artwork = _generate_artwork(spec, artwork_size)
    if debug_enabled:
        _save_debug(artwork, "02_artwork.png", debug_dir)

    # 3. Use billboard quad directly from template (already in native coordinates)
    quad = template.get("billboard_quad", [[100, 100], [500, 100], [520, 300], [80, 320]])
    if debug_enabled:
        print(f"DEBUG: billboard quad (native): {quad}")

    # 3b. Billboard mask (for compositing)
    mask = Image.new("L", scene_size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.polygon([tuple(p) for p in quad], fill=255)
    if debug_enabled:
        _save_debug(mask, "03_billboard_mask.png", debug_dir)

    # 4. Warp artwork into billboard quad (returns RGBA with transparency outside quad)
    warped = _perspective_transform_pil(artwork, quad, scene_size, debug=debug_enabled)
    if debug_enabled:
        _save_debug(warped, "04_warped_artwork.png", debug_dir)

    # 5. Clean composite: paste warped artwork onto scene using its own alpha channel
    composite = scene.copy()
    composite.paste(warped, (0, 0), warped)
    if debug_enabled:
        _save_debug(composite, "05_composite.png", debug_dir)

    # 6. Final: save output (no global effects — preserve source pixels outside billboard)
    final = composite
    if debug_enabled:
        _save_debug(final, "06_final.png", debug_dir)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path)
    return output_path
