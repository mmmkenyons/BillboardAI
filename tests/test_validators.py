"""Regression tests for screenshot validator downsampling fix.

Verifies that expensive metric computations (Laplacian, Canny, entropy)
run on a memory-safe analysis copy while original dimensions are preserved
in diagnostics.  Tall images must not trigger ArrayMemoryError.
"""

import numpy as np
import cv2

from engine.scraper.validators import (
    _create_analysis_image,
    _MAX_ANALYSIS_WIDTH,
    _MAX_ANALYSIS_HEIGHT,
    compute_metrics,
    validate_screenshot,
    ScreenshotMetrics,
    ScreenshotQuality,
)


# ---------------------------------------------------------------------------
# _create_analysis_image
# ---------------------------------------------------------------------------

def test_analysis_image_small_image_returns_copy():
    """Images under the pixel cap return a copy, not the same object."""
    img = np.zeros((800, 600, 3), dtype=np.uint8)
    result = _create_analysis_image(img)
    assert result is not img, "must return a copy, not the original array"
    assert result.shape == img.shape
    assert result.dtype == img.dtype


def test_analysis_image_exactly_at_cap_returns_copy():
    """An image at the max dimensions (1200x2000) is not downsampled."""
    img = np.zeros((_MAX_ANALYSIS_HEIGHT, _MAX_ANALYSIS_WIDTH, 3), dtype=np.uint8)
    result = _create_analysis_image(img)
    assert result.shape == (_MAX_ANALYSIS_HEIGHT, _MAX_ANALYSIS_WIDTH, 3)


def test_analysis_image_tall_image_is_downsampled():
    """A tall image (1200 x 10000) must be downsampled below the cap."""
    img = np.zeros((10000, 1200, 3), dtype=np.uint8)
    result = _create_analysis_image(img)
    rh, rw = result.shape[:2]
    assert rw <= _MAX_ANALYSIS_WIDTH, (
        f"analysis width {rw} exceeds cap {_MAX_ANALYSIS_WIDTH}"
    )
    assert rh <= _MAX_ANALYSIS_HEIGHT, (
        f"analysis height {rh} exceeds cap {_MAX_ANALYSIS_HEIGHT}"
    )
    # At least one dimension should be at the cap (tight fit)
    assert rw == _MAX_ANALYSIS_WIDTH or rh == _MAX_ANALYSIS_HEIGHT, (
        f"neither dimension at cap: {rw}x{rh}"
    )
    # Aspect ratio should be approximately preserved
    original_aspect = 1200 / 10000
    result_aspect = rw / rh
    assert abs(original_aspect - result_aspect) < 0.05, (
        f"aspect ratio drifted: orig={original_aspect:.4f} result={result_aspect:.4f}"
    )


def test_analysis_image_wide_image_is_downsampled():
    """A wide image (10000 x 800) must be downsampled below the cap."""
    img = np.zeros((800, 10000, 3), dtype=np.uint8)
    result = _create_analysis_image(img)
    rh, rw = result.shape[:2]
    assert rw <= _MAX_ANALYSIS_WIDTH
    assert rh <= _MAX_ANALYSIS_HEIGHT


def test_analysis_image_does_not_mutate_original():
    """The original image array must not be modified."""
    img = np.random.randint(0, 255, (5000, 1200, 3), dtype=np.uint8)
    original_copy = img.copy()
    _create_analysis_image(img)
    assert np.array_equal(img, original_copy), "original image was mutated"


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

def test_compute_metrics_preserves_original_dimensions():
    """Original width/height must reflect the full image, not the analysis copy."""
    img = np.random.randint(0, 255, (5000, 1200, 3), dtype=np.uint8)
    metrics = compute_metrics(img)
    assert metrics.width == 1200
    assert metrics.height == 5000
    assert metrics.original_size == "1200x5000"
    assert metrics.original_pixel_count == 1200 * 5000
    # Analysis copy should be smaller
    assert metrics.analysis_width <= _MAX_ANALYSIS_WIDTH
    assert metrics.analysis_height <= _MAX_ANALYSIS_HEIGHT
    assert metrics.analysis_pixel_count < metrics.original_pixel_count


def test_compute_metrics_tall_image_no_memory_error():
    """A 1200x15000 image must not raise MemoryError / ArrayMemoryError."""
    # Use uint8 to keep memory reasonable; the fix prevents the Laplacian
    # from allocating a 64F array at full resolution.
    img = np.random.randint(0, 255, (15000, 1200, 3), dtype=np.uint8)
    metrics = compute_metrics(img)
    assert isinstance(metrics, ScreenshotMetrics)
    assert metrics.width == 1200
    assert metrics.height == 15000
    # All float fields should be finite
    for attr in ("mean_brightness", "stddev", "laplacian_variance",
                 "entropy", "white_ratio", "black_ratio", "edge_density"):
        val = getattr(metrics, attr)
        assert np.isfinite(val), f"{attr} is not finite: {val}"


