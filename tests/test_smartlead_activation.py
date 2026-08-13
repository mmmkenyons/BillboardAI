from __future__ import annotations

import os
from gui.models.smartlead_activation import (
    SMARTLEAD_ACTIVATION_RESULT_ACTIVATED,
    SMARTLEAD_ACTIVATION_RESULT_ALREADY_ACTIVE,
    SMARTLEAD_ACTIVATION_RESULT_BLOCKED,
    SMARTLEAD_ACTIVATION_RESULT_DRY_RUN,
    SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED,
)
from gui.models.smartlead_activation_store import SmartleadActivationStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_launch import (
    SMARTLEAD_LAUNCH_STATUS_BLOCKED,
    SMARTLEAD_LAUNCH_STATUS_NOT_READY,
    SMARTLEAD_LAUNCH_STATUS_PARTIAL,
    SMARTLEAD_LAUNCH_STATUS_READY,
    SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED,
)
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadCampaignDetails,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.smartlead_activation import SmartleadActivationService
from gui.services.smartlead_api import SmartleadApiError
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService

from tests.test_smartlead_reconciliation import _hosted_store


class FakeApi:
    def __init__(self, *, status="DRAFTED", timeout_on_write=False, unreadable_after_timeout=False):
        self.settings = SmartleadConnectionSettings()
        self.campaigns = {"1": SmartleadCampaignDetails(campaign_id="1", name="Campaign 1", status=status)}
        self.leads = {"1": [{"id": "lead-a", "email": "a@example.com"}]}
        self.sequences = {"1": [{"id": "seq1", "steps": [{"subject": "{{bb_subject}}", "content": "{{bb_body}}\n{{bb_mockup_url}}"}]}]}
        self.accounts = {"1": [{"id": "acct-1"}, {"id": "acct-2"}, {"id": "acct-3"}]}
        self.start_campaign_calls = []
        self.add_leads_calls = []
        self.update_sequence_calls = []
        self.update_schedule_calls = []
        self.update_account_calls = []
        self.timeout_on_write = timeout_on_write
        self.unreadable_after_timeout = unreadable_after_timeout
        self.allow_active_read_after_timeout = False

    def get_campaign(self, campaign_id):
        if self.unreadable_after_timeout and self.timeout_on_write and self.start_campaign_calls and not self.allow_active_read_after_timeout:
            raise SmartleadApiError("TIMEOUT", "Remote read failed.")
        return self.campaigns[campaign_id]

    def get_campaign_leads(self, campaign_id):
        return list(self.leads.get(campaign_id, []))

    def get_campaign_sequences(self, campaign_id):
        return list(self.sequences.get(campaign_id, []))

    def get_campaign_email_accounts(self, campaign_id):
        return list(self.accounts.get(campaign_id, []))

    def start_campaign(self, campaign_id):
        self.start_campaign_calls.append(campaign_id)
        if self.timeout_on_write:
            raise SmartleadApiError("TIMEOUT", "Timed out")
        self.campaigns[campaign_id] = SmartleadCampaignDetails(campaign_id=campaign_id, name=self.campaigns[campaign_id].name, status="ACTIVE")
        return {"success": True}


def _pub(tmp_path):
    store = SmartleadPublicationStore(path=os.path.join(str(tmp_path), "pub.json"))
    store.append(
        SmartleadPublicationReceipt.create(
            source_package_id="pkg-1",
            source_package_directory="",
            handoff_manifest_path="",
            campaign_id="1",
            campaign_name="Campaign 1",
            target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
            mode=SMARTLEAD_PUBLISH_MODE_LIVE,
            total_candidates=1,
            lead_results=[SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1")],
        )
    )
    store.save()
    return store


class StubReconciliationService(SmartleadReconciliationService):
    def __init__(self, *args, statuses=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._statuses = list(statuses or [])

    def evaluate_launch_readiness(self, *, source_package_id: str, campaign_id: str):
        result = super().evaluate_launch_readiness(source_package_id=source_package_id, campaign_id=campaign_id)
        if self._statuses:
            forced = self._statuses.pop(0)
            return type(result)(**{**result.to_dict(), "status": forced})
        return result


def _service(tmp_path, api, statuses=None):
    pub = _pub(tmp_path)
    hosted = _hosted_store(tmp_path, ["a"])
    seq = SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=os.path.join(str(tmp_path), "seq.json")))
    reconcile = StubReconciliationService(api_client=api, publication_store=pub, hosted_asset_store=hosted, sequence_service=seq, statuses=statuses)
    store = SmartleadActivationStore(path=os.path.join(str(tmp_path), "activation.json"))
    return SmartleadActivationService(api_client=api, reconciliation_service=reconcile, activation_store=store, sequence_service=seq), store, api


