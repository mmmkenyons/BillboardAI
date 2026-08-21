"""Run-scoped Smartlead portable export service (Sprint 5Y).

Consumes an already-prepared run-scoped Smartlead package + handoff (produced by
``SmartleadRunHandoffService``) and produces a portable, Smartlead-ready
``smartlead.csv`` for the operator to take outside BillboardAI.

The exported lead data reuses the established Smartlead handoff column contract
from ``gui.services.smartlead_handoff`` and ``gui.models.smartlead_handoff``
unchanged, with the additive ``mockup_url`` column (aligned to
``SMARTLEAD_CUSTOM_FIELD_MAP``: ``mockup_url -> bb_mockup_url``).

This service orchestrates existing components; it never rebuilds a campaign
package, never mutates canonical stores, never hosts assets, and never performs
any external Smartlead side effect. Missing hosted public URLs are surfaced as a
warning/fallback and never block an otherwise-valid lead.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.personalization_field_catalog import (
    DEFAULT_REQUIRED_EXPORT_COLUMNS,
    PersonalizationFieldMapping,
    PersonalizationFieldMappingStore,
    default_personalization_mapping,
    enabled_mappings_in_order,
    mapping_fingerprint,
    normalize_export_name,
    validate_personalization_mapping,
)
from gui.models.smartlead_handoff import (
    DEFAULT_SMARTLEAD_COLUMN_ORDER,
    SMARTLEAD_PREFLIGHT_BLOCKED,
    SMARTLEAD_PREFLIGHT_CONFLICT,
    SMARTLEAD_PREFLIGHT_READY,
    SMARTLEAD_PREFLIGHT_WARNING,
)
from gui.models.smartlead_run_export import (
    SMARTLEAD_EXPORT_BLOCKED,
    SMARTLEAD_EXPORT_CONFLICT,
    SMARTLEAD_EXPORT_EXCLUDED,
    SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN,
    SMARTLEAD_EXPORT_READY,
    SMARTLEAD_EXPORT_WARNING,
    SmartleadRunExportReceipt,
    SmartleadRunExportResult,
    SmartleadRunExportRow,
)
from gui.models.smartlead_run_package import SmartleadRunPackageRecord, SmartleadRunPackageStore
from gui.services.personalization_field_values import (
    PersonalizationFieldContext,
    get_personalization_field_value,
    personalization_preview_rows,
)
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService

EXPORT_VERSION = "5Y"
EXPORT_CSV_FILENAME = "smartlead.csv"
EXPORT_MANIFEST_FILENAME = "export_manifest.json"

# Handoff preflight status -> export readiness status.
_PREFLIGHT_TO_EXPORT = {
    SMARTLEAD_PREFLIGHT_READY: SMARTLEAD_EXPORT_READY,
    SMARTLEAD_PREFLIGHT_WARNING: SMARTLEAD_EXPORT_WARNING,
    SMARTLEAD_PREFLIGHT_BLOCKED: SMARTLEAD_EXPORT_BLOCKED,
    SMARTLEAD_PREFLIGHT_CONFLICT: SMARTLEAD_EXPORT_CONFLICT,
}


def _clean(value: object) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_export_columns(header: list[str] | None) -> list[str]:
    """Preserve the handoff column order and insert ``mockup_url`` after ``mockup_path``."""
    columns = [str(item) for item in (header or list(DEFAULT_SMARTLEAD_COLUMN_ORDER)) if str(item).strip()]
    if SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN in columns:
        return columns
    if "mockup_path" in columns:
        index = columns.index("mockup_path") + 1
        columns.insert(index, SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN)
    else:
        columns.append(SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN)
    return columns


class SmartleadRunExportService:
    def __init__(
        self,
        *,
        run_handoff_service: SmartleadRunHandoffService,
        hosted_asset_store: HostedAssetStore | None = None,
        mapping_store: PersonalizationFieldMappingStore | None = None,
        export_root: str | None = None,
    ) -> None:
        self._run_handoff = run_handoff_service
        self._hosted_asset_store = hosted_asset_store or HostedAssetStore()
        self._mapping_store = mapping_store or PersonalizationFieldMappingStore()
        default_root = os.path.join(os.path.dirname(self._run_handoff.package_store.path), "exports")
        self._export_root = os.path.abspath(export_root or default_root)

    @property
    def export_root(self) -> str:
        return self._export_root

    @property
    def package_store(self) -> SmartleadRunPackageStore:
        return self._run_handoff.package_store

    def get_field_mapping(self) -> list[PersonalizationFieldMapping]:
        return self._mapping_store.load_or_default()

    def save_field_mapping(self, mapping: list[PersonalizationFieldMapping]) -> list[PersonalizationFieldMapping]:
        self._mapping_store.save(mapping)
        return self.get_field_mapping()

    def restore_default_field_mapping(self) -> list[PersonalizationFieldMapping]:
        mapping = default_personalization_mapping()
        self._mapping_store.save(mapping)
        return mapping

    # ------------------------------------------------------------------
    # Read-only preview / readiness
    # ------------------------------------------------------------------
    def build_export_rows(self, campaign_run_id: str) -> SmartleadRunExportResult:
        context, record = self._resolve_context(campaign_run_id)
        if record is None:
            return SmartleadRunExportResult(
                success=False,
                message=(
                    "No prepared Smartlead package for this run. "
                    "Run \"Prepare Smartlead Package\" first."
                ),
                campaign_run_id=_clean(campaign_run_id),
            )
        rows, counts, _columns = self._build_rows(record)
        return SmartleadRunExportResult(
            success=True,
            message=self._summary_message(rows, counts),
            campaign_run_id=record.campaign_run_id,
            campaign_name=_clean(getattr(context, "campaign_name", "")),
            rows=rows,
            **counts,
        )
# ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_run(self, campaign_run_id: str, *, destination: str | None = None) -> SmartleadRunExportResult:
        context, record = self._resolve_context(campaign_run_id)
        if record is None:
            return SmartleadRunExportResult(
                success=False,
                message=(
                    "No prepared Smartlead package for this run. "
                    "Run \"Prepare Smartlead Package\" first."
                ),
                campaign_run_id=_clean(campaign_run_id),
            )

        rows, counts, handoff_columns = self._build_rows(record)
        exportable = [row for row in rows if row.exportable]
        mapping = self.get_field_mapping()
        try:
            validate_personalization_mapping(mapping)
        except ValueError as exc:
            return SmartleadRunExportResult(
                success=False,
                message=str(exc),
                campaign_run_id=record.campaign_run_id,
                campaign_name=_clean(getattr(context, "campaign_name", "")),
                rows=rows,
                **counts,
            )
        columns = self._build_mapped_columns(handoff_columns, mapping)

        campaign_name = _clean(getattr(context, "campaign_name", ""))
        label = self._sanitize_label(campaign_name or record.campaign_run_id)
        export_dir, csv_name = self._resolve_destination(destination, label, record.campaign_run_id)
        csv_path = os.path.join(export_dir, csv_name)
        manifest_path = os.path.join(export_dir, EXPORT_MANIFEST_FILENAME)

        csv_rows: list[dict[str, str]] = []
        for row in exportable:
            payload = self._project_row(row, mapping, columns)
            csv_rows.append({column: payload.get(column, "") for column in columns})

        if csv_rows:
            self._write_export_csv(csv_path, columns, csv_rows)

        fingerprint = self._fingerprint(exportable, mapping)
        exported_statuses = {row.prospect_id: row.status for row in exportable if row.prospect_id}
        receipt = SmartleadRunExportReceipt(
            campaign_run_id=record.campaign_run_id,
            package_id=_clean(record.package_id),
            export_directory=export_dir,
            smartlead_csv_path=csv_path if csv_rows else "",
            manifest_path=manifest_path,
            exported_at=_utc_now_iso(),
            total_members=counts["total_members"],
            exported_rows=counts["exported_rows"],
            ready=counts["ready"],
            warning=counts["warning"],
            blocked=counts["blocked"],
            conflict=counts["conflict"],
            excluded=counts["excluded"],
            with_public_url=counts["with_public_url"],
            local_fallback=counts["local_fallback"],
            fingerprint=fingerprint,
            exported_statuses=exported_statuses,
        )
        self._write_export_manifest(manifest_path, receipt, rows, columns, mapping)
        self._persist_receipt(record, receipt)

        return SmartleadRunExportResult(
            success=True,
            message=self._summary_message(rows, counts),
            campaign_run_id=record.campaign_run_id,
            campaign_name=campaign_name,
            export_directory=export_dir,
            smartlead_csv_path=csv_path if csv_rows else "",
            manifest_path=manifest_path,
            receipt=receipt,
            rows=rows,
            **counts,
        )

    def latest_export(self, campaign_run_id: str) -> SmartleadRunExportReceipt | None:
        record = self.package_store.get(_clean(campaign_run_id))
        if record is None:
            return None
        last = dict(getattr(record, "last_export", None) or {})
        if not last:
            return None
        return SmartleadRunExportReceipt.from_dict(last)

    def preview_field_mapping(self, campaign_run_id: str) -> list[dict[str, str]]:
        rows_result = self.build_export_rows(campaign_run_id)
        first = next((row for row in rows_result.rows if row.exportable), None)
        if first is None:
            return []
        return personalization_preview_rows(self.get_field_mapping(), self._field_context(first))
# ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_context(self, campaign_run_id: str):
        context = self._run_handoff.context_for_run(_clean(campaign_run_id))
        record = getattr(context, "package_record", None)
        return context, record

    def _build_rows(
        self, record: SmartleadRunPackageRecord
    ) -> tuple[tuple[SmartleadRunExportRow, ...], dict[str, int], list[str]]:
        preflight_by_pid = self._read_preflight(record)
        handoff_rows, handoff_columns = self._read_handoff(record)
        handoff_by_pid = {
            _clean(row.get("prospect_id")): row for row in handoff_rows if _clean(row.get("prospect_id"))
        }

        rows: list[SmartleadRunExportRow] = []
        for entry in record.entries:
            prospect_id = _clean(entry.prospect_id)
            pre = preflight_by_pid.get(prospect_id)
            handoff_row = handoff_by_pid.get(prospect_id)
            if pre is not None:
                status = _PREFLIGHT_TO_EXPORT.get(pre.get("status"), SMARTLEAD_EXPORT_BLOCKED)
                reason = _clean(pre.get("reason"))
                warning = _clean(pre.get("warning"))
                company = _clean(pre.get("company"))
                email = _clean(pre.get("email"))
            else:
                status = SMARTLEAD_EXPORT_EXCLUDED
                reason = _clean(entry.blocker) or "Not included in the prepared Smartlead package."
                warning = ""
                company = ""
                email = ""
            mockup_path = _clean(handoff_row.get("mockup_path")) if handoff_row is not None else ""
            fields = dict(handoff_row) if handoff_row is not None else {}
            mockup_url, _has_url = self._resolve_public_url(
                prospect_id,
                _clean(entry.generation_job_id),
                _clean(entry.project_id),
            )
            rows.append(
                SmartleadRunExportRow(
                    prospect_id=prospect_id,
                    company=company,
                    email=email,
                    status=status,
                    reason=reason,
                    warning=warning,
                    mockup_path=mockup_path,
                    mockup_url=mockup_url,
                    generation_job_id=_clean(entry.generation_job_id),
                    project_id=_clean(entry.project_id),
                    fields=fields,
                )
            )

        counts = self._counts(rows)
        return tuple(rows), counts, handoff_columns

    def _build_mapped_columns(self, handoff_columns: list[str], mapping: list[PersonalizationFieldMapping]) -> list[str]:
        legacy_columns = build_export_columns(handoff_columns)
        columns = [column for column in legacy_columns if column in DEFAULT_REQUIRED_EXPORT_COLUMNS]
        for item in enabled_mappings_in_order(mapping):
            export_name = normalize_export_name(item.export_name)
            if not export_name or export_name in columns:
                continue
            columns.append(export_name)
        return columns

    def _project_row(
        self,
        row: SmartleadRunExportRow,
        mapping: list[PersonalizationFieldMapping],
        columns: list[str],
    ) -> dict[str, str]:
        context = self._field_context(row)
        payload: dict[str, str] = {}
        for item in enabled_mappings_in_order(mapping):
            export_name = normalize_export_name(item.export_name)
            if not export_name:
                continue
            payload[export_name] = get_personalization_field_value(item.field_key, context)
        # Backward-compatible guard for Sprint 5Y default schema. These are all
        # populated through the default mapping, but preserving row.fields here
        # protects older/corrupt mapping load fallbacks from dropping columns.
        for column in columns:
            if column not in payload:
                if column == SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN:
                    payload[column] = row.mockup_url
                else:
                    payload[column] = _clean(row.fields.get(column))
        return payload

    def _field_context(self, row: SmartleadRunExportRow) -> PersonalizationFieldContext:
        run_service = self._run_handoff._run_service
        prospect = run_service._prospect_store.get(row.prospect_id)
        job = run_service._job_store.get(row.generation_job_id) if row.generation_job_id else None
        project = None
        project_id = row.project_id or _clean(getattr(job, "project_id", ""))
        if project_id:
            try:
                project = run_service._project_store.load(project_id)
            except Exception:
                project = None
        return PersonalizationFieldContext(
            prospect=prospect,
            generation_job=job,
            project=project,
            handoff_fields=dict(row.fields),
            mockup_url=row.mockup_url,
            campaign_run_id="",
        )

    def _counts(self, rows: list[SmartleadRunExportRow]) -> dict[str, int]:
        ready = sum(1 for r in rows if r.status == SMARTLEAD_EXPORT_READY)
        warning = sum(1 for r in rows if r.status == SMARTLEAD_EXPORT_WARNING)
        blocked = sum(1 for r in rows if r.status == SMARTLEAD_EXPORT_BLOCKED)
        conflict = sum(1 for r in rows if r.status == SMARTLEAD_EXPORT_CONFLICT)
        excluded = sum(1 for r in rows if r.status == SMARTLEAD_EXPORT_EXCLUDED)
        exported = [r for r in rows if r.exportable]
        with_public_url = sum(1 for r in exported if r.has_public_url)
        return {
            "total_members": len(rows),
            "exported_rows": len(exported),
            "ready": ready,
            "warning": warning,
            "blocked": blocked,
            "conflict": conflict,
            "excluded": excluded,
            "with_public_url": with_public_url,
            "local_fallback": len(exported) - with_public_url,
        }

    def _summary_message(self, rows: list[SmartleadRunExportRow], counts: dict[str, int]) -> str:
        return (
            f"Exported {counts['exported_rows']} Smartlead-ready lead(s). "
            f"Ready {counts['ready']} | Warning {counts['warning']} | "
            f"Blocked {counts['blocked']} | Conflict {counts['conflict']} | "
            f"Excluded {counts['excluded']}."
        )
    def _read_preflight(self, record: SmartleadRunPackageRecord) -> dict[str, dict[str, str]]:
        handoff_dir = _clean(record.handoff_directory)
        path = os.path.join(handoff_dir, "smartlead_preflight.csv")
        if not handoff_dir or not os.path.isfile(path):
            return {}
        result: dict[str, dict[str, str]] = {}
        with open(path, "r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                prospect_id = _clean(row.get("prospect_id"))
                if not prospect_id:
                    continue
                result[prospect_id] = {
                    "status": _clean(row.get("status")),
                    "reason": _clean(row.get("reason")),
                    "warning": _clean(row.get("warning")),
                    "company": _clean(row.get("company")),
                    "email": _clean(row.get("email")),
                }
        return result

    def _read_handoff(self, record: SmartleadRunPackageRecord) -> tuple[list[dict[str, str]], list[str]]:
        csv_path = _clean(record.smartlead_csv_path)
        if not csv_path or not os.path.isfile(csv_path):
            return [], []
        with open(csv_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            rows = [{str(k): str(v or "") for k, v in row.items()} for row in reader]
        return rows, columns

    def _resolve_public_url(self, prospect_id: str, generation_job_id: str, project_id: str) -> tuple[str, bool]:
        assets = [a for a in self._hosted_asset_store.find_by_prospect(prospect_id) if a.has_valid_public_url]
        if not assets:
            return "", False
        if generation_job_id:
            matches = [a for a in assets if _clean(a.generation_job_id) == generation_job_id]
            if matches:
                return self._latest_asset(matches).public_url, True
        if project_id:
            matches = [a for a in assets if _clean(a.project_id) == project_id]
            if matches:
                return self._latest_asset(matches).public_url, True
        return self._latest_asset(assets).public_url, True

    @staticmethod
    def _latest_asset(assets: list) -> Any:
        return sorted(assets, key=lambda a: _clean(a.hosted_at))[-1]
    def _fingerprint(self, rows: list[SmartleadRunExportRow], mapping: list[PersonalizationFieldMapping] | None = None) -> str:
        parts = ["|".join([row.prospect_id, row.status, row.mockup_url]) for row in rows]
        if mapping is not None:
            parts.append(mapping_fingerprint(mapping))
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _sanitize_label(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._")
        return cleaned or "campaign"

    def _resolve_destination(self, destination: str | None, label: str, campaign_run_id: str) -> tuple[str, str]:
        if destination:
            dest = os.path.abspath(str(destination))
            if dest.lower().endswith(".csv"):
                export_dir = os.path.dirname(dest)
                csv_name = os.path.basename(dest)
            else:
                export_dir = dest
                csv_name = EXPORT_CSV_FILENAME
            os.makedirs(export_dir, exist_ok=True)
            if os.path.exists(os.path.join(export_dir, csv_name)):
                base, ext = os.path.splitext(csv_name)
                index = 2
                while os.path.exists(os.path.join(export_dir, f"{base}_{index}{ext}")):
                    index += 1
                csv_name = f"{base}_{index}{ext}"
            return export_dir, csv_name

        root = self._export_root
        candidate = os.path.join(root, label)
        if os.path.exists(candidate):
            index = 2
            while os.path.exists(os.path.join(root, f"{label}_{index}")):
                index += 1
            candidate = os.path.join(root, f"{label}_{index}")
        os.makedirs(candidate, exist_ok=True)
        return candidate, EXPORT_CSV_FILENAME

    @staticmethod
    def _write_export_csv(path: str, columns: list[str], rows: list[dict[str, str]]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        os.replace(tmp, path)

    @staticmethod
    def _write_export_manifest(
        path: str,
        receipt: SmartleadRunExportReceipt,
        rows: list[SmartleadRunExportRow],
        columns: list[str] | None = None,
        mapping: list[PersonalizationFieldMapping] | None = None,
    ) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "export_version": EXPORT_VERSION,
            "receipt": receipt.to_dict(),
            "rows": [row.to_dict() for row in rows],
        }
        if columns is not None:
            payload["export_columns"] = list(columns)
        if mapping is not None:
            payload["field_mapping"] = {
                "fingerprint": mapping_fingerprint(mapping),
                "enabled_fields": [
                    {"field_key": item.field_key, "export_name": normalize_export_name(item.export_name)}
                    for item in enabled_mappings_in_order(mapping)
                ],
            }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, path)

    def _persist_receipt(self, record: SmartleadRunPackageRecord, receipt: SmartleadRunExportReceipt) -> None:
        exported = set((receipt.exported_statuses or {}).keys())
        payload = record.to_dict()
        entries = []
        for entry in payload.get("entries", []) or []:
            if not isinstance(entry, dict):
                continue
            prospect_id = _clean(entry.get("prospect_id"))
            is_exported = prospect_id in exported
            entry = dict(entry)
            entry["exported"] = is_exported
            if is_exported:
                entry["disposition"] = "EXPORTED"
                entry["disposition_reason"] = "Exported to portable Smartlead CSV."
            elif entry.get("exportable"):
                entry["disposition"] = "EXPORTABLE_NOT_EXPORTED"
                entry["disposition_reason"] = "Exportable member was not written to CSV."
            entries.append(entry)
        payload["entries"] = entries
        payload["last_export"] = receipt.to_dict()
        updated = SmartleadRunPackageRecord.from_dict(payload)
        self.package_store.upsert(updated)
        self.package_store.save()