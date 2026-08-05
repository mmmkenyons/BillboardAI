"""Metadata extraction utilities for BillboardAI scraper."""

from urllib.parse import urljoin


def _normalize_url(base_url, src):
    if not src:
        return None
    return urljoin(base_url, src.strip())


def _find_meta_tag(soup, key, attr_name="property"):
    tag = soup.find("meta", attrs={attr_name: key})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def extract_favicon(soup, base_url):
    candidate = soup.find("link", rel=["icon", "shortcut icon", "apple-touch-icon"])
    if candidate and candidate.get("href"):
        return _normalize_url(base_url, candidate["href"])
    return None


def extract_metadata(soup, base_url):
    metadata = {
        "title": None,
        "description": None,
        "keywords": None,
        "canonical": None,
        "favicon": None,
        "og": {},
        "twitter": {},
    }

    if soup.title and soup.title.string:
        metadata["title"] = soup.title.string.strip()

    description = _find_meta_tag(soup, "description", attr_name="name")
    if description:
        metadata["description"] = description

    keywords = _find_meta_tag(soup, "keywords", attr_name="name")
    if keywords:
        metadata["keywords"] = keywords

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        metadata["canonical"] = _normalize_url(base_url, canonical["href"])

    og_keys = ["og:title", "og:description", "og:image", "og:site_name"]
    for og_key in og_keys:
        value = _find_meta_tag(soup, og_key, attr_name="property")
        if value:
            metadata["og"][og_key] = value

    twitter_keys = ["twitter:title", "twitter:description", "twitter:image"]
    for twitter_key in twitter_keys:
        value = _find_meta_tag(soup, twitter_key, attr_name="name")
        if value:
            metadata["twitter"][twitter_key] = value

    metadata["favicon"] = extract_favicon(soup, base_url)
    return metadata
