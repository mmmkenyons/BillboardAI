"""CreativeArtworkRenderer: draw a CreativeLayoutSpec into a rectangular PIL image.

Draws ONLY from a CreativeLayoutSpec. It never inspects BrandProfile,
MessageStrategy, or AdConcept, never reads physical-scene geometry, and never
performs perspective transforms. Output is a clean rectangular advertisement at
exactly spec.artwork_width x spec.artwork_height.

Visual language (Sprint 2G gate):
  - CTA is a strong full-width bottom band (outdoor callout), not a rounded UI pill.
  - A brand ``field`` panel backs the logo zone for visual mass.
  - Text sits on the readable background / on-accent band only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from engine.layout import contrast, typography
from engine.layout.model import CreativeLayoutSpec, LayoutLogo, LayoutText, contain_size


class CreativeArtworkRenderer:
    """Renders a resolved CreativeLayoutSpec to a PIL image."""

    def __init__(self, registry: "typography.FontRegistry" = None) -> None:
        self._registry = registry or typography.FontRegistry()

    def render(self, spec: CreativeLayoutSpec) -> Image.Image:
        w, h = spec.artwork_width, spec.artwork_height
        img = Image.new("RGB", (w, h), spec.palette.background)
        draw = ImageDraw.Draw(img)

        if spec.field_rect is not None:
            self._draw_field(draw, spec)
        if spec.logo is not None:
            self._draw_logo(img, spec.logo)
        if spec.headline is not None:
            self._draw_text_block(draw, spec.headline, spec.palette.text)
        for proof in spec.proofs:
            self._draw_text_block(draw, proof, spec.palette.text)
        if spec.cta is not None:
            self._draw_cta_band(draw, spec.cta, spec.palette.accent)
        return img

    def render_to_file(self, spec: CreativeLayoutSpec, path: str) -> str:
        """Render and save to *path* (creating parent dirs); returns the path."""
        img = self.render(spec)
        path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        return path

    # ------------------------------------------------------------------

    def _draw_field(self, draw: ImageDraw.ImageDraw, spec: CreativeLayoutSpec) -> None:
        x0, y0, x1, y1 = spec.field_rect
        draw.rectangle([x0, y0, x1, y1], fill=spec.palette.field)

    def _draw_text_block(self, draw: ImageDraw.ImageDraw, lt: LayoutText, color: str) -> None:
        font = self._registry.resolve(lt.font, lt.font_size)
        x0, y0, x1, y1 = lt.rect
        lines = list(lt.lines) or [lt.text]
        line_height = lt.line_height or typography.text_height(font)
        total = line_height * len(lines)
        y = y0 + max(0, (y1 - y0 - total) // 2)
        for line in lines:
            line_w = draw.textlength(line, font=font)
            if lt.alignment == "center":
                x = x0 + max(0, (x1 - x0 - line_w) // 2)
            elif lt.alignment == "right":
                x = x1 - line_w
            else:
                x = x0
            draw.text((x, y), line, font=font, fill=color)
            y += line_height

    def _draw_cta_band(self, draw: ImageDraw.ImageDraw, ct: LayoutText, accent: str) -> None:
        """Full-width accent band: an outdoor callout, not a web button."""
        font = self._registry.resolve(ct.font, ct.font_size)
        text = " ".join(ct.lines or [ct.text])
        x0, y0, x1, y1 = ct.rect
        draw.rectangle([x0, y0, x1, y1], fill=accent)
        line_height = ct.line_height or typography.text_height(font)
        text_w = draw.textlength(text, font=font)
        x = x0 + max(0, (x1 - x0 - text_w) // 2)
        y = y0 + max(0, (y1 - y0 - line_height) // 2)
        fill = contrast.choose_text_on(accent)
        draw.text((x, y), text, font=font, fill=fill)

    def _draw_logo(self, img: Image.Image, logo: LayoutLogo) -> None:
        if not logo.path or not os.path.exists(logo.path):
            return
        try:
            source = Image.open(logo.path).convert("RGBA")
        except OSError:
            return
        x0, y0, x1, y1 = logo.rect
        rw, rh = (x1 - x0), (y1 - y0)
        if rw <= 0 or rh <= 0:
            return
        clear = max(2, round(min(rw, rh) * 0.08))
        paste = logo.paste_size or contain_size(
            max(1, rw - 2 * clear), max(1, rh - 2 * clear), logo.source_aspect
        )
        cw, ch = paste
        if cw <= 0 or ch <= 0:
            return
        resized = source.resize((cw, ch), Image.Resampling.LANCZOS)
        ox = x0 + (rw - cw) // 2
        oy = y0 + (rh - ch) // 2
        img.paste(resized, (ox, oy), resized)
