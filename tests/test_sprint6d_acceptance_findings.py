from __future__ import annotations

import csv
import json
import os
import time

from engine.brand_profile import BrandAsset, BrandProfile, BrandProfileBuilder
from engine.person_personalization import EXPERIENCE, choose_personalization
from gui.models.mockup_concept import MockupConcept
from gui.models.project import Project
from gui.models.project_store import ProjectStore
from gui.models.prospect import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_ERROR,
    RESOLUTION_NOT_FOUND,
    RESOLUTION_RESOLVED,
    RESOLUTION_TIMEOUT,
    Prospect,
)
from gui.models.smartlead_run_export import (
    SMARTLEAD_EXPORT_BLOCKED,
    SMARTLEAD_EXPORT_CONFLICT,
    SMARTLEAD_EXPORT_EXCLUDED,
    SMARTLEAD_EXPORT_READY,
    SMARTLEAD_EXPORT_WARNING,
    SmartleadRunExportReceipt,
)
from gui.models.smartlead_run_package import SmartleadRunPackageEntry, SmartleadRunPackageRecord
from gui.services.copy_quality import (
    MISSING_CTA,
    MISSING_HEADLINE,
    QUALITY_BLOCKED,
    QUALITY_PASS,
    SEO_TITLE_LIKE,
    UNSUPPORTED_NUMERIC_CLAIM,
    UNSUPPORTED_SUPERLATIVE,
    assess_copy_quality,
)
from gui.services.profile_resolver import ProfileResolverService
from gui.services.smartlead_run_export import SmartleadRunExportService


PARENT = "https://example.com"


class _Row:
    def __init__(self, headline="Trusted Local Care", cta="Call Today", body="A billboard for Example Co."):
        self.headline = headline
        self.cta = cta
        self.email_subject = "Billboard idea"
        self.email_body = body
        self.personalization_basis = ""
        self.creative_summary = ""


def _prospect(**overrides) -> Prospect:
    data = dict(
        prospect_id="p1",
        company_name="Example Realty",
        website=PARENT,
        email="a@example.com",
        contact_name="Jane Smith",
        category="real estate",
    )
    data.update(overrides)
    return Prospect(**data)


def _project(tmp_path, prospect: Prospect, source_text: str = "") -> Project:
    project = Project.create(output_root=str(tmp_path), name="proj")
    profile = BrandProfile(company_name=prospect.company_name, website=prospect.website)
    if source_text:
        project.metadata["source_evidence"] = source_text
    project.update_from_pipeline(brand_profile=profile, concepts=[])
    return project


def _concept(headline: str, cta: str = "Call Today") -> MockupConcept:
    return MockupConcept.create("mock.png", "contractor", headline, cta, 90, company_name="Example Realty")


def _codes(result) -> set[str]:
    return {reason.code for reason in result.reasons}


def test_resolver_total_deadline_interrupts_blocking_fetch_and_stays_safe() -> None:
    calls: list[str] = []

    def slow_fetch(url: str) -> str:
        calls.append(url)
        time.sleep(0.25)
        return "<urlset><url><loc>https://example.com/agents/jane-smith</loc></url></urlset>"

    service = ProfileResolverService(fetcher=slow_fetch, browser_fetcher=None, total_timeout=0.03)
    started = time.monotonic()
    result = service.resolve("Jane Smith", PARENT)
    elapsed = time.monotonic() - started

    assert elapsed < 0.15
    assert calls
    assert result.status == RESOLUTION_TIMEOUT
    assert result.url == ""
    assert result.diagnostics["bounded_limits"]["total_timeout_seconds"] == 0.03
    assert result.diagnostics["timeout_reason"].startswith("TOTAL_RESOLUTION_TIMEOUT:")
    assert result.diagnostics.get("timeout_stage") in {"collect_sitemaps", "sitemap_discovery"}


