"""Read-only Smartlead handoff preflight and artifact generation."""

from __future__ import annotations

import csv
import json
import os
import re

from gui.models.smartlead_handoff import (
    DEFAULT_SMARTLEAD_COLUMN_ORDER,
    SmartleadHandoffProfile,
    SmartleadHandoffResult,
    SmartleadHandoffSummary,
    SmartleadPreflightRow,
    SMARTLEAD_PREFLIGHT_BLOCKED,
    SMARTLEAD_PREFLIGHT_CONFLICT,
    SMARTLEAD_PREFLIGHT_READY,
    SMARTLEAD_PREFLIGHT_WARNING,
)

PREFLIGHT_COLUMNS = (
    "prospect_id",
    "company",
    "email",
    "status",
    "reason",
    "warning",
)


class SmartleadHandoffService:
    def __init__(self) -> None:
        self._email_pattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

    def prepare_handoff(
        self,
        package_directory: str,
        *,
        profile: SmartleadHandoffProfile | None = None,
    ) -> SmartleadHandoffResult:
        package_root = os.path.abspath(str(package_directory or "").strip())
        if not package_root or not os.path.isdir(package_root):
            return SmartleadHandoffResult(success=False, message="Approved package directory does not exist.")

        active_profile = profile or SmartleadHandoffProfile.default()
        mapping_error = self._validate_profile(active_profile)
        if mapping_error:
            return SmartleadHandoffResult(success=False, message=mapping_error, package_directory=package_root, profile=active_profile)

        campaign_csv_path = os.path.join(package_root, "campaign.csv")
        manifest_path = os.path.join(package_root, "manifest.json")
        if not os.path.isfile(campaign_csv_path):
            return SmartleadHandoffResult(success=False, message="Approved package is missing campaign.csv.", package_directory=package_root, profile=active_profile)
        if not os.path.isfile(manifest_path):
            return SmartleadHandoffResult(success=False, message="Approved package is missing manifest.json.", package_directory=package_root, profile=active_profile)

        with open(campaign_csv_path, "r", encoding="utf-8", newline="") as handle:
            campaign_rows = list(csv.DictReader(handle))
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)

        manifest_rows = {
            str(entry.get("prospect_id") or ""): entry
            for entry in list(manifest.get("prospects") or [])
            if str(entry.get("prospect_id") or "").strip()
        }
        approved_candidates = []
        for row in campaign_rows:
            prospect_id = self._clean(row.get("prospect_id"))
            manifest_entry = manifest_rows.get(prospect_id)
            if manifest_entry is None:
                continue
            if self._clean(manifest_entry.get("status")).upper() not in {"READY", "WARNING"}:
                continue
            approved_candidates.append(row)

        email_to_ids: dict[str, list[str]] = {}
        for row in approved_candidates:
            email_key = self._clean(row.get("email")).lower()
            if email_key:
                email_to_ids.setdefault(email_key, []).append(self._clean(row.get("prospect_id")))

        preflight_rows: list[SmartleadPreflightRow] = []
        final_rows: list[dict[str, str]] = []

        for row in approved_candidates:
            preflight = self._preflight_row(package_root, row, active_profile, email_to_ids)
            preflight_rows.append(preflight)
            if preflight.status in {SMARTLEAD_PREFLIGHT_READY, SMARTLEAD_PREFLIGHT_WARNING}:
                final_rows.append(self._ordered_output_row(preflight.mapped_fields, active_profile))

        handoff_dir = os.path.join(package_root, "handoff")
        os.makedirs(handoff_dir, exist_ok=True)
        mapping_path = os.path.join(handoff_dir, "smartlead_mapping.json")
        preflight_path = os.path.join(handoff_dir, "smartlead_preflight.csv")
        handoff_manifest_path = os.path.join(handoff_dir, "smartlead_handoff_manifest.json")
        output_csv_path = os.path.join(handoff_dir, "smartlead.csv")

        self._write_mapping(mapping_path, active_profile)
        self._write_preflight(preflight_path, preflight_rows)

        summary = SmartleadHandoffSummary(
            total_approved_rows=len(approved_candidates),
            ready=sum(1 for row in preflight_rows if row.status == SMARTLEAD_PREFLIGHT_READY),
            warnings=sum(1 for row in preflight_rows if row.status == SMARTLEAD_PREFLIGHT_WARNING),
            blocked=sum(1 for row in preflight_rows if row.status == SMARTLEAD_PREFLIGHT_BLOCKED),
            conflicts=sum(1 for row in preflight_rows if row.status == SMARTLEAD_PREFLIGHT_CONFLICT),
            output_csv_path=output_csv_path if final_rows else "",
            mapping_path=mapping_path,
            preflight_path=preflight_path,
            manifest_path=handoff_manifest_path,
            handoff_directory=handoff_dir,
        )

        if final_rows:
            self._write_final_csv(output_csv_path, final_rows)
        elif os.path.exists(output_csv_path):
            os.remove(output_csv_path)

        self._write_handoff_manifest(handoff_manifest_path, package_root, active_profile, summary, preflight_rows, bool(final_rows))

        message = "Smartlead handoff prepared." if final_rows else "Smartlead preflight completed, but no rows are ready for handoff."
        return SmartleadHandoffResult(
            success=bool(final_rows),
            message=message,
            package_directory=package_root,
            handoff_directory=handoff_dir,
            smartlead_csv_path=output_csv_path if final_rows else "",
            mapping_path=mapping_path,
            preflight_path=preflight_path,
            manifest_path=handoff_manifest_path,
            summary=summary,
            profile=active_profile,
            rows=tuple(preflight_rows),
        )

    def _preflight_row(
        self,
        package_root: str,
        row: dict[str, str],
        profile: SmartleadHandoffProfile,
        email_to_ids: dict[str, list[str]],
    ) -> SmartleadPreflightRow:
        prospect_id = self._clean(row.get("prospect_id"))
        company = self._clean(row.get("company"))
        email = self._clean(row.get("email"))
        reasons: list[str] = []
        warnings: list[str] = []

        mapped_fields = self._apply_mapping(row, profile)

        for required_source in profile.required_fields:
            if not self._clean(row.get(required_source)):
                reasons.append(f"Missing required field: {required_source}.")

        if not self._is_valid_email(email):
            reasons.append("Email failed local format sanity validation.")

        duplicate_ids = email_to_ids.get(email.lower(), []) if email else []
        if email and len(duplicate_ids) > 1:
            reasons.append(f"Duplicate email conflict with prospects: {', '.join(sorted(duplicate_ids))}.")

        asset_rel = self._clean(row.get("mockup_relative_path"))
        if asset_rel:
            asset_path = os.path.join(package_root, *asset_rel.replace("\\", "/").split("/"))
            if not os.path.isfile(asset_path):
                reasons.append("Packaged mockup asset reference is missing.")
        elif self._mapping_enabled(profile, "mockup_relative_path"):
            warnings.append("Mockup asset reference is blank.")

        self._check_subject_body_safety(row, reasons)

        if reasons and any("Duplicate email conflict" in reason for reason in reasons):
            status = SMARTLEAD_PREFLIGHT_CONFLICT
        elif reasons:
            status = SMARTLEAD_PREFLIGHT_BLOCKED
        elif warnings:
            status = SMARTLEAD_PREFLIGHT_WARNING
        else:
            status = SMARTLEAD_PREFLIGHT_READY

        return SmartleadPreflightRow(
            prospect_id=prospect_id,
            company=company,
            email=email,
            status=status,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            mapped_fields=mapped_fields,
        )

    def _apply_mapping(self, row: dict[str, str], profile: SmartleadHandoffProfile) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for item in profile.field_mapping:
            if not item.enabled:
                continue
            value = self._clean(row.get(item.source_field))
            mapped[item.destination_field] = value
        return mapped

    def _ordered_output_row(self, mapped_fields: dict[str, str], profile: SmartleadHandoffProfile) -> dict[str, str]:
        destinations = [item.destination_field for item in profile.field_mapping if item.enabled]
        ordered = [column for column in DEFAULT_SMARTLEAD_COLUMN_ORDER if column in destinations]
        ordered.extend(column for column in destinations if column not in ordered)
        return {column: mapped_fields.get(column, "") for column in ordered}

    def _validate_profile(self, profile: SmartleadHandoffProfile) -> str:
        seen_destinations: set[str] = set()
        source_fields = {item.source_field for item in profile.field_mapping}
        for item in profile.field_mapping:
            if item.required and not item.enabled:
                return f"Required mapping cannot be disabled: {item.source_field}."
            destination = self._clean(item.destination_field)
            if item.enabled and destination in seen_destinations:
                return f"Duplicate destination mapping is not allowed: {destination}."
            if item.enabled and destination:
                seen_destinations.add(destination)
        for required_field in profile.required_fields:
            if required_field not in source_fields:
                return f"Missing required source mapping: {required_field}."
            match = next((item for item in profile.field_mapping if item.source_field == required_field), None)
            if match is None or not match.enabled:
                return f"Required source mapping is disabled: {required_field}."
        return ""

    def _mapping_enabled(self, profile: SmartleadHandoffProfile, source_field: str) -> bool:
        match = next((item for item in profile.field_mapping if item.source_field == source_field), None)
        return bool(match.enabled) if match is not None else False

    def _write_mapping(self, path: str, profile: SmartleadHandoffProfile) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(profile.to_dict(), handle, indent=2)

    def _write_preflight(self, path: str, rows: list[SmartleadPreflightRow]) -> None:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(PREFLIGHT_COLUMNS))
            writer.writeheader()
            for row in rows:
                payload = row.to_dict()
                writer.writerow({column: payload.get(column, "") for column in PREFLIGHT_COLUMNS})

    def _write_final_csv(self, path: str, rows: list[dict[str, str]]) -> None:
        columns = list(rows[0].keys()) if rows else list(DEFAULT_SMARTLEAD_COLUMN_ORDER)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_handoff_manifest(
        self,
        path: str,
        package_root: str,
        profile: SmartleadHandoffProfile,
        summary: SmartleadHandoffSummary,
        rows: list[SmartleadPreflightRow],
        emitted_csv: bool,
    ) -> None:
        payload = {
            "handoff_version": "5P",
            "package_directory": package_root,
            "profile": profile.to_dict(),
            "summary": {
                "total_approved_rows": summary.total_approved_rows,
                "ready": summary.ready,
                "warnings": summary.warnings,
                "blocked": summary.blocked,
                "conflicts": summary.conflicts,
                "output_csv_path": summary.output_csv_path,
                "mapping_path": summary.mapping_path,
                "preflight_path": summary.preflight_path,
                "manifest_path": summary.manifest_path,
            },
            "smartlead_csv_emitted": emitted_csv,
            "rows": [row.to_dict() for row in rows],
            "notes": [
                "Email validation is local format sanity only; no deliverability or DNS checks are performed.",
                "Only approved package rows are considered; canonical package files and review state remain unchanged.",
            ],
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _check_subject_body_safety(self, row: dict[str, str], reasons: list[str]) -> None:
        combined = "\n".join([self._clean(row.get("email_subject")), self._clean(row.get("email_body"))])
        forbidden = [
            self._clean(row.get("opportunity_id")),
            self._clean(row.get("location_id")),
            self._clean(row.get("placement_id")),
            self._clean(row.get("generation_job_id")),
            self._clean(row.get("project_id")),
            "STRONG MATCH",
            "FOLLOW_UP",
        ]
        for token in forbidden:
            if token and token in combined:
                reasons.append("Subject/body safety boundary violated by internal metadata.")
                return

    def _is_valid_email(self, value: str) -> bool:
        email = self._clean(value)
        if not email or any(ch.isspace() for ch in email):
            return False
        if "@" not in email:
            return False
        return bool(self._email_pattern.match(email))

    def _clean(self, value: object) -> str:
        return str(value or "").strip()
