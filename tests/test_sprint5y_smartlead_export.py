"""Sprint 5Y tests for run-scoped Smartlead portable export."""
from __future__ import annotations

import csv
import json
import os

from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.hosted_asset import HostedMockupAsset
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.mockup_concept import MockupConcept
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
    SMARTLEAD_EXPORT_WARNING,
)
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.services.smartlead_run_export import SmartleadRunExportService, build_export_columns
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService


def _runtime(tmp_path):
    root = str(tmp_path)
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
def _ready_prospect(components, prospect_id, company, email, image_name="mock.png"):
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
        source_path="irrelevant.png",
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


def _prepare_run(run_service, run_handoff, name, prospect_ids):
    run = run_service.create_run(name, prospect_ids)
    run_handoff.prepare_package_for_run(run.id)
    return run


def _read_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
# --- A. Basic export -----------------------------------------------------
def test_basic_export(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "b"])

    result = c["export_svc"].export_run(run.id)
    assert result.success
    assert result.exported_rows == 1
    assert result.ready == 1
    assert result.excluded == 1
    assert result.export_directory
    assert os.path.isfile(result.smartlead_csv_path)
    assert result.receipt is not None
    rows = _read_csv_rows(result.smartlead_csv_path)
    assert len(rows) == 1
    assert rows[0]["email"] == "a@example.com"


# --- B. Schema preservation + additive mockup_url -----------------------
def test_export_schema_preserves_handoff_columns_and_adds_mockup_url(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "b"])

    result = c["export_svc"].export_run(run.id)
    rows = _read_csv_rows(result.smartlead_csv_path)
    header = list(rows[0].keys())

    expected = build_export_columns(list(DEFAULT_SMARTLEAD_COLUMN_ORDER))
    assert header == expected
    # Established handoff fields are all present and correctly ordered.
    assert header.index("mockup_url") == header.index("mockup_path") + 1
    for idx, column in enumerate(DEFAULT_SMARTLEAD_COLUMN_ORDER):
        assert column in header
    # Additive field present and blank when not hosted.
    assert SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN in header
    assert rows[0][SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN] == ""

    # Deterministic ordering of rows.
    result2 = c["export_svc"].export_run(run.id)
    rows2 = _read_csv_rows(c["export_svc"].latest_export(run.id).smartlead_csv_path)
    assert [r["prospect_id"] for r in rows2] == [r["prospect_id"] for r in rows]


# --- C. Hosted URL propagation ------------------------------------------
def test_hosted_url_propagates_for_matching_prospect(tmp_path):
    c = _runtime(tmp_path)
    a, a_proj, _ = _ready_prospect(c, "a", "A Co", "a@example.com")
    _ready_prospect(c, "cc", "C Co", "c@example.com", image_name="c.png")
    _hosted(c, "a", a_proj, "job-a", "https://res.cloudinary.com/demo/a.png")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "cc"])

    result = c["export_svc"].export_run(run.id)
    assert result.with_public_url == 1
    by_id = {r["prospect_id"]: r for r in _read_csv_rows(result.smartlead_csv_path)}
    assert by_id["a"][SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN] == "https://res.cloudinary.com/demo/a.png"
    # cc has no hosted receipt -> falls back, stays exportable.
    assert by_id["cc"][SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN] == ""
    assert result.local_fallback == 1
    row_a = next(r for r in result.rows if r.prospect_id == "a")
    assert row_a.has_public_url


# --- D. Missing hosted URL is exportable + local fallback ---------------
def test_missing_hosted_url_lead_still_exportable(tmp_path):
    c = _runtime(tmp_path)
    _, _, concept = _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])

    result = c["export_svc"].export_run(run.id)
    assert result.success
    assert result.exported_rows == 1
    assert result.with_public_url == 0
    assert result.local_fallback == 1
    rows = _read_csv_rows(result.smartlead_csv_path)
    assert rows[0][SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN] == ""
    assert rows[0]["mockup_path"] != ""
    row_a = next(r for r in result.rows if r.prospect_id == "a")
    assert row_a.status == SMARTLEAD_EXPORT_READY


# --- E. Existing handoff blocker not promoted ---------------------------
def test_non_ready_member_not_promoted(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "b"])

    result = c["export_svc"].export_run(run.id)
    row_b = next(r for r in result.rows if r.prospect_id == "b")
    assert row_b.status == SMARTLEAD_EXPORT_EXCLUDED
    assert row_b.status != SMARTLEAD_EXPORT_READY
    # Blocked/excluded member never appears as a valid outbound row.
    csv_ids = {r["prospect_id"] for r in _read_csv_rows(result.smartlead_csv_path)}
    assert "b" not in csv_ids


