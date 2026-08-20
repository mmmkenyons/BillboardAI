"""Sprint 6D verifier -- Sprint 6C targeted re-acceptance remediation.

Deterministic, offline, and Qt-free. Covers the safety/throughput fixes that
protect real-world production re-acceptance without weakening wrong-person,
copy-quality, campaign, or Smartlead gates.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from gui.models.mockup_concept import MockupConcept  # noqa: E402
from gui.models.project import Project  # noqa: E402
from gui.models.prospect import RESOLUTION_AMBIGUOUS, RESOLUTION_ERROR, Prospect  # noqa: E402
from gui.models.smartlead_run_export import (  # noqa: E402
    SMARTLEAD_EXPORT_BLOCKED,
    SMARTLEAD_EXPORT_CONFLICT,
    SMARTLEAD_EXPORT_EXCLUDED,
    SMARTLEAD_EXPORT_READY,
    SMARTLEAD_EXPORT_WARNING,
    SmartleadRunExportReceipt,
)
from gui.models.smartlead_run_package import SmartleadRunPackageEntry, SmartleadRunPackageRecord  # noqa: E402
from gui.services.copy_quality import MISSING_CTA, MISSING_HEADLINE, QUALITY_BLOCKED, QUALITY_PASS, assess_copy_quality  # noqa: E402
from gui.services.profile_resolver import ProfileResolverService  # noqa: E402
from gui.services.smartlead_run_export import SmartleadRunExportService  # noqa: E402


PARENT = "https://example.com"


def check(name: str, condition: bool, counts: dict[str, int], detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + f": {name}{' - ' + detail if detail else ''}")
    counts["passed" if condition else "failed"] += 1


class _Row:
    def __init__(self, headline: str = "Trusted Local Care", cta: str = "Call Today", body: str = "A billboard for Example Realty.") -> None:
        self.headline = headline
        self.cta = cta
        self.email_subject = "Billboard idea"
        self.email_body = body
        self.personalization_basis = ""
        self.creative_summary = ""


def _concept(headline: str, cta: str = "Call Today") -> MockupConcept:
    return MockupConcept.create("mock.png", "contractor", headline, cta, 90, company_name="Example Realty")


def _prospect(**overrides) -> Prospect:
    data = dict(
        prospect_id="p1",
        company_name="Example Realty",
        website=PARENT,
        email="jane@example.com",
        contact_name="Jane Smith",
        category="real estate",
    )
    data.update(overrides)
    return Prospect(**data)


def _codes(result) -> set[str]:
    return {reason.code for reason in result.reasons}


def verify_resolver_deadline(counts: dict[str, int]) -> None:
    calls: list[str] = []

    def slow_fetch(url: str) -> str:
        calls.append(url)
        time.sleep(0.25)
        return "<urlset><url><loc>https://example.com/agents/jane-smith</loc></url></urlset>"

    service = ProfileResolverService(fetcher=slow_fetch, browser_fetcher=None, total_timeout=0.03)
    started = time.monotonic()
    result = service.resolve("Jane Smith", PARENT)
    elapsed = time.monotonic() - started
    check("resolver returns within total deadline", elapsed < 0.15, counts, f"elapsed={elapsed:.3f}s")
    check("resolver timeout is safe error", result.status == RESOLUTION_ERROR and result.url == "", counts, result.status)
    check("resolver timeout diagnostics present", str(result.diagnostics.get("timeout_reason", "")).startswith("TOTAL_RESOLUTION_TIMEOUT:"), counts)


def verify_person_and_copy_quality(counts: dict[str, int]) -> None:
    person_data = {
        "url": "https://example.com/agent/jane-smith",
        "company": "Example Realty",
        "headline": "Jane Smith | Example Realty",
        "ad_copy": "Jane Smith | Example Realty",
        "metadata": {"title": "Jane Smith | Example Realty"},
        "html": "<html><body><h1>Jane Smith</h1><p>18 years helping clients move.</p></body></html>",
        "business_intel": {"categories": ["real estate agent"]},
        "person_context": {"contact_name": "Jane Smith", "resolved_profile_url": "https://example.com/agent/jane-smith"},
    }
    profile = BrandProfileBuilder.from_scrape_data(person_data)
    check("person years fact extracted", profile.person_facts.years_experience == "18", counts, profile.person_facts.years_experience)
    check("person years provenance retained", bool(profile.person_facts.provenance.get("years_experience")), counts)

    with tempfile.TemporaryDirectory() as tmp:
        project = Project.create(output_root=tmp, name="person")
        project.update_from_pipeline(brand_profile=profile, concepts=[_concept(profile.personalized_headline, profile.personalized_cta)])
        supported = assess_copy_quality(
            prospect=_prospect(),
            concept=_concept("18 Years Helping Buyers Move"),
            project=project,
            row=_Row(headline="18 Years Helping Buyers Move"),
        )
        check("supported numeric copy passes", supported.status == QUALITY_PASS, counts, supported.status)

        unresolved = BrandProfileBuilder.from_scrape_data({
            "url": PARENT,
            "company": "Example Realty",
            "headline": "Example Realty",
            "ad_copy": "Homes Across Town",
            "html": "<html><body><h1>Our Team</h1><p>Bob Agent serves buyers.</p></body></html>",
            "person_context": {"contact_name": "Jane Smith", "resolution_status": RESOLUTION_AMBIGUOUS, "company_name": "Example Realty"},
        })
        check("unresolved intended person suppresses contact fact", unresolved.person_facts.contact_name == "", counts)
        check("unresolved intended person suppresses creative", unresolved.personalized_headline == "", counts)
        check("unresolved diagnostics present", unresolved.source_metadata["asset_selection_diagnostics"]["intended_person_unresolved"] is True, counts)

        blank = assess_copy_quality(
            prospect=_prospect(contact_name=""),
            concept=_concept(""),
            project=project,
            row=_Row(headline="", cta="Call Today"),
        )
        missing_cta = assess_copy_quality(
            prospect=_prospect(contact_name=""),
            concept=_concept("Trusted Local Care", ""),
            project=project,
            row=_Row(headline="Trusted Local Care", cta=""),
        )
        check("missing headline blocks", blank.status == QUALITY_BLOCKED and MISSING_HEADLINE in _codes(blank), counts)
        check("missing CTA blocks", missing_cta.status == QUALITY_BLOCKED and MISSING_CTA in _codes(missing_cta), counts)


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
        return type("Ctx", (), {"package_record": self.package_store.record, "campaign_name": "Verifier"})()


def verify_smartlead_warning_export(counts: dict[str, int]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        handoff = os.path.join(tmp, "handoff")
        os.makedirs(handoff, exist_ok=True)
        with open(os.path.join(handoff, "smartlead_preflight.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["prospect_id", "company", "email", "status", "reason", "warning"])
            writer.writeheader()
            writer.writerow({"prospect_id": "ready", "company": "Ready Co", "email": "r@example.com", "status": "READY", "reason": "", "warning": ""})
            writer.writerow({"prospect_id": "warn", "company": "Warn Co", "email": "w@example.com", "status": "WARNING", "reason": "", "warning": "minor"})
            writer.writerow({"prospect_id": "blocked", "company": "Blocked Co", "email": "b@example.com", "status": "BLOCKED", "reason": "bad", "warning": ""})
            writer.writerow({"prospect_id": "conflict", "company": "Conflict Co", "email": "c@example.com", "status": "CONFLICT", "reason": "duplicate", "warning": ""})
        with open(os.path.join(handoff, "smartlead.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["prospect_id", "company", "email", "mockup_path"])
            writer.writeheader()
            writer.writerow({"prospect_id": "ready", "company": "Ready Co", "email": "r@example.com", "mockup_path": "r.png"})
            writer.writerow({"prospect_id": "warn", "company": "Warn Co", "email": "w@example.com", "mockup_path": "w.png"})
        record = SmartleadRunPackageRecord(
            campaign_run_id="run-1",
            package_id="pkg-1",
            handoff_directory=handoff,
            smartlead_csv_path=os.path.join(handoff, "smartlead.csv"),
            entries=(
                SmartleadRunPackageEntry("ready", status="READY"),
                SmartleadRunPackageEntry("warn", status="WARNING"),
                SmartleadRunPackageEntry("blocked", status="BLOCKED"),
                SmartleadRunPackageEntry("conflict", status="CONFLICT"),
                SmartleadRunPackageEntry("excluded", status="EXCLUDED"),
            ),
        )
        run_handoff = _RunHandoff(record)
        result = SmartleadRunExportService(run_handoff_service=run_handoff, export_root=os.path.join(tmp, "exports")).export_run("run-1")
        statuses = {row.prospect_id: row.status for row in result.rows}
        expected_exported_statuses = {"ready": SMARTLEAD_EXPORT_READY, "warn": SMARTLEAD_EXPORT_WARNING}
        check("Smartlead warning remains exportable", result.success and result.exported_rows == 2 and statuses.get("warn") == SMARTLEAD_EXPORT_WARNING, counts, str(statuses))
        check(
            "Smartlead non-exportable statuses excluded",
            statuses.get("blocked") == SMARTLEAD_EXPORT_BLOCKED
            and statuses.get("conflict") == SMARTLEAD_EXPORT_CONFLICT
            and statuses.get("excluded") == SMARTLEAD_EXPORT_EXCLUDED
            and all(status not in result.receipt.exported_statuses.values() for status in (SMARTLEAD_EXPORT_BLOCKED, SMARTLEAD_EXPORT_CONFLICT, SMARTLEAD_EXPORT_EXCLUDED)),
            counts,
            str(statuses),
        )
        check("Smartlead receipt exposes exported statuses", result.receipt is not None and result.receipt.exported_statuses == expected_exported_statuses, counts)
        persisted = run_handoff.package_store.record.last_export
        check("Smartlead persisted receipt stores exported statuses", persisted.get("exported_statuses") == expected_exported_statuses, counts)
        check("Smartlead receipt reload preserves exported statuses", SmartleadRunExportReceipt.from_dict(persisted).exported_statuses == expected_exported_statuses, counts)
        reloaded_record = SmartleadRunPackageRecord.from_dict(run_handoff.package_store.record.to_dict())
        latest = SmartleadRunExportService(run_handoff_service=_RunHandoff(reloaded_record), export_root=os.path.join(tmp, "exports_reload")).latest_export("run-1")
        check("Smartlead reconstructed service returns exported statuses", latest is not None and latest.exported_statuses == expected_exported_statuses, counts)
        old_receipt = dict(persisted)
        old_receipt.pop("exported_statuses", None)
        check("Smartlead old receipts without exported statuses load safely", SmartleadRunExportReceipt.from_dict(old_receipt).exported_statuses == {}, counts)
        with open(result.manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        check("Smartlead manifest counts warning", manifest["receipt"]["warning"] == 1, counts)
        check("Smartlead manifest persists exported statuses", manifest["receipt"].get("exported_statuses") == expected_exported_statuses, counts)


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    verify_resolver_deadline(counts)
    verify_person_and_copy_quality(counts)
    verify_smartlead_warning_export(counts)
    print("SPRINT 6D VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())