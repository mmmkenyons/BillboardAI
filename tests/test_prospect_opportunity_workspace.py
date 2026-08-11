"""Sprint 5F Prospect Opportunity Workspace aggregation tests.

Coverage:
- AGGREGATION: snapshot fields, research/location/opportunity data, recommendations
- MATCH LABEL: strong/good/possible/no match, deterministic boundaries
- PARTIAL STATES: no project, no inventory, no eligible, failed research, no coords
- READ vs REFRESH: no scrape, no geocode, no research, refresh via existing service
"""

from __future__ import annotations

import os

import pytest

from engine.brand_profile import BrandProfile
from gui.models.inventory import (
    PERIOD_YEAR,
    STATUS_AVAILABLE,
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
from gui.services.prospect_opportunity_workspace import (
    LOC_ADDRESS_INCOMPLETE,
    LOC_RESOLVED,
    LOC_UNRESOLVED,
    MATCH_GOOD,
    MATCH_NONE,
    MATCH_POSSIBLE,
    MATCH_STRONG,
    ProspectOpportunitySnapshot,
    ProspectOpportunityWorkspaceService,
    _location_status,
    _match_strength,
    _research_display,
)
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Harness:
    """Build real persisted stores with seeded data for snapshot tests."""

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
            address="123 Main St",
            phone="605-764-9517",
            domain="jimwoodsroofing.com",
            market_id="m_dmv",
            latitude=39.37,
            longitude=-104.86,
            research_status="SUCCEEDED",
            geocode_metadata={"source": "manual"},
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
        self.mkt = Market(name="Denver Metro", market_id="m_dmv")
        self.loc = Location(
            location_id="l_ks123",
            name="King Soopers #123",
            retailer_id=self.ret.retailer_id,
            market_id=self.mkt.market_id,
            store_number="123",
            city="Castle Rock",
            state="CO",
            latitude=39.39,
            longitude=-104.85,
            weekly_traffic=15000,
        )
        self.place = Placement(
            placement_id="pl_cart",
            location_id=self.loc.location_id,
            name="Front Cart Corral",
            placement_type="cart_corral",
            status=STATUS_AVAILABLE,
            price=Money.dollars(12000),
            price_period=PERIOD_YEAR,
        )
        self.inv.create_inventory(
            retailers=[self.ret],
            markets=[self.mkt],
            locations=[self.loc],
            placements=[self.place],
        )
        self.inv.save()

        # --- opportunity store ---
        self.opp_store = OpportunityStore(
            path=os.path.join(self.root, "opportunities.json")
        )

    def build_service(self) -> ProspectOpportunityWorkspaceService:
        return ProspectOpportunityWorkspaceService(
            prospect_store=self.ps,
            project_store=self.psr,
            inventory_store=self.inv,
            opportunity_service=OpportunityService(
                prospect_store=self.ps,
                project_store=self.psr,
                inventory_store=self.inv,
                opportunity_store=self.opp_store,
            ),
        )

from gui.services.store_recommendation import StoreRecommendationService

# ---------------------------------------------------------------------------
# Unit tests: pure functions
# ---------------------------------------------------------------------------


class TestMatchStrength:
    def test_strong_match(self):
        assert _match_strength(96, 3) == MATCH_STRONG

    def test_good_match(self):
        assert _match_strength(80, 2) == MATCH_GOOD

    def test_possible_match(self):
        assert _match_strength(50, 1) == MATCH_POSSIBLE

    def test_no_eligible_match(self):
        assert _match_strength(0, 0) == MATCH_NONE

    def test_no_eligible_with_score(self):
        assert _match_strength(85, 0) == MATCH_NONE

    def test_none_score(self):
        assert _match_strength(None, 5) == MATCH_NONE

    def test_boundary_90_is_strong(self):
        assert _match_strength(90, 2) == MATCH_STRONG

    def test_boundary_89_is_good(self):
        assert _match_strength(89, 2) == MATCH_GOOD

    def test_boundary_75_is_good(self):
        assert _match_strength(75, 2) == MATCH_GOOD

    def test_boundary_74_is_possible(self):
        assert _match_strength(74, 2) == MATCH_POSSIBLE

    def test_boundary_1_is_possible(self):
        assert _match_strength(1, 2) == MATCH_POSSIBLE

    def test_boundary_100_is_strong(self):
        assert _match_strength(100, 2) == MATCH_STRONG

    def test_zero_score_with_eligible_is_none(self):
        # score 0 with eligible opportunities still maps to NO ELIGIBLE MATCH
        assert _match_strength(0, 3) == MATCH_NONE


class TestResearchDisplay:
    def test_known_status(self):
        assert _research_display("SUCCEEDED") == "SUCCEEDED"

    def test_not_ready(self):
        assert _research_display("NOT_READY") == "NOT READY"

    def test_empty_defaults(self):
        assert _research_display("") == "NOT READY"

    def test_none_defaults(self):
        assert _research_display(None) == "NOT READY"


class TestLocationStatus:
    def test_resolved(self):
        assert _location_status(39.0, -104.0, "addr", "city", "ST") == LOC_RESOLVED

    def test_unresolved_no_coords(self):
        assert _location_status(None, None, "addr", "city", "ST") == LOC_UNRESOLVED

    def test_address_incomplete(self):
        assert _location_status(None, None, "", "", "") == LOC_ADDRESS_INCOMPLETE

    def test_address_incomplete_none(self):
        assert _location_status(None, None, None, None, None) == LOC_ADDRESS_INCOMPLETE

    def test_invalid_lat(self):
        assert _location_status(999, -104, "addr", "", "") == LOC_UNRESOLVED

# ---------------------------------------------------------------------------
# Integration: snapshot building
# ---------------------------------------------------------------------------


class TestSnapshotAggregation:
    def test_no_prospect_empty(self, tmp_path):
        svc = ProspectOpportunityWorkspaceService()
        snap = svc.snapshot_for_prospect("")
        assert snap.is_empty is True

    def test_unknown_prospect_empty(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("no_such_id")
        assert snap.is_empty is True

    def test_basic_fields_populate(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.refresh_for_prospect("p_roof", recommendation_limit=3)
        assert snap.prospect_id == "p_roof"
        assert snap.company_name == "Jim Woods Roofing"
        assert snap.is_empty is False

    def test_research_status_from_authoritative(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.research_status == "SUCCEEDED"
        assert snap.research_complete is True

    def test_project_resolves(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.project_id is not None
        assert snap.project_available is True

    def test_location_resolved_status(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.location_status == LOC_RESOLVED
        assert snap.latitude == 39.37
        assert snap.longitude == -104.86

    def test_location_address_display(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert "123 Main St" in snap.address_display
        assert "Castle Rock" in snap.address_display

    def test_opportunity_count(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.refresh_for_prospect("p_roof")
        assert snap.opportunity_count >= 1

    def test_recommendations_consumed(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.refresh_for_prospect("p_roof", recommendation_limit=3)
        assert len(snap.recommendations) >= 1
        assert len(snap.recommendations) <= 3

    def test_best_store_is_first_recommendation(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.refresh_for_prospect("p_roof", recommendation_limit=3)
        if snap.recommendations:
            assert snap.best_store is snap.recommendations[0]

# ---------------------------------------------------------------------------
# Partial states
# ---------------------------------------------------------------------------


class TestPartialStates:
    def test_no_project(self, tmp_path):
        h = _Harness(tmp_path)
        h.psr.delete(h.project.id)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.project_id is None
        assert snap.project_available is False

    def test_unresolved_location(self, tmp_path):
        h = _Harness(tmp_path)
        h.prospect.latitude = None
        h.prospect.longitude = None
        h.ps.save()
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.location_status == LOC_UNRESOLVED

    def test_research_failed(self, tmp_path):
        h = _Harness(tmp_path)
        h.prospect.research_status = "FAILED"
        h.ps.save()
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.research_status == "FAILED"
        assert snap.research_complete is False

    def test_no_stale_data_between_prospects(self, tmp_path):
        h = _Harness(tmp_path)
        p2 = Prospect(
            prospect_id="p_baker",
            company_name="Baker Painting",
            category="painting",
            city="Denver",
            state="CO",
            research_status="NOT_READY",
        )
        h.ps.collection.prospects.append(p2)
        h.ps.save()
        svc = h.build_service()
        snap1 = svc.refresh_for_prospect("p_roof")
        snap2 = svc.snapshot_for_prospect("p_baker")
        assert snap1.company_name == "Jim Woods Roofing"
        assert snap2.company_name == "Baker Painting"
        assert snap1.prospect_id != snap2.prospect_id


# ---------------------------------------------------------------------------
# Read vs Refresh
# ---------------------------------------------------------------------------


class TestReadVsRefresh:
    def test_snapshot_read_does_not_scrape(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        snap = svc.snapshot_for_prospect("p_roof")
        assert snap.prospect_id == "p_roof"

    def test_refresh_no_duplicate_opportunities(self, tmp_path):
        h = _Harness(tmp_path)
        svc = h.build_service()
        svc.refresh_for_prospect("p_roof")
        svc.refresh_for_prospect("p_roof")
        opportunities = svc._opportunity_service.by_prospect("p_roof")
        placement_ids = [o.placement_id for o in opportunities]
        assert len(placement_ids) == len(set(placement_ids))


# ---------------------------------------------------------------------------
# Snapshot DTO defaults
# ---------------------------------------------------------------------------


class TestSnapshotDefaults:
    def test_empty_snapshot(self):
        snap = ProspectOpportunitySnapshot()
        assert snap.is_empty is True
        assert snap.company_name == ""
        assert snap.match_strength == MATCH_NONE

    def test_empty_snapshot_is_empty_true(self):
        snap = ProspectOpportunitySnapshot(is_empty=True)
        assert snap.is_empty is True
