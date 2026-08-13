"""Read-only Smartlead publication reconciliation and launch readiness (5S)."""

from __future__ import annotations

from collections import defaultdict

from gui.models.hosted_asset import is_valid_public_url
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_launch import (
    SMARTLEAD_LAUNCH_STATUS_BLOCKED,
    SMARTLEAD_LAUNCH_STATUS_NOT_READY,
    SMARTLEAD_LAUNCH_STATUS_READY,
    SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED,
    SMARTLEAD_RECONCILE_DUPLICATE_REMOTE,
    SMARTLEAD_RECONCILE_FAILED,
    SMARTLEAD_RECONCILE_LOCAL_ONLY,
    SMARTLEAD_RECONCILE_MATCHED,
    SMARTLEAD_RECONCILE_MISMATCH,
    SMARTLEAD_RECONCILE_PENDING,
    SMARTLEAD_RECONCILE_REMOTE_ONLY,
    SmartleadLaunchReadiness,
    SmartleadReconciliationResult,
    SmartleadReconciliationRow,
)
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_STATUS_FAILED,
    SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED,
    SMARTLEAD_PUBLISH_STATUS_SKIPPED,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SmartleadPublishedLead,
    utc_now_iso,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.services.smartlead_api import SmartleadApiClient, SmartleadApiError
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService


