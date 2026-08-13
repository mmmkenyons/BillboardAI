"""Sprint 5S verifier -- synthetic only, no live network."""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.hosted_asset import HostedMockupAsset
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_PUBLISH_STATUS_FAILED,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadCampaignDetails,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
    SmartleadPublishTarget,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_publish import SmartleadPublishService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService


class FakeSmartleadApi:
    def __init__(self):
        self.settings = SmartleadConnectionSettings()
        self.campaigns = {
            "alpha": SmartleadCampaignDetails(campaign_id="alpha", name="Campaign Alpha", status="DRAFTED"),
            "beta": SmartleadCampaignDetails(campaign_id="beta", name="Campaign Beta", status="DRAFTED"),
        }
        self.remote_leads = {
            "alpha": [{"id": "lead-A", "email": "a@example.com"}],
            "beta": [{"id": "lead-Z", "email": "z@example.com"}],
        }
        self.sequence = [{"id": "seq1", "steps": [{"subject": "{{bb_subject}}", "content": "{{bb_body}}\n{{bb_mockup_url}}"}]}]
        self.accounts = [{"id": "acct-1"}]
        self.add_calls = []
        self.activation_calls = []

    def get_campaign(self, campaign_id):
        if campaign_id not in self.campaigns:
            from gui.services.smartlead_api import SmartleadApiError

            raise SmartleadApiError("NOT_FOUND", "Campaign not found.")
        return self.campaigns[campaign_id]

    def get_campaign_leads(self, campaign_id):
        return list(self.remote_leads.get(campaign_id, []))

    def get_campaign_sequences(self, campaign_id):
        return list(self.sequence)

    def get_campaign_email_accounts(self, campaign_id):
        return list(self.accounts)

    def add_leads(self, campaign_id, lead_list):
        self.add_calls.append((campaign_id, list(lead_list)))
        created = []
        for item in lead_list:
            lead_id = f"lead-{item['custom_fields']['bb_prospect_id']}"
            payload = {"id": lead_id, "email": item["email"]}
            self.remote_leads.setdefault(campaign_id, []).append(payload)
            created.append(payload)
        return {"data": created}


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1




