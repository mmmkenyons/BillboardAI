from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.prospect_store import ProspectStore
from gui.services.prospect_csv_import import (
    MAPPING_AMBIGUOUS,
    MAPPING_UNMAPPED,
    ProspectCsvImporter,
    classification_evidence,
    detect_mapping_details,
    select_creative_company_name,
    select_creative_phone,
)


def check(name: str, condition: bool, failures: list[str]) -> None:
    print(("PASS" if condition else "FAIL") + f" {name}")
    if not condition:
        failures.append(name)


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        apollo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "fixtures", "sprint7a_apollo.csv")
        generic_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "fixtures", "sprint7a_generic.csv")
        apollo_text = open(apollo_path, encoding="utf-8").read()
        generic_text = open(generic_path, encoding="utf-8").read()

        preview = detect_mapping_details(apollo_text.splitlines()[0].split(","))
        mapping = preview.mapping
        statuses = {d.source_column: d.status for d in preview.columns}
        check("1 Apollo-style headers recognized", "company_name" in mapping and "naics_codes" in mapping, failures)
        generic_preview = detect_mapping_details(generic_text.splitlines()[0].split(","))
        generic_mapping = generic_preview.mapping
        check("2 generic aliases recognized", generic_mapping.get("company_name") == "Business" and generic_mapping.get("company_phone") == "Office Phone", failures)
        check("3 unknown headers remain unmapped", any(d.source_column == "Mystery Column" and d.status == MAPPING_UNMAPPED for d in generic_preview.columns), failures)
        check("4 ambiguous headers are not silently guessed", any(d.status == MAPPING_AMBIGUOUS for d in detect_mapping_details(["LinkedIn"]).columns), failures)

        store = ProspectStore(path=os.path.join(tmp, "apollo.json"))
        result = ProspectCsvImporter(store).import_text(apollo_text)
        prospects = store.list()
        t2 = next(p for p in prospects if p.company_name == "T2 Roofing LLC")
        blank = next(p for p in prospects if p.company_name == "Blank Email Roofing")
        nosite = next(p for p in prospects if p.company_name == "Structured Leads LLC")
        check("5 company_name preserved", t2.company_name == "T2 Roofing LLC", failures)
        check("6 company_name_for_ads/display preserved separately", t2.company_name_for_ads == "T2 Roofing", failures)
        check("7 creative company-name precedence works", select_creative_company_name(t2) == "T2 Roofing", failures)
        phone = select_creative_phone(t2)
        check("8 company phone outranks mobile for billboard creative", phone["source_field"] == "company_phone" and phone["phone"] == t2.company_phone, failures)
        check("9 phone provenance/type retained", t2.metadata["creative_phone"]["source_field"] == "company_phone", failures)
        check("10 NAICS outranks keywords/industry for classification evidence", classification_evidence(t2)["basis"] == "naics_codes", failures)
        no_naics_store = ProspectStore(path=os.path.join(tmp, "kw.json"))
        ProspectCsvImporter(no_naics_store).import_text("Company name,Keywords,Industry\nK,roofing;gutters,Construction")
        check("11 keywords outrank broad industry when NAICS absent", classification_evidence(no_naics_store.list()[0])["basis"] == "company_keywords", failures)
        check("12 supplied email preserved", t2.email == "ana@t2roof.example", failures)
        check("13 blank email remains blank", blank.email == "", failures)
        check("14 blank email is eligible for future enrichment", blank.metadata["email_state"]["email_enrichment_eligible"] is True, failures)
        check("15 supplied email is not unnecessarily marked for enrichment", t2.metadata["email_state"]["email_enrichment_eligible"] is False, failures)
        check("16 website normalization works", t2.website.startswith("https://") and t2.domain == "t2roofing.example", failures)
        check("17 missing website does not block prospect creation", nosite.website == "" and nosite.status == "IMPORTED", failures)
        store.save(); loaded = ProspectStore(path=store.path); loaded.load(); t2_loaded = next(p for p in loaded.list() if p.company_name == "T2 Roofing LLC")
        check("18 unmapped source fields survive serialization/reload", t2_loaded.metadata["source_unmapped"].get("Favorite color") == "blue", failures)
        check("19 provenance survives serialization/reload", t2_loaded.metadata["field_provenance"]["company_name"]["origin"] == "IMPORTED", failures)
        generic_store = ProspectStore(path=os.path.join(tmp, "generic.json"))
        ProspectCsvImporter(generic_store).import_text(generic_text)
        g = generic_store.list()[0]
        check("20 Apollo and generic CSV can normalize to equivalent canonical fields", (t2.company_name, t2.company_phone, t2.mobile_phone, t2.naics_codes) == (g.company_name, g.company_phone, g.mobile_phone, g.naics_codes), failures)
        before_id = t2.prospect_id
        dup = ProspectCsvImporter(store).import_text("Company name,Website,Email\nChanged Name,t2roofing.example,new@example.com")
        t2_after = next(p for p in store.list() if p.prospect_id == before_id)
        check("21 no duplicate destructive merge", dup.merged == 1 and t2_after.company_name == "T2 Roofing LLC", failures)
        check("22 import has no generation side effects", not any("generation" in k for p in store.list() for k in p.metadata), failures)
        check("23 import has no publication side effects", not any("publication" in k for p in store.list() for k in p.metadata), failures)
        check("24 import has no Smartlead activation/upload side effects", not any("smartlead" in k.lower() for p in store.list() for k in p.metadata), failures)

    passed = 24 - len(failures)
    print(f"Sprint 7A verifier: PASS {passed}/24 FAIL {len(failures)}/24")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())