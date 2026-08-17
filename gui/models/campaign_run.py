"""Sprint 5W durable Campaign Run scope model (Qt-free).

A ``CampaignRun`` represents the operator's current batch/workflow scope: a named
collection of stable prospect IDs being worked through the canonical pipeline.

It persists ONLY scope/identity information (run id, name, prospect ids, optional
source metadata, timestamps). It NEVER copies canonical stage state — research,
opportunities, projects, mockups, outreach, review decisions, package contents,
and Smartlead receipts all remain canonical in their existing stores and are
derived on demand by :class:`gui.services.campaign_run.CampaignRunService`.

Serialization follows the forward-compatible ``to_dict`` / ``from_dict`` pattern
used across the engine/GUI models: unknown persisted fields are ignored and
missing optional fields receive safe defaults.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_RUNS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "campaign_runs",
)
DEFAULT_RUNS_PATH = os.path.join(DEFAULT_RUNS_DIR, "campaign_runs.json")


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_id() -> str:
    """Return a stable, filesystem-safe, JSON-safe unique run id."""
    return f"run_{uuid.uuid4()}"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_ids(prospect_ids: Any) -> List[str]:
    """Coerce a persisted/iterable value to an ordered, de-duplicated id list."""
    if not prospect_ids:
        return []
    if isinstance(prospect_ids, (str, bytes)):
        prospect_ids = [prospect_ids]
    seen: set[str] = set()
    ordered: List[str] = []
    for raw in prospect_ids:
        pid = _clean(raw)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)
    return ordered


class CampaignRunError(Exception):
    """Base error for campaign-run persistence."""


class CampaignRunCorruptionError(CampaignRunError):
    """Raised when the runs file exists but cannot be parsed."""


@dataclass
class CampaignRun:
    """A named scope of prospect IDs being worked as one campaign run.

    Only identity/scope is persisted. Stage progress is derived from canonical
    stores by ``CampaignRunService`` — never copied here.
    """

    id: str = field(default_factory=new_run_id)
    name: str = ""
    prospect_ids: List[str] = field(default_factory=list)
    source: str = ""  # e.g. "import", "selection", "manual"
    source_id: str = ""  # optional import/selection reference
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        """Stamp updated_at to now (called on any mutation)."""
        self.updated_at = utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "prospect_ids": list(self.prospect_ids),
            "source": self.source,
            "source_id": self.source_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CampaignRun":
        raw = data if isinstance(data, dict) else {}
        return cls(
            id=_clean(raw.get("id")) or new_run_id(),
            name=_clean(raw.get("name")),
            prospect_ids=_dedupe_ids(raw.get("prospect_ids")),
            source=_clean(raw.get("source")),
            source_id=_clean(raw.get("source_id")),
            created_at=_clean(raw.get("created_at")) or utc_now_iso(),
            updated_at=_clean(raw.get("updated_at")) or utc_now_iso(),
        )


class CampaignRunStore:
    """JSON persistence for campaign runs (atomic writes, forward-compatible).

    Repository abstraction mirroring the pattern of ``ProspectStore`` /
    ``ResearchQueueStore``. Owns the on-disk layout::

        <root>/campaign_runs/campaign_runs.json

    Design points:
    - **Atomic writes** — a temporary file is written in the same directory and
      then ``os.replace``-d over the target, so a crash during save cannot easily
      corrupt the file.
    - **Git-ignored by default** — the default path lives under ``output/``.
    - **JSON only** — no pickle / binary serialization.
    - **Deterministic ordering** — ``list()`` is ordered by (``created_at``, ``id``).
    - **Forward compatible** — ``from_dict`` ignores unknown fields.
    """

    def __init__(
        self,
        path: Optional[Union[str, "os.PathLike[str]"]] = None,
    ) -> None:
        self._path = os.path.abspath(str(path)) if path else DEFAULT_RUNS_PATH
        self._runs: List[CampaignRun] = []
        self._schema_version = SCHEMA_VERSION
        self.load(safe_missing=True)

    @property
    def path(self) -> str:
        """The absolute path to the campaign runs file."""
        return self._path

    @property
    def schema_version(self) -> int:
        return self._schema_version

    def list(self) -> List[CampaignRun]:
        """All runs, deterministically ordered by (created_at, id)."""
        return sorted(self._runs, key=lambda r: (r.created_at, r.id))

    def get(self, run_id: str) -> Optional[CampaignRun]:
        rid = _clean(run_id)
        for run in self._runs:
            if run.id == rid:
                return run
        return None

    def exists(self, run_id: str) -> bool:
        return self.get(run_id) is not None

    def upsert(self, run: CampaignRun) -> CampaignRun:
        """Insert or replace a run in the snapshot and persist."""
        existing = self.get(run.id)
        if existing is None:
            self._runs.append(run)
        else:
            index = self._runs.index(existing)
            self._runs[index] = run
        run.touch()
        self.save()
        return run

    def delete(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None:
            return False
        self._runs.remove(run)
        self.save()
        return True

    def create(
        self,
        name: str,
        prospect_ids: Any,
        *,
        source: str = "",
        source_id: str = "",
    ) -> CampaignRun:
        """Create and persist a new run with the given scope."""
        run = CampaignRun(
            name=_clean(name) or "Campaign Run",
            prospect_ids=_dedupe_ids(prospect_ids),
            source=source,
            source_id=source_id,
        )
        return self.upsert(run)

    def rename(self, run_id: str, name: str) -> CampaignRun:
        run = self.get(run_id)
        if run is None:
            raise CampaignRunError(f"Campaign run {run_id!r} not found")
        run.name = _clean(name) or run.name
        return self.upsert(run)

    def add_prospects(self, run_id: str, prospect_ids: Any) -> CampaignRun:
        """Add prospect IDs to a run (preserving order, de-duplicated)."""
        run = self.get(run_id)
        if run is None:
            raise CampaignRunError(f"Campaign run {run_id!r} not found")
        existing = list(run.prospect_ids)
        for pid in _dedupe_ids(prospect_ids):
            if pid not in existing:
                existing.append(pid)
        run.prospect_ids = existing
        return self.upsert(run)

    def remove_prospects(self, run_id: str, prospect_ids: Any) -> CampaignRun:
        """Remove prospect IDs from a run WITHOUT deleting canonical data."""
        run = self.get(run_id)
        if run is None:
            raise CampaignRunError(f"Campaign run {run_id!r} not found")
        to_remove = set(_dedupe_ids(prospect_ids))
        run.prospect_ids = [pid for pid in run.prospect_ids if pid not in to_remove]
        return self.upsert(run)

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------
    def load(self, safe_missing: bool = False) -> None:
        """Load runs from disk, replacing the snapshot.

        Raises FileNotFoundError when missing (unless ``safe_missing``) and
        CampaignRunCorruptionError when it cannot be parsed.
        """
        if not os.path.exists(self._path):
            self._runs = []
            self._schema_version = SCHEMA_VERSION
            if safe_missing:
                return
            raise FileNotFoundError(f"No campaign runs file found at {self._path!r}")
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise CampaignRunCorruptionError(
                f"Corrupted campaign runs at {self._path!r}: {exc}"
            ) from exc
        runs_raw = payload.get("runs", []) if isinstance(payload, dict) else []
        self._schema_version = int(
            (payload or {}).get("schema_version", SCHEMA_VERSION) or SCHEMA_VERSION
        )
        self._runs = [
            CampaignRun.from_dict(item)
            for item in runs_raw
            if isinstance(item, dict)
        ]

    def save(self) -> None:
        """Persist the current snapshot atomically (tmp file + os.replace)."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: Dict[str, Any] = {
            "schema_version": self._schema_version,
            "runs": [run.to_dict() for run in self._runs],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)


