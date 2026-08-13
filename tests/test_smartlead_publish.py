from __future__ import annotations

import csv
import json
import os

from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_DRY_RUN,
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_TARGET_MODE_CREATE_DRAFT,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadCampaignDetails,
    SmartleadPublishTarget,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.services.smartlead_publish import SmartleadPublishService, UPLOAD_BATCH_SIZE


class FakeApiClient:
    def __init__(self):
        self.add_calls = []
        self.created = []
        self.settings = SmartleadConnectionSettings()
        self.fail_batch = False

    def test_connection(self):
        return type("Result", (), {"connected": True, "status": "CONNECTED", "message": "ok"})()

    def list_campaigns(self):
        return []

    def create_campaign(self, name):
        self.created.append(name)
        return SmartleadCampaignDetails(campaign_id="900", name=name, status="DRAFTED")

    def get_campaign(self, campaign_id):
        return SmartleadCampaignDetails(campaign_id=campaign_id, name="Existing", status="DRAFTED", sequence_count=1, email_account_count=1, raw_sequence_configured=True, raw_sender_accounts_configured=True)

    def add_leads(self, campaign_id, lead_list):
        self.add_calls.append((campaign_id, lead_list))
        if self.fail_batch and len(self.add_calls) == 2:
            from gui.services.smartlead_api import SmartleadApiError

            raise SmartleadApiError("UNAVAILABLE", "Smartlead service unavailable.")
        return {"data": [{"email": item["email"], "id": f"lead-{index}"} for index, item in enumerate(lead_list, start=1)]}


def _seed_handoff(root):
    package_dir = os.path.join(root, "package")
    handoff_dir = os.path.join(package_dir, "handoff")
    os.makedirs(handoff_dir, exist_ok=True)
    with open(os.path.join(package_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"package_id": "pkg-1", "prospects": [{"prospect_id": "a", "status": "READY"}, {"prospect_id": "b", "status": "WARNING"}, {"prospect_id": "c", "status": "BLOCKED"}, {"prospect_id": "d", "status": "CONFLICT"}, {"prospect_id": "e", "status": "CONFLICT"}]}, handle)
    with open(os.path.join(handoff_dir, "smartlead_preflight.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["prospect_id", "company", "email", "status", "reason", "warning"])
        writer.writeheader()
        writer.writerows([
            {"prospect_id": "a", "company": "Alpha", "email": "a@example.com", "status": "READY", "reason": "", "warning": ""},
            {"prospect_id": "b", "company": "Bravo", "email": "b@example.com", "status": "WARNING", "reason": "", "warning": "Missing contact name."},
            {"prospect_id": "c", "company": "Charlie", "email": "c@example.com", "status": "BLOCKED", "reason": "bad", "warning": ""},
            {"prospect_id": "d", "company": "Delta", "email": "dup@example.com", "status": "CONFLICT", "reason": "dup", "warning": ""},
            {"prospect_id": "e", "company": "Echo", "email": "dup@example.com", "status": "CONFLICT", "reason": "dup", "warning": ""},
        ])
    with open(os.path.join(handoff_dir, "smartlead.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["email", "first_name", "company", "email_subject", "email_body", "mockup_path", "city", "state", "headline", "cta", "personalization_basis", "prospect_id"])
        writer.writeheader()
        writer.writerows([
            {"email": "a@example.com", "first_name": "Alice", "company": "Alpha", "email_subject": "Sub A", "email_body": "Body A", "mockup_path": "mockups/a.png", "city": "Denver", "state": "CO", "headline": "H1", "cta": "C1", "personalization_basis": "company", "prospect_id": "a"},
            {"email": "b@example.com", "first_name": "Bob", "company": "Bravo", "email_subject": "Sub B", "email_body": "Body B", "mockup_path": "mockups/b.png", "city": "Austin", "state": "TX", "headline": "H2", "cta": "C2", "personalization_basis": "location", "prospect_id": "b"},
        ])
    with open(os.path.join(handoff_dir, "smartlead_handoff_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"package_directory": package_dir, "rows": [{"prospect_id": "a", "status": "READY"}, {"prospect_id": "b", "status": "WARNING"}, {"prospect_id": "c", "status": "BLOCKED"}, {"prospect_id": "d", "status": "CONFLICT"}, {"prospect_id": "e", "status": "CONFLICT"}]}, handle)
    return handoff_dir


def test_dry_run_default_and_no_write_requests(tmp_path):
    handoff = _seed_handoff(str(tmp_path))
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=os.path.join(str(tmp_path), "receipts.json")))
    result = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"))
    assert result.dry_run is True
    assert api.add_calls == []


def test_ready_and_warning_rows_publish_payload_only(tmp_path):
    handoff = _seed_handoff(str(tmp_path))
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=os.path.join(str(tmp_path), "receipts.json")))
    result = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"))
    assert len(result.payload_preview) == 2
    first = result.payload_preview[0]
    assert first["custom_fields"]["bb_subject"] == "Sub A"
    assert first["custom_fields"]["bb_body"] == "Body A"


def test_blocked_conflict_and_nonapproved_never_publish(tmp_path):
    handoff = _seed_handoff(str(tmp_path))
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=os.path.join(str(tmp_path), "receipts.json")))
    result = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"))
    emails = [item["email"] for item in result.payload_preview]
    assert emails == ["a@example.com", "b@example.com"]


