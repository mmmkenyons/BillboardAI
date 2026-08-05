"""BillboardAI main window.

Thin shell hosting the application views in a stacked widget. The Home
page is shown by default; the other pages are placeholders kept hidden so
the application appearance is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
)

from gui.views.batch_page import BatchPage
from gui.views.history_page import HistoryPage
from gui.views.home_page import HomePage
from gui.views.settings_page import SettingsPage

if TYPE_CHECKING:
    from gui.controllers.app_controller import BillboardController


class MainWindow(QMainWindow):
    """Main application window for BillboardAI."""

    def __init__(self, controller: BillboardController | None = None) -> None:
        super().__init__()
        self.setWindowTitle("BillboardAI")
        self.setMinimumSize(960, 640)

        self._controller = controller

        self._build_ui()

        if self._controller is not None:
            self._controller.attach(self)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._stack = QStackedWidget(self)

        self.home_page = HomePage(self._stack)
        self.settings_page = SettingsPage(self._stack)
        self.batch_page = BatchPage(self._stack)
        self.history_page = HistoryPage(self._stack)

        self._stack.addWidget(self.home_page)
        self._stack.addWidget(self.settings_page)
        self._stack.addWidget(self.batch_page)
        self._stack.addWidget(self.history_page)

        self._stack.setCurrentWidget(self.home_page)

        self.setCentralWidget(self._stack)

    # ------------------------------------------------------------------
    # Navigation (for future use)
    # ------------------------------------------------------------------
    def show_page(self, page: str) -> None:
        """Switch to the named page ('home', 'settings', 'batch', 'history')."""
        pages = {
            "home": self.home_page,
            "settings": self.settings_page,
            "batch": self.batch_page,
            "history": self.history_page,
        }
        widget = pages.get(page)
        if widget is not None:
            self._stack.setCurrentWidget(widget)

    # ------------------------------------------------------------------
    # Backward-compatible attribute access (delegated to HomePage)
    # ------------------------------------------------------------------
    @property
    def url_input(self) -> QLineEdit:
        return self.home_page.url_input

    @property
    def template_combo(self) -> QComboBox:
        return self.home_page.template_combo

    @property
    def output_folder_input(self) -> QLineEdit:
        return self.home_page.output_folder_input

    @property
    def generate_button(self) -> QPushButton:
        return self.home_page.generate_button

    @property
    def preview_label(self) -> QLabel:
        return self.home_page.preview_label

    @property
    def progress_bar(self) -> QProgressBar:
        return self.home_page.progress_bar

    @property
    def status_label(self) -> QLabel:
        return self.home_page.status_label