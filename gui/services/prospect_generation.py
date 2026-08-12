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
    ProspectGenerationJob,
)
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore

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
    ) -> None:
        self._prospect_store = prospect_store
        self._job_store = job_store or ProspectGenerationStore()
        self._generate = generation_callable or (lambda request: engine_generate(request))
        self._default_output_root = os.path.abspath(default_output_root) if default_output_root else os.path.abspath(os.path.join("output", "prospect_mockups"))
        self._project_store = project_store or ProjectStore(root=self._default_output_root)

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
        effective_root = os.path.abspath(output_root or self._default_output_root)
        job = ProspectGenerationJob(
            prospect_id=prospect.prospect_id,
            website=prospect.website,
            template=eligibility.resolved_template,
            status=JOB_STATUS_QUEUED,
            output_root=effective_root,
            metadata={"company_name": prospect.company_name},
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
    ) -> list[JobCreationResult]:
        results: list[JobCreationResult] = []
        template_map = templates or {}
        for prospect_id in prospect_ids:
            results.append(
                self.create_job(
                    prospect_id,
                    template=template_map.get(prospect_id),
                    output_root=output_root,
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
        output_path = os.path.join(project.image_path, project.next_concept_filename())
        request = MockupRequest(
            url=job.website,
            template=job.template,
            output_folder=project.root_dir,
            output_path=output_path,
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
        if isinstance(result.extra, dict):
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