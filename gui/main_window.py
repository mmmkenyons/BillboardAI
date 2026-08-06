"""BillboardAI main window.

Thin shell hosting the application views in a stacked widget, with a
professional menu bar, toolbar, status bar, and keyboard shortcuts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QToolBar,
)

from gui.resources import APP_VERSION
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
        self.setWindowTitle(f"BillboardAI v{APP_VERSION}")
        self.setMinimumSize(960, 640)

        self._controller = controller

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._build_shortcuts()

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

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        self.new_mockup_action = QAction("&New Mockup", self)
        self.new_mockup_action.setShortcut(QKeySequence("Ctrl+N"))
        self.new_mockup_action.triggered.connect(self._on_new_mockup)
        file_menu.addAction(self.new_mockup_action)

        self.open_output_action = QAction("&Open Output Folder", self)
        self.open_output_action.setShortcut(QKeySequence("Ctrl+O"))
        self.open_output_action.triggered.connect(self._on_open_output_folder)
        file_menu.addAction(self.open_output_action)

        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")
        home_action = QAction("&Home", self)
        home_action.triggered.connect(lambda: self.show_page("home"))
        view_menu.addAction(home_action)

        history_action = QAction("&History", self)
        history_action.setEnabled(False)
        view_menu.addAction(history_action)

        batch_action = QAction("&Batch", self)
        batch_action.setEnabled(False)
        view_menu.addAction(batch_action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        settings_action = QAction("&Settings", self)
        settings_action.setEnabled(False)
        tools_menu.addAction(settings_action)

        batch_mode_action = QAction("&Batch Mode", self)
        batch_mode_action.setEnabled(False)
        tools_menu.addAction(batch_mode_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About BillboardAI", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.toolbar_generate = QAction("Generate", self)
        self.toolbar_generate.triggered.connect(self._on_generate)
        toolbar.addAction(self.toolbar_generate)

        self.toolbar_open_folder = QAction("Open Folder", self)
        self.toolbar_open_folder.triggered.connect(self._on_open_output_folder)
        toolbar.addAction(self.toolbar_open_folder)

        toolbar.addSeparator()
        settings_action = QAction("Settings", self)
        settings_action.setEnabled(False)
        toolbar.addAction(settings_action)

    def _build_status_bar(self) -> None:
        self.status_bar = self.statusBar()
        self.status_message = QLabel("Ready", self)
        self.status_bar.addWidget(self.status_message, 1)

        self.version_label = QLabel(f"Version {APP_VERSION}", self)
        self.status_bar.addPermanentWidget(self.version_label)

        self.output_folder_label = QLabel("", self)
        self.status_bar.addPermanentWidget(self.output_folder_label)

    def _build_shortcuts(self) -> None:
        # Ctrl+Enter -> Generate
        generate_shortcut = QAction(self)
        generate_shortcut.setShortcut(QKeySequence("Ctrl+Return"))
        generate_shortcut.triggered.connect(self._on_generate)
        self.addAction(generate_shortcut)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_status(self, message: str) -> None:
        """Update the status bar message."""
        self.status_message.setText(message)

    def set_output_folder_status(self, folder: str) -> None:
        """Update the output folder shown in the status bar."""
        self.output_folder_label.setText(f"Output Folder: {folder}")

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
    # Slots
    # ------------------------------------------------------------------
    def _on_generate(self) -> None:
        if self._controller is not None:
            self._controller.generate_mockup()

    def _on_new_mockup(self) -> None:
        if self._controller is not None:
            self._controller.new_mockup()

    def _on_open_output_folder(self) -> None:
        if self._controller is not None:
            self._controller.open_output_folder()

    def _on_about(self) -> None:
        import platform
        import sys

        from PySide6.QtCore import qVersion

        QMessageBox.about(
            self,
            "About BillboardAI",
            f"<h3>BillboardAI v{APP_VERSION}</h3>"
            "<p>AI-Powered Billboard Mockup Generator</p>"
            f"<p>Python {platform.python_version()}<br>"
            f"Qt {qVersion()}</p>"
            "<p>© 2026 BillboardAI. All rights reserved.</p>",
        )

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
        return self.status_message