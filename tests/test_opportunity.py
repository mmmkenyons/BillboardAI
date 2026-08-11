"""Sprint 5C opportunity model + engine tests (Qt-free).

Covers the Opportunity model, eligibility hard-blockers, deterministic category
matching, Haversine distance, market/location fit, traffic bands, prospect
quality, scoring, reasons, ranking, and engine independence. All tests use the
real models (Prospect / Placement / Location / BrandProfile) and the real
``OpportunityEngine``; no GUI and no network.
"""

from __future__ import annotations

import math

import pytest

from engine.brand_profile import BrandProfile
from gui.models.inventory import (
    PERIOD_YEAR,
    STATUS_ARCHIVED,
    STATUS_AVAILABLE,
    STATUS_HELD,
    STATUS_SOLD,
    Money,
    Location,
    Placement,
)
from gui.models.prospect import Prospect

from engine.opportunity import (
    CATEGORY_WEIGHT,
    MARKET_WEIGHT,
    TRAFFIC_WEIGHT,
    QUALITY_WEIGHT,
    COMMERCIAL_WEIGHT,
    STATUS_NEW,
    STATUS_RECOMMENDED,
    STATUS_SELECTED,
    Opportunity,
    OpportunityEngine,
    canonical_category,
    category_forms,
    haversine_miles,
    rank_opportunities,
)

ENGINE = OpportunityEngine()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_prospect(
    category: str = "roofing",
    subcategory: str = "",
    city: str = "Castle Rock",
    state: str = "CO",
    market_id: str = "",
    phone: str = "555-0100",
    domain: str = "roofco.example",
    metadata: dict | None = None,
    prospect_id: str = "p1",
) -> Prospect:
    return Prospect(
        prospect_id=prospect_id,
        company_name="Roof Co",
        category=category,
        subcategory=subcategory,
        city=city,
        state=state,
        market_id=market_id,
        phone=phone,
        domain=domain,
        metadata=metadata or {},
    )


def make_location(
    city: str = "Castle Rock",
    state: str = "CO",
    market_id: str = "",
    weekly_traffic: int | None = 15000,
    lat: float | None = None,
    lng: float | None = None,
    location_id: str = "loc1",
) -> Location:
    return Location(
        location_id=location_id,
        market_id=market_id,
        name="King Soopers #123",
        city=city,
        state=state,
        weekly_traffic=weekly_traffic,
        latitude=lat,
        longitude=lng,
    )


def make_placement(
    status: str = STATUS_AVAILABLE,
    exclusive: str = "",
    blocked: tuple = (),
    price: Money | None = Money.dollars(12000),
    traffic_override: int | None = None,
    placement_id: str = "pl1",
    location_id: str = "loc1",
) -> Placement:
    return Placement(
        placement_id=placement_id,
        location_id=location_id,
        name=f"Placement {placement_id}",
        status=status,
        price=price,
        price_period=PERIOD_YEAR,
        exclusive_category=exclusive,
        blocked_categories=list(blocked),
        traffic_override=traffic_override,
    )


def make_bp(
    categories: tuple = ("roofing",),
    quality: float = 90.0,
    vision: float = 70.0,
    phone: str = "555-0199",
    differentiators: tuple = ("licensed",),
    trust: tuple = (),
) -> BrandProfile:
    return BrandProfile(
        categories=list(categories),
        quality_score=quality,
        vision_score=vision,
        phone=phone,
        differentiators=list(differentiators),
        trust_signals=list(trust),
        services=["roofing"],
    )


# ---------------------------------------------------------------------------
# MODEL
# ---------------------------------------------------------------------------


