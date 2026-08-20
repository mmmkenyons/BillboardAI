"""Sprint 5AD bulk campaign assembly orchestration.

This service is read-only over prospect/generation/project data and delegates
package/export work to existing Campaign Review, Smartlead Run Handoff, and
Smartlead Run Export services.  It never scrapes, resolves profiles, generates,
renders, hosts, uploads, publishes, activates, or sends.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from gui.models.campaign_assembly import (
    ASSEMBLY_STATUS_BLOCKED,
    ASSEMBLY_STATUS_EXCLUDED,
    ASSEMBLY_STATUS_READY,
    ASSEMBLY_STATUS_WARNING,
    CampaignAssemblyReason,
    CampaignAssemblySnapshot,
    CampaignAssemblyStore,
    OutreachReadinessResult,
    utc_now_iso,
)
from gui.models.campaign_review import CAMPAIGN_REVIEW_STATUS_APPROVED, CAMPAIGN_REVIEW_STATUS_EXCLUDED
from gui.models.personalization_field_catalog import enabled_mappings_in_order, mapping_fingerprint
from gui.services.campaign_export import EXPORT_STATUS_BLOCKED, EXPORT_STATUS_READY, EXPORT_STATUS_WARNING
from gui.services.copy_quality import (
    QUALITY_BLOCKED,
    QUALITY_WARNING,
    assess_copy_quality,
    assess_profile_quality,
)
from gui.services.personalization_field_values import PersonalizationFieldContext, get_personalization_field_value


REASON_PROSPECT_NOT_FOUND = "PROSPECT_NOT_FOUND"
REASON_MISSING_EMAIL = "MISSING_EMAIL"
REASON_GENERATION_NOT_COMPLETE = "GENERATION_NOT_COMPLETE"
REASON_MISSING_PROJECT = "MISSING_PROJECT"
REASON_MISSING_CONCEPT = "MISSING_CONCEPT"
REASON_MISSING_MOCKUP = "MISSING_MOCKUP"
REASON_MISSING_HEADLINE = "MISSING_HEADLINE"
REASON_MISSING_CTA = "MISSING_CTA"
REASON_EXPORT_VALUE_CONFLICT = "EXPORT_VALUE_CONFLICT"
REASON_OPERATOR_EXCLUDED = "OPERATOR_EXCLUDED"
REASON_NOT_APPROVED = "NOT_APPROVED"
REASON_OPTIONAL_FIELD_BLANK = "OPTIONAL_PERSONALIZATION_FIELD_BLANK"
REASON_WARNING = "WARNING"
REASON_COPY_QUALITY_PREFIX = "COPY_QUALITY_"
REASON_PROFILE_QUALITY_PREFIX = "PROFILE_QUALITY_"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values or []:
        value = _clean(raw)
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _reason_code(message: str) -> str:
    text = _clean(message).lower()
    if "prospect not found" in text:
        return REASON_PROSPECT_NOT_FOUND
    if "missing email" in text or "malformed email" in text:
        return REASON_MISSING_EMAIL
    if "queued" in text or "running" in text or "generation" in text or "successful generation" in text:
        return REASON_GENERATION_NOT_COMPLETE
    if "project" in text:
        return REASON_MISSING_PROJECT
    if "concept" in text:
        return REASON_MISSING_CONCEPT
    if "mockup" in text or "source" in text or "image" in text or "asset" in text:
        return REASON_MISSING_MOCKUP
    if "headline" in text:
        return REASON_MISSING_HEADLINE
    if "cta" in text:
        return REASON_MISSING_CTA
    if "duplicate" in text or "conflict" in text:
        return REASON_EXPORT_VALUE_CONFLICT
    return "READINESS_BLOCKER"


@dataclass(frozen=True)
class CampaignAssemblySummary:
    total_prospects: int = 0
    ready: int = 0
    warning: int = 0
    blocked: int = 0
    conflict: int = 0
    excluded: int = 0
    exportable: int = 0
    included: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_prospects": self.total_prospects,
            "ready": self.ready,
            "warning": self.warning,
            "blocked": self.blocked,
            "conflict": self.conflict,
            "excluded": self.excluded,
            "exportable": self.exportable,
            "included": self.included,
            "reason_counts": dict(self.reason_counts),
            "warning_counts": dict(self.warning_counts),
        }


@dataclass(frozen=True)
class CampaignAssemblyResult:
    success: bool
    message: str
    snapshot: CampaignAssemblySnapshot | None = None
    summary: CampaignAssemblySummary = field(default_factory=CampaignAssemblySummary)
    export_result: Any | None = None


class CampaignAssemblyService:
    def __init__(
        self,
        *,
        run_service: Any,
        run_handoff_service: Any,
        run_export_service: Any,
        assembly_store: CampaignAssemblyStore | None = None,
    ) -> None:
        self._run_service = run_service
        self._run_handoff_service = run_handoff_service
        self._run_export_service = run_export_service
        self._assembly_store = assembly_store or CampaignAssemblyStore()

    @property
    def store(self) -> CampaignAssemblyStore:
        return self._assembly_store

    def latest_snapshot(self, campaign_run_id: str) -> CampaignAssemblySnapshot | None:
        return self._assembly_store.get(campaign_run_id)

    def evaluate_run(self, campaign_run_id: str) -> CampaignAssemblyResult:
        run = self._run_service.get_run(campaign_run_id)
        if run is None:
            return CampaignAssemblyResult(False, "Campaign run not found.")
        snapshot = self._build_snapshot(run, persist=False)
        return CampaignAssemblyResult(True, self._summary_message(snapshot), snapshot, self._summary(snapshot.readiness))

    def assemble_campaign(self, campaign_run_id: str) -> CampaignAssemblyResult:
        run = self._run_service.get_run(campaign_run_id)
        if run is None:
            return CampaignAssemblyResult(False, "Campaign run not found.")
        snapshot = self._build_snapshot(run, persist=True)
        return CampaignAssemblyResult(True, self._summary_message(snapshot), snapshot, self._summary(snapshot.readiness))

    def set_excluded(self, campaign_run_id: str, prospect_id: str, excluded: bool, note: str = "") -> CampaignAssemblyResult:
        run = self._run_service.get_run(campaign_run_id)
        if run is None:
            return CampaignAssemblyResult(False, "Campaign run not found.")
        if excluded:
            self._run_service.review_service.exclude(prospect_id)
        else:
            readiness = self._readiness_for(prospect_id, force_not_excluded=True)
            if not readiness.exportable:
                snapshot = self._build_snapshot(run, persist=True)
                return CampaignAssemblyResult(False, "Only READY/WARNING prospects can be re-included.", snapshot, self._summary(snapshot.readiness))
            self._run_service.review_service.approve(prospect_id)
        return self.assemble_campaign(campaign_run_id)

    def prepare_package(self, campaign_run_id: str) -> CampaignAssemblyResult:
        assembled = self.assemble_campaign(campaign_run_id)
        if not assembled.success:
            return assembled
        context = self._run_handoff_service.prepare_package_for_run(campaign_run_id)
        snapshot = self._build_snapshot(self._run_service.get_run(campaign_run_id), persist=False)
        record = getattr(context, "package_record", None)
        if record is not None:
            snapshot = self._replace_snapshot_refs(
                snapshot,
                created_at=(assembled.snapshot.created_at if assembled.snapshot else snapshot.created_at),
                modified_at=utc_now_iso(),
                package_directory=_clean(getattr(record, "package_directory", "")),
                handoff_directory=_clean(getattr(record, "handoff_directory", "")),
                smartlead_csv_path=_clean(getattr(record, "smartlead_csv_path", "")),
                export_receipt=dict(getattr(record, "last_export", {}) or {}),
            )
            self._assembly_store.upsert(snapshot)
        return CampaignAssemblyResult(True, self._summary_message(snapshot), snapshot, self._summary(snapshot.readiness))

    def export_campaign(self, campaign_run_id: str, *, destination: str | None = None) -> CampaignAssemblyResult:
        prepared = self.prepare_package(campaign_run_id)
        if not prepared.success:
            return prepared
        export_result = self._run_export_service.export_run(campaign_run_id, destination=destination)
        snapshot = prepared.snapshot
        record = self._run_handoff_service.package_store.get(campaign_run_id)
        if snapshot is not None and record is not None:
            snapshot = self._replace_snapshot_refs(
                snapshot,
                modified_at=utc_now_iso(),
                smartlead_csv_path=_clean(getattr(export_result, "smartlead_csv_path", "")) or snapshot.smartlead_csv_path,
                export_receipt=dict(getattr(record, "last_export", {}) or (getattr(getattr(export_result, "receipt", None), "to_dict", lambda: {})())),
            )
            self._assembly_store.upsert(snapshot)
        return CampaignAssemblyResult(bool(getattr(export_result, "success", False)), getattr(export_result, "message", ""), snapshot, self._summary(snapshot.readiness if snapshot else ()), export_result)

    def _build_snapshot(self, run: Any, *, persist: bool) -> CampaignAssemblySnapshot:
        previous = self._assembly_store.get(run.id)
        readiness = tuple(self._readiness_for(pid) for pid in _dedupe(run.prospect_ids))
        included = tuple(item.prospect_id for item in readiness if item.included)
        excluded = tuple(item.prospect_id for item in readiness if item.status == ASSEMBLY_STATUS_EXCLUDED)
        record = self._run_handoff_service.package_store.get(run.id)
        snapshot = CampaignAssemblySnapshot(
            campaign_run_id=run.id,
            name=_clean(getattr(run, "name", "")),
            created_at=(previous.created_at if previous else utc_now_iso()),
            modified_at=utc_now_iso(),
            prospect_ids_considered=tuple(_dedupe(run.prospect_ids)),
            included_prospect_ids=included,
            excluded_prospect_ids=excluded,
            readiness=readiness,
            mapping_fingerprint=mapping_fingerprint(self._run_export_service.get_field_mapping()),
            package_directory=_clean(getattr(record, "package_directory", "")) if record else "",
            handoff_directory=_clean(getattr(record, "handoff_directory", "")) if record else "",
            smartlead_csv_path=_clean(getattr(record, "smartlead_csv_path", "")) if record else "",
            export_receipt=dict(getattr(record, "last_export", {}) or {}) if record else {},
        )
        if persist:
            self._assembly_store.upsert(snapshot)
        return snapshot

    def _replace_snapshot_refs(self, snapshot: CampaignAssemblySnapshot, **changes: Any) -> CampaignAssemblySnapshot:
        payload = {
            "campaign_run_id": snapshot.campaign_run_id,
            "name": snapshot.name,
            "created_at": snapshot.created_at,
            "modified_at": snapshot.modified_at,
            "prospect_ids_considered": snapshot.prospect_ids_considered,
            "included_prospect_ids": snapshot.included_prospect_ids,
            "excluded_prospect_ids": snapshot.excluded_prospect_ids,
            "readiness": snapshot.readiness,
            "mapping_fingerprint": snapshot.mapping_fingerprint,
            "package_directory": snapshot.package_directory,
            "handoff_directory": snapshot.handoff_directory,
            "smartlead_csv_path": snapshot.smartlead_csv_path,
            "export_receipt": snapshot.export_receipt,
        }
        payload.update(changes)
        return CampaignAssemblySnapshot(**payload)

    def _readiness_for(self, prospect_id: str, *, force_not_excluded: bool = False) -> OutreachReadinessResult:
        decision = self._run_service.review_service.get_decision(prospect_id)
        prospect = self._run_service.prospect_store.get(prospect_id)
        eligibility, row, resolved = self._run_service.export_service.resolve_for_package(prospect_id)
        if decision.status == CAMPAIGN_REVIEW_STATUS_EXCLUDED and not force_not_excluded:
            return self._result_from_parts(prospect_id, ASSEMBLY_STATUS_EXCLUDED, prospect, row, resolved, (CampaignAssemblyReason(REASON_OPERATOR_EXCLUDED, "Operator excluded this prospect."),), ())
        blocking: list[CampaignAssemblyReason] = []
        warnings: list[CampaignAssemblyReason] = []
        if decision.status != CAMPAIGN_REVIEW_STATUS_APPROVED and not force_not_excluded:
            blocking.append(CampaignAssemblyReason(REASON_NOT_APPROVED, "Prospect is not approved for campaign review."))
        if eligibility.status == EXPORT_STATUS_BLOCKED:
            blocking.extend(CampaignAssemblyReason(_reason_code(reason), reason) for reason in eligibility.reasons)
        if row is not None:
            if not _clean(row.headline):
                blocking.append(CampaignAssemblyReason(REASON_MISSING_HEADLINE, "Missing headline."))
            if not _clean(row.cta):
                blocking.append(CampaignAssemblyReason(REASON_MISSING_CTA, "Missing CTA."))
            if not _clean(row.mockup_path) or not os.path.isfile(os.path.abspath(row.mockup_path)):
                blocking.append(CampaignAssemblyReason(REASON_MISSING_MOCKUP, "Rendered mockup file is missing."))
        if prospect is not None and row is not None and resolved is not None:
            copy_quality = assess_copy_quality(
                prospect=prospect,
                concept=getattr(resolved, "concept", None),
                project=getattr(resolved, "project", None),
                row=row,
            )
            for reason in copy_quality.reasons:
                assembly_reason = CampaignAssemblyReason(
                    f"{REASON_COPY_QUALITY_PREFIX}{reason.code}",
                    reason.message,
                )
                if copy_quality.status == QUALITY_BLOCKED:
                    blocking.append(assembly_reason)
                elif copy_quality.status == QUALITY_WARNING:
                    warnings.append(assembly_reason)
            profile_quality = assess_profile_quality(prospect)
            for reason in profile_quality.reasons:
                assembly_reason = CampaignAssemblyReason(
                    f"{REASON_PROFILE_QUALITY_PREFIX}{reason.code}",
                    reason.message,
                )
                if profile_quality.status == QUALITY_BLOCKED:
                    blocking.append(assembly_reason)
                elif profile_quality.status == QUALITY_WARNING:
                    warnings.append(assembly_reason)
        warnings.extend(CampaignAssemblyReason(REASON_WARNING, warning) for warning in eligibility.warnings)
        status = ASSEMBLY_STATUS_BLOCKED if blocking else (ASSEMBLY_STATUS_WARNING if warnings or eligibility.status == EXPORT_STATUS_WARNING else ASSEMBLY_STATUS_READY)
        return self._result_from_parts(prospect_id, status, prospect, row, resolved, tuple(blocking), tuple(warnings))

    def _result_from_parts(self, prospect_id: str, status: str, prospect: Any, row: Any, resolved: Any, blocking: tuple[CampaignAssemblyReason, ...], warnings: tuple[CampaignAssemblyReason, ...]) -> OutreachReadinessResult:
        complete, total, optional_warnings = self._personalization_summary(prospect, row, resolved)
        warnings = tuple(list(warnings) + list(optional_warnings))
        if status == ASSEMBLY_STATUS_READY and warnings:
            status = ASSEMBLY_STATUS_WARNING
        included = status in {ASSEMBLY_STATUS_READY, ASSEMBLY_STATUS_WARNING}
        return OutreachReadinessResult(
            prospect_id=prospect_id,
            status=status,
            blocking_reasons=blocking,
            warning_reasons=warnings,
            email=_clean(getattr(row, "email", "")) or _clean(getattr(prospect, "email", "")),
            contact_name=_clean(getattr(row, "contact_name", "")) or _clean(getattr(prospect, "contact_name", "")),
            company=_clean(getattr(row, "company", "")) or _clean(getattr(prospect, "company_name", "")),
            project_id=_clean(getattr(row, "project_id", "")) or _clean(getattr(getattr(resolved, "project", None), "id", "")),
            generation_job_id=_clean(getattr(row, "generation_job_id", "")) or _clean(getattr(getattr(resolved, "job", None), "id", "")),
            mockup_path=_clean(getattr(row, "mockup_path", "")),
            headline=_clean(getattr(row, "headline", "")),
            cta=_clean(getattr(row, "cta", "")),
            personalization_basis=_clean(getattr(row, "personalization_basis", "")),
            profile_url=_clean(getattr(prospect, "manual_profile_url", "")) or _clean(getattr(prospect, "resolved_profile_url", "")),
            personalization_complete=complete,
            personalization_total=total,
            included=included,
        )

    def _personalization_summary(self, prospect: Any, row: Any, resolved: Any) -> tuple[int, int, tuple[CampaignAssemblyReason, ...]]:
        mapping = self._run_export_service.get_field_mapping()
        enabled = enabled_mappings_in_order(mapping)
        context = PersonalizationFieldContext(
            prospect=prospect,
            generation_job=getattr(resolved, "job", None),
            project=getattr(resolved, "project", None),
            handoff_fields=row.to_csv_dict() if hasattr(row, "to_csv_dict") else {},
        )
        total = len(enabled)
        complete = 0
        warnings: list[CampaignAssemblyReason] = []
        for item in enabled:
            value = get_personalization_field_value(item.field_key, context)
            if value:
                complete += 1
            elif item.field_key not in {"email", "email_subject", "email_body", "mockup_path", "mockup_url"}:
                warnings.append(CampaignAssemblyReason(REASON_OPTIONAL_FIELD_BLANK, f"Optional field blank: {item.field_key}"))
        return complete, total, tuple(warnings)

    def _summary(self, readiness: tuple[OutreachReadinessResult, ...]) -> CampaignAssemblySummary:
        reason_counts: Counter[str] = Counter()
        warning_counts: Counter[str] = Counter()
        for item in readiness:
            for reason in item.blocking_reasons:
                reason_counts[reason.code] += 1
            for warning in item.warning_reasons:
                warning_counts[warning.code] += 1
        return CampaignAssemblySummary(
            total_prospects=len(readiness),
            ready=sum(1 for item in readiness if item.status == ASSEMBLY_STATUS_READY),
            warning=sum(1 for item in readiness if item.status == ASSEMBLY_STATUS_WARNING),
            blocked=sum(1 for item in readiness if item.status == ASSEMBLY_STATUS_BLOCKED),
            conflict=0,
            excluded=sum(1 for item in readiness if item.status == ASSEMBLY_STATUS_EXCLUDED),
            exportable=sum(1 for item in readiness if item.exportable),
            included=sum(1 for item in readiness if item.included),
            reason_counts=dict(sorted(reason_counts.items())),
            warning_counts=dict(sorted(warning_counts.items())),
        )

    def _summary_message(self, snapshot: CampaignAssemblySnapshot) -> str:
        summary = self._summary(snapshot.readiness)
        return (
            f"Campaign assembly: {summary.total_prospects} considered, "
            f"{summary.included} included/exportable, {summary.blocked} blocked, "
            f"{summary.warning} warnings, {summary.excluded} excluded."
        )