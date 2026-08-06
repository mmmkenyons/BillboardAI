"""Concept gallery widget for the BillboardAI GUI.

Displays scrollable thumbnails of all mockup concepts in the current
project. Clicking a thumbnail selects that concept. Thumbnails are
cached as QPixmap so they don't need to be re-rendered from disk.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.models.mockup_concept import MockupConcept

# Thumbnail size for gallery items.
_THUMBNAIL_SIZE = 160


class ConceptGallery(QWidget):
    """Scrollable thumbnail gallery of mockup concepts.

    Emits :attr:`concept_selected` with the concept ID when a thumbnail
    is clicked.
    """

    concept_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("conceptGallery")

        self._thumbnail_cache: dict[str, QPixmap] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        self._list_widget = QListWidget(self)
        self._list_widget.setObjectName("conceptList")
        self._list_widget.setSpacing(6)
        self._list_widget.setMovement(QListWidget.Movement.Static)
        self._list_widget.setFlow(QListWidget.Flow.LeftToRight)
        self._list_widget.setWrapping(True)
        self._list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        self._list_widget.setGridSize(
            QPixmap(_THUMBNAIL_SIZE + 20, _THUMBNAIL_SIZE + 60).size().boundedTo(
                QPixmap(_THUMBNAIL_SIZE + 20, _THUMBNAIL_SIZE + 60).size()
            )
        )
        # Use icon size for thumbnails.
        from PySide6.QtCore import QSize

        self._list_widget.setIconSize(QSize(_THUMBNAIL_SIZE, _THUMBNAIL_SIZE))

        self._layout.addWidget(self._list_widget)

        # Empty state label.
        self._empty_label_text = "No concepts yet. Generate a mockup to get started."
        self._empty_label = None

    def _ensure_empty_label(self) -> None:
        if self._empty_label is None:
            from PySide6.QtWidgets import QLabel

            self._empty_label = QLabel(self._empty_label_text, self)
            self._empty_label.setObjectName("emptyState")
            self._empty_label.setAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            self._layout.insertWidget(0, self._empty_label)

    def _update_empty_state(self) -> None:
        has_items = self._list_widget.count() > 0
        if has_items:
            if self._empty_label is not None:
                self._empty_label.hide()
        else:
            self._ensure_empty_label()
            if self._empty_label is not None:
                self._empty_label.show()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_concepts(self, concepts: list[MockupConcept]) -> None:
        """Populate the gallery with the given concepts."""
        self._list_widget.clear()
        self._thumbnail_cache.clear()
        for concept in concepts:
            self._add_concept_item(concept)
        self._update_empty_state()
        # Select the currently selected concept (if any).
        selected = next(
            (c for c in concepts if c.selected), concepts[0] if concepts else None
        )
        if selected:
            self.select_concept(selected.id)

    def add_concept(self, concept: MockupConcept) -> None:
        """Add a single concept to the gallery and select it."""
        self._add_concept_item(concept)
        self._update_empty_state()
        self.select_concept(concept.id)

    def select_concept(self, concept_id: str) -> None:
        """Highlight the concept with the given ID in the gallery."""
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item and item.data(1000) == concept_id:
                self._list_widget.setCurrentItem(item)
                return

    def get_thumbnail(self, concept: MockupConcept) -> QPixmap | None:
        """Return a cached thumbnail QPixmap for the concept, or None."""
        if concept.id in self._thumbnail_cache:
            return self._thumbnail_cache[concept.id]

        pixmap = QPixmap(concept.image_path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                _THUMBNAIL_SIZE,
                _THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumbnail_cache[concept.id] = pixmap
            return pixmap
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _add_concept_item(self, concept: MockupConcept) -> None:
        """Add a single concept as a QListWidgetItem."""
        thumbnail = self.get_thumbnail(concept)
        icon = QIcon(thumbnail) if thumbnail else QIcon()

        item = QListWidgetItem(icon, "")
        item.setData(1000, concept.id)  # Store concept ID inUserRole+1

        # Set size hint for the item.
        from PySide6.QtCore import QSize

        item.setSizeHint(QSize(_THUMBNAIL_SIZE + 20, _THUMBNAIL_SIZE + 60))

        # Show quality badge as text below the thumbnail.
        quality_text = f"Q{int(concept.quality_score)}"
        item.setData(1001, quality_text)  # Store for tooltip/details

        self._list_widget.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Emit the concept ID when an item is clicked."""
        concept_id = item.data(1000)
        if concept_id:
            self.concept_selected.emit(concept_id)
