"""BillboardAI rendering module.

Implements scene-based billboard rendering per Sprint 4C requirements.
Preserves RenderContext contract, reuses existing helpers where possible.
Template-driven: all geometry, dimensions, and scene paths come from
template configuration files in assets/templates/.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from engine.config import DEBUG, DEBUG_FOLDER, OUTPUT_DIR

logger = logging.getLogger(__name__)

RENDER_QUALITY_PASS = "PASS"
RENDER_QUALITY_WARNING = "WARNING"
RENDER_QUALITY_BLOCKED = "BLOCKED"
RENDER_HEADLINE_OVERFLOW = "RENDER_HEADLINE_OVERFLOW"
RENDER_CTA_OVERFLOW = "RENDER_CTA_OVERFLOW"
RENDER_TEXT_CLIPPED = "RENDER_TEXT_CLIPPED"
RENDER_TEXT_UNREADABLE = "RENDER_TEXT_UNREADABLE"

_LAST_RENDER_QUALITY: dict[str, Any] = {"status": RENDER_QUALITY_PASS, "reasons": []}


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


def _font_size(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    return int(getattr(font, "size", 0) or 0)


def _line_height(draw: ImageDraw.ImageDraw, line: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), line or "Ag", font=font)
    return int(bbox[3] - bbox[1])


def get_last_render_quality() -> dict[str, Any]:
    return {"status": _LAST_RENDER_QUALITY.get("status", RENDER_QUALITY_PASS), "reasons": list(_LAST_RENDER_QUALITY.get("reasons", []))}


def _set_last_render_quality(status: str, reasons: list[dict[str, Any]]) -> None:
    global _LAST_RENDER_QUALITY
    _LAST_RENDER_QUALITY = {"status": status, "reasons": reasons}


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


def _load_template(template_name: str) -> tuple[Dict[str, Any], str]:
    """Load template definition (scene, quad, dimensions).

    Args:
        template_name: Template identifier (matches filename without .json).

    Returns:
        (template_dict, resolved_template_path)

    Raises:
        FileNotFoundError: If the template JSON file does not exist.
    """
    template_path = Path("assets/templates") / f"{template_name}.json"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f), str(template_path)


def load_physical_template(template_name: str) -> Dict[str, Any]:
    """Public, validated loader for a physical scene template.

    Returns the template dict (scene path, reference_size, billboard_quad,
    default_artwork_size, ...). Raises FileNotFoundError when the template JSON
    does not exist and ValueError when its configuration is invalid. This is the
    single fact source for the intended rectangular artwork dimensions.
    """
    template, template_path = _load_template(template_name)
    _validate_template(template, template_path)
    return template


def artwork_size_for_template(template_name: str) -> Tuple[int, int]:
    """Return the physical template's intended rectangular artwork (width, height).

    The creative must be generated at exactly these dimensions so the completed
    artwork is never stretched to fit the calibrated quad.
    """
    template = load_physical_template(template_name)
    size = template["default_artwork_size"]
    return int(size[0]), int(size[1])


def list_scene_templates() -> List[Dict[str, Any]]:
    """Discover calibrated physical scene templates from ``assets/templates``.

    Returns metadata (id, display name, artwork size) for every valid ``*.json``
    template rather than hardcoding scene ids. Invalid templates are skipped so a
    single bad file never breaks the scene selector. Rows are deterministic
    (sorted by filename).
    """
    template_dir = Path("assets/templates")
    if not template_dir.is_dir():
        return []
    result: List[Dict[str, Any]] = []
    for path in sorted(template_dir.glob("*.json")):
        try:
            template = load_physical_template(path.stem)
        except Exception:  # noqa: BLE001 - skip corrupt/unreadable templates
            continue
        default_size = template.get("default_artwork_size") or [0, 0]
        result.append(
            {
                "id": str(template.get("id") or path.stem),
                "name": str(template.get("name") or path.stem),
                "artwork_size": {
                    "width": int(default_size[0]),
                    "height": int(default_size[1]),
                },
            }
        )
    return result


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
    max_text_width = width - 2 * (card_margin + 20)
    content_bottom = card_bottom - 20
    quality_reasons: list[dict[str, Any]] = []

    def add_reason(code: str, message: str, severity: str = RENDER_QUALITY_WARNING, **extra: Any) -> None:
        quality_reasons.append({"code": code, "message": message, "severity": severity, **extra})

    draw.text((text_x, text_y), spec.get("company", "Brand"), font=company_font, fill=accent_color)
    company_height = draw.textbbox((0, 0), spec.get("company", "Brand"), font=company_font)[3]
    text_y += company_height + 10

    for line in headline_lines:
        bbox = draw.textbbox((text_x, text_y), line, font=headline_font)
        if bbox[2] > text_x + max_text_width:
            add_reason(RENDER_HEADLINE_OVERFLOW, "Rendered headline exceeds its text bounds.", line=line)
        draw.text((text_x, text_y), line, font=headline_font, fill=text_color)
        text_y += _line_height(draw, line, headline_font) + 8
    if headline_lines and _font_size(headline_font) < 24:
        add_reason(RENDER_TEXT_UNREADABLE, "Headline required an unreadable font size.", RENDER_QUALITY_BLOCKED, font_size=_font_size(headline_font))

    if subtitle_lines and any(line.strip() for line in subtitle_lines):
        for line in subtitle_lines:
            draw.text((text_x, text_y), line, font=subtitle_font, fill=text_color)
            text_y += _line_height(draw, line, subtitle_font) + 6

    button_box = [text_x, text_y + 15, text_x + 220, text_y + 55]
    cta_bbox = draw.textbbox((text_x + 20, text_y + 22), cta_text, font=badge_font)
    if cta_bbox[2] > button_box[2] - 10 or cta_bbox[3] > button_box[3] - 4:
        add_reason(RENDER_CTA_OVERFLOW, "Rendered CTA exceeds its button bounds.", cta=cta_text)
    if button_box[3] > content_bottom:
        add_reason(RENDER_TEXT_CLIPPED, "Rendered text/button extends outside the card bounds.", RENDER_QUALITY_BLOCKED, bottom=button_box[3], limit=content_bottom)
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

    status = RENDER_QUALITY_BLOCKED if any(r.get("severity") == RENDER_QUALITY_BLOCKED for r in quality_reasons) else (RENDER_QUALITY_WARNING if quality_reasons else RENDER_QUALITY_PASS)
    _set_last_render_quality(status, quality_reasons)
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


def _validate_template(template: Dict[str, Any], template_path: str) -> None:
    """Validate a physical billboard template configuration.

    All geometry, dimensions, and paths must be present and consistent.
    Fails with a clear error for any invalid or missing configuration.

    Raises:
        ValueError: If any validation check fails.
    """
    # --- Required top-level keys ---
    required_keys = [
        "id",
        "scene_path",
        "reference_size",
        "billboard_quad",
        "default_artwork_size",
    ]
    for key in required_keys:
        if key not in template:
            raise ValueError(
                f"Template '{template_path}' missing required key: '{key}'"
            )

    # --- scene_path ---
    scene_path = template["scene_path"]
    if not isinstance(scene_path, str) or not scene_path:
        raise ValueError(
            f"Template '{template_path}': 'scene_path' must be a non-empty string"
        )
    if not os.path.exists(scene_path):
        raise FileNotFoundError(
            f"Template '{template_path}': scene image not found: {scene_path}"
        )

    # --- reference_size ---
    ref_size = template["reference_size"]
    if (
        not isinstance(ref_size, (list, tuple))
        or len(ref_size) != 2
        or not all(isinstance(v, (int, float)) and v > 0 for v in ref_size)
    ):
        raise ValueError(
            f"Template '{template_path}': 'reference_size' must be [width, height] "
            f"with two positive integers, got: {ref_size}"
        )
    ref_w, ref_h = int(ref_size[0]), int(ref_size[1])

    # Verify source image dimensions match reference_size
    actual_w, actual_h = Image.open(scene_path).size
    if (actual_w, actual_h) != (ref_w, ref_h):
        raise ValueError(
            f"Template '{template_path}': source image dimensions "
            f"({actual_w}x{actual_h}) do not match reference_size "
            f"({ref_w}x{ref_h})"
        )

    # --- billboard_quad ---
    quad = template["billboard_quad"]
    if not isinstance(quad, list) or len(quad) != 4:
        raise ValueError(
            f"Template '{template_path}': 'billboard_quad' must be a list of "
            f"exactly 4 [x, y] points (TL, TR, BR, BL), got {len(quad) if isinstance(quad, list) else type(quad).__name__} entries"
        )

    for i, pt in enumerate(quad):
        corner_names = ["TL", "TR", "BR", "BL"]
        if (
            not isinstance(pt, (list, tuple))
            or len(pt) != 2
            or not all(isinstance(v, (int, float)) for v in pt)
        ):
            raise ValueError(
                f"Template '{template_path}': 'billboard_quad' point {i} "
                f"({corner_names[i]}) must be [x, y] with numeric values, got: {pt}"
            )
        x, y = float(pt[0]), float(pt[1])
        if x < 0 or x > ref_w or y < 0 or y > ref_h:
            raise ValueError(
                f"Template '{template_path}': 'billboard_quad' point {i} "
                f"({corner_names[i]}) [{x:.1f}, {y:.1f}] is outside "
                f"source image bounds ({ref_w}x{ref_h})"
            )

    # Check quad is non-degenerate (area > 0)
    pts = np.array(quad, dtype=np.float32)
    area = cv2.contourArea(pts)
    if area <= 0:
        raise ValueError(
            f"Template '{template_path}': 'billboard_quad' is degenerate "
            f"(area={area:.1f}). Check point ordering (TL, TR, BR, BL)."
        )

    # --- default_artwork_size ---
    artwork_size = template["default_artwork_size"]
    if (
        not isinstance(artwork_size, (list, tuple))
        or len(artwork_size) != 2
        or not all(isinstance(v, (int, float)) and v > 0 for v in artwork_size)
    ):
        raise ValueError(
            f"Template '{template_path}': 'default_artwork_size' must be "
            f"[width, height] with two positive integers, got: {artwork_size}"
        )

    # --- artwork_aspect (optional but validated if present) ---
    artwork_aspect = template.get("artwork_aspect")
    if artwork_aspect is not None:
        if not isinstance(artwork_aspect, (int, float)) or artwork_aspect <= 0:
            raise ValueError(
                f"Template '{template_path}': 'artwork_aspect' must be a "
                f"positive number, got: {artwork_aspect}"
            )
        # Warn if artwork_aspect is inconsistent with default_artwork_size
        config_aspect = artwork_size[0] / artwork_size[1]
        if abs(config_aspect - artwork_aspect) > 0.1:
            logger.warning(
                "Template '%s': 'artwork_aspect' (%.3f) differs from "
                "'default_artwork_size' aspect (%.3f)",
                template_path,
                artwork_aspect,
                config_aspect,
            )


def _composite_artwork(
    template: Dict[str, Any],
    artwork: Image.Image,
    output_path: str,
    debug_enabled: bool = False,
    debug_dir: Optional[Path] = None,
) -> str:
    """Warp completed artwork into the template's calibrated quad and composite.

    Preserves every source-scene pixel outside the billboard replacement area.
    This is the only place that performs perspective warp + compositing, shared
    by the legacy render_billboard path and the Sprint 2H artwork entry point.
    """
    scene_path = template["scene_path"]
    if not os.path.exists(scene_path):
        raise FileNotFoundError(f"Scene image not found: {scene_path}")

    # Load scene at native resolution — no resize, no crop, no fit
    scene = Image.open(scene_path).convert("RGB")
    scene_size = scene.size
    if debug_enabled:
        print(f"DEBUG: scene size (native): {scene_size}")
        _save_debug(scene, "01_scene.png", debug_dir)

    # Use billboard quad directly from template (already in native coordinates)
    quad = template["billboard_quad"]
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


def render_artwork_into_scene(
    artwork: Image.Image,
    scene_template: str,
    output_path: str,
) -> str:
    """Sprint 2H entry: place a *completed* rectangular artwork into a physical scene.

    This is the physical-renderer integration seam. It consumes a pre-rendered
    PIL artwork image only — it never creates headlines, chooses proof/CTA,
    inspects BrandProfile/MessageStrategy/AdConcept, or decides composition. The
    artwork is generated at the template's intended aspect ratio by the caller
    and warped into the calibrated quad without any re-stretching.

    Args:
        artwork: Completed rectangular artwork (RGB/RGBA) at the template's
            default_artwork_size.
        scene_template: Physical scene template id (e.g. cart_corral).
        output_path: Where to save the final mockup.

    Returns:
        output_path
    """
    if not scene_template:
        raise ValueError("No scene_template specified — set 'scene_template' in the render spec")
    template, template_path = _load_template(scene_template)
    logger.info("Renderer template path: %s", template_path)
    logger.info("Renderer reference_size: %s", template.get("reference_size"))
    logger.info("Renderer billboard_quad: %s", template.get("billboard_quad"))

    _validate_template(template, template_path)

    debug_enabled = DEBUG or os.getenv("BILLBOARD_DEBUG", "0") in ("1", "true", "yes")
    debug_dir = Path(DEBUG_FOLDER or str(OUTPUT_DIR / "debug"))

    return _composite_artwork(
        template, artwork, output_path,
        debug_enabled=debug_enabled, debug_dir=debug_dir,
    )


def render_billboard(spec: Dict[str, Any], output_path: str) -> str:
    """Main renderer - loads scene/template at native resolution, generates artwork,
    warps into billboard quad, composites. Output matches source scene dimensions exactly.
    """
    if not output_path:
        output_path = str(OUTPUT_DIR / "billboard.png")

    debug_enabled = DEBUG or os.getenv("BILLBOARD_DEBUG", "0") in ("1", "true", "yes")
    debug_dir = Path(DEBUG_FOLDER or str(OUTPUT_DIR / "debug"))

    # 1. Load template (scene + placement)
    # 'scene_template' selects the physical billboard scene (e.g. cart_corral).
    # 'template' / 'selected_template' is the design theme (e.g. contractor, realtor)
    # and is NOT used for physical template selection.
    scene_template = spec.get("scene_template")
    if not scene_template:
        raise ValueError("No scene_template specified — set 'scene_template' in render spec")
    template, template_path = _load_template(scene_template)
    logger.info("Renderer template path: %s", template_path)
    logger.info("Renderer reference_size: %s", template.get("reference_size"))
    logger.info("Renderer billboard_quad: %s", template.get("billboard_quad"))

    # Validate template configuration before rendering
    _validate_template(template, template_path)

    # 2. Generate artwork at configured working resolution
    default_size = template["default_artwork_size"]
    artwork_size = (int(default_size[0]), int(default_size[1]))
    artwork = _generate_artwork(spec, artwork_size)
    if debug_enabled:
        _save_debug(artwork, "02_artwork.png", debug_dir)

    return _composite_artwork(
        template, artwork, output_path,
        debug_enabled=debug_enabled, debug_dir=debug_dir,
    )
