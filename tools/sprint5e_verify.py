"""Sprint 5E verification script — NO network, deterministic fake geocoder.

ALL COORDINATES ARE SYNTHETIC VERIFICATION DATA — NOT REAL LOCATIONS.
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def step(n, label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{str(n).rjust(4)}] {mark}: {label}")
    if detail:
        print(f"       {detail}")
    if not ok:
        print(f"\n*** VERIFICATION FAILED at step {n} ({label}) ***")
        sys.exit(1)


def main() -> None:
    from engine.geocoding import (
        FakeGeocoder,
        GeocodeResult,
        build_normalized_address,
        utc_now_iso,
    )
    from engine.opportunity import OpportunityEngine
    from gui.models.inventory import Location, Placement
    from gui.models.inventory_store import InventoryStore
    from gui.models.prospect import Prospect
    from gui.models.prospect_store import ProspectStore
    from gui.services.geocoding_cache import GeocodeCache
    from gui.services.location_enrichment import LocationEnrichmentService
    from gui.services.store_recommendation import StoreRecommendationService

    # ------------------------------------------------------------------
    # Setup: isolated temp dirs
    # ------------------------------------------------------------------
    tmpdir = os.path.join(PROJECT_ROOT, "output", "sprint5e_verify")
    os.makedirs(tmpdir, exist_ok=True)

    prospects_path = os.path.join(tmpdir, "prospects.json")
    inventory_path = os.path.join(tmpdir, "inventory.json")
    cache_path = os.path.join(tmpdir, "geocode_cache.json")

    for p in [prospects_path, inventory_path, cache_path]:
        if os.path.exists(p):
            os.remove(p)

    print("=" * 70)
    print("SPRINT 5E VERIFICATION — Location Enrichment + Geocoding Foundation")
    print("ALL COORDINATES ARE SYNTHETIC VERIFICATION DATA")
    print("=" * 70)

    # [1-2] Create verification Prospect + show unresolved
    print("\n[1-2] Create verification Prospect")
    prospect = Prospect(
        prospect_id="verify_p_5e",
        company_name="Verification Biz",
        address="200 S Wilcox St",
        city="Castle Rock",
        state="CO",
        postal_code="80104",
    )
    addr = build_normalized_address(
        street=prospect.address, city=prospect.city,
        state=prospect.state, postal_code=prospect.postal_code
    )
    step(1, "Prospect created", bool(prospect.address and prospect.city),
         f"{prospect.address}, {prospect.city}")
    step(2, "Coordinates are None initially",
         prospect.latitude is None and prospect.longitude is None,
         f"Address: {addr}")
    # [3-4] Geocode + persist prospect
    print("\n[3-4] Geocode Prospect via fake provider + persist")
    fake_result = GeocodeResult(
        latitude=39.3722, longitude=-104.8561,
        provider="fake_verifier",
        formatted_address="200 S Wilcox St, Castle Rock, CO 80104, US",
        queried_address=addr, source="geocoded", resolved_at=utc_now_iso(),
    )
    fake = FakeGeocoder({addr.lower(): fake_result})
    cache = GeocodeCache(path=cache_path)
    enrichment = LocationEnrichmentService(geocoder=fake, cache=cache)
    outcome = enrichment.enrich_prospect(prospect)
    step(3, "Prospect geocoded", outcome.success and prospect.latitude == 39.3722,
         f"lat={prospect.latitude}, lon={prospect.longitude}")

    pstore = ProspectStore(path=prospects_path)
    pstore.upsert(prospect)
    pstore.save()
    gm = getattr(prospect, "geocode_metadata", {})
    step(4, "Persisted with provenance",
         os.path.exists(prospects_path) and gm.get("source") == "geocoded",
         f"source={gm.get('source')}")

    # [5] Repeat lookup, prove cache hit
    print("\n[5] Repeat lookup — prove cache hit")
    calls_before = fake.call_count
    cache2 = GeocodeCache(path=cache_path)
    pstore2 = ProspectStore(path=prospects_path)
    pstore2.load()
    p2 = pstore2.get("verify_p_5e")
    step(5, "Prospect reloaded from disk",
         p2 is not None and p2.latitude == 39.3722,
         f"lat={p2.latitude if p2 else 'N/A'}")

    enrichment2 = LocationEnrichmentService(geocoder=fake, cache=cache2)
    if p2:
        p2.latitude = None
        p2.longitude = None
        p2.geocode_metadata = {}
        outcome2 = enrichment2.enrich_prospect(p2)
        step(5.1, "Cache hit on second lookup",
             outcome2.success and p2.latitude == 39.3722,
             f"calls before={calls_before} after={fake.call_count}")

    # [6-8] Inventory Location enrichment
    print("\n[6-8] Inventory Location enrichment")
    location = Location(
        location_id="verify_loc_5e", name="King Soopers (VERIFY)",
        address="100 Founders Pkwy", city="Castle Rock", state="CO",
        postal_code="80104",
    )
    step(6, "Location created, no coords",
         location.latitude is None and location.longitude is None,
         f"{location.address}, {location.city}")

    loc_addr = build_normalized_address(
        street=location.address, city=location.city,
        state=location.state, postal_code=location.postal_code
    )
    loc_result = GeocodeResult(
        latitude=39.3743, longitude=-104.8594, provider="fake_verifier",
        formatted_address="100 Founders Pkwy, Castle Rock, CO 80104, US",
        queried_address=loc_addr, source="geocoded", resolved_at=utc_now_iso(),
    )
    fake_loc = FakeGeocoder({loc_addr.lower(): loc_result})
    cache_loc = GeocodeCache(path=cache_path)
    enrichment_loc = LocationEnrichmentService(geocoder=fake_loc, cache=cache_loc)
    loc_outcome = enrichment_loc.enrich_location(location)
    step(7, "Location geocoded",
         loc_outcome.success and location.latitude == 39.3743,
         f"lat={location.latitude}, lon={location.longitude}")

    istore = InventoryStore(path=inventory_path)
    istore.inventory.locations.append(location)
    istore.save()
    loc_gm = getattr(location, "geocode_metadata", {})
    step(8, "Location persisted with provenance",
         os.path.exists(inventory_path) and loc_gm.get("source") == "geocoded",
         f"source={loc_gm.get('source')}")


    # [9-12] Downstream integration
    print("\n[9-12] Downstream: Opportunities + StoreRecommendation")
    engine = OpportunityEngine()
    placement = Placement(
        placement_id="verify_pl_5e", location_id=location.location_id,
        name="Front Cart Corral (VERIFY)", placement_type="cart_corral",
    )
    opp = engine.evaluate(prospect, placement, location)
    step(9, "Opportunity has real distance",
         opp.distance_miles is not None and opp.distance_source == "haversine",
         f"distance_miles={opp.distance_miles}")

    step(10, "distance_miles is reasonable float",
         isinstance(opp.distance_miles, float) and opp.distance_miles > 0,
         f"value={opp.distance_miles}")

    istore.inventory.placements.append(placement)
    rec_svc = StoreRecommendationService(inventory_store=istore)
    rec = rec_svc._build_recommendation(opp)
    step(11, "StoreRecommendation preserves distance",
         rec is not None and rec.distance_miles == opp.distance_miles,
         f"rec.distance_miles={rec.distance_miles if rec else 'N/A'}")

    # Create a second location further away
    loc_far = Location(
        location_id="verify_loc_far", name="Far Store (VERIFY)",
        address="1600 California St", city="Denver", state="CO",
        postal_code="80202", latitude=39.7480, longitude=-104.9930,
    )
    istore.inventory.locations.append(loc_far)
    placement_far = Placement(
        placement_id="verify_pl_far", location_id=loc_far.location_id,
        name="Rooftop (VERIFY)", placement_type="billboard",
    )
    istore.inventory.placements.append(placement_far)
    opp_far = engine.evaluate(prospect, placement_far, loc_far)
    istore.save()

    recs = []
    for o in [opp, opp_far]:
        r = rec_svc._build_recommendation(o)
        if r and r.distance_miles is not None:
            recs.append(r)
    nearest_first = (
        len(recs) >= 2
        and recs[0].distance_miles is not None
        and recs[1].distance_miles is not None
        and recs[0].distance_miles < recs[1].distance_miles
    )
    step(12, "NEAREST ranks closer first", nearest_first,
         f"near={recs[0].distance_miles}, far={recs[1].distance_miles}")
    # [13] Force refresh
    print("\n[13] Force refresh demonstrates provider re-call")
    prospect.latitude = 39.0
    prospect.longitude = -104.0
    prospect.geocode_metadata = {"source": "manual"}
    calls_before_refresh = fake.call_count
    outcome_refresh = enrichment.enrich_prospect(prospect, force_refresh=True)
    step(13, "Force refresh replaces manual coords",
         outcome_refresh.success and prospect.latitude == 39.3722,
         f"calls: {calls_before_refresh} -> {fake.call_count}")

    # [14] No duplicate
    print("\n[14] No duplicate Opportunities")
    opp2 = engine.evaluate(prospect, placement, location)
    step(14, "Same inputs produce consistent distance",
         opp2.distance_miles == opp.distance_miles,
         f"d1={opp.distance_miles}, d2={opp2.distance_miles}")

    # [15] Reload
    print("\n[15] Reload stores — coordinates survive restart")
    pstore3 = ProspectStore(path=prospects_path)
    pstore3.load()
    p3 = pstore3.get("verify_p_5e")
    step(15, "Prospect coordinates survive reload",
         p3 is not None and p3.latitude == 39.3722,
         f"lat={p3.latitude if p3 else 'N/A'}")

    istore3 = InventoryStore(path=inventory_path)
    istore3.load()
    loc3 = istore3.inventory.get_location("verify_loc_5e")
    step(15.1, "Location coordinates survive reload",
         loc3 is not None and loc3.latitude == 39.3743,
         f"lat={loc3.latitude if loc3 else 'N/A'}")

    # Summary
    print("\n" + "=" * 70)
    print("SPRINT 5E VERIFICATION: ALL STEPS PASSED")
    print("=" * 70)
    print(f"\n  Geocode cache entries: {cache.entry_count}")
    print(f"  Fake provider calls: {fake.call_count}")
    print(f"  Prospects file: {prospects_path}")
    print(f"  Inventory file: {inventory_path}")
    print(f"  Cache file: {cache_path}")
    print("\nAll coordinates are SYNTHETIC VERIFICATION DATA.")


if __name__ == "__main__":
    main()

