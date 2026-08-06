"""Recent websites widget for the BillboardAI GUI."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

_EMPTY_TEXT = "No recent websites."


class RecentWebsites(QFrame):
    """Displays the list of recently generated websites.

    Selecting an entry emits :attr:`website_selected`.
    """

    website_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("recentPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        heading = QLabel("Recent Websites", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        self.empty_label = QLabel(_EMPTY_TEXT, self)
        self.empty_label.setObjectName("emptyState")
        layout.addWidget(self.empty_label)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("recentList")
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_websites(self, websites: list[str]) -> None:
        """Populate the list with the given websites."""
        self.list_widget.clear()
        for url in websites:
            self.list_widget.addItem(QListWidgetItem(url))

        has_items = self.list_widget.count() > 0
        self.list_widget.setVisible(has_items)
        self.empty_label.setVisible(not has_items)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.website_selected.emit(item.text())