class TestModel:
    def test_minimal_opportunity(self):
        o = Opportunity()
        assert o.prospect_id == ""
        assert o.placement_id == ""
        assert o.eligible is False
        assert o.score == 0
        assert o.score_components == {}
        assert o.status == STATUS_NEW

    def test_unique_id(self):
        assert Opportunity().opportunity_id != Opportunity().opportunity_id

    def test_serialization_round_trip(self):
        o = Opportunity(
            prospect_id="p1",
            placement_id="pl1",
            eligible=True,
            score=96,
            score_components={"category_fit": 35, "market_fit": 20},
            reasons=["Roofing category allowed"],
            status=STATUS_RECOMMENDED,
            distance_miles=12.5,
            distance_source="haversine",
            project_id="prj1",
            location_id="loc1",
            market_id="m1",
        )
        assert Opportunity.from_dict(o.to_dict()).to_dict() == o.to_dict()

    def test_unknown_fields_safe(self):
        o = Opportunity(prospect_id="p1", eligible=True, score=10)
        d = o.to_dict()
        d["totally_new_field"] = {"nested": 1}
        assert Opportunity.from_dict(d).to_dict() == o.to_dict()

    def test_missing_optional_fields_safe(self):
        o = Opportunity.from_dict({})
        assert o.eligible is False
        assert o.score == 0
        assert o.score_components == {}
        assert o.distance_miles is None
        assert o.status == STATUS_NEW

    def test_status_validation(self):
        o = Opportunity.from_dict({"status": "NOT_A_STATUS"})
        assert o.status == STATUS_NEW

    def test_score_persists(self):
        o = Opportunity(score=77)
        assert Opportunity.from_dict(o.to_dict()).score == 77

    def test_score_components_persist(self):
        o = Opportunity(score_components={"category_fit": 35, "traffic": 12})
        assert Opportunity.from_dict(o.to_dict()).score_components == o.score_components

    def test_reasons_persist(self):
        o = Opportunity(reasons=["Roofing category allowed", "Same city as placement"])
        assert Opportunity.from_dict(o.to_dict()).reasons == o.reasons
# ---------------------------------------------------------------------------
# ELIGIBILITY
# ---------------------------------------------------------------------------


class TestEligibility:
    def test_available_eligible(self):
        op = ENGINE.evaluate(make_prospect(), make_placement(), make_location())
        assert op.eligible is True

    def test_sold_blocked(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(status=STATUS_SOLD), make_location()
        )
        assert op.eligible is False
        assert op.score == 0
        assert "SOLD" in op.eligibility_reasons[0]

    def test_held_blocked(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(status=STATUS_HELD), make_location()
        )
        assert op.eligible is False

    def test_archived_blocked(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(status=STATUS_ARCHIVED), make_location()
        )
        assert op.eligible is False

    def test_blocked_category_rejected(self):
        op = ENGINE.evaluate(
            make_prospect(category="attorney"),
            make_placement(blocked=("attorney",)),
            make_location(),
        )
        assert op.eligible is False
        assert any("category blocked" in r for r in op.eligibility_reasons)

    def test_exclusivity_mismatch_rejected(self):
        op = ENGINE.evaluate(
            make_prospect(category="roofing"),
            make_placement(exclusive="Realtor"),
            make_location(),
        )
        assert op.eligible is False
        assert any("already exclusive" in r for r in op.eligibility_reasons)

    def test_exclusivity_match_accepted(self):
        op = ENGINE.evaluate(
            make_prospect(category="roofing"),
            make_placement(exclusive="Roofing"),
            make_location(),
        )
        assert op.eligible is True

    def test_no_restrictions_accepted(self):
        op = ENGINE.evaluate(
            make_prospect(category="plumbing"),
            make_placement(exclusive="", blocked=()),
            make_location(),
        )
        assert op.eligible is True


# ---------------------------------------------------------------------------
# CATEGORY
# ---------------------------------------------------------------------------


class TestCategory:
    def test_brand_profile_category_used_first(self):
        # BP says roofing; prospect.category says attorney -> BP wins.
        op = ENGINE.evaluate(
            make_prospect(category="attorney"),
            make_placement(blocked=("attorney",)),
            make_location(),
            brand_profile=make_bp(categories=("roofing",)),
        )
        assert op.eligible is True
        assert op.recommended_category == "roofing"
        assert op.score_components["category_fit"] == CATEGORY_WEIGHT

    def test_prospect_category_fallback(self):
        op = ENGINE.evaluate(
            make_prospect(category="roofing"),
            make_placement(),
            make_location(),
            brand_profile=None,
        )
        assert op.eligible is True
        assert op.recommended_category == "roofing"
        assert op.score_components["category_fit"] == 28  # fallback (not researched)

    def test_normalization_case_whitespace(self):
        assert canonical_category("  Roofing  ") == "roofing"
        op = ENGINE.evaluate(
            make_prospect(category="  Roofing "),
            make_placement(exclusive="roofing"),
            make_location(),
        )
        assert op.eligible is True

    def test_small_synonym_mapping(self):
        # "real estate" prospect must match a placement exclusive to "Realtor".
        assert canonical_category("realtor") == "real estate"
        assert "realtor" in category_forms("real estate")
        op = ENGINE.evaluate(
            make_prospect(category="real estate"),
            make_placement(exclusive="Realtor"),
            make_location(),
        )
        assert op.eligible is True
        assert op.recommended_category == "real estate"

    def test_unsupported_category_not_invented(self):
        # Placement exclusive to Realtor; prospect is plumbing -> not eligible and
        # we do NOT fabricate a category to force eligibility.
        op = ENGINE.evaluate(
            make_prospect(category="plumbing"),
            make_placement(exclusive="Realtor"),
            make_location(),
        )
        assert op.eligible is False
        assert op.recommended_category == ""
