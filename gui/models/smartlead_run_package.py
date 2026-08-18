"""Persistent run-scoped Smartlead package state for Sprint 5X."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SmartleadRunPackageEntry:
    prospect_id: str
    status: str = ""
    project_id: str = ""
    generation_job_id: str = ""
    email: str = ""
    blocker: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        return {key: str(value or "") for key, value in data.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadRunPackageEntry":
        raw = data if isinstance(data, dict) else {}
        return cls(
            prospect_id=str(raw.get("prospect_id") or "").strip(),
            status=str(raw.get("status") or "").strip(),
            project_id=str(raw.get("project_id") or "").strip(),
            generation_job_id=str(raw.get("generation_job_id") or "").strip(),
            email=str(raw.get("email") or "").strip(),
            blocker=str(raw.get("blocker") or "").strip(),
        )


@dataclass(frozen=True)
class SmartleadRunPackageRecord:
    campaign_run_id: str
    package_id: str = ""
    package_directory: str = ""
    package_manifest_path: str = ""
    handoff_directory: str = ""
    handoff_manifest_path: str = ""
    smartlead_csv_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: str = "NOT_PREPARED"
    package_hash: str = ""
    total_members: int = 0
    ready_count: int = 0
    blocked_count: int = 0
    packaged_count: int = 0
    entries: tuple[SmartleadRunPackageEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadRunPackageRecord":
        raw = data if isinstance(data, dict) else {}
        return cls(
            campaign_run_id=str(raw.get("campaign_run_id") or "").strip(),
            package_id=str(raw.get("package_id") or "").strip(),
            package_directory=str(raw.get("package_directory") or "").strip(),
            package_manifest_path=str(raw.get("package_manifest_path") or "").strip(),
            handoff_directory=str(raw.get("handoff_directory") or "").strip(),
            handoff_manifest_path=str(raw.get("handoff_manifest_path") or "").strip(),
            smartlead_csv_path=str(raw.get("smartlead_csv_path") or "").strip(),
            created_at=str(raw.get("created_at") or "").strip(),
            updated_at=str(raw.get("updated_at") or "").strip(),
            status=str(raw.get("status") or "NOT_PREPARED").strip() or "NOT_PREPARED",
            package_hash=str(raw.get("package_hash") or "").strip(),
            total_members=int(raw.get("total_members") or 0),
            ready_count=int(raw.get("ready_count") or 0),
            blocked_count=int(raw.get("blocked_count") or 0),
            packaged_count=int(raw.get("packaged_count") or 0),
            entries=tuple(
                SmartleadRunPackageEntry.from_dict(item)
                for item in list(raw.get("entries") or [])
                if isinstance(item, dict)
            ),
        )


DEFAULT_SMARTLEAD_RUN_PACKAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "smartlead",
)
DEFAULT_SMARTLEAD_RUN_PACKAGE_PATH = os.path.join(
    DEFAULT_SMARTLEAD_RUN_PACKAGE_DIR,
    "run_packages.json",
)


class SmartleadRunPackageStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_SMARTLEAD_RUN_PACKAGE_PATH)
        self._records: dict[str, SmartleadRunPackageRecord] = {}
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def get(self, campaign_run_id: str) -> SmartleadRunPackageRecord | None:
        return self._records.get(str(campaign_run_id or "").strip())

    def upsert(self, record: SmartleadRunPackageRecord) -> SmartleadRunPackageRecord:
        key = str(record.campaign_run_id or "").strip()
        if key:
            self._records[key] = record
        return record

    def list(self) -> list[SmartleadRunPackageRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def load(self, safe_missing: bool = False, safe_corrupt: bool = False) -> None:
        if not os.path.exists(self._path):
            self._records = {}
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            if safe_corrupt:
                self._records = {}
                return
            raise
        records: dict[str, SmartleadRunPackageRecord] = {}
        for item in list((payload or {}).get("records") or []):
            if not isinstance(item, dict):
                continue
            record = SmartleadRunPackageRecord.from_dict(item)
            if record.campaign_run_id:
                records[record.campaign_run_id] = record
        self._records = records

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload = {
            "schema_version": 1,
            "records": [record.to_dict() for record in self.list()],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)