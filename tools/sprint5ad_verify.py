"""Sprint 5AD offline verifier: bulk campaign assembly acceptance checks."""
from __future__ import annotations

import csv
import importlib.util
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Avoid importing engine.__init__ (which imports uploader/cloudinary) during this
# offline verifier.  personalization_field_values only needs PersonFacts from
# engine.person_personalization, so load that module directly and register a
# minimal engine package shim for this process.
if "engine.person_personalization" not in sys.modules:
    engine_pkg = types.ModuleType("engine")
    engine_pkg.__path__ = [os.path.join(ROOT, "engine")]
    sys.modules.setdefault("engine", engine_pkg)
    spec = importlib.util.spec_from_file_location(
        "engine.person_personalization",
        os.path.join(ROOT, "engine", "person_personalization.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["engine.person_personalization"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

from gui.models.campaign_assembly import ASSEMBLY_STATUS_BLOCKED, ASSEMBLY_STATUS_EXCLUDED, CampaignAssemblyStore
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.mockup_concept import MockupConcept
from gui.models.personalization_field_catalog import PersonalizationFieldMapping, PersonalizationFieldMappingStore, default_personalization_mapping
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.models.prospect_generation import OpportunityGenerationContext, ProspectGenerationJob
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.prospect_store import ProspectStore
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_assembly import CampaignAssemblyService, REASON_MISSING_EMAIL
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.services.smartlead_run_export import SmartleadRunExportService
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    if condition:
        counts["pass"] += 1
        print(f"PASS {name}")
    else:
        counts["fail"] += 1
        print(f"FAIL {name}")


def runtime(root: str):
    prospect_store = ProspectStore(path=os.path.join(root, "prospects.json"))
    job_store = ProspectGenerationStore(path=os.path.join(root, "jobs.json"))
    project_store = ProjectStore(root=os.path.join(root, "projects"))
    review_store = CampaignReviewStore(path=os.path.join(root, "review.json"))
    run_store = CampaignRunStore(path=os.path.join(root, "runs.json"))
    export_service = CampaignExportService(prospect_store=prospect_store, job_store=job_store, project_store=project_store)
    package_service = CampaignPackageService(export_service=export_service)
    review_service = CampaignReviewService(prospect_store=prospect_store, export_service=export_service, review_store=review_store, package_service=package_service)
    run_service = CampaignRunService(run_store=run_store, prospect_store=prospect_store, job_store=job_store, project_store=project_store, review_store=review_store, export_service=export_service, review_service=review_service)
    run_handoff = SmartleadRunHandoffService(run_service=run_service, package_store=SmartleadRunPackageStore(path=os.path.join(root, "packages.json")), package_root=os.path.join(root, "smartlead_runs"))
    mapping_store = PersonalizationFieldMappingStore(path=os.path.join(root, "mapping.json"))
    run_export = SmartleadRunExportService(run_handoff_service=run_handoff, hosted_asset_store=HostedAssetStore(path=os.path.join(root, "hosted.json")), mapping_store=mapping_store, export_root=os.path.join(root, "exports"))
    assembly_store = CampaignAssemblyStore(path=os.path.join(root, "assemblies.json"))
    assembly = CampaignAssemblyService(run_service=run_service, run_handoff_service=run_handoff, run_export_service=run_export, assembly_store=assembly_store)
    return locals()


def ready(c, pid: str, *, email: str | None = None, contact_name: str = "Alice Owner") -> None:
    prospect = Prospect(prospect_id=pid, company_name=f"{pid.upper()} Co", website=f"https://{pid}.example.com", email=email if email is not None else f"{pid}@example.com", contact_name=contact_name, category="roofing", city="Castle Rock", state="CO")
    c["prospect_store"].create(prospect)
    c["prospect_store"].save()
    project = c["project_store"].create(company_name=prospect.company_name, website=prospect.website, name=pid)
    image_path = os.path.join(project.image_path, f"{pid}.png")
    with open(image_path, "w", encoding="utf-8") as handle:
        handle.write(pid)
    concept = MockupConcept.create(image_path=image_path, template="contractor", headline=f"{pid} Billboard", cta="Call Today", quality_score=90, company_name=prospect.company_name)
    project.add_concept(concept)
    c["project_store"].save(project)
    job = ProspectGenerationJob(id=f"job-{pid}", prospect_id=pid, website=prospect.website, template="contractor", status="SUCCEEDED", project_id=project.id, result_path=image_path, opportunity_id="opp-1", location_id="loc-1", placement_id="pl-1", opportunity_context=OpportunityGenerationContext(opportunity_id="opp-1", location_id="loc-1", placement_id="pl-1", city="Castle Rock", state="CO", placement_name="I-25", placement_type="Billboard"))
    c["job_store"].upsert(job)
    c["job_store"].save()
    c["review_service"].approve(pid)


def main() -> int:
    counts = {"pass": 0, "fail": 0}
    with tempfile.TemporaryDirectory(prefix="bb_5ad_verify_") as root:
        c = runtime(root)
        ready(c, "a")
        ready(c, "b", contact_name="")
        missing = Prospect(prospect_id="missing", company_name="Missing Co", email="", website="https://missing.example.com")
        c["prospect_store"].create(missing)
        c["prospect_store"].save()
        ready(c, "excluded")
        c["review_service"].exclude("excluded")
        mapping = default_personalization_mapping()
        mapping.append(PersonalizationFieldMapping("professional_title", "professional_title", enabled=True, position=999))
        c["mapping_store"].save(mapping)
        run = c["run_service"].create_run("Sprint 5AD", ["a", "b", "missing", "excluded"])

        assembled = c["assembly"].assemble_campaign(run.id)
        rows = {row.prospect_id: row for row in assembled.snapshot.readiness}
        check("assembly succeeds", assembled.success, counts)
        check("ready/warning exportable", assembled.summary.exportable == 2, counts)
        check("missing email blocked", rows["missing"].status == ASSEMBLY_STATUS_BLOCKED and assembled.summary.reason_counts.get(REASON_MISSING_EMAIL) == 1, counts)
        check("explicit exclusion persisted", rows["excluded"].status == ASSEMBLY_STATUS_EXCLUDED, counts)
        check("optional mapping warning nonblocking", rows["a"].exportable and assembled.snapshot.mapping_fingerprint, counts)

        exported = c["assembly"].export_campaign(run.id, destination=os.path.join(root, "final_export"))
        check("Smartlead export integration", exported.success and os.path.isfile(exported.export_result.smartlead_csv_path), counts)
        if exported.success and exported.export_result.smartlead_csv_path:
            with open(exported.export_result.smartlead_csv_path, newline="", encoding="utf-8") as handle:
                export_rows = list(csv.DictReader(handle))
            check("Sprint 5AC mapped optional column emitted", "professional_title" in export_rows[0], counts)
        else:
            check("Sprint 5AC mapped optional column emitted", False, counts)

        reloaded_store = CampaignAssemblyStore(path=c["assembly_store"].path)
        check("restart persistence", reloaded_store.get(run.id) is not None and len(reloaded_store.get(run.id).readiness) == 4, counts)
        before_jobs = [job.to_dict() for job in c["job_store"].list()]
        c["assembly"].assemble_campaign(run.id)
        after_jobs = [job.to_dict() for job in c["job_store"].list()]
        check("no generation side effect", before_jobs == after_jobs, counts)
        check("no Smartlead/API side effect", exported.success and exported.export_result.exported_rows == 2, counts)

    print(f"Sprint 5AD verifier: {counts['pass']} PASS, {counts['fail']} FAIL")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())