"""Qt controller for Smartlead handoff preflight, hosted mockups, sequence
readiness, and safe URL sync (Sprint 5R)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from gui.models.smartlead_publication import SmartleadPublishTarget
from gui.services.smartlead_activation import SmartleadActivationService
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_pilot import SmartleadPilotService
from gui.services.smartlead_publish import SmartleadPublishService
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


class SmartleadHandoffController(QObject):
    summary_changed = Signal(object)
    rows_changed = Signal(object)
    status_message = Signal(str)
    error_message = Signal(str)
    connection_changed = Signal(object)
    campaigns_changed = Signal(object)
    publish_result_changed = Signal(object)
    hosting_connection_changed = Signal(object)
    hosting_summary_changed = Signal(object)
    readiness_changed = Signal(object)
    url_sync_changed = Signal(object)
    reconciliation_changed = Signal(object)
    launch_readiness_changed = Signal(object)
    activation_result_changed = Signal(object)
    pilot_changed = Signal(object)
    pilot_list_changed = Signal(object)
    pilot_preflight_changed = Signal(object)
    pilot_activation_changed = Signal(object)
    pilot_pause_changed = Signal(object)
    run_context_changed = Signal(object)

    def __init__(
        self,
        *,
        service: SmartleadHandoffService,
        publish_service: SmartleadPublishService | None = None,
        hosting_service: object | None = None,
        sequence_service: object | None = None,
        reconciliation_service: SmartleadReconciliationService | None = None,
        activation_service: SmartleadActivationService | None = None,
        pilot_service: SmartleadPilotService | None = None,
        run_handoff_service: SmartleadRunHandoffService | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._publish_service = publish_service
        self._hosting_service = hosting_service
        self._sequence_service = sequence_service
        self._reconciliation_service = reconciliation_service
        self._activation_service = activation_service
        self._pilot_service = pilot_service
        self._run_handoff_service = run_handoff_service
        self._last_result = None
        self._active_run_id = ""

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

    def open_run_context(self, campaign_run_id: str) -> object:
        self._active_run_id = str(campaign_run_id or "").strip()
        if self._run_handoff_service is None or not self._active_run_id:
            return None
        context = self._run_handoff_service.context_for_run(self._active_run_id)
        self.run_context_changed.emit(context)
        self.summary_changed.emit(context.summary.to_dict())
        self.rows_changed.emit([row.to_dict() for row in context.rows])
        return context

    def prepare_run_package(self) -> object:
        if self._run_handoff_service is None or not self._active_run_id:
            return None
        context = self._run_handoff_service.prepare_package_for_run(self._active_run_id)
        self.run_context_changed.emit(context)
        self.summary_changed.emit(context.summary.to_dict())
        self.rows_changed.emit([row.to_dict() for row in context.rows])
        if getattr(context.summary, "handoff_directory", ""):
            self.status_message.emit("Smartlead package prepared.")
        return context

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

    # ------------------------------------------------------------------
    # Hosting + sequence + URL sync (Sprint 5R)
    # ------------------------------------------------------------------
    def test_hosting_connection(self) -> object:
        if self._hosting_service is None:
            result = type("HostingConnectionResult", (), {"connected": False, "status": "UNAVAILABLE", "message": "Hosting service unavailable."})()
        else:
            result = self._hosting_service.test_connection()
        self.hosting_connection_changed.emit(result)
        return result

    def hosting_dry_run(self, package_directory: str, handoff_directory: str) -> object:
        if self._hosting_service is None:
            result = None
        else:
            result = self._hosting_service.dry_run(package_directory, handoff_directory)
        if result is not None:
            self.hosting_summary_changed.emit(result)
        return result

    def host_mockups(
        self,
        package_directory: str,
        handoff_directory: str,
        *,
        mode: str,
        live_enabled: bool,
        confirmed: bool,
    ) -> object:
        if self._hosting_service is None:
            result = None
        else:
            result = self._hosting_service.host(
                package_directory,
                handoff_directory,
                mode=mode,
                live_enabled=live_enabled,
                confirmed=confirmed,
            )
        if result is not None:
            self.hosting_summary_changed.emit(result)
            if getattr(result, "success", False):
                self.status_message.emit(result.message)
            else:
                self.error_message.emit(result.message)
        return result

    def refresh_sequence_readiness(self, campaign_id: str) -> object:
        if self._sequence_service is None:
            result = None
        else:
            result = self._sequence_service.check_readiness(campaign_id)
        if result is not None:
            self.readiness_changed.emit(result)
        return result

    def prepare_sequence(
        self,
        campaign_id: str,
        *,
        live_enabled: bool,
        confirmed: bool,
    ) -> object:
        if self._sequence_service is None:
            result = None
        else:
            result = self._sequence_service.prepare_sequence(
                campaign_id,
                live_enabled=live_enabled,
                confirmed=confirmed,
                mode="LIVE" if live_enabled else "DRY_RUN",
            )
        if result is not None:
            self.readiness_changed.emit(result)
        return result

    def sync_hosted_urls(
        self,
        *,
        source_package_id: str,
        campaign_id: str,
        mode: str,
        live_enabled: bool,
        confirmed: bool,
    ) -> object:
        if self._publish_service is None:
            result = None
        else:
            result = self._publish_service.sync_hosted_urls(
                source_package_id=source_package_id,
                campaign_id=campaign_id,
                mode=mode,
                live_enabled=live_enabled,
                confirmed=confirmed,
            )
        if result is not None:
            self.url_sync_changed.emit(result)
            if getattr(result, "success", False):
                self.status_message.emit(result.message)
            else:
                self.error_message.emit(result.message)
        return result

    def refresh_reconciliation(self, *, source_package_id: str, campaign_id: str) -> object:
        if self._reconciliation_service is None:
            result = None
        else:
            result = self._reconciliation_service.reconcile_campaign(source_package_id=source_package_id, campaign_id=campaign_id)
        if result is not None:
            self.reconciliation_changed.emit(result)
        return result

    def refresh_launch_readiness(self, *, source_package_id: str, campaign_id: str) -> object:
        if self._reconciliation_service is None:
            result = None
        else:
            result = self._reconciliation_service.evaluate_launch_readiness(source_package_id=source_package_id, campaign_id=campaign_id)
        if result is not None:
            self.launch_readiness_changed.emit(result)
        return result

    def activation_preview(self, *, source_package_id: str, campaign_id: str) -> object:
        if self._activation_service is None:
            result = None
        else:
            result = self._activation_service.activation_preview(source_package_id=source_package_id, campaign_id=campaign_id)
        if result is not None:
            self.activation_result_changed.emit(result)
        return result

    def activate_campaign(
        self,
        *,
        source_package_id: str,
        campaign_id: str,
        mode: str,
        live_enabled: bool,
        confirmed: bool,
    ) -> object:
        if self._activation_service is None:
            result = None
        else:
            result = self._activation_service.activate_campaign(
                source_package_id=source_package_id,
                campaign_id=campaign_id,
                mode=mode,
                live_enabled=live_enabled,
                confirmed=confirmed,
            )
        if result is not None:
            self.activation_result_changed.emit(result)
            if getattr(result, "success", False):
                self.status_message.emit(result.message)
            else:
                self.error_message.emit(result.message)
            if self._reconciliation_service is not None:
                self.refresh_reconciliation(source_package_id=source_package_id, campaign_id=campaign_id)
                self.refresh_launch_readiness(source_package_id=source_package_id, campaign_id=campaign_id)
            if self._sequence_service is not None:
                self.refresh_sequence_readiness(campaign_id)
        return result

    def resume_publication(
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
            result = self._publish_service.resume_publication(
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

    def refresh_pilots(self) -> list[object]:
        pilots = self._pilot_service.list_pilots() if self._pilot_service is not None else []
        self.pilot_list_changed.emit(pilots)
        return pilots

    def create_pilot(
        self,
        *,
        campaign_id: str,
        campaign_name: str,
        source_package_id: str,
        source_handoff_path: str,
        selected_prospect_ids: list[str],
        selected_emails: list[str],
    ) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.create_pilot(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            source_handoff_path=source_handoff_path,
            selected_prospect_ids=selected_prospect_ids,
            selected_emails=selected_emails,
        )
        self.pilot_changed.emit(result)
        self.refresh_pilots()
        self.status_message.emit(f"Pilot created with {len(getattr(result, 'recipients', ())) } recipients.")
        return result

    def preflight_pilot(self, pilot_id: str) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.preflight_pilot(pilot_id)
        self.pilot_preflight_changed.emit(result)
        self.pilot_changed.emit(result.pilot)
        if getattr(result, "success", False):
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self.refresh_pilots()
        return result

    def dry_run_pilot(self, pilot_id: str) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.dry_run_activation(pilot_id)
        self.pilot_activation_changed.emit(result)
        return result

    def activate_pilot(self, pilot_id: str, *, confirmed: bool) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.activate_pilot(pilot_id, confirmed=confirmed)
        self.pilot_activation_changed.emit(result)
        self.pilot_changed.emit(result.pilot)
        if getattr(result, "success", False):
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self.refresh_pilots()
        return result

    def refresh_pilot_status(self, pilot_id: str) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.refresh_pilot_status(pilot_id)
        self.pilot_changed.emit(result)
        self.refresh_pilots()
        self.status_message.emit("Pilot status refreshed.")
        return result

    def pause_pilot(self, pilot_id: str, *, confirmed: bool) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.pause_pilot(pilot_id, confirmed=confirmed)
        self.pilot_pause_changed.emit(result)
        self.pilot_changed.emit(result.pilot)
        if getattr(result, "success", False):
            self.status_message.emit(result.message)
        else:
            self.error_message.emit(result.message)
        self.refresh_pilots()
        return result

    def mark_pilot_review_complete(self, pilot_id: str) -> object:
        if self._pilot_service is None:
            return None
        result = self._pilot_service.mark_review_complete(pilot_id)
        self.pilot_changed.emit(result)
        self.refresh_pilots()
        self.status_message.emit("Pilot review marked complete.")
        return result
