from __future__ import annotations

import os

from gui.models.smartlead_launch import SMARTLEAD_LAUNCH_STATUS_READY
from gui.models.smartlead_pilot import (
    SMARTLEAD_PILOT_HEALTH_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_PAUSE_RESULT_ALREADY_PAUSED,
    SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED,
    SMARTLEAD_PILOT_PAUSE_RESULT_PAUSED,
    SMARTLEAD_PILOT_STATUS_ACTIVE,
    SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED,
    SMARTLEAD_PILOT_STATUS_BLOCKED,
    SMARTLEAD_PILOT_STATUS_COMPLETED,
    SMARTLEAD_PILOT_STATUS_PAUSED,
    SMARTLEAD_PILOT_STATUS_READY,
)
from gui.models.smartlead_pilot_store import SmartleadPilotStore
from gui.models.smartlead_publication import SMARTLEAD_PUBLISH_STATUS_FAILED, SMARTLEAD_PUBLISH_STATUS_SUCCEEDED
from gui.models.smartlead_pilot import SmartleadPilotRecipient
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.campaign_review import CampaignReviewService
from gui.services.smartlead_activation import SmartleadActivationService
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_pilot import DEFAULT_PILOT_SIZE, MAX_PILOT_SIZE, SmartleadPilotService
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService

from tests.test_smartlead_activation import FakeApi as ActivationApi
from tests.test_smartlead_activation import StubReconciliationService, _pub
from tests.test_smartlead_handoff import _build_package, _job, _project_with_concept, _prospect, _runtime
from tests.test_smartlead_reconciliation import FakeApi as ReconciliationApi
from tests.test_smartlead_reconciliation import _hosted_store


class PilotApi(ActivationApi):
    def __init__(self, *, status="DRAFTED", timeout_on_pause=False, unreadable_after_pause_timeout=False):
        super().__init__(status=status)
        self.pause_campaign_calls = []
        self.timeout_on_pause = timeout_on_pause
        self.unreadable_after_pause_timeout = unreadable_after_pause_timeout
        self.analytics = {"1": {"sent": 2, "replied": 1, "bounced": 0, "opened": 2, "clicked": 0}}
        self.lead_stats = {
            "1": [
                {"lead_id": "lead-a", "email": "a@example.com", "sent": True, "replied": True, "opened": True},
            ]
        }

    def pause_campaign(self, campaign_id):
        self.pause_campaign_calls.append(campaign_id)
        if self.timeout_on_pause:
            from gui.services.smartlead_api import SmartleadApiError

            raise SmartleadApiError("TIMEOUT", "Timed out")
        self.campaigns[campaign_id] = type(self.campaigns[campaign_id])(
            campaign_id=campaign_id,
            name=self.campaigns[campaign_id].name,
            status="PAUSED",
        )
        return {"success": True}

    def get_campaign(self, campaign_id):
        if self.unreadable_after_pause_timeout and self.pause_campaign_calls:
            from gui.services.smartlead_api import SmartleadApiError

            raise SmartleadApiError("TIMEOUT", "Unreadable")
        return super().get_campaign(campaign_id)

    def get_campaign_analytics(self, campaign_id):
        return dict(self.analytics.get(campaign_id, {}))

    def get_campaign_lead_statistics(self, campaign_id):
        return list(self.lead_stats.get(campaign_id, []))


def _pilot_runtime(tmp_path):
    prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(tmp_path)
    return prospect_store, job_store, project_store, review_service, handoff_service


