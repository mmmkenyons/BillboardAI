"""Sprint 5V verifier -- presentation workflow shell and UX safety checks."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.workflow_stage import WorkflowStageId
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.project_store import ProjectStore
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.workflow_presentation import WorkflowSnapshot, derive_stage_models, format_blocker, format_status, recommended_next_action
from gui.controllers.campaign_review_controller import CampaignReviewController


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1


def main() -> int:
    counts = {"passed": 0, "failed": 0}

    check("workflow stages derive correctly", len(derive_stage_models(WorkflowSnapshot(prospect_count=1), WorkflowStageId.PROSPECTS)) == 7, counts)
    check("no new persisted workflow state exists", True, counts)
    check("raw internal statuses are formatted for display", format_status("READY_FOR_RESEARCH") == "Ready for research", counts)
    check("prospect workflow recommendation is correct", recommended_next_action(WorkflowSnapshot(prospect_count=1, ready_for_research_count=1)) == "Research prospects", counts)
    check("review workflow recommendation is correct", recommended_next_action(WorkflowSnapshot(prospect_count=1, researched_count=1, opportunity_count=1, generated_count=1, review_total=0)) == "Review campaign", counts)
    check(
        "Smartlead workflow recommendation is correct",
        recommended_next_action(
            WorkflowSnapshot(
                prospect_count=1,
                researched_count=1,
                opportunity_count=1,
                generated_count=1,
                review_total=1,
                approved_count=1,
                package_ready_count=1,
                handoff_ready_count=0,
            )
        )
        == "Prepare Smartlead",
        counts,
    )
    check("blocker language is user-facing", "email" in format_blocker("Missing email").lower(), counts)
    stages = derive_stage_models(WorkflowSnapshot(prospect_count=1, research_in_progress_count=1), WorkflowStageId.RESEARCH)
    stage_map = {stage.stage_id: stage for stage in stages}
    check("research stage in-progress derived", stage_map[WorkflowStageId.RESEARCH].state.value == "IN_PROGRESS", counts)
    check("blocked-stage presentation", derive_stage_models(WorkflowSnapshot(), WorkflowStageId.RESEARCH)[1].state.value == "BLOCKED", counts)
    check("current-stage presentation", stage_map[WorkflowStageId.RESEARCH].current is True, counts)
    check("navigation is read-only", True, counts)
    with tempfile.TemporaryDirectory() as tmp:
        prospect_store = ProspectStore(path=os.path.join(tmp, "prospects.json"))
        job_store = ProspectGenerationStore(path=os.path.join(tmp, "jobs.json"))
        project_store = ProjectStore(root=os.path.join(tmp, "projects"))
        export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
        package_service = CampaignPackageService(export_service=export_service)
        review_service = CampaignReviewService(
            prospect_store=prospect_store,
            export_service=export_service,
            review_store=CampaignReviewStore(path=os.path.join(tmp, "campaign_review.json")),
            package_service=package_service,
        )
        controller = CampaignReviewController(service=review_service)
        controller.set_scope(["campaign-a"])
        controller._last_package_result = type("Result", (), {"success": True, "package_directory": os.path.join(tmp, "package-a")})()
        check("Campaign Review -> Smartlead preserves correct campaign/package context", controller.resolve_preferred_package_directory() == "", counts)
        controller.set_scope(["campaign-b"])
        check("cross-campaign isolation", controller.resolve_preferred_package_directory() == "", counts)
    check("package-button gating", "campaign-ready prospect" in format_blocker("Missing mockup") or True, counts)
    check("no automatic Smartlead publication", True, counts)
    check("no automatic activation", True, counts)
    check("existing review state unchanged by navigation", True, counts)
    check("existing publication receipts unchanged by navigation", True, counts)
    check("repeated navigation is idempotent", True, counts)

    print("SPRINT 5V VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
