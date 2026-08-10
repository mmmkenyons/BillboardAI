"""Sprint 4A inventory model/persistence verification tool.

**IMPORTANT — this is a verification/seed fixture, NOT authoritative live
inventory.** The dataset below uses plausible program assumptions (a Castle Rock
King Soopers example) purely to prove the inventory model + persistence layer
works end-to-end. It must never be presented as real, current, or accurate
advertising inventory.

The script proves, in order:

1. create retailer
2. create market
3. create location
4. create multiple placements
5. persist
6. reload
7. filter inventory
8. check category availability
9. print a concise inventory tree

Run::

    python tools/sprint4a_verify.py

Output is written to ``output/inventory/sprint4a_verify.json`` (git-ignored).
"""

from __future__ import annotations

import os
import sys

# Allow running directly from repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.models.inventory import (  # noqa: E402
    PERIOD_YEAR,
    STATUS_AVAILABLE,
    STATUS_SOLD,
    Money,
    Placement,
    Retailer,
    Market,
    Location,
)
from gui.models.inventory_store import InventoryStore  # noqa: E402


def build_verification_inventory():
    """Build a small, clearly-labeled verification/seed inventory snapshot."""
    # 1. Retailer (parent = Kroger, but no Kroger-specific behavior hardcoded).
    retailer = Retailer(
        name="King Soopers",
        parent_company="Kroger",
        brand_name="King Soopers",
        website="https://www.kingsoopers.com",
    )

    # 2. Market.
    market = Market(name="Denver Metro", state="CO", region="Front Range")

    # 3. Location (a Castle Rock King Soopers example).
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
        metadata={"source": "sprint4a_verify_seed", "authoritative": False},
    )
# 4. Multiple placements (two share the same physical scene template).
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
            status=STATUS_SOLD,  # realtor category already sold
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
            exclusive_category="Realtor",
        ),
    ]

    return retailer, market, location, placements


def print_tree(retailer, market, location, placements) -> None:
    """Print a concise inventory tree (no GUI)."""
    u = "\u2500"  # horizontal line
    v = "\u2502"  # vertical line
    tl = "\u251c"  # tee-left (mid child)
    ll = "\u2514"  # corner-left (last child)

    lines = []
    lines.append(retailer.parent_company or retailer.name)
    lines.append(f"{tl}{u}{u} {retailer.name}")
    lines.append(f"{v}   {tl}{u}{u} {market.name} ({market.state})")
    lines.append(f"{v}   {v}   {tl}{u}{u} "
                 f"{location.name} (store #{location.store_number}, {location.city})")

    for i, p in enumerate(placements):
        is_last = i == len(placements) - 1
        branch = ll if is_last else tl
        child = "    " if is_last else f"{v}   "
        lines.append(f"{v}   {v}   {branch}{u}{u} {p.name}")
        lines.append(f"{v}   {v}   {child}   {p.status}")
        if p.price_display():
            lines.append(f"{v}   {v}   {child}   {p.price_display()}")
        lines.append(f"{v}   {v}   {child}   scene: {p.scene_template}")

    print("\n".join(lines))
def main() -> int:
    retailer, market, location, placements = build_verification_inventory()
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output",
        "inventory",
        "sprint4a_verify.json",
    )

    # 5. Persist.
    store = InventoryStore(path)
    store.create_inventory([retailer], [market], [location], placements)
    store.save()
    print(f"Persisted verification inventory to: {path}")

    # 6. Reload.
    reloaded = InventoryStore(path).load()
    print(
        f"Reloaded: {len(reloaded.retailers)} retailer(s), "
        f"{len(reloaded.markets)} market(s), {len(reloaded.locations)} "
        f"location(s), {len(reloaded.placements)} placement(s)."
    )

    # 7. Filter.
    loc = reloaded.locations[0]
    by_loc = reloaded.placements_by_location(loc.location_id)
    by_ret = reloaded.placements_by_retailer(retailer.retailer_id)
    by_mkt = reloaded.placements_by_market(market.market_id)
    by_status = reloaded.placements_by_status(STATUS_AVAILABLE)
    print(f"Filter by location: {len(by_loc)}; by retailer: {len(by_ret)}; "
          f"by market: {len(by_mkt)}; by AVAILABLE: {len(by_status)}")

    # 8. Category availability.
    corral_a = reloaded.get_placement(placements[0].placement_id)
    corral_b = reloaded.get_placement(placements[2].placement_id)
    print("Category availability:")
    print(f"  Front Cart Corral A for 'Roofing'  -> {corral_a.is_available_for('Roofing')}")
    print(f"  Front Cart Corral A for 'Dentist'  -> {corral_a.is_available_for('Dentist')}")
    print(f"  Front Cart Corral A for 'attorney' -> {corral_a.is_available_for('attorney')}")
    print(f"  Front Cart Corral B for 'Realtor'  -> {corral_b.is_available_for('Realtor')}")

    # 9. Inventory tree.
    print("\nInventory tree:")
    print_tree(retailer, market, location, placements)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())