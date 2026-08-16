"""Sprint 5A prospect workspace service (pure Python, Qt-free).

Owns the DOMAIN/BUSINESS logic for managing prospects so it is testable without
a desktop:

    ProspectWorkspacePage
        -> ProspectController (Qt signals, selection)
            -> ProspectWorkspaceService (logic + persistence)
                -> ProspectStore (JSON on disk)

Responsibilities: load prospects (empty when no file, never crash); list /
filter / search prospects; create / update / archive; research-readiness;
duplicate detection; CSV import orchestration (delegating to
:class:`~gui.services.prospect_csv_import.ProspectCsvImporter`).

Design rules honored (mirroring the inventory workspace):

- **No raw widgets.** This module never imports Qt.
- **No direct JSON writes.** Persistence flows through ``ProspectStore``.
- **No web requests.** Import/normalization/dedup are all local & deterministic.
- **No Project auto-creation.** Importing prospects never creates Projects.
- **Explicit validation.** Invalid values raise :class:`ProspectValidationError`
  with concise messages.

A clean future-facing hook :meth:`create_project_from_prospect` is provided but
**not** called automatically — a Project should be created only when research
/work begins, never at import time.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gui.models.prospect import (
    PRIORITIES,
    PROSPECT_STATUSES,
    WORKFLOW_STATUSES,
    Contact,
    Prospect,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_state,
    normalize_tags,
    normalize_website,
    utc_now_iso,
)
from gui.models.prospect_store import (
    ProspectCollection,
    ProspectCorruptionError,
    ProspectStore,
)
from gui.services.prospect_csv_import import (
    ProspectCsvImporter,
    ProspectImportError,
    ProspectImportResult,
)

logger = logging.getLogger(__name__)

# Sentinels distinguish "leave unchanged" from "set to None" internally.
_UNSET = object()

# Fields exposed to the manual editor (create/edit).
EDITABLE_FIELDS = (
    "company_name",
    "website",
    "phone",
    "email",
    "city",
    "state",
    "category",
    "contact_name",
    "contact_title",
    "notes",
    "tags",
)


class ProspectValidationError(ValueError):
    """Raised when a user action would create an invalid prospect value."""


def _clean(value: Any) -> str:
    """Trim a value to a string (None -> empty)."""
    if value is None:
        return ""
    return str(value).strip()
class ProspectValidationError(ValueError):
    """Raised when a user action would create an invalid prospect value."""


class ProspectWorkspaceService:
    """Stateless (per-call) domain operations over a ``ProspectStore``."""

    def __init__(self, store: Optional[ProspectStore] = None) -> None:
        self._store = store or ProspectStore()
        self._importer = ProspectCsvImporter(self._store)

    # ------------------------------------------------------------------
    # Store / load
    # ------------------------------------------------------------------

    @property
    def store(self) -> ProspectStore:
        """The underlying repository (used by the controller for persistence)."""
        return self._store

    @property
    def importer(self) -> ProspectCsvImporter:
        """The CSV importer bound to this service's store."""
        return self._importer

    def ensure_loaded(self) -> ProspectCollection:
        """Load prospects (empty when missing) and return the snapshot.

        Corruption is surfaced: we do NOT swallow a corrupted file (caller wants
        to know), but a missing file is treated as an empty store.
        """
        if self._store.exists():
            self._store.load_or_empty()
        return self._store.collection

    def load(self) -> None:
        """Load prospects; a missing store becomes empty (never crashes)."""
        self.ensure_loaded()

    def reload(self) -> None:
        """Re-load from disk, surfacing corruption clearly."""
        self.ensure_loaded()

    def save(self) -> None:
        """Persist the current prospect snapshot atomically."""
        self._store.save()

    # ------------------------------------------------------------------
    # Listing / filters
    # ------------------------------------------------------------------

    def list_prospects(self) -> List[Prospect]:
        """Return all prospects, deterministically ordered by id."""
        self.ensure_loaded()
        return self._store.list()

    def get_prospect(self, prospect_id: str) -> Optional[Prospect]:
        self.ensure_loaded()
        return self._store.get(prospect_id)

    def list_by_status(self, status: str) -> List[Prospect]:
        self.ensure_loaded()
        return self._store.collection.by_status(status)

    def list_by_category(self, category: str) -> List[Prospect]:
        self.ensure_loaded()
        return self._store.collection.by_category(category)

    def search(self, query: str) -> List[Prospect]:
        self.ensure_loaded()
        return self._store.collection.search(query)

    def categories(self) -> List[str]:
        """Distinct prospect categories (deterministic, used for the filter)."""
        self.ensure_loaded()
        seen: Dict[str, str] = {}
        for p in self._store.collection.prospects:
            if p.category:
                key = p.category.lower()
                if key not in seen:
                    seen[key] = p.category
        return sorted(seen.values(), key=str.lower)

    def statuses(self) -> List[str]:
        """All prospect statuses, in a stable display order."""
        return list(PROSPECT_STATUSES)

    def imported_count(self) -> int:
        self.ensure_loaded()
        return len(self._store.collection.prospects)
    # ------------------------------------------------------------------
    # Mutations (create / update / archive)
    # ------------------------------------------------------------------

    def create_prospect(self, **fields) -> Prospect:
        """Create a new prospect from editor fields. May raise validation error."""
        self.ensure_loaded()
        prospect = self._prospect_from_fields(Prospect(), fields)
        if not prospect.company_name:
            raise ProspectValidationError(
                "company name is required to add a prospect"
            )
        self._store.create(prospect)
        prospect.status = (
            "READY_FOR_RESEARCH"
            if prospect.is_ready_for_research()
            else "IMPORTED"
        )
        self.save()
        return prospect

    def update_prospect(self, prospect_id: str, **fields) -> Prospect:
        """Update an existing prospect's editable fields (fills only provided)."""
        self.ensure_loaded()
        current = self._store.get(prospect_id)
        if current is None:
            raise ProspectValidationError(f"Prospect {prospect_id!r} not found.")
        current = self._prospect_from_fields(current, fields)
        if not current.company_name:
            raise ProspectValidationError("company name is required")
        # Recompute research readiness based on current website/domain.
        current.status = (
            "READY_FOR_RESEARCH"
            if (current.domain or current.website)
            else current.status
        )
        current.touch()
        self.save()
        return current

    def archive_prospect(self, prospect_id: str) -> Optional[Prospect]:
        """Mark a prospect as ARCHIVED and persist. Returns the prospect."""
        self.ensure_loaded()
        prospect = self._store.archive(prospect_id)
        if prospect is not None:
            self.save()
        return prospect

    def set_status(self, prospect_id: str, status: str) -> Optional[Prospect]:
        """Set a prospect's lifecycle status (validated) and persist."""
        if status not in PROSPECT_STATUSES:
            raise ProspectValidationError(f"Unknown prospect status: {status!r}")
        self.ensure_loaded()
        prospect = self._store.get(prospect_id)
        if prospect is None:
            raise ProspectValidationError(f"Prospect {prospect_id!r} not found.")
        prospect.status = status
        prospect.touch()
        self.save()
        return prospect

    # ------------------------------------------------------------------
    # Sprint 5G: sales follow-up workflow
    # ------------------------------------------------------------------

    def update_workflow(
        self,
        prospect_id: str,
        *,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        next_action: Optional[str] = None,
        next_action_date: Any = _UNSET,
        notes: Optional[str] = None,
    ) -> Prospect:
        """Update the sales follow-up workflow fields for a prospect.

        Partial updates are supported: ``None`` means "leave unchanged".
        ``next_action_date=_UNSET`` means "leave unchanged"; ``None`` clears the
        date. Values are validated against the controlled enums and persisted
        through the authoritative ProspectStore.

        No scraping, enrichment, research, or opportunity recomputation is
        performed as a side effect.
        """
        self.ensure_loaded()
        prospect = self._store.get(prospect_id)
        if prospect is None:
            raise ProspectValidationError(f"Prospect {prospect_id!r} not found.")

        if status is not None:
            if status not in WORKFLOW_STATUSES:
                raise ProspectValidationError(
                    f"Unknown workflow status: {status!r}"
                )
            prospect.workflow_status = status

        if priority is not None:
            if priority not in PRIORITIES:
                raise ProspectValidationError(
                    f"Unknown workflow priority: {priority!r}"
                )
            prospect.priority = priority

        if next_action is not None:
            prospect.next_action = str(next_action).strip()

        if notes is not None:
            prospect.workflow_notes = str(notes).strip()

        if next_action_date is not _UNSET:
            if next_action_date is None or str(next_action_date).strip() == "":
                prospect.next_action_date = None
            else:
                from datetime import date

                try:
                    prospect.next_action_date = date.fromisoformat(
                        str(next_action_date).strip()
                    ).isoformat()
                except (TypeError, ValueError) as exc:
                    raise ProspectValidationError(
                        f"Invalid next-action date: {next_action_date!r}"
                    ) from exc

        prospect.touch()
        self.save()
        return prospect

    # ------------------------------------------------------------------
    # CSV import
    # ------------------------------------------------------------------

    def import_csv(
        self,
        content: str,
        source: str = "csv_import",
        mapping: Optional[Dict[str, str]] = None,
    ) -> ProspectImportResult:
        """Import prospects from CSV text. Persists merged/imported rows.

        Rows are added/merged in the store; this method does NOT auto-create any
        Project. Returns the structured import result for the UI.
        """
        self.ensure_loaded()
        result = self._importer.import_text(content, source=source, mapping=mapping)
        if result.imported or result.merged:
            self.save()
        return result

    def import_csv_file(
        self,
        path: str,
        source: str = "csv_import",
        mapping: Optional[Dict[str, str]] = None,
    ) -> ProspectImportResult:
        """Import prospects from a CSV file path."""
        self.ensure_loaded()
        result = self._importer.import_file(path, source=source, mapping=mapping)
        if result.imported or result.merged:
            self.save()
        return result

    # ------------------------------------------------------------------
    # Future-facing: Project creation (NOT called automatically)
    # ------------------------------------------------------------------

    def create_project_from_prospect(self, prospect_id: str) -> Any:
        """Create a Project for a prospect when research/work begins.

        This method is deliberately NOT invoked by import or by any automatic
        pipeline. A Project should be created only when the user starts
        work/research on a specific prospect. Raises NotImplementedError until
        the project-workspace link is wired in a later sprint.
        """
        raise NotImplementedError(
            "Project creation from a prospect is wired in a later sprint; "
            "projects are never auto-created at import time."
        )
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prospect_from_fields(
        self, base: Prospect, fields: Dict[str, Any]
    ) -> Prospect:
        """Apply editable fields onto a prospect with normalization."""

        def _val(key: str) -> str:
            if key not in fields or fields[key] is _UNSET:
                return _clean(getattr(base, key))
            return _clean(fields[key])

        website_raw = _val("website")
        website = normalize_website(website_raw)

        base.company_name = _val("company_name")
        base.website = website
        base.domain = normalize_domain(website) if website else _val("domain")
        base.phone = normalize_phone(_val("phone"))
        base.email = normalize_email(_val("email"))
        base.city = _val("city")
        if fields.get("state", _UNSET) is not _UNSET:
            base.state = normalize_state(_val("state"))
        base.category = _clean(_val("category")).strip().lower()
        base.contact_name = _val("contact_name")
        base.contact_title = _val("contact_title")
        base.notes = _val("notes")
        if fields.get("tags", _UNSET) is not _UNSET:
            base.tags = normalize_tags(fields["tags"])
        return base