class SmartleadReconciliationService:
    def __init__(
        self,
        *,
        api_client: SmartleadApiClient,
        publication_store: SmartleadPublicationStore,
        hosted_asset_store: HostedAssetStore | None = None,
        sequence_service: SmartleadSequenceReadinessService | None = None,
    ) -> None:
        self._api_client = api_client
        self._publication_store = publication_store
        self._hosted_asset_store = hosted_asset_store or HostedAssetStore()
        self._sequence_service = sequence_service

    def reconcile_campaign(self, *, source_package_id: str, campaign_id: str) -> SmartleadReconciliationResult:
        receipts = [
            receipt
            for receipt in self._publication_store.list()
            if receipt.source_package_id == source_package_id and receipt.campaign_id == campaign_id
        ]
        ordered_local = self._reduce_latest_local_state(receipts)
        campaign_name = next((receipt.campaign_name for receipt in reversed(receipts) if receipt.campaign_name), "")

        reasons: list[str] = []
        warnings: list[str] = []
        try:
            campaign = self._api_client.get_campaign(campaign_id)
            remote_campaign_found = True
            campaign_name = campaign_name or campaign.name
            remote_leads = self._api_client.get_campaign_leads(campaign_id)
        except SmartleadApiError as exc:
            remote_campaign_found = False
            remote_leads = []
            reasons.append(f"Remote campaign lookup failed: {exc.message}")

        remote_by_id: dict[str, dict] = {}
        remote_by_email: dict[str, list[dict]] = defaultdict(list)
        for lead in remote_leads:
            remote_id = str(lead.get("id") or lead.get("lead_id") or "").strip()
            email = str(lead.get("email") or "").strip().lower()
            if remote_id:
                remote_by_id[remote_id] = lead
            if email:
                remote_by_email[email].append(lead)

        rows: list[SmartleadReconciliationRow] = []
        matched = local_only = remote_only = mismatched = failed = pending = duplicate_remote = 0
        matched_remote_ids: set[str] = set()

        for lead in ordered_local:
            remote_matches = self._remote_matches_for_lead(lead, remote_by_id, remote_by_email)
            for item in remote_matches:
                remote_id = str(item.get("id") or item.get("lead_id") or "").strip()
                if remote_id:
                    matched_remote_ids.add(remote_id)
            row = self._classify_row(campaign_id=campaign_id, lead=lead, remote_matches=remote_matches)
            rows.append(row)
            if row.classification == SMARTLEAD_RECONCILE_MATCHED:
                matched += 1
            elif row.classification == SMARTLEAD_RECONCILE_LOCAL_ONLY:
                local_only += 1
            elif row.classification == SMARTLEAD_RECONCILE_REMOTE_ONLY:
                remote_only += 1
            elif row.classification == SMARTLEAD_RECONCILE_MISMATCH:
                mismatched += 1
            elif row.classification == SMARTLEAD_RECONCILE_FAILED:
                failed += 1
            elif row.classification == SMARTLEAD_RECONCILE_DUPLICATE_REMOTE:
                duplicate_remote += 1
            else:
                pending += 1

        for remote in sorted(remote_leads, key=lambda item: (str(item.get("email") or "").lower(), str(item.get("id") or item.get("lead_id") or ""))):
            remote_id = str(remote.get("id") or remote.get("lead_id") or "").strip()
            if remote_id and remote_id in matched_remote_ids:
                continue
            rows.append(
                SmartleadReconciliationRow(
                    campaign_id=campaign_id,
                    publication_key="",
                    prospect_id=str((remote.get("custom_fields") or {}).get("bb_prospect_id") or ""),
                    email=str(remote.get("email") or ""),
                    local_status="",
                    remote_status="REMOTE_PRESENT",
                    classification=SMARTLEAD_RECONCILE_REMOTE_ONLY,
                    remote_lead_id=remote_id,
                    reasons=("Remote lead exists without matching local publication record.",),
                )
            )
            remote_only += 1

        rows = sorted(rows, key=lambda row: (str(row.prospect_id or ""), str(row.email or "").lower(), str(row.publication_key or ""), str(row.remote_lead_id or "")))
        reconciliation_required = bool(reasons or local_only or remote_only or mismatched or duplicate_remote or (remote_campaign_found is False and ordered_local))
        if duplicate_remote:
            warnings.append("Duplicate remote Smartlead leads detected for at least one local publication.")
        if remote_only:
            warnings.append("Remote-only Smartlead leads were detected and were not imported into BillboardAI.")
        if local_only:
            warnings.append("Local publication records were detected without a matching remote Smartlead lead.")
        return SmartleadReconciliationResult(
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            remote_campaign_found=remote_campaign_found,
            checked_at=utc_now_iso(),
            matched=matched,
            local_only=local_only,
            remote_only=remote_only,
            mismatched=mismatched,
            failed=failed,
            pending=pending,
            duplicate_remote=duplicate_remote,
            reconciliation_required=reconciliation_required,
            rows=tuple(rows),
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    def evaluate_launch_readiness(self, *, source_package_id: str, campaign_id: str) -> SmartleadLaunchReadiness:
        reconciliation = self.reconcile_campaign(source_package_id=source_package_id, campaign_id=campaign_id)
        local = self._reduce_latest_local_state(
            [receipt for receipt in self._publication_store.list() if receipt.source_package_id == source_package_id and receipt.campaign_id == campaign_id]
        )
        published = sum(1 for lead in local if lead.status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED)
        failed = sum(1 for lead in local if lead.status == SMARTLEAD_PUBLISH_STATUS_FAILED)
        pending = sum(1 for lead in local if lead.status in {SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED, SMARTLEAD_PUBLISH_STATUS_SKIPPED})
        duplicate_count = reconciliation.duplicate_remote
        missing_asset_count = 0
        for lead in local:
            if lead.status != SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
                continue
            assets = [asset for asset in self._hosted_asset_store.find_by_prospect(lead.prospect_id) if is_valid_public_url(asset.public_url)]
            if not assets:
                missing_asset_count += 1

        reasons = list(reconciliation.reasons)
        warnings = list(reconciliation.warnings)
        sequence_ready = False
        if self._sequence_service is not None and reconciliation.remote_campaign_found:
            readiness = self._sequence_service.check_readiness(campaign_id)
            sequence_ready = bool(getattr(readiness, "ready_for_manual_activation", False))
            if not sequence_ready:
                reasons.extend(list(getattr(readiness, "blockers", ()) or ()))
            warnings.extend(list(getattr(readiness, "warnings", ()) or ()))
        else:
            reasons.append("Sequence readiness could not be confirmed.")

        if not reconciliation.remote_campaign_found:
            reasons.append("Remote Smartlead campaign was not found.")
        if failed:
            reasons.append("One or more Smartlead publications are still failed.")
        if pending:
            reasons.append("One or more Smartlead publications are still pending or not attempted.")
        if missing_asset_count:
            reasons.append("One or more published prospects are missing a hosted HTTPS mockup asset.")
        if reconciliation.reconciliation_required:
            reasons.append("Smartlead reconciliation requires attention.")
        if duplicate_count:
            reasons.append("Duplicate remote Smartlead leads were detected.")

        status = SMARTLEAD_LAUNCH_STATUS_READY
        if reconciliation.reconciliation_required:
            status = SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED
        if reasons:
            blocked = any(
                reason in {
                    "Remote Smartlead campaign was not found.",
                    "One or more Smartlead publications are still failed.",
                    "One or more Smartlead publications are still pending or not attempted.",
                    "One or more published prospects are missing a hosted HTTPS mockup asset.",
                    "Duplicate remote Smartlead leads were detected.",
                }
                for reason in reasons
            )
            if blocked:
                status = SMARTLEAD_LAUNCH_STATUS_BLOCKED
            elif reconciliation.reconciliation_required:
                status = SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED
            else:
                status = SMARTLEAD_LAUNCH_STATUS_NOT_READY
        if not local:
            status = SMARTLEAD_LAUNCH_STATUS_NOT_READY
            reasons.append("No local Smartlead publication state exists for this campaign/package.")

        return SmartleadLaunchReadiness(
            campaign_id=campaign_id,
            campaign_name=reconciliation.campaign_name,
            status=status,
            total_expected=len(local),
            published_count=published,
            failed_count=failed,
            pending_count=pending,
            duplicate_count=duplicate_count,
            missing_asset_count=missing_asset_count,
            sequence_ready=sequence_ready,
            remote_campaign_found=bool(reconciliation.remote_campaign_found),
            reconciliation_required=reconciliation.reconciliation_required,
            reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)),
            warnings=tuple(dict.fromkeys(warning for warning in warnings if warning)),
            checked_at=utc_now_iso(),
        )

    def _reduce_latest_local_state(self, receipts: list[object]) -> list[SmartleadPublishedLead]:
        by_key: dict[str, SmartleadPublishedLead] = {}
        for receipt in receipts:
            for lead in receipt.lead_results:
                if not lead.publication_key:
                    continue
                existing = by_key.get(lead.publication_key)
                by_key[lead.publication_key] = self._canonicalize_same_key(existing, lead)
        return [by_key[key] for key in sorted(by_key.keys(), key=lambda value: tuple(value.split(":")))]

    def _canonicalize_same_key(
        self,
        existing: SmartleadPublishedLead | None,
        incoming: SmartleadPublishedLead,
    ) -> SmartleadPublishedLead:
        if existing is None:
            return incoming

        existing_status = str(existing.status or "").upper()
        incoming_status = str(incoming.status or "").upper()

        # Success is semantic publication truth. A later SKIPPED record for the
        # same publication identity must not downgrade an established success.
        if existing_status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED and incoming_status == SMARTLEAD_PUBLISH_STATUS_SKIPPED:
            return existing
        if incoming_status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
            remote_lead_id = incoming.remote_lead_id or existing.remote_lead_id
            if remote_lead_id != incoming.remote_lead_id:
                return incoming.replaced(remote_lead_id=remote_lead_id)
            return incoming
        if existing_status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
            return existing

        # For non-success states, later records remain authoritative.
        return incoming

    def _remote_matches_for_lead(
        self,
        lead: SmartleadPublishedLead,
        remote_by_id: dict[str, dict],
        remote_by_email: dict[str, list[dict]],
    ) -> list[dict]:
        if lead.remote_lead_id and lead.remote_lead_id in remote_by_id:
            return [remote_by_id[lead.remote_lead_id]]
        return list(remote_by_email.get(str(lead.email or "").strip().lower(), []))

    def _classify_row(self, *, campaign_id: str, lead: SmartleadPublishedLead, remote_matches: list[dict]) -> SmartleadReconciliationRow:
        reasons: list[str] = []
        local_status = lead.status
        remote_status = "REMOTE_MISSING"
        remote_lead_id = lead.remote_lead_id
        duplicate_ids: tuple[str, ...] = ()
        classification = SMARTLEAD_RECONCILE_PENDING

        if len(remote_matches) > 1:
            duplicate_ids = tuple(sorted(str(item.get("id") or item.get("lead_id") or "") for item in remote_matches if str(item.get("id") or item.get("lead_id") or "")))
            classification = SMARTLEAD_RECONCILE_DUPLICATE_REMOTE
            reasons.append("Multiple remote Smartlead leads matched this local publication.")
        elif not remote_matches:
            if local_status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
                classification = SMARTLEAD_RECONCILE_LOCAL_ONLY
                reasons.append("Local publication succeeded but remote lead was not found.")
            elif local_status == SMARTLEAD_PUBLISH_STATUS_FAILED:
                classification = SMARTLEAD_RECONCILE_FAILED
                reasons.append("Local publication failed and no remote lead was found.")
            else:
                classification = SMARTLEAD_RECONCILE_PENDING
                reasons.append("Local publication has not completed and no remote lead was found.")
        else:
            remote = remote_matches[0]
            remote_lead_id = str(remote.get("id") or remote.get("lead_id") or remote_lead_id or "")
            remote_status = str(remote.get("status") or "REMOTE_PRESENT")
            remote_email = str(remote.get("email") or "").strip().lower()
            local_email = str(lead.email or "").strip().lower()
            if remote_email and local_email and remote_email != local_email:
                classification = SMARTLEAD_RECONCILE_MISMATCH
                reasons.append("Remote lead email does not match local publication email.")
            elif local_status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
                classification = SMARTLEAD_RECONCILE_MATCHED
            elif local_status == SMARTLEAD_PUBLISH_STATUS_FAILED:
                classification = SMARTLEAD_RECONCILE_MISMATCH
                reasons.append("Remote lead exists even though the latest local publication state is FAILED.")
            else:
                classification = SMARTLEAD_RECONCILE_MISMATCH
                reasons.append("Remote lead exists while the latest local publication state is pending or not attempted.")

        return SmartleadReconciliationRow(
            campaign_id=campaign_id,
            publication_key=lead.publication_key,
            prospect_id=lead.prospect_id,
            email=lead.email,
            local_status=local_status,
            remote_status=remote_status,
            classification=classification,
            remote_lead_id=remote_lead_id,
            duplicate_remote_lead_ids=duplicate_ids,
            reasons=tuple(reasons),
        )