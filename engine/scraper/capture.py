"""Dedicated ScreenshotCaptureService for robust capture, retry, validation.

Per sprint plan: separates concerns from WebsiteScraper orchestration.
Uses pluggable validators, 3-tier retry strategies, debug rejected saves.
Returns ScreenshotResult or raises ScreenshotValidationError.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional

from playwright.sync_api import Page
import time

from .. import config
from .validators import ScreenshotQuality, validate_screenshot

logger = logging.getLogger(__name__)


class ScreenshotValidationError(Exception):
    """Raised when screenshot fails validation after retries."""
    def __init__(self, message: str, quality: Optional[ScreenshotQuality] = None):
        self.quality = quality
        super().__init__(message)


@dataclass
class ScreenshotResult:
    """Result from capture service (success path only)."""
    path: str
    quality: ScreenshotQuality
    strategy_used: str
    retries: int = 0


class ScreenshotCaptureService:
    """Service for Playwright screenshot with retry, validation, diagnostics."""

    def __init__(self, filename_base: str = "screenshot"):
        self.filename_base = filename_base
        self.debug = config.DEBUG

    def capture(self, page: Page, output_dir: str | None = None) -> ScreenshotResult:
        """Main entry: try strategies until valid or raise."""
        if output_dir is None:
            output_dir = config.ASSETS_FOLDER
        if not isinstance(output_dir, str):
            raise ValueError("output_dir must be a string path")

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        path = str(Path(output_dir) / f"{self.filename_base}_screenshot.png")

        # Resolve the URL to capture from the live page object
        effective_url = page.url or self.url
        if not effective_url:
            raise ValueError("ScreenshotCaptureService.capture(): no URL available — page.url is empty and service.url was not set")

        logger.info("Capture input url=%s", effective_url)
        logger.info("Capture current page.url=%s", page.url)
        logger.info("Capture strategy=networkidle (attempt 1)")

        strategies = [
            ("networkidle", lambda p: (p.goto(effective_url, wait_until="networkidle", timeout=config.TIMEOUT), p.screenshot(path=path, full_page=True))[1]),
            ("load_fonts", self._capture_with_load_and_fonts),
            ("scroll", self._capture_with_scroll),
        ]

        for i, (name, strategy) in enumerate(strategies):
            try:
                logger.info("Capture strategy=%s (attempt %d)", name, i + 1)
                strategy(page)
                quality = validate_screenshot(path)
                if quality.valid:
                    return ScreenshotResult(
                        path=path,
                        quality=quality,
                        strategy_used=name,
                        retries=i,
                    )
                if self.debug:
                    print(f"[DEBUG] Strategy '{name}' produced invalid screenshot (reason: {quality.reason}, score: {quality.score})")
                if i < len(strategies) - 1:
                    time.sleep(1)  # Backoff
                    continue
                raise ScreenshotValidationError(f"Screenshot validation failed after {len(strategies)} attempts. Reason: {quality.reason or 'unknown'}", quality)
            except Exception as e:
                if i == len(strategies) - 1:
                    raise ScreenshotValidationError(f"Capture failed: {e}") from e
                continue

        raise ScreenshotValidationError("Unexpected capture failure")

    def _capture_with_load_and_fonts(self, page: Page) -> None:
        """Strategy 2: load + fonts.ready + sleep."""
        effective_url = page.url or self.url
        if not effective_url:
            raise ValueError("ScreenshotCaptureService._capture_with_load_and_fonts(): no URL available")
        logger.info("Capture strategy=load_fonts url=%s", effective_url)
        page.goto(effective_url, wait_until="load", timeout=config.TIMEOUT)
        page.evaluate("() => document.fonts.ready")
        time.sleep(2)
        page.screenshot(path=self._get_path(), full_page=True)

    def _capture_with_scroll(self, page: Page) -> None:
        """Strategy 3: scroll to trigger lazy JS renders."""
        effective_url = page.url or self.url
        if not effective_url:
            raise ValueError("ScreenshotCaptureService._capture_with_scroll(): no URL available")
        logger.info("Capture strategy=scroll url=%s", effective_url)
        page.goto(effective_url, wait_until="load", timeout=config.TIMEOUT)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        time.sleep(1.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        page.screenshot(path=self._get_path(), full_page=True)

    def _get_path(self) -> str:
        """Helper for path (updated in capture)."""
        return str(Path(config.ASSETS_FOLDER) / f"{self.filename_base}_screenshot.png")

    # Placeholder for url (set by scraper)
    url: Optional[str] = None


# Convenience
def capture_screenshot(page: Page, filename_base: str = "screenshot") -> ScreenshotResult:
    """Convenience for service."""
    service = ScreenshotCaptureService(filename_base)
    service.url = page.url  # Set from live page object
    logger.info("Screenshot requested_url=%s", service.url)
    return service.capture(page)
