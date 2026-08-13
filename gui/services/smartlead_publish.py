"""Dry-run and live publishing service for Smartlead-approved handoff rows."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from typing import Any

from gui.models.hosted_asset import is_valid_public_url
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import (
    SMARTLEAD_HOSTED_SYNC_FAILED,
    SMARTLEAD_HOSTED_SYNC_NOT_SYNCABLE,
    SMARTLEAD_HOSTED_SYNC_PENDING,
    SMARTLEAD_HOSTED_SYNC_SKIPPED,
    SMARTLEAD_HOSTED_SYNC_SYNCED,
    SMARTLEAD_PUBLISH_MODE_DRY_RUN,
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_PUBLISH_STATUS_FAILED,
    SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED,
    SMARTLEAD_PUBLISH_STATUS_SKIPPED,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SMARTLEAD_TARGET_MODE_CREATE_DRAFT,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadPublishLead,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
    SmartleadPublishResult,
    SmartleadPublishTarget,
    SmartleadUrlSyncLeadResult,
    SmartleadUrlSyncResult,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.services.smartlead_api import SmartleadApiClient, SmartleadApiError

SMARTLEAD_CUSTOM_FIELD_MAP: dict[str, str] = {
    "email_subject": "bb_subject",
    "email_body": "bb_body",
    "company": "bb_company",
    "city": "bb_city",
    "state": "bb_state",
    "headline": "bb_headline",
    "cta": "bb_cta",
    "mockup_path": "bb_local_mockup_path",
    "mockup_relative_path": "bb_local_mockup_path",
    "mockup_url": "bb_mockup_url",
    "personalization_basis": "bb_personalization_basis",
}

SAFE_EXISTING_CAMPAIGN_STATUSES = {"DRAFTED", "PAUSED", "STOPPED", "ACTIVE"}
UPLOAD_BATCH_SIZE = 400


class SmartleadPublishService:
    def __init__(
        self,
        *,
        api_client: SmartleadApiClient,
        receipt_store: SmartleadPublicationStore | None = None,
        settings: SmartleadConnectionSettings | None = None,
        hosted_asset_store: HostedAssetStore | None = None,
    ) -> None:
        self._api_client = api_client
        self._receipt_store = receipt_store or SmartleadPublicationStore()
        self._settings = settings or api_client.settings
        self._hosted_asset_store = hosted_asset_store or HostedAssetStore()

    def list_campaigns(self):
        return self._api_client.list_campaigns()

    def test_connection(self):
        return self._api_client.test_connection()

    def publish_from_handoff(
        self,
        handoff_directory: str,
        *,
        target: SmartleadPublishTarget,
        mode: str = SMARTLEAD_PUBLISH_MODE_DRY_RUN,
        live_enabled: bool = False,
        confirmed: bool = False,
    ) -> SmartleadPublishResult:
        resolved_mode = SMARTLEAD_PUBLISH_MODE_LIVE if mode == SMARTLEAD_PUBLISH_MODE_LIVE else SMARTLEAD_PUBLISH_MODE_DRY_RUN
        if resolved_mode == SMARTLEAD_PUBLISH_MODE_LIVE and (not live_enabled or not confirmed):
            return SmartleadPublishResult(success=False, message="Live Smartlead writes require explicit enable and confirmation.", mode=resolved_mode, target_mode=target.mode, dry_run=False)
        dry_run = resolved_mode != SMARTLEAD_PUBLISH_MODE_LIVE
        package_root, manifest, handoff_manifest, preflight_rows, final_rows = self._load_handoff(handoff_directory)
        candidates = self._build_publishable_leads(package_root, manifest, handoff_manifest, preflight_rows, final_rows)
        blocked = sum(1 for row in preflight_rows if str(row.get("status") or "") not in {"READY", "WARNING"})
        payload_preview = [self._lead_payload(item) for item in candidates]
        batches = self._batch(payload_preview, UPLOAD_BATCH_SIZE)
        campaign_id = str(target.campaign_id or "")
        campaign_name = str(target.campaign_name or target.create_name or "")
        if dry_run:
            return SmartleadPublishResult(
                success=True,
                message="Smartlead dry run prepared. No live writes performed.",
                mode=resolved_mode,
                target_mode=target.mode,
                dry_run=True,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                total_candidates=len(preflight_rows),
                eligible=len(candidates),
                blocked_or_conflict=blocked,
                batches_planned=len(batches),
                payload_preview=tuple(payload_preview),
            )

        campaign_id, campaign_name = self._resolve_live_target(target)
        details = self._api_client.get_campaign(campaign_id)
        if details.status and details.status.upper() not in SAFE_EXISTING_CAMPAIGN_STATUSES:
            return SmartleadPublishResult(success=False, message=f"Campaign status {details.status} is not safe for upload.", mode=resolved_mode, target_mode=target.mode, dry_run=False, campaign_id=campaign_id, campaign_name=campaign_name)

        prior_success = self._successful_publication_keys(source_package_id=str(manifest.get("package_id") or ""), campaign_id=campaign_id)
        lead_results: list[SmartleadPublishedLead] = []
        live_payloads: list[dict[str, Any]] = []
        for lead in candidates:
            if lead.publication_key in prior_success:
                lead_results.append(SmartleadPublishedLead(publication_key=lead.publication_key, prospect_id=lead.prospect_id, email=lead.email, status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, campaign_id=campaign_id, reason="Already published to this campaign."))
            else:
                live_payloads.append(self._lead_payload(lead))
        payload_batches = self._batch(live_payloads, UPLOAD_BATCH_SIZE)
        attempted_batches = 0
        cursor = 0
        for batch_index, batch in enumerate(payload_batches, start=1):
            attempted_batches += 1
            try:
                response = self._api_client.add_leads(campaign_id, batch)
            except SmartleadApiError as exc:
                for item in batch:
                    lead_results.append(SmartleadPublishedLead(publication_key=str(item.get("_publication_key") or ""), prospect_id=str(item.get("custom_fields", {}).get("bb_prospect_id") or ""), email=str(item.get("email") or ""), status=SMARTLEAD_PUBLISH_STATUS_FAILED, campaign_id=campaign_id, error_code=exc.code, reason=exc.message, batch_index=batch_index))
                for remaining in payload_batches[batch_index:]:
                    for item in remaining:
                        lead_results.append(SmartleadPublishedLead(publication_key=str(item.get("_publication_key") or ""), prospect_id=str(item.get("custom_fields", {}).get("bb_prospect_id") or ""), email=str(item.get("email") or ""), status=SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED, campaign_id=campaign_id, batch_index=batch_index + 1))
                break
            else:
                succeeded_ids = self._extract_remote_ids(response, batch)
                for item in batch:
                    email = str(item.get("email") or "")
                    lead_results.append(SmartleadPublishedLead(publication_key=str(item.get("_publication_key") or ""), prospect_id=str(item.get("custom_fields", {}).get("bb_prospect_id") or ""), email=email, status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id=succeeded_ids.get(email, ""), published_at=self._now(), campaign_id=campaign_id, batch_index=batch_index))
                cursor += len(batch)

        receipt = SmartleadPublicationReceipt.create(
            source_package_id=str(manifest.get("package_id") or ""),
            source_package_directory=package_root,
            handoff_manifest_path=os.path.join(handoff_directory, "smartlead_handoff_manifest.json"),
            campaign_id=campaign_id,
            campaign_name=campaign_name or details.name,
            target_mode=target.mode,
            mode=resolved_mode,
            total_candidates=len(preflight_rows),
            lead_results=lead_results,
        )
        self._receipt_store.append(receipt)
        self._receipt_store.save()
        return SmartleadPublishResult(
            success=receipt.failed == 0,
            message="Smartlead upload completed." if receipt.failed == 0 else "Smartlead upload completed with partial failure.",
            mode=resolved_mode,
            target_mode=target.mode,
            dry_run=False,
            campaign_id=campaign_id,
            campaign_name=campaign_name or details.name,
            total_candidates=len(preflight_rows),
            eligible=len(candidates),
            blocked_or_conflict=blocked,
            attempted=receipt.attempted,
            succeeded=receipt.succeeded,
            skipped=receipt.skipped,
            failed=receipt.failed,
            batches_planned=len(payload_batches),
            batches_attempted=attempted_batches,
            receipt=receipt,
            payload_preview=tuple(payload_preview),
            lead_results=tuple(lead_results),
        )

    def _resolve_live_target(self, target: SmartleadPublishTarget) -> tuple[str, str]:
        if target.mode == SMARTLEAD_TARGET_MODE_CREATE_DRAFT:
            created = self._api_client.create_campaign(target.create_name)
            return created.campaign_id, created.name
        return str(target.campaign_id or ""), str(target.campaign_name or "")

    # ------------------------------------------------------------------
    # Hosted-URL sync for already-published leads (Sprint 5R)
    # ------------------------------------------------------------------
    def sync_hosted_urls(
        self,
        *,
        source_package_id: str,
        campaign_id: str,
        mode: str = SMARTLEAD_PUBLISH_MODE_DRY_RUN,
        live_enabled: bool = False,
        confirmed: bool = False,
        asset_store: HostedAssetStore | None = None,
    ) -> SmartleadUrlSyncResult:
        resolved_mode = SMARTLEAD_PUBLISH_MODE_LIVE if mode == SMARTLEAD_PUBLISH_MODE_LIVE else SMARTLEAD_PUBLISH_MODE_DRY_RUN
        if resolved_mode == SMARTLEAD_PUBLISH_MODE_LIVE and (not live_enabled or not confirmed):
            return SmartleadUrlSyncResult(
                success=False,
                message="Live URL sync requires explicit enable and confirmation.",
                mode=resolved_mode,
                source_package_id=source_package_id,
                campaign_id=campaign_id,
            )
        dry_run = resolved_mode != SMARTLEAD_PUBLISH_MODE_LIVE
        store = asset_store or self._hosted_asset_store
        receipts = [
            receipt
            for receipt in self._receipt_store.list()
            if receipt.source_package_id == source_package_id and receipt.campaign_id == campaign_id
        ]
        overall_results: list[SmartleadUrlSyncLeadResult] = []
        synced = 0
        skipped = 0
        failed = 0
        not_syncable = 0

        for receipt in receipts:
            updated_leads: list[SmartleadPublishedLead] = []
            changed = False
            for lead in receipt.lead_results:
                if lead.status != SMARTLEAD_PUBLISH_STATUS_SUCCEEDED or not lead.remote_lead_id:
                    continue
                expected_url = self._resolve_hosted_url(lead.prospect_id, store)
                if not expected_url:
                    not_syncable += 1
                    overall_results.append(
                        SmartleadUrlSyncLeadResult(
                            publication_key=lead.publication_key,
                            prospect_id=lead.prospect_id,
                            email=lead.email,
                            status=SMARTLEAD_HOSTED_SYNC_NOT_SYNCABLE,
                            remote_lead_id=lead.remote_lead_id,
                            reason="No valid hosted HTTPS mockup URL available for this prospect.",
                        )
                    )
                    continue
                if lead.hosted_sync_status == SMARTLEAD_HOSTED_SYNC_SYNCED and lead.hosted_mockup_url == expected_url:
                    skipped += 1
                    overall_results.append(
                        SmartleadUrlSyncLeadResult(
                            publication_key=lead.publication_key,
                            prospect_id=lead.prospect_id,
                            email=lead.email,
                            status=SMARTLEAD_HOSTED_SYNC_SKIPPED,
                            hosted_mockup_url=expected_url,
                            remote_lead_id=lead.remote_lead_id,
                            reason="Already synchronized to the expected hosted URL.",
                        )
                    )
                    continue
                if dry_run:
                    overall_results.append(
                        SmartleadUrlSyncLeadResult(
                            publication_key=lead.publication_key,
                            prospect_id=lead.prospect_id,
                            email=lead.email,
                            status=SMARTLEAD_HOSTED_SYNC_PENDING,
                            hosted_mockup_url=expected_url,
                            remote_lead_id=lead.remote_lead_id,
                            reason="Would update bb_mockup_url.",
                        )
                    )
                    continue
                try:
                    self._api_client.update_campaign_lead(campaign_id, lead.remote_lead_id, {"bb_mockup_url": expected_url})
                except SmartleadApiError as exc:
                    failed += 1
                    overall_results.append(
                        SmartleadUrlSyncLeadResult(
                            publication_key=lead.publication_key,
                            prospect_id=lead.prospect_id,
                            email=lead.email,
                            status=SMARTLEAD_HOSTED_SYNC_FAILED,
                            hosted_mockup_url=expected_url,
                            remote_lead_id=lead.remote_lead_id,
                            reason=f"Update failed: {exc.message}",
                        )
                    )
                    continue
                synced += 1
                overall_results.append(
                    SmartleadUrlSyncLeadResult(
                        publication_key=lead.publication_key,
                        prospect_id=lead.prospect_id,
                        email=lead.email,
                        status=SMARTLEAD_HOSTED_SYNC_SYNCED,
                        hosted_mockup_url=expected_url,
                        remote_lead_id=lead.remote_lead_id,
                        asset_id=next((a.identity_key() for a in store.find_by_prospect(lead.prospect_id) if a.has_valid_public_url), ""),
                        reason="Updated bb_mockup_url on existing lead.",
                    )
                )
                updated_leads.append(
                    lead.replaced(
                        hosted_mockup_url=expected_url,
                        hosted_sync_status=SMARTLEAD_HOSTED_SYNC_SYNCED,
                        last_synced_at=self._now(),
                    )
                )
                changed = True

            if not dry_run and changed:
                from dataclasses import replace as _replace

                updated_receipt = _replace(
                    receipt,
                    lead_results=tuple(_merge_lead_results(receipt.lead_results, updated_leads)),
                )
                self._receipt_store.replace(updated_receipt)
                self._receipt_store.save()

        if dry_run:
            return SmartleadUrlSyncResult(
                success=True,
                message=f"URL sync dry run prepared for {len(receipts)} receipt(s). No live writes performed.",
                mode=resolved_mode,
                source_package_id=source_package_id,
                campaign_id=campaign_id,
                total=len(overall_results),
                synced=0,
                skipped=skipped,
                failed=0,
                not_syncable=not_syncable,
                results=tuple(overall_results),
            )
        return SmartleadUrlSyncResult(
            success=failed == 0,
            message="URL sync completed." if failed == 0 else "URL sync completed with partial failure.",
            mode=resolved_mode,
            source_package_id=source_package_id,
            campaign_id=campaign_id,
            total=len(overall_results),
            synced=synced,
            skipped=skipped,
            failed=failed,
            not_syncable=not_syncable,
            results=tuple(overall_results),
        )

    def _resolve_hosted_url(self, prospect_id: str, store: HostedAssetStore) -> str:
        assets = [asset for asset in store.find_by_prospect(prospect_id) if is_valid_public_url(asset.public_url)]
        assets.sort(key=lambda asset: asset.hosted_at)
        return assets[-1].public_url if assets else ""

    def _load_handoff(self, handoff_directory: str):
        root = os.path.abspath(handoff_directory)
        preflight_path = os.path.join(root, "smartlead_preflight.csv")
        csv_path = os.path.join(root, "smartlead.csv")
        handoff_manifest_path = os.path.join(root, "smartlead_handoff_manifest.json")
        with open(handoff_manifest_path, "r", encoding="utf-8") as handle:
            handoff_manifest = json.load(handle)
        package_root = os.path.abspath(str(handoff_manifest.get("package_directory") or os.path.dirname(root)))
        with open(os.path.join(package_root, "manifest.json"), "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        with open(preflight_path, "r", encoding="utf-8", newline="") as handle:
            preflight_rows = list(csv.DictReader(handle))
        final_rows: list[dict[str, str]] = []
        if os.path.isfile(csv_path):
            with open(csv_path, "r", encoding="utf-8", newline="") as handle:
                final_rows = list(csv.DictReader(handle))
        return package_root, manifest, handoff_manifest, preflight_rows, final_rows

    def _build_publishable_leads(self, package_root: str, manifest: dict[str, Any], handoff_manifest: dict[str, Any], preflight_rows: list[dict[str, str]], final_rows: list[dict[str, str]]) -> list[SmartleadPublishLead]:
        final_by_id = {str(row.get("prospect_id") or ""): row for row in final_rows}
        leads: list[SmartleadPublishLead] = []
        for row in list(handoff_manifest.get("rows") or []):
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").upper()
            if status not in {"READY", "WARNING"}:
                continue
            prospect_id = str(row.get("prospect_id") or "")
            payload_row = final_by_id.get(prospect_id)
            if not payload_row:
                continue
            email = str(payload_row.get("email") or "").strip()
            publication_key = f"{manifest.get('package_id', '')}:{prospect_id}:{email.lower()}"
            custom_fields = self._custom_fields(payload_row)
            custom_fields["bb_prospect_id"] = prospect_id
            leads.append(
                SmartleadPublishLead(
                    publication_key=publication_key,
                    prospect_id=prospect_id,
                    email=email,
                    first_name=str(payload_row.get("first_name") or ""),
                    company=str(payload_row.get("company") or ""),
                    custom_fields=custom_fields,
                    local_mockup_path=str(payload_row.get("mockup_path") or payload_row.get("mockup_relative_path") or ""),
                    source_row=dict(payload_row),
                )
            )
        return leads

    def _custom_fields(self, row: dict[str, str]) -> dict[str, str]:
        payload: dict[str, str] = {}
        for source, destination in SMARTLEAD_CUSTOM_FIELD_MAP.items():
            value = str(row.get(source) or "")
            if value:
                payload[destination] = value
        return payload

    def _lead_payload(self, lead: SmartleadPublishLead) -> dict[str, Any]:
        payload = {
            "email": lead.email,
            "first_name": lead.first_name,
            "company_name": lead.company,
            "custom_fields": dict(lead.custom_fields),
            "_publication_key": lead.publication_key,
        }
        return payload

    def _successful_publication_keys(self, *, source_package_id: str, campaign_id: str) -> set[str]:
        keys: set[str] = set()
        for receipt in self._receipt_store.list():
            if receipt.source_package_id != source_package_id or receipt.campaign_id != campaign_id:
                continue
            for lead in receipt.lead_results:
                if lead.status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED:
                    keys.add(lead.publication_key)
        return keys

    def _extract_remote_ids(self, response: Any, batch: list[dict[str, Any]]) -> dict[str, str]:
        result: dict[str, str] = {}
        if isinstance(response, dict):
            for container_key in ("data", "leads", "inserted_leads", "created_leads"):
                container = response.get(container_key)
                if isinstance(container, list):
                    for item in container:
                        if isinstance(item, dict):
                            email = str(item.get("email") or "")
                            result[email] = str(item.get("id") or item.get("lead_id") or "")
            skipped = response.get("skipped_leads")
            if isinstance(skipped, list):
                for item in skipped:
                    if isinstance(item, dict):
                        email = str(item.get("email") or "")
                        result.setdefault(email, str(item.get("id") or item.get("lead_id") or ""))
        return result

    def _batch(self, items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        if size <= 0:
            return [list(items)] if items else []
        return [items[index:index + size] for index in range(0, len(items), size)]

    def _now(self) -> str:
        from gui.models.smartlead_publication import utc_now_iso

        return utc_now_iso()


def _merge_lead_results(
    existing_leads: tuple[SmartleadPublishedLead, ...],
    updated_leads: list[SmartleadPublishedLead],
) -> list[SmartleadPublishedLead]:
    """Return existing leads with the updated ones overlaid by publication_key."""
    by_key = {lead.publication_key: lead for lead in existing_leads}
    for lead in updated_leads:
        by_key[lead.publication_key] = lead
    return [by_key[lead.publication_key] for lead in existing_leads]