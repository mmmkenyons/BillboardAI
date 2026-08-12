#!/usr/bin/env python
"""Sprint 5L verifier — campaign export / Smartlead-ready outreach package."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5l_verify_")
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
        from gui.models.prospect_generation import (
            JOB_STATUS_FAILED,
            JOB_STATUS_QUEUED,
            JOB_STATUS_SUCCEEDED,
            OpportunityGenerationContext,
            ProspectGenerationJob,
        )
        from gui.models.prospect_generation_store import ProspectGenerationStore
        from gui.models.prospect_store import ProspectStore
        from gui.services.campaign_export import CampaignExportService, EXPORT_STATUS_BLOCKED, EXPORT_STATUS_READY, EXPORT_STATUS_WARNING

        prospects = ProspectStore(path=os.path.join(root, "prospects.json"))
        jobs = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
        projects = ProjectStore(root=os.path.join(root, "projects"))
        service = CampaignExportService(prospect_store=prospects, job_store=jobs, project_store=projects)

        def add_prospect(**kwargs):
            prospect = Prospect(**kwargs)
            prospects.create(prospect)
            prospects.save()
            return prospect

        def add_project(prospect: Prospect, image_name: str):
            project = projects.create(company_name=prospect.company_name, website=prospect.website, name=prospect.prospect_id)
            image_path = os.path.join(project.image_path, image_name)
            with open(image_path, "w", encoding="utf-8") as handle:
                handle.write("synthetic")
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

        prospect_a = add_prospect(
            prospect_id="a",
            company_name="ABC Roofing",
            website="https://abc.com",
            email="owner@abc.com",
            contact_name="Alice Owner",
            category="roofing",
            city="Castle Rock",
            state="CO",
        )
        project_a, concept_a = add_project(prospect_a, "a.png")
        add_job(
            id="job-a-success",
            prospect_id="a",
            website=prospect_a.website,
            template="contractor",
            status=JOB_STATUS_SUCCEEDED,
            project_id=project_a.id,
            result_path=concept_a.image_path,
            opportunity_id="opp-a",
            location_id="loc-a",
            placement_id="pl-a",
            opportunity_context=OpportunityGenerationContext(
                opportunity_id="opp-a",
                location_id="loc-a",
                placement_id="pl-a",
                location_name="King Soopers #123",
                city="Castle Rock",
                state="CO",
                placement_name="Front Cart Corral A",
                placement_type="cart_corral",
            ),
        )
        check("ready export", service.check_eligibility("a").status == EXPORT_STATUS_READY)

        prospect_b = add_prospect(
            prospect_id="b",
            company_name="No Email Co",
            website="https://b.com",
            email="",
            category="roofing",
        )
        check("blocked missing email", service.check_eligibility("b").status == EXPORT_STATUS_BLOCKED)

        prospect_c = add_prospect(
            prospect_id="c",
            company_name="No Gen Co",
            website="https://c.com",
            email="owner@c.com",
            category="roofing",
        )
        check("blocked no generation", service.check_eligibility("c").status == EXPORT_STATUS_BLOCKED)

        prospect_d = add_prospect(
            prospect_id="d",
            company_name="Generic Co",
            website="https://d.com",
            email="owner@d.com",
            category="dentist",
            city="",
            state="CO",
        )
        project_d, concept_d = add_project(prospect_d, "d.png")
        add_job(
            id="job-d-success",
            prospect_id="d",
            website=prospect_d.website,
            template="dentist",
            status=JOB_STATUS_SUCCEEDED,
            project_id=project_d.id,
            result_path=concept_d.image_path,
            opportunity_id="",
            location_id="",
            placement_id="",
            opportunity_context=None,
        )
        check("generic export warning", service.check_eligibility("d").status == EXPORT_STATUS_WARNING)

        prospect_e = add_prospect(
            prospect_id="e",
            company_name="History Co",
            website="https://e.com",
            email="owner@e.com",
            category="roofing",
            city="Parker",
            state="CO",
        )
        project_e1, concept_e1 = add_project(prospect_e, "e1.png")
        project_e2, concept_e2 = add_project(prospect_e, "e2.png")
        add_job(
            id="job-e-1",
            prospect_id="e",
            website=prospect_e.website,
            template="contractor",
            status=JOB_STATUS_SUCCEEDED,
            project_id=project_e1.id,
            result_path=concept_e1.image_path,
        )
        add_job(
            id="job-e-2",
            prospect_id="e",
            website=prospect_e.website,
            template="contractor",
            status=JOB_STATUS_SUCCEEDED,
            project_id=project_e2.id,
            result_path=concept_e2.image_path,
        )
        add_job(
            id="job-e-3",
            prospect_id="e",
            website=prospect_e.website,
            template="contractor",
            status=JOB_STATUS_FAILED,
            project_id="",
            result_path="",
        )
        check("newest usable success selected", service.build_row("e").generation_job_id == "job-e-2")

        prospect_f = add_prospect(
            prospect_id="f",
            company_name="Queued Co",
            website="https://f.com",
            email="owner@f.com",
            category="roofing",
        )
        project_f, concept_f = add_project(prospect_f, "f.png")
        add_job(
            id="job-f-1",
            prospect_id="f",
            website=prospect_f.website,
            template="contractor",
            status=JOB_STATUS_SUCCEEDED,
            project_id=project_f.id,
            result_path=concept_f.image_path,
        )
        add_job(
            id="job-f-2",
            prospect_id="f",
            website=prospect_f.website,
            template="contractor",
            status=JOB_STATUS_QUEUED,
        )
        check("newer queued does not erase prior success", service.build_row("f").generation_job_id == "job-f-1")

        before_jobs = len(jobs.list())
        before_projects = len(projects.list())
        preview = service.preview_rows(["a", "d"])
        check("read-only preview", len(jobs.list()) == before_jobs and len(projects.list()) == before_projects and len(preview) == 2)

        output_path = os.path.join(root, "campaign.csv")
        service.export_csv(["a", "d", "a"], output_path)
        with open(output_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        check("deterministic csv output", len(rows) == 2 and rows[0]["prospect_id"] == "a" and rows[1]["prospect_id"] == "d")
        check("opportunity traceability", rows[0]["opportunity_id"] == "opp-a" and rows[0]["placement_id"] == "pl-a")
        check("generic blank opportunity fields", rows[1]["opportunity_id"] == "" and rows[1]["location_id"] == "" and rows[1]["placement_id"] == "")
        check("csv round-trip", rows[0]["email"] == "owner@abc.com" and rows[1]["email"] == "owner@d.com")

        print("\nSANITIZED CSV HEADER:")
        with open(output_path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        print(lines[0])
        if len(lines) > 1:
            print("SANITIZED OPPORTUNITY ROW:")
            print(lines[1])
        if len(lines) > 2:
            print("SANITIZED GENERIC ROW:")
            print(lines[2])

    except Exception:
        traceback.print_exc()
        failed += 1

    print("\nSPRINT 5L VERIFICATION COMPLETE")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(verify())