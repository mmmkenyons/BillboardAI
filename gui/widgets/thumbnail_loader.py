"""Safe thumbnail loading for the BillboardAI GUI (Sprint 3B).

Loads scaled-down previews without blocking the GUI thread or crashing on
missing/corrupt files. Uses ``QImageReader`` with ``setScaledSize`` so only the
needed resolution is decoded (no full-resolution decode per card), preserves
aspect ratio, and shows a placeholder instead of raising on failure.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

logger = logging.getLogger(__name__)

# Placeholder text shown when an image cannot be loaded.
_MISSING_TEXT = "No image"
_CORRUPT_TEXT = "Unavailable"


def load_thumbnail(path: str, max_width: int, max_height: int) -> QPixmap:
    """Return a scaled QPixmap for ``path`` (aspect preserved), or an empty one.

    Never raises: missing files, unreadable/corrupt images, and decode failures
    all return ``QPixmap()`` (empty).
    """
    if not path or not os.path.isfile(path):
        return QPixmap()
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid():
            return QPixmap()
        scaled = size.scaled(
            max_width, max_height, Qt.AspectRatioMode.KeepAspectRatio
        )
        reader.setScaledSize(scaled)
        image = reader.read()
        if image.isNull():
            return QPixmap()
        return QPixmap.fromImage(image)
    except Exception:  # noqa: BLE001 - never crash on a bad image
        logger.warning("Could not load thumbnail for %r", path)
        return QPixmap()


class ThumbnailLabel(QLabel):
    """A fixed-size label that shows a scaled image or a graceful placeholder."""

    def __init__(
        self,
        max_width: int,
        max_height: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._max_width = max_width
        self._max_height = max_height
        self.setObjectName("thumbnailPlaceholder")
        self.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.setFixedSize(max_width, max_height)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setScaledContents(False)
        self.setMinimumSize(1, 1)
        self._show_placeholder(_MISSING_TEXT)

    def set_image_path(self, path: str) -> None:
        """Load and display a thumbnail for ``path`` (safe)."""
        if not path or not os.path.isfile(path):
            self._show_placeholder(_MISSING_TEXT)
            return
        pixmap = load_thumbnail(path, self._max_width, self._max_height)
        if pixmap.isNull():
            self._show_placeholder(_CORRUPT_TEXT)
            return
        self.setText("")
        self.setPixmap(pixmap)

    def _show_placeholder(self, text: str) -> None:
        self.clear()
        self.setPixmap(QPixmap())
        self.setText(text)