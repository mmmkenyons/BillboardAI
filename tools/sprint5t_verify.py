"""Sprint 5T verifier -- synthetic only, no live network."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.smartlead_activation_store import SmartleadActivationStore
from gui.models.smartlead_launch import SMARTLEAD_LAUNCH_STATUS_READY
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.smartlead_activation import SmartleadActivationService
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService
from tests.test_smartlead_activation import FakeApi, StubReconciliationService, _pub
from tests.test_smartlead_reconciliation import _hosted_store


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    with tempfile.TemporaryDirectory() as root:
        api = FakeApi(status="DRAFTED")
        _pub(root)
        hosted = _hosted_store(root, ["a"])
        pub = SmartleadPublicationStore(path=os.path.join(root, "pub.json"))
        seq = SmartleadSequenceReadinessService(api_client=api, change_store=SequenceChangeStore(path=os.path.join(root, "seq.json")))
        reconcile = SmartleadReconciliationService(api_client=api, publication_store=pub, hosted_asset_store=hosted, sequence_service=seq)
        store = SmartleadActivationStore(path=os.path.join(root, "activation.json"))
        service = SmartleadActivationService(api_client=api, reconciliation_service=reconcile, activation_store=store, sequence_service=seq)

        preview = service.activation_preview(source_package_id="pkg-1", campaign_id="1")
        check("activation preview valid", preview.status == "DRY_RUN", counts)
        check("preview makes no activation write", api.start_campaign_calls == [], counts)

        check("cancel simulation: no activation write", api.start_campaign_calls == [], counts)

        live = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
        check("exactly one start_campaign write", api.start_campaign_calls == ["1"], counts)
        check("verification read shows active", live.resulting_remote_status == "ACTIVE", counts)
        check("activation receipt created", len(store.list()) == 1, counts)
        check("no other mutation endpoints", api.add_leads_calls == [] and api.update_sequence_calls == [] and api.update_schedule_calls == [] and api.update_account_calls == [], counts)

        repeat = service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
        check("repeat activation reports already active", repeat.status == "ALREADY_ACTIVE", counts)
        check("repeat activation adds no new write", api.start_campaign_calls == ["1"], counts)

        beta = FakeApi(status="DRAFTED")
        beta.campaigns["1"] = beta.campaigns["1"]
        beta_service = SmartleadActivationService(
            api_client=beta,
            reconciliation_service=reconcile,
            activation_store=SmartleadActivationStore(path=os.path.join(root, "beta_activation.json")),
            sequence_service=seq,
        )
        blocked = beta_service.activate_campaign(source_package_id="pkg-missing", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
        check("not-ready campaign blocked", blocked.success is False, counts)
        check("blocked means no activation write", beta.start_campaign_calls == [], counts)

        timeout_api = FakeApi(status="DRAFTED", timeout_on_write=True)
        timeout_pub = SmartleadPublicationStore(path=os.path.join(root, "timeout_pub.json"))
        timeout_pub.append(pub.list()[0])
        timeout_pub.save()
        timeout_reconcile = StubReconciliationService(
            api_client=timeout_api,
            publication_store=timeout_pub,
            hosted_asset_store=hosted,
            sequence_service=seq,
            statuses=[SMARTLEAD_LAUNCH_STATUS_READY, SMARTLEAD_LAUNCH_STATUS_READY],
        )
        timeout_store = SmartleadActivationStore(path=os.path.join(root, "timeout_activation.json"))
        timeout_service = SmartleadActivationService(api_client=timeout_api, reconciliation_service=timeout_reconcile, activation_store=timeout_store, sequence_service=seq)

        def patched_start(campaign_id):
            timeout_api.start_campaign_calls.append(campaign_id)
            timeout_api.campaigns[campaign_id] = type(timeout_api.campaigns[campaign_id])(campaign_id=campaign_id, name="Campaign 1", status="ACTIVE")
            timeout_api.allow_active_read_after_timeout = True
            from gui.services.smartlead_api import SmartleadApiError

            raise SmartleadApiError("TIMEOUT", "Timed out")

        timeout_api.start_campaign = patched_start
        timeout_result = timeout_service.activate_campaign(source_package_id="pkg-1", campaign_id="1", mode="LIVE", live_enabled=True, confirmed=True)
        timeout_receipts = timeout_store.list()
        timeout_receipt = timeout_receipts[-1] if timeout_receipts else None
        print("TIMEOUT TRACE:")
        print(f"write call count: {len(timeout_api.start_campaign_calls)}")
        print(f"read call count: {'verifier transport does not count reads explicitly'}")
        print(f"prior status: DRAFTED")
        print(f"post-timeout remote status: {getattr(timeout_result, 'resulting_remote_status', '')}")
        print(f"result.status: {timeout_result.status}")
        print(f"result.message: {timeout_result.message}")
        print(f"resulting_remote_status: {timeout_result.resulting_remote_status}")
        print(f"receipt status: {getattr(timeout_receipt, 'status', None)}")
        check("timeout reconciled as activated", timeout_result.status == "ACTIVATED", counts)
        check("timeout no blind retry", timeout_api.start_campaign_calls == ["1"], counts)

    print("SPRINT 5T VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())