"""Jim Woods Roofing regression test for Sprint 2A."""
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(name)s:%(levelname)s:%(message)s")

import config
from scraper.site import WebsiteScraper

# Clean previous assets to force fresh download
if os.path.exists(config.ASSETS_FOLDER):
    try:
        shutil.rmtree(config.ASSETS_FOLDER)
    except PermissionError:
        print("(Could not clean assets folder — continuing anyway)")

scraper = WebsiteScraper("https://jimwoodsroofing.com")
data = scraper.run()

print()
print("=== LOGO NORMALIZATION REPORT ===")
print(f"Logo URL: {data.get('logo_url')}")
print(f"Logo path: {data.get('logo_path')}")
logo = data.get("logo")
if logo:
    print("Logo BrandAsset:")
    print(f"  Filename: {os.path.basename(logo['path'])}")
    print(f"  Format: {logo['format']}")
    print(f"  Dimensions: {logo['width']}x{logo['height']}")
    print(f"  Alpha: {logo['has_alpha']}")
    print(f"  MIME: {logo['mime_type']}")
    print(f"  File size: {logo['file_size']} bytes")
    if logo["path"].endswith(".bin"):
        print("  WARNING: Logo still has .bin extension!")
    else:
        print("  .bin ELIMINATED: Logo has canonical extension")
else:
    print("  No logo BrandAsset (normalization may have failed)")

print(f"Validated BrandAssets: {len(data.get('assets', []))}")
print(f"Legacy asset_paths count: {len(data.get('asset_paths', []))}")
print("Scrape completed: True")
print(f"Company: {data.get('company')}")

# Test rendering
print()
print("=== RENDERING TEST ===")
output = scraper.render_billboard("contractor")
print(f"Render output: {output}")
print(f"Render completed: {os.path.exists(output)}")