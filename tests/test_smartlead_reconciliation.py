from __future__ import annotations

import os

from gui.models.hosted_asset import HostedMockupAsset
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_PUBLISH_STATUS_FAILED,
    SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED,
    SMARTLEAD_PUBLISH_STATUS_SKIPPED,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadCampaignDetails,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService


class FakeApi:
    def __init__(self, *, campaigns=None, leads=None, sequences=None, accounts=None):
        self.settings = SmartleadConnectionSettings()
        self.campaigns = {"1": SmartleadCampaignDetails(campaign_id="1", name="Camp 1", status="DRAFTED")} if campaigns is None else campaigns
        self.leads = {"1": []} if leads is None else leads
        self.sequences = {"1": [{"id": "seq1", "steps": [{"subject": "{{bb_subject}}", "content": "{{bb_body}}\n{{bb_mockup_url}}"}]}]} if sequences is None else sequences
        self.accounts = {"1": [{"id": "acct-1"}]} if accounts is None else accounts

    def get_campaign(self, campaign_id):
        if campaign_id not in self.campaigns:
            from gui.services.smartlead_api import SmartleadApiError

            raise SmartleadApiError("NOT_FOUND", "Campaign not found.")
        return self.campaigns[campaign_id]

    def get_campaign_leads(self, campaign_id):
        return list(self.leads.get(campaign_id, []))

    def get_campaign_sequences(self, campaign_id):
        return list(self.sequences.get(campaign_id, []))

    def get_campaign_email_accounts(self, campaign_id):
        return list(self.accounts.get(campaign_id, []))


def _receipt_store(tmp_path, leads, *, campaign_id="1", source_package_id="pkg-1"):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    receipt = SmartleadPublicationReceipt.create(
        source_package_id=source_package_id,
        source_package_directory="",
        handoff_manifest_path="",
        campaign_id=campaign_id,
        campaign_name=f"Camp {campaign_id}",
        target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
        mode=SMARTLEAD_PUBLISH_MODE_LIVE,
        total_candidates=len(leads),
        lead_results=leads,
    )
    store.append(receipt)
    store.save()
    return store


def _hosted_store(tmp_path, prospect_ids):
    store = HostedAssetStore(path=os.path.join(str(tmp_path), "hosted.json"))
    for prospect_id in prospect_ids:
        store.put(
            HostedMockupAsset(
                prospect_id=prospect_id,
                generation_job_id=f"job-{prospect_id}",
                project_id="p1",
                source_path=f"{prospect_id}.png",
                source_fingerprint=f"fp-{prospect_id}",
                provider="fake",
                provider_asset_id=f"asset-{prospect_id}",
                public_url=f"https://cdn.example.com/{prospect_id}.png",
                secure_url=f"https://cdn.example.com/{prospect_id}.png",
                hosted_at="2026-01-01T00:00:00+00:00",
            )
        )
    store.save()
    return store


def _svc(tmp_path, pub_store, api, hosted_store=None):
    seq = SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=os.path.join(str(tmp_path), "seq.json")))
    return SmartleadReconciliationService(
        api_client=api,
        publication_store=pub_store,
        hosted_asset_store=hosted_store or HostedAssetStore(path=os.path.join(str(tmp_path), "hosted-empty.json")),
        sequence_service=seq,
    )


def test_all_published_reconciliation(tmp_path):
    pub = _receipt_store(
        tmp_path,
        [
            SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1"),
            SmartleadPublishedLead(publication_key="pkg-1:b:b@example.com", prospect_id="b", email="b@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-b", campaign_id="1"),
        ],
    )
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}, {"id": "lead-b", "email": "b@example.com"}]})
    result = _svc(tmp_path, pub, api).reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    assert result.matched == 2
    assert result.reconciliation_required is False


def test_local_only_mismatch(tmp_path):
    pub = _receipt_store(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")])
    api = FakeApi(leads={"1": []})
    result = _svc(tmp_path, pub, api).reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    assert result.local_only == 1
    assert result.reconciliation_required is True


def test_remote_only_lead(tmp_path):
    pub = _receipt_store(tmp_path, [])
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]})
    result = _svc(tmp_path, pub, api).reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    assert result.remote_only == 1


