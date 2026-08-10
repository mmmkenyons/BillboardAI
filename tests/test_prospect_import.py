"""Sprint 5A CSV prospect import test suite.

Tests the Qt-free :class:`~gui.services.prospect_csv_import.ProspectCsvImporter`
directly (mapping, normalization, validation, dedup/merge, error handling,
encoding) plus the matching :class:`~gui.services.prospect_workspace.ProspectWorkspaceService`
import orchestration. Filesystem tests use ``tmp_path`` and never touch the
real ``output/prospects`` directory. No web requests are ever made.
"""

from __future__ import annotations

import os

import pytest

from gui.models.prospect import STATUS_IMPORTED, STATUS_READY_FOR_RESEARCH
from gui.models.prospect_store import ProspectStore
from gui.services.prospect_csv_import import (
    ProspectCsvImporter,
    ProspectImportError,
    detect_mapping,
)
from gui.services.prospect_workspace import ProspectWorkspaceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _importer(tmp_path) -> ProspectCsvImporter:
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    return ProspectCsvImporter(store)


def _csv(*rows: str) -> str:
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

class TestCsvImport:
    def test_normal_csv_import(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "company,website,phone,city,state",
            "Jim Woods Roofing,www.jimwoodsroofing.com,6057649517,Sioux Falls,SD",
            "ABC Dental,abcdental.com,,Castle Rock,CO",
        )
        result = imp.import_text(text)
        assert result.imported == 2
        assert result.rows_total == 2
        prospects = imp._store.list()
        assert len(prospects) == 2
        jim = next(p for p in prospects if p.company_name == "Jim Woods Roofing")
        dental = next(p for p in prospects if p.company_name == "ABC Dental")
        assert jim.domain == "jimwoodsroofing.com"
        assert jim.status == STATUS_READY_FOR_RESEARCH
        assert dental.status == STATUS_READY_FOR_RESEARCH

    def test_alias_headers(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "business_name,url,phone_number,email_address,industry,zip",
            "Jim Woods Roofing,jimwoodsroofing.com,6057649517,j@x.com,Roofing,57104",
        )
        result = imp.import_text(text)
        assert result.imported == 1
        p = imp._store.list()[0]
        assert p.company_name == "Jim Woods Roofing"
        assert p.domain == "jimwoodsroofing.com"
        assert p.category == "roofing"
        assert p.postal_code == "57104"

    def test_missing_optional_fields(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company", "Jim Woods Roofing")
        result = imp.import_text(text)
        assert result.imported == 1
        p = imp._store.list()[0]
        assert p.website == ""
        assert p.status == STATUS_IMPORTED
        assert p.is_ready_for_research() is False

    def test_missing_company_invalid(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company,website", ",example.com")
        result = imp.import_text(text)
        assert result.invalid == 1
        assert result.imported == 0
        assert imp._store.list() == []

    def test_unknown_columns_preserved_in_metadata(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company,website,some_extra_col", "Jim,example.com,keepme")
        result = imp.import_text(text)
        assert result.imported == 1
        p = imp._store.list()[0]
        assert p.metadata.get("raw_some_extra_col") == "keepme"

    def test_invalid_email_row_handled(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company,email", "Jim,bademail")
        result = imp.import_text(text)
        assert result.invalid == 1
        assert result.imported == 0

    def test_invalid_url_row_handled(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company,website", "Jim,not a valid url")
        result = imp.import_text(text)
        assert result.invalid == 1

    def test_blank_row_skipped(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "company,website",
            "Jim,example.com",
            ",",
            "Bob,bob.com",
        )
        result = imp.import_text(text)
        assert result.skipped == 1
        assert result.imported == 2
    def test_duplicate_merge(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "company,website,phone",
            "Jim,www.jimwoodsroofing.com,6057649517",
            "Jim Woods Roofing,jimwoodsroofing.com,9998887777",
        )
        result = imp.import_text(text)
        assert result.imported == 1
        assert result.merged == 1
        assert len(imp._store.list()) == 1
        p = imp._store.list()[0]
        assert p.phone == "6057649517"

    def test_possible_duplicate_reported(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "company,city,state",
            "Castle Rock Realty,Castle Rock,CO",
            "CASTLE ROCK REALTY,Castle Rock,CO",
        )
        result = imp.import_text(text)
        assert result.imported == 2  # both imported (not auto-merged)
        assert len(imp._store.list()) == 2
        second = [r for r in result.rows if r.status == "imported"][-1]
        assert "possible duplicate" in second.message

    def test_import_result_counts_correct(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "company,website",
            "Jim,example.com",
            "Bob,bob.com",
            ",bad.com",
        )
        result = imp.import_text(text)
        assert result.rows_total == 3
        assert result.imported == 2
        assert result.invalid == 1
        assert result.skipped == 0

    def test_row_numbers_correct(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv(
            "company,website",
            "Jim,example.com",
            ",bad.com",
        )
        result = imp.import_text(text)
        assert result.rows[0].row_number == 2
        assert result.rows[1].row_number == 3

    def test_bad_csv_encoding_fallback(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        raw = b"company,website\nJim\xe9,example.com\n"
        result = imp.import_bytes(raw)
        assert result.imported == 1

    def test_empty_csv(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        with pytest.raises(ProspectImportError):
            imp.import_text("")

    def test_header_only_csv(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company,website")
        result = imp.import_text(text)
        assert result.rows_total == 0
        assert result.imported == 0

    def test_utf8_bom_handled(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        raw = b"\xef\xbb\xbfcompany,website\nJim,example.com\n"
        result = imp.import_bytes(raw)
        assert result.imported == 1
        assert result.mapping.get("company_name") == "company"

    def test_duplicate_headers_first_wins(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("company,company,website", "A,B,example.com")
        result = imp.import_text(text)
        assert result.imported == 1
        p = imp._store.list()[0]
        assert p.company_name == "A"

    def test_no_company_column_raises(self, tmp_path) -> None:
        imp = _importer(tmp_path)
        text = _csv("website,phone", "example.com,1234567890")
        with pytest.raises(ProspectImportError):
            imp.import_text(text)

    def test_detect_mapping_reports_before_import(self, tmp_path) -> None:
        mapping = detect_mapping(["company", "website", "phone", "random"])
        assert mapping["company_name"] == "company"
        assert mapping["website"] == "website"
        assert mapping["phone"] == "phone"
        assert "random" not in mapping


# ---------------------------------------------------------------------------
# SERVICE IMPORT
# ---------------------------------------------------------------------------

class TestWorkspaceImport:
    def _service(self, tmp_path) -> ProspectWorkspaceService:
        return ProspectWorkspaceService(
            store=ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
        )

    def test_import_via_service_persists(self, tmp_path) -> None:
        svc = self._service(tmp_path)
        svc.load()
        text = _csv("company,website", "Jim,example.com", "Bob,bob.com")
        result = svc.import_csv(text)
        assert result.imported == 2
        svc2 = self._service(tmp_path)
        svc2.load()
        assert len(svc2.list_prospects()) == 2

    def test_no_project_auto_created(self, tmp_path) -> None:
        svc = self._service(tmp_path)
        svc.load()
        text = _csv("company,website", "Jim,example.com")
        svc.import_csv(text)
        with pytest.raises(NotImplementedError):
            svc.create_project_from_prospect("whatever")
    def test_bad_csv_file_path(self, tmp_path) -> None:
        imp = ProspectCsvImporter(ProspectStore(path=os.path.join(str(tmp_path), "p.json")))
        missing = os.path.join(str(tmp_path), "does_not_exist.csv")
        with pytest.raises(ProspectImportError):
            imp.import_file(missing)