"""Sprint 5C OpportunityService (pure Python, Qt-free).

Owns the orchestration that connects researched prospects (Prospect +
Project/BrandProfile) to available advertising inventory (Placement) and
persists the resulting **Opportunity** relationships via ``OpportunityStore``:

    prospect_store     -> Prospect (raw / managed lead)
    project_store      -> Project (BrandProfile) associated by metadata["prospect_id"]
    inventory_store    -> Placement / Location / Market hierarchy
    opportunity_store  -> Opportunity persistence (idempotent upsert)
    OpportunityEngine  -> deterministic eligibility + score + reasons

Responsibilities: locate a Prospect; locate its associated researched Project;
load the inventory hierarchy; evaluate opportunities; rank placements for a
prospect (and prospects for a placement); persist/upsert; recompute; and
query/filter.

Design rules honored (mirroring the other workspace services):

- **No raw widgets.** This module never imports Qt.
- **No direct JSON writes.** Persistence flows through ``OpportunityStore``.
- **No web requests / scraper / LLM.** Matching is local & deterministic.
- **Engine stays pure.** All business rules live in ``OpportunityEngine``; this
  service only locates objects and wires them together.
- **No Project by company-name matching.** A Project is associated with a
  prospect ONLY via ``project.metadata["prospect_id"]``.
- **No hard-block for missing research.** A prospect may still get an
  opportunity without a researched Project; research-quality components are
  simply neutral/zero (per the Sprint 5C rule).
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from engine.brand_profile import BrandProfile
from engine.opportunity import (
    Opportunity,
    OpportunityEngine,
    rank_opportunities,
)
from gui.models.inventory_store import InventoryStore
from gui.models.opportunity_store import OpportunityStore
from gui.models.project import Project
from gui.models.project_store import ProjectStore

logger = logging.getLogger(__name__)


class OpportunityService:
    """Stateless (per-call) domain operations wiring stores + engine."""

    def __init__(
        self,
        prospect_store: Any = None,
        project_store: Any = None,
        inventory_store: Optional[InventoryStore] = None,
        opportunity_store: Optional[OpportunityStore] = None,
        engine: Optional[OpportunityEngine] = None,
    ) -> None:
        from gui.models.prospect_store import ProspectStore

        self._prospect_store = prospect_store or ProspectStore()
        self._project_store = project_store or ProjectStore()
        self._inventory_store = inventory_store or InventoryStore()
        self._opportunity_store = opportunity_store or OpportunityStore()
        self._engine = engine or OpportunityEngine()
        self._loaded = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def prospect_store(self) -> Any:
        return self._prospect_store

    @property
    def project_store(self) -> ProjectStore:
        return self._project_store

    @property
    def inventory_store(self) -> InventoryStore:
        return self._inventory_store

    @property
    def opportunity_store(self) -> OpportunityStore:
        return self._opportunity_store

    @property
    def engine(self) -> OpportunityEngine:
        return self._engine
    # ------------------------------------------------------------------
    # Load / persistence
    # ------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Ensure prospect + opportunity stores have an in-memory snapshot.

        Loads at most once per service instance. This is important: recompute
        evaluates many opportunities in a loop, and a reload on every evaluate
        would wipe in-memory upserts made earlier in the same batch.
        """
        if self._loaded:
            return
        self._prospect_store.load_or_empty()
        self._opportunity_store.load_or_empty()
        self._loaded = True

    def save(self) -> None:
        """Persist the opportunity snapshot to disk (atomic)."""
        self._opportunity_store.save()

    def upsert(self, opportunity: Opportunity) -> Opportunity:
        """Idempotently persist one opportunity (keyed prospect+placement)."""
        return self._opportunity_store.upsert(opportunity)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def locate_prospect(self, prospect_id: str):
        """Return the Prospect by id, or None."""
        self.ensure_loaded()
        return self._prospect_store.get(prospect_id)

    def locate_project(self, prospect_id: str) -> Optional[Project]:
        """Return the researched Project associated with a prospect, or None.

        Association key (Sprint 5B contract): ``project.metadata["prospect_id"]``.
        Projects are NEVER matched by company name.
        """
        if not prospect_id:
            return None
        for project in self._project_store.list():
            if str(project.metadata.get("prospect_id") or "") == prospect_id:
                return project
        return None

    def _brand_profile_for(self, project: Optional[Project]) -> Optional[BrandProfile]:
        """Hydrate a BrandProfile from the persisted project snapshot (or None)."""
        if project is None or not project.brand_profile:
            return None
        try:
            return BrandProfile.from_dict(project.brand_profile)
        except Exception:  # noqa: BLE001 - corrupt snapshot -> no research evidence
            logger.warning("Could not hydrate BrandProfile for project %s", project.id)
            return None

    def locate_placement(self, placement_id: str):
        """Return the Placement by id, or None."""
        return self._inventory_store.inventory.get_placement(placement_id)

    def locate_location(self, location_id: str):
        """Return the Location by id, or None."""
        return self._inventory_store.inventory.get_location(location_id)

    def locate_market(self, market_id: str):
        """Return the Market by id, or None."""
        return self._inventory_store.inventory.get_market(market_id)
    # ------------------------------------------------------------------
    # Evaluate / rank
    # ------------------------------------------------------------------

    def evaluate(self, prospect_id: str, placement_id: str) -> Opportunity:
        """Evaluate ONE prospect/placement pair (not persisted by default).

        Locates the prospect, the associated researched Project (if any), the
        placement, and its location/market; then runs the engine.
        """
        prospect = self.locate_prospect(prospect_id)
        if prospect is None:
            raise ValueError(f"Prospect {prospect_id!r} not found")
        placement = self.locate_placement(placement_id)
        if placement is None:
            raise ValueError(f"Placement {placement_id!r} not found")

        project = self.locate_project(prospect_id)
        brand_profile = self._brand_profile_for(project)

        location = self.locate_location(getattr(placement, "location_id", "") or "")
        market = None
        if location is not None:
            market = self.locate_market(getattr(location, "market_id", "") or "")

        opportunity = self._engine.evaluate(
            prospect=prospect,
            placement=placement,
            location=location,
            brand_profile=brand_profile,
            market=market,
        )
        if project is not None:
            opportunity.project_id = project.id
        return opportunity

    def _evaluate_all_for_prospect(self, prospect_id: str) -> List[Opportunity]:
        """Evaluate a prospect against every placement in inventory."""
        opportunities: List[Opportunity] = []
        for placement in list(self._inventory_store.inventory.placements):
            opportunities.append(self.evaluate(prospect_id, placement.placement_id))
        return opportunities

    def rank_placements_for_prospect(
        self,
        prospect_id: str,
        limit: Optional[int] = None,
        include_ineligible: bool = False,
    ) -> List[Opportunity]:
        """Rank placements for a prospect (score DESC, deterministic tie-break).

        Ineligible placements are omitted by default. This is the foundation for
        Sprint 5D Top-3 / Top-5 nearby-store recommendations. Does not persist.
        """
        opportunities = self._evaluate_all_for_prospect(prospect_id)
        return rank_opportunities(
            opportunities,
            include_ineligible=include_ineligible,
            limit=limit,
        )

    def _evaluate_all_for_placement(self, placement_id: str) -> List[Opportunity]:
        """Evaluate every prospect against one placement (reverse query)."""
        prospects = self._prospect_store.list()
        opportunities: List[Opportunity] = []
        for prospect in prospects:
            opportunities.append(self.evaluate(prospect.prospect_id, placement_id))
        return opportunities

    def rank_prospects_for_placement(
        self,
        placement_id: str,
        limit: Optional[int] = None,
        include_ineligible: bool = False,
    ) -> List[Opportunity]:
        """Rank prospects for an open placement (reverse query).

        Strategically useful when inventory sales start from
        "I need to sell this open placement." Does not persist.
        """
        opportunities = self._evaluate_all_for_placement(placement_id)
        return rank_opportunities(
            opportunities,
            include_ineligible=include_ineligible,
            limit=limit,
        )
    # ------------------------------------------------------------------
    # Recommend (rank + persist/upsert)
    # ------------------------------------------------------------------

    def recommend_for_prospect(
        self,
        prospect_id: str,
        limit: Optional[int] = None,
        include_ineligible: bool = False,
    ) -> List[Opportunity]:
        """Evaluate + rank + PERSIST opportunities for a prospect.

        Every evaluated placement is upserted (idempotent by prospect+placement),
        then the ranked list is returned. Re-running never duplicates.
        """
        opportunities = self._evaluate_all_for_prospect(prospect_id)
        for opp in opportunities:
            self._opportunity_store.upsert(opp)
        self._opportunity_store.save()
        return rank_opportunities(
            opportunities,
            include_ineligible=include_ineligible,
            limit=limit,
        )

    def recommend_for_placement(
        self,
        placement_id: str,
        limit: Optional[int] = None,
        include_ineligible: bool = False,
    ) -> List[Opportunity]:
        """Evaluate + rank + PERSIST opportunities for one placement."""
        opportunities = self._evaluate_all_for_placement(placement_id)
        for opp in opportunities:
            self._opportunity_store.upsert(opp)
        self._opportunity_store.save()
        return rank_opportunities(
            opportunities,
            include_ineligible=include_ineligible,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Recompute (rescore existing matches, no duplicates)
    # ------------------------------------------------------------------

    def recompute(
        self,
        prospect_id: Optional[str] = None,
        placement_id: Optional[str] = None,
    ) -> int:
        """Rescore existing opportunities (and upsert), returning the count.

        Filters to the given prospect and/or placement (None = all). This is the
        explicit recompute seam for when inventory/prospect data changes — no
        automatic background invalidation is performed.
        """
        existing = self.list()
        if prospect_id:
            existing = [o for o in existing if o.prospect_id == prospect_id]
        if placement_id:
            existing = [o for o in existing if o.placement_id == placement_id]

        updated = 0
        for old in existing:
            opp = self.evaluate(old.prospect_id, old.placement_id)
            stored = self._opportunity_store.upsert(opp)
            updated += 1
            _ = stored
        if updated:
            self._opportunity_store.save()
        return updated

    def archive(self, opportunity_id: str) -> Optional[Opportunity]:
        """Mark an opportunity ARCHIVED (non-destructive) and persist."""
        archived = self._opportunity_store.archive(opportunity_id)
        if archived is not None:
            self._opportunity_store.save()
        return archived

    # ------------------------------------------------------------------
    # Query / filter (pass-through to the store)
    # ------------------------------------------------------------------

    def get(self, opportunity_id: str) -> Optional[Opportunity]:
        return self._opportunity_store.get(opportunity_id)

    def list(self) -> List[Opportunity]:
        return self._opportunity_store.list()

    def by_prospect(self, prospect_id: str) -> List[Opportunity]:
        return self._opportunity_store.by_prospect(prospect_id)

    def by_project(self, project_id: str) -> List[Opportunity]:
        return self._opportunity_store.by_project(project_id)

    def by_placement(self, placement_id: str) -> List[Opportunity]:
        return self._opportunity_store.by_placement(placement_id)

    def by_location(self, location_id: str) -> List[Opportunity]:
        return self._opportunity_store.by_location(location_id)

    def by_market(self, market_id: str) -> List[Opportunity]:
        return self._opportunity_store.by_market(market_id)

    def by_status(self, status: str) -> List[Opportunity]:
        return self._opportunity_store.by_status(status)

    def eligible_only(self) -> List[Opportunity]:
        return self._opportunity_store.eligible_only()
