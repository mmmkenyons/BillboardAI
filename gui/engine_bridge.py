"""Boundary between the GUI and the existing engine.

The GUI never calls engine modules directly; it goes through this bridge.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

from engine.scraper.site import WebsiteScraper

from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, str | None], None]


def generate(
    request: MockupRequest,
    progress_callback: ProgressCallback | None = None,
) -> MockupResult:
    """Generate a mockup for the given request.

    Translates a :class:`MockupRequest` into the engine's parameters, runs
    the existing pipeline, and converts the output into a
    :class:`MockupResult`.
    """
    start = time.time()
    result = MockupResult(website=request.url)

    def _report(percent: int, message: str, stage: str | None = None) -> None:
        if progress_callback:
            progress_callback(percent, message, stage)

    try:
        logger.info("Starting generation for %s", request.url)
        _report(0, "Starting...", "start")

        scraper = WebsiteScraper(request.url)
        data = scraper.run(progress_callback=progress_callback)

        # Render into the user's chosen output folder.
        os.makedirs(request.output_folder, exist_ok=True)
        output_path = os.path.join(
            request.output_folder,
            f"{scraper.filename_base}_{request.template}.png",
        )
        rendered_path = scraper.render_billboard(
            request.template, output_path, progress_callback=progress_callback
        )

        # Populate as many fields as the engine provides.
        result.success = True
        result.message = "Mockup generated successfully."
        result.company_name = data.get("company", "")
        result.headline = data.get("ad_copy") or data.get("headline", "")
        result.quality_score = float(data.get("quality_score", 0) or 0)
        result.logo_path = data.get("logo_path", "") or ""
        result.preview_path = rendered_path
        result.output_path = rendered_path
        # cta is left blank: the engine does not expose the CTA text in its
        # returned data. upload_url is also left blank: this flow does not upload.
        logger.info("Generation finished: %s", rendered_path)
    except Exception as exc:  # noqa: BLE001 - never crash the GUI
        logger.exception("Generation failed")
        result.success = False
        result.message = f"Generation failed: {exc}"
        result.warnings.append(str(exc))

    result.elapsed_time = time.time() - start
    return result