# ---------------------------------------------------------------------------
# DISTANCE
# ---------------------------------------------------------------------------


class TestDistance:
    def test_haversine_known_points(self):
        # King Soopers Castle Rock ~ 39.3743, -104.8594
        # approx 1.0 mile apart
        d = haversine_miles(39.38, -104.86, 39.37, -104.87)
        assert 0.5 < d < 2.0

    def test_missing_prospect_coords_none(self):
        op = ENGINE.evaluate(
            make_prospect(metadata={}),
            make_placement(),
            make_location(lat=39.37, lng=-104.87),
        )
        assert op.distance_miles is None

    def test_missing_location_coords_none(self):
        op = ENGINE.evaluate(
            make_prospect(metadata={"latitude": 39.38, "longitude": -104.86}),
            make_placement(),
            make_location(lat=None, lng=None),
        )
        assert op.distance_miles is None

    def test_same_coordinates_zero(self):
        op = ENGINE.evaluate(
            make_prospect(metadata={"latitude": 39.37, "longitude": -104.87}),
            make_placement(),
            make_location(lat=39.37, lng=-104.87),
        )
        assert op.distance_miles is not None
        assert op.distance_miles < 0.1

    def test_distance_source_haversine(self):
        op = ENGINE.evaluate(
            make_prospect(metadata={"latitude": 39.38, "longitude": -104.86}),
            make_placement(),
            make_location(lat=39.37, lng=-104.87),
        )
        assert op.distance_source == "haversine"


# ---------------------------------------------------------------------------
# MARKET FIT
# ---------------------------------------------------------------------------


class TestMarketFit:
    def test_same_city_state_bonus(self):
        op = ENGINE.evaluate(
            make_prospect(city="Castle Rock", state="CO"),
            make_placement(),
            make_location(city="Castle Rock", state="CO"),
        )
        assert op.score_components["market_fit"] == MARKET_WEIGHT
        assert any("Same city as placement" in r for r in op.reasons)

    def test_same_market_bonus(self):
        op = ENGINE.evaluate(
            make_prospect(city="Denver", state="CO", market_id="m_dmv"),
            make_placement(),
            make_location(city="Aurora", state="CO", market_id="m_dmv"),
        )
        assert op.score_components["market_fit"] == 18

    def test_same_state_only_not_overvalued(self):
        op = ENGINE.evaluate(
            make_prospect(city="Fort Collins", state="CO"),
            make_placement(),
            make_location(city="Denver", state="CO"),
        )
        # CO/CO -> small bonus, NOT full weight
        assert op.score_components["market_fit"] == 5
        assert any("Same state only" in r for r in op.reasons)

    def test_distance_bonus_when_coords_exist(self):
        # Prospect coords very close to location coords
        op = ENGINE.evaluate(
            make_prospect(
                metadata={"latitude": 39.3743, "longitude": -104.8594},
                city="Castle Rock",
                state="CO",
            ),
            make_placement(),
            make_location(
                city="Castle Rock", state="CO",
                lat=39.3743, lng=-104.8594,
            ),
        )
        # Distance ~ 0 -> near max market bonus
        assert op.score_components["market_fit"] >= 15
        assert "miles from placement" in " ".join(op.reasons)

    def test_no_geographic_evidence(self):
        op = ENGINE.evaluate(
            make_prospect(city="", state="", market_id=""),
            make_placement(),
            make_location(city="", state="", market_id=""),
        )
        assert op.score_components["market_fit"] == 0
        assert any("No geographic" in r for r in op.reasons)


# ---------------------------------------------------------------------------
# TRAFFIC
# ---------------------------------------------------------------------------


