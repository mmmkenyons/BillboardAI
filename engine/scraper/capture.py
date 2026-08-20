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
    def __init__(self, message: str, quality: Optional[ScreenshotQuality] = None, diagnostics: Optional[dict[str, Any]] = None):
        self.quality = quality
        self.diagnostics = dict(diagnostics or {})
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
        self._active_path = path

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
            ("viewport_fallback", self._capture_viewport_fallback),
            ("delayed_viewport_fallback", self._capture_delayed_viewport_fallback),
        ]
        diagnostics: dict[str, Any] = {"attempts": [], "max_attempts": len(strategies)}
        last_quality: Optional[ScreenshotQuality] = None

        for i, (name, strategy) in enumerate(strategies):
            try:
                logger.info("Capture strategy=%s (attempt %d)", name, i + 1)
                strategy(page)
                quality = validate_screenshot(path)
                last_quality = quality
                diagnostics["attempts"].append({"strategy": name, "valid": bool(quality.valid), "reason": quality.reason or "", "score": quality.score})
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
                raise ScreenshotValidationError(f"Screenshot validation failed after {len(strategies)} attempts. Reason: {quality.reason or 'unknown'}", quality, diagnostics)
            except ScreenshotValidationError:
                raise
            except Exception as e:
                diagnostics["attempts"].append({"strategy": name, "exception": str(e)[:160]})
                if i == len(strategies) - 1:
                    raise ScreenshotValidationError(f"Capture failed: {e}", last_quality, diagnostics) from e
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

    def _capture_viewport_fallback(self, page: Page) -> None:
        """Bounded fallback: capture only the initial viewport.

        Some sites produce blank/low-information full-page screenshots due to
        sticky overlays or huge lazy regions.  This keeps validation unchanged
        and tries a smaller rendered region instead.
        """
        effective_url = page.url or self.url
        if not effective_url:
            raise ValueError("ScreenshotCaptureService._capture_viewport_fallback(): no URL available")
        logger.info("Capture strategy=viewport_fallback url=%s", effective_url)
        page.goto(effective_url, wait_until="domcontentloaded", timeout=config.TIMEOUT)
        time.sleep(1)
        page.screenshot(path=self._get_path(), full_page=False)

    def _capture_delayed_viewport_fallback(self, page: Page) -> None:
        """Bounded fallback: short delayed viewport capture after load."""
        effective_url = page.url or self.url
        if not effective_url:
            raise ValueError("ScreenshotCaptureService._capture_delayed_viewport_fallback(): no URL available")
        logger.info("Capture strategy=delayed_viewport_fallback url=%s", effective_url)
        page.goto(effective_url, wait_until="load", timeout=config.TIMEOUT)
        time.sleep(3)
        page.screenshot(path=self._get_path(), full_page=False)

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
        return getattr(self, "_active_path", str(Path(config.ASSETS_FOLDER) / f"{self.filename_base}_screenshot.png"))

    # Placeholder for url (set by scraper)
    url: Optional[str] = None


# Convenience
def capture_screenshot(page: Page, filename_base: str = "screenshot") -> ScreenshotResult:
    """Convenience for service."""
    service = ScreenshotCaptureService(filename_base)
    service.url = page.url  # Set from live page object
    logger.info("Screenshot requested_url=%s", service.url)
    return service.capture(page)
