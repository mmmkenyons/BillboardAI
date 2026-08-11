"""OpportunityStore: repository abstraction for durable BillboardAI Opportunities.

The Opportunity is the sale-purpose relationship between a **Prospect** and a
**Placement** (Sprint 5C matching). Similar in spirit to ``ProspectStore`` and
``InventoryStore``, this owns the on-disk layout and load/save lifecycle:

    <root>/
        opportunities/opportunities.json

The file is a single JSON document with a top-level ``schema_version`` and an
``opportunities`` collection. A single file keeps the format simple and
maintainable while remaining forward compatible: each model's ``from_dict``
ignores unknown fields and supplies safe defaults for missing optional fields.

Design points:

- **Atomic writes** — a temporary file is written in the same directory and
  then ``os.replace``-d over the target, so a crash during save cannot easily
  corrupt the file.
- **Clear corruption errors** — malformed JSON raises ``OpportunityCorruptionError``
  (a subclass of ``OpportunityError``) with a descriptive message.
- **Missing file** — ``load()`` raises ``FileNotFoundError``; ``exists()`` /
  ``load_or_empty()`` let a caller decide how to handle absence.
- **Git-ignored by default** — the default path lives under ``output/opportunities``
  (git-ignored), never inside source code.
- **JSON only** — no pickle/binary serialization, so the file is human-readable
  and portable.
- **Deterministic ordering** — ``list()`` returns opportunities sorted by
  ``opportunity_id``; filter helpers preserve that ordering.
- **Idempotent upsert** — ``(prospect_id, placement_id)`` maps to ONE durable
  Opportunity. Re-running matching UPDATES the existing record (preserving its
  ``opportunity_id``, ``created_at``, and manual status/notes) instead of
  creating duplicates.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from engine.opportunity import (
    MANUAL_STATUSES,
    Opportunity,
)

logger = logging.getLogger(__name__)

# Bump when the persisted schema changes incompatibly. Old files remain loadable
# because from_dict is forward compatible, but a bump lets us run migrations.
SCHEMA_VERSION = 1

# Default opportunities file (git-ignored via output/).
DEFAULT_OPPORTUNITIES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "opportunities",
)
DEFAULT_OPPORTUNITIES_PATH = os.path.join(
    DEFAULT_OPPORTUNITIES_DIR, "opportunities.json"
)


class OpportunityError(Exception):
    """Base error for opportunity persistence."""


class OpportunityCorruptionError(OpportunityError):
    """Raised when the opportunities file exists but cannot be parsed."""


class OpportunityCollection:
    """An in-memory snapshot of all opportunities.

    Holds the opportunity list plus the schema version. Query helpers operate
    directly on the snapshot so callers can filter without touching the
    store/disk. All list operations are deterministically ordered by id.
    """

    def __init__(
        self,
        opportunities: Optional[List[Opportunity]] = None,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.opportunities: List[Opportunity] = list(opportunities or [])
        self.schema_version: int = schema_version

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "opportunities": [o.to_dict() for o in self.opportunities],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "OpportunityCollection":
        if not isinstance(data, dict):
            raise OpportunityCorruptionError(
                "opportunities root must be a JSON object (got %s)"
                % type(data).__name__
            )
        schema = data.get("schema_version")
        try:
            schema_int = int(schema) if schema is not None else SCHEMA_VERSION
        except (TypeError, ValueError):
            schema_int = SCHEMA_VERSION
        return cls(
            opportunities=[
                Opportunity.from_dict(o)
                for o in data.get("opportunities", [])
                if isinstance(o, dict)
            ],
            schema_version=schema_int,
        )

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get(self, opportunity_id: str) -> Optional[Opportunity]:
        for o in self.opportunities:
            if o.opportunity_id == opportunity_id:
                return o
        return None

    def get_by_key(
        self, prospect_id: str, placement_id: str
    ) -> Optional[Opportunity]:
        """Return the opportunity for a (prospect_id, placement_id), or None."""
        for o in self.opportunities:
            if o.prospect_id == prospect_id and o.placement_id == placement_id:
                return o
        return None

    def sorted(self) -> List[Opportunity]:
        return sorted(self.opportunities, key=lambda o: o.opportunity_id)
    # ------------------------------------------------------------------
    # Filtering (deterministic ordering by id)
    # ------------------------------------------------------------------

    def by_prospect(self, prospect_id: str) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.prospect_id == prospect_id],
            key=lambda o: o.opportunity_id,
        )

    def by_project(self, project_id: str) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.project_id == project_id],
            key=lambda o: o.opportunity_id,
        )

    def by_placement(self, placement_id: str) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.placement_id == placement_id],
            key=lambda o: o.opportunity_id,
        )

    def by_location(self, location_id: str) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.location_id == location_id],
            key=lambda o: o.opportunity_id,
        )

    def by_market(self, market_id: str) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.market_id == market_id],
            key=lambda o: o.opportunity_id,
        )

    def by_status(self, status: str) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.status == status],
            key=lambda o: o.opportunity_id,
        )

    def eligible_only(self) -> List[Opportunity]:
        return sorted(
            [o for o in self.opportunities if o.eligible],
            key=lambda o: o.opportunity_id,
        )


class OpportunityStore:
    """Save / load / list / filter / upsert / archive durable opportunities."""

    def __init__(
        self,
        path: Optional[Union[str, "os.PathLike[str]"]] = None,
        collection: Optional[OpportunityCollection] = None,
    ) -> None:
        self._path = os.path.abspath(str(path)) if path else DEFAULT_OPPORTUNITIES_PATH
        self._collection = (
            collection if collection is not None else OpportunityCollection()
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        """The absolute path to the opportunities.json file."""
        return self._path

    @property
    def collection(self) -> OpportunityCollection:
        """The current in-memory opportunity snapshot managed by this store."""
        return self._collection

    def exists(self) -> bool:
        """Return True when an opportunities file exists on disk."""
        return os.path.isfile(self._path)

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the current snapshot atomically (tmp file + os.replace)."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = self._collection.to_dict()
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp_path, self._path)

    def load(self) -> OpportunityCollection:
        """Load opportunities from disk, replacing the store's snapshot.

        Raises FileNotFoundError when the file is missing and
        OpportunityCorruptionError when the file cannot be parsed.
        """
        if not os.path.isfile(self._path):
            raise FileNotFoundError(f"No opportunities file found at {self._path!r}")
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise OpportunityCorruptionError(
                f"Corrupted opportunities file at {self._path!r}: {exc}"
            ) from exc
        self._collection = OpportunityCollection.from_dict(data)
        return self._collection

    def load_or_empty(self) -> OpportunityCollection:
        """Load if present; otherwise keep/create an empty snapshot (no raise)."""
        if self.exists():
            return self.load()
        self._collection = OpportunityCollection()
        return self._collection
    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, opportunity: Opportunity) -> Opportunity:
        """Add a new opportunity to the snapshot (no dedup)."""
        self._collection.opportunities.append(opportunity)
        return opportunity

    def add(self, opportunity: Opportunity) -> Opportunity:
        """Alias for :meth:`create`."""
        return self.create(opportunity)

    def get(self, opportunity_id: str) -> Optional[Opportunity]:
        """Return an opportunity by id, or None."""
        return self._collection.get(opportunity_id)

    def list(self) -> List[Opportunity]:
        """Return all opportunities, deterministically ordered by id."""
        return self._collection.sorted()

    def update(self, opportunity: Opportunity) -> Opportunity:
        """Replace an existing opportunity in the snapshot by id (no-op if absent).

        The caller is responsible for calling ``save()`` to persist.
        """
        existing = self.get(opportunity.opportunity_id)
        if existing is None:
            return opportunity
        index = self._collection.opportunities.index(existing)
        self._collection.opportunities[index] = opportunity
        return opportunity

    def upsert(self, opportunity: Opportunity) -> Opportunity:
        """Idempotently persist an opportunity keyed by ``(prospect_id, placement_id)``.

        - If no record exists for the pair, the ``opportunity`` is appended and
          returned unchanged.
        - If a record already exists for the pair, it is UPDATED in place:
            * preserved: ``opportunity_id``, ``created_at``, existing manual
              status (REVIEWED/SELECTED/REJECTED/ARCHIVED), existing notes;
            * updated:   project_id, location_id, market_id, eligible,
              eligibility_reasons, reasons, score, score_components,
              recommended_category, distance_miles, distance_source, metadata;
            * the ``status`` is taken from the incoming record only when the
              existing one is still an automatic status (NEW/RECOMMENDED);
            * ``modified_at`` is refreshed.

        Returns the effective stored ``Opportunity``. This guarantees re-running
        matching never creates duplicate opportunities.
        """
        existing = self._collection.get_by_key(
            opportunity.prospect_id, opportunity.placement_id
        )
        if existing is None:
            self._collection.opportunities.append(opportunity)
            return opportunity

        # Preserve created_at + id. Update computed fields.
        existing.project_id = opportunity.project_id
        existing.location_id = opportunity.location_id
        existing.market_id = opportunity.market_id
        existing.eligible = opportunity.eligible
        existing.eligibility_reasons = list(opportunity.eligibility_reasons)
        existing.reasons = list(opportunity.reasons)
        existing.score = opportunity.score
        existing.score_components = dict(opportunity.score_components)
        existing.recommended_category = opportunity.recommended_category
        existing.distance_miles = opportunity.distance_miles
        existing.distance_source = opportunity.distance_source

        # Preserve manual status; otherwise adopt the recomputed status.
        if existing.status not in MANUAL_STATUSES:
            existing.status = opportunity.status

        # Preserve manual notes; only fill when currently empty.
        if not existing.notes:
            existing.notes = opportunity.notes

        # Merge metadata (incoming keys added only when absent).
        for key, value in opportunity.metadata.items():
            if key not in existing.metadata:
                existing.metadata[key] = value

        existing.touch()
        return existing

    def archive(self, opportunity_id: str) -> Optional[Opportunity]:
        """Mark an opportunity as ARCHIVED (non-destructive). Returns it or None."""
        opportunity = self.get(opportunity_id)
        if opportunity is None:
            return None
        opportunity.status = "ARCHIVED"
        opportunity.touch()
        return opportunity

    def remove(self, opportunity_id: str) -> bool:
        """Permanently remove an opportunity from the snapshot. True if removed."""
        opportunity = self.get(opportunity_id)
        if opportunity is None:
            return False
        self._collection.opportunities.remove(opportunity)
        return True

    # ------------------------------------------------------------------
    # Filters (deterministic ordering by id)
    # ------------------------------------------------------------------

    def by_prospect(self, prospect_id: str) -> List[Opportunity]:
        return self._collection.by_prospect(prospect_id)

    def by_project(self, project_id: str) -> List[Opportunity]:
        return self._collection.by_project(project_id)

    def by_placement(self, placement_id: str) -> List[Opportunity]:
        return self._collection.by_placement(placement_id)

    def by_location(self, location_id: str) -> List[Opportunity]:
        return self._collection.by_location(location_id)

    def by_market(self, market_id: str) -> List[Opportunity]:
        return self._collection.by_market(market_id)

    def by_status(self, status: str) -> List[Opportunity]:
        return self._collection.by_status(status)

    def eligible_only(self) -> List[Opportunity]:
        return self._collection.eligible_only()
