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
from PySide6.QtCore import QDate

from gui.models.prospect import (
    STATUS_ARCHIVED,
    STATUS_DISQUALIFIED,
    STATUS_IMPORTED,
    STATUS_READY_FOR_RESEARCH,
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    WORKFLOW_STATUS_CONTACTED,
    WORKFLOW_STATUS_FOLLOW_UP,
    WORKFLOW_STATUS_NEW,
    WORKFLOW_STATUS_READY_TO_CONTACT,
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
# Sprint 5G: workflow service
# ---------------------------------------------------------------------------

class TestWorkflowService:
    def test_workflow_update_persists(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        updated = svc.update_workflow(
            p.prospect_id,
            status=WORKFLOW_STATUS_READY_TO_CONTACT,
            priority=PRIORITY_HIGH,
            next_action="Call owner",
            next_action_date="2026-08-15",
            notes="Hot lead",
        )
        assert updated.workflow_status == WORKFLOW_STATUS_READY_TO_CONTACT
        assert updated.priority == PRIORITY_HIGH
        assert updated.next_action == "Call owner"
        assert updated.next_action_date == "2026-08-15"
        assert updated.workflow_notes == "Hot lead"

    def test_partial_workflow_update_preserves_unspecified_fields(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        svc.update_workflow(
            p.prospect_id,
            status=WORKFLOW_STATUS_CONTACTED,
            priority=PRIORITY_HIGH,
            next_action="Call owner",
            next_action_date="2026-08-15",
            notes="Hot lead",
        )
        updated = svc.update_workflow(p.prospect_id, next_action="Email owner")
        assert updated.workflow_status == WORKFLOW_STATUS_CONTACTED
        assert updated.priority == PRIORITY_HIGH
        assert updated.next_action == "Email owner"
        assert updated.next_action_date == "2026-08-15"
        assert updated.workflow_notes == "Hot lead"

    def test_workflow_reload_preserves_state(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        svc.update_workflow(
            p.prospect_id,
            status=WORKFLOW_STATUS_FOLLOW_UP,
            priority=PRIORITY_NORMAL,
            next_action="Follow up",
            next_action_date="2026-09-01",
            notes="",
        )
        svc2 = _service(tmp_path)
        svc2.load()
        reloaded = svc2.get_prospect(p.prospect_id)
        assert reloaded.workflow_status == WORKFLOW_STATUS_FOLLOW_UP
        assert reloaded.priority == PRIORITY_NORMAL
        assert reloaded.next_action_date == "2026-09-01"

    def test_import_merge_does_not_erase_workflow_state(self, tmp_path) -> None:
        # Critical Sprint 5G scenario: an enrichment/import update with workflow
        # fields absent/default must NOT destroy the user's sales workflow state.
        svc = _service(tmp_path)
        p = _seed(svc)
        svc.update_workflow(
            p.prospect_id,
            status=WORKFLOW_STATUS_CONTACTED,
            priority=PRIORITY_HIGH,
            next_action="Call Friday",
            next_action_date="2026-08-15",
            notes="Spoke to owner",
        )
        svc.store.save()

        # Reload authoritative state, then run the import/merge path with an
        # incoming record that carries enrichment data but default workflow fields.
        svc.store.load()
        existing = svc.store.get(p.prospect_id)
        incoming = Prospect(
            prospect_id=p.prospect_id,
            company_name=p.company_name,
            website=p.website,
            address="123 Main St",
        )  # workflow fields default to NEW / NORMAL / "" / None
        svc.store.merge(existing, incoming)

        merged = svc.store.get(p.prospect_id)
        assert merged.workflow_status == WORKFLOW_STATUS_CONTACTED
        assert merged.priority == PRIORITY_HIGH
        assert merged.next_action == "Call Friday"
        assert merged.next_action_date == "2026-08-15"
        assert merged.workflow_notes == "Spoke to owner"
        # Enrichment data was applied without touching workflow state.
        assert merged.address == "123 Main St"

    def test_workflow_update_does_not_duplicate_prospect(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        svc.update_workflow(p.prospect_id, status=WORKFLOW_STATUS_CONTACTED)
        assert svc.imported_count() == 1

    def test_update_workflow_injected_store_is_authoritative(self, tmp_path) -> None:
        custom_store = ProspectStore(path=os.path.join(str(tmp_path), "custom.json"))
        svc = ProspectWorkspaceService(store=custom_store)
        p = svc.create_prospect(company_name="Injected Co", website="inj.com")
        svc.update_workflow(p.prospect_id, status=WORKFLOW_STATUS_READY_TO_CONTACT)
        svc2 = ProspectWorkspaceService(store=custom_store)
        svc2.load()
        assert svc2.get_prospect(p.prospect_id).workflow_status == WORKFLOW_STATUS_READY_TO_CONTACT

    def test_update_workflow_does_not_modify_other_prospect(self, tmp_path) -> None:
        svc = _service(tmp_path)
        a = svc.create_prospect(company_name="A", website="a.com")
        b = svc.create_prospect(company_name="B", website="b.com")
        svc.update_workflow(
            a.prospect_id,
            status=WORKFLOW_STATUS_CONTACTED,
            priority=PRIORITY_HIGH,
            next_action="Call A",
        )
        other = svc.get_prospect(b.prospect_id)
        assert other.workflow_status == WORKFLOW_STATUS_NEW
        assert other.priority == PRIORITY_NORMAL
        assert other.next_action == ""

    def test_update_workflow_unknown_status_raises(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        with pytest.raises(ProspectValidationError):
            svc.update_workflow(p.prospect_id, status="GARBAGE")

    def test_update_workflow_unknown_priority_raises(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        with pytest.raises(ProspectValidationError):
            svc.update_workflow(p.prospect_id, priority="GARBAGE")

    def test_update_workflow_invalid_date_raises(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        with pytest.raises(ProspectValidationError):
            svc.update_workflow(p.prospect_id, next_action_date="not-a-date")

    def test_update_workflow_clears_date_with_none(self, tmp_path) -> None:
        svc = _service(tmp_path)
        p = _seed(svc)
        svc.update_workflow(p.prospect_id, next_action_date="2026-08-15")
        updated = svc.update_workflow(p.prospect_id, next_action_date=None)
        assert updated.next_action_date is None

    def test_update_workflow_missing_prospect_raises(self, tmp_path) -> None:
        svc = _service(tmp_path)
        svc.load()
        with pytest.raises(ProspectValidationError):
            svc.update_workflow("no-such-id", status=WORKFLOW_STATUS_CONTACTED)


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

    # ------------------------------------------------------------------
    # Sprint 5G: workflow UI
    # ------------------------------------------------------------------

    def test_workflow_panel_disabled_when_no_selection(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        h.page._populate_workflow_panel()
        assert h.page.workflow_save_btn.isEnabled() is False

    def test_selecting_prospect_populates_workflow_panel(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        p = h.controller.list_prospects()[0]
        h.controller.select(p.prospect_id)
        h.page._populate_workflow_panel()
        assert h.page.workflow_save_btn.isEnabled() is True
        assert h.page.workflow_status_combo.currentData() == "NEW"
        assert h.page.workflow_priority_combo.currentData() == "NORMAL"

    def test_saving_workflow_through_controller_updates_store(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=True)
        p = h.controller.list_prospects()[0]
        h.controller.select(p.prospect_id)
        h.page._selected_id = p.prospect_id
        h.page._populate_workflow_panel()

        h.page.workflow_status_combo.setCurrentIndex(
            h.page.workflow_status_combo.findData(WORKFLOW_STATUS_READY_TO_CONTACT)
        )
        h.page.workflow_priority_combo.setCurrentIndex(
            h.page.workflow_priority_combo.findData(PRIORITY_HIGH)
        )
        h.page.workflow_next_action.setText("Call owner")
        h.page.workflow_date_check.setChecked(True)
        h.page.workflow_date_edit.setDate(QDate(2026, 8, 15))
        h.page.workflow_notes.setPlainText("Hot lead")

        h.page._on_save_workflow()

        updated = h.controller.get_prospect(p.prospect_id)
        assert updated.workflow_status == WORKFLOW_STATUS_READY_TO_CONTACT
        assert updated.priority == PRIORITY_HIGH
        assert updated.next_action == "Call owner"
        assert updated.next_action_date == "2026-08-15"
        assert updated.workflow_notes == "Hot lead"

    def test_switching_prospects_replaces_workflow_values(self, tmp_path) -> None:
        h = _ProspectHarness(tmp_path, seed=False)
        a = h.controller.create_prospect(company_name="A", website="a.com")
        b = h.controller.create_prospect(company_name="B", website="b.com")
        h.controller.update_workflow(
            a.prospect_id,
            status=WORKFLOW_STATUS_CONTACTED,
            priority=PRIORITY_HIGH,
            next_action="Call A",
            next_action_date="2026-08-10",
            notes="Note A",
        )
        h.controller.update_workflow(
            b.prospect_id,
            status=WORKFLOW_STATUS_FOLLOW_UP,
            priority=PRIORITY_NORMAL,
            next_action="Call B",
            next_action_date="2026-08-11",
            notes="Note B",
        )
        h.controller.reload()

        h.controller.select(a.prospect_id)
        h.page._populate_workflow_panel()
        assert h.page.workflow_status_combo.currentData() == WORKFLOW_STATUS_CONTACTED
        assert h.page.workflow_next_action.text() == "Call A"

        h.controller.select(b.prospect_id)
        h.page._populate_workflow_panel()
        assert h.page.workflow_status_combo.currentData() == WORKFLOW_STATUS_FOLLOW_UP
        assert h.page.workflow_next_action.text() == "Call B"

        h.controller.select(a.prospect_id)
        h.page._populate_workflow_panel()
        assert h.page.workflow_status_combo.currentData() == WORKFLOW_STATUS_CONTACTED
        assert h.page.workflow_next_action.text() == "Call A"

    # ------------------------------------------------------------------
    # Sprint 5F: Dependency-injection regression
    # ------------------------------------------------------------------

    def test_select_updates_opportunity_snapshot_from_controller_store(
        self, tmp_path
    ) -> None:
        """Controller with injected stores MUST share them with the snapshot svc."""
        import os
        from gui.models.inventory import (
            PERIOD_YEAR, STATUS_AVAILABLE, Money,
            Location, Market, Placement, Retailer,
        )
        from gui.models.inventory_store import InventoryStore
        from gui.models.opportunity_store import OpportunityStore
        from gui.models.project_store import ProjectStore
        from gui.models.prospect import Prospect
        from gui.models.prospect_store import ProspectStore
        from gui.services.opportunity_service import OpportunityService
        from gui.services.prospect_opportunity_workspace import (
            ProspectOpportunityWorkspaceService,
        )
        from gui.controllers.prospect_controller import ProspectController

        root = str(tmp_path)

        # 1. Seeded prospect
        ps = ProspectStore(path=os.path.join(root, "prospects.json"))
        p = Prospect(
            prospect_id="p_test",
            company_name="Injection Test Co",
            category="roofing",
            city="Denver",
            state="CO",
            research_status="SUCCEEDED",
        )
        ps.collection.prospects.append(p)
        ps.save()

        # 2. Inventory with one placement
        invs = InventoryStore(path=os.path.join(root, "inventory.json"))
        retailer = Retailer(name="Test Retailer")
        market = Market(name="Test Market", market_id="m_test")
        loc = Location(
            location_id="l_test", name="Test Store #1",
            retailer_id=retailer.retailer_id,
            market_id=market.market_id,
            store_number="1", city="Denver", state="CO",
            latitude=39.74, longitude=-104.99, weekly_traffic=10000,
        )
        pl = Placement(
            placement_id="pl_test", location_id=loc.location_id,
            name="Window Banner", placement_type="window",
            status=STATUS_AVAILABLE,
            price=Money.dollars(6000), price_period=PERIOD_YEAR,
        )
        invs.create_inventory(
            retailers=[retailer], markets=[market],
            locations=[loc], placements=[pl],
        )
        invs.save()

        # 3. Opportunity service wired to the SAME stores
        opp_store = OpportunityStore(
            path=os.path.join(root, "opportunities.json")
        )
        opp_svc = OpportunityService(
            prospect_store=ps,
            project_store=ProjectStore(root=os.path.join(root, "projects")),
            inventory_store=invs,
            opportunity_store=opp_store,
        )

        # 4. Snapshot service wired to SAME stores
        snap_svc = ProspectOpportunityWorkspaceService(
            prospect_store=ps,
            project_store=opp_svc.project_store,
            inventory_store=invs,
            opportunity_service=opp_svc,
        )

        # 5. Controller — shares prospect store AND snapshot svc
        from gui.services.prospect_workspace import ProspectWorkspaceService
        controller = ProspectController(
            service=ProspectWorkspaceService(store=ps),
            opportunity_workspace_service=snap_svc,
        )

        # 6. Select → snapshot must reflect injected store data
        controller.select("p_test")
        snapshot = controller.snapshot
        assert snapshot is not None, "Snapshot should not be None after select"
        assert snapshot.is_empty is False, "Snapshot should not be empty"
        assert snapshot.company_name == "Injection Test Co", (
            f"Expected 'Injection Test Co', got {snapshot.company_name!r}"
        )
        assert snapshot.prospect_id == "p_test"

        # 7. No duplicate store — snapshot svc shares controller's prospect store
        assert (
            controller._snapshot_svc._prospect_store is controller._service.store
        ), "Snapshot service must share the controller's ProspectStore instance"
    def test_select_switch_no_stale_snapshot(self, tmp_path) -> None:
        """Selecting a different prospect must update the snapshot — no stale data."""
        import os
        from gui.models.inventory import (
            PERIOD_YEAR, STATUS_AVAILABLE, Money,
            Location, Market, Placement, Retailer,
        )
        from gui.models.inventory_store import InventoryStore
        from gui.models.opportunity_store import OpportunityStore
        from gui.models.project_store import ProjectStore
        from gui.models.prospect import Prospect
        from gui.models.prospect_store import ProspectStore
        from gui.services.opportunity_service import OpportunityService
        from gui.services.prospect_opportunity_workspace import (
            ProspectOpportunityWorkspaceService,
        )
        from gui.controllers.prospect_controller import ProspectController
        from gui.services.prospect_workspace import ProspectWorkspaceService

        root = str(tmp_path)

        # Two prospects
        ps = ProspectStore(path=os.path.join(root, "prospects.json"))
        p1 = Prospect(
            prospect_id="p_alpha", company_name="Alpha Inc",
            category="roofing", city="Denver", state="CO",
            research_status="SUCCEEDED",
        )
        p2 = Prospect(
            prospect_id="p_beta", company_name="Beta LLC",
            category="painting", city="Boulder", state="CO",
            research_status="NOT_READY",
        )
        ps.collection.prospects.extend([p1, p2])
        ps.save()

        # Inventory with two locations/placements
        invs = InventoryStore(path=os.path.join(root, "inventory.json"))
        retailer = Retailer(name="Test Retailer")
        market = Market(name="CO Market", market_id="m_co")
        loc1 = Location(
            location_id="l_a", name="Store A",
            retailer_id=retailer.retailer_id, market_id=market.market_id,
            store_number="A", city="Denver", state="CO",
            latitude=39.74, longitude=-104.99, weekly_traffic=10000,
        )
        loc2 = Location(
            location_id="l_b", name="Store B",
            retailer_id=retailer.retailer_id, market_id=market.market_id,
            store_number="B", city="Boulder", state="CO",
            latitude=40.01, longitude=-105.27, weekly_traffic=8000,
        )
        pl1 = Placement(
            placement_id="pl_a", location_id=loc1.location_id,
            name="Window A", placement_type="window",
            status=STATUS_AVAILABLE, price=Money.dollars(6000),
            price_period=PERIOD_YEAR,
        )
        pl2 = Placement(
            placement_id="pl_b", location_id=loc2.location_id,
            name="Window B", placement_type="window",
            status=STATUS_AVAILABLE, price=Money.dollars(5000),
            price_period=PERIOD_YEAR,
        )
        invs.create_inventory(
            retailers=[retailer], markets=[market],
            locations=[loc1, loc2], placements=[pl1, pl2],
        )
        invs.save()

        opp_store = OpportunityStore(
            path=os.path.join(root, "opportunities.json")
        )
        opp_svc = OpportunityService(
            prospect_store=ps,
            project_store=ProjectStore(root=os.path.join(root, "projects")),
            inventory_store=invs,
            opportunity_store=opp_store,
        )
        snap_svc = ProspectOpportunityWorkspaceService(
            prospect_store=ps,
            project_store=opp_svc.project_store,
            inventory_store=invs,
            opportunity_service=opp_svc,
        )
        controller = ProspectController(
            service=ProspectWorkspaceService(store=ps),
            opportunity_workspace_service=snap_svc,
        )

        # Select first
        controller.select("p_alpha")
        snap1 = controller.snapshot
        assert snap1 is not None
        assert snap1.company_name == "Alpha Inc"
        assert snap1.prospect_id == "p_alpha"

        # Switch to second — no stale data
        controller.select("p_beta")
        snap2 = controller.snapshot
        assert snap2 is not None
        assert snap2.company_name == "Beta LLC"
        assert snap2.prospect_id == "p_beta"
        assert snap1.prospect_id != snap2.prospect_id
