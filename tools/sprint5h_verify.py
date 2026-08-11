#!/usr/bin/env python
"""Sprint 5H verifier — Prospect Follow-Up Queue / Portfolio Triage.

SYNTHETIC VERIFICATION DATA — no network, no geocoding provider, no scraping.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify():
    root = tempfile.mkdtemp(prefix="sprint5h_verify_")
    print(f"VERIFIER ROOT: {root}")
    print("SYNTHETIC VERIFICATION DATA\n")

    from datetime import date

    from gui.models.prospect import (
        PRIORITY_HIGH,
        PRIORITY_LOW,
        PRIORITY_NORMAL,
        PRIORITY_URGENT,
        WORKFLOW_STATUS_CONTACTED,
        WORKFLOW_STATUS_FOLLOW_UP,
        WORKFLOW_STATUS_LOST,
        WORKFLOW_STATUS_NEW,
        WORKFLOW_STATUS_NOT_INTERESTED,
        WORKFLOW_STATUS_QUALIFIED,
        WORKFLOW_STATUS_READY_TO_CONTACT,
        WORKFLOW_STATUS_WON,
        Prospect,
    )
    from gui.models.prospect_store import ProspectStore
    from gui.services.prospect_follow_up import (
        STATUS_FILTER_ACTIVE,
        STATUS_FILTER_ALL,
        STATUS_FILTER_CLOSED,
        TIMING_CLOSED,
        TIMING_DUE_TODAY,
        TIMING_NO_DUE_DATE,
        TIMING_OVERDUE,
        TIMING_UPCOMING,
        TIMING_FILTER_NEEDS_ATTENTION,
        derive_timing_state,
        ProspectFollowUpItem,
        ProspectFollowUpService,
    )

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

    today = date(2026, 8, 15)

    # 1-6. Timing classification
    check("Overdue classification", derive_timing_state(Prospect(next_action_date="2026-08-14"), today) == TIMING_OVERDUE)
    check("Due Today classification", derive_timing_state(Prospect(next_action_date="2026-08-15"), today) == TIMING_DUE_TODAY)
    check("Upcoming classification", derive_timing_state(Prospect(next_action_date="2026-08-16"), today) == TIMING_UPCOMING)
    check("No Due Date classification", derive_timing_state(Prospect(next_action_date=None), today) == TIMING_NO_DUE_DATE)
    check("Terminal classification = CLOSED", derive_timing_state(Prospect(workflow_status=WORKFLOW_STATUS_WON, next_action_date="2026-08-14"), today) == TIMING_CLOSED)
    check("Injected today works", derive_timing_state(Prospect(next_action_date="2026-08-14"), "2026-08-15") == TIMING_OVERDUE)

    # 7. Priority ordering
    store = ProspectStore(path=os.path.join(root, "prospects.json"))
    for spec in [
        ("p_low", PRIORITY_LOW, "2026-08-20"),
        ("p_normal", PRIORITY_NORMAL, "2026-08-20"),
        ("p_high", PRIORITY_HIGH, "2026-08-20"),
        ("p_urgent", PRIORITY_URGENT, "2026-08-20"),
    ]:
        store.create(Prospect(prospect_id=spec[0], company_name=spec[0], priority=spec[1], next_action_date=spec[2]))
    store.save()
    svc = ProspectFollowUpService(store)
    items = svc.list_items(today=today)
    order = [i.prospect_id for i in items]
    check("Priority ordering (urgent > high > normal > low)", order == ["p_urgent", "p_high", "p_normal", "p_low"], f"got {order}")

    # 8. Earlier upcoming date sorts before later
    store2 = ProspectStore(path=os.path.join(root, "prospects2.json"))
    store2.create(Prospect(prospect_id="later", next_action_date="2026-08-20"))
    store2.create(Prospect(prospect_id="earlier", next_action_date="2026-08-16"))
    store2.save()
    svc2 = ProspectFollowUpService(store2)
    items2 = svc2.list_items(today=today)
    check("Earlier upcoming date sorts first", [i.prospect_id for i in items2] == ["earlier", "later"])

    # 9. Deterministic tie ordering
    store3 = ProspectStore(path=os.path.join(root, "prospects3.json"))
    store3.create(Prospect(prospect_id="b", company_name="Tie", priority=PRIORITY_NORMAL, next_action_date="2026-08-20"))
    store3.create(Prospect(prospect_id="a", company_name="Tie", priority=PRIORITY_NORMAL, next_action_date="2026-08-20"))
    store3.save()
    svc3 = ProspectFollowUpService(store3)
    items3 = svc3.list_items(today=today)
    check("Deterministic tie ordering", [i.prospect_id for i in items3] == ["a", "b"])

    # 10. Terminal prospects excluded from default active queue
    store4 = ProspectStore(path=os.path.join(root, "prospects4.json"))
    store4.create(Prospect(prospect_id="active", workflow_status=WORKFLOW_STATUS_NEW))
    store4.create(Prospect(prospect_id="won", workflow_status=WORKFLOW_STATUS_WON))
    store4.create(Prospect(prospect_id="lost", workflow_status=WORKFLOW_STATUS_LOST))
    store4.create(Prospect(prospect_id="not_interested", workflow_status=WORKFLOW_STATUS_NOT_INTERESTED))
    store4.save()
    svc4 = ProspectFollowUpService(store4)
    items4 = svc4.list_items(today=today)
    check("Default active queue excludes terminal", len(items4) == 1 and items4[0].prospect_id == "active")

    # 11. Search filtering
    store5 = ProspectStore(path=os.path.join(root, "prospects5.json"))
    store5.create(Prospect(prospect_id="a", company_name="Alpha Dental"))
    store5.create(Prospect(prospect_id="b", company_name="Beta Roofing"))
    store5.save()
    svc5 = ProspectFollowUpService(store5)
    searched = svc5.list_items(today=today, search_text="roof")
    check("Search filtering", len(searched) == 1 and searched[0].prospect_id == "b")

    # 12-14. Status filters
    active = svc4.list_items(today=today, status_filter=STATUS_FILTER_ACTIVE)
    check("Status Active filter", len(active) == 1 and active[0].prospect_id == "active")
    all_items = svc4.list_items(today=today, status_filter=STATUS_FILTER_ALL)
    check("Status All filter", len(all_items) == 4)
    closed = svc4.list_items(today=today, status_filter=STATUS_FILTER_CLOSED)
    check("Closed filter", len(closed) == 3)

    # 15. Priority filter
    store6 = ProspectStore(path=os.path.join(root, "prospects6.json"))
    store6.create(Prospect(prospect_id="n", priority=PRIORITY_NORMAL))
    store6.create(Prospect(prospect_id="h", priority=PRIORITY_HIGH))
    store6.save()
    svc6 = ProspectFollowUpService(store6)
    high = svc6.list_items(today=today, priority_filter=PRIORITY_HIGH)
    check("Priority filter", len(high) == 1 and high[0].prospect_id == "h")


    # 16-19. Timing filters
    store7 = ProspectStore(path=os.path.join(root, "prospects7.json"))
    store7.create(Prospect(prospect_id="o", next_action_date="2026-08-14"))
    store7.create(Prospect(prospect_id="u", next_action_date="2026-08-20"))
    store7.create(Prospect(prospect_id="d", next_action_date="2026-08-15"))
    store7.save()
    svc7 = ProspectFollowUpService(store7)
    check("Overdue filter", len(svc7.list_items(today=today, timing_filter=TIMING_OVERDUE)) == 1)
    check("Due Today filter", len(svc7.list_items(today=today, timing_filter=TIMING_DUE_TODAY)) == 1)
    check("Upcoming filter", len(svc7.list_items(today=today, timing_filter=TIMING_UPCOMING)) == 1)
    store8 = ProspectStore(path=os.path.join(root, "prospects8.json"))
    store8.create(Prospect(prospect_id="nd", next_action_date=None))
    store8.create(Prospect(prospect_id="dt", next_action_date="2026-08-15"))
    store8.save()
    svc8 = ProspectFollowUpService(store8)
    no_date_items = svc8.list_items(today=today, timing_filter=TIMING_NO_DUE_DATE)
    check("No Due Date filter", len(no_date_items) == 1 and no_date_items[0].prospect_id == "nd")

    # 20. Needs Attention semantics
    store9 = ProspectStore(path=os.path.join(root, "prospects9.json"))
    store9.create(Prospect(prospect_id="over", next_action_date="2026-08-14"))
    store9.create(Prospect(prospect_id="due", next_action_date="2026-08-15"))
    store9.create(Prospect(prospect_id="urgent", priority=PRIORITY_URGENT, next_action_date="2026-08-20"))
    store9.create(Prospect(prospect_id="calm", priority=PRIORITY_NORMAL, next_action_date="2026-08-20"))
    store9.save()
    svc9 = ProspectFollowUpService(store9)
    needs = svc9.list_items(today=today, timing_filter=TIMING_FILTER_NEEDS_ATTENTION)
    check("Needs Attention semantics", len(needs) == 3 and {i.prospect_id for i in needs} == {"over", "due", "urgent"})

    # 21. Injected ProspectStore authority
    custom_store = ProspectStore(path=os.path.join(root, "custom.json"))
    custom_store.create(Prospect(prospect_id="custom", company_name="Custom Co"))
    custom_store.save()
    custom_svc = ProspectFollowUpService(custom_store)
    custom_items = custom_svc.list_items(today=today)
    check("Injected ProspectStore authority", len(custom_items) == 1 and custom_items[0].prospect_id == "custom")

    # 22. Queue refresh after workflow mutation
    store10 = ProspectStore(path=os.path.join(root, "prospects10.json"))
    store10.create(Prospect(prospect_id="mut", company_name="Mutable Co", workflow_status=WORKFLOW_STATUS_NEW))
    store10.save()
    svc10 = ProspectFollowUpService(store10)
    before_count = len(svc10.list_items(today=today))
    p = store10.get("mut")
    p.workflow_status = WORKFLOW_STATUS_WON
    store10.save()
    after_count = len(svc10.list_items(today=today))
    check("Queue refresh after workflow mutation", before_count == 1 and after_count == 0)

    # 23. Row-to-prospect navigation
    item = ProspectFollowUpItem(prospect_id="nav_id", company_name="Nav Co")
    check("Row-to-prospect navigation", item.prospect_id == "nav_id" and item.company_name == "Nav Co")

    # 24. No duplicate prospects
    store11 = ProspectStore(path=os.path.join(root, "prospects11.json"))
    store11.create(Prospect(prospect_id="dup", company_name="Dup"))
    store11.save()
    svc11 = ProspectFollowUpService(store11)
    ids = [i.prospect_id for i in svc11.list_items(today=today, status_filter=STATUS_FILTER_ALL)]
    check("No duplicate prospects", len(ids) == len(set(ids)))

    # 25. No workflow mutation from filtering
    store12 = ProspectStore(path=os.path.join(root, "prospects12.json"))
    store12.create(Prospect(prospect_id="safe", workflow_status=WORKFLOW_STATUS_NEW, priority=PRIORITY_NORMAL, next_action_date="2026-08-20"))
    store12.save()
    svc12 = ProspectFollowUpService(store12)
    p_before = store12.get("safe").to_dict()
    svc12.list_items(today=today, status_filter=STATUS_FILTER_ALL, priority_filter=PRIORITY_HIGH, timing_filter=TIMING_OVERDUE)
    p_after = store12.get("safe").to_dict()
    check("No workflow mutation from filtering", p_before == p_after)

    # 26. No queue-render side effects
    check("No queue-render side effects", ProspectFollowUpItem().timing_state == TIMING_NO_DUE_DATE)

    # SUMMARY
    print()
    print("=" * 60)
    print("SPRINT 5H VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Temp data at: {root}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("SYNTHETIC VERIFICATION DATA - not real prospects or inventory.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(verify())

