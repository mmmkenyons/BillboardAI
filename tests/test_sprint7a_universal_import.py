from __future__ import annotations

import os

from gui.models.prospect_store import ProspectStore
from gui.models.prospect import normalize_website
from gui.services.prospect_csv_import import (
    MAPPING_ALIAS,
    MAPPING_AMBIGUOUS,
    MAPPING_EXACT,
    MAPPING_UNMAPPED,
    ProspectCsvImporter,
    classification_evidence,
    detect_mapping,
    detect_mapping_details,
    select_creative_company_name,
    select_creative_phone,
)


def _store(tmp_path) -> ProspectStore:
    return ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))


def _import_text(tmp_path, text: str):
    store = _store(tmp_path)
    result = ProspectCsvImporter(store).import_text(text)
    return result, store.list()


def test_alias_statuses_and_ambiguity() -> None:
    preview = detect_mapping_details(["company_name", "Office Phone", "Favorite Color", "LinkedIn"])
    statuses = {d.source_column: d.status for d in preview.columns}
    assert statuses["company_name"] == MAPPING_EXACT
    assert statuses["Office Phone"] == MAPPING_ALIAS
    assert statuses["Favorite Color"] == MAPPING_UNMAPPED
    assert statuses["LinkedIn"] == MAPPING_AMBIGUOUS
    assert "company_phone" in detect_mapping(["Office Phone"])


def test_company_display_phone_email_website_and_classification(tmp_path) -> None:
    text = "\n".join([
        "Company name,Company name for emails,Email,Mobile phone,Corporate phone,Website,NAICS codes,Keywords,Industry,Favorite color",
        "T2 Roofing LLC,T2 Roofing, owner@t2roof.example ,303-555-0101,303-555-0199,www.t2roofing.example/,238160 - Roofing Contractors,storm damage; roof replacement,Construction,blue",
    ])
    result, prospects = _import_text(tmp_path, text)
    assert result.imported == 1
    p = prospects[0]
    assert p.company_name == "T2 Roofing LLC"
    assert p.company_name_for_ads == "T2 Roofing"
    assert select_creative_company_name(p) == "T2 Roofing"
    creative_phone = select_creative_phone(p)
    assert creative_phone["phone"] == "3035550199"
    assert creative_phone["source_field"] == "company_phone"
    assert p.mobile_phone == "3035550101"
    assert p.email == "owner@t2roof.example"
    assert p.metadata["email_state"]["email_enrichment_eligible"] is False
    assert p.website == "https://www.t2roofing.example"
    assert p.naics_codes == ["238160"]
    assert classification_evidence(p)["basis"] == "naics_codes"
    assert p.metadata["source_unmapped"]["Favorite color"] == "blue"
    assert p.metadata["field_provenance"]["company_phone"]["origin"] == "IMPORTED"


def test_blank_email_missing_website_and_keywords_precedence_survive_reload(tmp_path) -> None:
    store = _store(tmp_path)
    text = "\n".join([
        "Company name,Email,Keywords,Industry,Unknown",
        "No Site Co,,roofing; gutters,Construction,kept",
    ])
    result = ProspectCsvImporter(store).import_text(text)
    assert result.imported == 1
    store.save()
    loaded = ProspectStore(path=store.path)
    loaded.load()
    p = loaded.list()[0]
    assert p.website == ""
    assert p.status == "IMPORTED"
    assert p.email == ""
    assert p.metadata["email_state"]["status"] == "email_missing"
    assert p.metadata["email_state"]["email_enrichment_eligible"] is True
    assert classification_evidence(p)["basis"] == "company_keywords"
    assert p.metadata["source_unmapped"]["Unknown"] == "kept"
    assert "field_provenance" in p.metadata


def test_apollo_and_generic_equivalent_and_no_destructive_duplicate_merge(tmp_path) -> None:
    fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    apollo = open(os.path.join(fixture_dir, "sprint7a_apollo.csv"), encoding="utf-8").read()
    generic = open(os.path.join(fixture_dir, "sprint7a_generic.csv"), encoding="utf-8").read()
    apollo_store = _store(tmp_path / "apollo")
    generic_store = _store(tmp_path / "generic")
    apollo_result = ProspectCsvImporter(apollo_store).import_text(apollo)
    generic_result = ProspectCsvImporter(generic_store).import_text(generic)
    assert apollo_result.imported == 3
    assert generic_result.imported == 1
    a = next(p for p in apollo_store.list() if p.company_name == "T2 Roofing LLC")
    g = generic_store.list()[0]
    assert a.company_name == g.company_name
    assert a.company_name_for_ads == g.company_name_for_ads
    assert a.company_phone == g.company_phone
    assert a.mobile_phone == g.mobile_phone
    assert a.naics_codes == g.naics_codes
    assert a.company_keywords == g.company_keywords
    assert "Favorite color" in a.metadata["source_unmapped"]

    dup_text = "Company name,Website,Email\nT2 Changed,t2roofing.example,new@t2roof.example"
    dup_result = ProspectCsvImporter(apollo_store).import_text(dup_text)
    assert dup_result.merged == 1
    retained = next(p for p in apollo_store.list() if p.domain == "t2roofing.example")
    assert retained.company_name == "T2 Roofing LLC"


def test_manual_mapping_override(tmp_path) -> None:
    text = "Biz,Phone-ish\nMapped Co,303-555-7777"
    store = _store(tmp_path)
    result = ProspectCsvImporter(store).import_text(text, mapping={"company_name": "Biz", "company_phone": "Phone-ish"})
    assert result.imported == 1
    p = store.list()[0]
    assert p.company_name == "Mapped Co"
    assert p.company_phone == "3035557777"


def test_website_normalization_preserves_meaningful_path_query() -> None:
    assert normalize_website("Example.com/path/?utm=kept") == "https://example.com/path/?utm=kept"
    assert normalize_website("www.example.com/") == "https://www.example.com"