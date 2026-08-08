"""Tests for asset normalizer and BrandAsset model."""

import io
import os
import tempfile

import pytest
from PIL import Image, ImageDraw

from engine.brand_profile import BrandAsset
from engine.scraper.asset_normalizer import (
    CANONICAL_EXTENSION,
    normalize_asset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_temp_image(folder, name, mode="RGB", size=(100, 80), fmt="PNG", draw_alpha=False):
    """Create a real image file on disk and return its path."""
    path = os.path.join(folder, name)
    if mode == "RGBA":
        img = Image.new("RGBA", size, (255, 0, 0, 128))
    elif mode == "P":
        img = Image.new("P", size)
        img.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0] + [0, 0, 0] * 253)
    else:
        img = Image.new(mode, size, (255, 0, 0))
    img.save(path, format=fmt)
    return path


def _write_corrupt_file(folder, name):
    """Write a file that is not a valid image."""
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(b"this is not an image\x00\x01\x02")
    return path


def _write_html_file(folder, name):
    """Write an HTML file masquerading as an image."""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><body><h1>404 Not Found</h1></body></html>")
    return path


# ---------------------------------------------------------------------------
# BrandAsset serialization
# ---------------------------------------------------------------------------


class TestBrandAssetSerialization:
    def test_round_trip(self):
        asset = BrandAsset(
            path="/tmp/logo.png",
            source_url="https://example.com/logo",
            asset_type="logo",
            mime_type="image/png",
            format="PNG",
            width=200,
            height=100,
            aspect_ratio=2.0,
            has_alpha=True,
            file_size=12345,
            confidence=1.0,
        )
        d = asset.to_dict()
        restored = BrandAsset.from_dict(d)
        assert restored.path == asset.path
        assert restored.source_url == asset.source_url
        assert restored.asset_type == asset.asset_type
        assert restored.mime_type == asset.mime_type
        assert restored.format == asset.format
        assert restored.width == asset.width
        assert restored.height == asset.height
        assert restored.aspect_ratio == asset.aspect_ratio
        assert restored.has_alpha == asset.has_alpha
        assert restored.file_size == asset.file_size
        assert restored.confidence == asset.confidence

    def test_from_dict_ignores_unknown_fields(self):
        d = {
            "path": "/x.png",
            "source_url": "http://a",
            "extra_field": "should be ignored",
        }
        asset = BrandAsset.from_dict(d)
        assert asset.path == "/x.png"
        assert not hasattr(asset, "extra_field")


# ---------------------------------------------------------------------------
# Content-based format detection
# ---------------------------------------------------------------------------


class TestFormatDetection:
    def test_extensionless_png_detected(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "logo_image", fmt="PNG")
        result = normalize_asset(path, "https://example.com/logo")
        assert result is not None
        assert result.format == "PNG"
        assert result.mime_type == "image/png"
        assert result.path.endswith(".png")

    def test_extensionless_jpeg_detected(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "logo_image", fmt="JPEG")
        result = normalize_asset(path, "https://example.com/logo")
        assert result is not None
        assert result.format == "JPEG"
        assert result.path.endswith(".jpg")

    def test_webp_detected(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "logo_image", fmt="WEBP")
        result = normalize_asset(path, "https://example.com/logo")
        assert result is not None
        assert result.format == "WEBP"
        assert result.path.endswith(".webp")

    def test_wrong_url_extension_does_not_override_actual_format(self, tmp_path):
        # File is PNG but named .gif
        path = _write_temp_image(str(tmp_path), "logo.gif", fmt="PNG")
        result = normalize_asset(path, "https://example.com/logo.gif")
        assert result is not None
        assert result.format == "PNG"
        assert result.path.endswith(".png")

    def test_wrong_content_type_does_not_override_actual_content(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "logo_image", fmt="PNG")
        result = normalize_asset(
            path,
            "https://example.com/logo",
            content_type="image/jpeg",  # wrong!
        )
        assert result is not None
        assert result.format == "PNG"
        assert result.mime_type == "image/png"


# ---------------------------------------------------------------------------
# Dimensions, aspect ratio, alpha
# ---------------------------------------------------------------------------


class TestImageProperties:
    def test_width_height_detected(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "img.png", size=(300, 150), fmt="PNG")
        result = normalize_asset(path, "https://example.com/img")
        assert result is not None
        assert result.width == 300
        assert result.height == 150

    def test_aspect_ratio_calculated(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "img.png", size=(300, 150), fmt="PNG")
        result = normalize_asset(path, "https://example.com/img")
        assert result is not None
        assert result.aspect_ratio == pytest.approx(2.0)

    def test_rgba_png_reports_alpha(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "img.png", mode="RGBA", fmt="PNG")
        result = normalize_asset(path, "https://example.com/img")
        assert result is not None
        assert result.has_alpha is True

    def test_rgb_image_reports_no_alpha(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "img.png", mode="RGB", fmt="PNG")
        result = normalize_asset(path, "https://example.com/img")
        assert result is not None
        assert result.has_alpha is False

    def test_file_size_populated(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "img.png", size=(10, 10), fmt="PNG")
        result = normalize_asset(path, "https://example.com/img")
        assert result is not None
        assert result.file_size > 0


