"""Qt controller for Smartlead handoff preflight and artifact generation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from gui.models.smartlead_publication import SmartleadPublishTarget
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_publish import SmartleadPublishService


class SmartleadHandoffController(QObject):
    summary_changed = Signal(object)
    rows_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)
    connection_changed = Signal(object)
    campaigns_changed = Signal(object)
    publish_result_changed = Signal(object)

    def __init__(self, *, service: SmartleadHandoffService, publish_service: SmartleadPublishService | None = None) -> None:
        super().__init__()
        self._service = service
        self._publish_service = publish_service
        self._last_result = None

    def prepare(self, package_directory: str) -> object:
        result = self._service.prepare_handoff(package_directory)
        self._last_result = result
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

    def set_handoff_directory(self, path: str) -> None:
        self.status_message.emit(f"Smartlead handoff directory ready: {path}")

    def test_connection(self) -> object:
        if self._publish_service is None:
            result = type("ConnectionResult", (), {"connected": False, "status": "UNAVAILABLE", "message": "Smartlead publish service unavailable."})()
        else:
            result = self._publish_service.test_connection()
        self.connection_changed.emit(result)
        return result

    def refresh_campaigns(self) -> list[object]:
        campaigns = self._publish_service.list_campaigns() if self._publish_service is not None else []
        self.campaigns_changed.emit(campaigns)
        return campaigns

    def publish(
        self,
        handoff_directory: str,
        *,
        target: SmartleadPublishTarget,
        mode: str,
        live_enabled: bool,
        confirmed: bool,
    ) -> object:
        if self._publish_service is None:
            result = None
        else:
            result = self._publish_service.publish_from_handoff(
                handoff_directory,
                target=target,
                mode=mode,
                live_enabled=live_enabled,
                confirmed=confirmed,
            )
        if result is not None:
            self.publish_result_changed.emit(result)
            if getattr(result, "success", False):
                self.status_message.emit(result.message)
            else:
                self.error_message.emit(result.message)
        return result
