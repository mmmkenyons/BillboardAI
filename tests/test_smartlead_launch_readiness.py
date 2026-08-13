from __future__ import annotations

import os

from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_launch import (
    SMARTLEAD_LAUNCH_STATUS_BLOCKED,
    SMARTLEAD_LAUNCH_STATUS_READY,
    SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED,
)
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

from tests.test_smartlead_reconciliation import FakeApi, _hosted_store


def _pub(tmp_path, leads):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(
        SmartleadPublicationReceipt.create(
            source_package_id="pkg-1",
            source_package_directory="",
            handoff_manifest_path="",
            campaign_id="1",
            campaign_name="Camp 1",
            target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
            mode=SMARTLEAD_PUBLISH_MODE_LIVE,
            total_candidates=len(leads),
            lead_results=leads,
        )
    )
    store.save()
    return store


def _svc(tmp_path, pub, api, hosted=None):
    seq = SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=os.path.join(str(tmp_path), "seq.json")))
    return SmartleadReconciliationService(api_client=api, publication_store=pub, hosted_asset_store=hosted or HostedAssetStore(path=os.path.join(str(tmp_path), "hosted.json")), sequence_service=seq)


def test_all_requirements_satisfied_ready(tmp_path):
    pub = _pub(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")])
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]})
    hosted = _hosted_store(tmp_path, ["a"])
    result = _svc(tmp_path, pub, api, hosted).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.status == SMARTLEAD_LAUNCH_STATUS_READY


def test_missing_hosted_asset_blocks(tmp_path):
    pub = _pub(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")])
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]})
    result = _svc(tmp_path, pub, api).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.status == SMARTLEAD_LAUNCH_STATUS_BLOCKED
    assert result.missing_asset_count == 1


def test_sequence_not_ready_blocks(tmp_path):
    pub = _pub(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")])
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]}, sequences={"1": []})
    hosted = _hosted_store(tmp_path, ["a"])
    result = _svc(tmp_path, pub, api, hosted).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.status in {SMARTLEAD_LAUNCH_STATUS_BLOCKED, SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED, "NOT_READY"}
    assert result.sequence_ready is False


def test_remote_campaign_missing_blocks(tmp_path):
    pub = _pub(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")])
    api = FakeApi(campaigns={}, leads={})
    hosted = _hosted_store(tmp_path, ["a"])
    result = _svc(tmp_path, pub, api, hosted).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.status in {SMARTLEAD_LAUNCH_STATUS_BLOCKED, SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED}
    assert result.remote_campaign_found is False


def test_reconciliation_mismatch_blocks(tmp_path):
    pub = _pub(tmp_path, [SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")])
    api = FakeApi(leads={"1": []})
    hosted = _hosted_store(tmp_path, ["a"])
    result = _svc(tmp_path, pub, api, hosted).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.status == SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED


def test_failed_and_pending_not_ready(tmp_path):
    pub = _pub(tmp_path, [
        SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1"),
        SmartleadPublishedLead(publication_key="pkg-1:b:b@example.com", prospect_id="b", email="b@example.com", status=SMARTLEAD_PUBLISH_STATUS_FAILED, campaign_id="1"),
        SmartleadPublishedLead(publication_key="pkg-1:c:c@example.com", prospect_id="c", email="c@example.com", status=SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED, campaign_id="1"),
    ])
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]})
    hosted = _hosted_store(tmp_path, ["a"])
    result = _svc(tmp_path, pub, api, hosted).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.status in {SMARTLEAD_LAUNCH_STATUS_BLOCKED, SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED, "NOT_READY"}
    assert result.failed_count == 1
    assert result.pending_count == 1


def test_success_then_skipped_counts_as_published(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")]))
    store.append(SmartleadPublicationReceipt.create(source_package_id="pkg-1", source_package_directory="", handoff_manifest_path="", campaign_id="1", campaign_name="Camp 1", target_mode=SMARTLEAD_TARGET_MODE_EXISTING, mode=SMARTLEAD_PUBLISH_MODE_LIVE, total_candidates=1, lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SKIPPED, remote_lead_id="lead-a", campaign_id="1")]))
    store.save()
    api = FakeApi(leads={"1": [{"id": "lead-a", "email": "a@example.com"}]})
    hosted = _hosted_store(tmp_path, ["a"])
    result = _svc(tmp_path, store, api, hosted).evaluate_launch_readiness(source_package_id="pkg-1", campaign_id="1")
    assert result.published_count == 1
    assert result.pending_count == 0
    assert result.status == SMARTLEAD_LAUNCH_STATUS_READY