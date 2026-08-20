"""Asset discovery and download for BillboardAI scraper."""

import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


CSS_URL_PATTERN = re.compile(r"url\(['\"]?(.*?)['\"]?\)")


def _normalize_url(base_url, src):
    if not src:
        return None
    return urljoin(base_url, src.strip())


def _extract_srcset_urls(value):
    if not value:
        return []

    urls = []
    for part in value.split(","):
        piece = part.strip().split(" ")[0]
        if piece:
            urls.append(piece)
    return urls


def _extract_css_urls(text):
    if not text:
        return []
    return [match.group(1).strip() for match in CSS_URL_PATTERN.finditer(text)]


def _collect_image_srcs(tag):
    sources = []
    if tag.name == "img":
        sources.extend([
            tag.get("src"),
            tag.get("data-src"),
            tag.get("data-lazy-src"),
            tag.get("data-original"),
        ])
        if tag.get("srcset"):
            sources.extend(_extract_srcset_urls(tag.get("srcset")))
    elif tag.name == "source":
        if tag.get("srcset"):
            sources.extend(_extract_srcset_urls(tag.get("srcset")))
        sources.append(tag.get("src"))
    else:
        sources.append(tag.get("src"))
    return sources


def discover_assets(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    urls = set()

    for tag in soup.find_all(["img", "source", "video", "audio"]):
        for candidate in _collect_image_srcs(tag):
            if not candidate:
                continue

            if candidate.lower().startswith("data:"):
                continue

            normalized = _normalize_url(base_url, candidate)
            if normalized:
                urls.add(normalized)

    for link in soup.find_all("link", rel=["icon", "shortcut icon", "apple-touch-icon", "manifest"]):
        href = link.get("href")
        if href:
            normalized = _normalize_url(base_url, href)
            if normalized:
                urls.add(normalized)

    for tag in soup.find_all(style=True):
        for src in _extract_css_urls(tag["style"]):
            normalized = _normalize_url(base_url, src)
            if normalized:
                urls.add(normalized)

    for style in soup.find_all("style"):
        for src in _extract_css_urls(style.get_text()):
            normalized = _normalize_url(base_url, src)
            if normalized:
                urls.add(normalized)

    return sorted(urls)


def discover_asset_contexts(html, base_url):
    """Return compact DOM text context keyed by normalized image URL."""
    soup = BeautifulSoup(html, "lxml")
    contexts = {}
    for tag in soup.find_all(["img", "source"]):
        pieces = [
            tag.get("alt") or "",
            tag.get("title") or "",
            " ".join(tag.get("class") or []),
            tag.get("id") or "",
            tag.get("aria-label") or "",
        ]
        parent = tag.parent
        if parent is not None:
            pieces.extend([
                " ".join(parent.get("class") or []),
                parent.get("id") or "",
                parent.get_text(" ", strip=True)[:300],
            ])
        context = " ".join(str(p) for p in pieces if p)[:800]
        for candidate in _collect_image_srcs(tag):
            if not candidate or candidate.lower().startswith("data:"):
                continue
            normalized = _normalize_url(base_url, candidate)
            if normalized and context:
                contexts.setdefault(normalized, context)
    return contexts


def save_asset(url, folder, downloader):
    if not url:
        return None
    os.makedirs(folder, exist_ok=True)
    return downloader(url, folder)
