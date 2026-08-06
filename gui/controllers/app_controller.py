"""Application controller for the BillboardAI GUI.

Routes user actions to the engine bridge. Handles input validation,
background threading, progress updates, and GUI state changes.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from gui.models.app_settings import DEFAULT_OUTPUT_FOLDER
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.models.recent_websites import RecentWebsitesStore
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
        self._recent = RecentWebsitesStore()
        self._success_timer: QTimer | None = None

    def attach(self, window: MainWindow) -> None:
        """Attach the controller to the main window and wire signals."""
        self._window = window
        page = window.home_page

        page.output_selector.browse_requested.connect(self.request_output_folder)
        page.generate_button.clicked.connect(self.generate_mockup)
        page.preview_panel.open_image_requested.connect(self.open_image)
        page.preview_panel.open_folder_requested.connect(self.open_output_folder)
        page.preview_panel.copy_path_requested.connect(self.copy_file_path)
        page.recent_websites.website_selected.connect(self._on_recent_selected)

        # Load recent websites into the UI.
        page.recent_websites.set_websites(self._recent.websites())
        window.set_output_folder_status(page.output_selector.folder())

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
            self._window.set_output_folder_status(selected)
            self._window.set_status(f"Output folder set to: {selected}")
            logger.info("Output folder set to: %s", selected)

    def open_output_folder(self) -> None:
        """Open the current output folder in the system file manager."""
        if self._window is None:
            return
        folder = self._window.home_page.output_selector.folder()
        if not folder or not os.path.isdir(folder):
            self._show_warning("Output Folder", "The output folder does not exist yet.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            logger.info("Opened output folder: %s", folder)
        except OSError as exc:
            logger.warning("Could not open output folder: %s", exc)

    def open_image(self) -> None:
        """Open the generated image in the system default viewer."""
        if self._window is None:
            return
        path = self._window.home_page.preview_panel.image_path()
        if not path or not os.path.isfile(path):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            logger.info("Opened image: %s", path)
        except OSError as exc:
            logger.warning("Could not open image: %s", exc)

    def copy_file_path(self) -> None:
        """Copy the generated image path to the clipboard."""
        if self._window is None:
            return
        path = self._window.home_page.preview_panel.image_path()
        if not path:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(path)
        self._window.set_status("File path copied to clipboard.")
        logger.info("Copied file path to clipboard: %s", path)

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
        self._window.set_status("Generating billboard...")
        page.progress_panel.reset()
        page.clear_result()

        logger.info("Generation started for %s", url)
        self._start_worker(request)

    def new_mockup(self) -> None:
        """Clear the current result and focus the URL field."""
        if self._window is None:
            return
        page = self._window.home_page
        page.clear_result()
        page.progress_panel.reset()
        self._window.set_status("Ready")
        page.url_input.setFocus()
        logger.info("New mockup requested")

    def _start_worker(self, request: MockupRequest) -> None:
        """Create and start the background generation worker."""
        thread = QThread()
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
        """Update the progress bar, stage label, and status bar."""
        if self._window is None:
            return
        page = self._window.home_page
        page.progress_panel.set_progress(percent, message, stage)
        self._window.set_status(message)

    def _on_finished(self, result: MockupResult) -> None:
        """Handle a completed generation."""
        if self._window is None:
            return
        page = self._window.home_page

        if result.success:
            page.set_result(result)
            self._recent.add(result.website)
            page.recent_websites.set_websites(self._recent.websites())
            self._window.set_status("✓ Mockup generated successfully")
            self._show_success_notification()
            logger.info("Generation completed: %s", result.preview_path)
        else:
            self._window.set_status("Generation failed")
            QMessageBox.critical(
                self._window,
                "Generation Failed",
                result.message or "An unknown error occurred.",
            )
            logger.error("Generation failed: %s", result.message)

        self._set_busy(False)

    def _on_failed(self, error: str) -> None:
        """Handle an unexpected worker failure."""
        if self._window is None:
            return
        self._window.set_status("Generation failed")
        QMessageBox.critical(
            self._window,
            "Generation Failed",
            f"An unexpected error occurred:\n{error}",
        )
        logger.error("Unexpected generation failure: %s", error)
        self._set_busy(False)

    def _cleanup_thread(self) -> None:
        """Clean up the finished thread and worker."""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    # ------------------------------------------------------------------
    # Recent websites
    # ------------------------------------------------------------------
    def _on_recent_selected(self, url: str) -> None:
        """Populate the URL field when a recent website is selected."""
        if self._window is None:
            return
        self._window.home_page.url_input.setText(url)
        self._window.set_status(f"Selected: {url}")
        logger.info("Recent website selected: %s", url)

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
        self._window.toolbar_generate.setEnabled(not busy)

    def _show_success_notification(self) -> None:
        """Briefly show a success message in the status bar."""
        if self._window is None:
            return
        if self._success_timer is not None:
            self._success_timer.stop()
        self._window.set_status("✓ Mockup generated successfully")
        timer = QTimer(self._window)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda: self._window.set_status("Completed successfully.")
        )
        timer.start(4000)
        self._success_timer = timer

    def _show_warning(self, title: str, message: str) -> None:
        if self._window is not None:
            QMessageBox.warning(self._window, title, message)