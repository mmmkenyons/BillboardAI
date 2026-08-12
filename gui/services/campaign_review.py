"""Review-layer service over canonical campaign export/package data."""

from __future__ import annotations

import os
from dataclasses import dataclass

from gui.models.campaign_review import (
    CAMPAIGN_REVIEW_STATUS_APPROVED,
    CAMPAIGN_REVIEW_STATUS_EXCLUDED,
    CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW,
    CampaignReviewDecision,
    CampaignReviewRow,
    reviewed_now,
)
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_package import CampaignPackageResult
from gui.models.prospect import Prospect
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import (
    EXPORT_STATUS_BLOCKED,
    CampaignExportRow,
    CampaignExportService,
)
from gui.services.campaign_package import CampaignPackageService


REVIEW_FILTER_ALL = "ALL"
REVIEW_FILTER_APPROVED = "APPROVED"
REVIEW_FILTER_EXCLUDED = "EXCLUDED"
REVIEW_FILTER_NEEDS_REVIEW = "NEEDS_REVIEW"
REVIEW_FILTER_BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CampaignReviewSummary:
    total: int = 0
    approved: int = 0
    excluded: int = 0
    needs_review: int = 0
    technically_blocked: int = 0
    approved_packageable: int = 0


class CampaignReviewService:
    def __init__(
        self,
        *,
        prospect_store: ProspectStore,
        export_service: CampaignExportService,
        review_store: CampaignReviewStore,
        package_service: CampaignPackageService,
    ) -> None:
        self._prospect_store = prospect_store
        self._export_service = export_service
        self._review_store = review_store
        self._package_service = package_service

    def list_rows(self, prospect_ids: list[str] | None = None) -> list[CampaignReviewRow]:
        ordered_ids = self._resolve_target_ids(prospect_ids)
        rows = [self._build_row(prospect_id) for prospect_id in ordered_ids]
        return sorted(rows, key=lambda row: (row.company.lower(), row.prospect_id))

    def filter_rows(self, rows: list[CampaignReviewRow], filter_name: str) -> list[CampaignReviewRow]:
        name = str(filter_name or REVIEW_FILTER_ALL).strip().upper()
        if name == REVIEW_FILTER_APPROVED:
            return [row for row in rows if row.review_status == CAMPAIGN_REVIEW_STATUS_APPROVED]
        if name == REVIEW_FILTER_EXCLUDED:
            return [row for row in rows if row.review_status == CAMPAIGN_REVIEW_STATUS_EXCLUDED]
        if name == REVIEW_FILTER_NEEDS_REVIEW:
            return [row for row in rows if row.review_status == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW]
        if name == REVIEW_FILTER_BLOCKED:
            return [row for row in rows if row.technical_status == EXPORT_STATUS_BLOCKED]
        return list(rows)

    def summary(self, prospect_ids: list[str] | None = None) -> CampaignReviewSummary:
        rows = self.list_rows(prospect_ids)
        return CampaignReviewSummary(
            total=len(rows),
            approved=sum(1 for row in rows if row.review_status == CAMPAIGN_REVIEW_STATUS_APPROVED),
            excluded=sum(1 for row in rows if row.review_status == CAMPAIGN_REVIEW_STATUS_EXCLUDED),
            needs_review=sum(1 for row in rows if row.review_status == CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW),
            technically_blocked=sum(1 for row in rows if row.technical_status == EXPORT_STATUS_BLOCKED),
            approved_packageable=sum(1 for row in rows if row.packageable),
        )

    def get_decision(self, prospect_id: str) -> CampaignReviewDecision:
        return self._review_store.get(prospect_id) or CampaignReviewDecision(prospect_id=str(prospect_id or "").strip())

    def approve(self, prospect_id: str) -> CampaignReviewDecision:
        return self._set_status(prospect_id, CAMPAIGN_REVIEW_STATUS_APPROVED)

    def exclude(self, prospect_id: str) -> CampaignReviewDecision:
        return self._set_status(prospect_id, CAMPAIGN_REVIEW_STATUS_EXCLUDED)

    def mark_needs_review(self, prospect_id: str) -> CampaignReviewDecision:
        return self._set_status(prospect_id, CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW)

    def bulk_approve(self, prospect_ids: list[str]) -> list[CampaignReviewDecision]:
        return [self.approve(prospect_id) for prospect_id in self._dedupe_ids(prospect_ids)]

    def bulk_exclude(self, prospect_ids: list[str]) -> list[CampaignReviewDecision]:
        return [self.exclude(prospect_id) for prospect_id in self._dedupe_ids(prospect_ids)]

    def bulk_mark_needs_review(self, prospect_ids: list[str]) -> list[CampaignReviewDecision]:
        return [self.mark_needs_review(prospect_id) for prospect_id in self._dedupe_ids(prospect_ids)]

    def update_note(self, prospect_id: str, note: str) -> CampaignReviewDecision:
        current = self.get_decision(prospect_id)
        updated = CampaignReviewDecision(
            prospect_id=current.prospect_id,
            status=current.status,
            note=str(note or "").strip(),
            reviewed_at=current.reviewed_at or reviewed_now(),
        )
        self._review_store.upsert(updated)
        self._review_store.save()
        return updated

    def approved_prospect_ids(self, prospect_ids: list[str] | None = None) -> list[str]:
        rows = self.list_rows(prospect_ids)
        return [row.prospect_id for row in rows if row.packageable]

    def build_approved_package(
        self,
        prospect_ids: list[str] | None,
        destination: str,
        campaign_name: str | None = None,
    ) -> CampaignPackageResult:
        approved_ids = self.approved_prospect_ids(prospect_ids)
        return self._package_service.build_package(approved_ids, destination, campaign_name=campaign_name)

    def open_project_id(self, prospect_id: str) -> str:
        row = self._build_row(prospect_id)
        return row.project_id

    def mockup_exists(self, prospect_id: str) -> bool:
        row = self._build_row(prospect_id)
        return bool(row.mockup_path and os.path.isfile(row.mockup_path))

    def _set_status(self, prospect_id: str, status: str) -> CampaignReviewDecision:
        current = self.get_decision(prospect_id)
        updated = CampaignReviewDecision(
            prospect_id=current.prospect_id,
            status=status,
            note=current.note,
            reviewed_at=reviewed_now(),
        )
        self._review_store.upsert(updated)
        self._review_store.save()
        return updated

    def _build_row(self, prospect_id: str) -> CampaignReviewRow:
        decision = self.get_decision(prospect_id)
        eligibility, row, resolved = self._export_service.resolve_for_package(prospect_id)
        prospect = resolved.prospect if resolved is not None else self._prospect_store.get(prospect_id)
        export_row = row or self._fallback_row(prospect)
        opportunity_display = self._opportunity_display(export_row)
        technical_reasons = tuple(eligibility.reasons)
        technical_warnings = tuple(eligibility.warnings)
        if row is not None and resolved is not None:
            source_path = os.path.abspath(resolved.concept.image_path or resolved.job.result_path)
            if not source_path or not os.path.isfile(source_path):
                technical_reasons = tuple(list(technical_reasons) + ["Source mockup file no longer exists."])
                technical_status = EXPORT_STATUS_BLOCKED
            else:
                technical_status = eligibility.status
        else:
            technical_status = eligibility.status
        return CampaignReviewRow(
            prospect_id=export_row.prospect_id or prospect_id,
            company=export_row.company or (prospect.company_name if prospect is not None else ""),
            email=export_row.email or (prospect.email if prospect is not None else ""),
            contact_name=export_row.contact_name or (prospect.contact_name if prospect is not None else ""),
            city=export_row.city or (prospect.city if prospect is not None else ""),
            state=export_row.state or (prospect.state if prospect is not None else ""),
            category=export_row.category or (prospect.category if prospect is not None else ""),
            website=export_row.website or (prospect.website if prospect is not None else ""),
            email_subject=export_row.email_subject,
            email_body=export_row.email_body,
            mockup_path=export_row.mockup_path,
            opportunity_display=opportunity_display,
            creative_summary=export_row.creative_summary,
            placement_name=export_row.placement_name,
            placement_type=export_row.placement_type,
            technical_status=technical_status,
            technical_reasons=technical_reasons,
            technical_warnings=technical_warnings,
            review_status=decision.status,
            review_note=decision.note,
            reviewed_at=decision.reviewed_at,
            generation_job_id=export_row.generation_job_id,
            project_id=export_row.project_id,
        )

    def _fallback_row(self, prospect: Prospect | None) -> CampaignExportRow:
        if prospect is None:
            return CampaignExportRow()
        return CampaignExportRow(
            prospect_id=prospect.prospect_id,
            company=prospect.company_name,
            email=prospect.email,
            contact_name=prospect.contact_name,
            city=prospect.city,
            state=prospect.state,
            category=prospect.category,
            website=prospect.website,
        )

    def _opportunity_display(self, row: CampaignExportRow) -> str:
        parts = [part for part in [row.location_name, row.placement_name, row.personalization_location] if str(part or "").strip()]
        return " — ".join(parts)

    def _resolve_target_ids(self, prospect_ids: list[str] | None) -> list[str]:
        if prospect_ids:
            return self._dedupe_ids(prospect_ids)
        return [prospect.prospect_id for prospect in self._prospect_store.list()]

    def _dedupe_ids(self, prospect_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in prospect_ids:
            prospect_id = str(raw or "").strip()
            if not prospect_id or prospect_id in seen:
                continue
            seen.add(prospect_id)
            ordered.append(prospect_id)
        return ordered