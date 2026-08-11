"""Sprint 5B durable research-queue store (Qt-free).

Repository abstraction for the batch research queue, mirroring the pattern of
``ProspectStore`` / ``ProjectStore``. It owns the on-disk layout:

    <root>/research/research_queue.json

The file is a single JSON document with a top-level ``schema_version`` and a
``jobs`` collection (each a serialized :class:`ResearchJob`).

Design points:

- **Atomic writes** — a temporary file is written in the same directory and then
  ``os.replace``-d over the target, so a crash during save cannot easily corrupt
  the file.
- **Clear corruption errors** — malformed JSON raises ``ResearchQueueCorruptionError``.
- **Git-ignored by default** — the default path lives under ``output/research``.
- **JSON only** — no pickle / binary serialization.
- **Deterministic ordering** — ``list()`` and filters are ordered by
  (``created_at``, ``job_id``).
- **Forward compatible** — ``from_dict`` ignores unknown fields.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from gui.models.research_job import (
    STATUS_SUCCEEDED,
    ResearchJob,
)

logger = logging.getLogger(__name__)

# Bump when the persisted schema changes incompatibly.
SCHEMA_VERSION = 1

# Default queue file (git-ignored via output/).
DEFAULT_RESEARCH_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "research",
)
DEFAULT_RESEARCH_QUEUE_PATH = os.path.join(DEFAULT_RESEARCH_DIR, "research_queue.json")


class ResearchQueueError(Exception):
    """Base error for research-queue persistence."""


class ResearchQueueCorruptionError(ResearchQueueError):
    """Raised when the queue file exists but cannot be parsed."""


class ResearchQueueCollection:
    """In-memory snapshot of all research jobs.

    Query helpers operate directly on the snapshot so callers can filter without
    touching disk. All list operations are deterministically ordered by
    (``created_at``, ``job_id``).
    """

    def __init__(
        self,
        jobs: Optional[List[ResearchJob]] = None,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.jobs: List[ResearchJob] = list(jobs or [])
        self.schema_version: int = schema_version

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "jobs": [j.to_dict() for j in self.jobs],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ResearchQueueCollection":
        if not isinstance(data, dict):
            raise ResearchQueueCorruptionError(
                "Research queue root must be a JSON object."
            )
        try:
            schema_version = int(data.get("schema_version") or SCHEMA_VERSION)
        except (TypeError, ValueError):
            schema_version = SCHEMA_VERSION
        raw_jobs = data.get("jobs")
        jobs: List[ResearchJob] = []
        if isinstance(raw_jobs, list):
            for item in raw_jobs:
                try:
                    jobs.append(ResearchJob.from_dict(item))
                except Exception as exc:  # noqa: BLE001 - skip poisoned entry
                    logger.warning("Skipping unreadable research job: %s", exc)
        return cls(jobs=jobs, schema_version=schema_version)
    # ------------------------------------------------------------------
    # Query helpers (deterministic order)
    # ------------------------------------------------------------------
    def sorted(self) -> List[ResearchJob]:
        return sorted(self.jobs)

    def get(self, job_id: str) -> Optional[ResearchJob]:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None

    def by_status(self, status: str) -> List[ResearchJob]:
        target = str(status or "")
        return sorted(
            [j for j in self.jobs if j.status == target],
            key=lambda j: (j.created_at, j.job_id),
        )

    def by_prospect(self, prospect_id: str) -> List[ResearchJob]:
        return sorted(
            [j for j in self.jobs if j.prospect_id == prospect_id],
            key=lambda j: (j.created_at, j.job_id),
        )

    def active_for_prospect(self, prospect_id: str) -> Optional[ResearchJob]:
        """Return the single active (pending/running/retry) job for a prospect."""
        for job in self.jobs:
            if job.prospect_id == prospect_id and job.is_active():
                return job
        return None

    def succeeded_for_prospect(self, prospect_id: str) -> Optional[ResearchJob]:
        for job in self.jobs:
            if job.prospect_id == prospect_id and job.status == STATUS_SUCCEEDED:
                return job
        return None


class ResearchQueueStore:
    """Create / save / load / list durable research jobs."""

    def __init__(
        self,
        path: Optional[Union[str, "os.PathLike[str]"]] = None,
        collection: Optional[ResearchQueueCollection] = None,
    ) -> None:
        self._path = (
            os.path.abspath(str(path)) if path else DEFAULT_RESEARCH_QUEUE_PATH
        )
        self._collection = (
            collection if collection is not None else ResearchQueueCollection()
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def path(self) -> str:
        """The absolute path to the research queue file."""
        return self._path

    @property
    def collection(self) -> ResearchQueueCollection:
        """The current in-memory job snapshot managed by this store."""
        return self._collection

    def exists(self) -> bool:
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

    def load(self) -> ResearchQueueCollection:
        """Load research jobs from disk, replacing the snapshot.

        Raises FileNotFoundError when missing and
        ResearchQueueCorruptionError when it cannot be parsed.
        """
        if not os.path.isfile(self._path):
            raise FileNotFoundError(
                f"No research queue file found at {self._path!r}"
            )
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ResearchQueueCorruptionError(
                f"Corrupted research queue at {self._path!r}: {exc}"
            ) from exc
        self._collection = ResearchQueueCollection.from_dict(data)
        return self._collection

    def load_or_empty(self) -> ResearchQueueCollection:
        """Load if present; otherwise keep an empty snapshot (no raise)."""
        if self.exists():
            return self.load()
        self._collection = ResearchQueueCollection()
        return self._collection

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def put(self, job: ResearchJob) -> ResearchJob:
        """Insert or replace a job in the snapshot and persist."""
        existing = self._collection.get(job.job_id)
        if existing is None:
            self._collection.jobs.append(job)
        else:
            index = self._collection.jobs.index(existing)
            self._collection.jobs[index] = job
        self.save()
        return job

    def get(self, job_id: str) -> Optional[ResearchJob]:
        return self._collection.get(job_id)

    def list(self) -> List[ResearchJob]:
        return self._collection.sorted()

    def remove(self, job_id: str) -> bool:
        job = self._collection.get(job_id)
        if job is None:
            return False
        self._collection.jobs.remove(job)
        self.save()
        return True