# --- F. Duplicate email conflict ----------------------------------------
def test_duplicate_email_conflict_not_exported_as_ready(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a1", "A One", "dup@example.com", image_name="a1.png")
    _ready_prospect(c, "a2", "A Two", "dup@example.com", image_name="a2.png")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a1", "a2"])

    result = c["export_svc"].export_run(run.id)
    statuses = {r.prospect_id: r.status for r in result.rows}
    # Established handoff CONFLICT semantics: both duplicate rows are CONFLICT
    # (the app's "zero ready on duplicate" behavior), never independent READY.
    assert statuses == {"a1": SMARTLEAD_EXPORT_CONFLICT, "a2": SMARTLEAD_EXPORT_CONFLICT}
    assert result.ready == 0
    assert result.conflict == 2
    assert result.exported_rows == 0
    # No duplicate conflicting lead is emitted as a valid outbound row.
    assert result.smartlead_csv_path == ""
# --- G. Excluded member represented correctly ---------------------------
def test_excluded_member_summary(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "b"])

    result = c["export_svc"].export_run(run.id)
    by_id = {r.prospect_id: r.status for r in result.rows}
    assert by_id["b"] == SMARTLEAD_EXPORT_EXCLUDED
    assert result.excluded == 1
    row_ids = {r["prospect_id"] for r in _read_csv_rows(result.smartlead_csv_path)}
    assert "b" not in row_ids


