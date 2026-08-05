"""Website scraping and data extraction for BillboardAI."""

import json
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import tldextract

import config
from designer import generate_billboard
from renderer.renderer import render_billboard
from scraper.assets import discover_assets
from scraper.color import extract_brand_colors
from scraper.css import extract_inline_styles, extract_stylesheet_urls
from scraper.headline import extract_headline
from scraper.hero import pick_hero_image
from scraper.logo import pick_best_logo
from scraper.metadata import extract_metadata


def _safe_filename(url, prefix=None):
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or parsed.netloc or "resource"
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    if prefix:
        name = f"{prefix}_{name}"
    if not os.path.splitext(name)[1]:
        name += ".bin"
    return name


def _normalize_url(base, src):
    if not src:
        return None
    return urljoin(base, src.strip())


class WebsiteScraper:

    def __init__(self, url: str):
        if not url.startswith("http"):
            url = "https://" + url

        self.url = url
        self.html = ""
        self.soup = None
        self.filename_base = tldextract.extract(self.url).domain or "website"
        self.hero_url = None
        self.headline = None
        self.asset_urls = []
        self.asset_paths = []
        self.css_paths = []
        self.logo_url = None
        self.logo_path = None
        self.logo_score = 0
        self.screenshot_path = None
        self.metadata = {}
        self.brand_colors = []
        self.last_data = None

    def load(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=config.USER_AGENT)
            page.goto(self.url, wait_until="networkidle", timeout=config.TIMEOUT)
            self.html = page.content()
            self.soup = BeautifulSoup(self.html, "lxml")
            self.hero_url = pick_hero_image(page)
            self.asset_urls = discover_assets(self.html, self.url)
            self.css_paths = self.save_css(page)
            self.asset_paths = self.save_assets()
            self.metadata = extract_metadata(self.soup, self.url)
            self.screenshot_path = self.save_screenshot(page)
            self.brand_colors = extract_brand_colors(self.screenshot_path)
            browser.close()

    def save_html(self):
        path = os.path.join(config.HTML_FOLDER, f"{self.filename_base}.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.html)
        return path

    def save_screenshot(self, page):
        path = os.path.join(config.ASSETS_FOLDER, f"{self.filename_base}_screenshot.png")
        page.screenshot(path=path, full_page=True)
        return path

    def download_resource(self, url, folder, prefix=None):
        if not url:
            return None

        os.makedirs(folder, exist_ok=True)
        filename = _safe_filename(url, prefix=prefix)
        path = os.path.join(folder, filename)

        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path

        try:
            response = requests.get(url, timeout=config.TIMEOUT / 1000, stream=True)
            if response.ok:
                content_length = int(response.headers.get("Content-Length", 0))
                if content_length > 10_000_000:
                    return None
                with open(path, "wb") as handle:
                    for chunk in response.iter_content(8192):
                        if chunk:
                            handle.write(chunk)
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    return path
                os.remove(path)
        except requests.RequestException:
            return None

        return None

    def save_css(self, page):
        css_paths = []
        for href in extract_stylesheet_urls(self.html, self.url):
            path = self.download_resource(href, config.CSS_FOLDER, prefix="style")
            if path:
                css_paths.append(path)

        inline_styles = extract_inline_styles(self.html)
        if inline_styles:
            inline_path = os.path.join(config.CSS_FOLDER, f"{self.filename_base}_inline.css")
            with open(inline_path, "w", encoding="utf-8") as handle:
                handle.write("\n\n".join(inline_styles))
            css_paths.append(inline_path)

        return sorted(css_paths)

    def save_assets(self):
        asset_paths = []
        seen = set()

        for url in self.asset_urls:
            if not url or url in seen:
                continue
            seen.add(url)
            path = self.download_resource(url, config.ASSETS_FOLDER, prefix="asset")
            if path:
                asset_paths.append(path)
        return sorted(asset_paths)

    def run(self):
        os.makedirs(config.ASSETS_FOLDER, exist_ok=True)
        os.makedirs(config.HTML_FOLDER, exist_ok=True)
        os.makedirs(config.JSON_FOLDER, exist_ok=True)

        start = time.time()
        self.load()
        html_path = self.save_html()
        self.logo_url, self.logo_score = pick_best_logo(self.html, self.url)
        self.logo_path = self.download_resource(self.logo_url, config.ASSETS_FOLDER, prefix="logo") if self.logo_url else None
        self.headline = extract_headline(self.html)

        data = {
            "url": self.url,
            "html_file": html_path,
            "screenshot_file": self.screenshot_path,
            "company": self.extract_company_name(),
            "headline": self.headline,
            "logo_url": self.logo_url,
            "logo_path": self.logo_path,
            "logo_score": self.logo_score,
            "hero_url": self.hero_url,
            "brand_colors": self.brand_colors,
            "asset_paths": self.asset_paths,
            "css_paths": self.css_paths,
            "screenshot_path": self.screenshot_path,
            "asset_urls": self.asset_urls,
            "metadata": self.metadata,
        }

        out_path = os.path.join(config.JSON_FOLDER, f"{self.filename_base}.json")
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)

        self.last_data = data
        print(f"Loaded {self.url} in {time.time() - start:.1f}s")
        return data

    def render_billboard(self, template_name="contractor", output_path=None):
        if not self.last_data:
            self.run()

        os.makedirs(config.IMAGE_FOLDER, exist_ok=True)
        output_path = output_path or os.path.join(
            config.IMAGE_FOLDER, f"{self.filename_base}_{template_name}.png"
        )
        billboard_spec = generate_billboard(self.last_data, template_name)
        render_billboard(billboard_spec, output_path)
        return output_path

    def extract_company_name(self):
        if not self.soup:
            return ""

        og = self.soup.find("meta", property="og:site_name")
        if og and og.get("content"):
            return og["content"]

        title = self.soup.title
        if title and title.get_text(strip=True):
            return title.get_text(strip=True).split("|")[0].strip()

        return tldextract.extract(self.url).domain.title()
