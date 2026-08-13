"""Sprint 5R verifier -- NO live network.

Uses a fake hosting provider and a fake Smartlead transport to prove the hosted
mockup + sequence readiness layer end to end: hosting dry-run/live, receipts,
idempotent reuse, URL sync, sequence readiness, and explicit draft-sequence
preparation with ABSOLUTELY NO campaign activation call.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.hosted_asset import (
    HOSTING_MODE_LIVE,
    HOSTING_STATUS_BLOCKED,
    HOSTING_STATUS_PENDING,
    HOSTING_STATUS_REUSED,
)
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadCampaignDetails,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
    SmartleadPublishTarget,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.asset_hosting import HostingConnectionResult, UploadedAsset
from gui.services.hosted_mockups import AssetHostingService, sha256_file
from gui.services.smartlead_publish import SmartleadPublishService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService


class FakeAssetProvider:
    name = "fake"

    def __init__(self):
        self.uploads = []

    def test_connection(self):
        return HostingConnectionResult(connected=True, status="CONNECTED", message="ok")

    def upload_asset(self, *, source_path, public_id):
        self.uploads.append((source_path, public_id))
        return UploadedAsset(provider_asset_id=public_id, public_url=f"https://cdn.example.com/{public_id}", secure_url=f"https://cdn.example.com/{public_id}")

    def resolve_existing(self, *, public_id):
        return None

    def delete_asset(self, *, public_id):
        return True


class FakeSmartleadApi:
    def __init__(self, *, status="DRAFTED"):
        self.settings = SmartleadConnectionSettings()
        self.status = status
        self.reset_sequence()
        self.accounts = [{"id": "acct-1"}]
        self.sequence_write_calls = []
        self.activation_calls = []
        self.update_calls = []

    def reset_sequence(self):
        # Initial state: no sequence is configured -> readiness blocked.
        self.sequences = []

    def get_campaign(self, campaign_id):
        return SmartleadCampaignDetails(campaign_id=campaign_id, name="Camp", status=self.status, sequence_count=len(self.sequences), email_account_count=len(self.accounts))

    def get_campaign_sequences(self, campaign_id):
        return list(self.sequences)

    def get_campaign_email_accounts(self, campaign_id):
        return list(self.accounts)

    def add_sequence(self, campaign_id, payload):
        self.sequence_write_calls.append((campaign_id, payload))
        step = payload["steps"][0]
        self.sequences = [{"id": "s1", "steps": [{"subject": step["subject"], "content": step["content"]}]}]

    def update_campaign_lead(self, campaign_id, lead_id, custom_fields):
        self.update_calls.append((campaign_id, lead_id, dict(custom_fields)))

    def start_campaign(self, campaign_id):  # ONLY present to prove it is never invoked
        self.activation_calls.append(campaign_id)


def _seed(root):
    package_dir = os.path.join(str(root), "package")
    handoff_dir = os.path.join(package_dir, "handoff")
    mockups_dir = os.path.join(package_dir, "mockups")
    os.makedirs(mockups_dir, exist_ok=True)
    os.makedirs(handoff_dir, exist_ok=True)
    for name in ("alpha.png", "bravo.png"):
        with open(os.path.join(mockups_dir, name), "w", encoding="utf-8") as handle:
            handle.write(f"mockup-content-{name}")
    manifest = {
        "package_id": "pkg-5r",
        "prospects": [
            {"prospect_id": "A", "status": "READY", "mockup_relative_path": "mockups/alpha.png", "generation_job_id": "job-A", "project_id": "proj"},
            {"prospect_id": "B", "status": "WARNING", "mockup_relative_path": "mockups/bravo.png", "generation_job_id": "job-B", "project_id": "proj"},
            {"prospect_id": "C", "status": "BLOCKED", "mockup_relative_path": "mockups/c.png", "generation_job_id": "job-C", "project_id": "proj"},
        ],
    }
    with open(os.path.join(package_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    with open(os.path.join(package_dir, "mockups", "c.png"), "w", encoding="utf-8") as handle:
        handle.write("?")
    handoff = {"package_directory": package_dir, "rows": [
        {"prospect_id": "A", "status": "READY"},
        {"prospect_id": "B", "status": "WARNING"},
        {"prospect_id": "C", "status": "BLOCKED"},
    ]}
    with open(os.path.join(handoff_dir, "smartlead_handoff_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(handoff, handle)
    return package_dir, handoff_dir


def main() -> int:
    from gui.models.hosted_asset import HostedMockupAsset

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
        package_dir, handoff = _seed(root)
        provider = FakeAssetProvider()
        store_path = os.path.join(root, "hosted_receipts.json")
        # Scenario B is previously hosted -> seed its durable receipt.
        pre_store = HostedAssetStore(path=store_path)
        pre_store.put(HostedMockupAsset(
            prospect_id="B", generation_job_id="job-B", project_id="proj",
            source_path=os.path.join(package_dir, "mockups", "bravo.png"),
            source_fingerprint=sha256_file(os.path.join(package_dir, "mockups", "bravo.png")),
            provider="fake", provider_asset_id="billboardai/pkg-5r/B/job-B",
            public_url="https://cdn.example.com/billboardai/pkg-5r/B/job-B",
            secure_url="https://cdn.example.com/billboardai/pkg-5r/B/job-B",
            hosted_at="2026-01-01T00:00:00+00:00",
        ))
        pre_store.save()
        hosting = AssetHostingService(provider=provider, asset_store=HostedAssetStore(path=store_path))

        # 1) Hosting dry run
        dry = hosting.dry_run(package_dir, handoff)
        statuses = {r.prospect_id: r.status for r in dry.results}
        check("hosting dry-run is DRY_RUN", dry.mode == "DRY_RUN")
        check("hosting dry-run does no upload", provider.uploads == [])
        check("dry-run: A pending (not yet hosted)", statuses.get("A") == HOSTING_STATUS_PENDING)
        check("dry-run: B reused (previously hosted)", statuses.get("B") == HOSTING_STATUS_REUSED)
        check("dry-run: C blocked", statuses.get("C") == HOSTING_STATUS_BLOCKED)

        # 2) Hosting fake live
        live = hosting.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
        lstatuses = {r.prospect_id: r.status for r in live.results}
        check("hosting live: A uploaded", lstatuses.get("A") == "HOSTED")
        check("hosting live: B reused (not re-uploaded)", lstatuses.get("B") == HOSTING_STATUS_REUSED)
        check("hosting live: C skipped (blocked)", lstatuses.get("C") == HOSTING_STATUS_BLOCKED)
        check("hosting live: exactly A uploaded once", len(provider.uploads) == 1)

        a_url = next((r.public_url for r in live.results if r.prospect_id == "A"), "")
        check("public URL is HTTPS", a_url.startswith("https://"))

        # Restart reuse
        provider2 = FakeAssetProvider()
        restarted = AssetHostingService(provider=provider2, asset_store=HostedAssetStore(path=store_path))
        again = restarted.host(package_dir, handoff, mode=HOSTING_MODE_LIVE, live_enabled=True, confirmed=True)
        check("restart: no duplicate hosting (both reused)", again.hosted == 0 and again.reused >= 2)
        check("restart: no upload performed", provider2.uploads == [])

        # 3) URL sync to published leads
        pub = SmartleadPublicationStore(path=os.path.join(root, "pub.json"))
        receipt = SmartleadPublicationReceipt.create(
            source_package_id="pkg-5r", source_package_directory=package_dir, handoff_manifest_path="",
            campaign_id="1", campaign_name="Camp", target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
            mode=SMARTLEAD_PUBLISH_MODE_LIVE,
            total_candidates=2,
            lead_results=[
                SmartleadPublishedLead(publication_key="pkg-5r:A:a@x.com", prospect_id="A", email="a@x.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-A", campaign_id="1"),
                SmartleadPublishedLead(publication_key="pkg-5r:B:b@x.com", prospect_id="B", email="b@x.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-B", campaign_id="1"),
            ],
        )
        pub.append(receipt)
        pub.save()

        api_client = FakeSmartleadApi()
        publish_service = SmartleadPublishService(api_client=api_client, receipt_store=pub, hosted_asset_store=HostedAssetStore(path=store_path))
        sync = publish_service.sync_hosted_urls(source_package_id="pkg-5r", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("URL sync: A/B synced", sync.synced == 2)
        check("URL sync: existing leads updated only (no create)", bool(api_client.update_calls) and all(c[1] in {"lead-A", "lead-B"} for c in api_client.update_calls))
        synced_urls = [c[2].get("bb_mockup_url") for c in api_client.update_calls]
        check("URL sync: hosted HTTPS URLs only", all(u.startswith("https://") for u in synced_urls))
        check("URL sync: no local mockup path used", all("D:\\" not in u and "local_mockup" not in u for u in synced_urls))
        sync2 = publish_service.sync_hosted_urls(source_package_id="pkg-5r", campaign_id="1", mode=SMARTLEAD_PUBLISH_MODE_LIVE, live_enabled=True, confirmed=True)
        check("URL sync: idempotent (second run skips)", sync2.skipped == 2 and len(api_client.update_calls) == 2)

        # 4) Sequence readiness + explicit preparation
        seq_service = SmartleadSequenceReadinessService(api_client=api_client, change_store=SequenceChangeStore(path=os.path.join(root, "seq.json")))
        before = seq_service.check_readiness("1")
        check("sequence: initial missing required variables", before.sequence_exists is False and before.bb_subject_present is False)
        check("sequence: readiness blocked initially", before.ready_for_manual_activation is False)
        check("no sequence write before explicit action", api_client.sequence_write_calls == [])
        after = seq_service.prepare_sequence("1", live_enabled=True, confirmed=True)
        check("sequence: explicit preparation writes once", len(api_client.sequence_write_calls) == 1)
        check("sequence: bb_subject present", after.bb_subject_present is True)
        check("sequence: bb_body present", after.bb_body_present is True)
        check("sequence: bb_mockup_url present", after.bb_mockup_url_present is True)
        check("sequence: sender accounts present", after.sender_accounts_present is True)
        check("sequence: readiness indicates MANUAL ACTIVATION", after.ready_for_manual_activation is True)
        check("NO campaign activation API call occurred", api_client.activation_calls == [])

    print("SPRINT 5R VERIFICATION COMPLETE")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())