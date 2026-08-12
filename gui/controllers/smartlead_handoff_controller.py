"""Qt controller for Smartlead handoff preflight and artifact generation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from gui.services.smartlead_handoff import SmartleadHandoffService


class SmartleadHandoffController(QObject):
    summary_changed = Signal(object)
    rows_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)

    def __init__(self, *, service: SmartleadHandoffService) -> None:
        super().__init__()
        self._service = service

    def prepare(self, package_directory: str) -> object:
        result = self._service.prepare_handoff(package_directory)
        if getattr(result, "summary", None) is not None:
            self.summary_changed.emit(result.summary)
        self.rows_changed.emit([row.to_dict() for row in getattr(result, "rows", ())])
        if getattr(result, "success", False):
            self.status_message.emit(result.message)
        else:
            if getattr(result, "rows", ()):
                self.status_message.emit(result.message)
            else:
                self.error_message.emit(result.message)
        return result
