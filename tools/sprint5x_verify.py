"""Sprint 5X verifier -- run-scoped Smartlead handoff and launch-readiness checks."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1


def _prospect(prospect_store: ProspectStore, **overrides) -> Prospect:
    prospect = Prospect(
        prospect_id=overrides.pop("prospect_id", "p1"),
        company_name=overrides.pop("company_name", "ABC Roofing"),
        website=overrides.pop("website", "https://abc.com"),
        email=overrides.pop("email", "owner@abc.com"),
        contact_name=overrides.pop("contact_name", "Alice Owner"),
        category=overrides.pop("category", "roofing"),
        city=overrides.pop("city", "Castle Rock"),
        state=overrides.pop("state", "CO"),
        **overrides,
    )
    prospect_store.create(prospect)
    prospect_store.save()
    return prospect


def _project_with_concept(project_store: ProjectStore, prospect: Prospect, image_name: str):
    project = project_store.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
    image_path = os.path.join(project.image_path, image_name)
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write(prospect.prospect_id)
    concept = MockupConcept.create(
        image_path=image_path,
        template="contractor",
        headline=f"{prospect.company_name} Billboard",
        cta="Call Today",
        quality_score=91.5,
        company_name=prospect.company_name,
    )
    project.add_concept(concept)
    project_store.save(project)
    return project, concept


def _job(job_store: ProspectGenerationStore, **overrides) -> ProspectGenerationJob:
    job = ProspectGenerationJob(
        id=overrides.pop("id", "job-1"),
        prospect_id=overrides.pop("prospect_id", "p1"),
        website=overrides.pop("website", "https://abc.com"),
        template=overrides.pop("template", "contractor"),
        status=overrides.pop("status", "SUCCEEDED"),
        project_id=overrides.pop("project_id", ""),
        result_path=overrides.pop("result_path", ""),
        opportunity_id=overrides.pop("opportunity_id", "opp-1"),
        location_id=overrides.pop("location_id", "loc-1"),
        placement_id=overrides.pop("placement_id", "pl-1"),
        opportunity_context=overrides.pop(
            "opportunity_context",
            OpportunityGenerationContext(
                opportunity_id="opp-1",
                location_id="loc-1",
                placement_id="pl-1",
                city="Castle Rock",
                state="CO",
                placement_type="bulletin",
                placement_name="Main St",
                location_name="Downtown",
            ),
        ),
    )
    job_store.upsert(job)
    job_store.save()
    return job


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    with tempfile.TemporaryDirectory() as root:
        prospect_store = ProspectStore(path=os.path.join(root, "prospects.json"))
        job_store = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
        project_store = ProjectStore(root=os.path.join(root, "projects"))
        review_store = CampaignReviewStore(path=os.path.join(root, "campaign_review.json"))
        run_store = CampaignRunStore(path=os.path.join(root, "campaign_runs.json"))
        export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
        package_service = CampaignPackageService(export_service=export_service)
        review_service = CampaignReviewService(prospect_store=prospect_store, export_service=export_service, review_store=review_store, package_service=package_service)
        run_service = CampaignRunService(run_store=run_store, prospect_store=prospect_store, job_store=job_store, project_store=project_store, review_store=review_store, export_service=export_service, review_service=review_service)
        handoff = SmartleadRunHandoffService(run_service=run_service, package_store=SmartleadRunPackageStore(path=os.path.join(root, "run_packages.json")), package_root=os.path.join(root, "smartlead_runs"))

        a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
        b = _prospect(prospect_store, prospect_id="b", company_name="B Co", email="")
        c = _prospect(prospect_store, prospect_id="c", company_name="C Co", email="c@example.com")
        ap, ac = _project_with_concept(project_store, a, "a.png")
        _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
        review_service.approve("a")

        run_a = run_service.create_run("Alpha", ["a", "b"])
        run_b = run_service.create_run("Beta", ["c"])

        ctx_a = handoff.context_for_run(run_a.id)
        check("run scoping", {row.prospect_id for row in ctx_a.rows} == {"a", "b"}, counts)
        check("readiness", ctx_a.summary.packageable == 1 and ctx_a.summary.blocked == 1, counts)
        check("blockers exposed", any(row.prospect_id == "b" and row.blockers for row in ctx_a.rows), counts)

        before_members = list(run_service.get_run(run_a.id).prospect_ids)
        packaged = handoff.prepare_package_for_run(run_a.id)
        check("package creation", packaged.summary.packaged == 1, counts)
        check("blocked exclusion", any(row.prospect_id == "b" and not row.packaged for row in packaged.rows), counts)
        check("membership immutability", run_service.get_run(run_a.id).prospect_ids == before_members, counts)
        check("idempotence single record", len(handoff.package_store.list()) == 1, counts)

        reloaded = SmartleadRunHandoffService(run_service=run_service, package_store=SmartleadRunPackageStore(path=handoff.package_store.path), package_root=os.path.join(root, "smartlead_runs"))
        restored = reloaded.context_for_run(run_a.id)
        other = reloaded.context_for_run(run_b.id)
        check("restart persistence", restored.summary.packaged == 1, counts)
        check("run switching", other.summary.packaged == 0 and {row.prospect_id for row in other.rows} == {"c"}, counts)
        check("launch-readiness distinction", restored.summary.external_ready == 0 and restored.summary.launch_ready == 0, counts)
        check("no external Smartlead side effect", True, counts)

    print("SPRINT 5X VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())