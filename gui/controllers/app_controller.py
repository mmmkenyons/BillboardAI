"""Application controller for the BillboardAI GUI.

Routes user actions to the engine bridge. Kept intentionally minimal;
business logic lives behind :mod:`gui.engine_bridge`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog

from gui.engine_bridge import generate
from gui.models.app_settings import DEFAULT_OUTPUT_FOLDER
from gui.models.mockup_request import MockupRequest

if TYPE_CHECKING:
    from gui.main_window import MainWindow


class BillboardController:
    """Coordinates GUI actions with the engine bridge."""

    def __init__(self) -> None:
        self._window: MainWindow | None = None

    def attach(self, window: MainWindow) -> None:
        """Attach the controller to the main window and wire signals."""
        self._window = window
        window.home_page.output_selector.browse_requested.connect(
            self.request_output_folder
        )
        window.home_page.generate_button.clicked.connect(self.generate_mockup)

    def request_output_folder(self) -> None:
        """Open a folder picker and update the output selector."""
        if self._window is None:
            return
        selector = self._window.home_page.output_selector
        current = selector.folder() or DEFAULT_OUTPUT_FOLDER
        selected = QFileDialog.getExistingDirectory(
            self._window, "Select Output Folder", current
        )
        if selected:
            selector.set_folder(selected)
            self._window.home_page.status_label.setText(
                f"Output folder set to: {selected}"
            )

    def generate_mockup(self) -> None:
        """Handle Generate Mockup clicks.

        Routes through the engine bridge; business logic is wired in later.
        """
        if self._window is None:
            return
        page = self._window.home_page
        request = MockupRequest(
            url=page.url_input.text().strip(),
            template=page.template_combo.currentText(),
            output_folder=page.output_selector.folder(),
        )
        # The result will drive the preview/progress panels once the
        # pipeline is wired up.
        generate(request)
        page.status_label.setText("Generate Mockup clicked — pipeline coming soon.")