"""Sprint 5D Store Recommendation end-to-end verification (Qt-free).

Uses Sprint 5C verification data (Jim Woods Roofing + King Soopers inventory)
to prove end-to-end store recommendations.

Run::
    python tools/sprint5d_verify.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.models.inventory_store import InventoryStore
from gui.models.opportunity_store import OpportunityStore
from gui.models.project_store import ProjectStore
from gui.models.prospect_store import ProspectStore
from gui.services.opportunity_service import OpportunityService
from gui.services.store_recommendation import (
    RANK_BEST_MATCH,
    RANK_NEAREST,
    StoreRecommendationService,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_DIR = os.path.join(ROOT, "output", "opportunities", "sprint5c_verify")
PROSPECTS_PATH = os.path.join(VERIFY_DIR, "prospects.json")
INVENTORY_PATH = os.path.join(VERIFY_DIR, "inventory.json")
PROJECTS_ROOT = os.path.join(VERIFY_DIR, "projects")
OPPORTUNITIES_PATH = os.path.join(VERIFY_DIR, "opportunities.json")

_failures: list = []


def step(n, label, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{n}] {label}: {status}" + (f" ({detail})" if detail else ""))
    if not ok:
        _failures.append((n, label, detail))


def main() -> int:
    print("=" * 70)
    print(" Sprint 5D Store Recommendation Verification")
    print(f" Data: {VERIFY_DIR}")
    print("=" * 70)

    ps = ProspectStore(path=PROSPECTS_PATH)
    try:
        ps.load()
    except FileNotFoundError:
        print("ERROR: Sprint 5C data not found. Run sprint5c_verify.py first.")
        return 1

    pstore = ProjectStore(root=PROJECTS_ROOT)
    inv = InventoryStore(path=INVENTORY_PATH)
    inv.load()
    oss = OpportunityStore(path=OPPORTUNITIES_PATH)
    try:
        oss.load()
    except FileNotFoundError:
        oss.collection.opportunities = []

    opp_svc = OpportunityService(
        prospect_store=ps, project_store=pstore,
        inventory_store=inv, opportunity_store=oss,
    )
    svc = StoreRecommendationService(
        opportunity_service=opp_svc, inventory_store=inv,
    )

    prospect = ps.get("prospect_jimwoods")
    if prospect is None:
        print("ERROR: prospect_jimwoods not found")
        return 1

    print(f"\nProspect: {prospect.company_name}")

    # 1. Researched Project
    print("\n[1] Researched Project:")
    project = opp_svc.locate_project(prospect.prospect_id)
    step(1, "Resolved via metadata", project is not None)

    # 2. Generate Opportunities
    print("\n[2] Generate Opportunities:")
    opp_svc.recommend_for_prospect(prospect.prospect_id)
    after_count = len(oss.list())
    step(2, "Opportunities generated", after_count > 0, f"count={after_count}")

    # 3. Store grouping
    print("\n[3] Store grouping:")
    eligible = [o for o in opp_svc.by_prospect(prospect.prospect_id) if o.eligible]
    by_loc = {}
    for o in eligible:
        by_loc.setdefault(o.location_id, []).append(o)
    step(3, "Grouped by location", len(by_loc) > 0,
         f"{len(by_loc)} stores, {len(eligible)} eligible")

    # 4. Best placement
    print("\n[4] Best placement per store:")
    recs = svc.recommend(prospect.prospect_id, limit=5)
    step(4, "Recommendations derived", len(recs) > 0, f"{len(recs)} stores")
    step(4.1, "One rec per location",
         len(recs) == len({r.location_id for r in recs}))

    # 5-7. Score, Traffic, Price
    print("\n[5-7] Score, Traffic, Price:")
    for r in recs:
        step(5, f"Score: {r.location_name}", r.score > 0, str(r.score))
        step(6, f"Traffic: {r.location_name}",
             r.weekly_traffic is not None, str(r.weekly_traffic))
        step(7, f"Price: {r.location_name}",
             bool(r.price_display), r.price_display)
        break

    # 8. Distance honesty
    print("\n[8] Distance honesty:")
    for r in recs:
        loc = inv.inventory.get_location(r.location_id)
        no_coords = loc and (loc.latitude is None or loc.longitude is None)
        step(8, "Missing coords → None", not no_coords or r.distance_miles is None,
             f"dist={r.distance_miles}")
        break
    p_lat = prospect.metadata.get("latitude") if prospect.metadata else None
    step(8.1, "No fabricated prospect coords", p_lat is None)

    # 9. Refresh idempotency
    print("\n[9] Refresh idempotency:")
    before_ids = {o.opportunity_id for o in oss.list()}
    svc.recommend(prospect.prospect_id, limit=3, refresh=True)
    after_ids = {o.opportunity_id for o in oss.list()}
    step(9, "No duplicates after refresh", before_ids == after_ids)

    # 10. Top 3 / 5
    print("\n[10] Top N limits:")
    top3 = svc.recommend(prospect.prospect_id, limit=3)
    step(10, "Top 3", len(top3) <= 3, f"returned {len(top3)}")
    top5 = svc.recommend(prospect.prospect_id, limit=5)
    step(10.1, "Top 5", len(top5) <= 5, f"returned {len(top5)}")

    # 11. NEAREST ranking mode
    print("\n[11] NEAREST ranking:")
    try:
        near = svc.recommend(prospect.prospect_id, limit=3, rank_mode=RANK_NEAREST)
        step(11, "NEAREST mode works", True, f"returned {len(near)}")
    except Exception as exc:
        step(11, "NEAREST mode", False, str(exc))

    # 12. Synthetic multi-store ranking
    print("\n[12] Synthetic multi-store ranking (CLEARLY LABELED):")
    from gui.models.inventory import Location as _Loc, Placement as _Pl, STATUS_AVAILABLE as _AV, PERIOD_YEAR as _PY, Money as _M
    syn_ret = inv.inventory.retailers[0]
    for i in range(3):
        lid = f"syn_loc_{i}"
        loc = _Loc(location_id=lid, retailer_id=syn_ret.retailer_id,
                    market_id=inv.inventory.markets[0].market_id,
                    name=f"SYNTHETIC KS #{200+i}", store_number=str(200+i),
                    city="SynCity", state="CO", weekly_traffic=10000+i*5000)
        pl = _Pl(placement_id=f"syn_pl_{i}", location_id=lid,
                  name="SYNTHETIC Cart Corral", status=_AV,
                  price=_M.dollars(10000), price_period=_PY,
                  exclusive_category="Roofing")
        inv.inventory.locations.append(loc)
        inv.inventory.placements.append(pl)
    inv.save()

    opp_svc.recommend_for_prospect(prospect.prospect_id)
    multi = svc.recommend(prospect.prospect_id, limit=5)
    store_count = len({r.location_id for r in multi})
    step(12, "Synthetic locations included", store_count >= 3,
         f"{store_count} stores")
    step(12.1, "Ranked by score DESC",
         all(multi[i].score >= multi[i+1].score for i in range(len(multi)-1)))

    # --- Result ---
    print("\n" + "=" * 70)
    if _failures:
        print(f"RESULT: {len(_failures)} step(s) FAILED")
        for n, label, detail in _failures:
            print(f"  step {n}: {label} - {detail}")
        return 1
    print("RESULT: All Sprint 5D verification steps PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
