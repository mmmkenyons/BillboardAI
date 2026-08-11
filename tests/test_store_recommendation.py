"""Sprint 5D Store Recommendation tests.

Coverage:
- GROUPING: one/multiple placements per location, best selected, SOLD/ineligible excluded
- RANKING: score descending, tie-break, limit 3/5/arbitrary, empty
- DISTANCE: known preserved, missing None, nearest ranking
- DISPLAY DATA: retailer, market, location, store_number, traffic, price, reasons
- PROSPECT INTEGRATION: scoping, project resolution, refresh no-duplicates, no re-scrape
"""

from __future__ import annotations

import os

import pytest

from engine.brand_profile import BrandProfile
from gui.models.inventory import (
    PERIOD_YEAR,
    STATUS_AVAILABLE,
    STATUS_SOLD,
    Money,
    Location,
    Market,
    Placement,
    Retailer,
)
from gui.models.inventory_store import InventoryStore
from gui.models.opportunity_store import OpportunityStore
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_store import ProspectStore
from gui.services.opportunity_service import OpportunityService
from gui.services.store_recommendation import (
    RANK_BEST_MATCH,
    RANK_NEAREST,
    StoreRecommendation,
    StoreRecommendationService,
)


class StoreRecHarness:
    """Build real persisted stores with seeded inventory for recommendation tests."""

    def __init__(self, tmp_path):
        self.root = str(tmp_path)

        # --- prospect store ---
        self.ps = ProspectStore(path=os.path.join(self.root, "prospects.json"))
        self.prospect = Prospect(
            prospect_id="p_roof",
            company_name="Jim Woods Roofing",
            category="roofing",
            city="Castle Rock",
            state="CO",
            phone="605-764-9517",
            domain="jimwoodsroofing.com",
            market_id="m_dmv",
            metadata={"latitude": 39.37, "longitude": -104.86},
        )
        self.ps.collection.prospects.append(self.prospect)
        self.ps.save()

        # --- researched project ---
        self.psr = ProjectStore(root=os.path.join(self.root, "projects"))
        self.project = self.psr.create(company_name="Jim Woods Roofing")
        self.project.metadata["prospect_id"] = "p_roof"
        self.project.brand_profile = BrandProfile(
            categories=["roofing"],
            quality_score=92.0,
            vision_score=70.0,
            phone="605-764-9517",
            differentiators=["licensed"],
            trust_signals=["BBB A+"],
        ).to_dict()
        self.psr.save(self.project)

        # --- inventory ---
        self.inv = InventoryStore(path=os.path.join(self.root, "inventory.json"))
        self.ret = Retailer(name="King Soopers")
        self.mkt = Market(name="Denver Metro", state="CO")
        self.loc = Location(
            location_id="loc1",
            retailer_id=self.ret.retailer_id,
            market_id=self.mkt.market_id,
            name="King Soopers #123",
            store_number="123",
            city="Castle Rock",
            state="CO",
            weekly_traffic=15000,
            latitude=39.37, longitude=-104.86,
        )
        self.pl_corral_a = Placement(
            placement_id="pl_corral_a",
            location_id=self.loc.location_id,
            name="Front Cart Corral A",
            status=STATUS_AVAILABLE,
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
            exclusive_category="Roofing",
        )
        self.pl_cart_nose = Placement(
            placement_id="pl_cart_nose",
            location_id=self.loc.location_id,
            name="Cart Nose A",
            status=STATUS_AVAILABLE,
            price=Money.dollars(8500),
            price_period=PERIOD_YEAR,
            exclusive_category="Roofing",
        )
        self.pl_corral_b = Placement(
            placement_id="pl_corral_b",
            location_id=self.loc.location_id,
            name="Cart Corral B",
            status=STATUS_SOLD,
        )

        self.inv.create_inventory(
            retailers=[self.ret],
            markets=[self.mkt],
            locations=[self.loc],
            placements=[self.pl_corral_a, self.pl_cart_nose, self.pl_corral_b],
        )
        self.inv.save()

        # --- opportunity store ---
        self.oss = OpportunityStore(
            path=os.path.join(self.root, "opportunities.json")
        )

        # --- service ---
        self.opp_svc = OpportunityService(
            prospect_store=self.ps,
            project_store=self.psr,
            inventory_store=self.inv,
            opportunity_store=self.oss,
        )
        self.svc = StoreRecommendationService(
            opportunity_service=self.opp_svc,
            inventory_store=self.inv,
        )

    def seed_opportunities(self):
        """Generate opportunities for the harness prospect."""
        self.opp_svc.recommend_for_prospect("p_roof")

