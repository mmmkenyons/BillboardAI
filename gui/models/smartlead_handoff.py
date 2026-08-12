"""Explicit models for Smartlead handoff preflight, mapping, and outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SMARTLEAD_PREFLIGHT_READY = "READY"
SMARTLEAD_PREFLIGHT_WARNING = "WARNING"
SMARTLEAD_PREFLIGHT_BLOCKED = "BLOCKED"
SMARTLEAD_PREFLIGHT_CONFLICT = "CONFLICT"

SMARTLEAD_PREFLIGHT_STATUSES: tuple[str, ...] = (
    SMARTLEAD_PREFLIGHT_READY,
    SMARTLEAD_PREFLIGHT_WARNING,
    SMARTLEAD_PREFLIGHT_BLOCKED,
    SMARTLEAD_PREFLIGHT_CONFLICT,
)

DEFAULT_SMARTLEAD_REQUIRED_FIELDS: tuple[str, ...] = (
    "email",
    "email_subject",
    "email_body",
)

DEFAULT_SMARTLEAD_OPTIONAL_FIELDS: tuple[str, ...] = (
    "first_name",
    "company",
    "mockup_relative_path",
    "contact_name",
    "website",
    "category",
    "city",
    "state",
    "headline",
    "cta",
    "personalization_basis",
    "prospect_id",
    "project_id",
    "generation_job_id",
)

DEFAULT_SMARTLEAD_COLUMN_ORDER: tuple[str, ...] = (
    "email",
    "first_name",
    "company",
    "email_subject",
    "email_body",
    "mockup_path",
    "contact_name",
    "website",
    "category",
    "city",
    "state",
    "headline",
    "cta",
    "personalization_basis",
    "prospect_id",
    "project_id",
    "generation_job_id",
)


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class CampaignFieldMapping:
    source_field: str
    destination_field: str
    required: bool = False
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_field": self.source_field,
            "destination_field": self.destination_field,
            "required": bool(self.required),
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CampaignFieldMapping":
        raw = data if isinstance(data, dict) else {}
        return cls(
            source_field=_clean(raw.get("source_field")),
            destination_field=_clean(raw.get("destination_field")),
            required=bool(raw.get("required", False)),
            enabled=bool(raw.get("enabled", True)),
        )


@dataclass(frozen=True)
class SmartleadHandoffProfile:
    profile_version: str
    name: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    field_mapping: tuple[CampaignFieldMapping, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_version": self.profile_version,
            "name": self.name,
            "required_fields": list(self.required_fields),
            "optional_fields": list(self.optional_fields),
            "field_mapping": [item.to_dict() for item in self.field_mapping],
            "created_at": self.created_at,
        }

    @classmethod
    def default(cls) -> "SmartleadHandoffProfile":
        created_at = datetime.now(timezone.utc).isoformat()
        mappings = (
            CampaignFieldMapping("email", "email", required=True, enabled=True),
            CampaignFieldMapping("first_name", "first_name", required=False, enabled=True),
            CampaignFieldMapping("company", "company", required=False, enabled=True),
            CampaignFieldMapping("email_subject", "email_subject", required=True, enabled=True),
            CampaignFieldMapping("email_body", "email_body", required=True, enabled=True),
            CampaignFieldMapping("mockup_relative_path", "mockup_path", required=False, enabled=True),
            CampaignFieldMapping("contact_name", "contact_name", required=False, enabled=True),
            CampaignFieldMapping("website", "website", required=False, enabled=True),
            CampaignFieldMapping("category", "category", required=False, enabled=True),
            CampaignFieldMapping("city", "city", required=False, enabled=True),
            CampaignFieldMapping("state", "state", required=False, enabled=True),
            CampaignFieldMapping("headline", "headline", required=False, enabled=True),
            CampaignFieldMapping("cta", "cta", required=False, enabled=True),
            CampaignFieldMapping("personalization_basis", "personalization_basis", required=False, enabled=True),
            CampaignFieldMapping("prospect_id", "prospect_id", required=False, enabled=True),
            CampaignFieldMapping("project_id", "project_id", required=False, enabled=True),
            CampaignFieldMapping("generation_job_id", "generation_job_id", required=False, enabled=True),
        )
        return cls(
            profile_version="5P",
            name="Smartlead Default Handoff",
            required_fields=DEFAULT_SMARTLEAD_REQUIRED_FIELDS,
            optional_fields=DEFAULT_SMARTLEAD_OPTIONAL_FIELDS,
            field_mapping=mappings,
            created_at=created_at,
        )


@dataclass(frozen=True)
class SmartleadPreflightRow:
    prospect_id: str
    company: str = ""
    email: str = ""
    status: str = SMARTLEAD_PREFLIGHT_BLOCKED
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    mapped_fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prospect_id": self.prospect_id,
            "company": self.company,
            "email": self.email,
            "status": self.status,
            "reason": "; ".join(reason for reason in self.reasons if _clean(reason)),
            "warning": "; ".join(warning for warning in self.warnings if _clean(warning)),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "mapped_fields": dict(self.mapped_fields),
        }


@dataclass(frozen=True)
class SmartleadHandoffSummary:
    total_approved_rows: int = 0
    ready: int = 0
    warnings: int = 0
    blocked: int = 0
    conflicts: int = 0
    output_csv_path: str = ""
    mapping_path: str = ""
    preflight_path: str = ""
    manifest_path: str = ""
    handoff_directory: str = ""

    @property
    def success(self) -> bool:
        return (self.ready + self.warnings) > 0


@dataclass(frozen=True)
class SmartleadHandoffResult:
    success: bool
    message: str
    package_directory: str = ""
    handoff_directory: str = ""
    smartlead_csv_path: str = ""
    mapping_path: str = ""
    preflight_path: str = ""
    manifest_path: str = ""
    summary: SmartleadHandoffSummary = field(default_factory=SmartleadHandoffSummary)
    profile: SmartleadHandoffProfile | None = None
    rows: tuple[SmartleadPreflightRow, ...] = ()
