"""Campaign export service for Smartlead-ready CSV packages.

Read-only over the canonical prospect/job/project stores. This module never
queues generation, creates projects, or mutates prospect workflow state.
"""

from __future__ import annotations

import csv
import os
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

from gui.models.mockup_concept import MockupConcept
from gui.models.project import Project
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    OpportunityGenerationContext,
    ProspectGenerationJob,
)
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.outreach_generation import (
    OutreachGenerationService,
    OutreachPersonalizationContext,
)


EXPORT_STATUS_READY = "READY"
EXPORT_STATUS_WARNING = "WARNING"
EXPORT_STATUS_BLOCKED = "BLOCKED"

CSV_COLUMNS: tuple[str, ...] = (
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
    "mockup_path",
    "mockup_filename",
    "quality_score",
    "template",
    "personalization_location",
    "creative_summary",
    "placement_name",
    "placement_type",
    "location_name",
    "prospect_id",
    "generation_job_id",
    "project_id",
    "opportunity_id",
    "location_id",
    "placement_id",
)


@dataclass(frozen=True)
class CampaignExportEligibility:
    status: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    selected_job_id: str = ""
    selected_project_id: str = ""


@dataclass(frozen=True)
class CampaignExportRow:
    email: str = ""
    first_name: str = ""
    contact_name: str = ""
    company: str = ""
    email_subject: str = ""
    email_body: str = ""
    email_opening_line: str = ""
    personalization_basis: str = ""
    website: str = ""
    category: str = ""
    city: str = ""
    state: str = ""
    headline: str = ""
    cta: str = ""
    mockup_path: str = ""
    mockup_filename: str = ""
    quality_score: str = ""
    template: str = ""
    personalization_location: str = ""
    creative_summary: str = ""
    placement_name: str = ""
    placement_type: str = ""
    location_name: str = ""
    prospect_id: str = ""
    generation_job_id: str = ""
    project_id: str = ""
    opportunity_id: str = ""
    location_id: str = ""
    placement_id: str = ""

    def to_csv_dict(self) -> dict[str, str]:
        data = asdict(self)
        return {column: str(data.get(column, "") or "") for column in CSV_COLUMNS}


@dataclass(frozen=True)
class CampaignExportPreview:
    prospect_id: str
    company: str
    email: str
    status: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    generation_job_id: str = ""
    project_id: str = ""


@dataclass(frozen=True)
class _ResolvedExport:
    prospect: Prospect
    job: ProspectGenerationJob
    project: Project
    concept: MockupConcept
    context: OpportunityGenerationContext | None
    warnings: tuple[str, ...] = field(default_factory=tuple)


