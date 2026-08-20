"""Qt controller for the Sprint 5W Campaign Run workspace.

A thin shell over :class:`gui.services.campaign_run.CampaignRunService`. It
exposes Qt signals, invokes the read-only orchestration service, tracks the
active run + selected prospect, and emits read-only navigation requests.

It performs NO stage mutations. The only persisted mutations are run
scope/identity (create/add/remove/rename/delete run) — never canonical
prospect/research/opportunity/generation/review/package/Smartlead state.
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from gui.services.campaign_run import (
    CampaignRunProspectRow,
    CampaignRunService,
    CampaignRunSnapshot,
)
from gui.services.campaign_assembly import CampaignAssemblyService


class CampaignRunController(QObject):
    runs_changed = Signal(object)
    run_opened = Signal(object)
    rows_changed = Signal(object)
    summary_changed = Signal(object)
    assembly_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)
    open_prospect_requested = Signal(str)
    open_project_requested = Signal(str)
    open_review_requested = Signal(object)
    open_smartlead_requested = Signal()
    open_pipeline_requested = Signal(str)
    continue_requested = Signal(str)

    def __init__(self, *, service: CampaignRunService, assembly_service: CampaignAssemblyService | None = None) -> None:
        super().__init__()
        self._service = service
        self._assembly_service = assembly_service
        self._active_run_id: Optional[str] = None
        self._selected_prospect_id: Optional[str] = None
        self._package_directory: Optional[str] = None
        self._last_snapshot: Optional[CampaignRunSnapshot] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def service(self) -> CampaignRunService:
        return self._service

    @property
    def assembly_service(self) -> CampaignAssemblyService | None:
        return self._assembly_service

    def set_assembly_service(self, assembly_service: CampaignAssemblyService | None) -> None:
        self._assembly_service = assembly_service

    def active_run_id(self) -> Optional[str]:
        return self._active_run_id

    def active_run(self):
        return self._service.get_run(self._active_run_id) if self._active_run_id else None

    def active_prospect_ids(self) -> list[str]:
        run = self.active_run()
        return list(run.prospect_ids) if run is not None else []

    def selected_prospect_id(self) -> Optional[str]:
        return self._selected_prospect_id

    def last_snapshot(self) -> Optional[CampaignRunSnapshot]:
        return self._last_snapshot

    # ------------------------------------------------------------------
    # Run scope operations (persist ONLY identity/scope)
    # ------------------------------------------------------------------
    def list_runs(self) -> list[dict[str, Any]]:
        return [run.to_dict() for run in self._service.list_runs()]

    def create_run(
        self,
        name: str,
        prospect_ids: Any,
        *,
        source: str = "",
        source_id: str = "",
    ) -> Optional[str]:
        try:
            run = self._service.create_run(name, prospect_ids, source=source, source_id=source_id)
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Could not create campaign run: {exc}")
            return None
        self._active_run_id = run.id
        self._selected_prospect_id = None
        self._package_directory = None
        self.runs_changed.emit(self.list_runs())
        self.run_opened.emit(run.to_dict())
        self.status_message.emit(f"Created campaign run \"{run.name}\".")
        self.refresh()
        return run.id

    def open_run(self, run_id: str) -> bool:
        run = self._service.get_run(run_id)
        if run is None:
            self.error_message.emit("Campaign run not found.")
            return False
        previous_selection = self._selected_prospect_id
        self._active_run_id = run.id
        self._selected_prospect_id = previous_selection if previous_selection in set(run.prospect_ids) else None
        self._package_directory = None
        self.run_opened.emit(run.to_dict())
        self.status_message.emit(f"Opened campaign run \"{run.name}\".")
        self.refresh()
        return True

    def add_prospects(self, prospect_ids: Any) -> None:
        if not self._active_run_id:
            self.error_message.emit("No active campaign run.")
            return
        try:
            run = self._service.add_prospects(self._active_run_id, prospect_ids)
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Could not add prospects: {exc}")
            return
        self.runs_changed.emit(self.list_runs())
        self.status_message.emit(f"Run now has {len(run.prospect_ids)} prospect(s).")
        self.refresh()

    def remove_prospect(self, prospect_id: str) -> None:
        if not self._active_run_id:
            return
        try:
            self._service.remove_prospects(self._active_run_id, [prospect_id])
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Could not remove prospect: {exc}")
            return
        if self._selected_prospect_id == prospect_id:
            self._selected_prospect_id = None
        self.runs_changed.emit(self.list_runs())
        self.status_message.emit("Removed prospect from run (canonical data untouched).")
        self.refresh()

    def rename_run(self, name: str) -> None:
        if not self._active_run_id:
            return
        try:
            run = self._service.rename_run(self._active_run_id, name)
        except Exception as exc:  # noqa: BLE001
            self.error_message.emit(f"Could not rename run: {exc}")
            return
        self.runs_changed.emit(self.list_runs())
        self.run_opened.emit(run.to_dict())
        self.status_message.emit("Campaign run renamed.")

    def delete_run(self, run_id: str) -> None:
        if self._service.delete_run(run_id):
            if self._active_run_id == run_id:
                self._active_run_id = None
                self._selected_prospect_id = None
                self._package_directory = None
            self.runs_changed.emit(self.list_runs())
            self.status_message.emit("Campaign run deleted (canonical data untouched).")
            self.refresh()

    def set_package_directory(self, directory: str | None) -> None:
        """Set the known built package directory (read-only derivation hint)."""
        self._package_directory = str(directory).strip() if directory else None
        self.refresh()

    # ------------------------------------------------------------------
    # Refresh (read-only snapshot)
    # ------------------------------------------------------------------
    def refresh(self) -> CampaignRunSnapshot:
        snapshot = self._service.snapshot(
            self._active_run_id, package_directory=self._package_directory
        )
        row_ids = [row.prospect_id for row in snapshot.rows]
        if self._selected_prospect_id not in row_ids:
            self._selected_prospect_id = row_ids[0] if row_ids else None
        self._last_snapshot = snapshot
        self.rows_changed.emit([row.to_dict() for row in snapshot.rows])
        self.summary_changed.emit(snapshot.summary.to_dict())
        self._emit_assembly()
        return snapshot

    # ------------------------------------------------------------------
    # Selection + detail
    # ------------------------------------------------------------------
    def select(self, prospect_id: str) -> None:
        pid = str(prospect_id or "").strip()
        self._selected_prospect_id = pid or None

    def _last_rows(self) -> list[CampaignRunProspectRow]:
        if self._last_snapshot is not None:
            return list(self._last_snapshot.rows)
        return []

    def _current_summary_dict(self) -> dict[str, Any]:
        if self._last_snapshot is not None:
            return self._last_snapshot.summary.to_dict()
        return {}

    def detail_for(self, prospect_id: str) -> dict[str, Any]:
        for row in self._last_rows():
            if row.prospect_id == str(prospect_id or "").strip():
                return row.to_dict()
        return {}

    # ------------------------------------------------------------------
    # Read-only navigation actions (Continue Campaign + open actions)
    # ------------------------------------------------------------------
    def continue_campaign(self) -> str:
        """Derive the next workspace target from canonical state and emit it.

        Pure read-only navigation: never researches/generates/publishes/activates.
        """
        snapshot = self.refresh()
        target = self._service.continue_target(
            self.active_prospect_ids(), package_directory=self._package_directory
        )
        if target == "pipeline":
            for row in snapshot.rows:
                if str(getattr(row, "next_action", "") or "") == "Resolve Opportunity":
                    self._selected_prospect_id = row.prospect_id or None
                    if row.prospect_id:
                        self.open_pipeline_requested.emit(row.prospect_id)
                        self.continue_requested.emit(target)
                        self.status_message.emit("Continue campaign: Resolve Opportunity")
                        return target
        # When targeting review, carry the run scope so the review table is
        # scoped to this run's prospect ids.
        if target == "campaign_review":
            self.open_review_requested.emit(self.active_prospect_ids())
        elif target == "smartlead":
            self.open_smartlead_requested.emit()
        self.continue_requested.emit(target)
        self.status_message.emit(f"Continue campaign: {target.replace('_', ' ').title()}")
        return target

    def open_prospect(self, prospect_id: str | None = None) -> None:
        pid = prospect_id or self._selected_prospect_id
        if pid:
            self.open_prospect_requested.emit(pid)

    def open_project(self, prospect_id: str | None = None) -> None:
        pid = prospect_id or self._selected_prospect_id
        if not pid:
            return
        detail = self.detail_for(pid)
        project_id = str(detail.get("project_id") or "")
        if project_id:
            self.open_project_requested.emit(project_id)
        else:
            self.status_message.emit("No project is associated with this prospect yet.")

    def open_review(self) -> None:
        self.open_review_requested.emit(self.active_prospect_ids())

    def open_smartlead(self) -> None:
        self.open_smartlead_requested.emit()

    def recommended_next_action(self) -> str:
        summary = self._current_summary_dict()
        return str(summary.get("recommended_next_action") or "")

    # ------------------------------------------------------------------
    # Sprint 5AD assembly actions (delegate to existing services)
    # ------------------------------------------------------------------
    def refresh_assembly(self) -> object | None:
        return self._emit_assembly()

    def prepare_assembly_package(self) -> object | None:
        if not self._active_run_id or self._assembly_service is None:
            self.error_message.emit("No active campaign assembly service.")
            return None
        result = self._assembly_service.prepare_package(self._active_run_id)
        if result.success:
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self._emit_assembly(result)
        self.refresh()
        return result

    def export_assembly_package(self, destination: str | None = None) -> object | None:
        if not self._active_run_id or self._assembly_service is None:
            self.error_message.emit("No active campaign assembly service.")
            return None
        result = self._assembly_service.export_campaign(self._active_run_id, destination=destination)
        if result.success:
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self._emit_assembly(result)
        self.refresh()
        return result

    def exclude_from_assembly(self, prospect_id: str | None = None) -> object | None:
        return self._set_assembly_excluded(prospect_id, True)

    def include_in_assembly(self, prospect_id: str | None = None) -> object | None:
        return self._set_assembly_excluded(prospect_id, False)

    def _set_assembly_excluded(self, prospect_id: str | None, excluded: bool) -> object | None:
        pid = str(prospect_id or self._selected_prospect_id or "").strip()
        if not pid or not self._active_run_id or self._assembly_service is None:
            return None
        result = self._assembly_service.set_excluded(self._active_run_id, pid, excluded)
        if result.success:
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self._emit_assembly(result)
        self.refresh()
        return result

    def _emit_assembly(self, result: object | None = None) -> object | None:
        if not self._active_run_id or self._assembly_service is None:
            return None
        if result is None:
            result = self._assembly_service.assemble_campaign(self._active_run_id)
        snapshot = getattr(result, "snapshot", None)
        summary = getattr(result, "summary", None)
        payload = {
            "success": bool(getattr(result, "success", False)),
            "message": str(getattr(result, "message", "") or ""),
            "summary": summary.to_dict() if hasattr(summary, "to_dict") else {},
            "rows": [item.to_dict() for item in getattr(snapshot, "readiness", ())] if snapshot is not None else [],
            "snapshot": snapshot.to_dict() if hasattr(snapshot, "to_dict") else {},
        }
        self.assembly_changed.emit(payload)
        return result