# --- H. Explicit destination --------------------------------------------
def test_explicit_destination(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    dest = os.path.join(str(tmp_path), "custom", "out")
    result = c["export_svc"].export_run(run.id, destination=dest)
    assert result.success
    assert os.path.isabs(result.export_directory)
    assert os.path.dirname(result.smartlead_csv_path) == os.path.normpath(dest)
    assert os.path.isfile(result.smartlead_csv_path)


# --- I. Default destination ---------------------------------------------
def test_default_destination(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    result = c["export_svc"].export_run(run.id)
    assert result.export_directory == os.path.join(c["export_svc"].export_root, "Alpha")
    assert result.smartlead_csv_path == os.path.join(result.export_directory, "smartlead.csv")
    assert os.path.isfile(result.smartlead_csv_path)


# --- J. Collision / repeat export ---------------------------------------
def test_repeat_export_does_not_overwrite(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])

    first = c["export_svc"].export_run(run.id)
    second = c["export_svc"].export_run(run.id)
    assert first.export_directory != second.export_directory
    assert os.path.isfile(first.smartlead_csv_path)
    assert os.path.isfile(second.smartlead_csv_path)
    assert _read_csv_rows(first.smartlead_csv_path) == _read_csv_rows(second.smartlead_csv_path)

    dest = os.path.join(str(tmp_path), "explicit")
    r1 = c["export_svc"].export_run(run.id, destination=dest)
    r2 = c["export_svc"].export_run(run.id, destination=dest)
    assert r1.smartlead_csv_path.endswith("smartlead.csv")
    assert r2.smartlead_csv_path.endswith("smartlead_2.csv")
    assert os.path.isfile(r1.smartlead_csv_path)
    assert os.path.isfile(r2.smartlead_csv_path)


# --- K. Restart persistence ---------------------------------------------
def test_export_metadata_survives_restart(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    result = c["export_svc"].export_run(run.id)

    c2 = _runtime(tmp_path)
    receipt = c2["export_svc"].latest_export(run.id)
    assert receipt is not None
    assert receipt.campaign_run_id == run.id
    assert receipt.smartlead_csv_path == result.smartlead_csv_path
    assert receipt.exported_rows == 1
    assert os.path.isfile(receipt.smartlead_csv_path)
    assert c2["run_handoff"].context_for_run(run.id).package_record is not None
# --- L. No canonical mutation -------------------------------------------
def test_export_does_not_mutate_canonical_state(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "b"])

    membership_before = list(c["run_service"].get_run(run.id).prospect_ids)
    prospects_before = len(c["prospect_store"].list())
    jobs_before = len(c["job_store"].list())
    package_before = c["run_handoff"].context_for_run(run.id).summary.packaged
    handoff_files = sorted(os.listdir(c["run_handoff"].context_for_run(run.id).package_record.handoff_directory))

    result = c["export_svc"].export_run(run.id)
    assert result.success

    assert list(c["run_service"].get_run(run.id).prospect_ids) == membership_before
    assert len(c["prospect_store"].list()) == prospects_before
    assert len(c["job_store"].list()) == jobs_before
    assert c["run_handoff"].context_for_run(run.id).summary.packaged == package_before
    assert sorted(os.listdir(c["run_handoff"].context_for_run(run.id).package_record.handoff_directory)) == handoff_files
    assert len(c["hosted_store"].list()) == 0


# --- M. Missing package --------------------------------------------------
def test_missing_package_fails_cleanly(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = c["run_service"].create_run("Alpha", ["a"])  # not prepared

    result = c["export_svc"].export_run(run.id)
    assert not result.success
    assert result.smartlead_csv_path == ""
    assert not os.path.exists(c["export_svc"].export_root)


# --- N. Run isolation ----------------------------------------------------
def test_run_isolation(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _ready_prospect(c, "cc", "C Co", "c@example.com", image_name="c.png")
    _ready_prospect(c, "z", "Z Co", "z@example.com", image_name="z.png")
    run_a = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "cc"])

    result = c["export_svc"].export_run(run_a.id)
    csv_ids = {r["prospect_id"] for r in _read_csv_rows(result.smartlead_csv_path)}
    assert csv_ids == {"a", "cc"}
    assert "z" not in csv_ids


# --- O. Standalone compatibility ----------------------------------------
def test_standalone_handoff_unchanged(tmp_path):
    from gui.services.smartlead_handoff import SmartleadHandoffService

    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    package_record = c["run_handoff"].context_for_run(run.id).package_record
    handoff_dir = package_record.handoff_directory
    before = sorted(os.listdir(handoff_dir))

    standalone = SmartleadHandoffService()
    profile = standalone.prepare_handoff(package_record.package_directory)
    assert not isinstance(profile, type(None))

    c["export_svc"].export_run(run.id)
    assert sorted(os.listdir(handoff_dir)) == before
# --- P. UI signal safety -------------------------------------------------
def test_export_button_executes_once_without_recursion(tmp_path):
    from collections import Counter

    from PySide6.QtWidgets import QApplication
    from gui.controllers.smartlead_handoff_controller import SmartleadHandoffController
    from gui.views.smartlead_handoff_page import SmartleadHandoffPage

    app = QApplication.instance() or QApplication([])
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    _prospect(c["prospect_store"], prospect_id="b", company_name="B Co", email="")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a", "b"])

    stub_service = type("S", (), {"prepare_handoff": lambda self, d: None})()
    controller = SmartleadHandoffController(
        service=stub_service,
        run_handoff_service=c["run_handoff"],
        run_export_service=c["export_svc"],
    )
    page = SmartleadHandoffPage()
    page.set_controller(controller)
    page.set_controller(controller)  # second bind is a no-op
    controller.open_run_context(run.id)
    app.processEvents()

    counts = Counter()

    def wrap(fn, name):
        def _wrapped(*args, **kwargs):
            counts[name] += 1
            if counts[name] > 5:
                raise AssertionError(f"unexpected recursion via {name}")
            return fn(*args, **kwargs)
        return _wrapped

    controller.export_run_smartlead = wrap(controller.export_run_smartlead, "export")
    page.export_run_button.click()
    app.processEvents()
    assert counts["export"] == 1
    assert page.export_run_button.isEnabled()
# --- Q. last_export backward compatibility (Section 4 audit) -------------
def test_last_export_backward_compatible(tmp_path):
    from gui.models.smartlead_run_export import SmartleadRunExportReceipt
    from gui.models.smartlead_run_package import SmartleadRunPackageRecord

    # A Sprint 5X-era record that has no last_export key at all must still load.
    old = {
        "campaign_run_id": "run-old",
        "package_id": "pkg-old",
        "package_directory": "/tmp/pkg",
        "handoff_directory": "/tmp/handoff",
        "smartlead_csv_path": "/tmp/handoff/smartlead.csv",
        "status": "PACKAGED",
        "total_members": 2,
        "entries": [
            {"prospect_id": "a", "status": "READY", "project_id": "p1", "generation_job_id": "job-a", "email": "a@example.com", "blocker": ""},
            {"prospect_id": "b", "status": "BLOCKED", "project_id": "", "generation_job_id": "", "email": "", "blocker": "missing email"},
        ],
    }
    record = SmartleadRunPackageRecord.from_dict(old)
    assert record.campaign_run_id == "run-old"
    assert record.last_export == {}
    assert record.ready_count == 0  # established defaults preserved
    assert len(record.entries) == 2
    assert record.entries[0].generation_job_id == "job-a"

    # Missing / absent-plus variants are equally safe on load.
    for missing_key in (None, ""):
        variant = dict(old)
        variant["last_export"] = missing_key
        assert SmartleadRunPackageRecord.from_dict(variant).last_export == {}

    # Malformed optional export metadata inside last_export (None fields, bad int)
    # must not break loading of an otherwise valid record.
    partial = dict(old)
    partial["last_export"] = {
        "campaign_run_id": None,
        "package_id": "pkg-old",
        "export_directory": "",
        "smartlead_csv_path": None,
        "exported_rows": "not-an-int",
        "total_members": 3,
        "conflict": "-1",
    }
    loaded = SmartleadRunPackageRecord.from_dict(partial)
    assert loaded.last_export["total_members"] == 3
    receipt = SmartleadRunExportReceipt.from_dict(loaded.last_export)
    assert receipt.campaign_run_id == ""
    assert receipt.total_members == 3
    assert receipt.exported_rows == 0  # non-int coerced safely

    # Serialization round-trips last_export stably.
    serialized = loaded.to_dict()
    assert serialized["last_export"] == loaded.last_export
    assert SmartleadRunPackageRecord.from_dict(serialized).last_export == loaded.last_export

    # latest_export tolerates a record with no durable export yet.
    c = _runtime(tmp_path)
    c["package_store"].upsert(SmartleadRunPackageRecord.from_dict(old))
    assert c["export_svc"].latest_export("run-old") is None