def test_batching_multiple_batches_and_stable_order(tmp_path):
    handoff = _seed_handoff(str(tmp_path))
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=os.path.join(str(tmp_path), "receipts.json")))
    payloads = [{"email": str(index)} for index in range(UPLOAD_BATCH_SIZE * 2 + 1)]
    batches = service._batch(payloads, UPLOAD_BATCH_SIZE)
    assert len(batches) == 3
    assert batches[0][0]["email"] == "0"
    assert batches[-1][-1]["email"] == str(UPLOAD_BATCH_SIZE * 2)


def test_live_partial_failure_and_resume_skip(tmp_path):
    handoff = _seed_handoff(str(tmp_path))
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=os.path.join(str(tmp_path), "receipts.json")))
    original_batch = service._batch
    service._batch = lambda items, size: [items[:1], items[1:]]
    api.fail_batch = True
    result = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert result.failed == 1
    api.fail_batch = False
    resumed = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert resumed.skipped >= 1
    service._batch = original_batch


def test_create_draft_dry_run_and_live_no_activation(tmp_path):
    handoff = _seed_handoff(str(tmp_path))
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=os.path.join(str(tmp_path), "receipts.json")))
    dry = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_CREATE_DRAFT, create_name="New Draft"))
    assert dry.dry_run is True
    assert api.created == []
    live = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_CREATE_DRAFT, create_name="New Draft"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert api.created == ["New Draft"]
    assert live.campaign_id == "900"


def test_receipt_no_api_key_and_persisted_restart_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTLEAD_API_KEY", "super-secret-test-key")
    handoff = _seed_handoff(str(tmp_path))
    store_path = os.path.join(str(tmp_path), "receipts.json")
    api = FakeApiClient()
    service = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=store_path))
    result = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    raw = open(store_path, "r", encoding="utf-8").read()
    assert "super-secret-test-key" not in raw
    restarted = SmartleadPublishService(api_client=api, receipt_store=SmartleadPublicationStore(path=store_path))
    resumed = restarted.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert resumed.skipped == 2


# ---------------------------------------------------------------------------
# Sprint 5R hosted-URL sync
# ---------------------------------------------------------------------------
import json as _json  # noqa: E402

from gui.models.hosted_asset import HostedMockupAsset
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
)
from gui.services.smartlead_api import SmartleadApiError
from gui.services.smartlead_publish import SMARTLEAD_CUSTOM_FIELD_MAP


def test_custom_field_map_includes_bb_mockup_url():
    assert SMARTLEAD_CUSTOM_FIELD_MAP.get("mockup_url") == "bb_mockup_url"


class FakeSyncApiClient:
    def __init__(self):
        self.update_calls = []
        self.add_calls = []
        self.activation_calls = []
        self.fail_lead_ids = set()
        self.settings = SmartleadConnectionSettings()

    def update_campaign_lead(self, campaign_id, lead_id, custom_fields):
        self.update_calls.append((campaign_id, lead_id, dict(custom_fields)))
        if lead_id in self.fail_lead_ids:
            raise SmartleadApiError("UNAVAILABLE", "Smartlead service unavailable.")
        return {"success": True}

    def add_leads(self, campaign_id, lead_list):
        self.add_calls.append((campaign_id, lead_list))


