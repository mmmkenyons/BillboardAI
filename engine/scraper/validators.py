"""Pluggable screenshot validators for quality checks.

Implements the validator framework per sprint plan. Each validator returns
part of ScreenshotQuality. Orchestrator combines them.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
import os
from datetime import datetime
import shutil

import cv2
import numpy as np

from .. import config

logger = logging.getLogger(__name__)

# Maximum dimensions for the analysis copy used in metric computation.
# Full-page screenshots can exceed 10 000 px in height, which causes
# MemoryError inside cv2.Laplacian / lap.var().  The analysis copy is
# downscaled to fit within these bounds while preserving aspect ratio.
_MAX_ANALYSIS_WIDTH = 1200
_MAX_ANALYSIS_HEIGHT = 2000


def _create_analysis_image(image: np.ndarray) -> np.ndarray:
    """Return a down-sampled copy of *image* suitable for metric computation.

    If either dimension exceeds the safe maximum (1200×2000) the image is
    resized with ``cv2.INTER_AREA`` (preserving aspect ratio) so that both
    dimensions fit within the bounds.  Otherwise a copy of the original is
    returned so callers never mutate the source.
    """
    h, w = image.shape[:2]
    if w <= _MAX_ANALYSIS_WIDTH and h <= _MAX_ANALYSIS_HEIGHT:
        return image.copy()

    scale = min(_MAX_ANALYSIS_WIDTH / w, _MAX_ANALYSIS_HEIGHT / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


@dataclass
class ScreenshotQuality:
    """Rich quality report for screenshots (pass/fail + diagnostics)."""
    valid: bool = False
    score: int = 0
    variance: float = 0.0
    stddev: float = 0.0
    brightness: float = 0.0
    entropy: float = 0.0
    dimensions: tuple[int, int] = (0, 0)
    reason: Optional[str] = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreenshotMetrics:
    """All raw metrics collected before decision (per approved design)."""
    width: int = 0
    height: int = 0
    mean_brightness: float = 0.0
    stddev: float = 0.0
    laplacian_variance: float = 0.0
    entropy: float = 0.0
    white_ratio: float = 0.0
    black_ratio: float = 0.0
    edge_density: float = 0.0
    # Debug metrics for memory-bounded analysis
    original_size: str = ""
    analysis_size: str = ""
    original_pixel_count: int = 0
    analysis_pixel_count: int = 0
    analysis_width: int = 0
    analysis_height: int = 0


class ScreenshotValidator:
    """Base for pluggable validators."""
    def validate(self, image: np.ndarray) -> ScreenshotQuality:
        raise NotImplementedError("Subclasses must implement validate")


class DimensionValidator(ScreenshotValidator):
    """Checks image dimensions against minimum."""
    def validate(self, image: np.ndarray) -> ScreenshotQuality:
        h, w = image.shape[:2]
        valid = w >= config.MIN_DIMENSION and h >= config.MIN_DIMENSION
        reason = None if valid else f"too_small_{w}x{h}"
        score = 20 if valid else 0
        return ScreenshotQuality(
            valid=valid,
            score=score,
            dimensions=(w, h),
            reason=reason,
            diagnostics={"width": w, "height": h},
        )


class VarianceValidator(ScreenshotValidator):
    """Variance (from Laplacian) for sharpness/detail."""
    def validate(self, image: np.ndarray) -> ScreenshotQuality:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(lap.var())
        valid = variance > config.SCREENSHOT_VARIANCE_THRESHOLD
        reason = None if valid else "low_variance"
        score = min(30, int(variance / 50)) if valid else 0
        return ScreenshotQuality(
            valid=valid,
            score=score,
            variance=variance,
            reason=reason,
            diagnostics={"variance": variance},
        )


class BrightnessValidator(ScreenshotValidator):
    """Brightness and stddev to reject uniform white/black."""
    def validate(self, image: np.ndarray) -> ScreenshotQuality:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        stddev = float(np.std(gray))
        valid = (40 < brightness < 220) and stddev > config.MIN_STDDEV
        reason = None if valid else ("all_white" if brightness > 220 else "all_black" if brightness < 40 else "low_contrast")
        score = 25 if valid else 0
        return ScreenshotQuality(
            valid=valid,
            score=score,
            brightness=brightness,
            stddev=stddev,
            reason=reason,
            diagnostics={"brightness": brightness, "stddev": stddev},
        )


class EntropyValidator(ScreenshotValidator):
    """Image entropy to catch low-information images (complements variance)."""
    def validate(self, image: np.ndarray) -> ScreenshotQuality:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist / hist.sum()
        hist = hist[hist > 0]
        entropy = -np.sum(hist * np.log2(hist)) if len(hist) > 0 else 0.0
        valid = bool(entropy > 1.0)  # Low threshold for web content; ensure Python bool
        reason = None if valid else "low_entropy"
        score = min(25, int(entropy * 10)) if valid else 0
        return ScreenshotQuality(
            valid=valid,
            score=score,
            entropy=entropy,
            reason=reason,
            diagnostics={"entropy": entropy},
        )


class ScreenshotDecisionEngine:
    """Single decision point using all metrics (no early exit, explicit rules)."""
    def decide(self, metrics: ScreenshotMetrics) -> ScreenshotQuality:
        # New robust rule per user feedback:
        # Reject only when BOTH visually empty AND statistically low-information
        is_visually_empty = (
            metrics.white_ratio > 0.95 or
            metrics.black_ratio > 0.95 or
            metrics.stddev < 8.0
        )
        is_low_information = (
            metrics.laplacian_variance < 50.0 or
            metrics.stddev < 12.0 or
            metrics.edge_density < 0.01
        )
        valid = not (is_visually_empty and is_low_information)
        reason = None if valid else "blank_or_low_information"
        # Quality score derived from strong metrics (Laplacian + stddev); no arbitrary weights
        score = int(min(100, metrics.stddev * 3 + metrics.laplacian_variance / 5))
        if score < 0:
            score = 0

        return ScreenshotQuality(
            valid=valid,
            score=score,
            variance=metrics.laplacian_variance,
            stddev=metrics.stddev,
            brightness=metrics.mean_brightness,
            entropy=metrics.entropy,
            dimensions=(metrics.width, metrics.height),
            reason=reason,
            diagnostics={
                "mean_brightness": metrics.mean_brightness,
                "stddev": metrics.stddev,
                "laplacian_variance": metrics.laplacian_variance,
                "entropy": metrics.entropy,
                "white_ratio": metrics.white_ratio,
                "black_ratio": metrics.black_ratio,
                "edge_density": metrics.edge_density,
            },
        )


def compute_metrics(image: np.ndarray) -> ScreenshotMetrics:
    """Collect all metrics in one place (no per-validator decisions).

    Expensive operations (Laplacian, Canny, entropy) are run on a
    down-sampled analysis copy to prevent MemoryError on tall pages.
    Original dimensions are preserved in the returned metrics.
    """
    h, w = image.shape[:2]
    original_pixels = w * h

    # Create a memory-safe analysis copy; expensive metrics run on this
    analysis = _create_analysis_image(image)
    ah, aw = analysis.shape[:2]
    analysis_pixels = aw * ah

    gray = cv2.cvtColor(analysis, cv2.COLOR_BGR2GRAY)

    mean_brightness = float(np.mean(gray))
    stddev = float(np.std(gray))

    # Laplacian (CV_32F to avoid float64 memory blowup on large analysis images)
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    laplacian_variance = float(lap.var())

    # Entropy (kept for diagnostics only)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist = hist / hist.sum()
    hist = hist[hist > 0]
    entropy = -np.sum(hist * np.log2(hist)) if len(hist) > 0 else 0.0

    # White/black ratios
    white_ratio = float(np.mean(gray > 240))
    black_ratio = float(np.mean(gray < 15))

    # Edge density (new structural metric)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.mean(edges > 0))

    return ScreenshotMetrics(
        width=w,
        height=h,
        mean_brightness=mean_brightness,
        stddev=stddev,
        laplacian_variance=laplacian_variance,
        entropy=entropy,
        white_ratio=white_ratio,
        black_ratio=black_ratio,
        edge_density=edge_density,
        original_size=f"{w}x{h}",
        analysis_size=f"{aw}x{ah}",
        original_pixel_count=original_pixels,
        analysis_pixel_count=analysis_pixels,
        analysis_width=aw,
        analysis_height=ah,
    )


def validate_screenshot(image_path: str | Path) -> ScreenshotQuality:
    """Orchestrator: collects ALL metrics first, then uses DecisionEngine.
    No early exit. Fully matches approved design and constraints.

    Hardened against OpenCV / NumPy / memory errors so a validation failure
    never crashes the scraper or desktop app.  On unexpected errors a
    degraded ``ScreenshotQuality(valid=False, reason="validator_crash")`` is
    returned so the pipeline can continue gracefully.
    """
    path = Path(image_path)
    if not path.exists():
        return ScreenshotQuality(valid=False, reason="file_not_found", score=0)

    try:
        image = cv2.imread(str(path))
    except Exception as exc:
        logger.error("cv2.imread raised for %s: %s", path, exc)
        return ScreenshotQuality(
            valid=False, reason="validator_crash", score=0,
            diagnostics={"error": f"imread: {exc}", "path": str(path)},
        )

    if image is None:
        return ScreenshotQuality(valid=False, reason="invalid_image", score=0)

    try:
        # New flow: compute all metrics first
        metrics = compute_metrics(image)
    except Exception as exc:
        logger.error("compute_metrics raised for %s (%dx%d): %s",
                     path, image.shape[1], image.shape[0], exc)
        return ScreenshotQuality(
            valid=False, reason="validator_crash", score=0,
            diagnostics={
                "error": f"compute_metrics: {exc}",
                "path": str(path),
                "dimensions": (image.shape[1], image.shape[0]),
            },
        )

    # Single decision
    engine = ScreenshotDecisionEngine()
    quality = engine.decide(metrics)
    quality.diagnostics["path"] = str(path)
    quality.diagnostics["metrics"] = metrics.__dict__

    if config.DEBUG:
        # Enhanced debug with all real metrics (Second Task completed)
        print(f"[VALIDATOR_DEBUG] width={metrics.width} height={metrics.height} "
              f"mean_brightness={metrics.mean_brightness:.2f} stddev={metrics.stddev:.2f} "
              f"entropy={metrics.entropy:.4f} laplacian_variance={metrics.laplacian_variance:.2f} "
              f"white_pct={metrics.white_ratio*100:.2f} black_pct={metrics.black_ratio*100:.2f} "
              f"edge_density={metrics.edge_density:.4f} reason={quality.reason or 'valid'} "
              f"score={quality.score}")

    if config.DEBUG and not quality.valid:
        _save_rejected_screenshot(path, quality)

    return quality


def _save_rejected_screenshot(original_path: Path, quality: ScreenshotQuality) -> None:
    """Save copy to debug/rejected/ with diagnostic name (debug only)."""
    import shutil
    from datetime import datetime

    os.makedirs(config.DEBUG_REJECTED_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    reason = quality.reason or "unknown"
    name = f"{reason}_{timestamp}_{original_path.name}"
    dest = Path(config.DEBUG_REJECTED_FOLDER) / name
    shutil.copy2(original_path, dest)
    print(f"[DEBUG] Rejected screenshot saved: {dest} (reason: {reason}, score: {quality.score})")
