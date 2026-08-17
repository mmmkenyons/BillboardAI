"""Sprint 5W read-only Campaign Run orchestration service.

Composes the canonical prospect/research/opportunity/generation/outreach/review/
package/Smartlead services to build a derived, presentation-only snapshot of a
campaign run. This module NEVER duplicates business logic: it reads results from
existing stores/services and derives stage state, next-action, and blockers.

It never:
- creates research jobs / opportunities / projects / mockups / outreach
- approves/excludes prospects
- builds packages
- hosts assets / publishes leads / activates campaigns

Only explicit existing stage actions (invoked elsewhere) mutate state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from gui.models.campaign_review import (
    CAMPAIGN_REVIEW_STATUS_APPROVED,
    CAMPAIGN_REVIEW_STATUS_EXCLUDED,
    CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW,
)
from gui.models.campaign_run import CampaignRun, CampaignRunStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from gui.services.campaign_export import (
    EXPORT_STATUS_BLOCKED,
    EXPORT_STATUS_READY,
    EXPORT_STATUS_WARNING,
    CampaignExportService,
)
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.prospect_generation import ProspectGenerationService
from gui.services.prospect_opportunity_workspace import ProspectOpportunityWorkspaceService
from gui.services.research_queue import (
    PROSPECT_FAILED,
    PROSPECT_NOT_READY,
    PROSPECT_QUEUED,
    PROSPECT_READY,
    PROSPECT_RUNNING,
    PROSPECT_SUCCEEDED,
    ResearchQueueStore,
)
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.workflow_presentation import package_matches_scope

# Derived stage status labels (presentation-only; never persisted).
STAGE_NOT_STARTED = "NOT_STARTED"
STAGE_READY = "READY"
STAGE_IN_PROGRESS = "IN_PROGRESS"
STAGE_COMPLETE = "COMPLETE"
STAGE_BLOCKED = "BLOCKED"
STAGE_FAILED = "FAILED"
STAGE_NOT_APPLICABLE = "NOT_APPLICABLE"

# Derived next-action labels (presentation-only).
ACTION_ADD_WEBSITE = "Add website"
ACTION_RESEARCH = "Research"
ACTION_RESOLVE_OPPORTUNITY = "Resolve Opportunity"
ACTION_GENERATE = "Generate"
ACTION_GENERATE_OUTREACH = "Generate Outreach"
ACTION_REVIEW = "Review"
ACTION_BUILD_PACKAGE = "Build Package"
ACTION_PREPARE_SMARTLEAD = "Prepare Smartlead"
ACTION_READY = "Ready"
ACTION_BLOCKED = "Blocked"

# Derived run-level overall states (presentation-only; never persisted).
RUN_STATE_EMPTY = "EMPTY"
RUN_STATE_IN_PROGRESS = "IN_PROGRESS"
RUN_STATE_NEEDS_ATTENTION = "NEEDS_ATTENTION"
RUN_STATE_READY_FOR_REVIEW = "READY_FOR_REVIEW"
RUN_STATE_READY_FOR_PACKAGE = "READY_FOR_PACKAGE"
RUN_STATE_READY_FOR_SMARTLEAD = "READY_FOR_SMARTLEAD"
RUN_STATE_COMPLETE = "COMPLETE"

# Navigation targets (page keys understood by MainWindow.show_page).
NAV_PROSPECTS = "prospects"
NAV_PIPELINE = "pipeline"
NAV_BATCH = "batch"
NAV_CAMPAIGN_REVIEW = "campaign_review"
NAV_SMARTLEAD = "smartlead"
NAV_CAMPAIGN_RUN = "campaign_run"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class CampaignRunProspectRow:
    """Derived, presentation-only snapshot for one prospect in a run.

    Every field is derived from canonical stores/services at snapshot time. No
    stage state is persisted on the run itself, so this row can never drift from
    the canonical source of truth.
    """

    prospect_id: str
    company_name: str = ""
    email: str = ""
    website: str = ""
    category: str = ""
    prospect_ready: bool = False
    research_status: str = STAGE_NOT_STARTED
    opportunity_status: str = STAGE_NOT_STARTED
    generation_status: str = STAGE_NOT_STARTED
    outreach_status: str = STAGE_NOT_STARTED
    review_status: str = STAGE_NOT_STARTED
    package_status: str = STAGE_NOT_STARTED
    smartlead_status: str = STAGE_NOT_STARTED
    next_action: str = ACTION_BLOCKED
    blockers: tuple[str, ...] = ()
    # Canonical IDs (read-only, for the detail pane / open actions).
    project_id: str = ""
    generation_job_id: str = ""
    opportunity_id: str = ""
    review_status_value: str = ""  # raw APPROVED/EXCLUDED/NEEDS_REVIEW
    technical_status: str = ""  # raw READY/WARNING/BLOCKED
    mockup_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "prospect_id": self.prospect_id,
            "company_name": self.company_name,
            "email": self.email,
            "website": self.website,
            "category": self.category,
            "prospect_ready": self.prospect_ready,
            "research_status": self.research_status,
            "opportunity_status": self.opportunity_status,
            "generation_status": self.generation_status,
            "outreach_status": self.outreach_status,
            "review_status": self.review_status,
            "package_status": self.package_status,
            "smartlead_status": self.smartlead_status,
            "next_action": self.next_action,
            "blockers": list(self.blockers),
            "project_id": self.project_id,
            "generation_job_id": self.generation_job_id,
            "opportunity_id": self.opportunity_id,
            "review_status_value": self.review_status_value,
            "technical_status": self.technical_status,
            "mockup_path": self.mockup_path,
        }


@dataclass(frozen=True)
class CampaignRunSummary:
    """Run-level derived counts, overall state, and recommended next action.

    Every field is derived from canonical stores at snapshot time. Nothing here
    is persisted; it is recomputed on demand so it can never drift.
    """

    total_prospects: int = 0
    ready_for_research: int = 0
    research_complete: int = 0
    opportunity_ready: int = 0
    generated: int = 0
    outreach_ready: int = 0
    approved: int = 0
    packageable: int = 0
    package_built: int = 0
    smartlead_ready: int = 0
    blocked: int = 0
    needs_attention: int = 0
    ready: int = 0
    overall_state: str = RUN_STATE_EMPTY
    recommended_next_action: str = ACTION_BLOCKED
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_prospects": self.total_prospects,
            "ready_for_research": self.ready_for_research,
            "research_complete": self.research_complete,
            "opportunity_ready": self.opportunity_ready,
            "generated": self.generated,
            "outreach_ready": self.outreach_ready,
            "approved": self.approved,
            "packageable": self.packageable,
            "package_built": self.package_built,
            "smartlead_ready": self.smartlead_ready,
            "blocked": self.blocked,
            "needs_attention": self.needs_attention,
            "ready": self.ready,
            "overall_state": self.overall_state,
            "recommended_next_action": self.recommended_next_action,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class CampaignRunSnapshot:
    """Full derived snapshot of one campaign run (rows + summary + run scope)."""

    run: Optional[CampaignRun]
    rows: tuple[CampaignRunProspectRow, ...] = ()
    summary: CampaignRunSummary = field(default_factory=CampaignRunSummary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict() if self.run is not None else None,
            "rows": [row.to_dict() for row in self.rows],
            "summary": self.summary.to_dict(),
        }


class CampaignRunService:
    """Read-only end-to-end campaign run orchestrator.

    Composes the canonical prospect/research/opportunity/generation/outreach/
    review/package/Smartlead services to derive a presentation-only snapshot.
    It never re-implements stage logic — it reads results from existing stores.

    Only run scope/identity is persisted (via :class:`CampaignRunStore`). All
    stage state is derived on demand so it can never drift from the canonical
    source of truth.
    """

    def __init__(
        self,
        *,
        run_store: CampaignRunStore | None = None,
        prospect_store: Any = None,
        job_store: Any = None,
        project_store: Any = None,
        review_store: Any = None,
        research_store: ResearchQueueStore | None = None,
        generation_service: ProspectGenerationService | None = None,
        export_service: CampaignExportService | None = None,
        review_service: CampaignReviewService | None = None,
        opportunity_workspace_service: ProspectOpportunityWorkspaceService | None = None,
        handoff_service: SmartleadHandoffService | None = None,
    ) -> None:
        from gui.models.prospect_store import ProspectStore
        from gui.models.project_store import ProjectStore
        from gui.models.prospect_generation_store import ProspectGenerationStore
        from gui.models.campaign_review_store import CampaignReviewStore

        self._run_store = run_store or CampaignRunStore()
        self._prospect_store = prospect_store or ProspectStore()
        self._job_store = job_store or ProspectGenerationStore()
        self._project_store = project_store or ProjectStore()
        self._review_store = review_store or CampaignReviewStore()
        self._research_store = research_store
        # Read-only canonical services over the shared stores. When callers
        # supply pre-built shared services, reuse them; otherwise build a
        # consistent read-only set from the shared stores.
        self._export_service = export_service or CampaignExportService(
            prospect_store=self._prospect_store,
            job_store=self._job_store,
            project_store=self._project_store,
        )
        self._package_service = CampaignPackageService(export_service=self._export_service)
        self._review_service = review_service or CampaignReviewService(
            prospect_store=self._prospect_store,
            export_service=self._export_service,
            review_store=self._review_store,
            package_service=self._package_service,
        )
        self._generation_service = generation_service or ProspectGenerationService(
            prospect_store=self._prospect_store,
            job_store=self._job_store,
            project_store=self._project_store,
        )
        self._opportunity_workspace_service = (
            opportunity_workspace_service
            or ProspectOpportunityWorkspaceService(
                prospect_store=self._prospect_store,
                project_store=self._project_store,
            )
        )
        self._handoff_service = handoff_service or SmartleadHandoffService()

    # ------------------------------------------------------------------
    # Properties (expose shared canonical services for callers)
    # ------------------------------------------------------------------
    @property
    def run_store(self) -> CampaignRunStore:
        return self._run_store

    @property
    def prospect_store(self) -> Any:
        return self._prospect_store

    @property
    def export_service(self) -> CampaignExportService:
        return self._export_service

    @property
    def review_service(self) -> CampaignReviewService:
        return self._review_service

    @property
    def generation_service(self) -> ProspectGenerationService:
        return self._generation_service

    @property
    def opportunity_workspace_service(self) -> ProspectOpportunityWorkspaceService:
        return self._opportunity_workspace_service

    # ------------------------------------------------------------------
    # Run scope operations (persist ONLY identity/scope)
    # ------------------------------------------------------------------
    def list_runs(self) -> list[CampaignRun]:
        return self._run_store.list()

    def get_run(self, run_id: str) -> Optional[CampaignRun]:
        return self._run_store.get(run_id)

    def create_run(
        self,
        name: str,
        prospect_ids: Any,
        *,
        source: str = "",
        source_id: str = "",
    ) -> CampaignRun:
        """Create a run scoped to the given prospect IDs (read-only over prospects)."""
        return self._run_store.create(name, prospect_ids, source=source, source_id=source_id)

    def rename_run(self, run_id: str, name: str) -> CampaignRun:
        return self._run_store.rename(run_id, name)

    def add_prospects(self, run_id: str, prospect_ids: Any) -> CampaignRun:
        return self._run_store.add_prospects(run_id, prospect_ids)

    def remove_prospects(self, run_id: str, prospect_ids: Any) -> CampaignRun:
        """Remove prospect IDs from a run WITHOUT deleting canonical prospect data."""
        return self._run_store.remove_prospects(run_id, prospect_ids)

    def delete_run(self, run_id: str) -> bool:
        """Delete a run scope only. Canonical prospect/stage data is untouched."""
        return self._run_store.delete(run_id)

    # ------------------------------------------------------------------
    # Derived snapshots (read-only over canonical stores)
    # ------------------------------------------------------------------
    def snapshot(
        self,
        run_id: str | None,
        *,
        package_directory: str | None = None,
    ) -> CampaignRunSnapshot:
        """Build the full derived snapshot for a run (read-only).

        ``package_directory`` (optional) is a known built package directory; when
        it matches the run scope it is used to derive per-prospect package /
        Smartlead readiness by reading the package manifest (no writes).
        """
        run = self._run_store.get(run_id) if run_id else None
        prospect_ids = list(run.prospect_ids) if run is not None else []
        rows = self.snapshot_rows(prospect_ids, package_directory=package_directory)
        summary = self.summary(prospect_ids, rows=rows, package_directory=package_directory)
        return CampaignRunSnapshot(run=run, rows=tuple(rows), summary=summary)

    def snapshot_rows(
        self,
        prospect_ids: Any,
        *,
        package_directory: str | None = None,
    ) -> list[CampaignRunProspectRow]:
        """Derive one read-only row per prospect id (in the given order)."""
        self._ensure_canonical_loaded()
        ordered = self._ordered_ids(prospect_ids)
        package_ids = self._package_included_ids(package_directory, ordered)
        rows: list[CampaignRunProspectRow] = []
        for prospect_id in ordered:
            rows.append(self._derive_row(prospect_id, package_ids=package_ids))
        return rows

    def _ensure_canonical_loaded(self) -> None:
        """Load canonical backing stores when available, without clobbering injected memory.

        Campaign Run is read-only over existing stores. In the real app it may be
        opened before the prospects workspace has explicitly loaded from disk, so
        resolve against ``load_or_empty`` snapshots here.
        """
        try:
            if hasattr(self._prospect_store, "load_or_empty"):
                self._prospect_store.load_or_empty()
        except Exception:
            pass
        try:
            if self._research_store is not None and hasattr(self._research_store, "load_or_empty"):
                self._research_store.load_or_empty()
        except Exception:
            pass

    def summary(
        self,
        prospect_ids: Any,
        *,
        rows: list[CampaignRunProspectRow] | None = None,
        package_directory: str | None = None,
    ) -> CampaignRunSummary:
        """Derive run-level counts, overall state, and recommended next action."""
        derived = rows if rows is not None else self.snapshot_rows(
            prospect_ids, package_directory=package_directory
        )
        return self._derive_summary(derived)

    def continue_target(
        self,
        prospect_ids: Any,
        *,
        package_directory: str | None = None,
    ) -> str:
        """Derive the navigation target for "Continue Campaign" (read-only).

        Maps the run's recommended next action to a MainWindow page key. This is
        pure navigation: it never mutates any stage state.
        """
        summary = self.summary(prospect_ids, package_directory=package_directory)
        return self._action_to_target(summary.recommended_next_action)

    @staticmethod
    def _action_to_target(action: str) -> str:
        mapping = {
            ACTION_ADD_WEBSITE: NAV_PROSPECTS,
            ACTION_RESEARCH: NAV_PROSPECTS,
            ACTION_RESOLVE_OPPORTUNITY: NAV_PIPELINE,
            ACTION_GENERATE: NAV_BATCH,
            ACTION_GENERATE_OUTREACH: NAV_CAMPAIGN_REVIEW,
            ACTION_REVIEW: NAV_CAMPAIGN_REVIEW,
            ACTION_BUILD_PACKAGE: NAV_CAMPAIGN_REVIEW,
            ACTION_PREPARE_SMARTLEAD: NAV_SMARTLEAD,
            ACTION_READY: NAV_SMARTLEAD,
            ACTION_BLOCKED: NAV_CAMPAIGN_RUN,
        }
        return mapping.get(str(action or ""), NAV_CAMPAIGN_RUN)

    # ------------------------------------------------------------------
    # Internal derivation helpers (all read-only over canonical stores)
    # ------------------------------------------------------------------
    @staticmethod
    def _ordered_ids(prospect_ids: Any) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in prospect_ids or []:
            pid = _clean(raw)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            ordered.append(pid)
        return ordered

    def _package_included_ids(
        self,
        package_directory: str | None,
        expected_ids: list[str],
    ) -> set[str]:
        """Read-only: prospect ids included (READY/WARNING) in a package manifest.

        Only returns a non-empty set when the package manifest matches the
        expected run scope (so cross-run package leakage is impossible).
        """
        if not package_directory or not expected_ids:
            return set()
        try:
            if not package_matches_scope(package_directory, list(expected_ids)):
                return set()
        except Exception:
            return set()
        manifest_path = os.path.join(os.path.abspath(package_directory), "manifest.json")
        if not os.path.isfile(manifest_path):
            return set()
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return set()
        included: set[str] = set()
        for item in list(manifest.get("prospects") or []):
            if str(item.get("status") or "").upper() in {EXPORT_STATUS_READY, EXPORT_STATUS_WARNING}:
                pid = _clean(item.get("prospect_id"))
                if pid:
                    included.add(pid)
        return included

    @staticmethod
    def _select_succeeded_job(jobs: list[Any]) -> Any | None:
        succeeded = [
            j for j in jobs
            if _clean(getattr(j, "status", "")) == JOB_STATUS_SUCCEEDED
        ]
        if not succeeded:
            return None
        def _key(j: Any) -> tuple[str, str]:
            return (
                str(getattr(j, "completed_at", "") or getattr(j, "created_at", "") or ""),
                str(getattr(j, "id", "") or ""),
            )
        return sorted(succeeded, key=_key, reverse=True)[0]

    def _derive_research(
        self,
        prospect: Prospect | None,
        jobs: list[Any] | None = None,
        review_row: Any | None = None,
    ) -> tuple[str, bool]:
        if prospect is None:
            return STAGE_NOT_STARTED, False
        status = _clean(getattr(prospect, "research_status", ""))
        # Downstream canonical evidence implies research was effectively completed
        # even if the prospect's explicit research_status was never backfilled.
        succeeded_job = self._select_succeeded_job(list(jobs or []))
        if succeeded_job is not None or review_row is not None:
            return STAGE_COMPLETE, True
        # Canonical fallback: a succeeded research job in the durable store.
        if status != PROSPECT_SUCCEEDED and self._research_store is not None:
            try:
                collection = getattr(self._research_store, "collection", None)
                finder = getattr(collection, "succeeded_for_prospect", None)
                if finder is not None and finder(prospect.prospect_id) is not None:
                    return STAGE_COMPLETE, True
            except Exception:
                pass
        if status == PROSPECT_SUCCEEDED:
            return STAGE_COMPLETE, True
        if status in (PROSPECT_QUEUED, PROSPECT_RUNNING):
            return STAGE_IN_PROGRESS, False
        if status == PROSPECT_FAILED:
            return STAGE_FAILED, False
        if status == PROSPECT_READY:
            return STAGE_READY, False
        if prospect.is_ready_for_research():
            return STAGE_READY, False
        return STAGE_NOT_STARTED, False

    def _derive_opportunity(
        self,
        prospect: Prospect | None,
        research_complete: bool,
        succeeded_job: Any | None,
    ) -> tuple[str, bool]:
        opp_count = 0
        if prospect is not None:
            try:
                snapshot = self._opportunity_workspace_service.snapshot_for_prospect(
                    prospect.prospect_id
                )
                opp_count = int(getattr(snapshot, "opportunity_count", 0) or 0)
            except Exception:
                opp_count = 0
        job_has_opportunity = bool(
            succeeded_job is not None
            and _clean(getattr(succeeded_job, "opportunity_id", ""))
        )
        if opp_count > 0 or job_has_opportunity:
            return STAGE_COMPLETE, True
        if research_complete:
            return STAGE_READY, False
        return STAGE_NOT_STARTED, False

    def _derive_generation(
        self,
        prospect: Prospect | None,
        jobs: list[Any],
    ) -> tuple[str, bool, list[str]]:
        blockers: list[str] = []
        if not jobs:
            if prospect is None:
                return STAGE_NOT_STARTED, False, ["Prospect not found"]
            eligibility = self._generation_service.check_eligibility(prospect.prospect_id)
            reasons = [r for r in (getattr(eligibility, "reasons", []) or []) if _clean(r)]
            if reasons:
                blockers.extend(reasons)
                return STAGE_BLOCKED, False, blockers
            return STAGE_READY, False, blockers
        statuses = [_clean(getattr(j, "status", "")) for j in jobs]
        if JOB_STATUS_SUCCEEDED in statuses:
            return STAGE_COMPLETE, True, []
        if JOB_STATUS_RUNNING in statuses or JOB_STATUS_QUEUED in statuses:
            return STAGE_IN_PROGRESS, False, []
        if JOB_STATUS_FAILED in statuses:
            return STAGE_FAILED, False, ["No successful generation"]
        return STAGE_NOT_STARTED, False, []

    def _derive_outreach(
        self,
        prospect: Prospect | None,
    ) -> tuple[str, bool, list[str]]:
        blockers: list[str] = []
        if prospect is None:
            return STAGE_NOT_STARTED, False, ["Prospect not found"]
        eligibility = self._export_service.check_eligibility(prospect.prospect_id)
        status = _clean(getattr(eligibility, "status", ""))
        if status in (EXPORT_STATUS_READY, EXPORT_STATUS_WARNING):
            return STAGE_COMPLETE, True, []
        if status == EXPORT_STATUS_BLOCKED:
            reasons = [r for r in (getattr(eligibility, "reasons", []) or []) if _clean(r)]
            blockers.extend(reasons or ["Outreach not ready"])
            return STAGE_BLOCKED, False, blockers
        return STAGE_NOT_STARTED, False, blockers

    def _derive_review(
        self,
        prospect_id: str,
    ) -> tuple[str, bool, str, str, Any | None]:
        try:
            rows = self._review_service.list_rows([prospect_id])
        except Exception:
            rows = []
        if not rows:
            return STAGE_NOT_STARTED, False, "", "", None
        row = rows[0]
        review_value = _clean(getattr(row, "review_status", ""))
        technical = _clean(getattr(row, "technical_status", ""))
        if review_value == CAMPAIGN_REVIEW_STATUS_APPROVED:
            return STAGE_COMPLETE, True, review_value, technical, row
        if review_value == CAMPAIGN_REVIEW_STATUS_EXCLUDED:
            return STAGE_NOT_APPLICABLE, False, review_value, technical, row
        return STAGE_READY, False, review_value, technical, row

    @staticmethod
    def _derive_package(
        packageable: bool,
        prospect_id: str,
        package_ids: set[str],
    ) -> tuple[str, bool]:
        if not packageable:
            return STAGE_BLOCKED, False
        if package_ids and prospect_id in package_ids:
            return STAGE_COMPLETE, True
        return STAGE_READY, False

    @staticmethod
    def _derive_smartlead(
        review_ok: bool,
        packageable: bool,
        package_built: bool,
        technical_status: str,
    ) -> str:
        if not review_ok:
            return STAGE_BLOCKED
        if technical_status == EXPORT_STATUS_BLOCKED:
            return STAGE_BLOCKED
        if package_built:
            return STAGE_READY
        if packageable:
            return STAGE_NOT_STARTED
        return STAGE_BLOCKED

    @staticmethod
    def _derive_next_action(
        prospect: Prospect | None,
        research_complete: bool,
        opportunity_ok: bool,
        generation_ok: bool,
        outreach_ok: bool,
        review_ok: bool,
        package_built: bool,
        smartlead_status: str,
        blockers: list[str],
    ) -> str:
        if prospect is None:
            return ACTION_BLOCKED
        website = _clean(getattr(prospect, "website", "") or getattr(prospect, "domain", ""))
        if not website:
            blockers.append("Missing website")
            return ACTION_ADD_WEBSITE
        if not research_complete:
            return ACTION_RESEARCH
        if not generation_ok and not opportunity_ok:
            return ACTION_RESOLVE_OPPORTUNITY
        if not generation_ok:
            return ACTION_GENERATE
        if not outreach_ok:
            return ACTION_GENERATE_OUTREACH
        if not review_ok:
            return ACTION_REVIEW
        if not package_built:
            return ACTION_BUILD_PACKAGE
        if smartlead_status != STAGE_READY:
            return ACTION_PREPARE_SMARTLEAD
        return ACTION_READY

    def _derive_row(
        self,
        prospect_id: str,
        *,
        package_ids: set[str] | None = None,
    ) -> CampaignRunProspectRow:
        prospect = self._prospect_store.get(prospect_id)
        company = email = website = category = ""
        prospect_ready = False
        if prospect is not None:
            company = _clean(prospect.company_name)
            email = _clean(prospect.email)
            website = _clean(prospect.website or prospect.domain)
            category = _clean(prospect.category)
            prospect_ready = True

        jobs = self._generation_service.jobs_for_prospect(prospect_id)
        pre_review_status, review_ok, review_value, technical_status, review_row = self._derive_review(prospect_id)
        research_status, research_complete = self._derive_research(
            prospect, jobs=jobs, review_row=review_row
        )
        succeeded_job = self._select_succeeded_job(jobs)
        opportunity_status, opportunity_ok = self._derive_opportunity(
            prospect, research_complete, succeeded_job
        )
        generation_status, generation_ok, gen_blockers = self._derive_generation(prospect, jobs)
        outreach_status, outreach_ok, out_blockers = self._derive_outreach(prospect)
        review_status = pre_review_status

        packageable = bool(getattr(review_row, "packageable", False)) if review_row is not None else False
        pkg_ids = package_ids or set()
        package_status, package_built = self._derive_package(packageable, prospect_id, pkg_ids)
        smartlead_status = self._derive_smartlead(review_ok, packageable, package_built, technical_status)

        blockers: list[str] = []
        blockers.extend(gen_blockers)
        blockers.extend(out_blockers)
        next_action = self._derive_next_action(
            prospect, research_complete, opportunity_ok, generation_ok,
            outreach_ok, review_ok, package_built, smartlead_status, blockers,
        )
        # De-duplicate blockers while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for blocker in blockers:
            if blocker and blocker not in seen:
                seen.add(blocker)
                deduped.append(blocker)

        project_id = ""
        if review_row is not None:
            project_id = _clean(getattr(review_row, "project_id", ""))
        if not project_id and succeeded_job is not None:
            project_id = _clean(getattr(succeeded_job, "project_id", ""))
        generation_job_id = _clean(getattr(succeeded_job, "id", "")) if succeeded_job is not None else ""
        opportunity_id = _clean(getattr(succeeded_job, "opportunity_id", "")) if succeeded_job is not None else ""
        mockup_path = _clean(getattr(review_row, "mockup_path", "")) if review_row is not None else ""

        return CampaignRunProspectRow(
            prospect_id=prospect_id,
            company_name=company,
            email=email,
            website=website,
            category=category,
            prospect_ready=prospect_ready,
            research_status=research_status,
            opportunity_status=opportunity_status,
            generation_status=generation_status,
            outreach_status=outreach_status,
            review_status=review_status,
            package_status=package_status,
            smartlead_status=smartlead_status,
            next_action=next_action,
            blockers=tuple(deduped),
            project_id=project_id,
            generation_job_id=generation_job_id,
            opportunity_id=opportunity_id,
            review_status_value=review_value,
            technical_status=technical_status,
            mockup_path=mockup_path,
        )

    def _derive_summary(self, rows: list[CampaignRunProspectRow]) -> CampaignRunSummary:
        total = len(rows)
        if total == 0:
            return CampaignRunSummary(
                overall_state=RUN_STATE_EMPTY,
                recommended_next_action="Add or import prospects",
            )
        ready_for_research = sum(1 for r in rows if r.research_status == STAGE_READY)
        research_complete = sum(1 for r in rows if r.research_status == STAGE_COMPLETE)
        opportunity_ready = sum(1 for r in rows if r.opportunity_status == STAGE_COMPLETE)
        generated = sum(1 for r in rows if r.generation_status == STAGE_COMPLETE)
        outreach_ready = sum(1 for r in rows if r.outreach_status == STAGE_COMPLETE)
        approved = sum(1 for r in rows if r.review_status_value == CAMPAIGN_REVIEW_STATUS_APPROVED)
        packageable = sum(1 for r in rows if r.package_status in (STAGE_READY, STAGE_COMPLETE))
        package_built = sum(1 for r in rows if r.package_status == STAGE_COMPLETE)
        smartlead_ready = sum(1 for r in rows if r.smartlead_status == STAGE_READY)
        ready = sum(1 for r in rows if r.next_action == ACTION_READY)
        blocked = sum(
            1 for r in rows
            if r.next_action == ACTION_BLOCKED
            or r.research_status == STAGE_FAILED
            or r.generation_status == STAGE_FAILED
        )
        needs_attention = sum(
            1 for r in rows
            if r.next_action in (ACTION_BLOCKED, ACTION_ADD_WEBSITE)
            or r.research_status == STAGE_FAILED
            or r.generation_status == STAGE_FAILED
        )

        # Unique blockers needing human attention (most frequent first, capped).
        blocker_counts: dict[str, int] = {}
        for r in rows:
            for b in r.blockers:
                blocker_counts[b] = blocker_counts.get(b, 0) + 1
        run_blockers = tuple(
            sorted(blocker_counts, key=lambda k: (-blocker_counts[k], k))[:12]
        )

        # Overall state (priority order, mutually consistent).
        if ready == total:
            state = RUN_STATE_COMPLETE
        elif package_built == total:
            state = RUN_STATE_READY_FOR_SMARTLEAD
        elif approved == total:
            state = RUN_STATE_READY_FOR_PACKAGE
        elif outreach_ready == total:
            state = RUN_STATE_READY_FOR_REVIEW
        elif needs_attention > 0:
            state = RUN_STATE_NEEDS_ATTENTION
        else:
            state = RUN_STATE_IN_PROGRESS

        # Run-level recommended next action: highest-priority action that at
        # least one prospect still needs (workflow order), else "Ready".
        priority = [
            ACTION_ADD_WEBSITE,
            ACTION_RESEARCH,
            ACTION_RESOLVE_OPPORTUNITY,
            ACTION_GENERATE,
            ACTION_GENERATE_OUTREACH,
            ACTION_REVIEW,
            ACTION_BUILD_PACKAGE,
            ACTION_PREPARE_SMARTLEAD,
            ACTION_BLOCKED,
        ]
        action_counts: dict[str, int] = {}
        for r in rows:
            action_counts[r.next_action] = action_counts.get(r.next_action, 0) + 1
        if ready == total:
            recommended = ACTION_READY
        else:
            recommended = next(
                (a for a in priority if action_counts.get(a, 0) > 0),
                ACTION_BLOCKED,
            )

        return CampaignRunSummary(
            total_prospects=total,
            ready_for_research=ready_for_research,
            research_complete=research_complete,
            opportunity_ready=opportunity_ready,
            generated=generated,
            outreach_ready=outreach_ready,
            approved=approved,
            packageable=packageable,
            package_built=package_built,
            smartlead_ready=smartlead_ready,
            blocked=blocked,
            needs_attention=needs_attention,
            ready=ready,
            overall_state=state,
            recommended_next_action=recommended,
            blockers=run_blockers,
        )







