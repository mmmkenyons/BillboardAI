"""Background worker that runs the generation pipeline off the GUI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from gui.engine_bridge import generate
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult

logger = logging.getLogger(__name__)


class GenerationWorker(QObject):
    """Runs :func:`gui.engine_bridge.generate` in a worker thread.

    Emits progress updates and the final result so the GUI thread can
    update widgets without blocking.
    """

    progress = Signal(int, str, str)  # percent, message, stage
    finished = Signal(object)  # MockupResult
    failed = Signal(str)  # error message

    def __init__(self, request: MockupRequest) -> None:
        super().__init__()
        self._request = request

    def run(self) -> None:
        """Execute the generation pipeline (called in the worker thread)."""
        logger.info("Pipeline started for %s", self._request.url)

        def _on_progress(percent: int, message: str, stage: str | None = None) -> None:
            self.progress.emit(percent, message, stage or "")

        try:
            result = generate(self._request, progress_callback=_on_progress)
            logger.info("Pipeline finished: success=%s", result.success)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - never crash the GUI
            logger.exception("Pipeline failed")
            self.failed.emit(str(exc))