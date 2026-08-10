"""Sprint 5A prospect test suite (model, normalization, dedup, store).

Covers the receive criteria from the Sprint 5A brief for the domain layer.
Filesystem tests use ``tmp_path`` and never touch the real ``output/prospects``
directory. Independence tests assert the model/store modules never import Qt or
scraper modules and perform no I/O during normalization.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from gui.models.prospect import (
    STATUS_ARCHIVED,
    STATUS_DISQUALIFIED,
    STATUS_IMPORTED,
    STATUS_NEW,
    STATUS_READY_FOR_RESEARCH,
    STATUS_RESEARCHED,
    Contact,
    DEDUP_EXACT,
    DEDUP_POSSIBLE,
    DEDUP_UNIQUE,
    PROSPECT_STATUSES,
    Prospect,
    ProspectDeduplicator,
    company_key,
    filesystem_safe_id,
    is_valid_email,
    is_valid_phone,
    is_valid_website,
    normalize_category,
    normalize_company_name,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_state,
    normalize_tags,
    normalize_website,
)
from gui.models.prospect_store import (
    DEFAULT_PROSPECTS_PATH,
    ProspectCollection,
    ProspectCorruptionError,
    ProspectError,
    ProspectStore,
    SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prospect(**kw) -> Prospect:
    base = dict(company_name="Castle Rock Realty", website="castlerockrealty.com")
    base.update(kw)
    return Prospect(**base)


def _store(tmp_path) -> ProspectStore:
    return ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))


# ---------------------------------------------------------------------------
# MODEL
# ---------------------------------------------------------------------------

class TestProspectModel:
    def test_minimal_construction(self) -> None:
        p = Prospect()
        assert p.prospect_id
        assert p.company_name == ""
        assert p.status == STATUS_NEW

    def test_prospect_construction(self) -> None:
        p = _prospect(city="Castle Rock", state="CO", category="Realtor")
        assert p.company_name == "Castle Rock Realty"
        assert p.city == "Castle Rock"
        assert p.state == "CO"

    def test_unique_ids(self) -> None:
        ids = [filesystem_safe_id("prospect") for _ in range(200)]
        assert len(set(ids)) == len(ids)

    def test_filesystem_json_safe_ids(self) -> None:
        uid = filesystem_safe_id("prospect")
        assert re.fullmatch(r"prospect_[0-9a-f-]+", uid)
        assert os.path.basename(uid) == uid

    def test_serialization_round_trip(self) -> None:
        p = _prospect(
            city="Sioux Falls",
            state="SD",
            tags=["roofing", "local"],
            notes="hello",
            contacts=[Contact(name="Jim", is_primary=True)],
        )
        restored = Prospect.from_dict(p.to_dict())
        assert restored.to_dict() == p.to_dict()

    def test_unknown_fields_ignored(self) -> None:
        d = _prospect().to_dict()
        d["some_unknown_future_field"] = "x"
        restored = Prospect.from_dict(d)
        assert not hasattr(restored, "some_unknown_future_field")
        assert restored.company_name == d["company_name"]

    def test_missing_optional_fields_safe(self) -> None:
        restored = Prospect.from_dict({"prospect_id": "p1", "company_name": "ABC"})
        assert restored.city == ""
        assert restored.email == ""
        assert restored.tags == []
        assert restored.metadata == {}
        assert restored.status == STATUS_NEW

    def test_status_validation_valid_statuses(self) -> None:
        for status in PROSPECT_STATUSES:
            p = _prospect(status=status)
            assert p.status == status

    def test_status_validation_unknown_defaults(self) -> None:
        p = Prospect.from_dict(_prospect().to_dict() | {"status": "NOT_A_STATUS"})
        assert p.status == STATUS_NEW

    def test_prospect_is_ready_for_research(self) -> None:
        assert _prospect(website="example.com").is_ready_for_research() is True
        assert _prospect(domain="example.com", website="").is_ready_for_research() is True
        assert _prospect(website="", domain="").is_ready_for_research() is False

    def test_contact_behavior(self) -> None:
        p = _prospect()
        contact = Contact(name="Jane", title="Owner", is_primary=True)
        p.contacts.append(contact)
        assert p.primary_contact.name == "Jane"
        p2 = _prospect()
        p2.contacts.append(Contact(name="First"))
        p2.contacts.append(Contact(name="Second"))
        assert p2.primary_contact.name == "First"
        assert _prospect().primary_contact is None

    def test_contact_round_trip(self) -> None:
        c = Contact(name="Jim", email="j@x.com", is_primary=True)
        assert Contact.from_dict(c.to_dict()).to_dict() == c.to_dict()
# ---------------------------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_website_normalization_adds_scheme_and_lowercases(self) -> None:
        assert normalize_website("WWW.Example.Com") == "https://www.example.com"

    def test_website_normalization_handles_pathless_trailing_slash(self) -> None:
        assert normalize_website("Example.com/") == "https://example.com"

    def test_website_normalization_keeps_https(self) -> None:
        assert normalize_website("https://sub.domain.org") == "https://sub.domain.org"

    def test_website_normalization_blank(self) -> None:
        assert normalize_website("") == ""
        assert normalize_website(None) == ""

    def test_domain_normalization(self) -> None:
        assert normalize_domain("https://www.JimWoodsRoofing.com") == "jimwoodsroofing.com"
        assert normalize_domain("jimwoodsroofing.com") == "jimwoodsroofing.com"

    def test_domain_blank(self) -> None:
        assert normalize_domain("") == ""

    def test_email_normalization_lowercases_domain(self) -> None:
        assert normalize_email("Jim@Example.COM") == "jim@example.com"

    def test_email_normalization_strips_spaces(self) -> None:
        assert normalize_email(" j@x.com ") == "j@x.com"

    def test_phone_normalization_to_digits(self) -> None:
        assert normalize_phone("(605) 764-9517") == "6057649517"
        assert normalize_phone("+1 605-764-9517") == "16057649517"
        assert normalize_phone("") == ""

    def test_category_normalization(self) -> None:
        assert normalize_category("  Roofing  ") == "roofing"

    def test_tags_normalization(self) -> None:
        assert normalize_tags("Roofing, roofing, local") == ["Roofing", "local"]
        assert normalize_tags(["a", "b", "a"]) == ["a", "b"]
        assert normalize_tags("") == []

    def test_state_normalization(self) -> None:
        assert normalize_state("co") == "CO"
        assert normalize_state("Colorado") == "CO"
        assert normalize_state("ZZ") == ""

    def test_company_normalization_not_over_normalized(self) -> None:
        assert normalize_company_name("  Jim    Woods   Roofing  ") == "Jim Woods Roofing"
        assert company_key("Wendys LLC") == "wendys llc"


# ---------------------------------------------------------------------------
# DEDUP
# ---------------------------------------------------------------------------

class TestDedup:
    def test_same_domain_duplicate_exact(self) -> None:
        a = _prospect(website="www.jimwoodsroofing.com")
        b = _prospect(website="https://JIMWOODSROOFING.com")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_EXACT

    def test_same_website_duplicate(self) -> None:
        a = _prospect(website="https://x.com")
        b = _prospect(website="https://x.com")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_EXACT

    def test_same_email_duplicate(self) -> None:
        a = _prospect(company_name="A", email="j@x.com")
        b = _prospect(company_name="B", email="J@X.COM")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_EXACT

    def test_same_phone_duplicate(self) -> None:
        a = _prospect(company_name="A", phone="(605) 764-9517")
        b = _prospect(company_name="B", phone="605-764-9517")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_EXACT

    def test_company_city_fallback_possible(self) -> None:
        a = _prospect(website="", company_name="Castle Rock Realty", city="Castle Rock", state="CO")
        b = _prospect(website="", company_name="CASTLE ROCK REALTY", city="Castle Rock", state="CO")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_POSSIBLE

    def test_fuzzy_company_only_not_auto_merged(self) -> None:
        a = _prospect(website="", company_name="Jim Woods Roofing")
        b = _prospect(website="", company_name="Jim W Roofing", city="Denver")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_UNIQUE

    def test_blank_values_do_not_create_false_duplicate(self) -> None:
        a = _prospect(company_name="A", website="", email="", phone="")
        b = _prospect(company_name="B", website="", email="", phone="")
        assert ProspectDeduplicator.compare(a, b) == DEDUP_UNIQUE


class TestMerge:
    def test_merge_preserves_id(self, tmp_path) -> None:
        s = _store(tmp_path)
        existing = _prospect(prospect_id="existing_id", website="x.com")
        s.create(existing)
        incoming = _prospect(prospect_id="new_id", website="x.com", phone="999")
        merged = s.merge(existing, incoming)
        assert merged.prospect_id == "existing_id"

    def test_merge_fills_missing_fields(self, tmp_path) -> None:
        s = _store(tmp_path)
        existing = _prospect(website="x.com", phone="")
        s.create(existing)
        incoming = _prospect(website="x.com", phone="6057649517")
        merged = s.merge(existing, incoming)
        assert merged.phone == "6057649517"

    def test_merge_does_not_overwrite_with_blanks(self, tmp_path) -> None:
        s = _store(tmp_path)
        existing = _prospect(website="x.com", phone="1112223333")
        s.create(existing)
        incoming = _prospect(website="x.com", phone="")
        merged = s.merge(existing, incoming)
        assert merged.phone == "1112223333"

    def test_merge_tags_union(self, tmp_path) -> None:
        s = _store(tmp_path)
        existing = _prospect(website="x.com", tags=["roofing", "local"])
        s.create(existing)
        incoming = _prospect(website="x.com", tags=["Roofing", "new"])
        merged = s.merge(existing, incoming)
        assert {t.lower() for t in merged.tags} == {"roofing", "local", "new"}
# ---------------------------------------------------------------------------
# STORE
# ---------------------------------------------------------------------------

class TestStore:
    def test_save_load(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(company_name="A", website="a.com"))
        s.save()
        s2 = _store(tmp_path)
        s2.load()
        assert len(s2.list()) == 1

    def test_atomic_save_no_tmp_left(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect())
        s.save()
        entries = os.listdir(tmp_path)
        assert "prospects.json" in entries
        assert not any(e.endswith(".tmp") for e in entries)

    def test_corrupted_json(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect())
        s.save()
        with open(s.path, "w", encoding="utf-8") as f:
            f.write("{ not json !")
        with pytest.raises(ProspectError):
            s.load()

    def test_missing_store_raises(self, tmp_path) -> None:
        s = _store(tmp_path)
        with pytest.raises(FileNotFoundError):
            s.load()

    def test_deterministic_list(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="z", company_name="Z"))
        s.create(_prospect(prospect_id="a", company_name="A"))
        ids = [p.prospect_id for p in s.list()]
        assert ids == sorted(ids)

    def test_filter_by_status(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="x1", status=STATUS_READY_FOR_RESEARCH))
        s.create(_prospect(prospect_id="x2", status=STATUS_DISQUALIFIED))
        got = s.collection.by_status(STATUS_READY_FOR_RESEARCH)
        assert [p.prospect_id for p in got] == ["x1"]

    def test_filter_by_category(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="c1", category="Roofing"))
        s.create(_prospect(prospect_id="c2", category="Dental"))
        assert [p.prospect_id for p in s.collection.by_category("roofing")] == ["c1"]

    def test_find_by_domain(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="d1", website="www.jimwoodsroofing.com"))
        found = s.collection.find_by_domain("jimwoodsroofing.com")
        assert found is not None and found.prospect_id == "d1"

    def test_find_by_email(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="e1", email="j@x.com"))
        found = s.collection.find_by_email("J@X.com")
        assert found is not None and found.prospect_id == "e1"

    def test_find_by_phone(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="p1", phone="(605) 764-9517"))
        found = s.collection.find_by_phone("605-764-9517")
        assert found is not None and found.prospect_id == "p1"

    def test_archive_persists(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="arch", website="a.com"))
        s.archive("arch")
        s.save()
        s2 = _store(tmp_path)
        s2.load()
        assert s2.get("arch").status == STATUS_ARCHIVED

    def test_reload_equivalent(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect(prospect_id="r1", company_name="Reload Co", tags=["t"]))
        s.save()
        s2 = _store(tmp_path)
        s2.load()
        assert s2.get("r1").company_name == "Reload Co"
        assert s2.get("r1").tags == ["t"]

    def test_schema_version_present(self, tmp_path) -> None:
        s = _store(tmp_path)
        s.create(_prospect())
        s.save()
        with open(s.path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == SCHEMA_VERSION

    def test_default_prospects_path_is_git_ignored(self) -> None:
        rel = os.path.relpath(DEFAULT_PROSPECTS_PATH)
        assert rel.startswith("output" + os.sep)
# ---------------------------------------------------------------------------
# ADVERSARIAL
# ---------------------------------------------------------------------------

class TestAdversarial:
    def test_from_dict_non_dict_safe(self) -> None:
        assert Prospect.from_dict(None).company_name == ""
        assert Prospect.from_dict("oops").company_name == ""
        assert Contact.from_dict(42).name == ""

    def test_collection_from_dict_non_dict_raises(self) -> None:
        with pytest.raises(ProspectError):
            ProspectCollection.from_dict("not-a-dict")

    def test_no_pickle_usage(self) -> None:
        import gui.models.prospect_store as s
        src = open(s.__file__, encoding="utf-8").read()
        assert "import pickle" not in src
        assert "import dill" not in src


# ---------------------------------------------------------------------------
# INDEPENDENCE
# ---------------------------------------------------------------------------

class TestIndependence:
    def test_prospect_model_no_gui_dependency(self) -> None:
        import gui.models.prospect as m
        src = open(m.__file__, encoding="utf-8").read()
        assert "PySide6" not in src
        assert "gui.services" not in src
        assert "gui.views" not in src
        assert "gui.widgets" not in src

    def test_prospect_model_no_scraper_dependency(self) -> None:
        import gui.models.prospect as m
        import gui.models.prospect_store as st
        for mod in (m, st):
            src = open(mod.__file__, encoding="utf-8").read()
            assert "engine.scraper" not in src
            assert "from scraper" not in src
            assert "import requests" not in src
            assert "urllib.request" not in src
            assert "import urllib" not in src

    def test_prospect_import_makes_no_web_requests(self) -> None:
        import gui.services.prospect_csv_import as imp
        src = open(imp.__file__, encoding="utf-8").read()
        assert "import requests" not in src
        assert "urllib.request" not in src
        assert "import urllib" not in src
        assert "scrape" not in src.lower()
        assert "WebsiteScraper" not in src


def test_validation_helpers() -> None:
    assert is_valid_email("j@x.com") is True
    assert is_valid_email("bad") is False
    assert is_valid_phone("6057649517") is True
    assert is_valid_phone("123") is False
    assert is_valid_website("https://x.com") is True
    assert is_valid_website("not a url") is False