class TestTraffic:
    def test_inherited_location_traffic(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(),
            make_location(weekly_traffic=15000),
        )
        assert op.score_components["traffic"] == 12

    def test_placement_override_traffic(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(traffic_override=25000),
            make_location(weekly_traffic=15000),
        )
        assert op.score_components["traffic"] == TRAFFIC_WEIGHT

    def test_missing_traffic_neutral(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(),
            make_location(weekly_traffic=None),
        )
        assert op.score_components["traffic"] == 0

    def test_traffic_bands_deterministic(self):
        bands = [
            (100, 5), (4999, 5), (5000, 8), (9999, 8),
            (10000, 12), (19999, 12), (20000, 15), (99999, 15),
        ]
        for raw, expected in bands:
            loc = make_location(weekly_traffic=raw)
            p = make_prospect()
            op = ENGINE.evaluate(p, make_placement(), loc)
            assert op.score_components["traffic"] == expected, f"traffic={raw}"
# ---------------------------------------------------------------------------
# PROSPECT QUALITY
# ---------------------------------------------------------------------------


class TestProspectQuality:
    def test_researched_project_bonus(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(), make_location(),
            brand_profile=make_bp(),
        )
        assert op.score_components["prospect_quality"] >= QUALITY_WEIGHT * 0.3
        assert any("Researched business profile" in r for r in op.reasons)

    def test_brand_profile_quality_contributes(self):
        high = ENGINE.evaluate(
            make_prospect(), make_placement(), make_location(),
            brand_profile=make_bp(quality=95, vision=85),
        )
        low = ENGINE.evaluate(
            make_prospect(), make_placement(), make_location(),
            brand_profile=make_bp(quality=10, vision=5),
        )
        assert high.score_components["prospect_quality"] > low.score_components["prospect_quality"]

    def test_missing_project_handled_safely(self):
        op = ENGINE.evaluate(
            make_prospect(phone="555-0100", domain="roof.example"),
            make_placement(),
            make_location(),
            brand_profile=None,
        )
        assert op.eligible is True  # not hard-blocked without research
        # still gets contact/website evidence
        assert op.score_components["prospect_quality"] >= 3

    def test_sparse_profile_not_hard_blocked(self):
        op = ENGINE.evaluate(
            make_prospect(category="roofing", phone="", domain=""),
            make_placement(),
            make_location(),
            brand_profile=None,
        )
        assert op.eligible is True
        # low quality is fine; never a hard blocker
        assert 0 <= op.score_components["prospect_quality"] <= QUALITY_WEIGHT


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------


def _happy(brand_profile=None, **kw):
    return ENGINE.evaluate(
        make_prospect(**kw),
        make_placement(**{k: v for k, v in kw.items() if k == "traffic_override"}),
        make_location(),
        brand_profile=brand_profile,
    )


class TestScoring:
    def test_total_within_0_100(self):
        for bp in (None, make_bp()):
            op = _happy(brand_profile=bp, category="roofing")
            assert 0 <= op.score <= 100

    def test_components_sum_to_score(self):
        op = _happy(brand_profile=make_bp())
        assert sum(op.score_components.values()) == op.score

    def test_stronger_fit_scores_higher(self):
        low = ENGINE.evaluate(
            make_prospect(), make_placement(traffic_override=100),
            make_location(),
            brand_profile=make_bp(quality=10, vision=5),
        )
        high = ENGINE.evaluate(
            make_prospect(), make_placement(traffic_override=40000),
            make_location(),
            brand_profile=make_bp(quality=99, vision=99),
        )
        assert high.score > low.score

    def test_ineligible_score_zero(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(status=STATUS_SOLD), make_location()
        )
        assert op.score == 0
        assert op.eligible is False

    def test_deterministic(self):
        a = ENGINE.evaluate(make_prospect(), make_placement(), make_location(), make_bp())
        b = ENGINE.evaluate(make_prospect(), make_placement(), make_location(), make_bp())
        # opportunity_id / timestamps are intentionally fresh; the computed
        # eligibility + score + components + reasons must be identical.
        for o in (a, b):
            assert o.eligible is True
            assert o.score == 96
            assert o.score_components == {
                "category_fit": 35,
                "market_fit": 20,
                "traffic": 12,
                "prospect_quality": 14,
                "commercial_fit": 15,
            }
        assert a.reasons == b.reasons

    def test_no_unsupported_financial_assumptions(self):
        op = _happy(brand_profile=make_bp())
        assert set(op.score_components) == {
            "category_fit", "market_fit", "traffic",
            "prospect_quality", "commercial_fit",
        }
        # No budget / revenue / ROI keys anywhere.
        assert "budget" not in op.score_components
        assert "revenue" not in op.score_components
        assert "roi" not in " ".join(op.reasons).lower()

    def test_commercial_fit_conservative_without_price(self):
        op = ENGINE.evaluate(
            make_prospect(),
            make_placement(price=None),
            make_location(),
            brand_profile=make_bp(),
        )
        assert 0 <= op.score_components["commercial_fit"] <= COMMERCIAL_WEIGHT
