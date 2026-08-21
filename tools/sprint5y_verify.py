"""Sprint 5Y verifier -- run-scoped Smartlead portable export.

Deterministic, headless (no Qt). Exercises the Sprint 5Y export boundary over
temporary stores/paths and prints PASS/FAIL lines with totals.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.hosted_asset import HostedMockupAsset
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.mockup_concept import MockupConcept
from gui.models.personalization_field_catalog import PersonalizationFieldMappingStore
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_handoff import DEFAULT_SMARTLEAD_COLUMN_ORDER
from gui.models.smartlead_run_export import (
    SMARTLEAD_EXPORT_BLOCKED,
    SMARTLEAD_EXPORT_CONFLICT,
    SMARTLEAD_EXPORT_EXCLUDED,
    SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN,
    SMARTLEAD_EXPORT_READY,
)
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_run_export import SmartleadRunExportService, build_export_columns
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1


def _build(root: str):
    components = {
        "root": root,
        "prospect_store": ProspectStore(path=os.path.join(root, "prospects.json")),
        "job_store": ProspectGenerationStore(path=os.path.join(root, "jobs.json")),
        "project_store": ProjectStore(root=os.path.join(root, "projects")),
        "review_store": CampaignReviewStore(path=os.path.join(root, "campaign_review.json")),
        "run_store": CampaignRunStore(path=os.path.join(root, "campaign_runs.json")),
        "hosted_store": HostedAssetStore(path=os.path.join(root, "hosted_assets.json")),
    }
    components["export_service"] = CampaignExportService(
        prospect_store=components["prospect_store"],
        job_store=components["job_store"],
        project_store=components["project_store"],
    )
    components["package_service"] = CampaignPackageService(export_service=components["export_service"])
    components["review_service"] = CampaignReviewService(
        prospect_store=components["prospect_store"],
        export_service=components["export_service"],
        review_store=components["review_store"],
        package_service=components["package_service"],
    )
    components["run_service"] = CampaignRunService(
        run_store=components["run_store"],
        prospect_store=components["prospect_store"],
        job_store=components["job_store"],
        project_store=components["project_store"],
        review_store=components["review_store"],
        export_service=components["export_service"],
        review_service=components["review_service"],
    )
    components["package_store"] = SmartleadRunPackageStore(path=os.path.join(root, "run_packages.json"))
    components["run_handoff"] = SmartleadRunHandoffService(
        run_service=components["run_service"],
        package_store=components["package_store"],
        package_root=os.path.join(root, "smartlead_runs"),
    )
    components["export_svc"] = SmartleadRunExportService(
        run_handoff_service=components["run_handoff"],
        hosted_asset_store=components["hosted_store"],
        mapping_store=PersonalizationFieldMappingStore(path=os.path.join(root, "personalization_field_mapping.json")),
        export_root=os.path.join(root, "smartlead_exports"),
    )
    return components


def _prospect(prospect_store, **overrides):
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


def _project_with_concept(project_store, prospect, image_name):
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
def _job(job_store, **overrides):
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
                placement_name="I-25",
                placement_type="Billboard",
            ),
        ),
        **overrides,
    )
    job_store.upsert(job)
    job_store.save()
    return job


def _ready(components, prospect_id, company, email, image_name="mock.png"):
    prospect = _prospect(
        components["prospect_store"],
        prospect_id=prospect_id,
        company_name=company,
        email=email,
    )
    project, concept = _project_with_concept(components["project_store"], prospect, image_name)
    _job(
        components["job_store"],
        id=f"job-{prospect_id}",
        prospect_id=prospect_id,
        project_id=project.id,
        result_path=concept.image_path,
    )
    components["review_service"].approve(prospect_id)
    return prospect, project, concept


def _hosted(components, prospect_id, project, job_id, url):
    asset = HostedMockupAsset(
        prospect_id=prospect_id,
        generation_job_id=job_id,
        project_id=project.id,
        source_path="mock.png",
        source_fingerprint="fp-1",
        provider="cloudinary",
        provider_asset_id=f"{prospect_id}:{job_id}",
        public_url=url,
        secure_url=url,
        hosted_at="2026-01-01T00:00:00+00:00",
    )
    components["hosted_store"].put(asset)
    components["hosted_store"].save()
    return asset
def main() -> int:
    import csv

    counts = {"passed": 0, "failed": 0}
    with tempfile.TemporaryDirectory() as root:
        c = _build(root)
        a, a_proj, _ = _ready(c, "a", "A Co", "a@example.com")
        _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
        _ready(c, "cc", "C Co", "c@example.com", image_name="c.png")
        _ready(c, "z", "Z Co", "z@example.com", image_name="z.png")
        _hosted(c, "a", a_proj, "job-a", "https://res.cloudinary.com/demo/a.png")

        run_a = c["run_service"].create_run("Alpha", ["a", "b", "cc"])
        prepared = c["run_handoff"].prepare_package_for_run(run_a.id)
        check("run-scoped package prepared", prepared.summary.packaged == 2 and prepared.summary.blocked == 1, counts)

        record = c["run_handoff"].context_for_run(run_a.id).package_record
        check(
            "package members scoped to run",
            {e.prospect_id for e in record.entries} == {"a", "b", "cc"},
            counts,
        )

        membership_before = list(c["run_service"].get_run(run_a.id).prospect_ids)
        handoff_dir = record.handoff_directory
        handoff_files_before = sorted(os.listdir(handoff_dir))

        result = c["export_svc"].export_run(run_a.id)
        check("export succeeds", result.success, counts)
        check("export targets correct run", result.receipt.campaign_run_id == run_a.id, counts)
        check("correct READY count", result.ready == 2 and result.exported_rows == 2, counts)
        check("excluded member counted", result.excluded == 1, counts)

        with open(result.smartlead_csv_path, "r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        csv_ids = {r.get("prospect_id") for r in rows}
        check("correct READY rows exported", csv_ids == {"a", "cc"}, counts)
        check("blocked/excluded not exported", "b" not in csv_ids, counts)

        header = list(rows[0].keys())
        check(
            "existing Smartlead columns preserved",
            header == build_export_columns(list(DEFAULT_SMARTLEAD_COLUMN_ORDER)),
            counts,
        )
        check(
            "mockup_url additive after mockup_path",
            header.index("mockup_url") == header.index("mockup_path") + 1,
            counts,
        )
        by_id = {r["prospect_id"]: r for r in rows}
        check(
            "mockup_url propagated for hosted prospect",
            by_id["a"]["mockup_url"] == "https://res.cloudinary.com/demo/a.png",
            counts,
        )
        check(
            "missing public URL degrades gracefully",
            by_id["cc"]["mockup_url"] == "" and by_id["cc"].get("mockup_path"),
            counts,
        )
        check(
            "default destination under export root",
            result.export_directory == os.path.join(c["export_svc"].export_root, "Alpha")
            and os.path.isfile(result.smartlead_csv_path),
            counts,
        )

        dest = os.path.join(root, "custom_export")
        r2 = c["export_svc"].export_run(run_a.id, destination=dest)
        check(
            "explicit destination works",
            r2.success and os.path.isfile(r2.smartlead_csv_path) and os.path.dirname(r2.smartlead_csv_path) == dest,
            counts,
        )

        check(
            "no run membership mutation",
            list(c["run_service"].get_run(run_a.id).prospect_ids) == membership_before,
            counts,
        )
        check("handoff directory untouched by export", sorted(os.listdir(handoff_dir)) == handoff_files_before, counts)

        # Duplicate conflict protection (dedicated run).
        _ready(c, "a1", "A One", "dup@example.com", image_name="a1.png")
        _ready(c, "a2", "A Two", "dup@example.com", image_name="a2.png")
        run_d = c["run_service"].create_run("Dup", ["a1", "a2"])
        c["run_handoff"].prepare_package_for_run(run_d.id)
        dres = c["export_svc"].export_run(run_d.id)
        check(
            "duplicate conflict protected",
            dres.ready == 0 and dres.conflict == 2 and dres.exported_rows == 0 and dres.smartlead_csv_path == "",
            counts,
        )

        # Unprepared run is blocked (no fallback to all prospects).
        run_b = c["run_service"].create_run("Bravo", ["z"])
        b_result = c["export_svc"].export_run(run_b.id)
        check("unprepared run export is blocked", not b_result.success and not os.path.exists(b_result.smartlead_csv_path), counts)

        # Standalone handoff service remains available.
        standalone = SmartleadHandoffService()
        standalone_result = standalone.prepare_handoff(record.package_directory)
        check("standalone Smartlead handoff remains available", standalone_result is not None, counts)

        # Durable export metadata survives a full reload.
        c2 = _build(root)
        receipt = c2["export_svc"].latest_export(run_a.id)
        check(
            "durable export metadata survives reload",
            receipt is not None
            and receipt.campaign_run_id == run_a.id
            and receipt.smartlead_csv_path == r2.smartlead_csv_path
            and receipt.exported_rows == 2,
            counts,
        )

    print("SPRINT 5Y VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())