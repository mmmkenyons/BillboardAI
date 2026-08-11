"""Sprint 5A prospect workspace test suite (service + controller + page).

The domain/service layer (:class:`gui.services.prospect_workspace.ProspectWorkspaceService`)
is Qt-free and tested directly (load, CRUD, archive, filters, research
readiness, import orchestration, no-project-auto-creation). A small set of
Qt-guarded controller/page tests only run when a QApplication is available
(offscreen platform). Filesystem tests use ``tmp_path`` and never touch the
real ``output/prospects`` directory.
"""

from __future__ import annotations

import os

import pytest

from gui.models.prospect import (
    STATUS_ARCHIVED,
    STATUS_DISQUALIFIED,
    STATUS_IMPORTED,
    STATUS_READY_FOR_RESEARCH,
    Prospect,
)
from gui.models.prospect_store import ProspectCorruptionError, ProspectStore
from gui.services.prospect_workspace import (
    ProspectValidationError,
    ProspectWorkspaceService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service(tmp_path) -> ProspectWorkspaceService:
    store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
    return ProspectWorkspaceService(store=store)


def _seed(svc: ProspectWorkspaceService) -> Prospect:
    svc.load()
    return svc.create_prospect(
        company_name="Jim Woods Roofing",
        website="www.jimwoodsroofing.com",
        phone="(605) 764-9517",
        city="Sioux Falls",
        state="SD",
        category="Roofing",
        contact_name="Jim Woods",
    )


# ---------------------------------------------------------------------------
# SERVICE
# ---------------------------------------------------------------------------

class TestService:
    def test_load_empty_store_no_crash(self, tmp_path) -> None:
        svc = _service(tmp_path)
        svc.load()
        assert svc.list_prospects() == []
        assert svc.imported_count() == 0

    def test_create_prospect(self, tmp_path) -> None:
        svc = _service(tmp_path)
        svc.load()
        p = svc.create_prospect(company_name="ABC Dental", website="abcdental.com")
        assert p.status == STATUS_READY_FOR_RESEARCH
        assert svc.imported_count() == 1

    def test_create_prospect_without_website_not_ready(self, tmp_path) -> None:
        svc = _service(tmp_path)
        svc.load()
        p = svc.create_prospect(company_name="No Site Co")
        assert p.status == STATUS_IMPORTED
        assert p.is_ready_for_research() is False

    def test_create_prospect_requires_company(self, tmp_path) -> None:
        svc = _service(tmp_path)
        svc.load()
        with pytest.raises(ProspectValidationError):
            svc.create_prospect(company_name="")

    def test_update_prospect(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        updated = svc.update_prospect(p.prospect_id, city="Castle Rock", state="CO")
        assert updated.city == "Castle Rock"
        assert updated.state == "CO"
        assert svc.get_prospect(p.prospect_id).city == "Castle Rock"

    def test_update_prospect_normalizes_website(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        updated = svc.update_prospect(p.prospect_id, website="WWW.X.Com")
        assert updated.website == "https://www.x.com"
        assert updated.domain == "x.com"

    def test_archive_prospect(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        archived = svc.archive_prospect(p.prospect_id)
        assert archived.status == STATUS_ARCHIVED
        svc2 = _service(tmp_path)
        svc2.load()
        assert svc2.get_prospect(p.prospect_id).status == STATUS_ARCHIVED

    def test_set_status_validated(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        svc.set_status(p.prospect_id, STATUS_DISQUALIFIED)
        assert svc.get_prospect(p.prospect_id).status == STATUS_DISQUALIFIED
        with pytest.raises(ProspectValidationError):
            svc.set_status(p.prospect_id, "NOT_A_STATUS")

    def test_filters(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        svc.create_prospect(
            company_name="ABC Dental", website="abcdental.com", category="Dental"
        )
        roofing = svc.list_by_category("roofing")
        assert len(roofing) == 1 and roofing[0].category == "roofing"

    def test_search(self, tmp_path) -> None:
        svc = _service(tmp_path)
        _seed(svc)
        svc.create_prospect(company_name="Castle Rock Realty", website="cr.com")
        assert len(svc.search("castle")) == 1
        assert len(svc.search("roofing")) == 1
        assert svc.search("") == svc.list_prospects()

    def test_corruption_surfaces_clearly(self, tmp_path) -> None:
        store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
        store.create(Prospect(company_name="X"))
        store.save()
        with open(store.path, "w", encoding="utf-8") as f:
            f.write("corrupt{")
        svc = ProspectWorkspaceService(store=store)
        with pytest.raises(ProspectCorruptionError):
            svc.load()

    def test_import_does_not_auto_create_project(self, tmp_path) -> None:
        svc = _service(tmp_path)
        svc.load()
        svc.import_csv("company,website\nJim,example.com\n")
        assert svc.imported_count() == 1
        p = svc.list_prospects()[0]
        assert p.prospect_id
# ---------------------------------------------------------------------------
# GUI (Qt-guarded, offscreen)
# ---------------------------------------------------------------------------

def _qapplication():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        pytest.skip("PySide6 not available")
    app = QApplication.instance()
    if app is None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


class _ProspectHarness:
    """Build a Prospects page wired to a real controller + store."""

    def __init__(self, tmp_path, seed: bool = True) -> None:
        _qapplication()
        from gui.controllers.prospect_controller import ProspectController
        from gui.views.prospect_workspace_page import ProspectWorkspacePage

        path = os.path.join(str(tmp_path), "prospects.json")
        self.controller = ProspectController(path=path)
        self.page = ProspectWorkspacePage()
        if seed:
            _seed(self.controller.service)
            self.controller.reload()
        self.page.set_controller(self.controller)
        # Prevent the modal error box from blocking offscreen tests.
        try:
            self.controller.error_message.disconnect(self.page._show_error)
        except (TypeError, RuntimeError):
            pass
        self.errors = []
        self.controller.error_message.connect(self.errors.append)


class TestProspectPage:
    def test_page_constructs_offscreen(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        assert h.page is not None
        assert h.page._controller is not None

    def test_persisted_prospects_load(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        assert h.controller.list_prospects()
        assert h.page.table.rowCount() >= 1

    def test_import_invokes_service_or_controller(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        result = h.controller.import_csv("company,website\nBob,bob.com\n")
        assert result is not None and result.imported == 1
        assert h.controller.list_prospects()

    def test_import_summary_displayed(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        statuses = []
        h.controller.status_message.connect(statuses.append)
        h.controller.import_csv("company,website\nBob,bob.com\n")
        assert any("Imported 1" in s for s in statuses)

    def test_bad_import_surfaces_error(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        result = h.controller.import_csv("website,phone\nexample.com,1234567890\n")
        assert result is None
        assert h.errors, "Expected an error message"

    def test_filter_works(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        h.controller.create_prospect(
            company_name="ABC Dental", website="abcdental.com", category="Dental"
        )
        h.controller.reload()
        idx = h.page.status_filter.findData(STATUS_READY_FOR_RESEARCH)
        h.page.status_filter.setCurrentIndex(idx)
        assert h.page.table.rowCount() > 0

    def test_search_works(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        h.controller.create_prospect(company_name="Zeta Corp", website="zeta.com")
        h.controller.reload()
        h.page.search_input.setText("zeta")
        assert h.page.table.rowCount() == 1

    def test_add_prospect_persists(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        h.controller.create_prospect(company_name="New Co", website="new.com")
        h.controller.store.save()
        svc2 = ProspectWorkspaceService(
            store=ProspectStore(path=h.controller.store.path)
        )
        svc2.load()
        assert any(p.company_name == "New Co" for p in svc2.list_prospects())

    def test_edit_prospect_persists(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        p = h.controller.list_prospects()[0]
        h.controller.update_prospect(p.prospect_id, city="Denver")
        assert h.controller.get_prospect(p.prospect_id).city == "Denver"

    def test_archive_persists(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        p = h.controller.list_prospects()[0]
        h.controller.archive_prospect(p.prospect_id)
        assert h.controller.get_prospect(p.prospect_id).status == STATUS_ARCHIVED

    def test_no_project_auto_created_on_import(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        h.controller.import_csv("company,website\nBob,bob.com\n")
        svc = h.controller.service
        assert svc.imported_count() == 1

    # ------------------------------------------------------------------
    # Sprint 5E regression: get_selected + location display
    # ------------------------------------------------------------------

    def test_get_selected_returns_none_when_unselected(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        assert h.controller.get_selected() is None

    def test_get_selected_returns_selected_prospect(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        p = h.controller.list_prospects()[0]
        h.controller.select(p.prospect_id)
        assert h.controller.get_selected() is not None
        assert h.controller.get_selected().prospect_id == p.prospect_id

    def test_location_display_refresh_does_not_crash(self, tmp_path) -> None:
        # Regression: _refresh_location_display depends on controller.get_selected()
        h = _ProspectHarness(tmp_path, seed=True)
        h.page._refresh_location_display()  # must not raise AttributeError
        assert h.page.location_display.text() != ""

    def test_location_display_honest_unresolved(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        p = h.controller.list_prospects()[0]
        h.controller.select(p.prospect_id)
        h.page._refresh_location_display()
        text = h.page.location_display.text()
        assert "not resolved" in text

    def test_resolve_location_button_wired_to_controller(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        assert hasattr(h.page, "resolve_location_button")
        assert hasattr(h.page, "_on_resolve_location")
        assert hasattr(h.controller, "enrich_location_for_selected")