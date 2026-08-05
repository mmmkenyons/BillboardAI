"""CSS scraping utilities for BillboardAI."""

from urllib.parse import urljoin
from bs4 import BeautifulSoup


def _normalize_url(base_url, src):
    if not src:
        return None
    return urljoin(base_url, src.strip())


def extract_stylesheet_urls(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    urls = []

    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href")
        if href:
            normalized = _normalize_url(base_url, href)
            if normalized:
                urls.append(normalized)

    return sorted(urls)


def extract_inline_styles(html):
    soup = BeautifulSoup(html, "lxml")
    return [style.get_text("\n", strip=True) for style in soup.find_all("style") if style.get_text(strip=True)]