def test_compute_metrics_normal_image_works():
    """A normal-sized image (1200x800) produces valid metrics."""
    img = np.random.randint(0, 255, (800, 1200, 3), dtype=np.uint8)
    metrics = compute_metrics(img)
    assert metrics.width == 1200
    assert metrics.height == 800
    assert metrics.analysis_pixel_count == metrics.original_pixel_count
    assert 0.0 <= metrics.white_ratio <= 1.0
    assert 0.0 <= metrics.black_ratio <= 1.0
    assert 0.0 <= metrics.edge_density <= 1.0


# ---------------------------------------------------------------------------
# validate_screenshot (integration)
# ---------------------------------------------------------------------------

def test_validate_screenshot_tall_image(tmp_path):
    """End-to-end: validate_screenshot on a tall image must not crash."""
    import cv2
    path = tmp_path / "tall.png"
    img = np.random.randint(0, 255, (12000, 1200, 3), dtype=np.uint8)
    cv2.imwrite(str(path), img)

    quality = validate_screenshot(str(path))
    assert isinstance(quality, ScreenshotQuality)
    # Original dimensions in the result
    assert quality.dimensions == (1200, 12000)
    assert "metrics" in quality.diagnostics


def test_validate_screenshot_blank_tall_rejected(tmp_path):
    """A tall blank (all-white) image must still be rejected as invalid."""
    path = tmp_path / "blank_tall.png"
    img = np.full((14000, 1280, 3), 255, dtype=np.uint8)
    cv2.imwrite(str(path), img)

    quality = validate_screenshot(str(path))
    assert quality.valid is False, f"blank tall image should be rejected, got {quality.reason}"
    assert quality.dimensions == (1280, 14000)


def test_validate_screenshot_content_tall_accepted(tmp_path):
    """A tall image with real content must be accepted as valid."""
    path = tmp_path / "content_tall.png"
    rng = np.random.default_rng(42)
    # Base: varied background (not uniform) so stddev stays healthy
    img = rng.integers(60, 200, (14000, 1280, 3), dtype=np.uint8)

    # Add dense structural content every ~500 px to simulate a real web page
    # with text blocks, images, and UI elements that survive downsampling
    for y in range(500, 13500, 500):
        # Dark header bar (40 px)
        img[y:y + 40, 50:1230, :] = rng.integers(20, 80, (40, 1180, 3), dtype=np.uint8)
        # Light content block with high contrast (160 px, total section = 200 px)
        img[y + 40:y + 200, 50:1230, :] = rng.integers(100, 255, (160, 1180, 3), dtype=np.uint8)
        # Text-like horizontal lines (dark on light)
        for line_y in range(y + 60, y + 180, 20):
            img[line_y, 80:1200, :] = rng.integers(0, 40, (1120, 3), dtype=np.uint8)
        # Colored accent blocks
        img[y + 100:y + 150, 100:400, 0] = rng.integers(200, 255, (50, 300), dtype=np.uint8)  # blue channel
        img[y + 100:y + 150, 500:800, 1] = rng.integers(200, 255, (50, 300), dtype=np.uint8)  # green channel
        img[y + 100:y + 150, 900:1200, 2] = rng.integers(200, 255, (50, 300), dtype=np.uint8)  # red channel
        # Edge-like vertical separators
        img[y:y + 200, 400:410, :] = 0
        img[y:y + 200, 800:810, :] = 0

    cv2.imwrite(str(path), img)

    quality = validate_screenshot(str(path))
    assert quality.valid is True, (
        f"content-rich tall image should be accepted, got reason={quality.reason}, "
        f"stddev={quality.stddev:.2f}, edge_density={quality.diagnostics.get('edge_density', 'N/A')}"
    )
    assert quality.dimensions == (1280, 14000)


def test_validate_screenshot_does_not_mutate_source(tmp_path):
    """validate_screenshot must not modify the source image file or array."""
    path = tmp_path / "source.png"
    img = np.random.randint(0, 255, (5000, 1200, 3), dtype=np.uint8)
    cv2.imwrite(str(path), img)

    # Read back to get exact bytes
    with open(path, "rb") as f:
        original_bytes = f.read()

    validate_screenshot(str(path))

    with open(path, "rb") as f:
        after_bytes = f.read()

    assert original_bytes == after_bytes, "source image file was modified by validation"


def test_validate_screenshot_corrupt_file_returns_crash(tmp_path):
    """A corrupt/unreadable file returns valid=False with reason=validator_crash."""
    path = tmp_path / "corrupt.png"
    path.write_bytes(b"not a real png file")

    quality = validate_screenshot(str(path))
    assert quality.valid is False
    assert quality.reason in ("invalid_image", "validator_crash")


def test_validate_screenshot_missing_file(tmp_path):
    """Missing file returns file_not_found."""
    quality = validate_screenshot(str(tmp_path / "nonexistent.png"))
    assert quality.valid is False
    assert quality.reason == "file_not_found"