def test_dry_run_default(tmp_path):
    service, store, api = _service(tmp_path, FakeApi())
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1")
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_DRY_RUN
    assert result.dry_run is True
    assert api.start_campaign_calls == []
    assert store.list() == []


def test_not_ready_blocked(tmp_path):
    for status in [SMARTLEAD_LAUNCH_STATUS_NOT_READY, SMARTLEAD_LAUNCH_STATUS_PARTIAL, SMARTLEAD_LAUNCH_STATUS_BLOCKED, SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED]:
        child = tmp_path / status
        child.mkdir()
        service, _store, api = _service(child, FakeApi(), statuses=[status])
        result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
        assert result.status == SMARTLEAD_ACTIVATION_RESULT_BLOCKED
        assert api.start_campaign_calls == []


def test_ready_allows_activation_attempt_and_persists_receipt(tmp_path):
    service, store, api = _service(tmp_path, FakeApi(), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_ACTIVATED
    assert api.start_campaign_calls == ["1"]
    assert result.resulting_remote_status == "ACTIVE"
    assert len(store.list()) == 1
    assert result.intended_request == {"intent": "START_CAMPAIGN", "campaign_id": "1"}


def test_fresh_readiness_rechecked_before_write(tmp_path):
    service, _store, api = _service(tmp_path, FakeApi(), statuses=[SMARTLEAD_LAUNCH_STATUS_READY, SMARTLEAD_LAUNCH_STATUS_BLOCKED])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_BLOCKED
    assert api.start_campaign_calls == []


def test_explicit_confirmation_required(tmp_path):
    service, _store, api = _service(tmp_path, FakeApi(), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=False)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_BLOCKED
    assert api.start_campaign_calls == []


def test_live_enable_required(tmp_path):
    service, _store, api = _service(tmp_path, FakeApi(), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=False, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_BLOCKED
    assert api.start_campaign_calls == []


def test_already_active_does_not_write_again(tmp_path):
    service, store, api = _service(tmp_path, FakeApi(status="ACTIVE"), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_ALREADY_ACTIVE
    assert api.start_campaign_calls == []
    assert len(store.list()) == 1


def test_paused_behavior_is_resume(tmp_path):
    service, _store, api = _service(tmp_path, FakeApi(status="PAUSED"), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_ACTIVATED
    assert api.start_campaign_calls == ["1"]


def test_unsupported_remote_status_blocked(tmp_path):
    service, store, api = _service(tmp_path, FakeApi(status="STOPPED"), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_BLOCKED
    assert api.start_campaign_calls == []
    assert len(store.list()) == 1


def test_timeout_remote_active_reconciles_as_success(tmp_path):
    api = FakeApi(timeout_on_write=True)
    service, store, api = _service(tmp_path, api, statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    def patched_start(campaign_id):
        api.start_campaign_calls.append(campaign_id)
        api.campaigns[campaign_id] = SmartleadCampaignDetails(campaign_id=campaign_id, name="Campaign 1", status="ACTIVE")
        api.allow_active_read_after_timeout = True
        raise SmartleadApiError("TIMEOUT", "Timed out")
    api.start_campaign = patched_start
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_ACTIVATED
    assert api.start_campaign_calls == ["1"]
    assert len(store.list()) == 1


def test_timeout_remote_unchanged_requires_reconciliation(tmp_path):
    service, store, api = _service(tmp_path, FakeApi(timeout_on_write=True), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED
    assert api.start_campaign_calls == ["1"]
    assert len(store.list()) == 1


def test_timeout_remote_unreadable_requires_reconciliation(tmp_path):
    service, store, api = _service(tmp_path, FakeApi(timeout_on_write=True, unreadable_after_timeout=True), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.status == SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED
    assert api.start_campaign_calls == ["1"]
    assert len(store.list()) == 1


def test_cross_campaign_isolation(tmp_path):
    service, store, api = _service(tmp_path, FakeApi(), statuses=[SMARTLEAD_LAUNCH_STATUS_READY])
    result = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
    assert result.campaign_id == "1"
    assert all(receipt.campaign_id == "1" for receipt in store.list())
    assert api.add_leads_calls == []
    assert api.update_sequence_calls == []
    assert api.update_schedule_calls == []
    assert api.update_account_calls == []