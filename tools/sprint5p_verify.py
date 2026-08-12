#!/usr/bin/env python
"""Sprint 5P verifier — Smartlead handoff / publishing readiness."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify() -> int:
    root = tempfile.mkdtemp(prefix="sprint5p_verify_")
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
        from gui.models.campaign_review_store import CampaignReviewStore
        from gui.models.mockup_concept import MockupConcept
        from gui.models.project_store import ProjectStore
        from gui.models.prospect import Prospect
        from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
        from gui.models.prospect_generation_store import ProspectGenerationStore
        from gui.models.prospect_store import ProspectStore
        from gui.services.campaign_export import CampaignExportService
        from gui.services.campaign_package import CampaignPackageService
        from gui.services.campaign_review import CampaignReviewService
        from gui.services.smartlead_handoff import SmartleadHandoffService

        prospects = ProspectStore(path=os.path.join(root, "prospects.json"))
        jobs = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
        projects = ProjectStore(root=os.path.join(root, "projects"))
        export_service = CampaignExportService(prospect_store=prospects, job_store=jobs, project_store=projects)
        package_service = CampaignPackageService(export_service=export_service)
        review_service = CampaignReviewService(
            prospect_store=prospects,
            export_service=export_service,
            review_store=CampaignReviewStore(path=os.path.join(root, "campaign_review.json")),
            package_service=package_service,
        )
        handoff_service = SmartleadHandoffService()

        def add_prospect(pid: str, company: str, email: str, contact_name: str = "Owner", city: str = "Castle Rock"):
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

        def seed_generation(prospect: Prospect, image_name: str, placement_type: str = "cart_corral"):
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
                        placement_name=f"Placement {prospect.prospect_id}",
                        placement_type=placement_type,
                    ),
                )
            )
            return image_path

        a = add_prospect("a", "A Co", "a@example.com")
        b = add_prospect("b", "B Co", "b@example.com", contact_name="")
        c = add_prospect("c", "C Co", "abc")
        d = add_prospect("d", "D Co", "shared@example.com")
        e = add_prospect("e", "E Co", "shared@example.com")
        f = add_prospect("f", "F Co", "f@example.com")
        g = add_prospect("g", "G Co", "g@example.com")
        prospects.save()
        for prospect, image in [(a, "a.png"), (b, "b.png"), (c, "c.png"), (d, "d.png"), (e, "e.png"), (f, "f.png"), (g, "g.png")]:
            seed_generation(prospect, image, placement_type="storefront" if prospect.prospect_id == "b" else "cart_corral")
        jobs.save()

        review_service.approve("a")
        review_service.approve("b")
        review_service.approve("c")
        review_service.approve("d")
        review_service.approve("e")
        review_service.exclude("f")
        review_service.mark_needs_review("g")

        package_result = review_service.build_approved_package(["a", "b", "c", "d", "e", "f", "g"], os.path.join(root, "packages"), "Sprint5P")
        before_campaign = open(package_result.campaign_csv_path, "rb").read()
        before_manifest = open(package_result.manifest_path, "rb").read()
        result = handoff_service.prepare_handoff(package_result.package_directory)

        check("mapping file exists", os.path.isfile(result.mapping_path))
        check("preflight file exists", os.path.isfile(result.preflight_path))
        check("handoff manifest exists", os.path.isfile(result.manifest_path))
        check("smartlead csv exists", os.path.isfile(result.smartlead_csv_path))

        with open(result.smartlead_csv_path, "r", encoding="utf-8", newline="") as handle:
            smartlead_rows = list(csv.DictReader(handle))
        with open(result.preflight_path, "r", encoding="utf-8", newline="") as handle:
            preflight_rows = list(csv.DictReader(handle))
        with open(result.manifest_path, "r", encoding="utf-8") as handle:
            handoff_manifest = json.load(handle)

        check("A/B final handoff rows only", [row["prospect_id"] for row in smartlead_rows] == ["a", "b"])
        check("preflight contains A-E only", [row["prospect_id"] for row in preflight_rows] == ["a", "b", "c", "d", "e"])
        status_map = {row["prospect_id"]: row["status"] for row in preflight_rows}
        check("C blocked", status_map.get("c") == "BLOCKED")
        check("D/E conflict", status_map.get("d") == "CONFLICT" and status_map.get("e") == "CONFLICT")
        check("F/G omitted", "f" not in status_map and "g" not in status_map)
        check("portable asset references", all(row["mockup_path"].startswith("mockups/") and not os.path.isabs(row["mockup_path"]) for row in smartlead_rows))
        check(
            "subject/body safe",
            all(
                token not in row["email_body"]
                for row in smartlead_rows
                for token in [row.get("project_id", ""), row.get("generation_job_id", ""), "STRONG MATCH", "FOLLOW_UP"]
                if token
            ),
        )
        check("no source mutation campaign", open(package_result.campaign_csv_path, "rb").read() == before_campaign)
        check("no source mutation manifest", open(package_result.manifest_path, "rb").read() == before_manifest)
        check("deterministic mapping", handoff_manifest["profile"]["field_mapping"][0]["destination_field"] == "email")

    except Exception:
        traceback.print_exc()
        failed += 1

    print("\nSPRINT 5P VERIFICATION COMPLETE")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(verify())
