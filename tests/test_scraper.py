import os
import config
from PIL import Image, ImageDraw
from scraper.site import WebsiteScraper
from engine.scraper.capture import ScreenshotValidationError


def test_run_scraper_creates_output(tmp_path, monkeypatch):
    test_url = "https://example.com"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "JSON_FOLDER", str(output_dir / "json"))
    monkeypatch.setattr(config, "HTML_FOLDER", str(output_dir / "html"))
    monkeypatch.setattr(config, "ASSETS_FOLDER", str(output_dir / "assets"))
    monkeypatch.setattr(config, "IMAGE_FOLDER", str(output_dir / "images"))
    monkeypatch.setattr(config, "DEBUG", True)  # Ensure debug for diagnostics if needed

    scraper = WebsiteScraper(test_url)

    class FakePage:
        def __init__(self):
            self.content_value = "<html><head><title>Example Domain</title></head><body><h1>Example Domain</h1></body></html>"
            self.url = test_url
            self._current_url = test_url  # Critical for capture service

        def content(self):
            return self.content_value

        def goto(self, url, wait_until=None, timeout=None):
            if url and not url.startswith("http"):
                raise ValueError(f"Invalid URL: {url}")
            self._current_url = url or self.url
            return None

        def screenshot(self, path=None, full_page=False, **kwargs):
            # Create realistic screenshot with text and variation for all validators to pass
            if path is None:
                path = "temp_screenshot.png"
            image = Image.new("RGB", (1200, 800), color=(240, 248, 255))
            draw = ImageDraw.Draw(image)
            # Add some content to ensure high variance, entropy, stddev, good brightness
            draw.rectangle([100, 100, 1100, 200], fill=(0, 102, 204))
            draw.text((150, 150), "EXAMPLE DOMAIN - Billboard Advertising", fill=(255, 255, 255))
            draw.text((150, 300), "Leading provider of outdoor advertising solutions.", fill=(50, 50, 50))
            draw.rectangle([100, 400, 500, 500], fill=(255, 215, 0))
            draw.text((150, 450), "GET A FREE QUOTE TODAY", fill=(0, 0, 0))
            # Add noise for variance
            for i in range(20):
                x = 100 + (i * 50) % 1000
                y = 550 + (i % 5) * 10
                draw.rectangle([x, y, x+5, y+5], fill=(100 + i*5, 150, 200))
            # Save to the exact path used by the test (the monkeypatched config.ASSETS_FOLDER is tmp_path based)
            if path and isinstance(path, str):
                image.save(path, format="PNG")
            else:
                image.save("example_screenshot.png", format="PNG")
            return path  # Playwright screenshot returns the path in some contexts, but mainly side-effect

        def evaluate(self, script):
            if "fonts.ready" in script or "scrollTo" in script:
                return True
            return []

        def is_closed(self) -> bool:
            return False

    class FakeBrowser:
        def new_page(self, user_agent=None):
            return FakePage()

        def close(self):
            pass

        def is_connected(self) -> bool:
            return True

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def launch(self, headless=True):
            return FakeBrowser()

    monkeypatch.setattr("engine.scraper.site.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("engine.scraper.site.pick_hero_image", lambda page: None)
    monkeypatch.setattr("engine.scraper.site.discover_assets", lambda html, base_url: [])

    result = scraper.run()

    assert result["company"] == "Example Domain"
    assert result["metadata"]["title"] == "Example Domain"
    assert isinstance(result.get("ad_copy"), str)
    assert isinstance(result.get("quality_score"), int)
    assert isinstance(result.get("vision_score"), int)
    assert result.get("quality_label") in {"excellent", "good", "needs improvement"}
    assert result.get("vision_label") in {"excellent", "good", "needs improvement"}
    assert os.path.exists(result["html_file"])
    screenshot_path = result.get("screenshot_file") or result.get("screenshot_path")
    assert screenshot_path is not None
    assert os.path.exists(screenshot_path)
    assert os.path.exists(str(output_dir / "json" / "example.json"))

    rendered_path = scraper.render_billboard("contractor")
    assert os.path.exists(rendered_path)
    assert rendered_path.endswith(("_contractor.png", "_contractor_dentist.png", "_contractor_realtor.png"))


def test_automatic_regeneration_on_weak_quality(tmp_path, monkeypatch):
    test_url = "https://example.com"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "JSON_FOLDER", str(output_dir / "json"))
    monkeypatch.setattr(config, "HTML_FOLDER", str(output_dir / "html"))
    monkeypatch.setattr(config, "ASSETS_FOLDER", str(output_dir / "assets"))
    monkeypatch.setattr(config, "IMAGE_FOLDER", str(output_dir / "images"))
    monkeypatch.setattr(config, "DEBUG", True)

    scraper = WebsiteScraper(test_url)

    class FakePage:
        def __init__(self):
            self.content_value = "<html><head><title>Example Domain</title></head><body><h1>Example Domain</h1></body></html>"
            self.url = test_url
            self._current_url = test_url

        def content(self):
            return self.content_value

        def goto(self, url, wait_until=None, timeout=None):
            if url and not url.startswith("http"):
                raise ValueError(f"Invalid URL: {url}")
            self._current_url = url or self.url
            return None

        def screenshot(self, path=None, full_page=False, **kwargs):
            # For this test, we want a screenshot that may trigger regeneration (lower quality)
            # But still valid enough to not raise ScreenshotValidationError
            if path is None:
                path = "temp_screenshot.png"
            image = Image.new("RGB", (800, 600), color=(200, 200, 210))  # Slightly varied
            draw = ImageDraw.Draw(image)
            draw.rectangle([50, 50, 750, 150], fill=(100, 100, 150))
            draw.text((100, 100), "EXAMPLE DOMAIN", fill=(255, 255, 255))
            # Add some noise
            for i in range(15):
                x = 50 + (i * 40) % 700
                y = 200 + (i % 4) * 20
                draw.rectangle([x, y, x+3, y+3], fill=(180, 180, 190))
            # Save to the exact path used by the test
            if path and isinstance(path, str):
                image.save(path, format="PNG")
            else:
                image.save("example_screenshot.png", format="PNG")
            return path

        def evaluate(self, script):
            if "fonts.ready" in script or "scrollTo" in script:
                return True
            return []

        def is_closed(self) -> bool:
            return False

    class FakeBrowser:
        def new_page(self, user_agent=None):
            return FakePage()

        def close(self):
            pass

        def is_connected(self) -> bool:
            return True

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def launch(self, headless=True):
            return FakeBrowser()

    monkeypatch.setattr("engine.scraper.site.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("engine.scraper.site.pick_hero_image", lambda page: None)
    monkeypatch.setattr("engine.scraper.site.discover_assets", lambda html, base_url: [])

    result = scraper.run()
    assert result["quality_label"] in {"needs improvement", "good", "excellent"}

    rendered_path = scraper.render_billboard("contractor")
    assert os.path.exists(rendered_path)
    assert result["regenerated"] in {True, False}
    if result.get("quality_label") == "needs improvement" or result.get("vision_label") == "needs improvement":
        assert result["regenerated"] is True
    else:
        assert result["regenerated"] is False


# New test for blank image case (keeps expecting ScreenshotValidationError)
def test_blank_image_raises_validation_error(tmp_path, monkeypatch):
    test_url = "https://example.com"
    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "JSON_FOLDER", str(output_dir / "json"))
    monkeypatch.setattr(config, "HTML_FOLDER", str(output_dir / "html"))
    monkeypatch.setattr(config, "ASSETS_FOLDER", str(output_dir / "assets"))
    monkeypatch.setattr(config, "IMAGE_FOLDER", str(output_dir / "images"))
    monkeypatch.setattr(config, "DEBUG", True)

    scraper = WebsiteScraper(test_url)

    class FakePage:
        def __init__(self):
            self.content_value = "<html><head><title>Example Domain</title></head><body><h1>Example Domain</h1></body></html>"
            self.url = test_url
            self._current_url = test_url

        def content(self):
            return self.content_value

        def goto(self, url, wait_until=None, timeout=None):
            if url and not url.startswith("http"):
                raise ValueError(f"Invalid URL: {url}")
            self._current_url = url or self.url
            return None

        def screenshot(self, path=None, full_page=False, **kwargs):
            if path is None:
                path = "temp_screenshot.png"
            # Blank/uniform image that should fail validation (low variance, low stddev, low entropy)
            image = Image.new("RGB", (800, 600), color=(255, 255, 255))  # All white
            image.save(path, format="PNG")
            return path

        def evaluate(self, script):
            return []

        def is_closed(self) -> bool:
            return False

    class FakeBrowser:
        def new_page(self, user_agent=None):
            return FakePage()

        def close(self):
            pass

        def is_connected(self) -> bool:
            return True

    class FakePlaywright:
        def __init__(self):
            self.chromium = self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def launch(self, headless=True):
            return FakeBrowser()

    monkeypatch.setattr("engine.scraper.site.sync_playwright", lambda: FakePlaywright())
    monkeypatch.setattr("engine.scraper.site.pick_hero_image", lambda page: None)
    monkeypatch.setattr("engine.scraper.site.discover_assets", lambda html, base_url: [])

    # This should raise ScreenshotValidationError as per revised requirements
    try:
        result = scraper.run()
        assert False, "Expected ScreenshotValidationError for blank image"
    except ScreenshotValidationError:
        pass  # Expected behavior
    except Exception as e:
        assert False, f"Expected ScreenshotValidationError, got {type(e).__name__}: {e}"
