#!/usr/bin/env python
"""Sprint 5G verifier — Prospect Action Workflow / Sales Follow-Up Foundation.

SYNTHETIC VERIFICATION DATA — no network, no geocoding provider, no scraping.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify():
    root = tempfile.mkdtemp(prefix="sprint5g_verify_")
    print(f"VERIFIER ROOT: {root}")
    print("SYNTHETIC VERIFICATION DATA\n")

    from gui.models.prospect import (
        PRIORITY_HIGH,
        PRIORITY_LOW,
        PRIORITY_NORMAL,
        WORKFLOW_STATUS_CONTACTED,
        WORKFLOW_STATUS_FOLLOW_UP,
        WORKFLOW_STATUS_NEW,
        WORKFLOW_STATUS_READY_TO_CONTACT,
        Prospect,
    )
    from gui.models.prospect_store import ProspectStore
    from gui.services.prospect_workspace import ProspectWorkspaceService

    passed = 0
    failed = 0

    def check(name: str, condition: bool, message: str = "") -> None:
        nonlocal passed, failed
        if condition:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}: {message}")
            failed += 1

    # 1. Default workflow state on new prospect
    p_default = Prospect(company_name="Default Co")
    check(
        "Default workflow state",
        p_default.workflow_status == WORKFLOW_STATUS_NEW
        and p_default.priority == PRIORITY_NORMAL
        and p_default.next_action == ""
        and p_default.next_action_date is None
        and p_default.workflow_notes == "",
    )

    # 2. Workflow fields serialize
    p_full = Prospect(
        company_name="Full Co",
        workflow_status=WORKFLOW_STATUS_READY_TO_CONTACT,
        priority=PRIORITY_HIGH,
        next_action="Call owner",
        next_action_date="2026-08-15",
        workflow_notes="Hot lead",
    )
    d_full = p_full.to_dict()
    check(
        "Workflow fields serialize",
        d_full["workflow_status"] == WORKFLOW_STATUS_READY_TO_CONTACT
        and d_full["priority"] == PRIORITY_HIGH
        and d_full["next_action"] == "Call owner"
        and d_full["next_action_date"] == "2026-08-15"
        and d_full["workflow_notes"] == "Hot lead",
    )

    # 3. Workflow fields deserialize
    restored = Prospect.from_dict(d_full)
    check(
        "Workflow fields deserialize",
        restored.workflow_status == WORKFLOW_STATUS_READY_TO_CONTACT
        and restored.priority == PRIORITY_HIGH
        and restored.next_action_date == "2026-08-15",
    )

    # 4. Pre-5G prospect loads with safe defaults
    legacy = Prospect.from_dict({"company_name": "Legacy Co", "website": "legacy.com"})
    check(
        "Pre-5G data loads with defaults",
        legacy.workflow_status == WORKFLOW_STATUS_NEW
        and legacy.priority == PRIORITY_NORMAL
        and legacy.next_action_date is None,
    )

    # 5. Optional next-action date round-trips
    date_prospect = Prospect(next_action_date="2026-08-20")
    date_restored = Prospect.from_dict(date_prospect.to_dict())
    check("Next-action date round-trip", date_restored.next_action_date == "2026-08-20")

    # 6. Malformed persisted date handled safely
    bad_date = Prospect.from_dict(
        {"company_name": "Bad Date Co", "next_action_date": "not-a-date"}
    )
    check("Malformed date defaults to None", bad_date.next_action_date is None)


    # 7. Workflow update persists through store
    ps = ProspectStore(path=os.path.join(root, "prospects.json"))
    p1 = Prospect(prospect_id="v_alpha", company_name="Alpha Inc")
    ps.collection.prospects.append(p1)
    ps.save()

    svc = ProspectWorkspaceService(store=ps)
    svc.update_workflow(
        "v_alpha",
        status=WORKFLOW_STATUS_CONTACTED,
        priority=PRIORITY_HIGH,
        next_action="Call owner",
        next_action_date="2026-08-15",
        notes="Hot lead",
    )

    svc2 = ProspectWorkspaceService(store=ps)
    svc2.load()
    reloaded = svc2.get_prospect("v_alpha")
    check(
        "Workflow update persists",
        reloaded is not None
        and reloaded.workflow_status == WORKFLOW_STATUS_CONTACTED
        and reloaded.priority == PRIORITY_HIGH
        and reloaded.next_action == "Call owner"
        and reloaded.next_action_date == "2026-08-15"
        and reloaded.workflow_notes == "Hot lead",
    )

    # 8. Partial update preserves unspecified fields
    svc2.update_workflow("v_alpha", next_action="Email owner")
    partial = svc2.get_prospect("v_alpha")
    check(
        "Partial update preserves fields",
        partial.workflow_status == WORKFLOW_STATUS_CONTACTED
        and partial.priority == PRIORITY_HIGH
        and partial.next_action == "Email owner"
        and partial.next_action_date == "2026-08-15",
    )

    # 9. Update does not duplicate prospect
    count = svc2.imported_count()
    svc2.update_workflow("v_alpha", status=WORKFLOW_STATUS_FOLLOW_UP)
    check("No duplicate prospects", svc2.imported_count() == count)

    # 10. Injected store is authoritative
    injected_path = os.path.join(root, "injected.json")
    injected_store = ProspectStore(path=injected_path)
    injected_svc = ProspectWorkspaceService(store=injected_store)
    p_inj = injected_svc.create_prospect(company_name="Injected Co", website="inj.com")
    injected_svc.update_workflow(
        p_inj.prospect_id, status=WORKFLOW_STATUS_READY_TO_CONTACT
    )
    injected_svc2 = ProspectWorkspaceService(store=injected_store)
    injected_svc2.load()
    check(
        "Injected store authoritative",
        injected_svc2.get_prospect(p_inj.prospect_id).workflow_status
        == WORKFLOW_STATUS_READY_TO_CONTACT,
    )

    # 11. Prospect A update does not modify Prospect B
    ps.collection.prospects.append(Prospect(prospect_id="v_beta", company_name="Beta LLC"))
    ps.save()
    svc3 = ProspectWorkspaceService(store=ps)
    svc3.update_workflow(
        "v_alpha",
        status=WORKFLOW_STATUS_FOLLOW_UP,
        priority=PRIORITY_LOW,
        next_action="Call alpha",
        notes="alpha note",
    )
    beta = svc3.get_prospect("v_beta")
    check(
        "Prospect A does not modify Prospect B",
        beta.workflow_status == WORKFLOW_STATUS_NEW
        and beta.priority == PRIORITY_NORMAL
        and beta.next_action == ""
        and beta.workflow_notes == "",
    )

    # 12. Invalid status rejected
    try:
        svc3.update_workflow("v_alpha", status="GARBAGE")
        check("Invalid status rejected", False, "no exception raised")
    except Exception:
        check("Invalid status rejected", True)

    # 13. Invalid priority rejected
    try:
        svc3.update_workflow("v_alpha", priority="GARBAGE")
        check("Invalid priority rejected", False, "no exception raised")
    except Exception:
        check("Invalid priority rejected", True)

    # 14. Invalid date rejected
    try:
        svc3.update_workflow("v_alpha", next_action_date="not-a-date")
        check("Invalid date rejected", False, "no exception raised")
    except Exception:
        check("Invalid date rejected", True)

    # 15. Clear date with None
    svc3.update_workflow("v_alpha", next_action_date=None)
    cleared = svc3.get_prospect("v_alpha")
    check("Date clears with None", cleared.next_action_date is None)

    # 16. Opportunity snapshot survival
    from engine.brand_profile import BrandProfile
    from gui.models.inventory import (
        PERIOD_YEAR,
        STATUS_AVAILABLE,
        Money,
        Location,
        Market,
        Placement,
        Retailer,
    )
    from gui.models.inventory_store import InventoryStore
    from gui.models.opportunity_store import OpportunityStore
    from gui.models.project_store import ProjectStore
    from gui.services.opportunity_service import OpportunityService
    from gui.services.prospect_opportunity_workspace import (
        ProspectOpportunityWorkspaceService,
    )

    psr = ProjectStore(root=os.path.join(root, "projects"))
    proj = psr.create(company_name="Alpha Inc", website="alpha.com")
    proj.metadata["prospect_id"] = "v_alpha"
    proj.brand_profile = BrandProfile(
        categories=["roofing"],
        quality_score=92.0,
        vision_score=70.0,
        phone="555-0000",
        differentiators=["licensed"],
        trust_signals=["BBB A+"],
    ).to_dict()
    psr.save(proj)

    invs = InventoryStore(path=os.path.join(root, "inventory.json"))
    retailer = Retailer(name="Test Retailer")
    market = Market(name="Test Market", market_id="m_test")
    loc = Location(
        location_id="l_1",
        name="Test Store #1",
        retailer_id=retailer.retailer_id,
        market_id=market.market_id,
        store_number="1",
        city="Castle Rock",
        state="CO",
        latitude=39.37,
        longitude=-104.86,
        weekly_traffic=10000,
    )
    pl = Placement(
        placement_id="pl_1",
        location_id=loc.location_id,
        name="Window 1",
        placement_type="window",
        status=STATUS_AVAILABLE,
        price=Money.dollars(5000),
        price_period=PERIOD_YEAR,
    )
    invs.create_inventory(
        retailers=[retailer], markets=[market], locations=[loc], placements=[pl]
    )
    invs.save()

    opp_store = OpportunityStore(path=os.path.join(root, "opportunities.json"))
    opp_svc = OpportunityService(
        prospect_store=ps,
        project_store=psr,
        inventory_store=invs,
        opportunity_store=opp_store,
    )
    snap_svc = ProspectOpportunityWorkspaceService(
        prospect_store=ps,
        project_store=psr,
        inventory_store=invs,
        opportunity_service=opp_svc,
    )
    snap_before = snap_svc.refresh_for_prospect("v_alpha")
    svc3.update_workflow(
        "v_alpha",
        status=WORKFLOW_STATUS_CONTACTED,
        next_action="Send proposal",
    )
    snap_after = snap_svc.snapshot_for_prospect("v_alpha")
    check(
        "Opportunity snapshot survives workflow update",
        snap_after.prospect_id == snap_before.prospect_id
        and snap_after.company_name == snap_before.company_name
        and snap_after.best_match_score == snap_before.best_match_score,
    )

    # 17. No duplicate opportunities after workflow updates
    opps = opp_svc.by_prospect("v_alpha")
    pids = [o.placement_id for o in opps]
    check(
        "No duplicate opportunities after workflow updates",
        len(pids) == len(set(pids)),
    )

    # 18. Reload preserves workflow state alongside snapshot
    ps.load()
    reloaded_alpha = ps.get("v_alpha")
    check(
        "Reload preserves workflow state",
        reloaded_alpha.workflow_status == WORKFLOW_STATUS_CONTACTED
        and reloaded_alpha.next_action == "Send proposal",
    )

    # 19. Controller exposes workflow API
    from gui.controllers.prospect_controller import ProspectController

    controller = ProspectController(service=svc3)
    result = controller.update_workflow(
        "v_alpha",
        status=WORKFLOW_STATUS_FOLLOW_UP,
        priority=PRIORITY_NORMAL,
        next_action="Follow up email",
        next_action_date="2026-09-01",
        notes="controller note",
    )
    check(
        "Controller workflow update persists",
        result is not None
        and result.workflow_status == WORKFLOW_STATUS_FOLLOW_UP
        and result.next_action_date == "2026-09-01",
    )

    # 20. ASCII-safe output values
    def _is_ascii(s):
        try:
            s.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    check(
        "Workflow output ASCII-safe",
        all(
            _is_ascii(v)
            for v in (
                reloaded_alpha.workflow_status,
                reloaded_alpha.priority,
                reloaded_alpha.next_action,
                reloaded_alpha.workflow_notes,
            )
        ),
    )

    # SUMMARY
    print()
    print("=" * 60)
    print("SPRINT 5G VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Temp data at: {root}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("SYNTHETIC VERIFICATION DATA - not real prospects or inventory.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(verify())

    check("Date clears with None", cleared.next_action_date is None)
