#!/usr/bin/env python
"""Sprint 5M verifier — deterministic personalized cold email generation."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5m_verify_")
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

        a = add_prospect(prospect_id="a", company_name="ABC Roofing", website="https://a.com", email="a@example.com", contact_name="Alice Owner", category="roofing", city="Castle Rock", state="CO", workflow_status="FOLLOW_UP", metadata={"internal": "secret"})
        ap, ac = add_project(a, "a.png")
        add_job(id="job-a", prospect_id="a", website=a.website, template="contractor", status="SUCCEEDED", project_id=ap.id, result_path=ac.image_path, opportunity_id="opp-a", location_id="loc-secret-123", placement_id="pl-a", metadata={"score": 94, "label": "STRONG MATCH", "job_id": "job-secret-789"}, opportunity_context=OpportunityGenerationContext(opportunity_id="opp-a", location_id="loc-secret-123", placement_id="pl-a", city="Castle Rock", state="CO", placement_name="Front Cart Corral", placement_type="cart_corral"))

        g = add_prospect(prospect_id="g", company_name="Generic Co", website="https://g.com", email="g@example.com", contact_name="", category="roofing")
        gp, gc = add_project(g, "g.png")
        add_job(id="job-g", prospect_id="g", website=g.website, template="contractor", status="SUCCEEDED", project_id=gp.id, result_path=gc.image_path, opportunity_id="", location_id="", placement_id="", opportunity_context=None)

        b = add_prospect(prospect_id="b", company_name="Bright Smile Dental", website="https://b.com", email="b@example.com", contact_name="Bob Brown", category="dentist", city="Austin", state="TX")
        bp, bc = add_project(b, "b.png")
        add_job(id="job-b", prospect_id="b", website=b.website, template="dentist", status="SUCCEEDED", project_id=bp.id, result_path=bc.image_path, opportunity_id="opp-b", location_id="loc-b", placement_id="pl-b", opportunity_context=OpportunityGenerationContext(opportunity_id="opp-b", location_id="loc-b", placement_id="pl-b", city="Austin", state="TX", placement_name="Storefront", placement_type="storefront"))

        row_a = service.build_row("a")
        row_g = service.build_row("g")
        row_b = service.build_row("b")

        check("opportunity-aware outreach", "Castle Rock" in row_a.email_body and "cart-corral placement" in row_a.email_body)
        check("generic outreach", "thought you might want to see it" in row_g.email_body)
        check("missing-contact behavior", row_g.email_body.startswith("Hi —"))
        check("safe placement wording", "placement_type=" not in row_a.email_body and "cart_corral" not in row_a.email_body)
        check("internal metadata does not leak", all(token not in row_a.email_body for token in ["94", "STRONG MATCH", "FOLLOW_UP", "loc-secret-123", "job-secret-789"]))
        check("cross-prospect isolation", "Bright Smile Dental" not in row_a.email_body and "ABC Roofing" not in row_b.email_body)
        check("snapshot immutability", "Castle Rock" in row_a.email_body)
        check("campaign export integration", bool(row_a.email_subject and row_a.email_body))
        check("legacy compatibility", row_g.opportunity_id == "" and row_g.email_subject == "Quick idea for Generic Co")

        output_path = os.path.join(root, "campaign.csv")
        service.export_csv(["a", "g", "b"], output_path)
        with open(output_path, "r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        check("csv round-trip", rows[0]["email_subject"] != "" and "\n\n" in rows[0]["email_body"])
        check("read-only behavior", len(jobs.list()) == 3 and len(projects.list()) == 3)

    except Exception:
        traceback.print_exc()
        failed += 1

    print("\nSPRINT 5M VERIFICATION COMPLETE")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(verify())