# ---------------------------------------------------------------------------
# REASONS
# ---------------------------------------------------------------------------


class TestReasons:
    def test_positive_reasons_generated(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(), make_location(),
            brand_profile=make_bp(categories=("roofing",)),
        )
        assert op.reasons
        assert any("category allowed" in r for r in op.reasons)

    def test_blocked_reason_generated(self):
        op = ENGINE.evaluate(
            make_prospect(category="attorney"),
            make_placement(blocked=("attorney",)),
            make_location(),
        )
        assert any("category blocked" in r for r in op.eligibility_reasons)

    def test_sold_reason_generated(self):
        op = ENGINE.evaluate(
            make_prospect(), make_placement(status=STATUS_SOLD), make_location()
        )
        assert any("Placement is SOLD" == r for r in op.eligibility_reasons)

    def test_geographic_uncertainty_explained(self):
        op = ENGINE.evaluate(
            make_prospect(city="", state=""),
            make_placement(),
            make_location(city="", state=""),
        )
        assert any("No geographic" in r for r in op.reasons)


# ---------------------------------------------------------------------------
# RANKING (engine helper)
# ---------------------------------------------------------------------------


class TestRanking:
    @staticmethod
    def _opp(placement_id, score, eligible=True):
        return Opportunity(
            prospect_id="p1",
            placement_id=placement_id,
            eligible=eligible,
            score=score,
        )

    def test_placements_ranked_desc(self):
        ops = [
            self._opp("c", 50),
            self._opp("a", 90),
            self._opp("b", 70),
        ]
        ranked = rank_opportunities(ops)
        assert [o.placement_id for o in ranked] == ["a", "b", "c"]

    def test_ineligible_omitted_by_default(self):
        ops = [self._opp("a", 90, eligible=False), self._opp("b", 70)]
        ranked = rank_opportunities(ops)
        assert [o.placement_id for o in ranked] == ["b"]

    def test_include_ineligible_optional(self):
        ops = [self._opp("a", 0, eligible=False), self._opp("b", 70)]
        ranked = rank_opportunities(ops, include_ineligible=True)
        assert len(ranked) == 2

    def test_deterministic_tie_break(self):
        ops = [
            self._opp("b", 80),
            self._opp("a", 80),
            self._opp("c", 80),
        ]
        r1 = [o.placement_id for o in rank_opportunities(ops)]
        r2 = [o.placement_id for o in rank_opportunities(ops)]
        assert r1 == r2 == ["a", "b", "c"]

    def test_limit_works(self):
        ops = [self._opp(x, x) for x in (90, 80, 70)]
        assert len(rank_opportunities(ops, limit=2)) == 2
        assert len(rank_opportunities(ops, limit=None)) == 3


# ---------------------------------------------------------------------------
# INDEPENDENCE
# ---------------------------------------------------------------------------


class TestIndependence:
    def _imports(self, mod):
        src = open(mod.__file__, encoding="utf-8").read()
        out = []
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("import ", "from ")):
                out.append(stripped)
        return out

    def test_no_gui_dependency(self):
        import engine.opportunity as mod
        for line in self._imports(mod):
            assert "PySide6" not in line
            assert "PyQt" not in line

    def test_no_web_requests(self):
        import engine.opportunity as mod
        for line in self._imports(mod):
            assert "requests" not in line
            assert "urllib.request" not in line
            assert "http" not in line

    def test_no_scraper_calls(self):
        import engine.opportunity as mod
        for line in self._imports(mod):
            assert "scraper" not in line
            assert "playwright" not in line

    def test_no_llm_calls(self):
        import engine.opportunity as mod
        for line in self._imports(mod):
            assert "openai" not in line
            assert "anthropic" not in line
            assert "llm" not in line
