#!/usr/bin/env python
"""Sprint 5N verifier — campaign package builder / Smartlead-ready export."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5n_verify_")
    passed = 0
    failed = 0

    def check(name: str, condition: bool, message: str = "") -> None:
        nonlocal passed, failed
        if condition:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name}: {message}")
            failed += 1

    try:
        from gui.models.mockup_concept import MockupConcept
        from gui.models.project_store import ProjectStore
        from gui.models.prospect import Prospect
        from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
        from gui.models.prospect_generation_store import ProspectGenerationStore
        from gui.models.prospect_store import ProspectStore
        from gui.services.campaign_export import CampaignExportService
        from gui.services.campaign_package import CampaignPackageService

        prospects = ProspectStore(path=os.path.join(root, "prospects.json"))
        jobs = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
        projects = ProjectStore(root=os.path.join(root, "projects"))
        export_service = CampaignExportService(prospect_store=prospects, job_store=jobs, project_store=projects)
        package_service = CampaignPackageService(export_service=export_service)

        def add_prospect(**kwargs):
            prospect = Prospect(**kwargs)
            prospects.create(prospect)
            prospects.save()
            return prospect

        def add_project(prospect: Prospect, image_name: str, payload: str):
            project = projects.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
            image_path = os.path.join(project.image_path, image_name)
            with open(image_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
            concept = MockupConcept.create(
                image_path=image_path,
                template="contractor",
                headline=f"{prospect.company_name} Billboard",
                cta="Call Today",
                quality_score=88,
                company_name=prospect.company_name,
            )
            project.add_concept(concept)
            projects.save(project)
            return project, concept

        def add_job(**kwargs):
            job = ProspectGenerationJob(**kwargs)
            jobs.upsert(job)
            jobs.save()
            return job

        a = add_prospect(prospect_id="a", company_name="ABC Roofing", website="https://a.com", email="a@example.com", contact_name="Alice Owner", category="roofing", city="Castle Rock", state="CO")
        ap, ac = add_project(a, "a.png", "alpha")
        add_job(id="job-a", prospect_id="a", website=a.website, template="contractor", status="SUCCEEDED", project_id=ap.id, result_path=ac.image_path, opportunity_id="opp-a", location_id="loc-a", placement_id="pl-a", opportunity_context=OpportunityGenerationContext(opportunity_id="opp-a", location_id="loc-a", placement_id="pl-a", city="Castle Rock", state="CO", placement_name="Front Cart Corral", placement_type="cart_corral"))

        b = add_prospect(prospect_id="b", company_name="Generic Co", website="https://b.com", email="b@example.com", contact_name="", category="roofing", city="", state="CO")
        bp, bc = add_project(b, "b.png", "beta")
        add_job(id="job-b", prospect_id="b", website=b.website, template="contractor", status="SUCCEEDED", project_id=bp.id, result_path=bc.image_path, opportunity_id="", location_id="", placement_id="", opportunity_context=None)

        c = add_prospect(prospect_id="c", company_name="Missing Mockup", website="https://c.com", email="c@example.com", contact_name="Chris C", category="roofing", city="Denver", state="CO")
        cp, cc = add_project(c, "c.png", "gamma")
        add_job(id="job-c", prospect_id="c", website=c.website, template="contractor", status="SUCCEEDED", project_id=cp.id, result_path=cc.image_path, opportunity_id="opp-c", location_id="loc-c", placement_id="pl-c", opportunity_context=OpportunityGenerationContext(opportunity_id="opp-c", location_id="loc-c", placement_id="pl-c", city="Denver", state="CO", placement_name="Front", placement_type="storefront"))
        os.remove(cc.image_path)

        d = add_prospect(prospect_id="d", company_name="No Email Co", website="https://d.com", email="", contact_name="Dana D", category="dentist", city="Austin", state="TX")

        before_jobs = [job.to_dict() for job in jobs.list()]
        before_projects = [project.id for project in projects.list()]
        package_root = os.path.join(root, "packages")
        result = package_service.build_package(["a", "b", "c", "d"], package_root, campaign_name="Sprint5N Demo")

        check("package succeeds partially", result.success and result.included_count == 2 and result.blocked_count == 2)
        check("package directory exists", os.path.isdir(result.package_directory))
        check("campaign.csv exists", os.path.isfile(result.campaign_csv_path))
        check("manifest.json exists", os.path.isfile(result.manifest_path))
        check("validation.csv exists", os.path.isfile(result.validation_csv_path))
        check("mockups directory exists", os.path.isdir(os.path.join(result.package_directory, "mockups")))

        with open(result.campaign_csv_path, "r", encoding="utf-8", newline="") as handle:
            campaign_rows = list(csv.DictReader(handle))
        with open(result.validation_csv_path, "r", encoding="utf-8", newline="") as handle:
            validation_rows = list(csv.DictReader(handle))
        with open(result.manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)

        check("campaign contains A and B only", [row["prospect_id"] for row in campaign_rows] == ["a", "b"])
        check("exactly two mockups copied", len(os.listdir(os.path.join(result.package_directory, "mockups"))) == 2)
        validation_map = {row["prospect_id"]: row for row in validation_rows}
        check("C and D in validation", "c" in validation_map and "d" in validation_map)
        check("C blocked for missing source", validation_map["c"]["status"] == "BLOCKED" and validation_map["c"]["reason"] == "Source mockup file no longer exists.")
        check("D blocked for missing email", validation_map["d"]["status"] == "BLOCKED" and validation_map["d"]["reason"] == "Missing email.")
        check("manifest counts correct", manifest["total_selected"] == 4 and manifest["total_exportable"] == 2 and manifest["total_blocked"] == 2)
        check("A preserves opportunity snapshot", campaign_rows[0]["opportunity_id"] == "opp-a" and campaign_rows[0]["placement_id"] == "pl-a")
        check("B has no invented opportunity metadata", campaign_rows[1]["opportunity_id"] == "" and campaign_rows[1]["location_id"] == "" and campaign_rows[1]["placement_id"] == "")
        check("packaged paths are relative", all(not os.path.isabs(row["mockup_relative_path"]) and row["mockup_relative_path"].startswith("mockups/") for row in campaign_rows))
        check("outreach contains no internal metadata", all(token not in campaign_rows[0]["email_body"] for token in ["loc-a", "job-a", "FOLLOW_UP", "STRONG MATCH"]))
        check("original mockups unchanged", os.path.isfile(ac.image_path) and os.path.isfile(bc.image_path))
        check("canonical stores unchanged", [job.to_dict() for job in jobs.list()] == before_jobs and [project.id for project in projects.list()] == before_projects)

    except Exception:
        traceback.print_exc()
        failed += 1

    print("\nSPRINT 5N VERIFICATION COMPLETE")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(verify())