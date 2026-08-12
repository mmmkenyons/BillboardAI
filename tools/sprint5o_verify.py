from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main() -> None:
    from gui.models.campaign_review_store import CampaignReviewStore
    from gui.models.mockup_concept import MockupConcept
    from gui.models.project_store import ProjectStore
    from gui.models.prospect import Prospect
    from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
    from gui.models.prospect_generation_store import ProspectGenerationStore
    from gui.models.prospect_store import ProspectStore
    from gui.services.campaign_export import EXPORT_STATUS_BLOCKED, EXPORT_STATUS_READY, EXPORT_STATUS_WARNING, CampaignExportService
    from gui.services.campaign_package import CampaignPackageService
    from gui.services.campaign_review import CampaignReviewService

    with tempfile.TemporaryDirectory() as root:
        prospects = ProspectStore(path=os.path.join(root, "prospects.json"))
        jobs = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
        projects = ProjectStore(root=os.path.join(root, "projects"))
        export_service = CampaignExportService(prospect_store=prospects, job_store=jobs, project_store=projects)
        package_service = CampaignPackageService(export_service=export_service)
        review_store = CampaignReviewStore(path=os.path.join(root, "campaign_review.json"))
        review_service = CampaignReviewService(
            prospect_store=prospects,
            export_service=export_service,
            review_store=review_store,
            package_service=package_service,
        )

        def add_prospect(pid: str, company: str, *, email: str = "owner@example.com", contact_name: str = "Owner", city: str = "Castle Rock"):
            prospect = Prospect(
                prospect_id=pid,
                company_name=company,
                website=f"https://{pid}.example.com",
                email=email,
                contact_name=contact_name,
                category="roofing",
                city=city,
                state="CO",
            )
            prospects.create(prospect)
            return prospect

        def seed_generation(prospect: Prospect, image_name: str, *, placement_type: str = "cart_corral"):
            project = projects.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
            image_path = os.path.join(project.image_path, image_name)
            with open(image_path, "w", encoding="utf-8") as handle:
                handle.write(prospect.prospect_id)
            concept = MockupConcept.create(
                image_path=image_path,
                template="contractor",
                headline=f"{prospect.company_name} Billboard",
                cta="Call Today",
                quality_score=90,
                company_name=prospect.company_name,
            )
            project.add_concept(concept)
            projects.save(project)
            jobs.upsert(
                ProspectGenerationJob(
                    id=f"job-{prospect.prospect_id}",
                    prospect_id=prospect.prospect_id,
                    website=prospect.website,
                    template="contractor",
                    status="SUCCEEDED",
                    project_id=project.id,
                    result_path=concept.image_path,
                    opportunity_id=f"opp-{prospect.prospect_id}",
                    location_id=f"loc-{prospect.prospect_id}",
                    placement_id=f"pl-{prospect.prospect_id}",
                    opportunity_context=OpportunityGenerationContext(
                        opportunity_id=f"opp-{prospect.prospect_id}",
                        location_id=f"loc-{prospect.prospect_id}",
                        placement_id=f"pl-{prospect.prospect_id}",
                        city=prospect.city,
                        state=prospect.state,
                        location_name=f"Location {prospect.prospect_id}",
                        placement_name=f"Placement {prospect.prospect_id}",
                        placement_type=placement_type,
                    ),
                )
            )
            return image_path

        a = add_prospect("a", "A Co")
        b = add_prospect("b", "B Co", contact_name="")
        c = add_prospect("c", "C Co")
        d = add_prospect("d", "D Co")
        e = add_prospect("e", "E Co")
        prospects.save()
        image_a = seed_generation(a, "a.png")
        image_b = seed_generation(b, "b.png", placement_type="storefront")
        seed_generation(c, "c.png")
        image_d = seed_generation(d, "d.png")
        seed_generation(e, "e.png")
        jobs.save()

        review_service.approve("a")
        review_service.approve("b")
        review_service.exclude("c")
        review_service.approve("d")
        review_service.mark_needs_review("e")

        os.remove(image_d)
        rows = {row.prospect_id: row for row in review_service.list_rows(["a", "b", "c", "d", "e"])}
        summary = review_service.summary(["a", "b", "c", "d", "e"])

        check("review summary totals", summary.total == 5 and summary.approved == 3 and summary.excluded == 1 and summary.needs_review == 1)
        check("A ready approved", rows["a"].technical_status == EXPORT_STATUS_READY and rows["a"].packageable)
        check("B warning approved", rows["b"].technical_status == EXPORT_STATUS_WARNING and rows["b"].packageable)
        check("C excluded", rows["c"].review_status == "EXCLUDED" and not rows["c"].packageable)
        check("D blocked despite approval", rows["d"].review_status == "APPROVED" and rows["d"].technical_status == EXPORT_STATUS_BLOCKED and not rows["d"].packageable)
        check("E needs review not packageable", rows["e"].review_status == "NEEDS_REVIEW" and not rows["e"].packageable)

        before_jobs = [job.to_dict() for job in jobs.list()]
        before_projects = [project.id for project in projects.list()]
        result = review_service.build_approved_package(["a", "b", "c", "d", "e"], os.path.join(root, "packages"), "Sprint5O")
        check("Build Approved Package includes A+B only", result.success and result.included_count == 2)
        check("no review action mutates jobs/projects", [job.to_dict() for job in jobs.list()] == before_jobs and [project.id for project in projects.list()] == before_projects)

        reloaded = CampaignReviewService(
            prospect_store=prospects,
            export_service=export_service,
            review_store=CampaignReviewStore(path=os.path.join(root, "campaign_review.json")),
            package_service=package_service,
        )
        reloaded_rows = {row.prospect_id: row for row in reloaded.list_rows(["a", "b", "c", "d", "e"])}
        check("restart preserves review decisions", reloaded_rows["a"].review_status == "APPROVED" and reloaded_rows["c"].review_status == "EXCLUDED" and reloaded_rows["e"].review_status == "NEEDS_REVIEW")
        check("cross-prospect isolation", "B Co" not in reloaded_rows["a"].email_body and "A Co" not in reloaded_rows["b"].email_body)


if __name__ == "__main__":
    main()