"""Sprint 5U verifier -- synthetic only, no live network."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.smartlead_pilot_store import SmartleadPilotStore
from gui.models.smartlead_publication import (
    SMARTLEAD_PUBLISH_MODE_LIVE,
    SMARTLEAD_PUBLISH_STATUS_SUCCEEDED,
    SMARTLEAD_TARGET_MODE_EXISTING,
    SmartleadPublishedLead,
    SmartleadPublicationReceipt,
)
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.smartlead_activation import SmartleadActivationService
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_pilot import SmartleadPilotService
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService

from tests.test_smartlead_handoff import _build_package, _job, _project_with_concept, _prospect, _runtime
from tests.test_smartlead_reconciliation import _hosted_store
from tests.test_smartlead_pilot import PilotApi


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    with tempfile.TemporaryDirectory() as root:
        prospect_store, job_store, project_store, review_service, handoff_service, _ = _runtime(root)
        for prospect_id, company, email in [
            ("a", "Alpha", "a@example.com"),
            ("b", "Bravo", "b@example.com"),
            ("c", "Charlie", "c@example.com"),
            ("d", "Delta", "d@example.com"),
            ("e", "Echo", "e@example.com"),
        ]:
            prospect = _prospect(prospect_store, prospect_id=prospect_id, company_name=company, email=email)
            project, concept = _project_with_concept(project_store, prospect, f"{prospect_id}.png")
            _job(job_store, id=f"job-{prospect_id}", prospect_id=prospect_id, project_id=project.id, result_path=concept.image_path)
        package_result = _build_package(review_service, ["a", "b", "c", "d", "e"], os.path.join(root, "packages"))
        handoff_result = handoff_service.prepare_handoff(package_result.package_directory)

        api = PilotApi(status="DRAFTED")
        api.leads["1"] = [
            {"id": "lead-a", "email": "a@example.com"},
            {"id": "lead-b", "email": "b@example.com"},
            {"id": "lead-c", "email": "c@example.com"},
            {"id": "lead-d", "email": "d@example.com"},
            {"id": "lead-e", "email": "e@example.com"},
        ]
        api.lead_stats["1"] = [
            {"lead_id": "lead-a", "email": "a@example.com", "sent": True, "replied": True, "opened": True},
            {"lead_id": "lead-b", "email": "b@example.com", "sent": True, "opened": True},
            {"lead_id": "lead-c", "email": "c@example.com", "sent": False},
            {"lead_id": "lead-d", "email": "d@example.com", "sent": False},
            {"lead_id": "lead-e", "email": "e@example.com", "sent": False},
        ]
        api.analytics["1"] = {"sent": 2, "replied": 1, "bounced": 0}
        publication_store = SmartleadPublicationStore(path=os.path.join(root, "pub.json"))
        publication_store.append(
            SmartleadPublicationReceipt.create(
                source_package_id="pkg-1",
                source_package_directory=package_result.package_directory,
                handoff_manifest_path=os.path.join(handoff_result.handoff_directory, "smartlead_handoff_manifest.json"),
                campaign_id="1",
                campaign_name="Campaign Alpha",
                target_mode=SMARTLEAD_TARGET_MODE_EXISTING,
                mode=SMARTLEAD_PUBLISH_MODE_LIVE,
                total_candidates=5,
                lead_results=[
                    SmartleadPublishedLead(publication_key="pkg-1:a:a@example.com", prospect_id="a", email="a@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-a", campaign_id="1"),
                    SmartleadPublishedLead(publication_key="pkg-1:b:b@example.com", prospect_id="b", email="b@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-b", campaign_id="1"),
                    SmartleadPublishedLead(publication_key="pkg-1:c:c@example.com", prospect_id="c", email="c@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-c", campaign_id="1"),
                    SmartleadPublishedLead(publication_key="pkg-1:d:d@example.com", prospect_id="d", email="d@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-d", campaign_id="1"),
                    SmartleadPublishedLead(publication_key="pkg-1:e:e@example.com", prospect_id="e", email="e@example.com", status=SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, remote_lead_id="lead-e", campaign_id="1"),
                ],
            )
        )
        publication_store.save()
        hosted = _hosted_store(root, ["a", "b", "c", "d", "e"])
        seq = SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=os.path.join(root, "seq.json")))
        reconcile = SmartleadReconciliationService(api_client=api, publication_store=publication_store, hosted_asset_store=hosted, sequence_service=seq)
        activation = SmartleadActivationService(api_client=api, reconciliation_service=reconcile, sequence_service=seq)
        pilot_store = SmartleadPilotStore(path=os.path.join(root, "pilot.json"))
        pilot_service = SmartleadPilotService(
            pilot_store=pilot_store,
            review_service=review_service,
            handoff_service=SmartleadHandoffService(),
            reconciliation_service=reconcile,
            activation_service=activation,
            api_client=api,
            sequence_service=seq,
        )

        pilot = pilot_service.create_pilot(
            campaign_id="1",
            campaign_name="Campaign Alpha",
            source_package_id="pkg-1",
            source_handoff_path=handoff_result.handoff_directory,
            selected_prospect_ids=["a", "b", "c", "d", "e"],
            selected_emails=["a@example.com", "b@example.com", "c@example.com", "d@example.com", "e@example.com"],
        )

        blocked = pilot_service.activate_pilot(pilot.pilot_id, confirmed=True)
        check("live activation blocked before provider confirmation", blocked.success is False, counts)
        check("blocked means no activation write", api.start_campaign_calls == [], counts)

        preview = pilot_service.dry_run_activation(pilot.pilot_id)
        check("dry run valid", preview.dry_run is True and preview.success is True, counts)
        check("dry run makes no write", api.start_campaign_calls == [], counts)

        os.environ["SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED"] = "true"
        live = pilot_service.activate_pilot(pilot.pilot_id, confirmed=True)
        check("exactly one activation write through 5T service", api.start_campaign_calls == ["1"], counts)
        check("ACTIVE verified", live.success is True and live.pilot is not None and live.pilot.status == "ACTIVE", counts)

        refreshed = pilot_service.refresh_pilot_status(pilot.pilot_id)
        check("campaign status ACTIVE", refreshed.snapshot is not None and refreshed.snapshot.remote_campaign_status == "ACTIVE", counts)
        check("pilot metrics sent=2 replied=1 bounced=0", refreshed.snapshot is not None and refreshed.snapshot.pilot_metrics.sent == 2 and refreshed.snapshot.pilot_metrics.replied == 1 and refreshed.snapshot.pilot_metrics.bounced == 0, counts)

        before_writes = (list(api.start_campaign_calls), list(api.pause_campaign_calls))
        again = pilot_service.refresh_pilot_status(pilot.pilot_id)
        check("refresh no writes", before_writes == (list(api.start_campaign_calls), list(api.pause_campaign_calls)), counts)

        paused = pilot_service.pause_pilot(pilot.pilot_id, confirmed=True)
        check("exactly one pause write", api.pause_campaign_calls == ["1"], counts)
        check("remote PAUSED verified", paused.success is True and paused.pilot is not None and paused.pilot.status == "PAUSED", counts)

        after_pause = pilot_service.refresh_pilot_status(pilot.pilot_id)
        check("refresh after pause shows PAUSED", after_pause.definition.status == "PAUSED", counts)
        check("no automatic resume", api.start_campaign_calls == ["1"], counts)

        reloaded = SmartleadPilotStore(path=pilot_store.path)
        reloaded_run = reloaded.get(pilot.pilot_id)
        check("restart pilot state persists", reloaded_run is not None and reloaded_run.definition.status == "PAUSED", counts)
        check("restart makes no write", api.start_campaign_calls == ["1"] and api.pause_campaign_calls == ["1"], counts)

        beta_runs = reloaded.get_by_campaign("beta")
        check("Campaign Beta untouched", beta_runs == [], counts)
        check("no STOP call", not hasattr(api, "stop_campaign"), counts)
        check("no lead publish during pilot flow", api.add_leads_calls == [], counts)
        check("no sequence modification", api.update_sequence_calls == [], counts)
        check("no sender modification", api.update_account_calls == [], counts)
        check("no schedule modification", api.update_schedule_calls == [], counts)

        os.environ.pop("SMARTLEAD_ACTIVATION_CONTRACT_VERIFIED", None)

    print("SPRINT 5U VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())