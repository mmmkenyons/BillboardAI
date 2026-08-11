"""Sprint 5D StoreRecommendationService (pure Python, Qt-free).

Consumes OpportunityService results and transforms eligible Placement
Opportunities into store-level recommendations:

    OpportunityService
            ↓
    eligible Placement Opportunities
            ↓
    StoreRecommendationService
            ↓
    group by Location
            ↓
    best Placement per Location
            ↓
    rank Locations
            ↓
    Top N
            ↓
    Prospect Workspace UI

Design rules:
- No Qt imports.
- No duplicate eligibility / scoring / category logic.
- No persistence — recommendations are derived/read models.
- No LLM / web / scraper / geocoding API calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ranking modes
# ---------------------------------------------------------------------------
RANK_BEST_MATCH = "BEST_MATCH"
RANK_NEAREST = "NEAREST"

RANK_MODES: tuple = (RANK_BEST_MATCH, RANK_NEAREST)


# ---------------------------------------------------------------------------
# StoreRecommendation — lightweight derived / read model
# ---------------------------------------------------------------------------

@dataclass
class StoreRecommendation:
    """A store-level recommendation: the best eligible placement at one location.

    This is NOT a durable business entity. It is regenerated from Opportunities
    + Inventory on demand. Opportunity remains the durable prospect-placement
    relationship.
    """

    # --- Location identity ---
    location_id: str = ""
    location_name: str = ""
    store_number: str = ""
    retailer_name: str = ""
    market_name: str = ""
    city: str = ""
    state: str = ""

    # --- Best representative placement ---
    opportunity_id: str = ""
    placement_id: str = ""
    placement_name: str = ""
    placement_type: str = ""

    # --- Computed metrics ---
    score: int = 0
    score_components: Dict[str, Any] = field(default_factory=dict)
    distance_miles: Optional[float] = None
    distance_source: str = ""
    weekly_traffic: Optional[int] = None
    price_display: str = ""
    recommended_category: str = ""

    # --- Explanation ---
    reasons: List[str] = field(default_factory=list)

    # --- Related entities ---
    prospect_id: str = ""
    project_id: str = ""


# ---------------------------------------------------------------------------
# StoreRecommendationService
# ---------------------------------------------------------------------------


class StoreRecommendationService:
    """Stateless service that derives store recommendations from Opportunities."""

    def __init__(
        self,
        opportunity_service: Any = None,
        inventory_store: Any = None,
    ) -> None:
        from gui.models.inventory_store import InventoryStore
        from gui.services.opportunity_service import OpportunityService

        self._opportunity_service = opportunity_service or OpportunityService()
        self._inventory_store = inventory_store or InventoryStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(
        self,
        prospect_id: str,
        limit: int = 3,
        rank_mode: str = RANK_BEST_MATCH,
        refresh: bool = False,
    ) -> List[StoreRecommendation]:
        """Return top-N store recommendations for a prospect."""
        if not prospect_id:
            return []

        if refresh:
            self._opportunity_service.recommend_for_prospect(prospect_id)

        opportunities = self._opportunity_service.by_prospect(prospect_id)
        eligible = [o for o in opportunities if o.eligible]
        if not eligible:
            return []

        by_location: Dict[str, List[Any]] = {}
        for opp in eligible:
            lid = opp.location_id or ""
            if not lid:
                continue
            by_location.setdefault(lid, []).append(opp)

        if not by_location:
            return []

        store_reps: List[StoreRecommendation] = []
        for lid, opps in by_location.items():
            best = self._best_placement(opps)
            if best is None:
                continue
            rec = self._build_recommendation(best)
            if rec is not None:
                store_reps.append(rec)

        store_reps = self._rank_stores(store_reps, rank_mode)
        if limit > 0:
            store_reps = store_reps[:limit]
        return store_reps


    # ------------------------------------------------------------------
    # Internal: best placement
    # ------------------------------------------------------------------

    def _best_placement(self, opportunities: List[Any]) -> Optional[Any]:
        """Highest score opportunity for a location, deterministic tie-break."""
        if not opportunities:
            return None
        return sorted(
            opportunities, key=lambda o: (-o.score, o.placement_id)
        )[0]

    # ------------------------------------------------------------------
    # Internal: build recommendation DTO
    # ------------------------------------------------------------------

    def _build_recommendation(
        self, opportunity: Any
    ) -> Optional[StoreRecommendation]:
        """Resolve inventory entities and build a StoreRecommendation."""
        inventory = self._inventory_store.inventory
        location = inventory.get_location(opportunity.location_id)
        if location is None:
            logger.warning(
                "Opportunity %s references unknown location %s",
                opportunity.opportunity_id,
                opportunity.location_id,
            )
            return None

        placement = inventory.get_placement(opportunity.placement_id)
        retailer = inventory.get_retailer(location.retailer_id)
        market = inventory.get_market(location.market_id)

        traffic = None
        if placement is not None:
            traffic = placement.effective_weekly_traffic(location)

        price_display_str = ""
        if placement is not None:
            price_display_str = placement.price_display() or ""

        return StoreRecommendation(
            location_id=location.location_id,
            location_name=location.name or "",
            store_number=location.store_number or "",
            retailer_name=retailer.name if retailer else "",
            market_name=market.name if market else "",
            city=location.city or "",
            state=location.state or "",
            opportunity_id=opportunity.opportunity_id,
            placement_id=opportunity.placement_id,
            placement_name=placement.name if placement else "",
            placement_type=placement.placement_type if placement else "",
            score=opportunity.score,
            score_components=dict(opportunity.score_components),
            distance_miles=opportunity.distance_miles,
            distance_source=opportunity.distance_source or "",
            weekly_traffic=traffic,
            price_display=price_display_str,
            recommended_category=opportunity.recommended_category or "",
            reasons=list(opportunity.reasons),
            prospect_id=opportunity.prospect_id or "",
            project_id=opportunity.project_id or "",
        )

    # ------------------------------------------------------------------
    # Internal: ranking store representatives
    # ------------------------------------------------------------------

    def _rank_stores(
        self,
        recommendations: List[StoreRecommendation],
        rank_mode: str,
    ) -> List[StoreRecommendation]:
        """Rank store recommendations according to the requested mode."""
        if rank_mode == RANK_NEAREST:
            return self._rank_by_distance(recommendations)
        return self._rank_by_score(recommendations)

    @staticmethod
    def _rank_by_score(
        recommendations: List[StoreRecommendation],
    ) -> List[StoreRecommendation]:
        """Score DESC, deterministic tie-break by location_id."""
        return sorted(
            recommendations,
            key=lambda r: (-r.score, r.location_id),
        )

    @staticmethod
    def _rank_by_distance(
        recommendations: List[StoreRecommendation],
    ) -> List[StoreRecommendation]:
        """Rank by distance ascending; unknowns sorted last by score."""
        known = [r for r in recommendations if r.distance_miles is not None]
        unknown = [r for r in recommendations if r.distance_miles is None]
        known.sort(
            key=lambda r: (r.distance_miles or 0.0, -r.score, r.location_id)
        )
        unknown.sort(key=lambda r: (-r.score, r.location_id))
        return known + unknown

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def locate_project(self, prospect_id: str) -> Optional[Any]:
        """Return the researched Project for a prospect, or None."""
        return self._opportunity_service.locate_project(prospect_id)