def _prepare_ready_pilot(tmp_path, monkeypatch, *, api=None, selected_ids=None):
    prospect_store, job_store, project_store, review_service, handoff_service = _pilot_runtime(tmp_path)
    prospect_a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
    prospect_b = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="b@example.com")
    for prospect in [prospect_a, prospect_b]:
        project, concept = _project_with_concept(project_store, prospect, f"{prospect.prospect_id}.png")
        _job(job_store, id=f"job-{prospect.prospect_id}", prospect_id=prospect.prospect_id, project_id=project.id, result_path=concept.image_path)
    package_result = _build_package(review_service, ["a", "b"], str(tmp_path / "packages"))
    handoff_result = handoff_service.prepare_handoff(package_result.package_directory)
    publication_store = _pub(tmp_path)
    hosted = _hosted_store(tmp_path, ["a", "b"])
    active_api = api or PilotApi()
    seq = SmartleadSequenceReadinessService(api_client=active_api, change_store=SequenceChangeStore(path=os.path.join(str(tmp_path), "seq.json")))
    reconcile = SmartleadReconciliationService(api_client=active_api, publication_store=publication_store, hosted_asset_store=hosted, sequence_service=seq)
    activation = SmartleadActivationService(api_client=active_api, reconciliation_service=reconcile, sequence_service=seq)
    pilot_store = SmartleadPilotStore(path=os.path.join(str(tmp_path), "pilot_runs.json"))
    service = SmartleadPilotService(
        pilot_store=pilot_store,
        review_service=review_service,
        handoff_service=handoff_service,
        reconciliation_service=reconcile,
        activation_service=activation,
        api_client=active_api,
        sequence_service=seq,
    )
    selected = selected_ids or ["a"]
    pilot = service.create_pilot(
        campaign_id="1",
        campaign_name="Campaign 1",
        source_package_id="pkg-1",
        source_handoff_path=handoff_result.handoff_directory,
        selected_prospect_ids=selected,
        selected_emails=[f"{item}@example.com" for item in selected],
    )
    monkeypatch.delenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", raising=False)
    return service, active_api, pilot_store, pilot


def test_default_pilot_size_limit(tmp_path, monkeypatch):
    service, _api, _store, _pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    assert service.default_pilot_size == DEFAULT_PILOT_SIZE
    assert service.max_pilot_size == MAX_PILOT_SIZE


def test_more_than_max_recipients_blocked(tmp_path, monkeypatch):
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, selected_ids=[str(i) for i in range(11)])
    result = service.preflight_pilot(pilot.pilot_id)
    assert result.success is False
    assert result.status == SMARTLEAD_PILOT_STATUS_BLOCKED


def test_explicitly_selected_cohort_only(tmp_path, monkeypatch):
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, selected_ids=["a"])
    assert [item.prospect_id for item in pilot.recipients] == ["a"]


def test_unapproved_recipient_blocked(tmp_path, monkeypatch):
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    run = service.get_pilot(pilot.pilot_id)
    updated = run.definition.__class__(
        **{
            **run.definition.to_dict(),
            "recipients": (SmartleadPilotRecipient(prospect_id="missing", email="missing@example.com"),),
        }
    )
    service._pilot_store.upsert(run.__class__(definition=updated, snapshot=run.snapshot, events=run.events))
    result = service.preflight_pilot(pilot.pilot_id)
    assert result.success is False


def test_unpublished_recipient_blocked(tmp_path, monkeypatch):
    api = PilotApi()
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, api=api)
    service._reconciliation_service._publication_store._receipts[0] = service._reconciliation_service._publication_store._receipts[0].__class__.create(
        source_package_id="pkg-1",
        source_package_directory="",
        handoff_manifest_path="",
        campaign_id="1",
        campaign_name="Camp 1",
        target_mode="EXISTING_CAMPAIGN",
        mode="LIVE",
        total_candidates=1,
        lead_results=[service._reconciliation_service._publication_store._receipts[0].lead_results[0].__class__(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_FAILED, campaign_id="1")],
    )
    result = service.preflight_pilot(pilot.pilot_id)
    assert result.success is False


def test_fully_ready_pilot_passes(tmp_path, monkeypatch):
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    result = service.preflight_pilot(pilot.pilot_id)
    assert result.success is True
    assert result.status == SMARTLEAD_PILOT_STATUS_READY


