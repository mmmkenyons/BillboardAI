"""Application controller for the BillboardAI GUI.

Routes user actions to the engine bridge. Handles input validation,
background threading, progress updates, and GUI state changes.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog, QMessageBox

from gui.models.app_settings import DEFAULT_OUTPUT_FOLDER
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.workers.generation_worker import GenerationWorker

if TYPE_CHECKING:
    from gui.main_window import MainWindow

logger = logging.getLogger(__name__)

_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def normalize_url(raw: str) -> str:
    """Normalize a user-entered URL, prepending https:// when needed."""
    url = raw.strip()
    if not url:
        return ""
    if not _URL_SCHEME_RE.match(url):
        url = "https://" + url
    return url


class BillboardController:
    """Coordinates GUI actions with the engine bridge."""

    def __init__(self) -> None:
        self._window: MainWindow | None = None
        self._thread: QThread | None = None
        self._worker: GenerationWorker | None = None

    def attach(self, window: MainWindow) -> None:
        """Attach the controller to the main window and wire signals."""
        self._window = window
        window.home_page.output_selector.browse_requested.connect(
            self.request_output_folder
        )
        window.home_page.generate_button.clicked.connect(self.generate_mockup)

    # ------------------------------------------------------------------
    # Output folder
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate_mockup(self) -> None:
        """Validate inputs and start generation in a background thread."""
        if self._window is None or self._is_running():
            return

        page = self._window.home_page

        # Normalize and validate the URL.
        url = normalize_url(page.url_input.text())
        if not url:
            self._show_warning("Invalid URL", "Please enter a website URL.")
            return
        if "." not in url.split("://")[-1].split("/")[0]:
            self._show_warning("Invalid URL", "Please enter a valid website URL.")
            return

        # Validate the output folder.
        output_folder = page.output_selector.folder()
        if not output_folder:
            self._show_warning("Invalid Output Folder", "Please choose an output folder.")
            return

        # Validate the template.
        template = page.selected_template
        if not template:
            self._show_warning("Invalid Template", "Please choose a template.")
            return

        request = MockupRequest(
            url=url,
            template=template,
            output_folder=output_folder,
        )

        self._set_busy(True)
        page.status_label.setText("Starting...")
        page.progress_bar.setValue(0)
        page.preview_panel.clear()

        self._start_worker(request)

    def _start_worker(self, request: MockupRequest) -> None:
        """Create and start the background generation worker."""
        thread = QThread(self._window)
        worker = GenerationWorker(request)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_thread)

        self._thread = thread
        self._worker = worker

        logger.info("Starting generation thread")
        thread.start()

    def _on_progress(self, percent: int, message: str, stage: str) -> None:
        """Update the progress bar and status label."""
        if self._window is None:
            return
        page = self._window.home_page
        page.progress_bar.setValue(percent)
        page.status_label.setText(message)

    def _on_finished(self, result: MockupResult) -> None:
        """Handle a completed generation."""
        if self._window is None:
            return
        page = self._window.home_page

        if result.success:
            page.preview_panel.set_image(result.preview_path)
            page.status_label.setText(
                f"Complete — {result.company_name or 'Mockup'} generated "
                f"in {result.elapsed_time:.1f}s"
            )
            logger.info("Preview loaded: %s", result.preview_path)
        else:
            page.status_label.setText("Generation failed")
            QMessageBox.critical(
                self._window,
                "Generation Failed",
                result.message or "An unknown error occurred.",
            )

        self._set_busy(False)

    def _on_failed(self, error: str) -> None:
        """Handle an unexpected worker failure."""
        if self._window is None:
            return
        page = self._window.home_page
        page.status_label.setText("Generation failed")
        QMessageBox.critical(
            self._window,
            "Generation Failed",
            f"An unexpected error occurred:\n{error}",
        )
        self._set_busy(False)

    def _cleanup_thread(self) -> None:
        """Clean up the finished thread and worker."""
        if self._thread is not None:
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _set_busy(self, busy: bool) -> None:
        """Enable/disable interactive controls during generation."""
        if self._window is None:
            return
        page = self._window.home_page
        page.url_input.setEnabled(not busy)
        page.template_combo.setEnabled(not busy)
        page.output_selector.setEnabled(not busy)
        page.generate_button.setEnabled(not busy)

    def _show_warning(self, title: str, message: str) -> None:
        if self._window is not None:
            QMessageBox.warning(self._window, title, message)