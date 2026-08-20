"""Run-scoped Smartlead portable export models (Sprint 5Y).

These models describe a Sprint 5Y run export: a portable, Smartlead-ready
``smartlead.csv`` derived from an already-prepared run-scoped Smartlead package
and handoff. The exported lead data follows the established Smartlead handoff
column contract (see ``gui.models.smartlead_handoff``) with an additive
``mockup_url`` column. No secrets, credentials, or canonical stage state are
carried on these records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

# Export-time readiness statuses. These mirror the Smartlead handoff preflight
# statuses (READY/WARNING/BLOCKED/CONFLICT) plus EXCLUDED for run members that
# were not included in the prepared package at all.
SMARTLEAD_EXPORT_READY = "READY"
SMARTLEAD_EXPORT_WARNING = "WARNING"
SMARTLEAD_EXPORT_BLOCKED = "BLOCKED"
SMARTLEAD_EXPORT_CONFLICT = "CONFLICT"
SMARTLEAD_EXPORT_EXCLUDED = "EXCLUDED"

SMARTLEAD_EXPORT_STATUSES: tuple[str, ...] = (
    SMARTLEAD_EXPORT_READY,
    SMARTLEAD_EXPORT_WARNING,
    SMARTLEAD_EXPORT_BLOCKED,
    SMARTLEAD_EXPORT_CONFLICT,
    SMARTLEAD_EXPORT_EXCLUDED,
)

# The additive exported column that propagates a hosted public mockup URL when a
# valid hosted-asset receipt exists. Its meaning aligns with
# ``SMARTLEAD_CUSTOM_FIELD_MAP`` (``mockup_url -> bb_mockup_url``).
SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN = "mockup_url"


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class SmartleadRunExportRow:
    """One run member's export/readiness row.

    ``fields`` carries the full original handoff row (all established Smartlead
    columns) so the portable CSV can be reproduced verbatim plus ``mockup_url``.
    """

    prospect_id: str
    company: str = ""
    email: str = ""
    status: str = ""
    reason: str = ""
    warning: str = ""
    mockup_path: str = ""
    mockup_url: str = ""
    generation_job_id: str = ""
    project_id: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def exportable(self) -> bool:
        return self.status in (SMARTLEAD_EXPORT_READY, SMARTLEAD_EXPORT_WARNING)

    @property
    def has_public_url(self) -> bool:
        return bool(_clean(self.mockup_url))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fields"] = {str(key): str(value or "") for key, value in data.get("fields", {}).items()}
        return data


@dataclass(frozen=True)
class SmartleadRunExportReceipt:
    """Durable metadata for one run export (persisted on the run package record).

    Survives restart and is sufficient to locate/re-open the latest export.
    """

    campaign_run_id: str
    package_id: str
    export_directory: str
    smartlead_csv_path: str
    manifest_path: str
    exported_at: str
    total_members: int = 0
    exported_rows: int = 0
    ready: int = 0
    warning: int = 0
    blocked: int = 0
    conflict: int = 0
    excluded: int = 0
    with_public_url: int = 0
    local_fallback: int = 0

    fingerprint: str = ""
    exported_statuses: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadRunExportReceipt":
        raw = data if isinstance(data, dict) else {}

        def _int(key: str) -> int:
            try:
                return int(raw.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            campaign_run_id=_clean(raw.get("campaign_run_id")),
            package_id=_clean(raw.get("package_id")),
            export_directory=_clean(raw.get("export_directory")),
            smartlead_csv_path=_clean(raw.get("smartlead_csv_path")),
            manifest_path=_clean(raw.get("manifest_path")),
            exported_at=_clean(raw.get("exported_at")),
            total_members=_int("total_members"),
            exported_rows=_int("exported_rows"),
            ready=_int("ready"),
            warning=_int("warning"),
            blocked=_int("blocked"),
            conflict=_int("conflict"),
            excluded=_int("excluded"),
            with_public_url=_int("with_public_url"),
            local_fallback=_int("local_fallback"),
            fingerprint=_clean(raw.get("fingerprint")),
            exported_statuses={str(k): _clean(v) for k, v in dict(raw.get("exported_statuses") or {}).items()},
        )


@dataclass(frozen=True)
class SmartleadRunExportResult:
    """Structured result returned to the controller/UI after a run export.

    ``rows`` always reflects the full run member set (READY/WARNING/BLOCKED/
    CONFLICT/EXCLUDED) so the UI can present readiness. When an export is
    actually written, ``receipt`` and the artifact paths are populated.
    """

    success: bool
    message: str
    campaign_run_id: str = ""
    campaign_name: str = ""
    export_directory: str = ""
    smartlead_csv_path: str = ""
    manifest_path: str = ""
    receipt: SmartleadRunExportReceipt | None = None
    rows: tuple[SmartleadRunExportRow, ...] = ()
    total_members: int = 0
    exported_rows: int = 0
    ready: int = 0
    warning: int = 0
    blocked: int = 0
    conflict: int = 0
    excluded: int = 0
    with_public_url: int = 0
    local_fallback: int = 0

    def __post_init__(self) -> None:
        if self.receipt is None or self.receipt.exported_statuses:
            return
        exported_statuses = {
            row.prospect_id: row.status
            for row in self.rows
            if row.exportable and row.prospect_id
        }
        if exported_statuses:
            object.__setattr__(self, "receipt", replace(self.receipt, exported_statuses=exported_statuses))
