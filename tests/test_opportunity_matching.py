"""Sprint 5C OpportunityService end-to-end matching tests.

Covers the service seam: locate prospect -> locate researched Project (via
metadata["prospect_id"]) -> load inventory -> evaluate all placements -> persist
(upsert, no duplicates) -> rank; the reverse (rank prospects for a placement);
recompute; and service independence (no GUI / web / scraper / LLM).
"""

from __future__ import annotations

import os

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


class OpportunityHarness:
    """Build real, persisted stores under ``tmp_path`` with a seeded prospect +
    researched project + King Soopers-like inventory."""

    def __init__(self, tmp_path):
        self.root = str(tmp_path)
        # --- prospect store ---
        self.ps = ProspectStore(path=os.path.join(self.root, "prospects.json"))
        self.ps.collection.prospects.append(
            Prospect(
                prospect_id="p_roof",
                company_name="Jim Woods Roofing",
                category="roofing",
                city="Castle Rock",
                state="CO",
                phone="605-764-9517",
                domain="jimwoodsroofing.com",
                market_id="m_dmv",
            )
        )
        self.ps.save()
        # --- researched project associated by metadata["prospect_id"] ---
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
        self.project_store = ProjectStore(root=os.path.join(self.root, "projects"))

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
        )
        self.pl_corral_a = Placement(
            placement_id="pl_corral_a",
            location_id=self.loc.location_id,
            name="Front Cart Corral A",
            status=STATUS_AVAILABLE,
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
            exclusive_category="Roofing",
            blocked_categories=["attorney"],
        )
        self.pl_cart_nose = Placement(
            placement_id="pl_cart_nose",
            location_id=self.loc.location_id,
            name="Cart Nose A",
            status=STATUS_AVAILABLE,
            price=Money.dollars(8000),
            price_period=PERIOD_YEAR,
        )
        self.pl_corral_b = Placement(
            placement_id="pl_corral_b",
            location_id=self.loc.location_id,
            name="Front Cart Corral B",
            status=STATUS_SOLD,  # hard-blocked
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
            exclusive_category="Realtor",
        )
        self.inv.create_inventory(
            [self.ret],
            [self.mkt],
            [self.loc],
            [self.pl_corral_a, self.pl_cart_nose, self.pl_corral_b],
        )

        # --- opportunity store + service ---
        self.oss = OpportunityStore(path=os.path.join(self.root, "opportunities.json"))
        self.svc = OpportunityService(
            prospect_store=self.ps,
            project_store=self.project_store,
            inventory_store=self.inv,
            opportunity_store=self.oss,
        )

    def rankings(self):
        return self.svc.rank_placements_for_prospect("p_roof")