def test_resolver_fast_resolution_unaffected() -> None:
    def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
        if url.endswith("/sitemap.xml") or url.endswith("/sitemap_index.xml"):
            return "<urlset><url><loc>https://example.com/agent/jane-smith</loc></url></urlset>"
        if url.endswith("/agent/jane-smith"):
            return "<html><head><title>Jane Smith | Example Realty</title></head><body><h1>Jane Smith</h1><p>Jane Smith helps buyers.</p></body></html>"
        return "<html></html>"

    result = ProfileResolverService(fetcher=fetch, total_timeout=2).resolve("Jane Smith", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.url == "https://example.com/agent/jane-smith"


def _person_scrape(years_text: str = "18 years helping clients move.") -> dict:
    return {
        "url": "https://example.com/agent/jane-smith",
        "company": "Example Realty",
        "headline": "Jane Smith | Example Realty",
        "ad_copy": "Jane Smith | Example Realty",
        "metadata": {"title": "Jane Smith | Example Realty"},
        "html": f"<html><body><h1>Jane Smith</h1><p>{years_text}</p></body></html>",
        "business_intel": {"categories": ["real estate agent"]},
        "person_context": {"contact_name": "Jane Smith", "resolved_profile_url": "https://example.com/agent/jane-smith"},
    }


def test_person_fact_provenance_persists_and_supports_numeric_copy(tmp_path) -> None:
    profile = BrandProfileBuilder.from_scrape_data(_person_scrape())
    assert profile.person_facts.years_experience == "18"
    assert profile.person_facts.provenance["years_experience"]
    restored = BrandProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert restored.person_facts.years_experience == "18"
    assert restored.person_facts.provenance["years_experience"]

    project = Project.create(output_root=str(tmp_path), name="person")
    project.update_from_pipeline(brand_profile=profile, concepts=[_concept(profile.personalized_headline, profile.personalized_cta)])
    prospect = _prospect()
    result = assess_copy_quality(prospect=prospect, concept=_concept("18 Years Helping Buyers Move"), project=project, row=_Row(headline="18 Years Helping Buyers Move", body="A billboard for Example Realty."))
    assert result.status == QUALITY_PASS


def test_unsupported_claims_remain_blocked_and_copy_is_not_evidence(tmp_path) -> None:
    prospect = _prospect()
    project = _project(tmp_path, prospect, "Jane Smith helps buyers and sellers.")
    numeric = assess_copy_quality(prospect=prospect, concept=_concept("18 Years Helping Buyers Move"), project=project, row=_Row(headline="18 Years Helping Buyers Move"))
    assert numeric.status == QUALITY_BLOCKED
    assert UNSUPPORTED_NUMERIC_CLAIM in _codes(numeric)
    superlative = assess_copy_quality(prospect=prospect, concept=_concept("#1 Agent in Iowa"), project=project, row=_Row(headline="#1 Agent in Iowa"))
    assert superlative.status == QUALITY_BLOCKED
    assert UNSUPPORTED_SUPERLATIVE in _codes(superlative)


def _asset(tmp_path, name: str, url: str) -> dict:
    path = os.path.join(str(tmp_path), name)
    with open(path, "wb") as handle:
        handle.write(b"fake")
    return BrandAsset(path=path, source_url=url, width=400, height=400, aspect_ratio=1.0, evidence=["dom_context:Bob Agent profile headshot"]).to_dict()


def test_unresolved_person_fallback_suppresses_person_identity_and_assets(tmp_path) -> None:
    for status in (RESOLUTION_AMBIGUOUS, RESOLUTION_NOT_FOUND, RESOLUTION_ERROR):
        data = {
            "url": PARENT,
            "company": "Example Realty",
            "headline": "Example Realty",
            "ad_copy": "Homes Across Town",
            "html": "<html><body><h1>Our Team</h1><p>Bob Agent and Alice Agent serve buyers.</p></body></html>",
            "metadata": {"title": "Example Realty Team"},
            "assets": [_asset(tmp_path, f"bob-{status}.jpg", "https://example.com/bob-agent-headshot.jpg")],
            "person_context": {"contact_name": "Jane Smith", "resolution_status": status, "company_name": "Example Realty"},
        }
        profile = BrandProfileBuilder.from_scrape_data(data)
        assert profile.person_facts.contact_name == ""
        assert profile.personalized_headline == ""
        assert profile.source_metadata["asset_selection_diagnostics"]["intended_person_unresolved"] is True
        assert all(asset.role != "PERSON_PROFILE" for asset in profile.assets)


def test_generic_business_behavior_unaffected(tmp_path) -> None:
    data = {
        "url": PARENT,
        "company": "Example Roofing",
        "headline": "Example Roofing",
        "ad_copy": "Storm Damage Help",
        "html": "<html><body><h1>Example Roofing</h1></body></html>",
        "metadata": {"title": "Example Roofing"},
    }
    profile = BrandProfileBuilder.from_scrape_data(data)
    assert profile.person_facts.contact_name == ""
    assert profile.ad_copy == "Storm Damage Help"


def test_copy_quality_blocks_missing_headline_and_cta(tmp_path) -> None:
    prospect = _prospect(contact_name="")
    project = _project(tmp_path, prospect, "Example Realty")
    blank = assess_copy_quality(prospect=prospect, concept=_concept(""), project=project, row=_Row(headline="", cta="Call Today"))
    assert blank.status == QUALITY_BLOCKED
    assert MISSING_HEADLINE in _codes(blank)
    whitespace = assess_copy_quality(prospect=prospect, concept=_concept(""), project=project, row=_Row(headline="   ", cta="Call Today"))
    assert whitespace.status == QUALITY_BLOCKED
    assert MISSING_HEADLINE in _codes(whitespace)
    no_cta = assess_copy_quality(prospect=prospect, concept=_concept("Trusted Local Care", ""), project=project, row=_Row(headline="Trusted Local Care", cta=""))
    assert no_cta.status == QUALITY_BLOCKED
    assert MISSING_CTA in _codes(no_cta)
    valid = assess_copy_quality(prospect=prospect, concept=_concept("Trusted Local Care"), project=project, row=_Row(headline="Trusted Local Care", cta="Call Today", body="A billboard for Example Realty."))
    assert valid.status == QUALITY_PASS


def test_seo_title_rewritten_before_quality_warning(tmp_path) -> None:
    profile = BrandProfileBuilder.from_scrape_data({
        "url": "https://dental.example",
        "company": "Aspen Dental",
        "headline": "Aspen Dental | Find a Dentist Near You for Dental Care",
        "ad_copy": "Aspen Dental | Find a Dentist Near You for Dental Care",
        "business_intel": {"categories": ["dentist"], "services": ["dental care"]},
    })
    assert profile.ad_copy == "Find Your Local Dentist"
    assert profile.source_metadata["copy_generation_diagnostics"]["seo_title_rewritten"] is True
    prospect = _prospect(contact_name="", company_name="Aspen Dental", category="dentist")
    project = _project(tmp_path, prospect, "dentist dental care")
    result = assess_copy_quality(prospect=prospect, concept=_concept(profile.ad_copy), project=project, row=_Row(headline=profile.ad_copy))
    assert SEO_TITLE_LIKE not in _codes(result)


class _PackageStore:
    def __init__(self, record: SmartleadRunPackageRecord):
        self.path = os.path.join(record.handoff_directory, "packages.json")
        self.record = record

    def get(self, _campaign_run_id):
        return self.record

    def upsert(self, record):
        self.record = record
        return record

    def save(self):
        return None


class _RunHandoff:
    def __init__(self, record: SmartleadRunPackageRecord):
        self.package_store = _PackageStore(record)
        self._run_service = type("RunSvc", (), {"_prospect_store": {}, "_job_store": {}, "_project_store": {}})()

    def context_for_run(self, _campaign_run_id):
        return type("Ctx", (), {"package_record": self.package_store.record, "campaign_name": "Test"})()


def test_warning_status_preserved_through_local_export_manifest(tmp_path) -> None:
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    with open(handoff / "smartlead_preflight.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["prospect_id", "company", "email", "status", "reason", "warning"])
        writer.writeheader()
        writer.writerow({"prospect_id": "ready", "company": "Ready Co", "email": "r@example.com", "status": "READY", "reason": "", "warning": ""})
        writer.writerow({"prospect_id": "warn", "company": "Warn Co", "email": "w@example.com", "status": "WARNING", "reason": "", "warning": "minor"})
        writer.writerow({"prospect_id": "blocked", "company": "Blocked Co", "email": "b@example.com", "status": "BLOCKED", "reason": "bad", "warning": ""})
        writer.writerow({"prospect_id": "conflict", "company": "Conflict Co", "email": "c@example.com", "status": "CONFLICT", "reason": "duplicate", "warning": ""})
    with open(handoff / "smartlead.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["prospect_id", "company", "email", "mockup_path"])
        writer.writeheader()
        writer.writerow({"prospect_id": "ready", "company": "Ready Co", "email": "r@example.com", "mockup_path": "r.png"})
        writer.writerow({"prospect_id": "warn", "company": "Warn Co", "email": "w@example.com", "mockup_path": "w.png"})
    record = SmartleadRunPackageRecord(
        campaign_run_id="run-1",
        package_id="pkg-1",
        handoff_directory=str(handoff),
        smartlead_csv_path=str(handoff / "smartlead.csv"),
        entries=(
            SmartleadRunPackageEntry("ready", status="READY"),
            SmartleadRunPackageEntry("warn", status="WARNING"),
            SmartleadRunPackageEntry("blocked", status="BLOCKED"),
            SmartleadRunPackageEntry("conflict", status="CONFLICT"),
            SmartleadRunPackageEntry("excluded", status="EXCLUDED"),
        ),
    )
    run_handoff = _RunHandoff(record)
    service = SmartleadRunExportService(run_handoff_service=run_handoff, export_root=str(tmp_path / "exports"))
    result = service.export_run("run-1")
    assert result.success is True
    statuses = {row.prospect_id: row.status for row in result.rows}
    assert statuses == {
        "ready": SMARTLEAD_EXPORT_READY,
        "warn": SMARTLEAD_EXPORT_WARNING,
        "blocked": SMARTLEAD_EXPORT_BLOCKED,
        "conflict": SMARTLEAD_EXPORT_CONFLICT,
        "excluded": SMARTLEAD_EXPORT_EXCLUDED,
    }
    assert result.exported_rows == 2
    assert result.ready == 1
    assert result.warning == 1
    assert result.blocked == 1
    assert result.conflict == 1
    assert result.excluded == 1
    expected_exported_statuses = {"ready": SMARTLEAD_EXPORT_READY, "warn": SMARTLEAD_EXPORT_WARNING}
    assert result.receipt.exported_statuses == expected_exported_statuses
    assert list(result.receipt.exported_statuses) == ["ready", "warn"]
    with open(result.smartlead_csv_path, "r", encoding="utf-8", newline="") as handle:
        assert "status" not in next(csv.DictReader(handle))

    persisted = run_handoff.package_store.record.last_export
    assert persisted["exported_statuses"] == expected_exported_statuses
    assert SmartleadRunExportReceipt.from_dict(persisted).exported_statuses == expected_exported_statuses
    reloaded_record = SmartleadRunPackageRecord.from_dict(run_handoff.package_store.record.to_dict())
    reloaded_service = SmartleadRunExportService(run_handoff_service=_RunHandoff(reloaded_record), export_root=str(tmp_path / "exports_reload"))
    latest = reloaded_service.latest_export("run-1")
    assert latest is not None
    assert latest.exported_statuses == expected_exported_statuses

    old_receipt = dict(persisted)
    old_receipt.pop("exported_statuses")
    assert SmartleadRunExportReceipt.from_dict(old_receipt).exported_statuses == {}

    manifest = json.loads(open(result.manifest_path, "r", encoding="utf-8").read())
    assert manifest["receipt"]["ready"] == 1
    assert manifest["receipt"]["warning"] == 1
    assert manifest["receipt"]["exported_statuses"] == expected_exported_statuses
    manifest_statuses = {row["prospect_id"]: row["status"] for row in manifest["rows"]}
    assert manifest_statuses["warn"] == "WARNING"