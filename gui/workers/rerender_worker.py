"""Background worker for local (no-scrape) billboard re-renders."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

from gui.engine_bridge import re_render
from engine.scraper.site import ScreenshotValidationError

logger = logging.getLogger(__name__)


class ReRenderWorker(QObject):
    """Runs :func:`gui.engine_bridge.re_render` off the GUI thread.

    Pass a **complete** effective ``render_context`` (project baseline merged
    with concept overrides). The worker does not invent theme/assets.
    """

    progress = Signal(int, str, str)  # percent, message, stage
    finished = Signal(object)  # MockupResult
    failed = Signal(str)  # error message

    def __init__(
        self,
        *,
        render_context: dict[str, Any],
        output_path: str,
        concept_id: str = "",
        # Optional legacy overrides (merged by bridge if provided).
        template: str | None = None,
        headline: str | None = None,
        cta: str | None = None,
        company: str | None = None,
        logo_path: str | None = None,
    ) -> None:
        super().__init__()
        self._render_context = render_context
        self._output_path = output_path
        self.concept_id = concept_id
        self._template = template
        self._headline = headline
        self._cta = cta
        self._company = company
        self._logo_path = logo_path

    def run(self) -> None:
        """Execute the local re-render pipeline (worker thread)."""
        logger.info(
            "Re-render started for concept=%s → %s",
            self.concept_id or "?",
            self._output_path,
        )

        def _on_progress(percent: int, message: str, stage: str | None = None) -> None:
            self.progress.emit(percent, message, stage or "")

        try:
            kwargs: dict[str, Any] = {
                "render_context": self._render_context,
                "output_path": self._output_path,
                "progress_callback": _on_progress,
            }
            if self._template is not None:
                kwargs["template"] = self._template
            if self._headline is not None:
                kwargs["headline"] = self._headline
            if self._cta is not None:
                kwargs["cta"] = self._cta
            if self._company is not None:
                kwargs["company"] = self._company
            if self._logo_path is not None:
                kwargs["logo_path"] = self._logo_path

            result = re_render(**kwargs)
            result.extra = dict(result.extra or {})
            result.extra["concept_id"] = self.concept_id
            logger.info("Re-render finished: success=%s", result.success)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - never crash the GUI
            logger.exception("Re-render worker failed")
            self.failed.emit(str(exc))
