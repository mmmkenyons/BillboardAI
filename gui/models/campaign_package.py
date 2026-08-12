"""Explicit models for campaign package build results and manifest data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class CampaignPackageProspect:
    prospect_id: str
    company: str
    email: str
    status: str
    reason: str = ""
    warning: str = ""
    generation_job_id: str = ""
    project_id: str = ""
    opportunity_id: str = ""
    location_id: str = ""
    placement_id: str = ""
    mockup_filename: str = ""
    mockup_relative_path: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        return {key: str(value or "") for key, value in data.items()}


@dataclass(frozen=True)
class CampaignPackageManifest:
    package_version: str
    package_id: str
    created_at: str
    campaign_name: str
    package_directory: str
    csv_filename: str
    validation_filename: str
    assets_directory: str
    total_selected: int
    total_exportable: int
    total_blocked: int
    total_warnings: int
    prospects: tuple[CampaignPackageProspect, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["prospects"] = [prospect.to_dict() for prospect in self.prospects]
        return payload


@dataclass(frozen=True)
class CampaignPackageResult:
    success: bool
    message: str
    package_directory: str = ""
    campaign_csv_path: str = ""
    manifest_path: str = ""
    validation_csv_path: str = ""
    included_count: int = 0
    blocked_count: int = 0
    warning_count: int = 0
    selected_count: int = 0
    manifest: CampaignPackageManifest | None = None
    blocked_reasons: tuple[str, ...] = field(default_factory=tuple)