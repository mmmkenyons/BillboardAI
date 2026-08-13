"""Explicit, guarded Smartlead campaign activation service (Sprint 5T)."""

from __future__ import annotations

from typing import Any

from gui.models.smartlead_activation import (
    SMARTLEAD_ACTIVATION_MODE_DRY_RUN,
    SMARTLEAD_ACTIVATION_MODE_LIVE,
    SMARTLEAD_ACTIVATION_RESULT_ACTIVATED,
    SMARTLEAD_ACTIVATION_RESULT_ALREADY_ACTIVE,
    SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
    SMARTLEAD_ACTIVATION_RESULT_DRY_RUN,
    SMARTLEAD_ACTIVATION_RESULT_FAILED,
    SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
    SmartleadActivationReceipt,
    SmartleadActivationResult,
)
from gui.models.smartlead_activation_store import SmartleadActivationStore
from gui.models.smartlead_launch import SMARTLEAD_LAUNCH_STATUS_READY
from gui.services.smartlead_api import SmartleadApiClient, SmartleadApiError
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService

ACTIVE_REMOTE_STATUSES = {"ACTIVE", "STARTED", "RUNNING", "SENDING"}
PAUSED_REMOTE_STATUSES = {"PAUSED"}
SUPPORTED_ACTIVATABLE_STATUSES = {"DRAFTED", "DRAFT"} | PAUSED_REMOTE_STATUSES
BLOCKED_REMOTE_STATUSES = {"STOPPED", "COMPLETED", "ARCHIVED"}


