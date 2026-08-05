import os
import config
from PIL import Image
from scraper.site import WebsiteScraper


def test_run_scraper_creates_output(tmp_path, monkeypatch):
    test_url = "https://example.com"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "JSON_FOLDER", str(output_dir / "json"))
    monkeypatch.setattr(config, "HTML_FOLDER", str(output_dir / "html"))
    monkeypatch.setattr(config, "ASSETS_FOLDER", str(output_dir / "assets"))
    monkeypatch.setattr(config, "IMAGE_FOLDER", str(output_dir / "images"))

    scraper = WebsiteScraper(test_url)

    class FakePage:
        def __init__(self):
            self.content_value = "<html><head><title>Example Domain</title></head><body><h1>Example Domain</h1></body></html>"
            self.url = test_url

        def content(self):
            return self.content_value

        def goto(self, url, wait_until=None, timeout=None):
            return None

        def screenshot(self, path, full_page):
            image = Image.new("RGB", (10, 10), color=(255, 255, 255))
            image.save(path, format="PNG")

        def evaluate(self, script):
            return []

    class FakeBrowser:
        def new_page(self, user_agent=None):
            return FakePage()

        def close(self):
            pass

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def launch(self, headless=True):
            return FakeBrowser()

    monkeypatch.setattr("scraper.site.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("scraper.site.pick_hero_image", lambda page: None)
    monkeypatch.setattr("scraper.site.discover_assets", lambda html, base_url: [])

    result = scraper.run()

    assert result["company"] == "Example Domain"
    assert result["metadata"]["title"] == "Example Domain"
    assert os.path.exists(result["html_file"])
    assert os.path.exists(result["screenshot_file"])
    assert os.path.exists(str(output_dir / "json" / "example.json"))

    rendered_path = scraper.render_billboard("contractor")
    assert os.path.exists(rendered_path)
    assert rendered_path.endswith("_contractor.png")
