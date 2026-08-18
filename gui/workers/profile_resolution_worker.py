"""Sprint 5Z profile resolution worker (Qt).

Runs the Qt-free :class:`~gui.services.profile_resolver.ProfileResolverService`
off the GUI thread, mirroring the existing generation/research workers: a plain
``QObject`` is moved to a ``QThread``, only emits signals, and never creates
QObject children or touches widgets from the worker thread.

The unit of work is the prospect list captured by the controller. The worker
resolves each prospect (person+parent website -> individual profile), applies
the result onto the in-memory ``Prospect`` object, and emits a single
``finished`` payload ``(prospects, results)`` so the GUI thread can persist once
(no duplicated signal execution).
"""

from __future__ import annotations

import logging
from typing import List, Sequence, Tuple

from PySide6.QtCore import QObject, Signal

from gui.models.prospect import Prospect
from gui.services.profile_resolver import (
    RESOLUTION_ERROR,
    ProfileResolverService,
    ResolutionResult,
)

logger = logging.getLogger(__name__)


class ProfileResolutionWorker(QObject):
    """Resolve a bounded list of prospects on a background QThread."""

    progress = Signal(str, str)  # prospect_id, status
    finished = Signal(object)  # tuple[list[Prospect], list[ResolutionResult]]
    failed = Signal(str)

    def __init__(
        self,
        service: ProfileResolverService,
        prospects: Sequence[Prospect],
    ) -> None:
        super().__init__()
        self._service = service
        self._prospects: List[Prospect] = list(prospects)

    def run(self) -> None:
        """Resolve every prospect; always finish with one payload."""
        results: List[ResolutionResult] = []
        try:
            for prospect in self._prospects:
                person = (prospect.contact_name or prospect.company_name or "").strip()
                result = self._service.resolve(person, prospect.website)
                self._service.apply_result(prospect, result)
                results.append(result)
                self.progress.emit(prospect.prospect_id, result.status)
            self.finished.emit((self._prospects, results))
        except Exception as exc:  # noqa: BLE001 - never crash the GUI
            logger.exception("Profile resolution batch failed")
            self.failed.emit(str(exc))