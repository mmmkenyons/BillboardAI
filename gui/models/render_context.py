"""Complete rendering contract for BillboardAI.

``render_context`` is the single object sufficient to recreate a billboard
without scraping, Playwright, or AI. Designer + renderer consume this
contract (via :func:`to_render_spec`) rather than ad-hoc scrape dicts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from gui.models.prospect_generation import OpportunityGenerationContext


RENDER_CONTEXT_VERSION = 1

_DEFAULT_CANVAS = {"width": 1600, "height": 900}


def _theme_from_template(template: str) -> dict[str, Any]:
    """Resolve theme fields from a template module (safe defaults on failure)."""
    name = template or "contractor"
    try:
        from engine.designer import load_template

        theme = load_template(name)
    except Exception:  # noqa: BLE001 - never break persistence/load
        theme = {
            "background_color": "#FFFFFF",
            "primary_color": "#222222",
            "accent_color": "#1F77B4",
            "text_color": "#111111",
            "button_color": "#FF7F0E",
            "font_family": "arial.ttf",
            "layout_style": "classic",
            "cta_text": "Learn More",
        }
    return theme


def _asset_exists(path: str) -> bool:
    if not path:
        return False
    try:
        import os

        return os.path.isfile(path)
    except OSError:
        return False


def _select_visual_assets(profile: Any) -> tuple[str, str, dict[str, Any]]:
    """Choose hero/background paths from a BrandProfile with person-aware rules."""
    from engine.brand_profile import (
        ROLE_GENERIC_HERO,
        ROLE_PERSON_HEADER,
        ROLE_PERSON_PROFILE,
        ROLE_PROPERTY_LISTING,
    )

    screenshot = str(profile.screenshot_path or "")
    diagnostics = dict(profile.source_metadata.get("asset_selection_diagnostics") or {})
    person_oriented = bool(diagnostics.get("person_oriented"))
    assets = list(profile.assets or [])

    usable = [a for a in assets if _asset_exists(str(a.path or "")) and int(a.width or 0) >= 120 and int(a.height or 0) >= 120]
    person_profiles = [a for a in usable if a.role == ROLE_PERSON_PROFILE and a.person_relevance_score >= 95]
    person_headers = [a for a in usable if a.role == ROLE_PERSON_HEADER and a.person_relevance_score >= 85]
    generic_heroes = [a for a in usable if a.role == ROLE_GENERIC_HERO]
    # Backward compatibility: historical BrandProfile.hero_assets paths were
    # treated as authoritative render paths, including in offline/synthetic
    # tests that do not create actual files.  Keep that behavior for the legacy
    # hero field; person-aware candidates from profile.assets still require a
    # real file so failed downloads fall back safely to screenshot.
    legacy_heroes = [a for a in profile.hero_assets or [] if str(a.path or "")]

    def key(asset: Any) -> tuple[float, float, str]:
        return (
            float(asset.person_relevance_score or 0),
            float(asset.selection_score or 0),
            str(asset.source_url or asset.path or ""),
        )

    selected_reason = "screenshot_fallback"
    if person_oriented and person_profiles:
        hero = sorted(person_profiles, key=key, reverse=True)[0]
        hero_path = hero.path
        selected_reason = "person_profile_preferred"
    elif person_oriented and person_headers:
        hero = sorted(person_headers, key=key, reverse=True)[0]
        hero_path = hero.path
        selected_reason = "person_header_preferred"
    elif legacy_heroes:
        hero = legacy_heroes[0]
        hero_path = hero.path
        selected_reason = "legacy_hero_asset"
    elif generic_heroes:
        hero = sorted(generic_heroes, key=key, reverse=True)[0]
        hero_path = hero.path
        selected_reason = "generic_hero_asset"
    else:
        hero = None
        hero_path = screenshot

    if person_oriented and person_headers:
        background = sorted(person_headers, key=key, reverse=True)[0]
        background_path = background.path
        background_reason = "person_header_background"
    elif generic_heroes:
        background = sorted(generic_heroes, key=key, reverse=True)[0]
        background_path = background.path
        background_reason = "generic_hero_background"
    else:
        background = None
        background_path = screenshot or hero_path
        background_reason = "screenshot_background_fallback"

    diagnostics.update({
        "selected_hero": hero_path or "",
        "selected_hero_role": getattr(hero, "role", "SCREENSHOT" if hero_path == screenshot else ""),
        "selected_hero_reason": selected_reason,
        "selected_background": background_path or "",
        "selected_background_role": getattr(background, "role", "SCREENSHOT" if background_path == screenshot else ""),
        "selected_background_reason": background_reason,
        "screenshot_path": screenshot,
        "property_listing_candidates": len([a for a in assets if a.role == ROLE_PROPERTY_LISTING]),
    })
    return str(hero_path or ""), str(background_path or ""), diagnostics


@dataclass
class RenderContext:
    """Versioned, complete inputs required to paint a billboard."""

    version: int = RENDER_CONTEXT_VERSION

    # --- Copy / identity ---
    company_name: str = ""
    headline: str = ""
    cta: str = ""
    subtitle: str = ""
    template: str = "contractor"

    # --- Assets (prefer project-local paths after ingest) ---
    logo_image: str = ""
    hero_image: str = ""
    background_image: str = ""

    # --- Theme (resolved at generation; authoritative for paint) ---
    primary_color: str = "#222222"
    secondary_color: str = "#FFFFFF"
    accent_color: str = "#1F77B4"
    text_color: str = "#111111"
    button_color: str = "#FF7F0E"
    background_color: str = "#FFFFFF"

    # --- Typography / layout ---
    fonts: dict = field(default_factory=lambda: {"family": "arial.ttf"})
    layout: dict = field(
        default_factory=lambda: {
            "style": "classic",
            "canvas": dict(_DEFAULT_CANVAS),
        }
    )

    # --- Provenance ---
    quality_score: float = 0.0
    source_url: str = ""
    brand_colors: list = field(default_factory=list)
    scene_template: str = "cart_corral"
    opportunity_context: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_brand_profile(
        cls,
        profile: Any,  # BrandProfile (lazy import to avoid circular deps)
        *,
        template: str = "contractor",
    ) -> "RenderContext":
        """Build a RenderContext from a BrandProfile.

        Maps business/brand intelligence into the paint/render contract.
        This is the preferred path when a BrandProfile is available.
        """
        # Lazy import to avoid circular dependency at module level
        from engine.brand_profile import BrandProfile as _BP

        if not isinstance(profile, _BP):
            raise TypeError(f"Expected BrandProfile, got {type(profile).__name__}")

        template_name = template or "contractor"
        theme = _theme_from_template(template_name)

        # --- Logo path ---
        logo_path = ""
        if profile.logo is not None:
            logo_path = profile.logo.path
        if not logo_path:
            # Fallback to legacy path stored in source_metadata
            logo_path = str(
                profile.source_metadata.get("legacy_logo_path") or ""
            )

        # --- Hero / background paths ---
        hero_path, background_path, asset_selection_diagnostics = _select_visual_assets(profile)

        # --- Colors ---
        brand_colors = list(profile.colors)

        # secondary_color: background, or second brand color if present.
        secondary = theme.get("background_color") or "#FFFFFF"
        if len(brand_colors) >= 2 and brand_colors[1]:
            secondary = str(brand_colors[1])

        primary = theme.get("primary_color") or "#222222"

        cta = theme.get("cta_text") or "Learn More"
        font_family = theme.get("font_family") or "arial.ttf"
        layout_style = theme.get("layout_style") or "classic"

        # --- Subtitle from metadata ---
        subtitle = profile.source_metadata.get("description") or ""
        if subtitle and subtitle == profile.headline:
            subtitle = ""

        return cls(
            version=RENDER_CONTEXT_VERSION,
            company_name=str(profile.company_name or ""),
            headline=str(profile.ad_copy or profile.headline or ""),
            cta=str(cta or ""),
            subtitle=str(subtitle or ""),
            template=template_name,
            logo_image=str(logo_path or ""),
            hero_image=str(hero_path or ""),
            background_image=str(background_path or hero_path or ""),
            primary_color=str(primary),
            secondary_color=str(secondary),
            accent_color=str(theme.get("accent_color") or "#1F77B4"),
            text_color=str(theme.get("text_color") or "#111111"),
            button_color=str(theme.get("button_color") or "#FF7F0E"),
            background_color=str(theme.get("background_color") or "#FFFFFF"),
            fonts={"family": str(font_family)},
            layout={
                "style": str(layout_style),
                "canvas": dict(_DEFAULT_CANVAS),
            },
            quality_score=float(profile.quality_score or 0),
            source_url=str(profile.website or ""),
            brand_colors=[str(c) for c in brand_colors],
            scene_template="cart_corral",
            opportunity_context={"asset_selection": asset_selection_diagnostics},
        )

    @classmethod
    def from_scrape(
        cls,
        scrape_data: dict[str, Any],
        *,
        template: str = "contractor",
        source_url: str = "",
    ) -> "RenderContext":
        """Build a complete contract from scraper output + template theme.

        Internally creates a BrandProfile and delegates to from_brand_profile()
        to avoid maintaining two separate mappings.
        """
        from engine.brand_profile import BrandProfileBuilder

        profile = BrandProfileBuilder.from_scrape_data(scrape_data)
        return cls.from_brand_profile(profile, template=template)


    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RenderContext":
        """Deserialize, migrating legacy (Phase A) partial contexts."""
        if not data:
            return cls()
        raw = dict(data)
        version = int(raw.get("version") or 0)

        # --- Legacy key migration (v0 / Phase A) ---
        if "company_name" not in raw and "company" in raw:
            raw["company_name"] = raw.get("company") or ""
        if "logo_image" not in raw:
            raw["logo_image"] = raw.get("logo_path") or ""
        if "hero_image" not in raw:
            raw["hero_image"] = (
                raw.get("hero_path")
                or raw.get("screenshot_path")
                or ""
            )
        if "background_image" not in raw:
            raw["background_image"] = raw.get("screenshot_path") or raw.get(
                "hero_image"
            ) or ""

        template = raw.get("template") or "contractor"
        theme = _theme_from_template(str(template))

        # Fill missing theme from template defaults.
        def _color(key: str, theme_key: str, fallback: str) -> str:
            val = raw.get(key)
            if val:
                return str(val)
            return str(theme.get(theme_key) or fallback)

        fonts_raw = raw.get("fonts")
        fonts: dict[str, Any] = fonts_raw if isinstance(fonts_raw, dict) else {}
        if not fonts.get("family"):
            fonts = {
                **fonts,
                "family": theme.get("font_family") or "arial.ttf",
            }

        layout_raw = raw.get("layout")
        layout: dict[str, Any] = layout_raw if isinstance(layout_raw, dict) else {}
        style = layout.get("style") or theme.get("layout_style") or "classic"
        canvas_raw = layout.get("canvas")
        canvas: dict[str, Any] = canvas_raw if isinstance(canvas_raw, dict) else {}
        canvas = {
            "width": int(canvas.get("width") or _DEFAULT_CANVAS["width"]),
            "height": int(canvas.get("height") or _DEFAULT_CANVAS["height"]),
        }

        cta = raw.get("cta") or theme.get("cta_text") or "Learn More"

        # subtitle from legacy metadata
        subtitle = raw.get("subtitle") or ""
        meta_raw = raw.get("metadata")
        if not subtitle and isinstance(meta_raw, dict):
            subtitle = meta_raw.get("description") or ""

        brand_colors = raw.get("brand_colors") or []
        if not isinstance(brand_colors, list):
            brand_colors = []
        opportunity_raw = raw.get("opportunity_context")
        if isinstance(opportunity_raw, dict):
            opportunity_context = dict(opportunity_raw)
            opportunity_context.update(
                OpportunityGenerationContext.from_dict(opportunity_raw).to_dict()
            )
        else:
            opportunity_context = {}

        secondary = raw.get("secondary_color") or theme.get("background_color") or "#FFFFFF"


        return cls(
            version=RENDER_CONTEXT_VERSION if version < 1 else version,
            company_name=str(raw.get("company_name") or ""),
            headline=str(raw.get("headline") or ""),
            cta=str(cta or ""),
            subtitle=str(subtitle or ""),
            template=str(template),
            logo_image=str(raw.get("logo_image") or ""),
            hero_image=str(raw.get("hero_image") or ""),
            background_image=str(raw.get("background_image") or ""),
            primary_color=_color("primary_color", "primary_color", "#222222"),
            secondary_color=str(secondary),
            accent_color=_color("accent_color", "accent_color", "#1F77B4"),
            text_color=_color("text_color", "text_color", "#111111"),
            button_color=_color("button_color", "button_color", "#FF7F0E"),
            background_color=_color("background_color", "background_color", "#FFFFFF"),
            fonts={"family": str(fonts.get("family") or "arial.ttf")},
            layout={"style": str(style), "canvas": canvas},
            quality_score=float(raw.get("quality_score") or 0),
            source_url=str(raw.get("source_url") or ""),
            brand_colors=[str(c) for c in brand_colors],
            scene_template=str(raw.get("scene_template") or "cart_corral"),
            opportunity_context=opportunity_context,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for project.json."""
        data = asdict(self)
        data["version"] = RENDER_CONTEXT_VERSION
        return data

    def merge_overrides(self, **overrides: Any) -> "RenderContext":
        """Return a copy with concept-level field overrides applied.

        Supported override keys (GUI-facing and contract names):
        headline, cta, company_name, company, template, logo_image, logo_path,
        hero_image, subtitle.
        """
        ctx = RenderContext.from_dict(self.to_dict())
        mapping = {
            "headline": "headline",
            "cta": "cta",
            "company_name": "company_name",
            "company": "company_name",
            "template": "template",
            "logo_image": "logo_image",
            "logo_path": "logo_image",
            "hero_image": "hero_image",
            "subtitle": "subtitle",
        }
        template_changed = False
        for key, value in overrides.items():
            attr = mapping.get(key)
            if attr is None or value is None:
                continue
            if attr == "template" and str(value) != ctx.template:
                template_changed = True
            setattr(ctx, attr, value if not isinstance(value, str) else value)

        if template_changed:
            ctx.apply_template_theme(ctx.template, preserve_user_cta=bool(overrides.get("cta")))
        return ctx

    def apply_template_theme(self, template: str, *, preserve_user_cta: bool = False) -> None:
        """Re-resolve colors/fonts/layout from a template module in-place."""
        template_name = template or "contractor"
        theme = _theme_from_template(template_name)
        self.template = template_name
        self.primary_color = str(theme.get("primary_color") or self.primary_color)
        self.secondary_color = str(theme.get("background_color") or self.secondary_color)
        self.accent_color = str(theme.get("accent_color") or self.accent_color)
        self.text_color = str(theme.get("text_color") or self.text_color)
        self.button_color = str(theme.get("button_color") or self.button_color)
        self.background_color = str(theme.get("background_color") or self.background_color)
        self.fonts = {"family": str(theme.get("font_family") or "arial.ttf")}
        layout = self.layout if isinstance(self.layout, dict) else {}
        canvas_raw = layout.get("canvas")
        canvas: dict[str, Any] = canvas_raw if isinstance(canvas_raw, dict) else dict(_DEFAULT_CANVAS)
        self.layout = {
            "style": str(theme.get("layout_style") or "classic"),
            "canvas": {
                "width": int(canvas.get("width") or 1600),
                "height": int(canvas.get("height") or 900),
            },
        }
        if not preserve_user_cta:
            self.cta = str(theme.get("cta_text") or self.cta or "Learn More")


    def to_render_spec(self) -> dict[str, Any]:
        """Map this contract to the dict :func:`render_billboard` understands.

        This is the only adapter between the stable contract and the renderer.
        No scrape keys are required.
        """
        layout = self.layout if isinstance(self.layout, dict) else {}
        canvas_raw = layout.get("canvas")
        canvas: dict[str, Any] = canvas_raw if isinstance(canvas_raw, dict) else {}
        fonts = self.fonts if isinstance(self.fonts, dict) else {}
        hero = self.hero_image or self.background_image or ""
        return {
            "template": self.template or "contractor",
            "selected_template": self.template or "contractor",
            "scene_template": self.scene_template or "cart_corral",
            "canvas": {
                "width": int(canvas.get("width") or 1600),
                "height": int(canvas.get("height") or 900),
            },
            "background_color": self.background_color or "#FFFFFF",
            "primary_color": self.primary_color or "#222222",
            "accent_color": self.accent_color or "#1F77B4",
            "text_color": self.text_color or "#111111",
            "button_color": self.button_color or "#FF7F0E",
            "font_family": fonts.get("family") or "arial.ttf",
            "layout_style": layout.get("style") or "classic",
            "cta_text": self.cta or "Learn More",
            "company": self.company_name or "Brand",
            "headline": self.headline or "Make your message unforgettable",
            "subtitle": self.subtitle or "",
            "logo_path": self.logo_image or "",
            "hero_path": hero,
            "brand_colors": list(self.brand_colors or []),
            "source_url": self.source_url or "",
            "opportunity_context": dict(self.opportunity_context or {}),
        }



    def with_asset_paths(
        self,
        *,
        logo_image: str | None = None,
        hero_image: str | None = None,
        background_image: str | None = None,
    ) -> "RenderContext":
        """Return a copy with rewritten asset paths (after project ingest)."""
        ctx = RenderContext.from_dict(self.to_dict())
        if logo_image is not None:
            ctx.logo_image = logo_image
        if hero_image is not None:
            ctx.hero_image = hero_image
        if background_image is not None:
            ctx.background_image = background_image
        return ctx


def ensure_render_context(data: dict[str, Any] | RenderContext | None) -> RenderContext:
    """Normalize dict or instance to :class:`RenderContext`."""
    if isinstance(data, RenderContext):
        return data
    return RenderContext.from_dict(data if isinstance(data, dict) else {})


def merge_context_dict(base: dict[str, Any] | None, **overrides: Any) -> dict[str, Any]:
    """Merge overrides into a context dict; return a plain dict (v1)."""
    ctx = ensure_render_context(base).merge_overrides(**overrides)
    return ctx.to_dict()
