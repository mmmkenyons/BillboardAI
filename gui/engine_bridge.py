"""Boundary between the GUI and the existing engine.

The GUI never calls engine modules directly; it goes through this bridge.

**Ownership rule (Sprint 4B):** the controller is the only component allowed
to create or own a :class:`~gui.models.project.Project`. This bridge never
creates project directories or ``Project`` objects — it only produces assets
at paths supplied by the caller.

**Render contract (Phase A.5):** local paint uses a complete
``render_context`` only — no scrape-shaped dicts on the re-render path.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from engine.ad_concept import AdConceptEngine
from engine.brand_profile import BrandProfileBuilder
from engine.message_strategy import MessageStrategyEngine
from engine.renderer.renderer import get_last_render_quality, render_billboard
from engine.scraper.site import WebsiteScraper, ScreenshotValidationError

from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.models.render_context import RenderContext, ensure_render_context


logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, str | None], None]


def _apply_opportunity_context(ctx: RenderContext, request: MockupRequest) -> RenderContext:
    opportunity = request.opportunity_context
    if opportunity is None:
        return ctx
    merged = RenderContext.from_dict(ctx.to_dict())
    merged.scene_template = opportunity.scene_template or merged.scene_template or "cart_corral"
    existing = dict(merged.opportunity_context or {})
    merged.opportunity_context = {**opportunity.to_dict(), **existing}
    return merged


def _creative_city_from_request(request: MockupRequest) -> str:
    opportunity = request.opportunity_context
    if opportunity is None:
        return ""
    return " ".join(str(opportunity.city or "").split()).strip()


def _apply_localized_creative(ctx: RenderContext, data: dict[str, Any], request: MockupRequest) -> RenderContext:
    """Optionally refine headline/CTA through the existing message strategy seam."""
    creative_city = _creative_city_from_request(request)
    if not creative_city:
        return ctx

    profile = BrandProfileBuilder.from_scrape_data(data if isinstance(data, dict) else {})
    strategies = MessageStrategyEngine().generate(profile, creative_locality=creative_city)
    if not strategies:
        return ctx
    concepts = AdConceptEngine().generate(profile, strategies)
    if not concepts:
        return ctx
    best = max(concepts, key=lambda concept: concept.score)
    merged = RenderContext.from_dict(ctx.to_dict())
    if (best.headline or "").strip():
        merged.headline = best.headline
    if (best.cta or "").strip():
        merged.cta = best.cta
    return merged


def _report(
    progress_callback: ProgressCallback | None,
    percent: int,
    message: str,
    stage: str | None = None,
) -> None:
    if progress_callback:
        progress_callback(percent, message, stage)


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory of ``path`` if needed."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def build_render_context(
    data: dict[str, Any],
    *,
    template: str = "contractor",
    source_url: str = "",
) -> dict[str, Any]:
    """Build a **complete** v1 render_context dict from scraper data + template.

    Paths may still point at engine cache locations; the controller copies
    assets into the project and rewrites ``logo_image`` / ``hero_image``.
    """
    ctx = RenderContext.from_scrape(
        data,
        template=template or "contractor",
        source_url=source_url,
    )
    return ctx.to_dict()


def build_brand_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Build the existing serializable BrandProfile snapshot from scraper data."""
    return BrandProfileBuilder.from_scrape_data(data if isinstance(data, dict) else {}).to_dict()


