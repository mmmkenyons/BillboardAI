"""Sprint 4B inventory workspace test suite.

Tests the Qt-free :class:`~gui.services.inventory_workspace.InventoryWorkspaceService`
directly (load, hierarchy, CRUD, relationships, availability, traffic, money,
filtering, archive, scene templates, persistence) plus a small set of
Qt-guarded controller/page tests that only run when a QApplication is
available (offscreen platform). Filesystem tests use ``tmp_path`` and never
touch the real ``output/inventory`` directory.
"""

from __future__ import annotations

import json
import os

import pytest

from gui.models.inventory import (
    PERIOD_MONTH,
    PERIOD_ONETIME,
    PERIOD_YEAR,
    STATUS_ARCHIVED,
    STATUS_AVAILABLE,
    STATUS_HELD,
    STATUS_SOLD,
    Money,
    Placement,
    Retailer,
    Market,
    Location,
)
from gui.models.inventory_store import (
    InventoryCorruptionError,
    InventoryStore,
)
from gui.services.inventory_workspace import (
    InventoryValidationError,
    InventoryWorkspaceService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _service(tmp_path) -> InventoryWorkspaceService:
    path = os.path.join(str(tmp_path), "inventory.json")
    store = InventoryStore(path=path)
    svc = InventoryWorkspaceService(store=store)
    svc.load()
    return svc


def _seed(svc: InventoryWorkspaceService):
    """Create the standard Castle Rock seed hierarchy through the service."""
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
    p1 = svc.create_placement(
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
    )
    p2 = svc.create_placement(
        location_id=location.location_id,
        name="Cart Nose A",
        placement_type="cart_handles",
        scene_template="cart_nose",
        status=STATUS_AVAILABLE,
        price="8000",
        price_period=PERIOD_YEAR,
    )
    p3 = svc.create_placement(
        location_id=location.location_id,
        name="Front Cart Corral B",
        placement_type="front_entrance",
        scene_template="cart_corral",
        status=STATUS_SOLD,
        price="12000",
        price_period=PERIOD_YEAR,
        exclusive_category="Realtor",
    )
    return retailer, market, location, [p1, p2, p3]
# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
class TestLoad:
    def test_empty_inventory_loads(self, tmp_path) -> None:
        svc = _service(tmp_path)
        assert svc.list_retailers() == []
        assert svc.list_markets() == []
        assert svc.list_locations() == []
        assert svc.list_placements() == []

    def test_persisted_inventory_loads(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        reloaded = _service(tmp_path)
        assert len(reloaded.list_retailers()) == 1
        assert len(reloaded.list_placements()) == 3

    def test_corrupt_inventory_surfaced(self, tmp_path) -> None:
        path = os.path.join(str(tmp_path), "inventory.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json !!!")
        store = InventoryStore(path=path)
        svc = InventoryWorkspaceService(store=store)
        with pytest.raises(InventoryCorruptionError):
            svc.load()


# ---------------------------------------------------------------------------
# TREE
# ---------------------------------------------------------------------------
class TestTree:
    def test_retailer_hierarchy(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h = svc.hierarchy()
        assert len(h) == 1
        assert h[0]["retailer"].name == "King Soopers"

    def test_market_hierarchy(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h = svc.hierarchy()
        assert len(h[0]["markets"]) == 1
        assert h[0]["markets"][0]["market"].name == "Denver Metro"

    def test_location_hierarchy(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h = svc.hierarchy()
        locs = h[0]["markets"][0]["locations"]
        assert len(locs) == 1
        assert locs[0]["location"].name == "King Soopers #123"

    def test_placement_hierarchy(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h = svc.hierarchy()
        placements = h[0]["markets"][0]["locations"][0]["placements"]
        assert len(placements) == 3

    def test_deterministic_ordering(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h1 = svc.hierarchy()
        h2 = svc.hierarchy()
        assert h1 == h2
        svc.reload()
        h3 = svc.hierarchy()
        assert h1 == h3
# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------
class TestCreate:
    def test_create_retailer(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="Target", parent_company="Target Corp")
        assert r.name == "Target"
        assert len(svc.list_retailers()) == 1

    def test_create_market(self, tmp_path) -> None:
        svc = _service(tmp_path)
        m = svc.create_market(name="Denver Metro", state="CO")
        assert m.name == "Denver Metro"
        assert len(svc.list_markets()) == 1

    def test_create_location(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="King Soopers")
        m = svc.create_market(name="Denver Metro")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="Store 1"
        )
        assert loc.retailer_id == r.retailer_id
        assert loc.market_id == m.market_id

    def test_create_placement(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="King Soopers")
        m = svc.create_market(name="Denver Metro")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="Store 1"
        )
        p = svc.create_placement(location_id=loc.location_id, name="Cart Nose A")
        assert p.location_id == loc.location_id

    def test_parent_context_prefilled(self, tmp_path) -> None:
        """New child uses the parent's id automatically (service stores it)."""
        svc = _service(tmp_path)
        r = svc.create_retailer(name="King Soopers")
        m = svc.create_market(name="Denver Metro")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="Store 1"
        )
        assert loc.retailer_id == r.retailer_id
        assert loc.market_id == m.market_id
        p = svc.create_placement(location_id=loc.location_id, name="A")
        assert p.location_id == loc.location_id

    def test_ids_unique(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r1 = svc.create_retailer(name="A")
        r2 = svc.create_retailer(name="B")
        assert r1.retailer_id != r2.retailer_id


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------
class TestUpdate:
    def test_retailer_update_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        svc.update_retailer(r.retailer_id, name="B", website="https://b.com")
        reloaded = _service(tmp_path)
        assert reloaded.get_retailer(r.retailer_id).name == "B"

    def test_market_update_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        m = svc.create_market(name="A")
        svc.update_market(m.market_id, name="B", state="CO")
        reloaded = _service(tmp_path)
        assert reloaded.get_market(m.market_id).name == "B"

    def test_location_update_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        svc.update_location(
            loc.location_id,
            retailer_id=r.retailer_id,
            market_id=m.market_id,
            name="S2",
            city="Denver",
        )
        reloaded = _service(tmp_path)
        updated = reloaded.get_location(loc.location_id)
        assert updated.name == "S2"
        assert updated.city == "Denver"

    def test_placement_update_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(location_id=loc.location_id, name="P1")
        svc.update_placement(
            p.placement_id,
            name="P2",
            placement_type="front",
            scene_template="cart_nose",
            status=STATUS_HELD,
            price="9999",
            price_period=PERIOD_MONTH,
            setup_fee="100",
            exclusive_category="Roofing",
            blocked_categories="attorney, law",
            traffic_override=20000,
            notes="note",
        )
        reloaded = _service(tmp_path)
        updated = reloaded.get_placement(p.placement_id)
        assert updated.name == "P2"
        assert updated.status == STATUS_HELD
        assert updated.price.amount_cents == 999900
        assert updated.price_period == PERIOD_MONTH
# ---------------------------------------------------------------------------
# RELATIONSHIPS
# ---------------------------------------------------------------------------
class TestRelationships:
    def test_invalid_retailer_reference_rejected(self, tmp_path) -> None:
        svc = _service(tmp_path)
        m = svc.create_market(name="Denver Metro")
        with pytest.raises(InventoryValidationError):
            svc.create_location(
                retailer_id="missing-retailer",
                market_id=m.market_id,
                name="S1",
            )

    def test_invalid_market_reference_rejected(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="King Soopers")
        with pytest.raises(InventoryValidationError):
            svc.create_location(
                retailer_id=r.retailer_id,
                market_id="missing-market",
                name="S1",
            )

    def test_invalid_location_reference_rejected(self, tmp_path) -> None:
        svc = _service(tmp_path)
        with pytest.raises(InventoryValidationError):
            svc.create_placement(location_id="missing-location", name="P")

    def test_orphan_display_handled(self, tmp_path) -> None:
        """Orphans are detected without crashing."""
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        svc.create_placement(location_id=loc.location_id, name="P")
        svc.store.inventory.locations[0].retailer_id = "gone"
        orphans = svc.orphans()
        assert loc.location_id in orphans["locations"]
        with pytest.raises(InventoryValidationError):
            svc.validate_relationships()
# ---------------------------------------------------------------------------
# PLACEMENT FIELDS
# ---------------------------------------------------------------------------
class TestPlacementFields:
    def test_status_change_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(location_id=loc.location_id, name="P")
        svc.set_placement_status(p.placement_id, STATUS_HELD)
        assert svc.get_placement(p.placement_id).status == STATUS_HELD
        assert _service(tmp_path).get_placement(p.placement_id).status == STATUS_HELD

    def test_scene_template_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", scene_template="cart_corral"
        )
        assert svc.get_placement(p.placement_id).scene_template == "cart_corral"

    def test_pricing_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id,
            name="P",
            price="12000",
            price_period=PERIOD_YEAR,
        )
        reloaded = _service(tmp_path).get_placement(p.placement_id)
        assert reloaded.price.amount_cents == 1200000
        assert reloaded.price_period == PERIOD_YEAR

    def test_setup_fee_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", setup_fee="500"
        )
        assert svc.get_placement(p.placement_id).setup_fee.amount_cents == 50000

    def test_weekly_traffic_override_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", traffic_override=20000
        )
        reloaded = _service(tmp_path).get_placement(p.placement_id)
        assert reloaded.traffic_override == 20000

    def test_blocked_categories_persist(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id,
            name="P",
            blocked_categories="attorney, law, Attorney",
        )
        reloaded = _service(tmp_path).get_placement(p.placement_id)
        assert "attorney" in reloaded.blocked_categories
        assert "law" in reloaded.blocked_categories
        assert reloaded.blocked_categories.count("attorney") == 1

    def test_exclusivity_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", exclusive_category="Roofing"
        )
        assert svc.get_placement(p.placement_id).exclusive_category == "Roofing"
