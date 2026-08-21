"""ProspectStore: repository abstraction for durable BillboardAI prospects.

Similar in spirit to ``InventoryStore``, this owns the on-disk layout and the
load/save lifecycle for the Sprint 5A prospect domain:

    <root>/
        prospects.json

The file is a single JSON document with a top-level ``schema_version`` and a
``prospects`` collection. A single file keeps the format simple and maintainable
while remaining forward compatible: each model's ``from_dict`` ignores unknown
fields and supplies safe defaults for missing optional fields.

Design points:

- **Atomic writes** — a temporary file is written in the same directory and
  then ``os.replace``-d over the target, so a crash during save cannot easily
  corrupt the file.
- **Clear corruption errors** — malformed JSON raises ``ProspectCorruptionError``
  (a subclass of ``ProspectError``) with a descriptive message.
- **Missing file** — ``load()`` raises ``FileNotFoundError``; ``exists()`` lets a
  caller decide whether to create fresh.
- **Git-ignored by default** — the default path lives under ``output/prospects``
  (git-ignored), never inside source code.
- **JSON only** — no pickle/binary serialization, so the file is human-readable
  and portable.
- **Deterministic ordering** — ``list()`` returns prospects sorted by
  ``prospect_id``; filter helpers preserve that ordering.

In addition to persistence, the store provides the duplicate-detection entry
points used by the import pipeline (``find_duplicate``) and the merge behavior
(``merge``), keeping dedup logic in one durable place.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from gui.models.prospect import (
    DEDUP_EXACT,
    DEDUP_POSSIBLE,
    PROSPECT_STATUSES,
    Prospect,
    ProspectDeduplicator,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_website,
)

logger = logging.getLogger(__name__)

# Bump when the persisted schema changes incompatibly. Old files remain loadable
# because from_dict is forward compatible, but a bump lets us run migrations.
SCHEMA_VERSION = 1

# Default prospects file (git-ignored via output/).
DEFAULT_PROSPECTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "prospects",
)
DEFAULT_PROSPECTS_PATH = os.path.join(DEFAULT_PROSPECTS_DIR, "prospects.json")


class ProspectError(Exception):
    """Base error for prospect persistence."""


class ProspectCorruptionError(ProspectError):
    """Raised when the prospects file exists but cannot be parsed."""
class ProspectCollection:
    """An in-memory snapshot of all prospects.

    Holds the prospect list plus the schema version. Query helpers operate
    directly on the snapshot so callers can filter without touching the
    store/disk. All list operations are deterministically ordered by id.
    """

    def __init__(
        self,
        prospects: Optional[List[Prospect]] = None,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.prospects: List[Prospect] = list(prospects or [])
        self.schema_version: int = schema_version

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prospects": [p.to_dict() for p in self.prospects],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ProspectCollection":
        if not isinstance(data, dict):
            raise ProspectCorruptionError(
                "prospects root must be a JSON object (got %s)"
                % type(data).__name__
            )
        schema = data.get("schema_version")
        try:
            schema_int = int(schema) if schema is not None else SCHEMA_VERSION
        except (TypeError, ValueError):
            schema_int = SCHEMA_VERSION
        return cls(
            prospects=[
                Prospect.from_dict(p)
                for p in data.get("prospects", [])
                if isinstance(p, dict)
            ],
            schema_version=schema_int,
        )

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get(self, prospect_id: str) -> Optional[Prospect]:
        for p in self.prospects:
            if p.prospect_id == prospect_id:
                return p
        return None

    def find_by_domain(self, domain: str) -> Optional[Prospect]:
        target = normalize_domain(domain)
        if not target:
            return None
        for p in self.prospects:
            if normalize_domain(p.domain or p.website) == target:
                return p
        return None

    def find_by_email(self, email: str) -> Optional[Prospect]:
        target = normalize_email(email)
        if not target:
            return None
        for p in self.prospects:
            if normalize_email(p.email) == target:
                return p
        return None

    def find_by_phone(self, phone: str) -> Optional[Prospect]:
        target = normalize_phone(phone)
        if not target:
            return None
        for p in self.prospects:
            if normalize_phone(p.phone) == target:
                return p
        return None

    def find_duplicate(self, candidate: Prospect) -> Optional[Prospect]:
        """Return the first existing prospect that is an exact duplicate.

        Possible duplicates (company+city fallback) are NOT returned here; the
        import pipeline separately reports them via ``check_possible_duplicates``.
        """
        for existing in self.prospects:
            verdict = ProspectDeduplicator.compare(candidate, existing)
            if verdict == DEDUP_EXACT:
                return existing
        return None

    def check_possible_duplicates(
        self, candidate: Prospect
    ) -> List[Prospect]:
        """Return existing prospects that are possible (non-exact) duplicates."""
        matches: List[Prospect] = []
        for existing in self.prospects:
            verdict = ProspectDeduplicator.compare(candidate, existing)
            if verdict == DEDUP_POSSIBLE:
                matches.append(existing)
        return matches

    # ------------------------------------------------------------------
    # Filtering (deterministic ordering by id)
    # ------------------------------------------------------------------

    def sorted(self) -> List[Prospect]:
        return sorted(self.prospects, key=lambda p: p.prospect_id)

    def by_status(self, status: str) -> List[Prospect]:
        return sorted(
            [p for p in self.prospects if p.status == status],
            key=lambda p: p.prospect_id,
        )

    def by_category(self, category: str) -> List[Prospect]:
        target = str(category or "").strip().lower()
        return sorted(
            [
                p
                for p in self.prospects
                if str(p.category or "").strip().lower() == target
            ],
            key=lambda p: p.prospect_id,
        )

    def by_state(self, state: str) -> List[Prospect]:
        target = str(state or "").strip().upper()
        return sorted(
            [p for p in self.prospects if (p.state or "").upper() == target],
            key=lambda p: p.prospect_id,
        )

    def search(self, query: str) -> List[Prospect]:
        """Case-insensitive search over company name / domain / website."""
        q = str(query or "").strip().lower()
        if not q:
            return self.sorted()
        return sorted(
            [
                p
                for p in self.prospects
                if q in p.company_name.lower()
                or q in (p.domain or "").lower()
                or q in (p.website or "").lower()
            ],
            key=lambda p: p.prospect_id,
        )
class ProspectStore:
    """Create / save / load / list / archive prospects, plus dedup & merge."""

    def __init__(
        self,
        path: Optional[Union[str, "os.PathLike[str]"]] = None,
        collection: Optional[ProspectCollection] = None,
    ) -> None:
        self._path = os.path.abspath(str(path)) if path else DEFAULT_PROSPECTS_PATH
        self._collection = (
            collection if collection is not None else ProspectCollection()
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        """The absolute path to the prospects.json file."""
        return self._path

    @property
    def collection(self) -> ProspectCollection:
        """The current in-memory prospect snapshot managed by this store."""
        return self._collection

    def exists(self) -> bool:
        """Return True when a prospects file exists on disk."""
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

    def load(self) -> ProspectCollection:
        """Load prospects from disk, replacing the store's snapshot.

        Raises FileNotFoundError when the file is missing and
        ProspectCorruptionError when the file cannot be parsed.
        """
        if not os.path.isfile(self._path):
            raise FileNotFoundError(f"No prospects file found at {self._path!r}")
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ProspectCorruptionError(
                f"Corrupted prospects file at {self._path!r}: {exc}"
            ) from exc
        self._collection = ProspectCollection.from_dict(data)
        return self._collection

    def load_or_empty(self) -> ProspectCollection:
        """Load if present; otherwise keep existing in-memory data (no raise).

        IMPORTANT: when no backing file exists the store preserves whatever
        in-memory data is already present — it does NOT construct a fresh
        empty collection that would destroy pre-loaded state.  This is
        essential for dependency-injection scenarios where an in-memory
        store is populated before any ``load``/``ensure_loaded`` call.
        """
        if self.exists():
            return self.load()
        return self._collection

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, prospect: Prospect) -> Prospect:
        """Add a new prospect to the snapshot (no project auto-created)."""
        self._collection.prospects.append(prospect)
        return prospect

    def add(self, prospect: Prospect) -> Prospect:
        """Alias for :meth:`create`."""
        return self.create(prospect)

    def get(self, prospect_id: str) -> Optional[Prospect]:
        """Return a prospect by id, or None."""
        return self._collection.get(prospect_id)

    def list(self) -> List[Prospect]:
        """Return all prospects, deterministically ordered by id."""
        return self._collection.sorted()

    def update(self, prospect: Prospect) -> Prospect:
        """Replace an existing prospect in the snapshot (no-op if absent).

        The caller is responsible for calling ``save()`` to persist.
        """
        existing = self.get(prospect.prospect_id)
        if existing is None:
            return prospect
        index = self._collection.prospects.index(existing)
        self._collection.prospects[index] = prospect
        return prospect

    def upsert(self, prospect: Prospect) -> Prospect:
        """Insert or update a prospect (idempotent by prospect_id)."""
        existing = self.get(prospect.prospect_id)
        if existing is None:
            return self.create(prospect)
        return self.update(prospect)

    def archive(self, prospect_id: str) -> Optional[Prospect]:
        """Mark a prospect as ARCHIVED (non-destructive). Returns the prospect."""
        prospect = self.get(prospect_id)
        if prospect is None:
            return None
        prospect.status = "ARCHIVED"
        prospect.touch()
        return prospect

    def remove(self, prospect_id: str) -> bool:
        """Permanently remove a prospect from the snapshot. True if removed."""
        prospect = self.get(prospect_id)
        if prospect is None:
            return False
        self._collection.prospects.remove(prospect)
        return True
# ------------------------------------------------------------------
    # Dedup / merge (used by the import pipeline)
    # ------------------------------------------------------------------

    def find_duplicate(self, candidate: Prospect) -> Optional[Prospect]:
        """Return the existing exact-duplicate prospect for a candidate, or None."""
        return self._collection.find_duplicate(candidate)

    def check_possible_duplicates(
        self, candidate: Prospect
    ) -> List[Prospect]:
        """Return existing possible (company+city) duplicates for a candidate."""
        return self._collection.check_possible_duplicates(candidate)

    def merge(self, existing: Prospect, incoming: Prospect) -> Prospect:
        """Merge an incoming prospect into an existing one (fills missing fields).

        Preserves the existing ``prospect_id`` and never overwrites stronger
        existing data with blanks. Missing fields are filled from the incoming
        record; tags are unioned; metadata/source provenance is preserved where
        useful; ``modified_at`` is updated.
        """
        existing.touch()

        def _fill(dst: str, src: str) -> str:
            return dst if dst.strip() else src.strip()

        # Merge scalar fields (never overwrite existing non-blank with blank).
        existing.website = _fill(existing.website, incoming.website)
        existing.domain = _fill(existing.domain, incoming.domain)
        existing.phone = _fill(existing.phone, incoming.phone)
        existing.company_name_for_ads = _fill(existing.company_name_for_ads, incoming.company_name_for_ads)
        existing.secondary_email = _fill(existing.secondary_email, incoming.secondary_email)
        existing.mobile_phone = _fill(existing.mobile_phone, incoming.mobile_phone)
        existing.work_direct_phone = _fill(existing.work_direct_phone, incoming.work_direct_phone)
        existing.company_phone = _fill(existing.company_phone, incoming.company_phone)
        existing.other_phone = _fill(existing.other_phone, incoming.other_phone)
        existing.email = _fill(existing.email, incoming.email)
        existing.address = _fill(existing.address, incoming.address)
        existing.city = _fill(existing.city, incoming.city)
        existing.state = _fill(existing.state, incoming.state)
        existing.postal_code = _fill(existing.postal_code, incoming.postal_code)
        existing.country = _fill(existing.country, incoming.country)
        existing.company_address = _fill(existing.company_address, incoming.company_address)
        existing.company_city = _fill(existing.company_city, incoming.company_city)
        existing.company_state = _fill(existing.company_state, incoming.company_state)
        existing.company_country = _fill(existing.company_country, incoming.company_country)
        existing.category = _fill(existing.category, incoming.category)
        existing.subcategory = _fill(existing.subcategory, incoming.subcategory)
        if not existing.naics_codes:
            existing.naics_codes = list(incoming.naics_codes)
        if not existing.sic_codes:
            existing.sic_codes = list(incoming.sic_codes)
        if not existing.company_keywords:
            existing.company_keywords = list(incoming.company_keywords)
        existing.industry = _fill(existing.industry, incoming.industry)
        existing.employee_count = _fill(existing.employee_count, incoming.employee_count)
        existing.annual_revenue = _fill(existing.annual_revenue, incoming.annual_revenue)
        existing.number_of_retail_locations = _fill(existing.number_of_retail_locations, incoming.number_of_retail_locations)
        existing.contact_name = _fill(existing.contact_name, incoming.contact_name)
        existing.contact_title = _fill(existing.contact_title, incoming.contact_title)
        existing.person_linkedin_url = _fill(existing.person_linkedin_url, incoming.person_linkedin_url)
        existing.company_linkedin_url = _fill(existing.company_linkedin_url, incoming.company_linkedin_url)
        existing.notes = _fill(existing.notes, incoming.notes)
        existing.market_id = _fill(existing.market_id, incoming.market_id)
        existing.location_hint = _fill(existing.location_hint, incoming.location_hint)
        existing.research_status = _fill(existing.research_status, incoming.research_status)

        # Sprint 5G: merge workflow fields (preserve existing non-blank values).
        existing.workflow_status = _fill(existing.workflow_status, incoming.workflow_status)
        existing.priority = _fill(existing.priority, incoming.priority)
        existing.next_action = _fill(existing.next_action, incoming.next_action)
        if existing.next_action_date is None and incoming.next_action_date:
            existing.next_action_date = incoming.next_action_date
        existing.workflow_notes = _fill(existing.workflow_notes, incoming.workflow_notes)

        # Preserve explicit source provenance; fill source/source_id if missing.
        existing.source = _fill(existing.source, incoming.source)
        existing.source_id = _fill(existing.source_id, incoming.source_id)

        # Union tags (preserve first-seen casing, no duplicates).
        merged_tags = list(existing.tags)
        for tag in incoming.tags:
            if tag.lower() not in {t.lower() for t in merged_tags}:
                merged_tags.append(tag)
        existing.tags = merged_tags

        # Merge metadata (incoming keys added only when absent).
        for key, value in incoming.metadata.items():
            if key not in existing.metadata:
                existing.metadata[key] = value

        return existing