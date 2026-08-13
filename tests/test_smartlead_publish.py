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