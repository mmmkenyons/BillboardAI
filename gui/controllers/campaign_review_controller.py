"""Qt controller for the campaign review workspace."""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QObject, Signal

from gui.services.campaign_review import CampaignReviewService


class CampaignReviewController(QObject):
    rows_changed = Signal(object)
    selection_changed = Signal(object)
    summary_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)
    open_project_requested = Signal(str)

    def __init__(self, *, service: CampaignReviewService) -> None:
        super().__init__()
        self._service = service
        self._selected_ids: list[str] = []
        self._scope_ids: list[str] | None = None
        self._filter = "ALL"

    def set_scope(self, prospect_ids: list[str] | None) -> None:
        self._scope_ids = [prospect_id for prospect_id in (prospect_ids or []) if str(prospect_id or "").strip()] or None
        self.refresh()

    def set_filter(self, filter_name: str) -> None:
        self._filter = str(filter_name or "ALL").strip().upper()
        self.refresh()

    def refresh(self) -> None:
        rows = self._service.list_rows(self._scope_ids)
        filtered = self._service.filter_rows(rows, self._filter)
        payload = [self._row_to_dict(row) for row in filtered]
        self.rows_changed.emit(payload)
        self.summary_changed.emit(self._service.summary(self._scope_ids))
        if self._selected_ids:
            self.selection_changed.emit(self.detail_for(self._selected_ids[0]))

    def detail_for(self, prospect_id: str) -> dict:
        row = self._service.list_rows([prospect_id])[0]
        return self._row_to_dict(row)

    def select(self, prospect_id: str) -> None:
        self._selected_ids = [str(prospect_id or "").strip()] if str(prospect_id or "").strip() else []
        if self._selected_ids:
            self.selection_changed.emit(self.detail_for(self._selected_ids[0]))

    def approve(self, prospect_id: str) -> None:
        self._service.approve(prospect_id)
        self.status_message.emit("Prospect approved.")
        self.refresh()

    def exclude(self, prospect_id: str) -> None:
        self._service.exclude(prospect_id)
        self.status_message.emit("Prospect excluded.")
        self.refresh()

    def mark_needs_review(self, prospect_id: str) -> None:
        self._service.mark_needs_review(prospect_id)
        self.status_message.emit("Prospect marked needs review.")
        self.refresh()

    def save_note(self, prospect_id: str, note: str) -> None:
        self._service.update_note(prospect_id, note)
        self.status_message.emit("Review note saved.")
        self.refresh()

    def bulk_approve(self, prospect_ids: list[str]) -> None:
        self._service.bulk_approve(prospect_ids)
        self.status_message.emit(f"Approved {len(prospect_ids)} prospect(s).")
        self.refresh()

    def bulk_exclude(self, prospect_ids: list[str]) -> None:
        self._service.bulk_exclude(prospect_ids)
        self.status_message.emit(f"Excluded {len(prospect_ids)} prospect(s).")
        self.refresh()

    def bulk_mark_needs_review(self, prospect_ids: list[str]) -> None:
        self._service.bulk_mark_needs_review(prospect_ids)
        self.status_message.emit(f"Marked {len(prospect_ids)} prospect(s) needs review.")
        self.refresh()

    def open_project(self, prospect_id: str) -> None:
        project_id = self._service.open_project_id(prospect_id)
        if not project_id:
            self.error_message.emit("No project available for this prospect.")
            return
        self.open_project_requested.emit(project_id)

    def open_mockup(self, prospect_id: str) -> None:
        row = self._service.list_rows([prospect_id])[0]
        if not row.mockup_path or not os.path.isfile(row.mockup_path):
            self.error_message.emit("Mockup file is missing.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(row.mockup_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", row.mockup_path])
            else:
                subprocess.Popen(["xdg-open", row.mockup_path])
        except OSError as exc:
            self.error_message.emit(f"Could not open mockup:\n{exc}")

    def open_mockup_folder(self, prospect_id: str) -> None:
        row = self._service.list_rows([prospect_id])[0]
        folder = os.path.dirname(row.mockup_path) if row.mockup_path else ""
        if not folder or not os.path.isdir(folder):
            self.error_message.emit("Mockup folder is missing.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as exc:
            self.error_message.emit(f"Could not open folder:\n{exc}")

    def build_approved_package(self, destination: str, campaign_name: str | None = None) -> object:
        result = self._service.build_approved_package(self._scope_ids, destination, campaign_name=campaign_name)
        if getattr(result, "success", False):
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self.refresh()
        return result

    def _row_to_dict(self, row: object) -> dict:
        return {
            "prospect_id": getattr(row, "prospect_id", ""),
            "company": getattr(row, "company", ""),
            "email": getattr(row, "email", ""),
            "contact_name": getattr(row, "contact_name", ""),
            "city": getattr(row, "city", ""),
            "state": getattr(row, "state", ""),
            "category": getattr(row, "category", ""),
            "website": getattr(row, "website", ""),
            "email_subject": getattr(row, "email_subject", ""),
            "email_body": getattr(row, "email_body", ""),
            "mockup_path": getattr(row, "mockup_path", ""),
            "opportunity_display": getattr(row, "opportunity_display", ""),
            "creative_summary": getattr(row, "creative_summary", ""),
            "placement_name": getattr(row, "placement_name", ""),
            "placement_type": getattr(row, "placement_type", ""),
            "technical_status": getattr(row, "technical_status", ""),
            "technical_reasons": list(getattr(row, "technical_reasons", ()) or ()),
            "technical_warnings": list(getattr(row, "technical_warnings", ()) or ()),
            "review_status": getattr(row, "review_status", ""),
            "review_note": getattr(row, "review_note", ""),
            "reviewed_at": getattr(row, "reviewed_at", ""),
            "project_id": getattr(row, "project_id", ""),
            "packageable": bool(getattr(row, "packageable", False)),
        }