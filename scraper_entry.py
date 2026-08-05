import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import sync_playwright
from sklearn.cluster import KMeans
import tldextract

from config import *
from scraper import WebsiteScraper

__all__ = ["WebsiteScraper"]

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(JSON_FOLDER, exist_ok=True)
os.makedirs(HTML_FOLDER, exist_ok=True)
os.makedirs(CSS_FOLDER, exist_ok=True)
os.makedirs(ASSETS_FOLDER, exist_ok=True)


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


def _clamp_rgb(value):
    return max(0, min(255, int(value)))


class WebsiteAnalyzer:

    def __init__(self, url):
        if not url.startswith("http"):
            url = "https://" + url

        self.url = url
        self.html = ""
        self.soup = None
        self.company = None
        self.logo_url = None
        self.logo_score = 0
        self.logo_path = None
        self.logo_color = None
        self.hero_url = None
        self.hero_path = None
        self.css_paths = []
        self.asset_paths = []
        self.screenshot_path = None
        self.html_path = None
        self.headline = None
        domain = tldextract.extract(self.url)
        self.filename_base = domain.domain or "website"

    def log(self, message, ok=True):
        prefix = "✓" if ok else "✗"
        print(f"{prefix} {message}")

    def _download_resource(self, page, url, folder, prefix=None):
        url = _normalize_url(self.url, url)
        if not url:
            return None

        filename = _safe_filename(url, prefix=prefix)
        path = os.path.join(folder, filename)

        try:
            response = page.context.request.get(url, timeout=TIMEOUT)
            if response.ok:
                with open(path, "wb") as handle:
                    handle.write(response.body())
                return path
        except Exception:
            return None

        return None

    def load(self):
        start = time.time()
        self.log("Website")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(self.url, wait_until="networkidle", timeout=TIMEOUT)
            self.html = page.content()
            self.soup = BeautifulSoup(self.html, "lxml")
            self.screenshot_path = self.save_screenshot(page)
            self.html_path = self.save_html()
            self.css_paths = self.save_css(page)
            self.asset_paths = self.save_assets(page)
            self.logo_url, self.logo_score = self.pick_logo(page)
            self.logo_path = self.save_logo(page, self.logo_url)
            self.logo_color = self.detect_logo_color(self.logo_path)
            self.hero_url = self.get_hero_image(page)
            self.hero_path = self.save_hero_image(page, self.hero_url)
            self.headline = self.extract_headline()
            browser.close()

        self.log("HTML")
        self.log("Screenshot")
        self.log("CSS")
        self.log("Assets")
        self.log("Logo")
        self.log("Colors")
        self.log("Hero")
        self.log("Headline")
        elapsed = time.time() - start
        self.log(f"Loaded in {elapsed:.1f} seconds")

    def save_screenshot(self, page):
        path = os.path.join(ASSETS_FOLDER, f"{self.filename_base}_screenshot.png")
        page.screenshot(path=path, full_page=True)
        return path

    def save_html(self):
        path = os.path.join(HTML_FOLDER, f"{self.filename_base}.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.html)
        return path

    def save_css(self, page):
        css_paths = []
        stylesheet_links = page.query_selector_all("link[rel='stylesheet']")

        for link in stylesheet_links:
            href = link.get_attribute("href")
            path = self._download_resource(page, href, CSS_FOLDER, prefix="style")
            if path:
                css_paths.append(path)

        inline_styles = page.eval_on_selector_all(
            "style",
            "elements => elements.map(e => e.textContent)"
        )

        inline_content = "\n\n".join([style for style in inline_styles or [] if style])
        if inline_content:
            inline_path = os.path.join(CSS_FOLDER, f"{self.filename_base}_inline.css")
            with open(inline_path, "w", encoding="utf-8") as handle:
                handle.write(inline_content)
            css_paths.append(inline_path)

        return css_paths

    def save_assets(self, page):
        assets = set()

        for img in self.soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            path = self._download_resource(page, src, ASSETS_FOLDER, prefix="img")
            if path:
                assets.add(path)

        for link in self.soup.find_all("link", rel=["icon", "shortcut icon"]):
            href = link.get("href")
            path = self._download_resource(page, href, ASSETS_FOLDER, prefix="icon")
            if path:
                assets.add(path)

        return sorted(assets)

    def pick_logo(self, page):
        candidates = []

        for img in self.soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if not src:
                continue

            text = (
                str(img.get("class") or "")
                + " "
                + str(img.get("alt") or "")
                + " "
                + str(img.get("id") or "")
                + " "
                + src
            ).lower()

            score = 0
            if "logo" in text:
                score += 100
            if "brand" in text or "mark" in text:
                score += 50
            if "header" in text:
                score += 20
            if "icon" in text:
                score += 15
            if "favicon" in text:
                score += 10
            if ".svg" in src:
                score += 40
            if ".png" in src or ".jpg" in src or ".jpeg" in src:
                score += 10
            if "hero" in text or "banner" in text or "slide" in text:
                score -= 20

            width = img.get("width")
            height = img.get("height")
            if width and height and width.isdigit() and height.isdigit():
                score += min((int(width) * int(height)) / 5000, 50)

            candidates.append((score, _normalize_url(self.url, src)))

        candidates = [c for c in candidates if c[1]]
        candidates.sort(key=lambda item: item[0], reverse=True)

        if candidates:
            top_score, top_logo = candidates[0]
            if top_score < 100:
                og_image = self.opengraph_image()
                if og_image:
                    return og_image, top_score
                return self.screenshot_logo_crop(page), top_score
            return top_logo, top_score

        og_image = self.opengraph_image()
        if og_image:
            return og_image, 0

        return self.screenshot_logo_crop(page), 0

    def opengraph_image(self):
        og = self.soup.find("meta", property="og:image")
        if og and og.get("content"):
            return _normalize_url(self.url, og["content"])
        return None

    def screenshot_logo_crop(self, page):
        if not self.screenshot_path or not os.path.exists(self.screenshot_path):
            return None

        try:
            image = Image.open(self.screenshot_path)
            width, height = image.size
            crop_w = int(min(400, width * 0.5))
            crop_h = int(min(200, height * 0.2))
            left = int((width - crop_w) / 2)
            top = int(height * 0.05)
            right = left + crop_w
            bottom = top + crop_h
            crop = image.crop((left, top, right, bottom))
            path = os.path.join(ASSETS_FOLDER, f"{self.filename_base}_logo_crop.png")
            crop.save(path)
            return path
        except Exception:
            return None

    def save_logo(self, page, url):
        if not url:
            return None
        if os.path.exists(url):
            return url
        return self._download_resource(page, url, ASSETS_FOLDER, prefix="logo")

    def detect_logo_color(self, logo_path):
        if not logo_path or not os.path.exists(logo_path):
            return None

        try:
            image = Image.open(logo_path).convert("RGB")
            image.thumbnail((300, 300), Image.Resampling.LANCZOS)
            pixels = np.array(image).reshape(-1, 3)
            pixels = pixels[~np.all(pixels == [255, 255, 255], axis=1)]
            if len(pixels) < 10:
                return None

            k = min(5, len(pixels))
            model = KMeans(n_clusters=k, random_state=42, n_init="auto")
            labels = model.fit_predict(pixels)
            counts = np.bincount(labels)
            centers = model.cluster_centers_
            palette = [tuple(map(_clamp_rgb, center)) for center in centers]
            sorted_indices = np.argsort(counts)[::-1]

            for idx in sorted_indices:
                color = palette[idx]
                r, g, b = color
                if self._is_ignore_color(r, g, b):
                    continue
                return {
                    "rgb": color,
                    "hex": "#%02x%02x%02x" % color,
                    "percent": float(counts[idx]) / len(labels) * 100,
                }
        except Exception:
            return None

        return None

    @staticmethod
    def _is_ignore_color(r, g, b):
        if max(r, g, b) < 35:
            return True
        if min(r, g, b) > 220:
            return True
        if abs(r - g) < 10 and abs(g - b) < 10:
            return True
        return False

    def get_hero_image(self, page):
        images = page.evaluate(
            "() => Array.from(document.images).map(img => {"
            " const rect = img.getBoundingClientRect();"
            " const style = window.getComputedStyle(img);"
            " return {"
            " src: img.currentSrc || img.src || img.getAttribute('data-src') || '',"
            " width: rect.width,"
            " height: rect.height,"
            " area: rect.width * rect.height,"
            " visible: rect.width > 100 && rect.height > 100 && style.visibility !== 'hidden' && style.display !== 'none'"
            " };"
            "})"
        )

        visible_images = [img for img in images if img.get("visible") and img.get("src")]
        visible_images.sort(key=lambda item: item.get("area", 0), reverse=True)

        for image in visible_images:
            src = image.get("src")
            if src and "logo" not in src.lower() and "icon" not in src.lower():
                return _normalize_url(self.url, src)

        return None

    def save_hero_image(self, page, url):
        if not url:
            return None
        return self._download_resource(page, url, ASSETS_FOLDER, prefix="hero")

    def extract_headline(self):
        if not self.soup:
            return None

        heading = self.soup.find("h1")
        if heading and heading.get_text(strip=True):
            return self._normalize_headline(heading.get_text(" ", strip=True))

        candidates = []
        for tag in ["h2", "h3", "h4"]:
            for element in self.soup.find_all(tag):
                text = element.get_text(" ", strip=True)
                if len(text) > 15:
                    score = 100 - (len(text) / 10)
                    if "specialist" in text.lower() or "experts" in text.lower():
                        score += 10
                    candidates.append((score, text))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return self._normalize_headline(candidates[0][1])

        title = self.soup.title
        if title and title.get_text(strip=True):
            return self._normalize_headline(title.get_text(" ", strip=True))

        desc = self.meta_description()
        if desc:
            return self._normalize_headline(desc)

        return None

    @staticmethod
    def _normalize_headline(text):
        text = text.strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r".*(?:\||-|:)", "", text).strip()
        return text

    def run(self):
        self.load()

        self.company = self.company_name()
        data = {
            "company": self.company,
            "phone": self.phone(),
            "email": self.email(),
            "description": self.meta_description(),
            "headline": self.headline,
            "logo_url": self.logo_url,
            "logo_score": self.logo_score,
            "logo_file": self.logo_path,
            "logo_color": self.logo_color,
            "hero_url": self.hero_url,
            "hero_file": self.hero_path,
            "screenshot_file": self.screenshot_path,
            "html_file": self.html_path,
            "css_files": self.css_paths,
            "asset_files": self.asset_paths,
            "website": self.url,
        }

        outfile = os.path.join(JSON_FOLDER, f"{self.company.replace(' ', '_')}.json")
        with open(outfile, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)

        return data

    def company_name(self):
        if self.soup is None:
            return None

        og = self.soup.find("meta", property="og:site_name")
        if og and og.get("content"):
            return og["content"]

        title = self.soup.title
        if title and title.get_text(strip=True):
            return title.get_text(strip=True).split("|")[0].strip()

        domain = tldextract.extract(self.url)
        return domain.domain.title() if domain.domain else self.url


if __name__ == "__main__":
    site = WebsiteAnalyzer("https://www.idealroofingco.com")
    result = site.run()
    print(json.dumps(result, indent=4))
