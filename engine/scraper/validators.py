"""Pluggable screenshot validators for quality checks.

Implements the validator framework per sprint plan. Each validator returns
part of ScreenshotQuality. Orchestrator combines them.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional
import os
from datetime import datetime
import shutil

import cv2
import numpy as np

from .. import config


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
    """Collect all metrics in one place (no per-validator decisions)."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    mean_brightness = float(np.mean(gray))
    stddev = float(np.std(gray))
    
    # Laplacian
    lap = cv2.Laplacian(gray, cv2.CV_64F)
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
    )


def validate_screenshot(image_path: str | Path) -> ScreenshotQuality:
    """Orchestrator: collects ALL metrics first, then uses DecisionEngine.
    No early exit. Fully matches approved design and constraints.
    """
    path = Path(image_path)
    if not path.exists():
        return ScreenshotQuality(valid=False, reason="file_not_found", score=0)

    image = cv2.imread(str(path))
    if image is None:
        return ScreenshotQuality(valid=False, reason="invalid_image", score=0)

    # New flow: compute all metrics first
    metrics = compute_metrics(image)
    
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