class TestServiceMatching:
    def test_rank_placements_for_prospect(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        ranked = h.rankings()
        eligible = [o for o in ranked if o.eligible]
        # both AVAILABLE roofing-compatible placements ranked, desc
        assert len(eligible) == 2
        scores = [o.score for o in eligible]
        assert scores == sorted(scores, reverse=True)

    def test_sold_omitted_by_default(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        ranked = h.rankings()
        assert all(o.placement_id != "pl_corral_b" for o in ranked)

    def test_include_ineligible_optional(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        ranked = h.svc.rank_placements_for_prospect("p_roof", include_ineligible=True)
        ids = {o.placement_id for o in ranked}
        assert "pl_corral_b" in ids
        blocked = [o for o in ranked if o.placement_id == "pl_corral_b"][0]
        assert blocked.eligible is False
        assert blocked.score == 0
        assert any("SOLD" in r for r in blocked.eligibility_reasons)

    def test_recommend_persists_and_no_duplicates(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        h.svc.recommend_for_prospect("p_roof")
        first_count = len(h.oss.list())
        first_ids = {o.opportunity_id for o in h.oss.list()}
        h.svc.recommend_for_prospect("p_roof")  # rerun
        h.svc.recommend_for_prospect("p_roof")  # rerun again
        assert len(h.oss.list()) == first_count == 3
        assert {o.opportunity_id for o in h.oss.list()} == first_ids

    def test_persisted_project_id(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        h.svc.recommend_for_prospect("p_roof")
        for o in h.oss.list():
            assert o.project_id == h.project.id
class TestReverseRanking:
    def test_prospects_ranked_for_placement(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        # add a second prospect so the placement has >1 candidate
        h.ps.collection.prospects.append(
            Prospect(
                prospect_id="p_dental",
                company_name="Castle Rock Dental",
                category="dentist",
                city="Castle Rock",
                state="CO",
                phone="555-0001",
                domain="crdental.example",
                market_id="m_dmv",
            )
        )
        h.ps.save()
        ranked = h.svc.rank_prospects_for_placement("pl_corral_a")
        # Corral A is exclusive to Roofing -> only the roofing prospect eligible
        eligible = [o for o in ranked if o.eligible]
        assert {o.prospect_id for o in eligible} == {"p_roof"}

    def test_restrictions_respected(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        # SOLD placement -> no eligible prospects
        ranked = h.svc.rank_prospects_for_placement("pl_corral_b")
        assert all(not o.eligible for o in ranked) if ranked else True

    def test_reverse_deterministic(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        a = [o.prospect_id for o in h.svc.rank_prospects_for_placement("pl_cart_nose")]
        b = [o.prospect_id for o in h.svc.rank_prospects_for_placement("pl_cart_nose")]
        assert a == b


class TestProjectAssociation:
    def test_located_via_metadata_not_company(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        project = h.svc.locate_project("p_roof")
        assert project is not None
        assert project.metadata.get("prospect_id") == "p_roof"

    def test_missing_project_still_scores(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        # a prospect with NO researched project still gets an opportunity
        h.ps.collection.prospects.append(
            Prospect(
                prospect_id="p_oracle",
                company_name="Oracle Roofing",
                category="roofing",
                city="Denver",
                state="CO",
                phone="555-9999",
            )
        )
        h.ps.save()
        ranked = h.svc.rank_placements_for_prospect("p_oracle")
        eligible = [o for o in ranked if o.eligible]
        assert len(eligible) >= 1
        # reduced evidence: not hard-blocked, quality component is present
        assert all(0 <= o.score_components["prospect_quality"] for o in eligible)


class TestRecompute:
    def test_recompute_updates_and_no_duplicates(self, tmp_path):
        h = OpportunityHarness(tmp_path)
        h.svc.recommend_for_prospect("p_roof")
        before = {o.opportunity_id for o in h.oss.list()}
        before_scores = {o.placement_id: o.score for o in h.oss.list()}
        # change inventory: Cart Nose traffic rises
        h.pl_cart_nose.traffic_override = 40000
        h.inv.save()
        n = h.svc.recompute(prospect_id="p_roof")
        assert n == 3
        assert {o.opportunity_id for o in h.oss.list()} == before
        after = {o.placement_id: o.score for o in h.oss.list()}
        assert after["pl_cart_nose"] > before_scores["pl_cart_nose"]


class TestServiceIndependence:
    def _imports(self, mod):
        src = open(mod.__file__, encoding="utf-8").read()
        return [l for l in src.splitlines() if l.lstrip().startswith(("import ", "from "))]

    def test_no_gui_or_network_imports(self):
        import gui.services.opportunity_service as mod
        for line in self._imports(mod):
            assert "PySide6" not in line
            assert "PyQt" not in line
            assert "requests" not in line
            assert "playwright" not in line
            assert "openai" not in line
            assert "scraper" not in line

    def test_no_llm_or_scraper(self):
        import gui.services.opportunity_service as mod
        for line in self._imports(mod):
            assert "openai" not in line
            assert "anthropic" not in line
            assert "llm" not in line
            assert "scraper" not in line
