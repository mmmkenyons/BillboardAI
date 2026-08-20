"""Sprint 5AD persisted campaign assembly snapshots.

An assembly snapshot records the operator's outreach-package intent for an
existing CampaignRun.  Canonical prospect, generation, project, review, package,
and Smartlead export data stay in their existing stores; this model stores only
IDs, compact readiness snapshots, mapping fingerprint, and export references so
an exported package remains auditable after later prospect edits.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


ASSEMBLY_STATUS_READY = "READY"
ASSEMBLY_STATUS_WARNING = "WARNING"
ASSEMBLY_STATUS_BLOCKED = "BLOCKED"
ASSEMBLY_STATUS_CONFLICT = "CONFLICT"
ASSEMBLY_STATUS_EXCLUDED = "EXCLUDED"

ASSEMBLY_STATUSES = (
    ASSEMBLY_STATUS_READY,
    ASSEMBLY_STATUS_WARNING,
    ASSEMBLY_STATUS_BLOCKED,
    ASSEMBLY_STATUS_CONFLICT,
    ASSEMBLY_STATUS_EXCLUDED,
)

DEFAULT_CAMPAIGN_ASSEMBLY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "campaign_assemblies",
)
DEFAULT_CAMPAIGN_ASSEMBLY_PATH = os.path.join(DEFAULT_CAMPAIGN_ASSEMBLY_DIR, "campaign_assemblies.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class CampaignAssemblyReason:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": _clean(self.code), "message": _clean(self.message)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CampaignAssemblyReason":
        raw = data if isinstance(data, dict) else {}
        return cls(code=_clean(raw.get("code")), message=_clean(raw.get("message")))


@dataclass(frozen=True)
class OutreachReadinessResult:
    prospect_id: str
    status: str
    blocking_reasons: tuple[CampaignAssemblyReason, ...] = ()
    warning_reasons: tuple[CampaignAssemblyReason, ...] = ()
    email: str = ""
    contact_name: str = ""
    company: str = ""
    project_id: str = ""
    generation_job_id: str = ""
    mockup_path: str = ""
    mockup_url: str = ""
    headline: str = ""
    cta: str = ""
    personalization_basis: str = ""
    profile_url: str = ""
    personalization_complete: int = 0
    personalization_total: int = 0
    included: bool = False

    @property
    def exportable(self) -> bool:
        return self.status in {ASSEMBLY_STATUS_READY, ASSEMBLY_STATUS_WARNING}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["blocking_reasons"] = [reason.to_dict() for reason in self.blocking_reasons]
        data["warning_reasons"] = [reason.to_dict() for reason in self.warning_reasons]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OutreachReadinessResult":
        raw = data if isinstance(data, dict) else {}
        status = _clean(raw.get("status")).upper() or ASSEMBLY_STATUS_BLOCKED
        if status not in ASSEMBLY_STATUSES:
            status = ASSEMBLY_STATUS_BLOCKED
        return cls(
            prospect_id=_clean(raw.get("prospect_id")),
            status=status,
            blocking_reasons=tuple(CampaignAssemblyReason.from_dict(item) for item in list(raw.get("blocking_reasons") or []) if isinstance(item, dict)),
            warning_reasons=tuple(CampaignAssemblyReason.from_dict(item) for item in list(raw.get("warning_reasons") or []) if isinstance(item, dict)),
            email=_clean(raw.get("email")),
            contact_name=_clean(raw.get("contact_name")),
            company=_clean(raw.get("company")),
            project_id=_clean(raw.get("project_id")),
            generation_job_id=_clean(raw.get("generation_job_id")),
            mockup_path=_clean(raw.get("mockup_path")),
            mockup_url=_clean(raw.get("mockup_url")),
            headline=_clean(raw.get("headline")),
            cta=_clean(raw.get("cta")),
            personalization_basis=_clean(raw.get("personalization_basis")),
            profile_url=_clean(raw.get("profile_url")),
            personalization_complete=int(raw.get("personalization_complete") or 0),
            personalization_total=int(raw.get("personalization_total") or 0),
            included=bool(raw.get("included", False)),
        )


@dataclass(frozen=True)
class CampaignAssemblySnapshot:
    campaign_run_id: str
    name: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    modified_at: str = field(default_factory=utc_now_iso)
    prospect_ids_considered: tuple[str, ...] = ()
    included_prospect_ids: tuple[str, ...] = ()
    excluded_prospect_ids: tuple[str, ...] = ()
    readiness: tuple[OutreachReadinessResult, ...] = ()
    mapping_fingerprint: str = ""
    package_directory: str = ""
    handoff_directory: str = ""
    smartlead_csv_path: str = ""
    export_receipt: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_run_id": self.campaign_run_id,
            "name": self.name,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "prospect_ids_considered": list(self.prospect_ids_considered),
            "included_prospect_ids": list(self.included_prospect_ids),
            "excluded_prospect_ids": list(self.excluded_prospect_ids),
            "readiness": [item.to_dict() for item in self.readiness],
            "mapping_fingerprint": self.mapping_fingerprint,
            "package_directory": self.package_directory,
            "handoff_directory": self.handoff_directory,
            "smartlead_csv_path": self.smartlead_csv_path,
            "export_receipt": dict(self.export_receipt or {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CampaignAssemblySnapshot":
        raw = data if isinstance(data, dict) else {}
        return cls(
            campaign_run_id=_clean(raw.get("campaign_run_id")),
            name=_clean(raw.get("name")),
            created_at=_clean(raw.get("created_at")),
            modified_at=_clean(raw.get("modified_at")),
            prospect_ids_considered=tuple(_clean(x) for x in list(raw.get("prospect_ids_considered") or []) if _clean(x)),
            included_prospect_ids=tuple(_clean(x) for x in list(raw.get("included_prospect_ids") or []) if _clean(x)),
            excluded_prospect_ids=tuple(_clean(x) for x in list(raw.get("excluded_prospect_ids") or []) if _clean(x)),
            readiness=tuple(OutreachReadinessResult.from_dict(item) for item in list(raw.get("readiness") or []) if isinstance(item, dict)),
            mapping_fingerprint=_clean(raw.get("mapping_fingerprint")),
            package_directory=_clean(raw.get("package_directory")),
            handoff_directory=_clean(raw.get("handoff_directory")),
            smartlead_csv_path=_clean(raw.get("smartlead_csv_path")),
            export_receipt=dict(raw.get("export_receipt") or {}),
        )


class CampaignAssemblyStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_CAMPAIGN_ASSEMBLY_PATH)
        self._snapshots: dict[str, CampaignAssemblySnapshot] = {}
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def get(self, campaign_run_id: str) -> CampaignAssemblySnapshot | None:
        return self._snapshots.get(_clean(campaign_run_id))

    def upsert(self, snapshot: CampaignAssemblySnapshot) -> CampaignAssemblySnapshot:
        if snapshot.campaign_run_id:
            self._snapshots[snapshot.campaign_run_id] = snapshot
            self.save()
        return snapshot

    def list(self) -> list[CampaignAssemblySnapshot]:
        return [self._snapshots[key] for key in sorted(self._snapshots)]

    def load(self, safe_missing: bool = False, safe_corrupt: bool = False) -> None:
        if not os.path.exists(self._path):
            self._snapshots = {}
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            if safe_corrupt:
                self._snapshots = {}
                return
            raise
        snapshots: dict[str, CampaignAssemblySnapshot] = {}
        for item in list((payload or {}).get("snapshots") or []):
            if isinstance(item, dict):
                snapshot = CampaignAssemblySnapshot.from_dict(item)
                if snapshot.campaign_run_id:
                    snapshots[snapshot.campaign_run_id] = snapshot
        self._snapshots = snapshots

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "snapshots": [s.to_dict() for s in self.list()]}, handle, indent=2)
        os.replace(tmp, self._path)