"""Sprint 4B inventory workspace verification tool.

**IMPORTANT — this is a verification/seed fixture, NOT authoritative live
inventory.** The dataset uses plausible program assumptions (a Castle Rock King
Soopers example) purely to prove the inventory workspace flows work end-to-end.

The script proves, in order:

1. create/load seed inventory
2. open through InventoryWorkspaceService
3. enumerate the hierarchy
4. select the Castle Rock location
5. list placements
6. update one placement status
7. update pricing
8. run a category availability check
9. save
10. reload
11. confirm all edits persist

Then it performs an offscreen GUI smoke test:

- open the inventory page
- hierarchy visible
- select location
- select placement
- detail fields populate
- edit/save succeeds
- no crash

Run::

    python tools/sprint4b_verify.py

Output is written to ``output/inventory/sprint4b_verify.json`` (git-ignored).
No live network is used.
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
    STATUS_HELD,
)
from gui.models.inventory_store import InventoryStore  # noqa: E402
from gui.services.inventory_workspace import (  # noqa: E402
    InventoryWorkspaceService,
)


def build_seed(svc: InventoryWorkspaceService):
    """Create the Sprint 4A verification seed through the service."""
    retailer = svc.create_retailer(
        name="King Soopers",
        parent_company="Kroger",
        brand_name="King Soopers",
        website="https://www.kingsoopers.com",
    )
    market = svc.create_market(name="Denver Metro", state="CO", region="Front Range")
    location = svc.create_location(
        retailer_id=retailer.retailer_id,
        market_id=market.market_id,
        name="King Soopers #123",
        store_number="123",
        address="950 N. Wilcox St.",
        city="Castle Rock",
        state="CO",
        postal_code="80104",
        weekly_traffic=15000,
    )
    placements = [
        svc.create_placement(
            location_id=location.location_id,
            name="Front Cart Corral A",
            placement_type="front_entrance",
            scene_template="cart_corral",
            status=STATUS_AVAILABLE,
            price="12000",
            price_period=PERIOD_YEAR,
            setup_fee="500",
            exclusive_category="Roofing",
            blocked_categories="attorney",
            notes="Verification seed data - not authoritative.",
        ),
        svc.create_placement(
            location_id=location.location_id,
            name="Cart Nose A",
            placement_type="cart_handles",
            scene_template="cart_nose",
            status=STATUS_AVAILABLE,
            price="8000",
            price_period=PERIOD_YEAR,
        ),
        svc.create_placement(
            location_id=location.location_id,
            name="Front Cart Corral B",
            placement_type="front_entrance",
            scene_template="cart_corral",
            status=STATUS_SOLD,
            price="12000",
            price_period=PERIOD_YEAR,
            exclusive_category="Realtor",
        ),
    ]
    return retailer, market, location, placements
def main() -> int:
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output",
        "inventory",
        "sprint4b_verify.json",
    )
    store = InventoryStore(path=path)
    svc = InventoryWorkspaceService(store=store)
    svc.load()

    # Start from a fresh snapshot so re-runs are deterministic.
    store.create_inventory()
    svc.save()

    # 1. Create/load seed.
    retailer, market, location, placements = build_seed(svc)
    print(f"Seeded: retailer={retailer.name}, market={market.name}, "
          f"location={location.name}, placements={len(placements)}")

    # 2. Open through the service.
    svc.reload()
    print("Reloaded through InventoryWorkspaceService.")

    # 3. Enumerate hierarchy.
    hierarchy = svc.hierarchy()
    assert len(hierarchy) == 1
    market_node = hierarchy[0]["markets"][0]
    loc_nodes = market_node["locations"]
    print(f"Hierarchy: {len(hierarchy)} retailer, "
          f"{len(loc_nodes)} location(s).")

    # 4. Select the Castle Rock location.
    castle_rock = svc.get_location(location.location_id)
    assert castle_rock is not None and castle_rock.city == "Castle Rock"
    print("Selected Castle Rock location.")

    # 5. List placements.
    by_loc = svc.store.inventory.placements_by_location(location.location_id)
    print(f"Placements at location: {len(by_loc)}")

    # 6. Update one placement status.
    target = [p for p in by_loc if p.name == "Front Cart Corral A"][0]
    svc.set_placement_status(target.placement_id, STATUS_HELD)
    print(f"Set {target.name} status -> {STATUS_HELD}")

    # 7. Update pricing.
    svc.update_placement(
        target.placement_id,
        name=target.name,
        placement_type=target.placement_type,
        scene_template=target.scene_template,
        status=STATUS_HELD,
        price="13500",
        price_period=PERIOD_YEAR,
        setup_fee="750",
        exclusive_category=target.exclusive_category,
        blocked_categories=target.blocked_categories,
        traffic_override=target.traffic_override,
        notes="Updated by sprint4b verification.",
    )
    print("Updated pricing -> $13,500/year, $750 setup.")

    # 8. Category availability check.
    details = svc.availability_details(target.placement_id, "Roofing")
    print(f"Availability Roofing -> available={details['available']} "
          f"({details['reason']})")

    # 9. Save.
    svc.save()
    print("Saved.")

    # 10. Reload.
    svc.reload()
    reloaded = svc.get_placement(target.placement_id)
    assert reloaded is not None
    assert reloaded.status == STATUS_HELD
    assert reloaded.price.amount_cents == 1350000
    assert reloaded.price_period == PERIOD_YEAR
    assert reloaded.setup_fee.amount_cents == 75000
    print("Reloaded; edits persisted.")

    # 11. Summary.
    s = svc.summary()
    print(f"Summary: total={s['total']} available={s['available']} "
          f"held={s['held']} sold={s['sold']}")

    # ---------- GUI offscreen smoke test ----------
    print("\n--- GUI smoke test (offscreen) ---")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from gui.controllers.inventory_controller import InventoryController
        from gui.views.inventory_workspace_page import InventoryWorkspacePage

        app = QApplication.instance() or QApplication([])
        ctrl = InventoryController(service=svc)
        ctrl.reload()
        page = InventoryWorkspacePage()
        page.set_controller(ctrl)

        # Hierarchy visible.
        assert page.tree.topLevelItemCount() >= 1
        print("Inventory page constructed; hierarchy visible.")

        # Select the location.
        page.select_entity("location", location.location_id)
        assert page.f_name.text() == location.name
        print("Selected location; detail populated.")

        # Select a placement.
        page.select_entity("placement", target.placement_id)
        assert page.f_name.text() == target.name
        assert page.f_status.currentData() == STATUS_HELD
        assert page.f_price.text() == "13500.0"
        print("Selected placement; detail fields populated.")

        # Edit + save through the page path.
        page.f_name.setText("Front Cart Corral A (Updated)")
        page._on_save()
        assert ctrl.get_placement(target.placement_id).name == \
            "Front Cart Corral A (Updated)"
        print("Edit + save succeeded.")

        # Availability checker UI.
        page.avail_input.setText("Roofing")
        page._on_check_availability()
        print(f"Availability checker -> {page.avail_result.text()}")
        print("GUI smoke test PASSED (no crash).")
    except Exception as exc:  # noqa: BLE001
        print(f"GUI smoke test FAILED: {exc}")
        return 1

    print("\nSprint 4B verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())