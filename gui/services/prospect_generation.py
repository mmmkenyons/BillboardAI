"""Qt-free prospect batch mockup generation orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from gui.engine_bridge import generate as engine_generate
from gui.models.mockup_concept import MockupConcept
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.models.project import Project
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect, is_valid_website
from gui.models.prospect_generation import (
    GenerationEligibility,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    OpportunityGenerationContext,
    ProspectGenerationJob,
)
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.profile_resolver import effective_scrape_url
from gui.services.prospect_opportunity_workspace import ProspectOpportunityWorkspaceService


class OpportunitySelectionError(ValueError):
    """Raised when an explicit opportunity selection is invalid."""

GenerationCallable = Callable[[MockupRequest], MockupResult]

SUPPORTED_TEMPLATES = ("contractor", "dentist", "realtor")
CATEGORY_TEMPLATE_MAP = {
    "roofing": "contractor",
    "contractor": "contractor",
    "painting": "contractor",
    "plumbing": "contractor",
    "hvac": "contractor",
    "dentist": "dentist",
    "dental": "dentist",
    "realtor": "realtor",
    "real estate": "realtor",
}


@dataclass
class JobCreationResult:
    prospect_id: str
    eligible: bool
    reasons: list[str]
    job: ProspectGenerationJob | None = None


class ProspectGenerationService:
    def __init__(
        self,
        *,
        prospect_store: ProspectStore,
        job_store: ProspectGenerationStore | None = None,
        generation_callable: GenerationCallable | None = None,
        default_output_root: str | None = None,
        project_store: ProjectStore | None = None,
        opportunity_workspace_service: ProspectOpportunityWorkspaceService | None = None,
    ) -> None:
        self._prospect_store = prospect_store
        self._job_store = job_store or ProspectGenerationStore()
        self._generate = generation_callable or (lambda request: engine_generate(request))
        self._default_output_root = os.path.abspath(default_output_root) if default_output_root else os.path.abspath(os.path.join("output", "prospect_mockups"))
        self._project_store = project_store or ProjectStore(root=self._default_output_root)
        self._opportunity_workspace_service = opportunity_workspace_service or ProspectOpportunityWorkspaceService(
            prospect_store=self._prospect_store,
            project_store=self._project_store,
        )

    @property
    def prospect_store(self) -> ProspectStore:
        return self._prospect_store

    @property
    def job_store(self) -> ProspectGenerationStore:
        return self._job_store

    @property
    def project_store(self) -> ProjectStore:
        return self._project_store

    def list_jobs(self) -> list[ProspectGenerationJob]:
        return self._job_store.list()

    def jobs_for_prospect(self, prospect_id: str) -> list[ProspectGenerationJob]:
        return [job for job in self._job_store.list() if job.prospect_id == prospect_id]

    def check_eligibility(self, prospect_id: str, template: str | None = None) -> GenerationEligibility:
        prospect = self._prospect_store.get(prospect_id)
        if prospect is None:
            return GenerationEligibility(False, ["Prospect not found"])
        website = (prospect.website or "").strip()
        reasons: list[str] = []
        if not website:
            reasons.append("Missing website")
        elif not is_valid_website(website):
            reasons.append("Invalid website")
        resolved_template = self.resolve_template(prospect, explicit_template=template)
        if not resolved_template:
            reasons.append("No supported template")
        elif resolved_template not in SUPPORTED_TEMPLATES:
            reasons.append("Unsupported template")
        return GenerationEligibility(
            eligible=not reasons,
            reasons=reasons,
            resolved_template=resolved_template,
            website=website,
        )

    def resolve_template(self, prospect: Prospect, explicit_template: str | None = None) -> str:
        if explicit_template:
            explicit = explicit_template.strip().lower()
            return explicit if explicit in SUPPORTED_TEMPLATES else ""
        category = (prospect.category or "").strip().lower()
        return CATEGORY_TEMPLATE_MAP.get(category, "")

    def create_job(
        self,
        prospect_id: str,
        *,
        template: str | None = None,
        output_root: str | None = None,
        opportunity_id: str | None = None,
    ) -> JobCreationResult:
        eligibility = self.check_eligibility(prospect_id, template)
        if not eligibility.eligible:
            return JobCreationResult(prospect_id, False, list(eligibility.reasons))
        active = self._find_active_duplicate(prospect_id, eligibility.resolved_template)
        if active is not None:
            return JobCreationResult(prospect_id, False, ["Active job already exists"], active)
        prospect = self._prospect_store.get(prospect_id)
        if prospect is None:
            return JobCreationResult(prospect_id, False, ["Prospect not found"])
        try:
            opportunity_context = self._resolve_opportunity_context(prospect_id, opportunity_id=opportunity_id)
        except OpportunitySelectionError as exc:
            return JobCreationResult(prospect_id, False, [str(exc)])
        effective_root = os.path.abspath(output_root or self._default_output_root)
        job = ProspectGenerationJob(
            prospect_id=prospect.prospect_id,
            # Sprint 5Z: snapshot the effective scrape URL (manual -> resolved ->
            # parent). Execution/run_job is unchanged; existing jobs keep their
            # original snapshot; a new/regenerated job uses the current target.
            website=effective_scrape_url(prospect),
            template=eligibility.resolved_template,
            status=JOB_STATUS_QUEUED,
            output_root=effective_root,
            opportunity_id=opportunity_context.opportunity_id if opportunity_context else "",
            location_id=opportunity_context.location_id if opportunity_context else "",
            placement_id=opportunity_context.placement_id if opportunity_context else "",
            opportunity_context=opportunity_context,
            metadata={
                "company_name": prospect.company_name,
                "opportunity_label": self._format_opportunity_label(opportunity_context),
            },
        )
        self._job_store.upsert(job)
        self._job_store.save()
        return JobCreationResult(prospect_id, True, [], job)

    def create_jobs(
        self,
        prospect_ids: Iterable[str],
        *,
        templates: dict[str, str] | None = None,
        output_root: str | None = None,
        opportunity_ids: dict[str, str] | None = None,
    ) -> list[JobCreationResult]:
        results: list[JobCreationResult] = []
        template_map = templates or {}
        opportunity_map = opportunity_ids or {}
        for prospect_id in prospect_ids:
            results.append(
                self.create_job(
                    prospect_id,
                    template=template_map.get(prospect_id),
                    output_root=output_root,
                    opportunity_id=opportunity_map.get(prospect_id),
                )
            )
        return results

    def run_job(self, job_id: str) -> ProspectGenerationJob:
        job = self._require_job(job_id)
        if job.status not in (JOB_STATUS_QUEUED, JOB_STATUS_FAILED, JOB_STATUS_SUCCEEDED):
            return job
        job.status = JOB_STATUS_RUNNING
        job.started_at = datetime.now()
        job.completed_at = None
        job.error = ""
        self._save_job(job)
        try:
            result = self._invoke_generation(job)
            if result.success:
                self._handle_success(job, result)
            else:
                self._handle_failure(job, result.message or "Generation failed")
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(job, str(exc))
        return job

    def run_queue(self) -> list[ProspectGenerationJob]:
        outcomes: list[ProspectGenerationJob] = []
        queued = [job for job in self._job_store.list() if job.status == JOB_STATUS_QUEUED]
        for job in queued:
            outcomes.append(self.run_job(job.id))
        return outcomes

    def _invoke_generation(self, job: ProspectGenerationJob) -> MockupResult:
        project = self._ensure_project(job)
        prospect = self._prospect_store.get(job.prospect_id)
        person_context = {}
        if prospect is not None:
            person_context = {
                "contact_name": prospect.contact_name,
                "contact_title": prospect.contact_title,
                "resolved_profile_url": prospect.resolved_profile_url,
                "manual_profile_url": prospect.manual_profile_url,
                "resolution_status": prospect.resolution_status,
                "resolution_confidence": prospect.resolution_confidence,
            }
        output_path = os.path.join(project.image_path, project.next_concept_filename())
        request = MockupRequest(
            url=job.website,
            template=job.template,
            output_folder=project.root_dir,
            output_path=output_path,
            options={"person_context": person_context} if person_context else {},
            opportunity_context=job.opportunity_context,
        )
        return self._generate(request)

    def _handle_success(self, job: ProspectGenerationJob, result: MockupResult) -> None:
        project = self._load_project(job)
        concept = MockupConcept.create(
            image_path=result.preview_path or result.output_path,
            template=job.template,
            headline=result.headline,
            cta=result.cta,
            quality_score=result.quality_score,
            company_name=result.company_name or project.company,
        )
        project.add_concept(concept)
        project.metadata["prospect_id"] = job.prospect_id
        project.metadata["generation_job_id"] = job.id
        if job.opportunity_id:
            project.metadata["opportunity_id"] = job.opportunity_id
        if job.location_id:
            project.metadata["location_id"] = job.location_id
        if job.placement_id:
            project.metadata["placement_id"] = job.placement_id
        if isinstance(result.extra, dict):
            brand_profile = result.extra.get("brand_profile")
            if isinstance(brand_profile, dict):
                project.brand_profile = dict(brand_profile)
            render_context = result.extra.get("render_context")
            if isinstance(render_context, dict):
                project.set_render_context(dict(render_context))
        self._project_store.save(project)
        prospect = self._prospect_store.get(job.prospect_id)
        if prospect is not None:
            prospect.metadata["project_id"] = project.id
            prospect.metadata["generation_result_path"] = result.preview_path or result.output_path
            prospect.touch()
            self._prospect_store.update(prospect)
            self._prospect_store.save()
        job.status = JOB_STATUS_SUCCEEDED
        job.completed_at = datetime.now()
        job.result_path = result.preview_path or result.output_path
        job.project_id = project.id
        job.project_root = project.root_dir
        job.error = ""
        self._save_job(job)

    def _handle_failure(self, job: ProspectGenerationJob, error: str) -> None:
        job.status = JOB_STATUS_FAILED
        job.completed_at = datetime.now()
        job.error = str(error)
        self._save_job(job)

    def _find_active_duplicate(self, prospect_id: str, template: str) -> ProspectGenerationJob | None:
        for job in self._job_store.list():
            if job.prospect_id == prospect_id and job.template == template and job.status in (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING):
                return job
        return None

    def _require_job(self, job_id: str) -> ProspectGenerationJob:
        job = self._job_store.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job {job_id}")
        return job

    def _save_job(self, job: ProspectGenerationJob) -> None:
        self._job_store.upsert(job)
        self._job_store.save()

    def _load_project(self, job: ProspectGenerationJob) -> Project:
        if not job.project_id:
            raise ValueError("Job is missing project_id")
        return self._project_store.load(job.project_id)

    def _ensure_project(self, job: ProspectGenerationJob) -> Project:
        if job.project_id:
            return self._load_project(job)
        prospect = self._prospect_store.get(job.prospect_id)
        if prospect is None:
            raise ValueError(f"Unknown prospect {job.prospect_id}")
        project = self._project_store.create(
            company_name=prospect.company_name,
            website=prospect.website,
            name=prospect.domain or prospect.company_name or prospect.prospect_id,
        )
        project.metadata["prospect_id"] = prospect.prospect_id
        self._project_store.save(project)
        job.project_id = project.id
        job.project_root = project.root_dir
        self._save_job(job)
        return project

    def recommended_opportunity_label(self, prospect_id: str) -> str:
        return self._format_opportunity_label(self._resolve_opportunity_context(prospect_id, opportunity_id=None))

    def _resolve_opportunity_context(
        self,
        prospect_id: str,
        *,
        opportunity_id: str | None,
    ) -> OpportunityGenerationContext | None:
        workspace = self._opportunity_workspace_service
        recommendation_service = workspace.recommendation_service
        inventory_store = recommendation_service._inventory_store
        opportunity_service = recommendation_service._opportunity_service
        try:
            inventory_store.load()
        except FileNotFoundError:
            pass
        opportunity_service.ensure_loaded()

        if opportunity_id:
            opportunity = opportunity_service.get(opportunity_id)
            if opportunity is None:
                raise OpportunitySelectionError("Opportunity not found")
            if opportunity.prospect_id != prospect_id:
                raise OpportunitySelectionError("Opportunity does not belong to prospect")
            location = inventory_store.inventory.get_location(opportunity.location_id)
            if location is None:
                raise OpportunitySelectionError("Opportunity location not found")
            placement = inventory_store.inventory.get_placement(opportunity.placement_id)
            if placement is None:
                raise OpportunitySelectionError("Opportunity placement not found")
            retailer = inventory_store.inventory.get_retailer(location.retailer_id)
            return OpportunityGenerationContext(
                opportunity_id=opportunity.opportunity_id,
                location_id=location.location_id,
                placement_id=placement.placement_id,
                scene_template=placement.scene_template or "cart_corral",
                retailer_name=retailer.name if retailer is not None else "",
                location_name=location.name or "",
                store_number=location.store_number or "",
                city=location.city or "",
                state=location.state or "",
                placement_name=placement.name or "",
                placement_type=placement.placement_type or "",
            )

        snapshot = workspace.snapshot_for_prospect(prospect_id)
        best_store = snapshot.best_store
        if best_store is None:
            return None
        placement = inventory_store.inventory.get_placement(best_store.placement_id)
        return OpportunityGenerationContext(
            opportunity_id=best_store.opportunity_id or "",
            location_id=best_store.location_id or "",
            placement_id=best_store.placement_id or "",
            scene_template=(placement.scene_template if placement is not None else "") or "cart_corral",
            retailer_name=best_store.retailer_name or "",
            location_name=best_store.location_name or "",
            store_number=best_store.store_number or "",
            city=best_store.city or "",
            state=best_store.state or "",
            placement_name=best_store.placement_name or "",
            placement_type=best_store.placement_type or "",
        )

    @staticmethod
    def _format_opportunity_label(context: OpportunityGenerationContext | None) -> str:
        if context is None or not context.opportunity_id:
            return "Generic"
        retailer = context.retailer_name.strip()
        store = context.store_number.strip()
        city = context.city.strip()
        name = retailer
        if retailer and store:
            name = f"{retailer} #{store}"
        elif context.location_name.strip():
            name = context.location_name.strip()
        if city:
            return f"{name} — {city}" if name else city
        return name or "Generic"