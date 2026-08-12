"""Build deterministic reviewable campaign packages from canonical export data."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from gui.models.campaign_package import (
    CampaignPackageManifest,
    CampaignPackageProspect,
    CampaignPackageResult,
)
from gui.models.prospect_generation import OpportunityGenerationContext
from gui.services.campaign_export import (
    EXPORT_STATUS_BLOCKED,
    EXPORT_STATUS_WARNING,
    CampaignExportRow,
    CampaignExportService,
)

PACKAGE_VERSION = "5N"
CAMPAIGN_CSV_COLUMNS: tuple[str, ...] = (
    "email",
    "first_name",
    "contact_name",
    "company",
    "email_subject",
    "email_body",
    "email_opening_line",
    "personalization_basis",
    "website",
    "category",
    "city",
    "state",
    "headline",
    "cta",
    "mockup_relative_path",
    "prospect_id",
    "generation_job_id",
    "project_id",
    "opportunity_id",
    "location_id",
    "placement_id",
)
VALIDATION_CSV_COLUMNS: tuple[str, ...] = (
    "prospect_id",
    "company",
    "email",
    "status",
    "reason",
    "warning",
    "generation_job_id",
    "project_id",
    "opportunity_id",
    "location_id",
    "placement_id",
    "mockup_relative_path",
)


@dataclass(frozen=True)
class _IncludedProspect:
    manifest_entry: CampaignPackageProspect
    export_row: CampaignExportRow
    source_path: str


class CampaignPackageService:
    def __init__(self, *, export_service: CampaignExportService) -> None:
        self._export_service = export_service

    def build_package(
        self,
        prospect_ids: list[str],
        destination: str,
        campaign_name: str | None = None,
    ) -> CampaignPackageResult:
        ordered_ids = self._ordered_ids(prospect_ids)
        selected_count = len(ordered_ids)
        if selected_count == 0:
            return CampaignPackageResult(success=False, message="No prospects selected.")

        package_label = self._sanitize_package_name(campaign_name or "campaign_package")
        destination_root = os.path.abspath(destination)
        os.makedirs(destination_root, exist_ok=True)
        final_dir = self._next_available_package_dir(destination_root, package_label)
        temp_dir = os.path.join(destination_root, f".{os.path.basename(final_dir)}.tmp")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        package_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        included: list[_IncludedProspect] = []
        manifest_entries: list[CampaignPackageProspect] = []
        blocked_reasons: list[str] = []
        warning_count = 0

        filename_registry: dict[str, int] = {}
        for prospect_id in ordered_ids:
            eligibility, row, resolved = self._export_service.resolve_for_package(prospect_id)
            if eligibility.status == EXPORT_STATUS_BLOCKED or row is None or resolved is None:
                reason = "; ".join(eligibility.reasons) or "Prospect is not exportable."
                blocked_reasons.append(f"{prospect_id}: {reason}")
                manifest_entries.append(
                    CampaignPackageProspect(
                        prospect_id=prospect_id,
                        company=row.company if row is not None else (resolved.prospect.company_name if resolved is not None else ""),
                        email=row.email if row is not None else (resolved.prospect.email if resolved is not None else ""),
                        status=EXPORT_STATUS_BLOCKED,
                        reason=reason,
                        warning="; ".join(eligibility.warnings),
                        generation_job_id=eligibility.selected_job_id,
                        project_id=eligibility.selected_project_id,
                    )
                )
                continue

            source_path = os.path.abspath(resolved.concept.image_path or resolved.job.result_path)
            if not source_path or not os.path.isfile(source_path):
                reason = "Source mockup file no longer exists."
                blocked_reasons.append(f"{prospect_id}: {reason}")
                manifest_entries.append(
                    CampaignPackageProspect(
                        prospect_id=row.prospect_id,
                        company=row.company,
                        email=row.email,
                        status=EXPORT_STATUS_BLOCKED,
                        reason=reason,
                        warning="; ".join(eligibility.warnings),
                        generation_job_id=row.generation_job_id,
                        project_id=row.project_id,
                        opportunity_id=row.opportunity_id,
                        location_id=row.location_id,
                        placement_id=row.placement_id,
                    )
                )
                continue

            relative_path = os.path.join("mockups", self._stable_asset_filename(row, source_path, filename_registry)).replace("\\", "/")
            status = eligibility.status
            warning_text = "; ".join(eligibility.warnings)
            if status == EXPORT_STATUS_WARNING:
                warning_count += 1
            entry = CampaignPackageProspect(
                prospect_id=row.prospect_id,
                company=row.company,
                email=row.email,
                status=status,
                reason="",
                warning=warning_text,
                generation_job_id=row.generation_job_id,
                project_id=row.project_id,
                opportunity_id=row.opportunity_id,
                location_id=row.location_id,
                placement_id=row.placement_id,
                mockup_filename=os.path.basename(relative_path),
                mockup_relative_path=relative_path,
            )
            manifest_entries.append(entry)
            included.append(_IncludedProspect(manifest_entry=entry, export_row=row, source_path=source_path))

        if not included:
            return CampaignPackageResult(
                success=False,
                message="No exportable prospects for campaign package.",
                blocked_count=len(manifest_entries),
                selected_count=selected_count,
                warning_count=warning_count,
                blocked_reasons=tuple(blocked_reasons),
            )

        try:
            os.makedirs(temp_dir, exist_ok=False)
            mockups_dir = os.path.join(temp_dir, "mockups")
            os.makedirs(mockups_dir, exist_ok=True)

            for item in included:
                shutil.copy2(item.source_path, os.path.join(temp_dir, item.manifest_entry.mockup_relative_path.replace("/", os.sep)))

            campaign_csv_path = os.path.join(temp_dir, "campaign.csv")
            validation_csv_path = os.path.join(temp_dir, "validation.csv")
            manifest_path = os.path.join(temp_dir, "manifest.json")

            self._write_campaign_csv(campaign_csv_path, included)
            self._write_validation_csv(validation_csv_path, manifest_entries)

            manifest = CampaignPackageManifest(
                package_version=PACKAGE_VERSION,
                package_id=package_id,
                created_at=created_at,
                campaign_name=campaign_name or package_label,
                package_directory=os.path.basename(final_dir),
                csv_filename="campaign.csv",
                validation_filename="validation.csv",
                assets_directory="mockups",
                total_selected=selected_count,
                total_exportable=len(included),
                total_blocked=len([entry for entry in manifest_entries if entry.status == EXPORT_STATUS_BLOCKED]),
                total_warnings=len([entry for entry in manifest_entries if entry.status == EXPORT_STATUS_WARNING]),
                prospects=tuple(manifest_entries),
            )
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest.to_dict(), handle, indent=2)

            os.replace(temp_dir, final_dir)
            return CampaignPackageResult(
                success=True,
                message=f"Campaign package created: {len(included)} included, {manifest.total_blocked} blocked",
                package_directory=final_dir,
                campaign_csv_path=os.path.join(final_dir, "campaign.csv"),
                manifest_path=os.path.join(final_dir, "manifest.json"),
                validation_csv_path=os.path.join(final_dir, "validation.csv"),
                included_count=len(included),
                blocked_count=manifest.total_blocked,
                warning_count=manifest.total_warnings,
                selected_count=selected_count,
                manifest=manifest,
                blocked_reasons=tuple(blocked_reasons),
            )
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _write_campaign_csv(self, path: str, included: list[_IncludedProspect]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CAMPAIGN_CSV_COLUMNS))
            writer.writeheader()
            for item in included:
                row = item.export_row
                writer.writerow(
                    {
                        "email": row.email,
                        "first_name": row.first_name,
                        "contact_name": row.contact_name,
                        "company": row.company,
                        "email_subject": row.email_subject,
                        "email_body": row.email_body,
                        "email_opening_line": row.email_opening_line,
                        "personalization_basis": row.personalization_basis,
                        "website": row.website,
                        "category": row.category,
                        "city": row.city,
                        "state": row.state,
                        "headline": row.headline,
                        "cta": row.cta,
                        "mockup_relative_path": item.manifest_entry.mockup_relative_path,
                        "prospect_id": row.prospect_id,
                        "generation_job_id": row.generation_job_id,
                        "project_id": row.project_id,
                        "opportunity_id": row.opportunity_id,
                        "location_id": row.location_id,
                        "placement_id": row.placement_id,
                    }
                )

    def _write_validation_csv(self, path: str, entries: list[CampaignPackageProspect]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(VALIDATION_CSV_COLUMNS))
            writer.writeheader()
            for entry in entries:
                writer.writerow({column: entry.to_dict().get(column, "") for column in VALIDATION_CSV_COLUMNS})

    def _ordered_ids(self, prospect_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in prospect_ids:
            prospect_id = str(raw or "").strip()
            if not prospect_id or prospect_id in seen:
                continue
            seen.add(prospect_id)
            ordered.append(prospect_id)
        return ordered

    def _sanitize_package_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._")
        return cleaned or "campaign_package"

    def _next_available_package_dir(self, destination_root: str, package_label: str) -> str:
        candidate = os.path.join(destination_root, package_label)
        if not os.path.exists(candidate):
            return candidate
        index = 2
        while True:
            candidate = os.path.join(destination_root, f"{package_label}_{index}")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _stable_asset_filename(self, row: CampaignExportRow, source_path: str, registry: dict[str, int]) -> str:
        company_slug = self._slug(row.company) or "company"
        prospect_slug = self._slug(row.prospect_id) or "prospect"
        _, ext = os.path.splitext(source_path)
        ext = ext or ".png"
        base = f"{company_slug}__{prospect_slug}"
        count = registry.get(base, 0) + 1
        registry[base] = count
        if count > 1:
            base = f"{base}_{count}"
        return f"{base}{ext.lower()}"

    def _slug(self, value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        return text[:80]