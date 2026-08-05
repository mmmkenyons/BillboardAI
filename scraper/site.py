"""Root scraper.site compatibility wrapper."""

import engine.scraper.site as _site

WebsiteScraper = _site.WebsiteScraper
sync_playwright = _site.sync_playwright
pick_hero_image = _site.pick_hero_image
discover_assets = _site.discover_assets
extract_headline = _site.extract_headline
extract_metadata = _site.extract_metadata
pick_best_logo = _site.pick_best_logo
render_billboard = _site.render_billboard

__all__ = [
    "WebsiteScraper",
    "sync_playwright",
    "pick_hero_image",
    "discover_assets",
    "extract_headline",
    "extract_metadata",
    "pick_best_logo",
    "render_billboard",
]
