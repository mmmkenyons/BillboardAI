"""Hero image selection for BillboardAI scraper."""

import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# Maximum number of lightweight candidates returned from the browser.
# Protects against MemoryError on pages with thousands of DOM images.
_MAX_CANDIDATES = 50

# Minimum rendered dimensions (px) for a candidate to be considered.
_MIN_WIDTH = 120
_MIN_HEIGHT = 120

# Maximum length for alt text returned to Python (defensive truncation).
_MAX_ALT_LENGTH = 200


def _normalize_url(base_url, src):
    if not src:
        return None
    return urljoin(base_url, src.strip())


def pick_hero_image(page):
    """Select the best hero image from the page.

    Filtering happens inside the browser to avoid transferring
    enormous data URIs or thousands of tiny-icon records across
    the Playwright protocol boundary.
    """
    candidates = page.evaluate(
        """() => {
        const MIN_WIDTH = 120;
        const MIN_HEIGHT = 120;
        const MAX_CANDIDATES = 50;
        const MAX_ALT_LENGTH = 200;

        const total = document.images.length;
        const seen = new Set();
        const results = [];

        for (let i = 0; i < document.images.length && results.length < MAX_CANDIDATES; i++) {
            const img = document.images[i];
            const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';

            // Skip empty, data: URIs, and blob: URLs
            if (!src || src.startsWith('data:') || src.startsWith('blob:')) {
                continue;
            }

            // Deduplicate by URL
            if (seen.has(src)) {
                continue;
            }
            seen.add(src);

            const rect = img.getBoundingClientRect();
            const style = window.getComputedStyle(img);

            // Skip hidden or tiny images
            if (
                rect.width < MIN_WIDTH ||
                rect.height < MIN_HEIGHT ||
                style.visibility === 'hidden' ||
                style.display === 'none'
            ) {
                continue;
            }

            const alt = (img.alt || '').substring(0, MAX_ALT_LENGTH);

            results.push({
                src: src,
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                alt: alt,
            });
        }

        // Sort by area descending so the largest candidates come first
        results.sort((a, b) => (b.width * b.height) - (a.width * a.height));

        return {
            total: total,
            filtered: results.length,
            candidates: results,
        };
    }"""
    )

    total = candidates.get("total", 0)
    filtered = candidates.get("filtered", 0)
    results = candidates.get("candidates", [])

    logger.info(
        "Hero extraction: document.images=%d  filtered=%d  returned=%d",
        total,
        filtered,
        len(results),
    )

    for candidate in results:
        src = candidate.get("src", "")
        if src and "logo" not in src.lower() and "icon" not in src.lower():
            return _normalize_url(page.url, src)

    return None
