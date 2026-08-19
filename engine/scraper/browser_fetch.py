"""Bounded browser-backed HTML fetch helper for public pages.

Reuses BillboardAI's existing Playwright conventions (headless Chromium,
configured USER_AGENT, and TIMEOUT-based navigation) but returns only the final
URL and rendered HTML. This is intentionally small so other bounded discovery
workflows can consume rendered same-domain HTML without triggering screenshot or
render pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .. import config


@dataclass(frozen=True)
class BrowserHtmlResult:
    final_url: str
    html: str


def fetch_rendered_html(url: str) -> BrowserHtmlResult:
    """Fetch one public page with Playwright and return final URL + HTML.

    Uses the same launch, user-agent, and resilient navigation behavior as the
    existing WebsiteScraper browser path, but does not capture screenshots or
    perform any asset/render processing.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=config.USER_AGENT)
        try:
            try:
                page.goto(url, wait_until="networkidle", timeout=config.TIMEOUT)
            except PlaywrightTimeoutError:
                page.goto(url, wait_until="domcontentloaded", timeout=config.TIMEOUT)
                page.wait_for_timeout(2500)
            return BrowserHtmlResult(final_url=page.url or url, html=page.content() or "")
        except PlaywrightError:
            raise
        finally:
            browser.close()