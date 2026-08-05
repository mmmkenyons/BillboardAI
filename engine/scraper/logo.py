"""Logo detection and scoring for BillboardAI."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


SVG_LOGO_PATTERN = re.compile(r"logo|brand|mark|identity", re.I)
DATA_URI_SVG = re.compile(r"data:image/svg\+xml", re.I)


def _normalize_url(base_url, src):
    if not src:
        return None
    return urljoin(base_url, src.strip())


def score_logo_image(img_tag, base_url):
    src = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-lazy-src") or img_tag.get("data-original") or img_tag.get("srcset")
    if not src:
        return None

    if isinstance(src, str) and DATA_URI_SVG.search(src):
        return 120, src

    if isinstance(src, str) and "," in src and img_tag.name == "img":
        src = src.split(",", 1)[0].strip().split(" ")[0]

    text = (
        str(img_tag.get("class") or "")
        + " "
        + str(img_tag.get("alt") or "")
        + " "
        + str(img_tag.get("id") or "")
        + " "
        + str(img_tag.get("title") or "")
        + " "
        + str(img_tag.get("aria-label") or "")
        + " "
        + str(src)
    ).lower()

    score = 0
    if "logo" in text:
        score += 120
    if "brand" in text or "mark" in text or "identity" in text:
        score += 60
    if "header" in text or "nav" in text:
        score += 20
    if "icon" in text:
        score += 25
    if "favicon" in text:
        score += 10
    if ".svg" in src:
        score += 45
    if ".png" in src or ".jpg" in src or ".jpeg" in src:
        score += 15
    if "hero" in text or "banner" in text or "slide" in text:
        score -= 25
    if "background" in text or "cover" in text:
        score -= 10

    width = img_tag.get("width")
    height = img_tag.get("height")
    if width and height and width.isdigit() and height.isdigit():
        score += min((int(width) * int(height)) / 5000, 50)

    return score, _normalize_url(base_url, src)


def score_svg_element(svg_tag, base_url):
    text = (
        str(svg_tag.get("class") or "")
        + " "
        + str(svg_tag.get("id") or "")
        + " "
        + str(svg_tag.get("aria-label") or "")
    )
    if SVG_LOGO_PATTERN.search(text):
        return 80, None
    return None


def pick_best_logo(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    candidates = []

    for img in soup.find_all("img"):
        result = score_logo_image(img, base_url)
        if result and result[1]:
            candidates.append(result)

    for svg in soup.find_all("svg"):
        result = score_svg_element(svg, base_url)
        if result:
            candidates.append(result)

    candidates.sort(key=lambda item: item[0], reverse=True)

    if candidates:
        top_score, top_logo = candidates[0]
        if top_score >= 50:
            return top_score, top_logo

    og_image = _normalize_url(base_url, _find_og_image(html))
    if og_image:
        return 70, og_image

    return None, None


def _find_og_image(html):
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"]
    twitter = soup.find("meta", attrs={"name": "twitter:image"})
    if twitter and twitter.get("content"):
        return twitter["content"]
    return None