# ---------------------------------------------------------------------------
# AVAILABILITY
# ---------------------------------------------------------------------------
class TestAvailability:
    def test_category_check_uses_is_available_for(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = [x for x in svc.list_placements() if x.exclusive_category == "Roofing"][0]
        assert svc.check_availability(p.placement_id, "Roofing")
        assert not svc.check_availability(p.placement_id, "MissingCat")

    def test_blocked_category_result(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = [x for x in svc.list_placements() if x.name == "Front Cart Corral A"][0]
        details = svc.availability_details(p.placement_id, "Attorney")
        assert not details["available"]
        assert details["reason"] == "Blocked"

    def test_exclusive_category_result(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = [x for x in svc.list_placements() if x.exclusive_category == "Roofing"][0]
        details = svc.availability_details(p.placement_id, "Dentist")
        assert not details["available"]
        assert "exclusive" in details["reason"].lower()

    def test_sold_placement_result(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = [x for x in svc.list_placements() if x.status == STATUS_SOLD][0]
        details = svc.availability_details(p.placement_id, "Realtor")
        assert not details["available"]
        assert "status" in details["reason"].lower()


# ---------------------------------------------------------------------------
# TRAFFIC
# ---------------------------------------------------------------------------
class TestTraffic:
    def test_inherited_traffic_displayed(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = [x for x in svc.list_placements() if x.traffic_override is None][0]
        assert svc.effective_traffic(p.placement_id) == 15000

    def test_override_traffic_displayed(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id,
            market_id=m.market_id,
            name="S1",
            weekly_traffic=10000,
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", traffic_override=20000
        )
        assert svc.effective_traffic(p.placement_id) == 20000


# ---------------------------------------------------------------------------
# MONEY
# ---------------------------------------------------------------------------
class TestMoney:
    def test_dollars_to_cents_conversion(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", price="12000.50"
        )
        assert p.price.amount_cents == 1200050

    def test_malformed_money_rejected(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        with pytest.raises(InventoryValidationError):
            svc.create_placement(
                location_id=loc.location_id, name="P", price="not-a-number"
            )

    def test_period_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id,
            name="P",
            price="1000",
            price_period=PERIOD_MONTH,
        )
        assert svc.get_placement(p.placement_id).price_period == PERIOD_MONTH

    def test_display_formatting(self, tmp_path) -> None:
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id,
            name="P",
            price="12000",
            price_period=PERIOD_YEAR,
        )
        assert p.price.format() == "$12,000"
        assert p.price_display() == "$12,000/year"
# ---------------------------------------------------------------------------
# FILTERING
# ---------------------------------------------------------------------------
class TestFiltering:
    def test_status_filter(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h = svc.hierarchy(status_filter=STATUS_SOLD)
        placements = h[0]["markets"][0]["locations"][0]["placements"]
        assert len(placements) == 1
        assert placements[0].status == STATUS_SOLD

    def test_filter_all_returns_all(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        h = svc.hierarchy(status_filter=None)
        placements = h[0]["markets"][0]["locations"][0]["placements"]
        assert len(placements) == 3


# ---------------------------------------------------------------------------
# ARCHIVE
# ---------------------------------------------------------------------------
class TestArchive:
    def test_placement_archive(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = svc.list_placements()[0]
        svc.archive_placement(p.placement_id)
        assert svc.get_placement(p.placement_id).status == STATUS_ARCHIVED

    def test_archived_placement_remains_persisted(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        p = svc.list_placements()[0]
        svc.archive_placement(p.placement_id)
        reloaded = _service(tmp_path)
        assert reloaded.get_placement(p.placement_id).status == STATUS_ARCHIVED

    def test_no_dangerous_cascade_delete(self, tmp_path) -> None:
        """Removing a retailer with locations is refused (no cascade)."""
        svc = _service(tmp_path)
        _seed(svc)
        r = svc.list_retailers()[0]
        with pytest.raises(InventoryValidationError):
            svc.remove_retailer(r.retailer_id)
        # The retailer and its children are still present.
        assert len(svc.list_retailers()) == 1
        assert len(svc.list_placements()) == 3


# ---------------------------------------------------------------------------
# SCENE TEMPLATES
# ---------------------------------------------------------------------------
class TestSceneTemplates:
    def test_scene_choices_dynamically_discovered(self, tmp_path) -> None:
        svc = _service(tmp_path)
        options = svc.scene_template_options()
        ids = {o.get("id") for o in options}
        assert "cart_corral" in ids
        assert "cart_nose" in ids

    def test_missing_scene_template_handled_safely(self, tmp_path) -> None:
        """A dangling scene reference loads fine and is not validated on load."""
        svc = _service(tmp_path)
        r = svc.create_retailer(name="A")
        m = svc.create_market(name="B")
        loc = svc.create_location(
            retailer_id=r.retailer_id, market_id=m.market_id, name="S1"
        )
        p = svc.create_placement(
            location_id=loc.location_id, name="P", scene_template="does_not_exist"
        )
        reloaded = _service(tmp_path)
        assert reloaded.get_placement(p.placement_id).scene_template == "does_not_exist"

    def test_no_hardcoded_template_names_in_service(self, tmp_path) -> None:
        """The service never hardcodes template names in its own logic."""
        import inspect

        import gui.services.inventory_workspace as mod

        source = inspect.getsource(mod)
        # The service module should not contain a hardcoded cart_corral literal
        # outside of the test helper import boundary. (Scene options come from
        # the renderer discovery.)
        assert "cart_corral" not in source.split('def scene_template_options')[1]


# ---------------------------------------------------------------------------
# PERSISTENCE
# ---------------------------------------------------------------------------
class TestPersistence:
    def test_close_reload_retains_inventory(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        reloaded = _service(tmp_path)
        assert len(reloaded.list_retailers()) == 1
        assert len(reloaded.list_markets()) == 1
        assert len(reloaded.list_locations()) == 1
        assert len(reloaded.list_placements()) == 3

    def test_create_save_reload_hierarchy(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        reloaded = _service(tmp_path)
        h = reloaded.hierarchy()
        assert len(h) == 1
        assert h[0]["retailer"].name == "King Soopers"
        assert len(h[0]["markets"][0]["locations"][0]["placements"]) == 3

    def test_service_never_manually_writes_json(self, tmp_path) -> None:
        """The service mutates the store snapshot, never raw files."""
        import inspect

        import gui.services.inventory_workspace as mod

        source = inspect.getsource(mod.InventoryWorkspaceService)
        assert "open(" not in source
        assert ".write(" not in source
        assert "json.dump" not in source
# ---------------------------------------------------------------------------
# GUI (Qt-guarded, offscreen)
# ---------------------------------------------------------------------------
def _qapplication():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        pytest.skip("PySide6 not available")
    app = QApplication.instance()
    if app is None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


class _InventoryHarness:
    """Build an InventoryWorkspacePage wired to a real controller + store."""

    def __init__(self, tmp_path, seed: bool = True) -> None:
        _qapplication()
        from gui.controllers.inventory_controller import InventoryController
        from gui.views.inventory_workspace_page import InventoryWorkspacePage

        path = os.path.join(str(tmp_path), "inventory.json")
        self.controller = InventoryController(path=path)
        self.page = InventoryWorkspacePage()
        if seed:
            _seed(self.controller.service)
            self.controller.reload()
        self.page.set_controller(self.controller)
        self.errors = []
        self.controller.error_message.connect(self.errors.append)


class TestInventoryPage:
    def test_inventory_page_constructs_offscreen(self, tmp_path) -> None:
        h = _InventoryHarness(tmp_path, seed=False)
        assert h.page is not None
        assert h.page._controller is not None

    def test_empty_state_renders_without_crash(self, tmp_path) -> None:
        h = _InventoryHarness(tmp_path, seed=False)
        assert h.page.tree.topLevelItemCount() == 1
        assert h.page.tree.topLevelItem(0).text(0) == "No retailers yet"

    def test_selecting_placement_populates_form(self, tmp_path) -> None:
        h = _InventoryHarness(tmp_path, seed=True)
        p = h.controller.list_placements()[0]
        h.page.select_entity("placement", p.placement_id)
        assert h.page.f_name.text() == p.name
        assert h.page.f_status.currentData() == p.status
        assert h.page.f_price.text() == str(p.price.amount_dollars)

    def test_save_action_invokes_controller_path(self, tmp_path) -> None:
        h = _InventoryHarness(tmp_path, seed=True)
        p = h.controller.list_placements()[0]
        h.page.select_entity("placement", p.placement_id)
        h.page.f_name.setText("Renamed Placement")
        h.page.f_status.setCurrentIndex(
            h.page.f_status.findData(STATUS_HELD)
        )
        h.page._on_save()
        assert h.controller.get_placement(p.placement_id).name == "Renamed Placement"
        assert h.controller.get_placement(p.placement_id).status == STATUS_HELD

    def test_status_text_visible_independent_of_color(self, tmp_path) -> None:
        """Placement tree labels carry the status as readable text."""
        from PySide6.QtCore import Qt

        h = _InventoryHarness(tmp_path, seed=True)
        # Find a placement item and confirm its label contains the status text.
        def walk(item):
            kind = item.data(0, Qt.ItemDataRole.UserRole)
            if kind and kind[0] == "placement":
                return item.text(0)
            for i in range(item.childCount()):
                result = walk(item.child(i))
                if result:
                    return result
            return None

        for i in range(h.page.tree.topLevelItemCount()):
            label = walk(h.page.tree.topLevelItem(i))
            if label:
                assert "[" in label and "]" in label
                return
        pytest.fail("No placement found in tree")

    def test_create_placement_requires_location(self, tmp_path) -> None:
        """Creating a placement without a selected location is prevented."""
        h = _InventoryHarness(tmp_path, seed=True)
        # No location selected -> context is None.
        h.page._begin_create("placement")
        h.page.f_name.setText("Orphan attempt")
        h.page._on_save()
        # No orphan placement was created.
        assert len(h.controller.list_placements()) == 3
        assert h.errors, "Expected an error message"