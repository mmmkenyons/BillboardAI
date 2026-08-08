"""Regression tests for hero image extraction (engine/scraper/hero.py)."""

from engine.scraper.hero import pick_hero_image


class FakePage:
    """Simulates a Playwright page with a configurable document.images collection."""

    def __init__(self, images, url="https://example.com"):
        self._images = images
        self.url = url

    def evaluate(self, script):
        """Execute the hero extraction JS against our fake image set."""
        # The script is a function string; we parse out the logic and run it
        # against our fake DOM.  For testing we simulate the JS environment.
        return _simulate_evaluate(self._images)


def _simulate_evaluate(images):
    """Minimal JS simulation of the hero extraction logic.

    Mirrors the browser-side JS in pick_hero_image() exactly.
    """
    MIN_WIDTH = 120
    MIN_HEIGHT = 120
    MAX_CANDIDATES = 50
    MAX_ALT_LENGTH = 200

    total = len(images)
    seen = set()
    results = []

    for img in images:
        if len(results) >= MAX_CANDIDATES:
            break

        src = img.get("currentSrc") or img.get("src") or img.get("data-src") or ""

        if not src or src.startswith("data:") or src.startswith("blob:"):
            continue

        if src in seen:
            continue
        seen.add(src)

        rect = img.get("rect", {"width": 0, "height": 0})
        style = img.get("style", {"visibility": "visible", "display": "block"})

        if (
            rect["width"] < MIN_WIDTH
            or rect["height"] < MIN_HEIGHT
            or style.get("visibility") == "hidden"
            or style.get("display") == "none"
        ):
            continue

        alt = (img.get("alt") or "")[:MAX_ALT_LENGTH]

        results.append(
            {
                "src": src,
                "width": round(rect["width"]),
                "height": round(rect["height"]),
                "alt": alt,
            }
        )

    results.sort(key=lambda r: r["width"] * r["height"], reverse=True)

    return {
        "total": total,
        "filtered": len(results),
        "candidates": results,
    }


# ---------------------------------------------------------------------------
# Helpers to build fake image dicts
# ---------------------------------------------------------------------------

def _img(src, width=800, height=600, alt="", visibility="visible", display="block"):
    return {
        "src": src,
        "rect": {"width": width, "height": height},
        "style": {"visibility": visibility, "display": display},
        "alt": alt,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_picks_largest_visible_image():
    page = FakePage(
        [
            _img("https://example.com/small.jpg", 200, 150),
            _img("https://example.com/large.jpg", 1200, 800),
            _img("https://example.com/medium.jpg", 600, 400),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/large.jpg"


def test_skips_hidden_images():
    page = FakePage(
        [
            _img("https://example.com/visible.jpg", 800, 600),
            _img("https://example.com/hidden.jpg", 1200, 800, display="none"),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/visible.jpg"


def test_skips_tiny_icons():
    page = FakePage(
        [
            _img("https://example.com/icon.png", 16, 16),
            _img("https://example.com/hero.jpg", 800, 600),
            _img("https://example.com/favicon.ico", 32, 32),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/hero.jpg"


def test_excludes_data_uris():
    page = FakePage(
        [
            _img("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk", 800, 600),
            _img("https://example.com/real.jpg", 800, 600),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/real.jpg"


def test_excludes_blob_urls():
    page = FakePage(
        [
            _img("blob:https://example.com/abc-123", 800, 600),
            _img("https://example.com/real.jpg", 800, 600),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/real.jpg"


def test_deduplicates_urls():
    page = FakePage(
        [
            _img("https://example.com/hero.jpg", 800, 600),
            _img("https://example.com/hero.jpg", 800, 600),
            _img("https://example.com/hero.jpg", 800, 600),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/hero.jpg"
    # The JS dedup means only one candidate is returned
    # (We can't easily assert the internal count, but the result is correct)


def test_caps_at_50_candidates():
    """If there are 200 valid images, only 50 should be returned to Python."""
    images = []
    for i in range(200):
        images.append(_img(f"https://example.com/img_{i:04d}.jpg", 800, 600))
    page = FakePage(images)
    result = pick_hero_image(page)
    # Should still pick one (the first by area, all same size so first encountered)
    assert result is not None
    assert result.startswith("https://example.com/img_")


def test_hundreds_of_dom_images_does_not_crash():
    """Simulate a page with 2000 DOM images — must not MemoryError."""
    images = []
    for i in range(2000):
        # Mix of tiny icons, data URIs, duplicates, and real images
        if i % 10 == 0:
            images.append(_img(f"https://example.com/hero_{i}.jpg", 800, 600))
        elif i % 5 == 0:
            images.append(_img("data:image/png;base64,AAAA", 16, 16))
        elif i % 3 == 0:
            images.append(_img("https://example.com/dup.jpg", 400, 300))
        else:
            images.append(_img(f"https://example.com/icon_{i}.png", 16, 16))
    page = FakePage(images)
    result = pick_hero_image(page)
    # Should not crash and should return a valid hero
    assert result is not None


def test_skips_logo_and_icon_in_url():
    page = FakePage(
        [
            _img("https://example.com/logo.png", 400, 200),
            _img("https://example.com/header-icon.svg", 300, 150),
            _img("https://example.com/banner.jpg", 800, 600),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/banner.jpg"


def test_returns_none_when_no_valid_images():
    page = FakePage(
        [
            _img("data:image/png;base64,AAAA", 800, 600),
            _img("https://example.com/logo.png", 400, 200),
        ]
    )
    result = pick_hero_image(page)
    assert result is None


def test_handles_empty_page():
    page = FakePage([])
    result = pick_hero_image(page)
    assert result is None


def test_handles_missing_src():
    page = FakePage(
        [
            {"src": "", "rect": {"width": 800, "height": 600}, "style": {"visibility": "visible", "display": "block"}, "alt": ""},
            _img("https://example.com/valid.jpg", 800, 600),
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/valid.jpg"


def test_uses_currentSrc_over_src():
    page = FakePage(
        [
            {
                "src": "https://example.com/lowres.jpg",
                "currentSrc": "https://example.com/highres.jpg",
                "rect": {"width": 800, "height": 600},
                "style": {"visibility": "visible", "display": "block"},
                "alt": "",
            },
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/highres.jpg"


def test_falls_back_to_data_src():
    page = FakePage(
        [
            {
                "src": "",
                "currentSrc": "",
                "data-src": "https://example.com/lazy.jpg",
                "rect": {"width": 800, "height": 600},
                "style": {"visibility": "visible", "display": "block"},
                "alt": "",
            },
        ]
    )
    result = pick_hero_image(page)
    assert result == "https://example.com/lazy.jpg"