class SmartleadActivationService:
    def __init__(
        self,
        *,
        api_client: SmartleadApiClient,
        reconciliation_service: SmartleadReconciliationService,
        activation_store: SmartleadActivationStore | None = None,
        sequence_service: SmartleadSequenceReadinessService | None = None,
    ) -> None:
        self._api_client = api_client
        self._reconciliation_service = reconciliation_service
        self._activation_store = activation_store or SmartleadActivationStore()
        self._sequence_service = sequence_service

    def activation_preview(self, *, source_package_id: str, campaign_id: str) -> SmartleadActivationResult:
        return self.activate_campaign(
            source_package_id=source_package_id,
            campaign_id=campaign_id,
            mode=SMARTLEAD_ACTIVATION_MODE_DRY_RUN,
            live_enabled=False,
            confirmed=False,
        )

    def activate_campaign(
        self,
        *,
        source_package_id: str,
        campaign_id: str,
        mode: str = SMARTLEAD_ACTIVATION_MODE_DRY_RUN,
        live_enabled: bool = False,
        confirmed: bool = False,
    ) -> SmartleadActivationResult:
        resolved_mode = SMARTLEAD_ACTIVATION_MODE_LIVE if mode == SMARTLEAD_ACTIVATION_MODE_LIVE else SMARTLEAD_ACTIVATION_MODE_DRY_RUN
        dry_run = resolved_mode != SMARTLEAD_ACTIVATION_MODE_LIVE

        try:
            campaign = self._api_client.get_campaign(campaign_id)
        except SmartleadApiError as exc:
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_FAILED,
                message=f"Remote campaign lookup failed: {exc.message}",
                mode=resolved_mode,
                dry_run=dry_run,
                campaign_id=str(campaign_id or ""),
                source_package_id=str(source_package_id or ""),
                reasons=(f"Remote campaign lookup failed: {exc.message}",),
            )

        fresh_readiness = self._reconciliation_service.evaluate_launch_readiness(source_package_id=source_package_id, campaign_id=campaign_id)
        remote_status = str(getattr(campaign, "status", "") or "").upper()
        sequence_info = self._sequence_service.check_readiness(campaign_id) if self._sequence_service is not None else None
        sender_account_count = int(getattr(sequence_info, "sender_account_count", 0) or 0)
        intended_request = {"intent": "START_CAMPAIGN", "campaign_id": str(campaign_id or "")}

        if remote_status in ACTIVE_REMOTE_STATUSES:
            receipt = self._persist_receipt(
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness=fresh_readiness,
                sender_account_count=sender_account_count,
                status=SMARTLEAD_ACTIVATION_RESULT_ALREADY_ACTIVE,
                message="Campaign is already active remotely.",
                confirmed=confirmed,
                mode=resolved_mode,
            )
            return SmartleadActivationResult(
                success=True,
                status=SMARTLEAD_ACTIVATION_RESULT_ALREADY_ACTIVE,
                message="Campaign is already active remotely.",
                mode=resolved_mode,
                dry_run=dry_run,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness_status=fresh_readiness.status,
                reasons=tuple(fresh_readiness.reasons),
                warnings=tuple(fresh_readiness.warnings),
                intended_request=intended_request,
                receipt=receipt,
            )

        if fresh_readiness.status != SMARTLEAD_LAUNCH_STATUS_READY:
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
                message="Campaign activation blocked: launch readiness is not READY.",
                mode=resolved_mode,
                dry_run=dry_run,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness_status=fresh_readiness.status,
                reasons=tuple(fresh_readiness.reasons),
                warnings=tuple(fresh_readiness.warnings),
                intended_request=intended_request,
            )

        if remote_status in BLOCKED_REMOTE_STATUSES or (remote_status and remote_status not in SUPPORTED_ACTIVATABLE_STATUSES):
            message = f"Campaign activation blocked from remote status {remote_status or 'UNKNOWN'}."
            receipt = self._persist_receipt(
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness=fresh_readiness,
                sender_account_count=sender_account_count,
                status=SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
                message=message,
                confirmed=confirmed,
                mode=resolved_mode,
            )
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
                message=message,
                mode=resolved_mode,
                dry_run=dry_run,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness_status=fresh_readiness.status,
                reasons=tuple(list(fresh_readiness.reasons) + [message]),
                warnings=tuple(fresh_readiness.warnings),
                intended_request=intended_request,
                receipt=receipt,
            )

        if dry_run:
            return SmartleadActivationResult(
                success=True,
                status=SMARTLEAD_ACTIVATION_RESULT_DRY_RUN,
                message="Activation dry run prepared. No Smartlead status write was performed.",
                mode=resolved_mode,
                dry_run=True,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness_status=fresh_readiness.status,
                reasons=tuple(fresh_readiness.reasons),
                warnings=tuple(fresh_readiness.warnings),
                intended_request=intended_request,
            )

        if not live_enabled or not confirmed:
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
                message="Live Smartlead activation requires explicit enable and confirmation.",
                mode=resolved_mode,
                dry_run=False,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness_status=fresh_readiness.status,
                reasons=tuple(list(fresh_readiness.reasons) + ["Live Smartlead activation requires explicit enable and confirmation."]),
                warnings=tuple(fresh_readiness.warnings),
                intended_request=intended_request,
            )

        write_readiness = self._reconciliation_service.evaluate_launch_readiness(source_package_id=source_package_id, campaign_id=campaign_id)
        if write_readiness.status != SMARTLEAD_LAUNCH_STATUS_READY:
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
                message="Campaign activation blocked: launch readiness changed before write and is no longer READY.",
                mode=resolved_mode,
                dry_run=False,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                source_package_id=source_package_id,
                prior_remote_status=remote_status,
                resulting_remote_status=remote_status,
                readiness_status=write_readiness.status,
                reasons=tuple(write_readiness.reasons),
                warnings=tuple(write_readiness.warnings),
                intended_request=intended_request,
            )

        try:
            self._api_client.start_campaign(campaign_id)
        except SmartleadApiError as exc:
            return self._handle_ambiguous_failure(
                exc=exc,
                source_package_id=source_package_id,
                campaign_id=campaign_id,
                campaign_name=campaign.name,
                prior_remote_status=remote_status,
                readiness=write_readiness,
                sender_account_count=sender_account_count,
                confirmed=confirmed,
                mode=resolved_mode,
                intended_request=intended_request,
            )

        return self._verify_after_write(
            source_package_id=source_package_id,
            campaign_id=campaign_id,
            campaign_name=campaign.name,
            prior_remote_status=remote_status,
            readiness=write_readiness,
            sender_account_count=sender_account_count,
            confirmed=confirmed,
            mode=resolved_mode,
            intended_request=intended_request,
        )

    def _handle_ambiguous_failure(
        self,
        *,
        exc: SmartleadApiError,
        source_package_id: str,
        campaign_id: str,
        campaign_name: str,
        prior_remote_status: str,
        readiness: object,
        sender_account_count: int,
        confirmed: bool,
        mode: str,
        intended_request: dict[str, Any],
    ) -> SmartleadActivationResult:
        try:
            campaign = self._api_client.get_campaign(campaign_id)
        except SmartleadApiError:
            message = "Activation result is unknown and remote state could not be re-read. Reconciliation required."
            receipt = self._persist_receipt(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status="",
                readiness=readiness,
                sender_account_count=sender_account_count,
                status=SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
                message=message,
                confirmed=confirmed,
                mode=mode,
            )
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
                message=message,
                mode=mode,
                dry_run=False,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status="",
                readiness_status=getattr(readiness, "status", ""),
                reasons=tuple(list(getattr(readiness, "reasons", ()) or ()) + [exc.message]),
                warnings=tuple(getattr(readiness, "warnings", ()) or ()),
                intended_request=intended_request,
                receipt=receipt,
            )

        resulting_remote_status = str(getattr(campaign, "status", "") or "").upper()
        if resulting_remote_status in ACTIVE_REMOTE_STATUSES:
            receipt = self._persist_receipt(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status=resulting_remote_status,
                readiness=readiness,
                sender_account_count=sender_account_count,
                status=SMARTLEAD_ACTIVATION_RESULT_ACTIVATED,
                message="Activation reconciled as successful after ambiguous write failure.",
                confirmed=confirmed,
                mode=mode,
            )
            return SmartleadActivationResult(
                success=True,
                status=SMARTLEAD_ACTIVATION_RESULT_ACTIVATED,
                message="Activation reconciled as successful after ambiguous write failure.",
                mode=mode,
                dry_run=False,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status=resulting_remote_status,
                readiness_status=getattr(readiness, "status", ""),
                reasons=tuple(getattr(readiness, "reasons", ()) or ()),
                warnings=tuple(getattr(readiness, "warnings", ()) or ()),
                intended_request=intended_request,
                receipt=receipt,
            )

        message = f"Activation failed before remote status changed: {exc.message}"
        receipt = self._persist_receipt(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            prior_remote_status=prior_remote_status,
            resulting_remote_status=resulting_remote_status,
            readiness=readiness,
            sender_account_count=sender_account_count,
            status=SMARTLEAD_ACTIVATION_RESULT_FAILED if exc.code != "TIMEOUT" else SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
            message=message,
            confirmed=confirmed,
            mode=mode,
        )
        return SmartleadActivationResult(
            success=False,
            status=SMARTLEAD_ACTIVATION_RESULT_FAILED if exc.code != "TIMEOUT" else SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
            message=message,
            mode=mode,
            dry_run=False,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            prior_remote_status=prior_remote_status,
            resulting_remote_status=resulting_remote_status,
            readiness_status=getattr(readiness, "status", ""),
            reasons=tuple(list(getattr(readiness, "reasons", ()) or ()) + [exc.message]),
            warnings=tuple(getattr(readiness, "warnings", ()) or ()),
            intended_request=intended_request,
            receipt=receipt,
        )

    def _verify_after_write(
        self,
        *,
        source_package_id: str,
        campaign_id: str,
        campaign_name: str,
        prior_remote_status: str,
        readiness: object,
        sender_account_count: int,
        confirmed: bool,
        mode: str,
        intended_request: dict[str, Any],
    ) -> SmartleadActivationResult:
        try:
            campaign = self._api_client.get_campaign(campaign_id)
        except SmartleadApiError as exc:
            message = f"Activation write completed but remote verification failed: {exc.message}"
            receipt = self._persist_receipt(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status="",
                readiness=readiness,
                sender_account_count=sender_account_count,
                status=SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
                message=message,
                confirmed=confirmed,
                mode=mode,
            )
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
                message=message,
                mode=mode,
                dry_run=False,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                readiness_status=getattr(readiness, "status", ""),
                reasons=tuple(list(getattr(readiness, "reasons", ()) or ()) + [exc.message]),
                warnings=tuple(getattr(readiness, "warnings", ()) or ()),
                intended_request=intended_request,
                receipt=receipt,
            )

        resulting_remote_status = str(getattr(campaign, "status", "") or "").upper()
        if resulting_remote_status not in ACTIVE_REMOTE_STATUSES:
            message = f"Activation could not be verified remotely; resulting status was {resulting_remote_status or 'UNKNOWN'}."
            receipt = self._persist_receipt(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status=resulting_remote_status,
                readiness=readiness,
                sender_account_count=sender_account_count,
                status=SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
                message=message,
                confirmed=confirmed,
                mode=mode,
            )
            return SmartleadActivationResult(
                success=False,
                status=SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
                message=message,
                mode=mode,
                dry_run=False,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                source_package_id=source_package_id,
                prior_remote_status=prior_remote_status,
                resulting_remote_status=resulting_remote_status,
                readiness_status=getattr(readiness, "status", ""),
                reasons=tuple(getattr(readiness, "reasons", ()) or ()),
                warnings=tuple(getattr(readiness, "warnings", ()) or ()),
                intended_request=intended_request,
                receipt=receipt,
            )

        receipt = self._persist_receipt(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            prior_remote_status=prior_remote_status,
            resulting_remote_status=resulting_remote_status,
            readiness=readiness,
            sender_account_count=sender_account_count,
            status=SMARTLEAD_ACTIVATION_RESULT_ACTIVATED,
            message="Campaign activated and verified remotely.",
            confirmed=confirmed,
            mode=mode,
        )
        return SmartleadActivationResult(
            success=True,
            status=SMARTLEAD_ACTIVATION_RESULT_ACTIVATED,
            message="Campaign activated and verified remotely.",
            mode=mode,
            dry_run=False,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            prior_remote_status=prior_remote_status,
            resulting_remote_status=resulting_remote_status,
            readiness_status=getattr(readiness, "status", ""),
            reasons=tuple(getattr(readiness, "reasons", ()) or ()),
            warnings=tuple(getattr(readiness, "warnings", ()) or ()),
            intended_request=intended_request,
            receipt=receipt,
        )

    def _persist_receipt(
        self,
        *,
        campaign_id: str,
        campaign_name: str,
        source_package_id: str,
        prior_remote_status: str,
        resulting_remote_status: str,
        readiness: Any,
        sender_account_count: int,
        status: str,
        message: str,
        confirmed: bool,
        mode: str,
    ) -> SmartleadActivationReceipt:
        reconciliation_status = "MATCHED" if getattr(readiness, "reconciliation_required", False) is False else "RECONCILIATION_REQUIRED"
        receipt = SmartleadActivationReceipt.create(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            source_package_id=source_package_id,
            prior_remote_status=prior_remote_status,
            resulting_remote_status=resulting_remote_status,
            readiness_status=str(getattr(readiness, "status", "") or ""),
            published_count=int(getattr(readiness, "published_count", 0) or 0),
            sequence_ready=bool(getattr(readiness, "sequence_ready", False)),
            sender_account_count=sender_account_count,
            reconciliation_status=reconciliation_status,
            status=status,
            message=message,
            confirmed=confirmed,
            mode=mode,
        )
        self._activation_store.append(receipt)
        self._activation_store.save()
        return receipt