"""Sprint 4A inventory test suite (models, pricing, traffic, status, category
rules, relationships, store, scene template, and independence).

Covers the receive criteria from the Sprint 4A brief. Filesystem tests use
``tmp_path`` and never touch the real ``output/inventory`` directory.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from gui.models.inventory import (
    DEFAULT_CURRENCY,
    PERIOD_MONTH,
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
    filesystem_safe_id,
)
from gui.models.inventory_store import (
    DEFAULT_INVENTORY_PATH,
    Inventory,
    InventoryCorruptionError,
    InventoryError,
    InventoryStore,
    SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _retailer(**kw) -> Retailer:
    base = dict(name="King Soopers", parent_company="Kroger")
    base.update(kw)
    return Retailer(**base)


def _market(**kw) -> Market:
    base = dict(name="Denver Metro", state="CO")
    base.update(kw)
    return Market(**base)


def _location(retailer_id: str = "", market_id: str = "", **kw) -> Location:
    base = dict(
        retailer_id=retailer_id,
        market_id=market_id,
        name="Castle Rock Location",
        store_number="123",
        city="Castle Rock",
        state="CO",
        postal_code="80104",
        weekly_traffic=15000,
    )
    base.update(kw)
    return Location(**base)


def _placement(location_id: str = "", **kw) -> Placement:
    base = dict(
        location_id=location_id,
        name="Front Cart Corral A",
        scene_template="cart_corral",
        status=STATUS_AVAILABLE,
        price=Money.dollars(12000),
        price_period=PERIOD_YEAR,
    )
    base.update(kw)
    return Placement(**base)
# ---------------------------------------------------------------------------
# MODELS
# ---------------------------------------------------------------------------


class TestModels:
    def test_retailer_construction(self) -> None:
        r = _retailer()
        assert r.name == "King Soopers"
        assert r.parent_company == "Kroger"
        assert r.retailer_id

    def test_market_construction(self) -> None:
        m = _market()
        assert m.name == "Denver Metro"
        assert m.state == "CO"

    def test_location_construction(self) -> None:
        loc = _location()
        assert loc.city == "Castle Rock"
        assert loc.weekly_traffic == 15000

    def test_placement_construction(self) -> None:
        p = _placement()
        assert p.name == "Front Cart Corral A"
        assert p.scene_template == "cart_corral"
        assert p.status == STATUS_AVAILABLE

    def test_unique_ids(self) -> None:
        ids = [filesystem_safe_id() for _ in range(200)]
        assert len(set(ids)) == len(ids)

    def test_filesystem_json_safe_ids(self) -> None:
        uid = filesystem_safe_id("placement")
        assert re.fullmatch(r"placement_[0-9a-f-]+", uid)
        # safe to use as a filename component
        assert os.path.basename(uid) == uid

    def test_serialization_round_trip(self) -> None:
        loc = _location()
        p = _placement(location_id=loc.location_id, exclusive_category=" roof ",
                       blocked_categories=["Dentist"])
        r = _retailer(); m = _market()
        inv = Inventory([r], [m], [loc], [p])
        restored = Inventory.from_dict(inv.to_dict())
        assert len(restored.retailers) == 1
        assert restored.retailers[0].name == "King Soopers"
        assert restored.placements[0].scene_template == "cart_corral"
        assert restored.placements[0].price.amount_cents == 1_200_000

    def test_unknown_fields_safe(self) -> None:
        data = {
            "retailer_id": "r1", "name": "X", "bogus_field": 123,
            "another_unknown": {"nested": True},
        }
        r = Retailer.from_dict(data)
        assert r.name == "X"
        assert r.retailer_id == "r1"

    def test_missing_optional_fields_safe(self) -> None:
        p = Placement.from_dict({"placement_id": "p1"})
        assert p.placement_id == "p1"
        assert p.price is None
        assert p.blocked_categories == []
        assert p.traffic_override is None
        assert p.status == STATUS_AVAILABLE


# ---------------------------------------------------------------------------
# PRICING
# ---------------------------------------------------------------------------


class TestPricing:
    def test_annual_price_persists(self) -> None:
        p = _placement(price=Money.dollars(12000), price_period=PERIOD_YEAR)
        restored = Placement.from_dict(p.to_dict())
        assert restored.price.amount_cents == 1_200_000
        assert restored.price_period == PERIOD_YEAR

    def test_monthly_price_persists(self) -> None:
        p = _placement(price=Money.dollars(1000), price_period=PERIOD_MONTH)
        restored = Placement.from_dict(p.to_dict())
        assert restored.price.amount_cents == 100_000
        assert restored.price_period == PERIOD_MONTH

    def test_setup_fee_persists(self) -> None:
        p = _placement(setup_fee=Money.dollars(500))
        restored = Placement.from_dict(p.to_dict())
        assert restored.setup_fee.amount_cents == 50_000

    def test_money_precision_safe(self) -> None:
        # 0.1 + 0.2 dollars must be exactly 30 cents, not 29.9999...
        total = Money.dollars(0.1).amount_cents + Money.dollars(0.2).amount_cents
        assert total == 30

    def test_money_dollar_conversion(self) -> None:
        assert Money.dollars(12_000).amount_cents == 1_200_000
        assert Money.cents(1_200_000).amount_dollars == 12000.0

    def test_money_format(self) -> None:
        assert Money.cents(1_200_000).format() == "$12,000"
        assert Money.cents(1_200_050).format() == "$12,000.50"

    def test_money_round_trip_via_dict(self) -> None:
        m = Money.dollars(1234.56)
        assert Money.from_dict(m.to_dict()) == m

    def test_money_from_dict_none(self) -> None:
        assert Money.from_dict(None) is None

    def test_money_currency(self) -> None:
        m = Money.cents(100, "USD")
        assert m.currency == DEFAULT_CURRENCY
        assert m.to_dict()["currency"] == "USD"


# ---------------------------------------------------------------------------
# TRAFFIC
# ---------------------------------------------------------------------------


class TestTraffic:
    def test_location_weekly_traffic(self) -> None:
        loc = _location(weekly_traffic=15000)
        assert loc.weekly_traffic == 15000

    def test_placement_traffic_override(self) -> None:
        loc = _location(weekly_traffic=15000)
        p = _placement(location_id=loc.location_id, traffic_override=20000)
        assert p.effective_weekly_traffic(loc) == 20000

    def test_placement_inherits_location_traffic(self) -> None:
        loc = _location(weekly_traffic=15000)
        p = _placement(location_id=loc.location_id)
        assert p.effective_weekly_traffic(loc) == 15000

    def test_missing_traffic_safe(self) -> None:
        p = _placement()
        assert p.effective_weekly_traffic() is None
        assert p.effective_weekly_traffic(None) is None

    def test_traffic_override_persists(self) -> None:
        p = _placement(traffic_override=18000)
        assert Placement.from_dict(p.to_dict()).traffic_override == 18000
# ---------------------------------------------------------------------------
# STATUS
# ---------------------------------------------------------------------------


class TestStatus:
    def test_available_placement(self) -> None:
        p = _placement(status=STATUS_AVAILABLE)
        assert p.is_available_for("Roofing")

    def test_sold_placement(self) -> None:
        p = _placement(status=STATUS_SOLD)
        assert p.is_available_for("Roofing") is False

    def test_held_placement(self) -> None:
        p = _placement(status=STATUS_HELD)
        assert p.is_available_for("Roofing") is False

    def test_archived_placement(self) -> None:
        p = _placement(status=STATUS_ARCHIVED)
        assert p.is_available_for("Roofing") is False

    def test_all_statuses_controlled(self) -> None:
        from gui.models.inventory import (
            PLACEMENT_STATUSES,
            STATUS_MAINTENANCE,
            STATUS_UNAVAILABLE,
        )
        assert PLACEMENT_STATUSES == (
            STATUS_AVAILABLE, STATUS_HELD, STATUS_SOLD,
            STATUS_UNAVAILABLE, STATUS_MAINTENANCE, STATUS_ARCHIVED,
        )

    def test_invalid_status_defaults_to_available(self) -> None:
        p = Placement.from_dict({"status": "NOPE"})
        assert p.status == STATUS_AVAILABLE


# ---------------------------------------------------------------------------
# CATEGORY RULES
# ---------------------------------------------------------------------------


class TestCategoryRules:
    def test_available_category_accepted(self) -> None:
        p = _placement()
        assert p.is_available_for("Roofing") is True

    def test_blocked_category_rejected(self) -> None:
        p = _placement(blocked_categories=["Dentist"])
        assert p.is_available_for("Dentist") is False
        assert p.is_available_for("Roofing") is True

    def test_sold_exclusive_category_rejected_where_appropriate(self) -> None:
        # exclusive means only that category may use the placement
        p = _placement(exclusive_category="Roofing")
        assert p.is_available_for("Roofing") is True
        assert p.is_available_for("Dentist") is False

    def test_sold_status_with_exclusive(self) -> None:
        p = _placement(status=STATUS_SOLD, exclusive_category="Roofing")
        assert p.is_available_for("Roofing") is False

    def test_case_normalization(self) -> None:
        p = _placement(exclusive_category="Roofing", blocked_categories=["DENTIST"])
        assert p.is_available_for("roofing") is True
        assert p.is_available_for("ROOFING") is True
        assert p.is_available_for("dentist") is False

    def test_whitespace_normalization(self) -> None:
        p = _placement(exclusive_category="  Roofing ")
        assert p.is_available_for("  roofing  ") is True

    def test_no_category_restriction_behaves_correctly(self) -> None:
        p = _placement()
        assert p.is_available_for("Anything") is True

    def test_empty_category_rejected(self) -> None:
        p = _placement()
        assert p.is_available_for("") is False
        assert p.is_available_for("   ") is False

    def test_blocked_wins_over_exclusive(self) -> None:
        p = _placement(exclusive_category="Roofing", blocked_categories=["Roofing"])
        assert p.is_available_for("Roofing") is False


# ---------------------------------------------------------------------------
# RELATIONSHIPS
# ---------------------------------------------------------------------------


class TestRelationships:
    def test_placement_links_to_location(self) -> None:
        loc = _location(); p = _placement(location_id=loc.location_id)
        assert p.location_id == loc.location_id

    def test_location_links_to_retailer(self) -> None:
        r = _retailer(); loc = _location(retailer_id=r.retailer_id)
        assert loc.retailer_id == r.retailer_id

    def test_location_links_to_market(self) -> None:
        m = _market(); loc = _location(market_id=m.market_id)
        assert loc.market_id == m.market_id

    def test_multiple_placements_per_location(self) -> None:
        loc = _location()
        inv = Inventory([], [], [loc], [
            _placement(location_id=loc.location_id, name="A"),
            _placement(location_id=loc.location_id, name="B"),
        ])
        assert len(inv.placements_by_location(loc.location_id)) == 2

    def test_same_scene_template_across_multiple_placements(self) -> None:
        p1 = _placement(scene_template="cart_corral")
        p2 = _placement(scene_template="cart_corral")
        assert p1.scene_template == p2.scene_template == "cart_corral"
# ---------------------------------------------------------------------------
# STORE
# ---------------------------------------------------------------------------


class TestStore:
    def test_create_save_inventory(self, tmp_path) -> None:
        store = InventoryStore(tmp_path / "inv.json")
        store.create_inventory([_retailer()], [_market()], [_location()], [_placement()])
        store.save()
        assert (tmp_path / "inv.json").exists()

    def test_load_inventory(self, tmp_path) -> None:
        path = tmp_path / "inv.json"
        s1 = InventoryStore(path)
        s1.create_inventory([_retailer()], [], [], [_placement()])
        s1.save()
        s2 = InventoryStore(path)
        inv = s2.load()
        assert len(inv.retailers) == 1
        assert len(inv.placements) == 1

    def test_atomic_save(self, tmp_path) -> None:
        path = tmp_path / "inv.json"
        s = InventoryStore(path)
        s.create_inventory([], [], [], [])
        s.save()
        # No stray temp files left behind
        assert not (tmp_path / "inv.json.tmp").exists()

    def test_corrupted_json_fails_clearly(self, tmp_path) -> None:
        path = tmp_path / "inv.json"
        path.write_text("{not valid json!!", encoding="utf-8")
        s = InventoryStore(path)
        with pytest.raises(InventoryCorruptionError):
            s.load()

    def test_missing_file_handled(self, tmp_path) -> None:
        s = InventoryStore(tmp_path / "nope.json")
        assert s.exists() is False
        with pytest.raises(FileNotFoundError):
            s.load()

    def test_schema_version_persists(self, tmp_path) -> None:
        path = tmp_path / "inv.json"
        s = InventoryStore(path)
        s.create_inventory([])
        s.save()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["schema_version"] == SCHEMA_VERSION
        assert s.load().schema_version == SCHEMA_VERSION

    def test_list_retailers(self, tmp_path) -> None:
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([_retailer(name="B"), _retailer(name="A")])
        names = {r.name for r in s.list_retailers()}
        assert names == {"A", "B"}
        # deterministic ordering is by retailer_id
        ids = [r.retailer_id for r in s.list_retailers()]
        assert ids == sorted(ids)

    def test_list_markets_locations_placements(self, tmp_path) -> None:
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([], [_market()], [_location()], [_placement()])
        assert len(s.list_markets()) == 1
        assert len(s.list_locations()) == 1
        assert len(s.list_placements()) == 1

    def test_filter_by_status(self, tmp_path) -> None:
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([], [], [], [
            _placement(status=STATUS_AVAILABLE, name="A"),
            _placement(status=STATUS_SOLD, name="B"),
        ])
        assert {p.name for p in s.placements_by_status(STATUS_AVAILABLE)} == {"A"}

    def test_filter_by_market(self, tmp_path) -> None:
        m1 = _market(name="Denver Metro")
        m2 = _market(name="Colorado Springs")
        loc1 = _location(market_id=m1.market_id)
        loc2 = _location(market_id=m2.market_id)
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([], [m1, m2], [loc1, loc2], [
            _placement(location_id=loc1.location_id, name="A"),
            _placement(location_id=loc2.location_id, name="B"),
        ])
        assert {p.name for p in s.placements_by_market(m1.market_id)} == {"A"}

    def test_filter_by_retailer(self, tmp_path) -> None:
        r1 = _retailer(name="King Soopers")
        r2 = _retailer(name="City Market")
        loc1 = _location(retailer_id=r1.retailer_id)
        loc2 = _location(retailer_id=r2.retailer_id)
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([r1, r2], [], [loc1, loc2], [
            _placement(location_id=loc1.location_id, name="A"),
            _placement(location_id=loc2.location_id, name="B"),
        ])
        assert {p.name for p in s.placements_by_retailer(r1.retailer_id)} == {"A"}

    def test_filter_by_location(self, tmp_path) -> None:
        loc1 = _location(); loc2 = _location()
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([], [], [loc1, loc2], [
            _placement(location_id=loc1.location_id, name="A"),
            _placement(location_id=loc2.location_id, name="B"),
        ])
        assert {p.name for p in s.placements_by_location(loc1.location_id)} == {"A"}

    def test_deterministic_ordering(self, tmp_path) -> None:
        s = InventoryStore(tmp_path / "inv.json")
        inv = Inventory(placements=[_placement(name="Z"), _placement(name="A")])
        s.set_inventory(inv)
        ids = [p.placement_id for p in s.list_placements()]
        assert ids == sorted(ids)

    def test_unknown_fields_safe_in_store(self, tmp_path) -> None:
        path = tmp_path / "inv.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "future_field": "ignored",
            "retailers": [{"name": "X", "unknown": 1}],
        }), encoding="utf-8")
        inv = InventoryStore(path).load()
        assert inv.retailers[0].name == "X"


# ---------------------------------------------------------------------------
# SCENE TEMPLATE
# ---------------------------------------------------------------------------


class TestSceneTemplate:
    def test_placement_stores_scene_template(self) -> None:
        p = _placement(scene_template="cart_nose")
        assert Placement.from_dict(p.to_dict()).scene_template == "cart_nose"

    def test_no_hardcoded_scene_template_branches(self) -> None:
        # The model must not branch on specific template ids. Verify the source
        # file contains no reference to the known MVP template names.
        src_path = os.path.join(
            os.path.dirname(__file__), "..", "gui", "models", "inventory.py"
        )
        src = open(src_path, encoding="utf-8").read()
        assert "cart_corral" not in src
        assert "cart_nose" not in src

    def test_advisory_scene_validation(self) -> None:
        p = _placement(scene_template="cart_corral")
        assert p.is_valid_scene_template({"cart_corral", "cart_nose"}) is True
        assert p.is_valid_scene_template({"cart_nose"}) is False
        assert p.is_valid_scene_template(set()) is False

    def test_load_does_not_fail_for_missing_scene(self, tmp_path) -> None:
        # Inventory loading must not fail just because a scene asset is missing.
        p = _placement(scene_template="does_not_exist_yet")
        s = InventoryStore(tmp_path / "inv.json")
        s.create_inventory([], [], [], [p])
        s.save()
        loaded = InventoryStore(tmp_path / "inv.json").load()
        assert loaded.placements[0].scene_template == "does_not_exist_yet"


# ---------------------------------------------------------------------------
# INDEPENDENCE
# ---------------------------------------------------------------------------


class TestIndependence:
    def test_models_do_not_import_gui_widgets(self) -> None:
        import gui.models.inventory as inv
        import gui.models.inventory_store as store_mod
        for mod in (inv, store_mod):
            src = open(mod.__file__, encoding="utf-8").read()
            assert "PySide6" not in src
            assert "gui.services" not in src
            assert "gui.views" not in src
            assert "gui.widgets" not in src

    def test_models_do_not_depend_on_brand_profile(self) -> None:
        import gui.models.inventory as inv
        import gui.models.inventory_store as store_mod
        for mod in (inv, store_mod):
            src = open(mod.__file__, encoding="utf-8").read()
            assert "brand_profile" not in src

    def test_models_do_not_depend_on_rendering_internals(self) -> None:
        import gui.models.inventory as inv
        import gui.models.inventory_store as store_mod
        for mod in (inv, store_mod):
            src = open(mod.__file__, encoding="utf-8").read()
            assert "engine.renderer" not in src
            assert "engine.layout" not in src


# ---------------------------------------------------------------------------
# ADVERSARIAL / EDGE
# ---------------------------------------------------------------------------


class TestAdversarial:
    def test_from_dict_non_dict_safe(self) -> None:
        assert Retailer.from_dict(None).name == ""
        assert Market.from_dict("oops").name == ""
        assert Location.from_dict([]).name == ""
        assert Placement.from_dict(42).name == ""

    def test_inventory_from_dict_non_dict_raises(self) -> None:
        with pytest.raises(InventoryError):
            Inventory.from_dict("not-a-dict")

    def test_bad_price_dict_safe(self) -> None:
        p = Placement.from_dict({"price": {"amount_cents": "not-a-number"}})
        assert p.price.amount_cents == 0

    def test_bad_traffic_safe(self) -> None:
        p = Placement.from_dict({"traffic_override": "garbage"})
        assert p.traffic_override is None

    def test_default_inventory_path_is_git_ignored(self) -> None:
        rel = os.path.relpath(DEFAULT_INVENTORY_PATH)
        assert rel.startswith("output" + os.sep)

    def test_no_pickle_usage(self) -> None:
        import gui.models.inventory_store as store_mod
        src = open(store_mod.__file__, encoding="utf-8").read()
        assert "pickle" not in src
        assert "dill" not in src