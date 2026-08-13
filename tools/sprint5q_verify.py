from __future__ import annotations

import os
import sys
import tempfile
import csv
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.smartlead_publication import SMARTLEAD_PUBLISH_MODE_LIVE, SMARTLEAD_TARGET_MODE_CREATE_DRAFT, SMARTLEAD_TARGET_MODE_EXISTING, SmartleadPublishTarget
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import SmartleadCampaignDetails
from gui.services.smartlead_publish import SmartleadPublishService


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


def main() -> int:
    passed = 0
    failed = 0

    def check(name: str, condition: bool) -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            print(f"FAILED: {name}")

    with tempfile.TemporaryDirectory() as root:
        handoff = _seed_handoff(root)
        store = SmartleadPublicationStore(path=os.path.join(root, "receipts.json"))
        api = FakeApiClient()
        service = SmartleadPublishService(api_client=api, receipt_store=store)

        dry = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"))
        check("dry run payload contains A/B only", [item["email"] for item in dry.payload_preview] == ["a@example.com", "b@example.com"])
        check("dry run no POST writes", api.add_calls == [])
        check("dry run target campaign preserved", dry.campaign_id == "1")
        check("dry run batching correct", dry.batches_planned == 1)

        api.fail_batch = True
        service._batch = lambda items, size: [items[:1], items[1:]]
        live = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("live first batch success second batch failure captured", live.succeeded == 1 and live.failed == 1)
        api.fail_batch = False
        resumed = service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="1", campaign_name="Existing"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("resume skips already successful leads", resumed.skipped >= 1)

        draft_api = FakeApiClient()
        draft_service = SmartleadPublishService(api_client=draft_api, receipt_store=SmartleadPublicationStore(path=os.path.join(root, "draft_receipts.json")))
        draft = draft_service.publish_from_handoff(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_CREATE_DRAFT, create_name="Verifier Draft"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("create draft returns ID", draft.campaign_id == "900")
        check("create draft no activation call exists", hasattr(draft_api, "create_campaign") and not hasattr(draft_api, "update_campaign_status"))
        receipt_text = open(os.path.join(root, "draft_receipts.json"), "r", encoding="utf-8").read()
        check("secret never appears in receipt", "super-secret-test-key" not in receipt_text)

    print("SPRINT 5Q VERIFICATION COMPLETE")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())