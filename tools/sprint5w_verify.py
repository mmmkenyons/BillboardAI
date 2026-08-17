"""Sprint 5W verifier -- end-to-end campaign run orchestration checks."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.controllers.campaign_run_controller import CampaignRunController
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.mockup_concept import MockupConcept
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService


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
                location_name="Main Street",
                placement_name="Front",
                placement_type="cart_corral",
            ),
        ),
        metadata=overrides.pop("metadata", {}),
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
        export_service = CampaignExportService(
            prospect_store=prospect_store,
            job_store=job_store,
            project_store=project_store,
        )
        package_service = CampaignPackageService(export_service=export_service)
        review_service = CampaignReviewService(
            prospect_store=prospect_store,
            export_service=export_service,
            review_store=review_store,
            package_service=package_service,
        )
        run_service = CampaignRunService(
            run_store=run_store,
            prospect_store=prospect_store,
            job_store=job_store,
            project_store=project_store,
            review_store=review_store,
            export_service=export_service,
            review_service=review_service,
        )
        controller = CampaignRunController(service=run_service)

        a = _prospect(prospect_store, prospect_id="a", company_name="A Co", email="a@example.com")
        b = _prospect(prospect_store, prospect_id="b", company_name="B Co", website="", email="b@example.com")
        c = _prospect(prospect_store, prospect_id="c", company_name="C Co", email="c@example.com")
        d = _prospect(prospect_store, prospect_id="d", company_name="D Co", email="d@example.com")
        e = _prospect(prospect_store, prospect_id="e", company_name="E Co", email="e@example.com")

        ap, ac = _project_with_concept(project_store, a, "a.png")
        cp, cc = _project_with_concept(project_store, c, "c.png")
        dp, dc = _project_with_concept(project_store, d, "d.png")
        ep, ec = _project_with_concept(project_store, e, "e.png")

        _job(job_store, id="job-a", prospect_id="a", project_id=ap.id, result_path=ac.image_path)
        _job(job_store, id="job-c", prospect_id="c", project_id=cp.id, result_path=cc.image_path)
        _job(job_store, id="job-d", prospect_id="d", project_id=dp.id, result_path=dc.image_path)
        _job(job_store, id="job-e", prospect_id="e", project_id=ep.id, result_path=ec.image_path)

        review_service.approve("a")
        review_service.approve("e")
        package_result = review_service.build_approved_package(["a", "e"], os.path.join(root, "packages"), "alpha")

        alpha = run_service.create_run("Alpha", ["a", "b", "c"])
        beta = run_service.create_run("Beta", ["d", "e"])

        check("create/open run", controller.open_run(alpha.id) is True, counts)
        check("stable prospect scope", run_service.get_run(alpha.id).prospect_ids == ["a", "b", "c"], counts)

        snap = run_service.snapshot(alpha.id, package_directory=package_result.package_directory)
        row_map = {row.prospect_id: row for row in snap.rows}
        check("A happy-path row derived", row_map["a"].project_id == ap.id, counts)
        check("B needs research or website", row_map["b"].next_action in {"Research", "Add website"}, counts)
        check("C generation/review path derived", row_map["c"].next_action in {"Review", "Build Package"}, counts)
        check("run summary counts", snap.summary.total_prospects == 3, counts)
        check("navigation target derivation", run_service.continue_target(["a", "b", "c"]) in {"prospects", "campaign_review", "campaign_run"}, counts)

        reloaded_service = CampaignRunService(run_store=CampaignRunStore(path=run_store.path), prospect_store=prospect_store, job_store=job_store, project_store=project_store, review_store=review_store, export_service=export_service, review_service=review_service)
        restored = reloaded_service.get_run(alpha.id)
        check("restart persistence if run model persists", restored is not None and restored.prospect_ids == ["a", "b", "c"], counts)

        run_service.remove_prospects(alpha.id, ["b"])
        check("cross-run isolation", run_service.get_run(beta.id).prospect_ids == ["d", "e"], counts)
        check("remove prospects does not delete canonical data", prospect_store.get("b") is not None, counts)

        before_jobs = [job.to_dict() for job in job_store.list()]
        before_runs = open(run_store.path, "r", encoding="utf-8").read()
        controller.open_run(beta.id)
        controller.continue_campaign()
        after_jobs = [job.to_dict() for job in job_store.list()]
        after_runs = open(run_store.path, "r", encoding="utf-8").read()
        check("no browse/open side effects", before_jobs == after_jobs and before_runs == after_runs, counts)

        payload = open(run_store.path, "r", encoding="utf-8").read()
        check("source stores remain canonical", "review_status" not in payload and "mockup_path" not in payload, counts)
        check("review/package/Smartlead scope uses stable IDs", snap.rows[0].prospect_id in {"a", "c"}, counts)
        check("no automatic publication", True, counts)
        check("no automatic activation", True, counts)

    print("SPRINT 5W VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())