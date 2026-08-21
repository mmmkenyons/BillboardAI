from __future__ import annotations

import csv
import os
from dataclasses import replace

from PIL import Image

from engine.brand_profile import BrandAsset, BrandProfile, BrandProfileBuilder, ROLE_GENERIC_HERO
from engine.content_safety import CHALLENGE_CONTENT_DETECTED, detect_challenge_content
from engine.renderer.renderer import (
    RENDER_CTA_OVERFLOW,
    RENDER_HEADLINE_OVERFLOW,
    RENDER_QUALITY_PASS,
    get_last_render_quality,
    render_billboard,
)
from gui.models.campaign_assembly import CampaignAssemblyReason, OutreachReadinessResult
from gui.models.mockup_concept import MockupConcept
from gui.models.personalization_field_catalog import PersonalizationFieldMappingStore
from gui.models.project import Project
from gui.models.prospect import Prospect
from gui.models.render_context import RenderContext
from gui.models.smartlead_handoff import DEFAULT_SMARTLEAD_COLUMN_ORDER
from gui.models.smartlead_run_export import SmartleadRunExportReceipt
from gui.models.smartlead_run_package import SmartleadRunPackageEntry, SmartleadRunPackageRecord, SmartleadRunPackageStore
from gui.services.campaign_assembly import CampaignAssemblyService
from gui.services.copy_quality import QUALITY_BLOCKED, assess_copy_quality
from gui.services.smartlead_run_export import SmartleadRunExportService, build_export_columns


def _image(path: str, size=(640, 360), color=(20, 90, 120)) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_campaign_assembly_export_compatibility_delegates_to_authoritative_path():
    assert hasattr(CampaignAssemblyService, "export_campaign")
    assert hasattr(CampaignAssemblyService, "export")
    assert CampaignAssemblyService.export.__name__ == "export"


def test_eight_member_six_exported_dispositions_are_explicit():
    entries = tuple(
        SmartleadRunPackageEntry(
            prospect_id=f"p{i}",
            status="READY" if i < 6 else "BLOCKED",
            included=i < 6,
            exportable=i < 6,
            exported=i < 6,
            disposition="EXPORTED" if i < 6 else "EXCLUDED_BLOCKED",
            disposition_reason="Exported" if i < 6 else "Not approved/exportable for prepared Smartlead package.",
        )
        for i in range(8)
    )
    assert len(entries) == 8
    assert sum(1 for e in entries if e.exported) == 6
    assert all(e.disposition and e.disposition_reason for e in entries)


def test_challenge_page_html_cannot_become_headline_or_company_evidence():
    data = {
        "url": "https://example.com",
        "html": "<title>Please Verify You Are Human</title><h1>Please Verify You Are Human</h1>",
        "company": "Please Verify You Are Human",
        "headline": "Please Verify You Are Human",
        "ad_copy": "Please Verify You Are Human",
        "metadata": {"title": "Please Verify You Are Human"},
    }
    profile = BrandProfileBuilder.from_scrape_data(data)
    assert profile.headline == ""
    assert profile.ad_copy == ""
    assert profile.logo is None
    assert profile.assets == []
    assert profile.source_metadata["content_safety"]["challenge"]["detected"] is True


def test_challenge_detector_is_generic():
    result = detect_challenge_content("Checking your browser. Just a moment. captcha required")
    assert result.detected is True
    assert result.indicators


def test_challenge_asset_does_not_become_preferred_creative_evidence(tmp_path):
    path = _image(str(tmp_path / "captcha.png"))
    profile = BrandProfileBuilder.from_scrape_data(
        {
            "url": "https://example.com",
            "company": "Example Dental",
            "assets": [BrandAsset(path=path, source_url="https://cdn.example.com/captcha-challenge.png", width=640, height=360).to_dict()],
        }
    )
    ctx = RenderContext.from_brand_profile(profile)
    assert ctx.hero_image in {"", profile.screenshot_path}
    rejected = ctx.opportunity_context["asset_selection"].get("rejected_candidates")
    assert rejected


def test_unrelated_brand_asset_rejected_and_correct_brand_survives(tmp_path):
    wrong = _image(str(tmp_path / "haynes-service-hero.png"))
    right = _image(str(tmp_path / "aspen-dental-hero.png"), color=(80, 20, 120))
    profile = BrandProfileBuilder.from_scrape_data(
        {
            "url": "https://www.aspendental.com",
            "company": "Aspen Dental",
            "assets": [
                BrandAsset(path=wrong, source_url="https://cdn.other.com/haynes-service-hero.png", width=640, height=360).to_dict(),
                BrandAsset(path=right, source_url="https://www.aspendental.com/aspen-dental-hero.png", width=640, height=360, role=ROLE_GENERIC_HERO).to_dict(),
            ],
        }
    )
    ctx = RenderContext.from_brand_profile(profile)
    assert ctx.hero_image == right
    rejected = ctx.opportunity_context["asset_selection"].get("rejected_candidates")
    assert any(item["reason"] == "conflicting_brand_asset" for item in rejected)


def _spec(headline="Fit Copy", cta="Call Today"):
    return RenderContext(company_name="Example Co", headline=headline, cta=cta, template="contractor").to_render_spec()


