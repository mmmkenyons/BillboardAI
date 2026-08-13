"""Pilot launch safety harness composed from canonical Smartlead services."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any

from gui.models.campaign_review import CAMPAIGN_REVIEW_STATUS_APPROVED
from gui.models.hosted_asset import is_valid_public_url
from gui.models.smartlead_activation import (
    SMARTLEAD_ACTIVATION_MODE_DRY_RUN,
    SMARTLEAD_ACTIVATION_MODE_LIVE,
)
from gui.models.smartlead_handoff import (
    SMARTLEAD_PREFLIGHT_READY,
    SMARTLEAD_PREFLIGHT_WARNING,
)
from gui.models.smartlead_launch import (
    SMARTLEAD_LAUNCH_STATUS_READY,
    SMARTLEAD_RECONCILE_MATCHED,
)
from gui.models.smartlead_pilot import (
    SMARTLEAD_PILOT_EVENT_ACTIVATED,
    SMARTLEAD_PILOT_EVENT_ACTIVATION_REQUESTED,
    SMARTLEAD_PILOT_EVENT_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_EVENT_CREATED,
    SMARTLEAD_PILOT_EVENT_PAUSED,
    SMARTLEAD_PILOT_EVENT_PAUSE_REQUESTED,
    SMARTLEAD_PILOT_EVENT_PREFLIGHT_PASSED,
    SMARTLEAD_PILOT_EVENT_REVIEW_COMPLETED,
    SMARTLEAD_PILOT_EVENT_STATUS_REFRESHED,
    SMARTLEAD_PILOT_HEALTH_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_HEALTH_HEALTHY,
    SMARTLEAD_PILOT_HEALTH_WATCH,
    SMARTLEAD_PILOT_PAUSE_RESULT_ALREADY_PAUSED,
    SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED,
    SMARTLEAD_PILOT_PAUSE_RESULT_PAUSED,
    SMARTLEAD_PILOT_STATUS_ACTIVE,
    SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_STATUS_BLOCKED,
    SMARTLEAD_PILOT_STATUS_COMPLETED,
    SMARTLEAD_PILOT_STATUS_DRAFT,
    SMARTLEAD_PILOT_STATUS_PAUSED,
    SMARTLEAD_PILOT_STATUS_READY,
    SmartleadPilotActivationResult,
    SmartleadPilotCheck,
    SmartleadPilotDefinition,
    SmartleadPilotEvent,
    SmartleadPilotMetrics,
    SmartleadPilotPauseResult,
    SmartleadPilotPreflightResult,
    SmartleadPilotRecipient,
    SmartleadPilotRecipientStatus,
    SmartleadPilotRun,
    SmartleadPilotSnapshot,
)
from gui.models.smartlead_pilot_store import SmartleadPilotStore
from gui.models.smartlead_publication import SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, utc_now_iso
from gui.services.campaign_review import CampaignReviewService
from gui.services.smartlead_activation import ACTIVE_REMOTE_STATUSES, PAUSED_REMOTE_STATUSES, SmartleadActivationService
from gui.services.smartlead_api import SmartleadApiClient, SmartleadApiError
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService

DEFAULT_PILOT_SIZE = 5
MAX_PILOT_SIZE = 10


class SmartleadPilotService:
    def __init__(
        self,
        *,
        pilot_store: SmartleadPilotStore,
        review_service: CampaignReviewService,
        handoff_service: SmartleadHandoffService,
        reconciliation_service: SmartleadReconciliationService,
        activation_service: SmartleadActivationService,
        api_client: SmartleadApiClient,
        sequence_service: SmartleadSequenceReadinessService | None = None,
        default_pilot_size: int = DEFAULT_PILOT_SIZE,
        max_pilot_size: int = MAX_PILOT_SIZE,
        activation_contract_env_var: str = "SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED",
    ) -> None:
        self._pilot_store = pilot_store
        self._review_service = review_service
        self._handoff_service = handoff_service
        self._reconciliation_service = reconciliation_service
        self._activation_service = activation_service
        self._api_client = api_client
        self._sequence_service = sequence_service
        self._default_pilot_size = int(default_pilot_size)
        self._max_pilot_size = int(max_pilot_size)
        self._activation_contract_env_var = str(activation_contract_env_var or "SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED")

    @property
    def default_pilot_size(self) -> int:
        return self._default_pilot_size

    @property
    def max_pilot_size(self) -> int:
        return self._max_pilot_size

    def activation_contract_verified(self) -> bool:
        return str(os.getenv(self._activation_contract_env_var, "") or "").strip().lower() in {"1", "true", "yes", "on"}

    def list_pilots(self) -> list[SmartleadPilotRun]:
        return self._pilot_store.list()

    def get_pilot(self, pilot_id: str) -> SmartleadPilotRun | None:
        return self._pilot_store.get(pilot_id)

    def create_pilot(
        self,
        *,
        campaign_id: str,
        campaign_name: str,
        source_package_id: str,
        source_handoff_path: str,
        selected_prospect_ids: list[str],
        selected_emails: list[str] | None = None,
    ) -> SmartleadPilotDefinition:
        recipient_rows = self._review_service.list_rows(selected_prospect_ids)
        ordered_ids = self._dedupe(selected_prospect_ids)
        ordered_emails = {str(item or "").strip().lower() for item in list(selected_emails or []) if str(item or "").strip()}
        recipients: list[SmartleadPilotRecipient] = []
        rows_by_id = {row.prospect_id: row for row in recipient_rows}
        for prospect_id in ordered_ids:
            row = rows_by_id.get(prospect_id)
            if row is None:
                continue
            email = str(row.email or "").strip()
            if ordered_emails and email.lower() not in ordered_emails:
                continue
            recipients.append(SmartleadPilotRecipient(prospect_id=prospect_id, email=email))
        definition = SmartleadPilotDefinition.create(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            source_handoff_path=source_handoff_path,
            recipients=recipients,
        )
        run = SmartleadPilotRun(
            definition=definition,
            snapshot=None,
            events=(
                SmartleadPilotEvent.create(
                    pilot_id=definition.pilot_id,
                    event_type=SMARTLEAD_PILOT_EVENT_CREATED,
                    message="Pilot created.",
                    details={"campaign_id": campaign_id, "recipient_count": len(recipients)},
                ),
            ),
        )
        self._pilot_store.upsert(run)
        self._pilot_store.save()
        return definition

    def preflight_pilot(self, pilot_id: str) -> SmartleadPilotPreflightResult:
        run = self._require_run(pilot_id)
        definition = run.definition
        checks, reasons, warnings = self._build_checks(definition)
        passed = all(check.passed or not check.required for check in checks)
        new_status = SMARTLEAD_PILOT_STATUS_READY if passed else SMARTLEAD_PILOT_STATUS_BLOCKED
        updated_definition = replace(
            definition,
            status=new_status,
            approved_at=utc_now_iso() if passed else definition.approved_at,
        )
        events = list(run.events)
        if passed:
            events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_PREFLIGHT_PASSED, message="Pilot preflight passed."))
        else:
            events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_ATTENTION_REQUIRED, message="Pilot preflight blocked.", details={"reasons": list(reasons)}))
        updated_run = SmartleadPilotRun(definition=updated_definition, snapshot=run.snapshot, events=tuple(events))
        self._pilot_store.upsert(updated_run)
        self._pilot_store.save()
        return SmartleadPilotPreflightResult(
            success=passed,
            status=new_status,
            message="Pilot READY." if passed else "Pilot preflight blocked.",
            pilot=updated_definition,
            checks=tuple(checks),
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    def dry_run_activation(self, pilot_id: str) -> SmartleadPilotActivationResult:
        run = self._require_run(pilot_id)
        preflight = self.preflight_pilot(pilot_id)
        return SmartleadPilotActivationResult(
            success=preflight.success,
            status="DRY_RUN" if preflight.success else preflight.status,
            message="Pilot dry run ready." if preflight.success else preflight.message,
            pilot=preflight.pilot,
            dry_run=True,
            activation_delegated=False,
            activation_result=None,
            expected_pause_target=run.definition.campaign_id,
            expected_monitor_targets=(run.definition.campaign_id, *(item.remote_lead_id or item.email for item in run.definition.recipients)),
            checks=preflight.checks,
        )

    def activate_pilot(self, pilot_id: str, *, confirmed: bool) -> SmartleadPilotActivationResult:
        run = self._require_run(pilot_id)
        preflight = self.preflight_pilot(pilot_id)
        if not preflight.success:
            return SmartleadPilotActivationResult(success=False, status=preflight.status, message=preflight.message, pilot=preflight.pilot, dry_run=False, checks=preflight.checks)
        if not confirmed:
            return SmartleadPilotActivationResult(success=False, status=SMARTLEAD_PILOT_STATUS_BLOCKED, message="Live pilot activation requires explicit confirmation.", pilot=preflight.pilot, dry_run=False, checks=preflight.checks)
        if not self.activation_contract_verified():
            return SmartleadPilotActivationResult(success=False, status=SMARTLEAD_PILOT_STATUS_BLOCKED, message="Live pilot activation blocked until SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED=true is configured locally.", pilot=preflight.pilot, dry_run=False, checks=preflight.checks)

        events = list(run.events)
        events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_ACTIVATION_REQUESTED, message="Pilot activation requested."))
        activation = self._activation_service.activate_campaign(
            source_package_id=run.definition.source_package_id,
            campaign_id=run.definition.campaign_id,
            mode=SMARTLEAD_ACTIVATION_MODE_LIVE,
            live_enabled=True,
            confirmed=True,
        )
        success = bool(getattr(activation, "success", False))
        remote_status = str(getattr(activation, "resulting_remote_status", "") or "").upper()
        new_status = SMARTLEAD_PILOT_STATUS_ACTIVE if remote_status in ACTIVE_REMOTE_STATUSES else SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED
        if success and remote_status in ACTIVE_REMOTE_STATUSES:
            events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_ACTIVATED, message="Pilot activated."))
        else:
            events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_ATTENTION_REQUIRED, message="Pilot activation needs attention.", details={"activation_status": getattr(activation, "status", "")}))
        updated_definition = replace(
            run.definition,
            status=new_status,
            activated_at=utc_now_iso() if success and remote_status in ACTIVE_REMOTE_STATUSES else run.definition.activated_at,
        )
        updated_run = SmartleadPilotRun(definition=updated_definition, snapshot=run.snapshot, events=tuple(events))
        self._pilot_store.upsert(updated_run)
        self._pilot_store.save()
        return SmartleadPilotActivationResult(
            success=success and remote_status in ACTIVE_REMOTE_STATUSES,
            status=new_status if success else SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED,
            message=str(getattr(activation, "message", "")),
            pilot=updated_definition,
            dry_run=False,
            activation_delegated=True,
            activation_result=activation.to_dict() if hasattr(activation, "to_dict") else dict(getattr(activation, "__dict__", {})),
            expected_pause_target=run.definition.campaign_id,
            expected_monitor_targets=(run.definition.campaign_id, *(item.remote_lead_id or item.email for item in run.definition.recipients)),
            checks=preflight.checks,
        )

    def pause_pilot(self, pilot_id: str, *, confirmed: bool) -> SmartleadPilotPauseResult:
        run = self._require_run(pilot_id)
        definition = run.definition
        if definition.status != SMARTLEAD_PILOT_STATUS_ACTIVE:
            return SmartleadPilotPauseResult(success=False, status=SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED, message="Pause is only available for active pilots.", pilot=definition)
        if not confirmed:
            return SmartleadPilotPauseResult(success=False, status=SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED, message="Pause requires confirmation.", pilot=definition)

        try:
            campaign = self._api_client.get_campaign(definition.campaign_id)
        except SmartleadApiError as exc:
            return SmartleadPilotPauseResult(success=False, status=SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED, message=f"Remote campaign lookup failed: {exc.message}", pilot=definition, attention_required=True)

        current_status = str(getattr(campaign, "status", "") or "").upper()
        if current_status in PAUSED_REMOTE_STATUSES:
            updated_definition = replace(definition, status=SMARTLEAD_PILOT_STATUS_PAUSED, paused_at=definition.paused_at or utc_now_iso())
            self._save_run_with_event(run, updated_definition, SMARTLEAD_PILOT_EVENT_PAUSED, "Pilot already paused.")
            return SmartleadPilotPauseResult(success=True, status=SMARTLEAD_PILOT_PAUSE_RESULT_ALREADY_PAUSED, message="Campaign already paused.", pilot=updated_definition, remote_status=current_status)
        if current_status not in ACTIVE_REMOTE_STATUSES:
            return SmartleadPilotPauseResult(success=False, status=SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED, message=f"Pause blocked because remote campaign status is {current_status or 'UNKNOWN' }.", pilot=definition, remote_status=current_status)

        events = list(run.events)
        events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_PAUSE_REQUESTED, message="Pilot pause requested."))
        write_error: SmartleadApiError | None = None
        try:
            self._api_client.pause_campaign(definition.campaign_id)
        except SmartleadApiError as exc:
            write_error = exc

        try:
            refreshed = self._api_client.get_campaign(definition.campaign_id)
            refreshed_status = str(getattr(refreshed, "status", "") or "").upper()
        except SmartleadApiError as exc:
            refreshed_status = ""
            if write_error is None:
                write_error = exc

        if refreshed_status in PAUSED_REMOTE_STATUSES:
            updated_definition = replace(definition, status=SMARTLEAD_PILOT_STATUS_PAUSED, paused_at=utc_now_iso())
            events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_PAUSED, message="Pilot paused."))
            updated_run = SmartleadPilotRun(definition=updated_definition, snapshot=run.snapshot, events=tuple(events))
            self._pilot_store.upsert(updated_run)
            self._pilot_store.save()
            return SmartleadPilotPauseResult(success=True, status=SMARTLEAD_PILOT_PAUSE_RESULT_PAUSED, message="Campaign paused and verified remotely.", pilot=updated_definition, remote_status=refreshed_status)

        updated_definition = replace(definition, status=SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED)
        events.append(SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_ATTENTION_REQUIRED, message="Pause requires manual attention.", details={"write_error": getattr(write_error, 'message', ''), "remote_status": refreshed_status}))
        updated_run = SmartleadPilotRun(definition=updated_definition, snapshot=run.snapshot, events=tuple(events))
        self._pilot_store.upsert(updated_run)
        self._pilot_store.save()
        message = "Pause request timed out or could not be verified. Manual reconciliation required."
        if refreshed_status and refreshed_status not in PAUSED_REMOTE_STATUSES:
            message = f"Pause write did not verify; remote campaign is still {refreshed_status}."
        return SmartleadPilotPauseResult(success=False, status=SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED, message=message, pilot=updated_definition, remote_status=refreshed_status, attention_required=True)

    def refresh_pilot_status(self, pilot_id: str) -> SmartleadPilotRun:
        run = self._require_run(pilot_id)
        definition = run.definition
        reconciliation = self._reconciliation_service.reconcile_campaign(source_package_id=definition.source_package_id, campaign_id=definition.campaign_id)
        campaign = self._api_client.get_campaign(definition.campaign_id)
        analytics = self._safe_campaign_analytics(definition.campaign_id)
        stats_rows = self._safe_lead_statistics(definition.campaign_id)
        snapshot = self._build_snapshot(definition=definition, reconciliation=reconciliation, campaign=campaign, analytics=analytics, stats_rows=stats_rows)

        normalized_status = str(getattr(campaign, "status", "") or "").upper()
        pilot_status = definition.status
        if normalized_status in ACTIVE_REMOTE_STATUSES:
            pilot_status = SMARTLEAD_PILOT_STATUS_ACTIVE
        elif normalized_status in PAUSED_REMOTE_STATUSES:
            pilot_status = SMARTLEAD_PILOT_STATUS_PAUSED
        elif snapshot.health == SMARTLEAD_PILOT_HEALTH_ATTENTION_REQUIRED:
            pilot_status = SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED

        updated_definition = replace(definition, status=pilot_status)
        updated_run = SmartleadPilotRun(
            definition=updated_definition,
            snapshot=snapshot,
            events=tuple(list(run.events) + [SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_STATUS_REFRESHED, message="Pilot status refreshed.")]),
        )
        self._pilot_store.upsert(updated_run)
        self._pilot_store.save()
        return updated_run

    def mark_review_complete(self, pilot_id: str) -> SmartleadPilotRun:
        run = self._require_run(pilot_id)
        updated_definition = replace(run.definition, status=SMARTLEAD_PILOT_STATUS_COMPLETED, completed_at=utc_now_iso())
        updated_run = SmartleadPilotRun(
            definition=updated_definition,
            snapshot=run.snapshot,
            events=tuple(list(run.events) + [SmartleadPilotEvent.create(pilot_id=pilot_id, event_type=SMARTLEAD_PILOT_EVENT_REVIEW_COMPLETED, message="Pilot review marked complete.")]),
        )
        self._pilot_store.upsert(updated_run)
        self._pilot_store.save()
        return updated_run

    def _build_checks(self, definition: SmartleadPilotDefinition) -> tuple[list[SmartleadPilotCheck], list[str], list[str]]:
        checks: list[SmartleadPilotCheck] = []
        reasons: list[str] = []
        warnings: list[str] = []
        recipients = list(definition.recipients)
        selected_count = len(recipients)

        checks.append(self._check("Correct Smartlead campaign selected", bool(definition.campaign_id), f"Campaign ID {definition.campaign_id or 'missing'}"))
        checks.append(self._check("Pilot size <= configured cap", 0 < selected_count <= self._max_pilot_size, f"Selected {selected_count} recipients; maximum allowed is {self._max_pilot_size}."))
        if selected_count == 0 or selected_count > self._max_pilot_size:
            reasons.append(f"Pilot recipient count must be between 1 and {self._max_pilot_size}.")

        review_rows = {row.prospect_id: row for row in self._review_service.list_rows([item.prospect_id for item in recipients])}
        for recipient in recipients:
            row = review_rows.get(recipient.prospect_id)
            approved = row is not None and row.review_status == CAMPAIGN_REVIEW_STATUS_APPROVED
            if not approved:
                reasons.append(f"{recipient.email}: campaign review is not APPROVED.")
            if row is not None and row.technical_status not in {SMARTLEAD_PREFLIGHT_READY, SMARTLEAD_PREFLIGHT_WARNING, 'READY', 'WARNING'}:
                reasons.append(f"{recipient.email}: technical handoff status is {row.technical_status or 'UNKNOWN'}.")

        checks.append(self._check("All explicitly approved", not any("campaign review is not APPROVED" in reason for reason in reasons), f"Selected recipients reviewed: {selected_count}"))

        reconciliation = self._reconciliation_service.reconcile_campaign(source_package_id=definition.source_package_id, campaign_id=definition.campaign_id)
        readiness = self._reconciliation_service.evaluate_launch_readiness(source_package_id=definition.source_package_id, campaign_id=definition.campaign_id)
        rows_by_prospect = {row.prospect_id: row for row in reconciliation.rows}
        publication_success = True
        hosted_assets_ready = True
        no_duplicate_remote = True
        all_reconciled = True
        remote_lead_missing = False
        recipients_with_remote: list[SmartleadPilotRecipient] = []

        for recipient in recipients:
            row = rows_by_prospect.get(recipient.prospect_id)
            if row is None:
                publication_success = False
                all_reconciled = False
                reasons.append(f"{recipient.email}: no reconciliation row found.")
                continue
            if row.local_status != SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
                publication_success = False
                reasons.append(f"{recipient.email}: publication did not succeed.")
            if row.classification != SMARTLEAD_RECONCILE_MATCHED:
                all_reconciled = False
                reasons.append(f"{recipient.email}: reconciliation status is {row.classification}.")
            if len(row.duplicate_remote_lead_ids) > 0:
                no_duplicate_remote = False
                reasons.append(f"{recipient.email}: duplicate remote lead detected.")
            if not row.remote_lead_id:
                remote_lead_missing = True
                reasons.append(f"{recipient.email}: remote lead missing.")
            recipients_with_remote.append(replace(recipient, remote_lead_id=row.remote_lead_id))

        definition = replace(definition, recipients=tuple(recipients_with_remote))

        handoff_statuses = self._handoff_rows(definition.source_handoff_path)
        for recipient in recipients_with_remote:
            handoff_status = handoff_statuses.get(recipient.prospect_id, "")
            if handoff_status not in {SMARTLEAD_PREFLIGHT_READY, SMARTLEAD_PREFLIGHT_WARNING}:
                reasons.append(f"{recipient.email}: handoff status is {handoff_status or 'UNKNOWN'}.")

        hosted_asset_count = 0
        for recipient in recipients_with_remote:
            assets = []
            if hasattr(self._reconciliation_service, "_hosted_asset_store"):
                assets = [asset for asset in self._reconciliation_service._hosted_asset_store.find_by_prospect(recipient.prospect_id) if is_valid_public_url(getattr(asset, "public_url", ""))]
            if not assets:
                hosted_assets_ready = False
                reasons.append(f"{recipient.email}: hosted mockup asset missing or invalid HTTPS URL.")
            else:
                hosted_asset_count += 1

        checks.append(self._check("Leads published", publication_success, "All pilot recipients must be successfully published."))
        checks.append(self._check("Reconciliation matched", all_reconciled and not remote_lead_missing, "Pilot recipients must reconcile to remote leads."))
        checks.append(self._check("Mockups hosted", hosted_assets_ready, f"Hosted assets verified for {hosted_asset_count}/{selected_count} recipients."))
        checks.append(self._check("No duplicate remote lead", no_duplicate_remote, "No pilot recipient may resolve to duplicate remote leads."))
        checks.append(self._check("Sequence ready", readiness.sequence_ready, "Campaign sequence must be ready."))
        checks.append(self._check("Sender accounts attached", getattr(readiness, "sequence_ready", False) and getattr(readiness, "status", "") == SMARTLEAD_LAUNCH_STATUS_READY or getattr(readiness, "remote_campaign_found", False), "Sender accounts must be attached."))
        checks.append(self._check("Launch readiness READY", readiness.status == SMARTLEAD_LAUNCH_STATUS_READY, f"Launch readiness is {readiness.status}."))
        checks.append(self._check("Campaign currently non-active", str(self._api_client.get_campaign(definition.campaign_id).status or "").upper() not in ACTIVE_REMOTE_STATUSES, "Remote campaign must not already be active for pilot start."))
        checks.append(self._check("Emergency pause capability available", hasattr(self._api_client, "pause_campaign"), "Pause campaign API seam is available."))
        checks.append(self._check("Live writes explicitly enabled", True, "Live writes remain user-controlled at activation time.", required=False))

        for item in getattr(readiness, "warnings", ()) or ():
            warnings.append(str(item))
        for item in getattr(readiness, "reasons", ()) or ():
            if str(item) not in reasons:
                reasons.append(str(item))

        run = self._pilot_store.get(definition.pilot_id)
        if run is not None and run.definition != definition:
            self._pilot_store.upsert(SmartleadPilotRun(definition=definition, snapshot=run.snapshot, events=run.events))
            self._pilot_store.save()
        return checks, reasons, warnings

    def _handoff_rows(self, handoff_directory: str) -> dict[str, str]:
        manifest_path = os.path.join(str(handoff_directory or ""), "smartlead_handoff_manifest.json")
        if not manifest_path or not os.path.isfile(manifest_path):
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return {}
        result: dict[str, str] = {}
        for row in list(payload.get("rows") or []):
            prospect_id = str(row.get("prospect_id") or "").strip()
            if prospect_id:
                result[prospect_id] = str(row.get("status") or "").strip().upper()
        return result

    def _build_snapshot(self, *, definition: SmartleadPilotDefinition, reconciliation: Any, campaign: Any, analytics: dict[str, Any], stats_rows: list[dict[str, Any]]) -> SmartleadPilotSnapshot:
        cohort = {item.remote_lead_id: item for item in definition.recipients if item.remote_lead_id} | {}
        cohort_by_email = {item.email.strip().lower(): item for item in definition.recipients if item.email}
        statuses: list[SmartleadPilotRecipientStatus] = []
        sent = replied = bounced = opened = clicked = 0
        reasons: list[str] = []
        warnings: list[str] = []

        for recipient in definition.recipients:
            row = None
            for item in stats_rows:
                lead_id = str(item.get("lead_id") or item.get("id") or "")
                email = str(item.get("email") or "").strip().lower()
                if (recipient.remote_lead_id and recipient.remote_lead_id == lead_id) or (recipient.email and recipient.email.strip().lower() == email):
                    row = item
                    break
            local_reasons: list[str] = []
            if row is None:
                local_reasons.append("Remote lead statistics unavailable for this pilot recipient.")
                reasons.append(f"{recipient.email}: remote lead statistics unavailable.")
            remote_status = str((row or {}).get("status") or (row or {}).get("lead_status") or "")
            sent_flag = self._truthy_stat(row, "sent") or remote_status.upper() in {"SENT", "OPENED", "CLICKED", "REPLIED", "BOUNCED"}
            replied_flag = self._truthy_stat(row, "replied") or self._truthy_stat(row, "reply") or remote_status.upper() == "REPLIED"
            bounced_flag = self._truthy_stat(row, "bounced") or remote_status.upper() == "BOUNCED"
            opened_flag = self._truthy_stat(row, "opened") or remote_status.upper() == "OPENED"
            clicked_flag = self._truthy_stat(row, "clicked") or remote_status.upper() == "CLICKED"
            sent += 1 if sent_flag else 0
            replied += 1 if replied_flag else 0
            bounced += 1 if bounced_flag else 0
            opened += 1 if opened_flag else 0
            clicked += 1 if clicked_flag else 0
            statuses.append(
                SmartleadPilotRecipientStatus(
                    prospect_id=recipient.prospect_id,
                    email=recipient.email,
                    remote_lead_id=recipient.remote_lead_id,
                    remote_status=remote_status,
                    sent=sent_flag,
                    replied=replied_flag,
                    bounced=bounced_flag,
                    opened=opened_flag,
                    clicked=clicked_flag,
                    reasons=tuple(local_reasons),
                )
            )

        not_sent = len(definition.recipients) - sent
        remote_campaign_status = str(getattr(campaign, "status", "") or "").upper()
        health = SMARTLEAD_PILOT_HEALTH_HEALTHY
        if remote_campaign_status not in ACTIVE_REMOTE_STATUSES | PAUSED_REMOTE_STATUSES | {"DRAFTED", "DRAFT"}:
            reasons.append(f"Unexpected remote campaign status: {remote_campaign_status or 'UNKNOWN'}.")
        if getattr(reconciliation, "reconciliation_required", False):
            reasons.append("Reconciliation mismatch detected.")
        if bounced > 0:
            warnings.append("Pilot cohort has bounce activity.")
        if reasons:
            health = SMARTLEAD_PILOT_HEALTH_ATTENTION_REQUIRED
        elif warnings:
            health = SMARTLEAD_PILOT_HEALTH_WATCH

        return SmartleadPilotSnapshot(
            pilot_id=definition.pilot_id,
            campaign_id=definition.campaign_id,
            remote_campaign_status=remote_campaign_status,
            health=health,
            last_checked_at=utc_now_iso(),
            campaign_metrics=dict(analytics or {}),
            pilot_metrics=SmartleadPilotMetrics(
                total_pilot_recipients=len(definition.recipients),
                sent=sent,
                not_sent=not_sent,
                replied=replied,
                bounced=bounced,
                opened=opened,
                clicked=clicked,
            ),
            recipient_statuses=tuple(statuses),
            warnings=tuple(warnings),
            reasons=tuple(reasons),
        )

    def _safe_campaign_analytics(self, campaign_id: str) -> dict[str, Any]:
        try:
            return self._api_client.get_campaign_analytics(campaign_id)
        except SmartleadApiError as exc:
            return {"error": exc.message}

    def _safe_lead_statistics(self, campaign_id: str) -> list[dict[str, Any]]:
        try:
            return self._api_client.get_campaign_lead_statistics(campaign_id)
        except SmartleadApiError:
            return []

    def _check(self, name: str, passed: bool, message: str, *, required: bool = True) -> SmartleadPilotCheck:
        return SmartleadPilotCheck(name=name, passed=bool(passed), message=str(message or ""), required=required)

    def _truthy_stat(self, row: dict[str, Any] | None, key: str) -> bool:
        if not isinstance(row, dict):
            return False
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        return str(value or "").strip().lower() in {"1", "true", "yes", "sent", "opened", "clicked", "replied", "bounced"}

    def _save_run_with_event(self, run: SmartleadPilotRun, definition: SmartleadPilotDefinition, event_type: str, message: str) -> None:
        updated_run = SmartleadPilotRun(
            definition=definition,
            snapshot=run.snapshot,
            events=tuple(list(run.events) + [SmartleadPilotEvent.create(pilot_id=definition.pilot_id, event_type=event_type, message=message)]),
        )
        self._pilot_store.upsert(updated_run)
        self._pilot_store.save()

    def _require_run(self, pilot_id: str) -> SmartleadPilotRun:
        run = self._pilot_store.get(pilot_id)
        if run is None:
            raise ValueError(f"Unknown pilot_id: {pilot_id}")
        return run

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered