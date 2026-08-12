"""JSON persistence for prospect generation jobs."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from gui.models.prospect_generation import ProspectGenerationJob

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_JOBS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "prospects",
)
DEFAULT_JOBS_PATH = os.path.join(DEFAULT_JOBS_DIR, "prospect_generation_jobs.json")


class ProspectGenerationCorruptionError(Exception):
    """Raised when the jobs file exists but cannot be parsed."""


class ProspectGenerationStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_JOBS_PATH)
        self._jobs: list[ProspectGenerationJob] = []
        self._schema_version = SCHEMA_VERSION
        self.load(safe_missing=True)

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[ProspectGenerationJob]:
        return sorted(self._jobs, key=lambda item: (item.created_at, item.id))

    def get(self, job_id: str) -> ProspectGenerationJob | None:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def upsert(self, job: ProspectGenerationJob) -> ProspectGenerationJob:
        existing = self.get(job.id)
        if existing is None:
            self._jobs.append(job)
        else:
            index = self._jobs.index(existing)
            self._jobs[index] = job
        return job

    def load(self, safe_missing: bool = False) -> None:
        if not os.path.exists(self._path):
            self._jobs = []
            self._schema_version = SCHEMA_VERSION
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ProspectGenerationCorruptionError(str(exc)) from exc
        jobs_raw = payload.get("jobs", []) if isinstance(payload, dict) else []
        self._schema_version = int((payload or {}).get("schema_version", SCHEMA_VERSION) or SCHEMA_VERSION)
        self._jobs = [
            ProspectGenerationJob.from_dict(item)
            for item in jobs_raw
            if isinstance(item, dict)
        ]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "jobs": [job.to_dict() for job in self._jobs],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)