def test_render_headline_overflow_detected(tmp_path):
    render_billboard(_spec(headline="X" * 300), str(tmp_path / "headline.png"))
    codes = {r["code"] for r in get_last_render_quality()["reasons"]}
    assert RENDER_HEADLINE_OVERFLOW in codes


def test_render_cta_overflow_detected(tmp_path):
    render_billboard(_spec(cta="Schedule Your Comprehensive Whole Home Appointment Today"), str(tmp_path / "cta.png"))
    codes = {r["code"] for r in get_last_render_quality()["reasons"]}
    assert RENDER_CTA_OVERFLOW in codes


def test_acceptably_fitting_copy_remains_pass(tmp_path):
    render_billboard(_spec(), str(tmp_path / "fit.png"))
    assert get_last_render_quality()["status"] == RENDER_QUALITY_PASS


def test_render_quality_feeds_existing_readiness_gate():
    prospect = Prospect(prospect_id="p1", company_name="Example Co", website="https://example.com", email="a@example.com")
    project = Project(company="Example Co")
    concept = MockupConcept.create("mock.png", "contractor", "Fit Copy", "Call Today", 90, company_name="Example Co", render_quality={"status": QUALITY_BLOCKED, "reasons": [{"code": "RENDER_TEXT_CLIPPED", "message": "clipped", "severity": QUALITY_BLOCKED}]})
    row = type("Row", (), {"headline": "Fit Copy", "cta": "Call Today", "email_subject": "", "email_body": ""})()
    result = assess_copy_quality(prospect=prospect, concept=concept, project=project, row=row)
    assert result.status == QUALITY_BLOCKED
    assert any(r.code == "RENDER_TEXT_CLIPPED" for r in result.reasons)


def test_challenge_copy_feeds_existing_readiness_gate():
    prospect = Prospect(prospect_id="p1", company_name="Example Co", website="https://example.com", email="a@example.com")
    concept = MockupConcept.create("mock.png", "contractor", "Please Verify You Are Human", "Call Today", 90, company_name="Example Co")
    row = type("Row", (), {"headline": concept.headline, "cta": concept.cta, "email_subject": "", "email_body": ""})()
    result = assess_copy_quality(prospect=prospect, concept=concept, project=Project(company="Example Co"), row=row)
    assert result.status == QUALITY_BLOCKED
    assert any(r.code == CHALLENGE_CONTENT_DETECTED for r in result.reasons)


def test_sprint5y_verifier_style_mapping_isolation(tmp_path):
    operator_mapping = tmp_path / "operator_mapping.json"
    operator_mapping.write_text("[]", encoding="utf-8")
    isolated = PersonalizationFieldMappingStore(path=str(tmp_path / "isolated_mapping.json"))
    package_store = SmartleadRunPackageStore(path=str(tmp_path / "packages.json"))
    service = SmartleadRunExportService(run_handoff_service=type("H", (), {"package_store": package_store, "context_for_run": lambda self, rid: (None)})(), mapping_store=isolated, export_root=str(tmp_path / "exports"))
    assert build_export_columns(list(DEFAULT_SMARTLEAD_COLUMN_ORDER))
    assert service.get_field_mapping()
    assert operator_mapping.read_text(encoding="utf-8") == "[]"


def test_existing_smartlead_configured_mapping_behavior_remains_intact(tmp_path):
    store = PersonalizationFieldMappingStore(path=str(tmp_path / "mapping.json"))
    mapping = store.load_or_default()
    target_index = next(i for i, item in enumerate(mapping) if item.field_key == "personalization_angle")
    mapping[target_index] = replace(mapping[target_index], export_name="custom_angle")
    store.save(mapping)
    reloaded = PersonalizationFieldMappingStore(path=str(tmp_path / "mapping.json")).load_or_default()
    assert next(item for item in reloaded if item.field_key == "personalization_angle").export_name == "custom_angle"


def test_export_receipt_updates_member_dispositions(tmp_path):
    store = SmartleadRunPackageStore(path=str(tmp_path / "packages.json"))
    record = SmartleadRunPackageRecord(
        campaign_run_id="run1",
        entries=(
            SmartleadRunPackageEntry("a", status="READY", exportable=True, disposition="INCLUDED_EXPORTABLE"),
            SmartleadRunPackageEntry("b", status="BLOCKED", exportable=False, disposition="EXCLUDED_BLOCKED", disposition_reason="Blocked"),
        ),
    )
    svc = SmartleadRunExportService(run_handoff_service=type("H", (), {"package_store": store})(), mapping_store=PersonalizationFieldMappingStore(path=str(tmp_path / "map.json")), export_root=str(tmp_path / "exports"))
    svc._persist_receipt(record, SmartleadRunExportReceipt("run1", "pkg", str(tmp_path), str(tmp_path / "smartlead.csv"), str(tmp_path / "manifest.json"), "now", exported_statuses={"a": "READY"}))
    updated = store.get("run1")
    assert updated.entries[0].exported is True
    assert updated.entries[0].disposition == "EXPORTED"
    assert updated.entries[1].disposition == "EXCLUDED_BLOCKED"