"""Sprint 5F Prospect Opportunity Workspace aggregation service (Qt-free).

Assembles a salesperson-facing snapshot of existing intelligence already produced
by the Opportunity, Recommendation, Research, and Location services. This module
is a PRESENTATION / AGGREGATION layer — it does NOT implement business rules,
scoring, geocoding, or research.

Design rules:
- No Qt imports.
- No duplicate eligibility, scoring, category, Haversine, or pricing logic.
- No web / scraper / LLM / geocoding API calls.
- Consumes existing services: ProspectStore, ProjectStore, InventoryStore,
  OpportunityService, StoreRecommendationService, LocationEnrichmentService.
- Snapshot read does NOT mutate, scrape, geocode, or enqueue research.
- Refresh invokes existing OpportunityService.recommend_for_prospect (idempotent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Match strength labels (PRESENTATION-ONLY; do NOT alter Opportunity.score)
# ---------------------------------------------------------------------------
MATCH_STRONG = "STRONG MATCH"     # score >= 90
MATCH_GOOD = "GOOD MATCH"         # 75 <= score < 90
MATCH_POSSIBLE = "POSSIBLE MATCH"  # 1 <= score < 75
MATCH_NONE = "NO ELIGIBLE MATCH"  # score == 0 or no eligible opportunities

# ---------------------------------------------------------------------------
# Location status (derived from existing coordinate/address data)
# ---------------------------------------------------------------------------
LOC_RESOLVED = "RESOLVED"
LOC_UNRESOLVED = "UNRESOLVED"
LOC_ADDRESS_INCOMPLETE = "ADDRESS INCOMPLETE"

# ---------------------------------------------------------------------------
# Research display statuses (mapped from authoritative Prospect.research_status)
# ---------------------------------------------------------------------------
_RESEARCH_DISPLAY = {
    "NOT_READY": "NOT READY",
    "READY": "READY",
    "QUEUED": "QUEUED",
    "RUNNING": "RUNNING",
    "SUCCEEDED": "SUCCEEDED",
    "FAILED": "FAILED",
}


def _research_display(research_status: Optional[str]) -> str:
    """Map authoritative research_status to human display label."""
    if not research_status:
        return "NOT READY"
    return _RESEARCH_DISPLAY.get(research_status.strip(), research_status.strip())


def _match_strength(score: Optional[int], eligible_count: int) -> str:
    """Presentation-only mapping from score to match strength label.

    Thresholds:
        90–100  → STRONG MATCH
        75–89   → GOOD MATCH
        1–74    → POSSIBLE MATCH
        0/none  → NO ELIGIBLE MATCH
    """
    if eligible_count == 0 or score is None or score <= 0:
        return MATCH_NONE
    if score >= 90:
        return MATCH_STRONG
    if score >= 75:
        return MATCH_GOOD
    return MATCH_POSSIBLE


def _location_status(
    latitude: Any, longitude: Any, address: Optional[str],
    city: Optional[str], state: Optional[str],
) -> str:
    """Derive a display-only location status from existing coordinate/address data.

    Does NOT perform geocoding. Only reads existing fields.
    """
    lat_ok = latitude is not None
    lon_ok = longitude is not None
    try:
        lat_ok = lat_ok and -90.0 <= float(latitude) <= 90.0
        lon_ok = lon_ok and -180.0 <= float(longitude) <= 180.0
    except (TypeError, ValueError):
        return LOC_UNRESOLVED

    if lat_ok and lon_ok:
        return LOC_RESOLVED

    has_address = bool((address or "").strip())
    has_city_state = bool((city or "").strip() or (state or "").strip())
    if not has_address and not has_city_state:
        return LOC_ADDRESS_INCOMPLETE
    return LOC_UNRESOLVED
# ---------------------------------------------------------------------------
# ProspectOpportunitySnapshot — presentation-ready DTO
# ---------------------------------------------------------------------------


@dataclass
class ProspectOpportunitySnapshot:
    """Aggregated snapshot of existing intelligence for a single prospect.

    Fields are presentation-ready. No business rules live here.
    """

    # --- Prospect identity ---
    prospect_id: str = ""
    company_name: str = ""

    # --- Research ---
    research_status: str = ""  # display label (e.g. "SUCCEEDED")
    research_complete: bool = False

    # --- Project ---
    project_id: Optional[str] = None
    project_available: bool = False

    # --- Location ---
    location_status: str = LOC_UNRESOLVED
    address_display: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    coordinate_source: str = ""

    # --- Opportunity counts ---
    opportunity_count: int = 0
    eligible_opportunity_count: int = 0

    # --- Match ---
    best_match_score: int = 0
    match_strength: str = MATCH_NONE

    # --- Best store (first recommendation in BEST_MATCH mode) ---
    best_store: Optional[Any] = None  # StoreRecommendation

    # --- Convenience fields from best store ---
    best_location_id: str = ""
    best_location_name: str = ""
    best_market: str = ""
    best_retailer: str = ""
    best_placement_id: str = ""
    best_placement_name: str = ""
    best_placement_type: str = ""
    weekly_traffic: Optional[int] = None
    distance_miles: Optional[float] = None
    price_display: str = ""
    reasons: List[str] = field(default_factory=list)

    # --- Recommendations ---
    recommendations: List[Any] = field(default_factory=list)

    # --- Empty / no-data state ---
    is_empty: bool = True


# ---------------------------------------------------------------------------
# ProspectOpportunityWorkspaceService
# ---------------------------------------------------------------------------


class ProspectOpportunityWorkspaceService:
    """Qt-free aggregation service for the Prospect Opportunity Workspace.

    Consumes existing services; never implements business rules.
    """

    def __init__(
        self,
        prospect_store: Any = None,
        project_store: Any = None,
        inventory_store: Any = None,
        opportunity_service: Any = None,
        store_recommendation_service: Any = None,
    ) -> None:
        from gui.models.inventory_store import InventoryStore
        from gui.models.project_store import ProjectStore
        from gui.models.prospect_store import ProspectStore
        from gui.services.opportunity_service import OpportunityService
        from gui.services.store_recommendation import StoreRecommendationService

        self._prospect_store = prospect_store or ProspectStore()
        self._project_store = project_store or ProjectStore()
        self._inventory_store = inventory_store or InventoryStore()
        self._opportunity_service = opportunity_service or OpportunityService(
            prospect_store=self._prospect_store,
            project_store=self._project_store,
            inventory_store=self._inventory_store,
        )
        self._rec_svc = store_recommendation_service or StoreRecommendationService(
            opportunity_service=self._opportunity_service,
            inventory_store=self._inventory_store,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def recommendation_service(self) -> Any:
        """The StoreRecommendationService used internally (shared reference)."""
        return self._rec_svc

    def snapshot_for_prospect(
        self,
        prospect_id: str,
        recommendation_limit: int = 3,
    ) -> ProspectOpportunitySnapshot:
        """READ existing state only. No recompute, no scrape, no geocode."""
        return self._build_snapshot(prospect_id, recommendation_limit, refresh=False)

    def refresh_for_prospect(
        self,
        prospect_id: str,
        recommendation_limit: int = 3,
    ) -> ProspectOpportunitySnapshot:
        """Recompute + read via existing OpportunityService.recommend_for_prospect."""
        return self._build_snapshot(prospect_id, recommendation_limit, refresh=True)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_snapshot(
        self, prospect_id: str, limit: int, refresh: bool,
    ) -> ProspectOpportunitySnapshot:
        if not prospect_id:
            return ProspectOpportunitySnapshot(is_empty=True)

        self._ensure_loaded()

        prospect = self._prospect_store.get(prospect_id)
        if prospect is None:
            return ProspectOpportunitySnapshot(is_empty=True)

        rs = (prospect.research_status or "").strip()
        research_complete = (rs == "SUCCEEDED")

        project = self._locate_project(prospect_id)
        project_id = project.id if project is not None else None

        loc_status = _location_status(
            prospect.latitude, prospect.longitude,
            prospect.address, prospect.city, prospect.state,
        )
        address_parts = [
            p for p in (prospect.address, prospect.city, prospect.state)
            if p and str(p).strip()
        ]
        address_display = ", ".join(address_parts) if address_parts else ""
        geo = getattr(prospect, "geocode_metadata", None) or {}
        coord_source = geo.get("source", "")

        if refresh:
            try:
                self._rec_svc._opportunity_service.recommend_for_prospect(prospect_id)
            except Exception as exc:
                logger.warning("Refresh recommend_for_prospect failed: %s", exc)

        opportunities = self._opportunity_service.by_prospect(prospect_id)
        eligible = [o for o in opportunities if o.eligible]
        opp_count = len(opportunities)
        eligible_count = len(eligible)

        recommendations = self._rec_svc.recommend(
            prospect_id, limit=limit, rank_mode="BEST_MATCH", refresh=False,
        )
        best_store = recommendations[0] if recommendations else None
        best_score = best_store.score if best_store is not None else 0
        match_str = _match_strength(best_score, eligible_count)

        snap = ProspectOpportunitySnapshot(
            prospect_id=prospect.prospect_id,
            company_name=prospect.company_name or "",
            research_status=_research_display(rs),
            research_complete=research_complete,
            project_id=project_id,
            project_available=project_id is not None,
            location_status=loc_status,
            address_display=address_display,
            latitude=prospect.latitude,
            longitude=prospect.longitude,
            coordinate_source=coord_source,
            opportunity_count=opp_count,
            eligible_opportunity_count=eligible_count,
            best_match_score=best_score,
            match_strength=match_str,
            best_store=best_store,
            recommendations=list(recommendations),
            is_empty=False,
        )

        if best_store is not None:
            bs = best_store
            snap.best_location_id = bs.location_id or ""
            snap.best_location_name = bs.location_name or ""
            snap.best_market = bs.market_name or ""
            snap.best_retailer = bs.retailer_name or ""
            snap.best_placement_id = bs.placement_id or ""
            snap.best_placement_name = bs.placement_name or ""
            snap.best_placement_type = bs.placement_type or ""
            snap.weekly_traffic = bs.weekly_traffic
            snap.distance_miles = bs.distance_miles
            snap.price_display = bs.price_display or ""
            snap.reasons = list(bs.reasons)

        return snap

    def _ensure_loaded(self) -> None:
        """Load stores if they haven't been loaded yet."""
        try:
            self._prospect_store.load()
        except FileNotFoundError:
            pass
        except Exception:
            pass
        try:
            self._opportunity_service.ensure_loaded()
        except Exception:
            pass

    def _locate_project(self, prospect_id: str) -> Any:
        """Find the Project associated with this prospect via metadata."""
        try:
            return self._opportunity_service.locate_project(prospect_id)
        except Exception:
            pass
        try:
            for proj in self._project_store.list():
                meta = getattr(proj, "metadata", {}) or {}
                if meta.get("prospect_id") == prospect_id:
                    return proj
        except Exception:
            pass
        return None