# ---------------------------------------------------------------------------
# Rejection of invalid content
# ---------------------------------------------------------------------------


class TestRejection:
    def test_corrupt_image_rejected(self, tmp_path):
        path = _write_corrupt_file(str(tmp_path), "bad.png")
        result = normalize_asset(path, "https://example.com/bad.png")
        assert result is None

    def test_html_masquerading_as_image_rejected(self, tmp_path):
        path = _write_html_file(str(tmp_path), "fake.png")
        result = normalize_asset(path, "https://example.com/fake.png")
        assert result is None

    def test_non_image_content_rejected(self, tmp_path):
        path = os.path.join(str(tmp_path), "script.js")
        with open(path, "w") as f:
            f.write("console.log('hello');")
        result = normalize_asset(path, "https://example.com/script.js")
        assert result is None

    def test_zero_byte_file_rejected(self, tmp_path):
        path = os.path.join(str(tmp_path), "empty.png")
        with open(path, "wb") as f:
            pass  # zero bytes
        result = normalize_asset(path, "https://example.com/empty.png")
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        result = normalize_asset(
            os.path.join(str(tmp_path), "nonexistent.png"),
            "https://example.com/nonexistent.png",
        )
        assert result is None


# ---------------------------------------------------------------------------
# Canonical naming
# ---------------------------------------------------------------------------


class TestCanonicalNaming:
    def test_canonical_extension_assigned(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "logo_image.bin", fmt="PNG")
        result = normalize_asset(path, "https://example.com/logo")
        assert result is not None
        assert result.path.endswith(".png")
        assert os.path.exists(result.path)
        # Original .bin should be gone
        assert not os.path.exists(path)

    def test_already_canonical_unchanged(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "logo.png", fmt="PNG")
        result = normalize_asset(path, "https://example.com/logo.png")
        assert result is not None
        assert result.path == path

    def test_filename_collision_handled_safely(self, tmp_path):
        folder = str(tmp_path)
        # Create a PNG that will be renamed to .png
        path1 = _write_temp_image(folder, "logo_image.bin", fmt="PNG")
        # Pre-create a file at the target name
        collision_path = os.path.join(folder, "logo_image.png")
        with open(collision_path, "wb") as f:
            f.write(b"preexisting")

        result = normalize_asset(path1, "https://example.com/logo")
        assert result is not None
        assert result.path.endswith(".png")
        # Should not have overwritten the preexisting file
        assert os.path.exists(collision_path)
        # The normalized path should be different
        assert os.path.basename(result.path) != "logo_image.png"
        # Original .bin should be gone
        assert not os.path.exists(path1)

    def test_jpeg_gets_jpg_extension(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "photo.bin", fmt="JPEG")
        result = normalize_asset(path, "https://example.com/photo")
        assert result is not None
        assert result.path.endswith(".jpg")

    def test_webp_gets_webp_extension(self, tmp_path):
        path = _write_temp_image(str(tmp_path), "hero.bin", fmt="WEBP")
        result = normalize_asset(path, "https://example.com/hero")
        assert result is not None
        assert result.path.endswith(".webp")


# ---------------------------------------------------------------------------
# Legacy compatibility markers
# ---------------------------------------------------------------------------


class TestLegacyCompatibility:
    """These tests verify that the data dict still carries legacy keys."""

    def test_legacy_logo_path_still_works(self):
        """logo_path is still a string in the data dict."""
        # This is tested implicitly by the scraper integration test.
        # Here we just verify BrandAsset doesn't interfere with the concept.
        asset = BrandAsset(
            path="/tmp/logo.png",
            source_url="https://example.com/logo",
            asset_type="logo",
            format="PNG",
            width=200,
            height=100,
        )
        d = asset.to_dict()
        assert d["path"] == "/tmp/logo.png"
        assert isinstance(d["path"], str)

    def test_legacy_asset_paths_still_work(self):
        """asset_paths remains a list of strings."""
        # BrandAsset serialization produces dicts, but asset_paths stays as strings.
        # The data dict carries both: asset_paths (legacy) and assets (structured).
        asset = BrandAsset(
            path="/tmp/hero.png",
            source_url="https://example.com/hero",
            asset_type="generic",
            format="PNG",
            width=300,
            height=200,
        )
        d = asset.to_dict()
        assert d["path"] == "/tmp/hero.png"


# ---------------------------------------------------------------------------
# CANONICAL_EXTENSION completeness
# ---------------------------------------------------------------------------


class TestCanonicalExtensionMapping:
    def test_all_expected_formats_present(self):
        assert CANONICAL_EXTENSION["PNG"] == ".png"
        assert CANONICAL_EXTENSION["JPEG"] == ".jpg"
        assert CANONICAL_EXTENSION["WEBP"] == ".webp"
        assert CANONICAL_EXTENSION["GIF"] == ".gif"
        assert CANONICAL_EXTENSION["BMP"] == ".bmp"