def _seed_sync_stores(tmp_path):
    host = HostedAssetStore(path=os.path.join(str(tmp_path), "hosted.json"))
    host.put(HostedMockupAsset(prospect_id="a", generation_job_id="job-a", project_id="p1", source_path="mockups/a.png", source_fingerprint="fpa", provider="fake", provider_asset_id="billboardai/pkg/a/job-a", public_url="https://cdn.example.com/a.png", secure_url="https://cdn.example.com/a.png", hosted_at="2026-01-01T00:00:00+00:00"))
    host.put(HostedMockupAsset(prospect_id="b", generation_job_id="job-b", project_id="p1", source_path="mockups/b.png", source_fingerprint="fpb", provider="fake", provider_asset_id="billboardai/pkg/b/job-b", public_url="https://cdn.example.com/b.png", secure_url="https://cdn.example.com/b.png", hosted_at="2026-01-01T00:00:00+00:00"))
    host.save()
    pub = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    receipt = SmartleadPublicationReceipt.create(
        source_package_id="pkg-1",
        source_package_directory="",
        handoff_manifest_path="",
        campaign_id="1",
        campaign_name="Camp",
        target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
        mode=SMARTLEAD_PUBLISH_MODE_LIVE,
        total_candidates=2,
        lead_results=[
            SmartleadPublishedLead(publication_key="pkg-1:a:a@x.com", prospect_id="a", email="a@x.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1"),
            SmartleadPublishedLead(publication_key="pkg-1:b:b@x.com", prospect_id="b", email="b@x.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-b", campaign_id="1"),
        ],
    )
    pub.append(receipt)
    pub.save()
    return host, pub


def _sync_service(tmp_path, api):
    host, pub = _seed_sync_stores(tmp_path)
    return SmartleadPublishService(api_client=api, receipt_store=pub, hosted_asset_store=host), pub


def test_sync_updates_existing_leads_without_duplicates(tmp_path):
    api = FakeSyncApiClient()
    service, _ = _sync_service(tmp_path, api)
    result = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert result.synced == 2
    assert api.add_calls == []  # no duplicate lead creation
    assert len(api.update_calls) == 2
    lead_ids = {call[1] for call in api.update_calls}
    assert lead_ids == {"lead-a", "lead-b"}
    for _, _, fields in api.update_calls:
        assert fields.get("bb_mockup_url").startswith("https://")


def test_sync_local_path_never_substituted_for_public_url(tmp_path):
    api = FakeSyncApiClient()
    service, _ = _sync_service(tmp_path, api)
    result = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    urls = [fields.get("bb_mockup_url") for _, _, fields in api.update_calls]
    for url in urls:
        assert url.startswith("https://")
        assert not str(url).lower().startswith(("d:", "c:"))
        assert "local_mockup" not in str(url)


def test_sync_idempotent_second_run_skips(tmp_path):
    api = FakeSyncApiClient()
    service, _ = _sync_service(tmp_path, api)
    first = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert first.synced == 2
    first_call_count = len(api.update_calls)
    second = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert second.skipped == 2
    assert len(api.update_calls) == first_call_count


def test_sync_partial_failure_and_retry_failed_only(tmp_path):
    api = FakeSyncApiClient()
    service, _ = _sync_service(tmp_path, api)
    api.fail_lead_ids = {"lead-b"}
    first = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert first.synced == 1 and first.failed == 1
    api.fail_lead_ids = set()
    second = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert second.skipped >= 1  # a already synced, skipped
    assert second.failed == 0
    synced_lead_ids = {call[1] for call in api.update_calls}
    assert "lead-b" in synced_lead_ids


def test_sync_restart_resume_skips_synced(tmp_path):
    api = FakeSyncApiClient()
    host, pub = _seed_sync_stores(tmp_path)
    service = SmartleadPublishService(api_client=api, receipt_store=pub, hosted_asset_store=host)
    service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    # Restart: fresh services reloading the persisted stores.
    api2 = FakeSyncApiClient()
    host2 = HostedAssetStore(path=host.path)
    pub2 = SmartleadPublicationStore(path=pub.path)
    service2 = SmartleadPublishService(api_client=api2, receipt_store=pub2, hosted_asset_store=host2)
    result = service2.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    assert result.skipped == 2
    assert api2.update_calls == []


def test_sync_per_prospect_isolation(tmp_path):
    api = FakeSyncApiClient()
    service, _ = _sync_service(tmp_path, api)
    service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
    by_lead = {call[1]: call[2].get("bb_mockup_url") for call in api.update_calls}
    assert by_lead["lead-a"] == "https://cdn.example.com/a.png"
    assert by_lead["lead-b"] == "https://cdn.example.com/b.png"


def test_sync_requires_confirmation_and_live(tmp_path):
    api = FakeSyncApiClient()
    service, _ = _sync_service(tmp_path, api)
    result = service.sync_hosted_urls(source_package_id="pkg-1", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=False)
    assert result.success is False
    assert api.update_calls == []