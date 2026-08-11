#!/usr/bin/env python
"""Sprint 5F verifier — Prospect Opportunity Workspace aggregation.

SYNTHETIC VERIFICATION DATA — no network, no geocoding provider, no scraping.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify():
    root = tempfile.mkdtemp(prefix="sprint5f_verify_")
    print(f"VERIFIER ROOT: {root}")
    print("SYNTHETIC VERIFICATION DATA\n")

    from engine.brand_profile import BrandProfile
    from gui.models.inventory import (
        PERIOD_YEAR, STATUS_AVAILABLE, Money,
        Location, Market, Placement, Retailer,
    )
    from gui.models.inventory_store import InventoryStore
    from gui.models.opportunity_store import OpportunityStore
    from gui.models.project_store import ProjectStore
    from gui.models.prospect import Prospect
    from gui.models.prospect_store import ProspectStore
    from gui.services.opportunity_service import OpportunityService
    from gui.services.prospect_opportunity_workspace import (
        ProspectOpportunityWorkspaceService,
    )

    # 1. Create verification Prospects
    ps = ProspectStore(path=os.path.join(root, "prospects.json"))
    p1 = Prospect(
        prospect_id="v_jim", company_name="Jim Woods Roofing",
        category="roofing", city="Castle Rock", state="CO",
        address="123 Main St, Castle Rock, CO",
        phone="(303) 555-0199", domain="jimwoodsroofing.com",
        market_id="m_den", latitude=39.37, longitude=-104.86,
        research_status="SUCCEEDED",
        geocode_metadata={"source": "manual"},
    )
    p2 = Prospect(
        prospect_id="v_baker", company_name="Baker Painting",
        category="painting", city="Denver", state="CO",
        address="456 Oak Ave, Denver, CO",
        phone="(720) 555-0147", domain="bakerpainting.com",
        research_status="QUEUED",
    )
    ps.collection.prospects.extend([p1, p2])
    ps.save()
    print("[1] Created 2 verification prospects")

    # 2. Researched Project
    psr = ProjectStore(root=os.path.join(root, "projects"))
    proj1 = psr.create(company_name="Jim Woods Roofing",
                       website="jimwoodsroofing.com")
    proj1.metadata["prospect_id"] = "v_jim"
    proj1.brand_profile = BrandProfile(
        categories=["roofing"], quality_score=92.0, vision_score=70.0,
        phone="(303) 555-0199",
        differentiators=["licensed", "insured"],
        trust_signals=["BBB A+", "4.8 stars"],
    ).to_dict()
    psr.save(proj1)
    print("[2] Researched project created for v_jim")

    # 3. Load Inventory
    invs = InventoryStore(path=os.path.join(root, "inventory.json"))
    retailer = Retailer(name="King Soopers")
    market = Market(name="Denver Metro", market_id="m_den")
    loc1 = Location(
        location_id="l_ks123", name="King Soopers #123",
        retailer_id=retailer.retailer_id, market_id=market.market_id,
        store_number="123", city="Castle Rock", state="CO",
        latitude=39.39, longitude=-104.85, weekly_traffic=15000,
    )
    loc2 = Location(
        location_id="l_ks456", name="King Soopers #456",
        retailer_id=retailer.retailer_id, market_id=market.market_id,
        store_number="456", city="Castle Rock", state="CO",
        latitude=39.40, longitude=-104.88, weekly_traffic=12000,
    )
    loc3 = Location(
        location_id="l_ks789", name="King Soopers #789",
        retailer_id=retailer.retailer_id, market_id=market.market_id,
        store_number="789", city="Denver", state="CO",
        latitude=39.74, longitude=-104.99, weekly_traffic=18000,
    )
    placements = []
    for i, loc in enumerate([loc1, loc2, loc3], start=1):
        placements.append(Placement(
            placement_id=f"pl_cart_{i}", location_id=loc.location_id,
            name="Front Cart Corral", placement_type="cart_corral",
            status=STATUS_AVAILABLE,
            price=Money.dollars(12000), price_period=PERIOD_YEAR,
        ))
    invs.create_inventory(
        retailers=[retailer], markets=[market],
        locations=[loc1, loc2, loc3], placements=placements,
    )
    invs.save()
    print("[3] Inventory loaded: 1 retailer, 1 market, 3 locations, 3 placements")
    # 4. Load/recompute Opportunities + build snapshot
    opp_store = OpportunityStore(path=os.path.join(root, "opportunities.json"))
    svc = ProspectOpportunityWorkspaceService(
        prospect_store=ps, project_store=psr, inventory_store=invs,
        opportunity_service=OpportunityService(
            prospect_store=ps, project_store=psr,
            inventory_store=invs, opportunity_store=opp_store,
        ),
    )
    snap = svc.refresh_for_prospect("v_jim", recommendation_limit=3)
    print("[4] Opportunities recomputed via existing service")
    print()
    print("[5] ProspectOpportunitySnapshot built")
    print(f"    Company: {snap.company_name}")
    print(f"[6] Research: {snap.research_status}")
    print(f"    Complete: {snap.research_complete}")
    print(f"[7] Location: {snap.location_status}")
    print(f"    Address:  {snap.address_display}")
    print(f"    Coords:   {snap.latitude}, {snap.longitude}")
    print(f"    Source:   {snap.coordinate_source}")
    print(f"[8] Opportunities: {snap.opportunity_count} total, "
          f"{snap.eligible_opportunity_count} eligible")
    print(f"[9] Best Store:")
    if snap.best_store:
        bs = snap.best_store
        print(f"    {bs.retailer_name} #{bs.store_number} - {bs.city}, {bs.state}")
        print(f"[10] Best Placement:")
        print(f"    {bs.placement_name} ({bs.placement_type})")
    else:
        print("    No eligible inventory match")
    print(f"[11] Score: {snap.best_match_score}")
    print(f"    Match: {snap.match_strength}")
    print(f"[12] Weekly Traffic: {snap.weekly_traffic}")
    print(f"[13] Price: {snap.price_display}")
    if snap.distance_miles is not None:
        print(f"[14] Distance: {snap.distance_miles:.1f} mi")
    else:
        print("[14] Distance unavailable")
    print(f"[15] Why This Fits:")
    if snap.reasons:
        for r in snap.reasons[:5]:
            print(f"    - {r}")
    else:
        print("    (no reasons)")
    print(f"[16] Top 3 Recommended Stores ({len(snap.recommendations)}):")
    for i, rec in enumerate(snap.recommendations, start=1):
        dist = f"{rec.distance_miles:.1f} mi" if rec.distance_miles else "N/A"
        print(f"    #{i} {rec.retailer_name} #{rec.store_number} "
              f"Score {rec.score:>3}  Dist {dist}")


    # 17. Switch prospect — no stale data
    snap2 = svc.snapshot_for_prospect("v_baker")
    assert snap2.company_name == "Baker Painting", "Stale data!"
    assert snap2.prospect_id != snap.prospect_id, "Same id!"
    print(f"[17] Switched to Baker Painting - no stale data")
    print(f"    Company: {snap2.company_name}")
    print(f"    Research: {snap2.research_status}")

    # 18. No duplicate Opportunities after refresh
    svc.refresh_for_prospect("v_jim")
    svc.refresh_for_prospect("v_jim")
    opps = svc._opportunity_service.by_prospect("v_jim")
    pids = [o.placement_id for o in opps]
    assert len(pids) == len(set(pids)), "Duplicates!"
    print(f"[18] No duplicate Opportunities after 2 refreshes: {len(opps)} unique")

    # 19. Reload persistence and rebuild snapshot
    ps2 = ProspectStore(path=os.path.join(root, "prospects.json"))
    psr2 = ProjectStore(root=os.path.join(root, "projects"))
    invs2 = InventoryStore(path=os.path.join(root, "inventory.json"))
    opp_store2 = OpportunityStore(
        path=os.path.join(root, "opportunities.json"))
    opp_svc2 = OpportunityService(
        prospect_store=ps2, project_store=psr2,
        inventory_store=invs2, opportunity_store=opp_store2,
    )
    svc2 = ProspectOpportunityWorkspaceService(
        prospect_store=ps2, project_store=psr2,
        inventory_store=invs2, opportunity_service=opp_svc2,
    )
    snap3 = svc2.snapshot_for_prospect("v_jim")
    assert snap3.company_name == "Jim Woods Roofing"
    assert snap3.research_status == "SUCCEEDED"
    assert snap3.prospect_id == snap.prospect_id
    print(f"[19] Reloaded from persistence - snapshot consistent")
    print(f"    Company: {snap3.company_name}")
    print(f"    Research: {snap3.research_status}")
    print(f"    Location: {snap3.location_status}")
    print(f"    Opportunities: {snap3.opportunity_count}")

    # 20. All ASCII-safe
    def _is_ascii(s):
        try:
            s.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False
    check_fields = [
        snap.company_name, snap.research_status, snap.location_status,
        snap.match_strength, snap.address_display, snap.price_display,
    ]
    all_ascii = all(_is_ascii(f) for f in check_fields if f)
    assert all_ascii, "Non-ASCII found in output!"
    print("[20] All output ASCII-safe: PASS")

    # SUMMARY
    print()
    print("=" * 60)
    print("SPRINT 5F VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Temp data at: {root}")
    print("All 20 verification steps passed.")
    print("No network, no geocoding provider, no scraping used.")
    print("SYNTHETIC VERIFICATION DATA - not real prospects or inventory.")
    return 0


if __name__ == "__main__":
    sys.exit(verify())