class CampaignExportService:
    def __init__(
        self,
        *,
        prospect_store: ProspectStore,
        job_store: ProspectGenerationStore,
        project_store: ProjectStore,
    ) -> None:
        self._prospect_store = prospect_store
        self._job_store = job_store
        self._project_store = project_store
        self._outreach_service = OutreachGenerationService()

    def check_eligibility(self, prospect_id: str) -> CampaignExportEligibility:
        prospect = self._prospect_store.get(prospect_id)
        if prospect is None:
            return CampaignExportEligibility(
                status=EXPORT_STATUS_BLOCKED,
                reasons=("Prospect not found.",),
            )
        if not _clean(prospect.email):
            return CampaignExportEligibility(
                status=EXPORT_STATUS_BLOCKED,
                reasons=("Missing email.",),
            )
        jobs = self._jobs_for_prospect(prospect_id)
        if not jobs:
            return CampaignExportEligibility(
                status=EXPORT_STATUS_BLOCKED,
                reasons=("No generation jobs found.",),
            )
        resolved = self._resolve_export(prospect)
        if resolved is None:
            terminal_statuses = {job.status for job in jobs}
            reasons: list[str] = []
            if JOB_STATUS_SUCCEEDED not in terminal_statuses:
                if terminal_statuses <= {JOB_STATUS_QUEUED}:
                    reasons.append("Generation is still queued.")
                elif terminal_statuses <= {JOB_STATUS_RUNNING}:
                    reasons.append("Generation is still running.")
                elif terminal_statuses <= {JOB_STATUS_FAILED}:
                    reasons.append("No usable successful generation exists.")
                else:
                    reasons.append("No usable successful generation exists.")
            else:
                reasons.append("Successful generation could not be resolved to a project and mockup path.")
            return CampaignExportEligibility(
                status=EXPORT_STATUS_BLOCKED,
                reasons=tuple(reasons),
            )
        status = EXPORT_STATUS_READY if not resolved.warnings else EXPORT_STATUS_WARNING
        return CampaignExportEligibility(
            status=status,
            warnings=resolved.warnings,
            selected_job_id=resolved.job.id,
            selected_project_id=resolved.project.id,
        )

    def build_row(self, prospect_id: str) -> CampaignExportRow:
        prospect = self._prospect_store.get(prospect_id)
        if prospect is None:
            raise ValueError(f"Prospect {prospect_id!r} not found")
        resolved = self._resolve_export(prospect)
        if resolved is None:
            raise ValueError(f"Prospect {prospect_id!r} is not exportable")
        return self._build_row_from_resolved(resolved)

    def resolve_for_package(self, prospect_id: str) -> tuple[CampaignExportEligibility, CampaignExportRow | None, _ResolvedExport | None]:
        """Return canonical export eligibility/row plus the authoritative resolved source.

        This preserves CampaignExportService as the single source of truth for
        successful-job, project, concept, and outreach selection while allowing
        package creation to add package-specific validation such as missing
        source asset files.
        """
        eligibility = self.check_eligibility(prospect_id)
        prospect = self._prospect_store.get(prospect_id)
        if prospect is None:
            return eligibility, None, None
        resolved = self._resolve_export(prospect)
        row = self._build_row_from_resolved(resolved) if resolved is not None else None
        return eligibility, row, resolved

    def build_rows(self, prospect_ids: Sequence[str]) -> list[CampaignExportRow]:
        rows: list[CampaignExportRow] = []
        seen: set[str] = set()
        for prospect_id in sorted({str(p) for p in prospect_ids if str(p)}):
            if prospect_id in seen:
                continue
            seen.add(prospect_id)
            eligibility = self.check_eligibility(prospect_id)
            if eligibility.status == EXPORT_STATUS_BLOCKED:
                continue
            rows.append(self.build_row(prospect_id))
        return rows

    def preview_rows(self, prospect_ids: Sequence[str]) -> list[CampaignExportPreview]:
        previews: list[CampaignExportPreview] = []
        for prospect_id in sorted({str(p) for p in prospect_ids if str(p)}):
            prospect = self._prospect_store.get(prospect_id)
            eligibility = self.check_eligibility(prospect_id)
            previews.append(
                CampaignExportPreview(
                    prospect_id=prospect_id,
                    company=prospect.company_name if prospect is not None else "",
                    email=prospect.email if prospect is not None else "",
                    status=eligibility.status,
                    reasons=eligibility.reasons,
                    warnings=eligibility.warnings,
                    generation_job_id=eligibility.selected_job_id,
                    project_id=eligibility.selected_project_id,
                )
            )
        return previews

    def export_csv(self, prospect_ids: Sequence[str], output_path: str) -> str:
        rows = self.build_rows(prospect_ids)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_csv_dict())
        return os.path.abspath(output_path)

    def _resolve_export(self, prospect: Prospect) -> _ResolvedExport | None:
        if not _clean(prospect.email):
            return None
        for job in self._select_candidate_jobs(prospect.prospect_id):
            project = self._safe_load_project(job.project_id)
            if project is None:
                continue
            concept = self._resolve_concept(project, job)
            if concept is None:
                continue
            image_path = _clean(concept.image_path or job.result_path)
            if not image_path:
                continue
            warnings = list(self._derive_warnings(prospect, job, concept))
            return _ResolvedExport(
                prospect=prospect,
                job=job,
                project=project,
                concept=concept,
                context=job.opportunity_context,
                warnings=tuple(warnings),
            )
        return None

    def _build_row_from_resolved(self, resolved: _ResolvedExport) -> CampaignExportRow:
        prospect = resolved.prospect
        job = resolved.job
        concept = resolved.concept
        context = resolved.context
        headline = _clean(concept.headline)
        city = _clean(prospect.city)
        state = _clean(prospect.state)
        outreach = self._outreach_service.generate_message(
            OutreachPersonalizationContext(
                first_name=_derive_first_name(prospect.contact_name),
                contact_name=_clean(prospect.contact_name),
                company_name=_clean(prospect.company_name),
                website=_clean(prospect.website),
                category=_clean(prospect.category),
                prospect_city=city,
                prospect_state=state,
                headline=headline,
                cta=_clean(concept.cta),
                template=_clean(concept.template or job.template),
                personalization_location=_clean(_trustworthy_location(prospect, context)),
                opportunity_city=_clean(context.city) if context else "",
                opportunity_state=_clean(context.state) if context else "",
                placement_name=_clean(context.placement_name) if context else "",
                placement_type=_clean(context.placement_type) if context else "",
                retailer_name=_clean(context.retailer_name) if context else "",
            )
        )
        return CampaignExportRow(
            email=_clean(prospect.email),
            first_name=_derive_first_name(prospect.contact_name),
            contact_name=_clean(prospect.contact_name),
            company=_clean(prospect.company_name),
            email_subject=outreach.subject,
            email_body=outreach.body,
            email_opening_line=outreach.opening_line,
            personalization_basis=outreach.personalization_basis,
            website=_clean(prospect.website),
            category=_clean(prospect.category),
            city=city,
            state=state,
            headline=headline,
            cta=_clean(concept.cta),
            mockup_path=_clean(concept.image_path or job.result_path),
            mockup_filename=os.path.basename(_clean(concept.image_path or job.result_path)),
            quality_score=_format_quality(concept.quality_score),
            template=_clean(concept.template or job.template),
            personalization_location=_clean(_trustworthy_location(prospect, context)),
            creative_summary=_build_creative_summary(prospect, headline, context),
            placement_name=_clean(context.placement_name) if context else "",
            placement_type=_clean(context.placement_type) if context else "",
            location_name=_clean(context.location_name) if context else "",
            prospect_id=prospect.prospect_id,
            generation_job_id=job.id,
            project_id=resolved.project.id,
            opportunity_id=_clean(job.opportunity_id),
            location_id=_clean(job.location_id),
            placement_id=_clean(job.placement_id),
        )

    def _jobs_for_prospect(self, prospect_id: str) -> list[ProspectGenerationJob]:
        return [job for job in self._job_store.list() if job.prospect_id == prospect_id]

    def _select_candidate_jobs(self, prospect_id: str) -> list[ProspectGenerationJob]:
        jobs = [job for job in self._jobs_for_prospect(prospect_id) if job.status == JOB_STATUS_SUCCEEDED]
        return sorted(
            jobs,
            key=lambda job: (
                job.completed_at or job.created_at,
                job.created_at,
                job.id,
            ),
            reverse=True,
        )

    def _safe_load_project(self, project_id: str) -> Project | None:
        if not _clean(project_id):
            return None
        try:
            return self._project_store.load(project_id)
        except FileNotFoundError:
            return None

    def _resolve_concept(self, project: Project, job: ProspectGenerationJob) -> MockupConcept | None:
        selected = project.get_selected_concept()
        if selected is not None and _clean(selected.image_path or job.result_path):
            if job.result_path and os.path.abspath(selected.image_path) == os.path.abspath(job.result_path):
                return selected
        for concept in reversed(project.concepts):
            if not _clean(concept.image_path):
                continue
            if job.result_path and os.path.abspath(concept.image_path) == os.path.abspath(job.result_path):
                return concept
        if selected is not None and _clean(selected.image_path):
            return selected
        for concept in reversed(project.concepts):
            if _clean(concept.image_path):
                return concept
        return None

    def _derive_warnings(
        self,
        prospect: Prospect,
        job: ProspectGenerationJob,
        concept: MockupConcept,
    ) -> Iterable[str]:
        if not _clean(prospect.contact_name):
            yield "Missing contact name."
        if not _clean(prospect.city):
            yield "Missing city."
        if not _clean(job.opportunity_id):
            yield "Generic generation without opportunity snapshot."
        if concept.quality_score in (None, ""):
            yield "Missing quality score."


def _clean(value: object) -> str:
    return str(value or "").strip()


def _derive_first_name(contact_name: str) -> str:
    parts = [part for part in _clean(contact_name).split() if part]
    if not parts:
        return ""
    first = parts[0]
    if len(first) < 2:
        return ""
    if any(ch in first for ch in ",@/\\"):
        return ""
    return first


def _format_quality(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _trustworthy_location(
    prospect: Prospect,
    context: OpportunityGenerationContext | None,
) -> str:
    if _clean(prospect.city):
        return _clean(prospect.city)
    if context is not None and _clean(context.city):
        return _clean(context.city)
    return ""


def _build_creative_summary(
    prospect: Prospect,
    headline: str,
    context: OpportunityGenerationContext | None,
) -> str:
    category = _clean(prospect.category)
    locality = _trustworthy_location(prospect, context)
    parts: list[str] = []
    if category:
        parts.append(category)
    parts.append("billboard concept")
    if locality:
        parts.append(f"for {locality}")
    summary = " ".join(parts).strip()
    return summary or headline