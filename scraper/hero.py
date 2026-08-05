"""Hero image selection for BillboardAI scraper."""

from urllib.parse import urljoin


def _normalize_url(base_url, src):
    if not src:
        return None
    return urljoin(base_url, src.strip())


def pick_hero_image(page):
    images = page.evaluate(
        "() => Array.from(document.images).map(img => {"
        " const rect = img.getBoundingClientRect();"
        " const style = window.getComputedStyle(img);"
        " return {"
        " src: img.currentSrc || img.src || img.getAttribute('data-src') || '',"
        " width: rect.width,"
        " height: rect.height,"
        " visible: rect.width > 120 && rect.height > 120 && style.visibility !== 'hidden' && style.display !== 'none'"
        " };"
        "})"
    )

    visible_images = [img for img in images if img.get("visible") and img.get("src")]
    visible_images.sort(key=lambda item: item.get("width", 0) * item.get("height", 0), reverse=True)

    for image in visible_images:
        src = image.get("src")
        if src and "logo" not in src.lower() and "icon" not in src.lower():
            return _normalize_url(page.url, src)

    return None