def test_duplicate_remote_detected(tmp_path):
    pub = _receipt_store(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, campaign_id="1")])
    api = FakeApi(leads={"1": [{"id": "lead-a1", "email": "a@example.com"}, {"id": "lead-a2", "email": "a@example.com"}]})
    result = _svc(tmp_path, pub, api).reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    assert result.duplicate_remote == 1
    assert result.reconciliation_required is True


def test_read_only_reconciliation_does_not_mutate_store(tmp_path):
    pub = _receipt_store(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_FAILED, campaign_id="1")])
    before = open(pub.path, "r", encoding="utf-8").read()
    api = FakeApi(leads={"1": []})
    _svc(tmp_path, pub, api).reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    after = open(pub.path, "r", encoding="utf-8").read()
    assert before == after


def test_cross_campaign_isolation(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-2", source_package_directory="", handoff_manifest_path="", campaign_id="2", campaign_name="Camp 2", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-2:c:c@example.com", prospect_id="c", email="c@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-c", campaign_id="2")]))
    store.save()
    api = FakeApi(campaigns={"1": SmartleadCampaignDetails(campaign_id="1", name="Camp 1", status="DRAFTED"), "2": SmartleadCampaignDetails(campaign_id="2", name="Camp 2", status="DRAFTED")}, leads={"1": [{"id": "lead-a", "email": "a@example.com"}], "2": [{"id": "lead-c", "email": "c@example.com"}]})
    svc = _svc(tmp_path, store, api)
    one = svc.reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    two = svc.reconcile_campaign(source_package_id="pkg-2", campaign_id="2")
    assert one.matched == 1 and two.matched == 1


def test_success_then_skipped_canonical_state_preserves_success(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, remote_lead_id="lead-a", campaign_id="1")]))
    store.save()
    svc = _svc(tmp_path, store, FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]}))
    reduced = svc._reduce_latest_local_state(store.list())
    assert reduced[0].status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED
    assert reduced[0].remote_lead_id == "lead-a"


def test_failed_then_succeeded_canonical_state(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_FAILED, campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.save()
    svc = _svc(tmp_path, store, FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]}))
    reduced = svc._reduce_latest_local_state(store.list())
    assert reduced[0].status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED


def test_pending_then_succeeded_canonical_state(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED, campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.save()
    svc = _svc(tmp_path, store, FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]}))
    reduced = svc._reduce_latest_local_state(store.list())
    assert reduced[0].status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED


def test_skipped_without_historical_success_remains_skipped(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, campaign_id="1")]))
    store.save()
    svc = _svc(tmp_path, store, FakeApi(leads={"1": []}))
    reduced = svc._reduce_latest_local_state(store.list())
    assert reduced[0].status == SMARTLEAD_PUBLISH_STATUS_SKIPPED


def test_success_then_skipped_does_not_create_reconciliation_mismatch(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, remote_lead_id="lead-a", campaign_id="1")]))
    store.save()
    result = _svc(tmp_path, store, FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]})).reconcile_campaign(source_package_id="pkg-1", campaign_id="1")
    assert result.matched == 1
    assert result.reconciliation_required is False


def test_different_publication_keys_do_not_collapse_together(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=2, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1"), SmartleadPublishedLead(publication_key="pkg-1:b:b@example.com", prospect_id="b", email="b@example.com", status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, campaign_id="1")]))
    store.save()
    svc = _svc(tmp_path, store, FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]}))
    reduced = svc._reduce_latest_local_state(store.list())
    assert {lead.publication_key for lead in reduced} == {"pkg-1:a:a@example.com", "pkg-1:b:b@example.com"}


def test_restart_preserves_canonical_result(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, remote_lead_id="lead-a", campaign_id="1")]))
    store.save()
    reloaded = SmartleadPublicationStore(path=store.path)
    svc = _svc(tmp_path, reloaded, FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]}))
    reduced = svc._reduce_latest_local_state(reloaded.list())
    assert reduced[0].status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED
    assert reduced[0].remote_lead_id == "lead-a"