def render_from_context(
    context: dict[str, Any] | RenderContext,
    output_path: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Paint a billboard using **only** the render_context contract.

    No Playwright. No WebsiteScraper. No AI.
    """
    if not output_path:
        raise ValueError("output_path is required for render_from_context")

    ctx = ensure_render_context(context)
    _report(progress_callback, 40, "Building design spec...", "design")
    spec = ctx.to_render_spec()

    _ensure_parent_dir(output_path)

    _report(progress_callback, 70, "Rendering mockup...", "render")
    return render_billboard(spec, output_path)


def generate(
    request: MockupRequest,
    progress_callback: ProgressCallback | None = None,
) -> MockupResult:
    """Generate a mockup for the given request.

    The caller **must** supply :attr:`MockupRequest.output_path`. This
    function never creates a Project — it scrapes, builds a full
    render_context, and writes the PNG to the supplied path.
    """
    start = time.time()
    result = MockupResult(website=request.url)

    try:
        if not request.output_path:
            raise ValueError(
                "MockupRequest.output_path is required; "
                "the controller must supply the render destination."
            )

        logger.info("Starting generation for %s → %s", request.url, request.output_path)
        _report(progress_callback, 0, "Starting...", "start")

        scraper = WebsiteScraper(request.url)
        try:
            data = scraper.run(progress_callback=progress_callback)
        except ScreenshotValidationError as e:
            result.success = False
            result.message = f"Unable to capture a usable screenshot from this website. {str(e)}"
            result.capture_error = str(e)
            result.warnings.append("Screenshot validation failed - invalid/blank capture (uniform color or low variance). Try a different site or enable debug for diagnostics.")
            logger.warning("ScreenshotValidationError: %s", e)
            result.elapsed_time = time.time() - start
            return result

        if isinstance(data, dict) and isinstance(request.options, dict):
            person_context = request.options.get("person_context")
            if isinstance(person_context, dict) and person_context:
                data = dict(data)
                data["person_context"] = dict(person_context)

        template_name = request.template or "contractor"
        brand_profile_snapshot = build_brand_profile(data if isinstance(data, dict) else {})
        render_context = build_render_context(
            data,
            template=template_name,
            source_url=request.url,
        )
        ctx_obj = _apply_opportunity_context(
            ensure_render_context(render_context),
            request,
        )
        ctx_obj = _apply_localized_creative(ctx_obj, data if isinstance(data, dict) else {}, request)
        render_context = ctx_obj.to_dict()

        # Prefer painting from the contract (single path with re_render).
        _ensure_parent_dir(request.output_path)
        _report(progress_callback, 70, "Rendering Mockup", "render")
        rendered_path = render_from_context(
            render_context,
            request.output_path,
            progress_callback=progress_callback,
        )

        # If engine quality gate historically swapped templates, keep request
        # template as source of truth for the contract (GUI chose it).
        if isinstance(scraper.last_data, dict):
            # Merge any quality fields from analysis into context.
            render_context = dict(render_context)
            if scraper.last_data.get("quality_score") is not None:
                render_context["quality_score"] = float(
                    scraper.last_data.get("quality_score") or 0
                )
        render_quality = get_last_render_quality()
        render_context = dict(render_context)
        render_context["render_quality"] = render_quality

        ctx_obj = ensure_render_context(render_context)

        result.success = True
        result.message = "Mockup generated successfully."
        result.company_name = ctx_obj.company_name
        result.headline = ctx_obj.headline
        result.cta = ctx_obj.cta
        result.quality_score = float(ctx_obj.quality_score or 0)
        result.logo_path = ctx_obj.logo_image
        result.preview_path = rendered_path
        result.output_path = rendered_path
        result.extra = {
            "template": ctx_obj.template,
            "render_context": ctx_obj.to_dict(),
            "brand_profile": brand_profile_snapshot,
            "render_quality": render_quality,
            "hero_path": ctx_obj.hero_image,
            "screenshot_path": ctx_obj.background_image,
            "brand_colors": list(ctx_obj.brand_colors or []),
            "filename_base": getattr(scraper, "filename_base", ""),
        }
        _report(progress_callback, 100, "Complete", "done")
        logger.info("Generation finished: %s", rendered_path)
    except Exception as exc:  # noqa: BLE001 - never crash the GUI
        logger.exception("Generation failed")
        result.success = False
        result.message = f"Generation failed: {exc}"
        result.warnings.append(str(exc))

    result.elapsed_time = time.time() - start
    return result


def re_render(
    *,
    render_context: dict[str, Any],
    output_path: str,
    template: str | None = None,
    headline: str | None = None,
    cta: str | None = None,
    company: str | None = None,
    logo_path: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MockupResult:
    """Re-render from a complete render_context (+ optional concept overrides).

    **No Playwright. No WebsiteScraper. No AI.**

    Preferred call shape::

        re_render(render_context=full_ctx, output_path=path)

    Legacy keyword overrides (template/headline/cta/company/logo_path) are
    still accepted and merged into the contract before paint.
    """
    start = time.time()
    base = ensure_render_context(render_context)
    result = MockupResult(website=base.source_url or "")

    try:
        if not output_path:
            raise ValueError("output_path is required for re_render")

        overrides: dict[str, Any] = {}
        if template is not None:
            overrides["template"] = template
        if headline is not None:
            overrides["headline"] = headline
        if cta is not None:
            overrides["cta"] = cta
        if company is not None:
            overrides["company_name"] = company
        if logo_path is not None:
            overrides["logo_image"] = logo_path

        ctx = base.merge_overrides(**overrides) if overrides else base

        logger.info(
            "Local re-render → %s (template=%s)",
            output_path,
            ctx.template,
        )
        _report(progress_callback, 10, "Preparing layout...", "rerender")

        rendered_path = render_from_context(
            ctx,
            output_path,
            progress_callback=progress_callback,
        )

        result.success = True
        result.message = "Mockup re-rendered successfully."
        result.company_name = ctx.company_name
        result.headline = ctx.headline
        result.cta = ctx.cta
        result.logo_path = ctx.logo_image
        result.preview_path = rendered_path
        result.output_path = rendered_path
        result.quality_score = float(ctx.quality_score or 0)
        result.extra = {
            "template": ctx.template,
            "local_rerender": True,
            "render_context": ctx.to_dict(),
            "render_quality": get_last_render_quality(),
        }
        _report(progress_callback, 100, "Complete", "done")
        logger.info("Re-render finished: %s", rendered_path)
    except Exception as exc:  # noqa: BLE001 - never crash the GUI
        logger.exception("Re-render failed")
        result.success = False
        result.message = f"Re-render failed: {exc}"
        result.warnings.append(str(exc))

    result.elapsed_time = time.time() - start
    return result
