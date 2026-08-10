"""Deterministic text wrapping, fitting, and measurement.

All measurement uses Pillow draw.textlength / font metrics, so results are
reproducible for a given font set. Text is word-wrapped (never silently edited),
and fit_text reduces font size until content fits its rect within a max line cap
and a hard minimum size.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from engine.layout import typography
from engine.layout.model import Rect


@dataclass(frozen=True)
class FitResult:
    lines: Tuple[str, ...]
    font_size: int
    line_height: int


def greedy_wrap(text: str, font, max_width: int, draw) -> List[str]:
    """Word-wrap text to max_width using the given draw+font. Words never split."""
    words = str(text).strip().split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def fit_text(
    text: str,
    role: str,
    registry: "typography.FontRegistry",
    rect: Rect,
    max_size: int,
    min_size: int,
    max_lines: int,
    draw,
) -> Optional[FitResult]:
    """Fit text into rect, reducing size until it fits (or None if it cannot).

    Respects max_lines and a hard min_size. Returns None when no size in range
    fits, which triggers the caller's priority-drop / overflow handling.
    """
    x0, y0, x1, y1 = rect
    avail_w = max(1, (x1 - x0) - 2)
    avail_h = max(1, y1 - y0)

    for size in range(int(max_size), int(min_size) - 1, -1):
        font = registry.resolve(role, size)
        lines = greedy_wrap(text, font, avail_w, draw)
        if len(lines) > max_lines:
            continue
        line_height = typography.text_height(font)
        total_height = line_height * len(lines) + max(0, (line_height // 3)) * max(
            0, len(lines) - 1
        )
        if total_height <= avail_h:
            return FitResult(lines=tuple(lines), font_size=size, line_height=line_height)
    return None