# ======================================================================
# GROUPING
# ======================================================================


class TestGrouping:

    def test_one_location_one_placement(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.pl_cart_nose.status = STATUS_SOLD
        h.pl_corral_b.status = STATUS_SOLD
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 1
        assert recs[0].location_id == "loc1"

    def test_one_location_multiple_placements(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.pl_corral_b.status = STATUS_SOLD
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 1

    def test_best_eligible_placement_selected(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        # Make Cart Nose's score lower by removing eligibility
        h.pl_cart_nose.exclusive_category = "Dentist"
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 1
        # Only Corral A (Roofing-exclusive) is eligible for roofing prospect
        assert recs[0].placement_id == "pl_corral_a"

    def test_sold_placement_not_selected(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.pl_corral_a.status = STATUS_SOLD
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 1
        assert recs[0].placement_id == "pl_cart_nose"

    def test_ineligible_placement_not_selected(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.pl_corral_a.exclusive_category = "Dentist"
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 1
        assert recs[0].placement_id == "pl_cart_nose"

    def test_two_locations_two_recommendations(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        loc2 = Location(
            location_id="loc2", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #456", store_number="456",
            city="Denver", state="CO", weekly_traffic=20000,
            latitude=39.74, longitude=-104.99,
        )
        pl2 = Placement(
            placement_id="pl_corral_2", location_id="loc2",
            name="Front Cart Corral", status=STATUS_AVAILABLE,
            price=Money.dollars(11000), price_period=PERIOD_YEAR,
            exclusive_category="Roofing",
        )
        h.inv.inventory.locations.append(loc2)
        h.inv.inventory.placements.append(pl2)
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=5)
        assert len(recs) == 2
        assert {r.location_id for r in recs} == {"loc1", "loc2"}

    def test_three_placements_same_store_one_rec(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        pl3 = Placement(
            placement_id="pl_corral_c", location_id="loc1",
            name="Cart Corral C", status=STATUS_AVAILABLE,
            price=Money.dollars(7000), price_period=PERIOD_YEAR,
            exclusive_category="Roofing",
        )
        h.inv.inventory.placements.append(pl3)
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=5)
        assert len(recs) == 1

# ======================================================================
# RANKING
# ======================================================================


class TestRanking:

    def _add_n_locations(self, h, n):
        for i in range(1, n + 1):
            lid = f"loc_extra_{i}"
            loc = Location(
                location_id=lid, retailer_id=h.ret.retailer_id,
                market_id=h.mkt.market_id,
                name=f"KS Extra #{i}", store_number=str(1000 + i),
                city="Denver", state="CO", weekly_traffic=10000 + i * 100,
            )
            pl = Placement(
                placement_id=f"pl_extra_{i}", location_id=lid,
                name="Cart Corral", status=STATUS_AVAILABLE,
                exclusive_category="Roofing",
            )
            h.inv.inventory.locations.append(loc)
            h.inv.inventory.placements.append(pl)
        h.inv.save()

    def test_higher_score_ranks_first(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        loc2 = Location(
            location_id="loc2", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #456", store_number="456",
            city="Denver", state="CO", weekly_traffic=5000,
            latitude=39.74, longitude=-104.99,
        )
        pl2 = Placement(
            placement_id="pl_denver", location_id="loc2",
            name="Front Cart Corral", status=STATUS_AVAILABLE,
            exclusive_category="Roofing",
        )
        h.inv.inventory.locations.append(loc2)
        h.inv.inventory.placements.append(pl2)
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=5)
        assert len(recs) == 2
        assert recs[0].score >= recs[1].score

    def test_deterministic_tie_break(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        loc_a = Location(
            location_id="loc_a", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #100", store_number="100",
            city="CityA", state="CO", weekly_traffic=15000,
        )
        pl_a = Placement(
            placement_id="pl_a", location_id="loc_a",
            name="Cart Corral", status=STATUS_AVAILABLE,
            exclusive_category="Roofing",
        )
        loc_b = Location(
            location_id="loc_b", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #200", store_number="200",
            city="CityB", state="CO", weekly_traffic=15000,
        )
        pl_b = Placement(
            placement_id="pl_b", location_id="loc_b",
            name="Cart Corral", status=STATUS_AVAILABLE,
            exclusive_category="Roofing",
        )
        h.inv.inventory.locations.extend([loc_a, loc_b])
        h.inv.inventory.placements.extend([pl_a, pl_b])
        h.inv.save()
        h.seed_opportunities()
        recs_a = h.svc.recommend("p_roof", limit=5)
        recs_b = h.svc.recommend("p_roof", limit=5)
        assert [r.location_id for r in recs_a] == [r.location_id for r in recs_b]

    def test_limit_3(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        self._add_n_locations(h, 5)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 3

    def test_limit_5(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        self._add_n_locations(h, 7)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=5)
        assert len(recs) == 5

    def test_arbitrary_limit(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        self._add_n_locations(h, 10)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=7)
        assert len(recs) == 7

    def test_no_eligible_empty(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.pl_corral_a.status = STATUS_SOLD
        h.pl_cart_nose.status = STATUS_SOLD
        h.pl_corral_b.status = STATUS_SOLD
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs == []

# ======================================================================
# DISTANCE
# ======================================================================


class TestDistance:

    def test_known_distance_preserved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) >= 1
        assert recs[0].distance_miles is not None

    def test_missing_distance_none(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.loc.latitude = None
        h.loc.longitude = None
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs) == 1
        assert recs[0].distance_miles is None

    def test_nearest_ranking_known_distances(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        loc2 = Location(
            location_id="loc2", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #456", store_number="456",
            city="Denver", state="CO", weekly_traffic=20000,
            latitude=39.74, longitude=-104.99,
        )
        pl2 = Placement(
            placement_id="pl_far", location_id="loc2",
            name="Cart Corral", status=STATUS_AVAILABLE,
            exclusive_category="Roofing",
        )
        h.inv.inventory.locations.append(loc2)
        h.inv.inventory.placements.append(pl2)
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=5, rank_mode=RANK_NEAREST)
        assert len(recs) == 2
        assert recs[0].distance_miles is not None
        assert recs[1].distance_miles is not None
        # loc1 should be nearer than loc2 (loc2 is Denver, further)
        assert recs[0].distance_miles < recs[1].distance_miles

    def test_nearest_unknowns_at_end(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        loc2 = Location(
            location_id="loc2", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #456", store_number="456",
            city="Denver", state="CO", weekly_traffic=20000,
            latitude=39.74, longitude=-104.99,
        )
        pl2 = Placement(
            placement_id="pl_far", location_id="loc2",
            name="Cart Corral", status=STATUS_AVAILABLE,
            exclusive_category="Roofing",
        )
        loc3 = Location(
            location_id="loc3", retailer_id=h.ret.retailer_id,
            market_id=h.mkt.market_id, name="KS #789", store_number="789",
            city="Boulder", state="CO", weekly_traffic=10000,
        )
        pl3 = Placement(
            placement_id="pl_boulder", location_id="loc3",
            name="Cart Corral", status=STATUS_AVAILABLE,
            exclusive_category="Roofing",
        )
        h.inv.inventory.locations.extend([loc2, loc3])
        h.inv.inventory.placements.extend([pl2, pl3])
        h.inv.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=5, rank_mode=RANK_NEAREST)
        # loc3 has no coords → at end
        last = recs[-1]
        assert last.location_id == "loc3" or last.distance_miles is None


# ======================================================================
# DISPLAY DATA
# ======================================================================


class TestDisplayData:

    def test_retailer_resolved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].retailer_name == "King Soopers"

    def test_market_resolved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].market_name == "Denver Metro"

    def test_location_resolved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].location_name == "King Soopers #123"
        assert recs[0].city == "Castle Rock"
        assert recs[0].state == "CO"

    def test_store_number_preserved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].store_number == "123"

    def test_traffic_uses_effective_traffic(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].weekly_traffic == 15000

    def test_price_uses_formatter(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert "$" in recs[0].price_display
        assert "/year" in recs[0].price_display

    def test_reasons_preserved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert len(recs[0].reasons) > 0

    def test_placement_data_resolved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].placement_name != ""
        assert recs[0].placement_id != ""

# ======================================================================
# PROSPECT INTEGRATION
# ======================================================================


class TestProspectIntegration:

    def test_scoped_to_selected_prospect(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.ps.collection.prospects.append(
            Prospect(
                prospect_id="p_dentist", company_name="Denver Dental",
                category="dentist", city="Denver", state="CO",
            )
        )
        h.ps.save()
        h.seed_opportunities()
        recs = h.svc.recommend("p_dentist", limit=3)
        # Dentist can't match Roofing-exclusive placements
        assert all(r.prospect_id == "p_dentist" or len(recs) == 0 for r in recs)

    def test_another_prospect_excluded(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.ps.collection.prospects.append(
            Prospect(
                prospect_id="p_oracle", company_name="Oracle Roofing",
                category="roofing", city="Denver", state="CO",
            )
        )
        h.ps.save()
        h.opp_svc.recommend_for_prospect("p_oracle")
        recs_jim = h.svc.recommend("p_roof", limit=3)
        recs_o = h.svc.recommend("p_oracle", limit=3)
        # Jim should only see his own
        assert all(r.prospect_id == "p_roof" for r in recs_jim)
        # Oracle should only see his own
        assert all(r.prospect_id == "p_oracle" for r in recs_o)

    def test_associated_project_resolved(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        recs = h.svc.recommend("p_roof", limit=3)
        assert recs[0].project_id == h.project.id

    def test_missing_project_handled(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.ps.collection.prospects.append(
            Prospect(
                prospect_id="p_orphan", company_name="Orphan Roofing",
                category="roofing", city="Denver", state="CO",
            )
        )
        h.ps.save()
        h.opp_svc.recommend_for_prospect("p_orphan")
        recs = h.svc.recommend("p_orphan", limit=3)
        assert len(recs) >= 1
        assert recs[0].project_id == ""

    def test_refresh_does_not_re_scrape(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        before_count = len(h.oss.list())
        recs = h.svc.recommend("p_roof", limit=3, refresh=True)
        after_count = len(h.oss.list())
        assert after_count == before_count

    def test_refresh_does_not_duplicate_opportunities(self, tmp_path):
        h = StoreRecHarness(tmp_path)
        h.seed_opportunities()
        before_ids = {o.opportunity_id for o in h.oss.list()}
        h.svc.recommend("p_roof", limit=3, refresh=True)
        after_ids = {o.opportunity_id for o in h.oss.list()}
        assert before_ids == after_ids


# ======================================================================
# SERVICE INDEPENDENCE
# ======================================================================


class TestServiceIndependence:

    def test_no_gui_imports(self):
        import gui.services.store_recommendation as mod
        src = open(mod.__file__, encoding="utf-8").read()
        for line in src.splitlines():
            if line.lstrip().startswith(("import ", "from ")):
                assert "PySide6" not in line
                assert "PyQt" not in line
                assert "QWidget" not in line

    def test_no_llm_or_scraper(self):
        import gui.services.store_recommendation as mod
        src = open(mod.__file__, encoding="utf-8").read()
        for line in src.splitlines():
            if line.lstrip().startswith(("import ", "from ")):
                assert "openai" not in line
                assert "anthropic" not in line
                assert "llm" not in line
                assert "scraper" not in line
                assert "playwright" not in line
                assert "requests" not in line
