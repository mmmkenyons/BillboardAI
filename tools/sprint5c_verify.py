"""Sprint 5C prospect-to-inventory opportunity matching verification (Qt-free).

Uses **verification/seed data** (Jim Woods Roofing + a King Soopers Castle Rock
inventory fixture) — clearly NOT authoritative live inventory or outreach data.

Proves end-to-end, against the REAL stores + service:

1. load prospect
2. locate the researched Project (via metadata["prospect_id"], not company name)
3. load inventory
4. evaluate all placements
5. persist Opportunities
6. rank them (score DESC, deterministic)
7. print score + components + reasons
8. show a blocked / ineligible placement
9. rerun matching
10. prove NO duplicate Opportunity is created

Guarantees around honesty:

- Coordinates are NOT fabricated for the demo; the real Jim Woods prospect has
  no lat/lng, so ``distance_miles`` must remain ``None`` here.
- A SEPARATE synthetic-coordinate check proves the distance seam works for
  Sprint 5D (this is the only place coordinates are supplied).
- No web requests / scraping / LLM are used.

Run::

    python tools/sprint5c_verify.py

Runtime data is written under ``output/opportunities/sprint5c_verify``
(git-ignored via ``output/``).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.brand_profile import BrandProfile  # noqa: E402
from gui.models.inventory import (  # noqa: E402
    PERIOD_YEAR,
    STATUS_AVAILABLE,
    STATUS_SOLD,
    Money,
    Location,
    Market,
    Placement,
    Retailer,
)
from gui.models.inventory_store import InventoryStore  # noqa: E402
from gui.models.opportunity_store import OpportunityStore  # noqa: E402
from gui.models.project_store import ProjectStore  # noqa: E402
from gui.models.prospect import Prospect  # noqa: E402
from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.services.opportunity_service import OpportunityService  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_DIR = os.path.join(ROOT, "output", "opportunities", "sprint5c_verify")
PROSPECTS_PATH = os.path.join(VERIFY_DIR, "prospects.json")
INVENTORY_PATH = os.path.join(VERIFY_DIR, "inventory.json")
PROJECTS_ROOT = os.path.join(VERIFY_DIR, "projects")
OPPORTUNITIES_PATH = os.path.join(VERIFY_DIR, "opportunities.json")
def _seed() -> None:
    """Create the verification dataset (clearly-labeled, not authoritative)."""
    os.makedirs(VERIFY_DIR, exist_ok=True)

    # --- Prospect: Jim Woods Roofing (Castle Rock, CO) ---
    ps = ProspectStore(path=PROSPECTS_PATH)
    ps.collection.prospects = [
        Prospect(
            prospect_id="prospect_jimwoods",
            company_name="Jim Woods Roofing",
            website="https://www.jimwoodsroofing.com",
            domain="jimwoodsroofing.com",
            phone="(605) 764-9517",
            email="info@jimwoodsroofing.com",
            city="Castle Rock",
            state="CO",
            postal_code="80104",
            category="roofing",
            market_id="m_denver_metro",
            metadata={
                "source": "sprint5c_verify_seed",
                "authoritative": False,
            },
        )
    ]
    ps.save()

    # --- Researched Project associated via metadata["prospect_id"] ---
    pstore = ProjectStore(root=PROJECTS_ROOT)
    project = pstore.create(company_name="Jim Woods Roofing")
    project.metadata["prospect_id"] = "prospect_jimwoods"
    project.metadata["research_job_provenance"] = True
    project.brand_profile = BrandProfile(
        company_name="Jim Woods Roofing",
        website="https://www.jimwoodsroofing.com",
        domain="jimwoodsroofing.com",
        categories=["roofing"],
        quality_score=92.0,
        vision_score=70.0,
        phone="(605) 764-9517",
        differentiators=["licensed", "insured"],
        trust_signals=["local", "BBB"],
    ).to_dict()
    pstore.save(project)
    # --- King Soopers Castle Rock inventory fixture (NOT authoritative) ---
    inv = InventoryStore(path=INVENTORY_PATH)
    retailer = Retailer(name="King Soopers", parent_company="Kroger")
    market = Market(name="Denver Metro", state="CO", region="Front Range")
    location = Location(
        retailer_id=retailer.retailer_id,
        market_id=market.market_id,
        name="King Soopers #123",
        store_number="123",
        address="950 N. Wilcox St.",
        city="Castle Rock",
        state="CO",
        postal_code="80104",
        weekly_traffic=15000,
        metadata={"source": "sprint5c_verify_seed", "authoritative": False},
    )
    placements = [
        Placement(
            location_id=location.location_id,
            name="Front Cart Corral A",
            placement_type="front_entrance",
            scene_template="cart_corral",
            status=STATUS_AVAILABLE,
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
            setup_fee=Money.dollars(500),
            exclusive_category="Roofing",  # one roofing company per store
            blocked_categories=["attorney"],
            notes="Verification seed data - not authoritative.",
        ),
        Placement(
            location_id=location.location_id,
            name="Cart Nose A",
            placement_type="cart_handles",
            scene_template="cart_nose",
            status=STATUS_AVAILABLE,
            price=Money.dollars(8000),
            price_period=PERIOD_YEAR,
        ),
        Placement(
            location_id=location.location_id,
            name="Front Cart Corral B",
            placement_type="front_entrance",
            scene_template="cart_corral",
            status=STATUS_SOLD,  # realtor category already sold -> blocked
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
            exclusive_category="Realtor",
        ),
    ]
    inv.create_inventory([retailer], [market], [location], placements)
    inv.save()

    # Start with a clean opportunities file.
    if os.path.isfile(OPPORTUNITIES_PATH):
        os.remove(OPPORTUNITIES_PATH)
_failures: list = []


def step(n: int, label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  step {n}: [{mark}] {label}" + (f" ({detail})" if detail else ""))
    if not ok:
        _failures.append((n, label, detail))


def main() -> int:
    print("=" * 70)
    print("SPRINT 5C - PROSPECT TO INVENTORY OPPORTUNITY MATCHING")
    print("  NOTE: verification/seed data only - NOT authoritative inventory.")
    print("=" * 70)

    _seed()

    os.makedirs(os.path.join(VERIFY_DIR, "projects"), exist_ok=True)
    ps = ProspectStore(path=PROSPECTS_PATH)
    os.makedirs(os.path.dirname(INVENTORY_PATH), exist_ok=True)
    inv = InventoryStore(path=INVENTORY_PATH)
    inv.load()  # populate the store's in-memory inventory snapshot
    project_store = ProjectStore(root=PROJECTS_ROOT)
    oss = OpportunityStore(path=OPPORTUNITIES_PATH)

    svc = OpportunityService(
        prospect_store=ps,
        project_store=project_store,
        inventory_store=inv,
        opportunity_store=oss,
    )

    # 1. load prospect
    print("\n[1] Load prospect:")
    prospect = svc.locate_prospect("prospect_jimwoods")
    step(1, "Prospect loaded", prospect is not None,
         prospect.company_name if prospect else "")
    assert prospect is not None

    # 2. locate researched Project via metadata["prospect_id"]
    print("\n[2] Locate researched Project:")
    project = svc.locate_project(prospect.prospect_id)
    step(2, "Project found by metadata[prospect_id]",
         project is not None and project.metadata.get("prospect_id") == prospect.prospect_id,
         project.id if project else "")

    # 3. load inventory
    print("\n[3] Load inventory:")
    inv_reloaded = InventoryStore(path=INVENTORY_PATH).load()
    step(3, "Inventory loaded", len(inv_reloaded.placements) == 3,
         f"{len(inv_reloaded.locations)} location, {len(inv_reloaded.placements)} placements")

    # 4. evaluate all placements
    print("\n[4] Evaluate all placements:")
    evaluated = svc.rank_placements_for_prospect(prospect.prospect_id, include_ineligible=True)
    step(4, "All placements evaluated", len(evaluated) == 3,
         f"{len(evaluated)} opportunities")

    # 5. persist opportunities
    print("\n[5] Persist opportunities:")
    svc.recommend_for_prospect(prospect.prospect_id)
    persisted = oss.list()
    step(5, "Opportunities persisted", len(persisted) == 3,
         f"{len(persisted)} rows -> {OPPORTUNITIES_PATH}")
# 6. print ranked opportunities with score + components + reasons
    print("\n[6] Ranked opportunities for Jim Woods Roofing:")
    ranked = svc.rank_placements_for_prospect(prospect.prospect_id, include_ineligible=True)
    ranked_eligible = [o for o in ranked if o.eligible]
    scores = [o.score for o in ranked_eligible]
    step(6, "Ranked score DESC", scores == sorted(scores, reverse=True), str(scores))

    for i, o in enumerate(ranked, start=1):
        placement = inv.inventory.get_placement(o.placement_id)
        pname = placement.name if placement else o.placement_id
        print(f"  {i}. {pname}")
        print(f"     Score: {o.score}   Eligible: {'YES' if o.eligible else 'NO'}"
              f"   Status: {o.status}")
        if o.eligible:
            print(f"     Category: {o.recommended_category}")
            traffic = placement.effective_weekly_traffic(inv.inventory.get_location(o.location_id)) if placement else None
            if traffic:
                print(f"     Traffic: {traffic:,}/week")
            else:
                print("     Traffic: unknown")
            print(f"     Distance: {o.distance_miles} miles ({o.distance_source or 'none'})")
            print("     Components:")
            for k, v in o.score_components.items():
                print(f"       {k}: {v}")
            print("     Reasons:")
            for r in o.reasons:
                print(f"       - {r}")
        else:
            print("     Reasons (blocked):")
            for r in o.eligibility_reasons:
                print(f"       - {r}")
        print()

    # 7. show blocked/ineligible placement
    print("[7] Blocked / ineligible placement:")
    blocked = [o for o in ranked if not o.eligible]
    step(7, "At least one ineligible placement shown",
         len(blocked) >= 1 and all(o.score == 0 for o in blocked),
         f"{len(blocked)} ineligible, score 0")
    for o in blocked:
        placement = inv.inventory.get_placement(o.placement_id)
        print(f"  {placement.name if placement else o.placement_id}: "
              f"eligible={o.eligible} score={o.score} reasons={o.eligibility_reasons}")

    # 8. rerun matching
    print("\n[8] Rerun matching (idempotency):")
    before_ids = {o.opportunity_id for o in oss.list()}
    before_created = {o.created_at for o in oss.list()}
    svc.recommend_for_prospect(prospect.prospect_id)
    after_ids = {o.opportunity_id for o in oss.list()}
    after_created = {o.created_at for o in oss.list()}
    step(8, "No duplicate Opportunity created", len(oss.list()) == 3 and before_ids == after_ids,
         f"count={len(oss.list())}")
    step(8.1, "created_at preserved across reruns", before_created == after_created)

    # 9. distance honesty: real Jim Woods prospect has no coords -> None
    print("\n[9] Distance honesty (no fabricated coordinates):")
    real = [o for o in ranked if o.eligible]
    all_none = all(o.distance_miles is None for o in real)
    step(9, "distance_miles is None for real prospect (no coords)",
         all_none, "confirmed no fabricated coordinates")

    # 10. synthetic coordinate check (separate, explicit)
    print("\n[10] Synthetic coordinate distance check (Sprint 5D seam):")
    from engine.opportunity import OpportunityEngine  # noqa: E402
    from gui.models.prospect import Prospect as _Prospect  # noqa: E402
    from gui.models.inventory import Location as _Location  # noqa: E402
    syn_prospect = _Prospect(
        prospect_id="syn", category="roofing",
        metadata={"latitude": 39.3743, "longitude": -104.8594},
    )
    syn_loc = _Location(
        location_id="syn_loc", city="Castle Rock", state="CO",
        latitude=39.3743, longitude=-104.8594,
    )
    syn_opp = OpportunityEngine().evaluate(
        syn_prospect, inv.inventory.placements[0], syn_loc
    )
    approx_zero = syn_opp.distance_miles is not None and syn_opp.distance_miles < 0.1
    step(10, "Synthetic straight-line distance computed",
         approx_zero and syn_opp.distance_source == "haversine",
         f"distance={syn_opp.distance_miles} source={syn_opp.distance_source}")

    print("\n" + "=" * 70)
    if _failures:
        print(f"RESULT: {len(_failures)} step(s) FAILED")
        for n, label, detail in _failures:
            print(f"  step {n}: {label} - {detail}")
        return 1
    print("RESULT: All Sprint 5C verification steps PASSED.")
    print(f"Artifacts under: {VERIFY_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
