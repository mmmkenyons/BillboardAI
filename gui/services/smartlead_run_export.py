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
        export_root: str | None = None,
    ) -> None:
        self._run_handoff = run_handoff_service
        self._hosted_asset_store = hosted_asset_store or HostedAssetStore()
        default_root = os.path.join(os.path.dirname(self._run_handoff.package_store.path), "exports")
        self._export_root = os.path.abspath(export_root or default_root)

    @property
    def export_root(self) -> str:
        return self._export_root

    @property
    def package_store(self) -> SmartleadRunPackageStore:
        return self._run_handoff.package_store

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
        columns = build_export_columns(handoff_columns)

        campaign_name = _clean(getattr(context, "campaign_name", ""))
        label = self._sanitize_label(campaign_name or record.campaign_run_id)
        export_dir, csv_name = self._resolve_destination(destination, label, record.campaign_run_id)
        csv_path = os.path.join(export_dir, csv_name)
        manifest_path = os.path.join(export_dir, EXPORT_MANIFEST_FILENAME)

        csv_rows: list[dict[str, str]] = []
        for row in exportable:
            payload: dict[str, str] = {str(k): str(v or "") for k, v in row.fields.items()}
            payload[SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN] = row.mockup_url
            csv_rows.append({column: payload.get(column, "") for column in columns})

        if csv_rows:
            self._write_export_csv(csv_path, columns, csv_rows)

        fingerprint = self._fingerprint(exportable)
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
        )
        self._write_export_manifest(manifest_path, receipt, rows)
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
    def _fingerprint(self, rows: list[SmartleadRunExportRow]) -> str:
        parts = ["|".join([row.prospect_id, row.status, row.mockup_url]) for row in rows]
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
        path: str, receipt: SmartleadRunExportReceipt, rows: list[SmartleadRunExportRow]
    ) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "export_version": EXPORT_VERSION,
            "receipt": receipt.to_dict(),
            "rows": [row.to_dict() for row in rows],
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, path)

    def _persist_receipt(self, record: SmartleadRunPackageRecord, receipt: SmartleadRunExportReceipt) -> None:
        updated = SmartleadRunPackageRecord.from_dict({**record.to_dict(), "last_export": receipt.to_dict()})
        self.package_store.upsert(updated)
        self.package_store.save()