def _seed_handoff(root: str) -> str:
    package_dir = os.path.join(root, "package")
    handoff_dir = os.path.join(package_dir, "handoff")
    os.makedirs(handoff_dir, exist_ok=True)
    with open(os.path.join(package_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"package_id": "pkg-alpha"}, handle)
    with open(os.path.join(handoff_dir, "smartlead_handoff_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"package_directory": package_dir, "rows": [{"prospect_id": "A", "status": "READY"}, {"prospect_id": "B", "status": "READY"}, {"prospect_id": "C", "status": "READY"}]}, handle)
    import csv

    with open(os.path.join(handoff_dir, "smartlead_preflight.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["prospect_id", "company", "email", "status", "reason", "warning"])
        writer.writeheader()
        writer.writerows([
            {"prospect_id": "A", "company": "Alpha A", "email": "a@example.com", "status": "READY", "reason": "", "warning": ""},
            {"prospect_id": "B", "company": "Bravo B", "email": "b@example.com", "status": "READY", "reason": "", "warning": ""},
            {"prospect_id": "C", "company": "Charlie C", "email": "c@example.com", "status": "READY", "reason": "", "warning": ""},
        ])
    with open(os.path.join(handoff_dir, "smartlead.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["email", "first_name", "company", "email_subject", "email_body", "mockup_path", "city", "state", "headline", "cta", "personalization_basis", "prospect_id"])
        writer.writeheader()
        writer.writerows([
            {"email": "a@example.com", "first_name": "A", "company": "Alpha A", "email_subject": "s1", "email_body": "b1", "mockup_path": "a.png", "city": "X", "state": "CO", "headline": "h1", "cta": "c1", "personalization_basis": "p1", "prospect_id": "A"},
            {"email": "b@example.com", "first_name": "B", "company": "Bravo B", "email_subject": "s2", "email_body": "b2", "mockup_path": "b.png", "city": "X", "state": "CO", "headline": "h2", "cta": "c2", "personalization_basis": "p2", "prospect_id": "B"},
            {"email": "c@example.com", "first_name": "C", "company": "Charlie C", "email_subject": "s3", "email_body": "b3", "mockup_path": "c.png", "city": "X", "state": "CO", "headline": "h3", "cta": "c3", "personalization_basis": "p3", "prospect_id": "C"},
        ])
    return handoff_dir


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    with tempfile.TemporaryDirectory() as root:
        api = FakeSmartleadApi()
        handoff = _seed_handoff(root)
        pub = SmartleadPublicationStore(path=os.path.join(root, "pub.json"))
        pub.append(
            SmartleadPublicationReceipt.create(
                source_package_id="pkg-alpha",
                source_package_directory=os.path.join(root, "package"),
                handoff_manifest_path="",
                campaign_id="alpha",
                campaign_name="Campaign Alpha",
                target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
                mode=SMARTLEAD_PUBLISH_MODE_LIVE,
                total_candidates=3,
                lead_results=[
                    SmartleadPublishedLead(publication_key="pkg-alpha:A:a@example.com", prospect_id="A", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-A", campaign_id="alpha"),
                    SmartleadPublishedLead(publication_key="pkg-alpha:B:b@example.com", prospect_id="B", email="b@example.com", status=SMARTLEAD_PUBLISH_STATUS_FAILED, campaign_id="alpha"),
                ],
            )
        )
        pub.save()
        hosted = HostedAssetStore(path=os.path.join(root, "hosted.json"))
        for prospect_id in ["A", "B", "C"]:
            hosted.put(HostedMockupAsset(prospect_id=prospect_id, generation_job_id=f"job-{prospect_id}", project_id="p1", source_path=f"{prospect_id}.png", source_fingerprint=f"fp-{prospect_id}", provider="fake", provider_asset_id=f"asset-{prospect_id}", public_url=f"https://cdn.example.com/{prospect_id}.png", secure_url=f"https://cdn.example.com/{prospect_id}.png", hosted_at="2026-01-01T00:00:00+00:00"))
        hosted.save()

        publish = SmartleadPublishService(api_client=api, receipt_store=pub, hosted_asset_store=hosted)
        seq = SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=os.path.join(root, "seq.json")))
        reconcile = SmartleadReconciliationService(api_client=api, publication_store=pub, hosted_asset_store=hosted, sequence_service=seq)

        first = reconcile.reconcile_campaign(source_package_id="pkg-alpha", campaign_id="alpha")
        ready1 = reconcile.evaluate_launch_readiness(source_package_id="pkg-alpha", campaign_id="alpha")
        check("Initial reconciliation identifies incomplete state", first.reconciliation_required is True or ready1.status != "READY", counts)
        check("Initial overall not ready", ready1.status != "READY", counts)

        resumed = publish.resume_publication(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="alpha", campaign_name="Campaign Alpha"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("Resume skips already successful A", resumed.skipped >= 1, counts)
        check("Resume publishes remaining prospects", resumed.succeeded >= 2, counts)

        second = reconcile.reconcile_campaign(source_package_id="pkg-alpha", campaign_id="alpha")
        ready2 = reconcile.evaluate_launch_readiness(source_package_id="pkg-alpha", campaign_id="alpha")
        check("Second reconciliation no longer reports unresolved mismatch", second.reconciliation_required is False, counts)
        check("Overall becomes READY", ready2.status == "READY", counts)

        add_before = len(api.add_calls)
        again = publish.resume_publication(handoff, target=SmartleadPublishTarget(mode=SMARTLEAD_TARGET_MODE_EXISTING, campaign_id="alpha", campaign_name="Campaign Alpha"), mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("Repeated resume is idempotent", len(api.add_calls) == add_before and again.skipped >= 3, counts)

        beta = reconcile.reconcile_campaign(source_package_id="pkg-alpha", campaign_id="beta")
        check("Campaign Beta stays isolated", beta.remote_only >= 1 and beta.campaign_id == "beta", counts)
        check("No campaign activation occurred", api.activation_calls == [], counts)

    print("SPRINT 5S VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())