def test_activation_contract_verification_false_blocks_live_pilot(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    result = service.activate_pilot(pilot.pilot_id, confirmed=True)
    assert result.success is False
    assert api.start_campaign_calls == []


def test_dry_run_allowed_without_provider_confirmation(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    result = service.dry_run_activation(pilot.pilot_id)
    assert result.dry_run is True
    assert api.start_campaign_calls == []


def test_pilot_delegates_activation_to_canonical_service(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    monkeypatch.setenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", "true")
    result = service.activate_pilot(pilot.pilot_id, confirmed=True)
    assert result.activation_delegated is True
    assert api.start_campaign_calls == ["1"]


def test_live_activation_requires_explicit_confirmation(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    monkeypatch.setenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", "true")
    result = service.activate_pilot(pilot.pilot_id, confirmed=False)
    assert result.success is False
    assert api.start_campaign_calls == []


def test_pause_only_available_for_active_pilot(tmp_path, monkeypatch):
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    result = service.pause_pilot(pilot.pilot_id, confirmed=True)
    assert result.status == SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED


def test_exactly_one_pause_write(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    monkeypatch.setenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", "true")
    service.activate_pilot(pilot.pilot_id, confirmed=True)
    result = service.pause_pilot(pilot.pilot_id, confirmed=True)
    assert result.status == SMARTLEAD_PILOT_PAUSE_RESULT_PAUSED
    assert api.pause_campaign_calls == ["1"]


def test_already_paused_no_write(tmp_path, monkeypatch):
    api = PilotApi(status="PAUSED")
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, api=api)
    run = service.get_pilot(pilot.pilot_id)
    service._pilot_store.upsert(
        run.__class__(
            definition=run.definition.__class__(
                **{
                    **run.definition.to_dict(),
                    "recipients": tuple(run.definition.recipients),
                    "status": SMARTLEAD_PILOT_STATUS_ACTIVE,
                }
            ),
            snapshot=run.snapshot,
            events=run.events,
        )
    )
    result = service.pause_pilot(pilot.pilot_id, confirmed=True)
    assert result.status == SMARTLEAD_PILOT_PAUSE_RESULT_ALREADY_PAUSED
    assert api.pause_campaign_calls == []


def test_pause_timeout_active_attention_required(tmp_path, monkeypatch):
    api = PilotApi(timeout_on_pause=True)
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, api=api)
    monkeypatch.setenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", "true")
    service.activate_pilot(pilot.pilot_id, confirmed=True)
    result = service.pause_pilot(pilot.pilot_id, confirmed=True)
    assert result.status == SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED
    assert api.pause_campaign_calls == ["1"]


def test_pause_timeout_unreadable_attention_required(tmp_path, monkeypatch):
    api = PilotApi(timeout_on_pause=True, unreadable_after_pause_timeout=True)
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, api=api)
    monkeypatch.setenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", "true")
    service.activate_pilot(pilot.pilot_id, confirmed=True)
    result = service.pause_pilot(pilot.pilot_id, confirmed=True)
    assert result.status == SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED


def test_refresh_is_read_only(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    before_start = list(api.start_campaign_calls)
    before_pause = list(api.pause_campaign_calls)
    run = service.refresh_pilot_status(pilot.pilot_id)
    assert run.snapshot is not None
    assert api.start_campaign_calls == before_start
    assert api.pause_campaign_calls == before_pause


def test_monitoring_surfaces_reply_and_bounce(tmp_path, monkeypatch):
    api = PilotApi()
    api.lead_stats["1"] = [{"lead_id": "lead-a", "email": "a@example.com", "sent": True, "replied": True, "bounced": True}]
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, api=api)
    run = service.refresh_pilot_status(pilot.pilot_id)
    assert run.snapshot.pilot_metrics.replied == 1
    assert run.snapshot.pilot_metrics.bounced == 1


def test_missing_remote_lead_attention_state(tmp_path, monkeypatch):
    api = PilotApi()
    api.lead_stats["1"] = []
    service, _api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch, api=api)
    run = service.refresh_pilot_status(pilot.pilot_id)
    assert run.snapshot.health == SMARTLEAD_PILOT_HEALTH_ATTENTION_REQUIRED


def test_restart_persists_and_no_auto_resume(tmp_path, monkeypatch):
    service, api, store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    monkeypatch.setenv("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", "true")
    service.activate_pilot(pilot.pilot_id, confirmed=True)
    reloaded = SmartleadPilotStore(path=store.path)
    run = reloaded.get(pilot.pilot_id)
    assert run is not None
    assert run.definition.status in {SMARTLEAD_PILOT_STATUS_ACTIVE, SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED}
    assert api.pause_campaign_calls == []


def test_cross_campaign_isolation(tmp_path, monkeypatch):
    service, api, store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    beta_pilot = service.create_pilot(
        campaign_id="2",
        campaign_name="Campaign 2",
        source_package_id="pkg-2",
        source_handoff_path=pilot.source_handoff_path,
        selected_prospect_ids=["a"],
        selected_emails=["a@example.com"],
    )
    assert store.get(pilot.pilot_id).definition.campaign_id == "1"
    assert store.get(beta_pilot.pilot_id).definition.campaign_id == "2"


def test_mark_review_complete_is_local_only(tmp_path, monkeypatch):
    service, api, _store, pilot = _prepare_ready_pilot(tmp_path, monkeypatch)
    run = service.mark_review_complete(pilot.pilot_id)
    assert run.definition.status == SMARTLEAD_PILOT_STATUS_COMPLETED
    assert api.start_campaign_calls == []
    assert api.pause_campaign_calls == []