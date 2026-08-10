"""Sprint 3B project workspace tests (service + controller).

The domain layer (:class:`gui.services.project_workspace.ProjectWorkspaceService`)
is Qt-free and tested directly. A small set of controller tests are guarded so
they only run when a QApplication is available (widgets are built headlessly on
the offscreen platform). Filesystem tests use ``tmp_path`` and never touch the
real ``output/projects`` directory.
"""

from __future__ import annotations

import os

import pytest

from engine.ad_concept import BRAND_DOMINANT, AdConcept
from engine.brand_profile import BrandAsset, BrandProfile
from engine.message_strategy import MessageStrategy

from gui.models.project import Project
from gui.models.project_artifact import (
    ARTIFACT_TYPE_ARTWORK,
    ARTIFACT_TYPE_MOCKUP,
)
from gui.models.project_store import ProjectStore
from gui.services.project_workspace import ProjectWorkspaceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brand_asset() -> BrandAsset:
    return BrandAsset(
        path="/tmp/logo.png",
        source_url="https://example.com/logo.png",
        asset_type="logo",
        mime_type="image/png",
        format="PNG",
        width=400,
        height=120,
        aspect_ratio=400 / 120,
        has_alpha=True,
        confidence=0.99,
    )


def _profile() -> BrandProfile:
    return BrandProfile(
        company_name="Jim Woods Roofing",
        website="https://jimwoodsroofing.com",
        domain="jimwoodsroofing.com",
        phone="605-764-9517",
        location="Sioux Falls, SD",
        service_area="Sioux Falls",
        services=["Roofing"],
        categories=["Roofing"],
        differentiators=["Financing Available", "Free Estimates"],
        trust_signals=["27 Years in Business"],
        guarantees=["Manufacturer Warranty"],
        years_in_business="27",
        colors=["#1B2A4A", "#F4F4F4"],
        logo=_brand_asset(),
    )


def _strategy() -> MessageStrategy:
    return MessageStrategy(
        strategy_type="TRUST_LED",
        primary_message="Trusted Since 1990",
        supporting_proof=["Licensed"],
        cta="Call Now",
        score=0.9,
        confidence=0.85,
    )


def _concept(concept_id: str = "concept-1", headline: str = "Source Headline") -> AdConcept:
    return AdConcept(
        concept_id=concept_id,
        composition_family=BRAND_DOMINANT,
        strategy_type="TRUST_LED",
        headline=headline,
        supporting_proof=["Financing Available"],
        cta="Source CTA",
        score=0.9,
        confidence=0.85,
        source_strategy=_strategy(),
        logo_asset=_brand_asset(),
    )


def _service(tmp_path) -> tuple[ProjectWorkspaceService, ProjectStore]:
    store = ProjectStore(root=str(tmp_path))
    return ProjectWorkspaceService(store=store), store


def _create_persisted_project(store: ProjectStore, profile: BrandProfile) -> Project:
    project = store.create(
        company_name=profile.company_name,
        website=profile.website,
    )
    project.update_from_pipeline(
        brand_profile=profile,
        strategies=[_strategy()],
        concepts=[_concept(), _concept("concept-2", "Second")],
    )
    project.selected_concept_id = "concept-2"
    store.save(project)
    return project


# ---------------------------------------------------------------------------
# PROJECT LIST
# ---------------------------------------------------------------------------
class TestProjectList:
    def test_list_persisted_projects(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        _create_persisted_project(store, _profile())
        _create_persisted_project(store, BrandProfile(company_name="Another Co"))
        assert len(svc.list_projects()) == 2

    def test_empty_list_handled(self, tmp_path) -> None:
        svc, _store = _service(tmp_path)
        assert svc.list_projects() == []

    def test_archived_projects_excluded(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        store.archive(p.id)
        assert [x.id for x in svc.list_projects()] == []

    def test_deterministic_ordering(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        _create_persisted_project(store, _profile())
        _create_persisted_project(store, BrandProfile(company_name="Zed Co"))
        _create_persisted_project(store, BrandProfile(company_name="Alpha Co"))
        ids = [p.id for p in svc.list_projects()]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# OPEN PROJECT
# ---------------------------------------------------------------------------
class TestOpenProject:
    def test_open_persisted_project(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        loaded = svc.open_project(p.id)
        assert loaded.company == "Jim Woods Roofing"
        assert loaded.brand_profile is not None
        assert len(loaded.ad_concepts) == 2

    def test_open_does_not_scrape(self, tmp_path, monkeypatch) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())

        def _fail(*_a, **_k):  # pragma: no cover - would fail if called
            raise AssertionError("Scraper must not run on reopen")

        monkeypatch.setattr("engine.scraper.site.WebsiteScraper.run", _fail)
        loaded = svc.open_project(p.id)
        assert loaded.website == "https://jimwoodsroofing.com"

    def test_missing_project_raises(self, tmp_path) -> None:
        svc, _store = _service(tmp_path)
        with pytest.raises(FileNotFoundError):
            svc.open_project("does-not-exist")

    def test_corrupt_project_handled(self, tmp_path) -> None:
        store = ProjectStore(root=str(tmp_path))
        pid = "corrupt-id"
        os.makedirs(os.path.join(str(tmp_path), pid), exist_ok=True)
        with open(
            os.path.join(str(tmp_path), pid, "project.json"), "w", encoding="utf-8"
        ) as fh:
            fh.write("{ not valid json !!!")
        svc = ProjectWorkspaceService(store=store)
        with pytest.raises(Exception):
            svc.open_project(pid)


# ---------------------------------------------------------------------------
# OVERVIEW / RESEARCH
# ---------------------------------------------------------------------------
class TestOverviewResearch:
    def test_profile_hydration(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        profile = svc.hydrate_brand_profile(p)
        assert profile is not None
        assert profile.company_name == "Jim Woods Roofing"
        assert profile.categories == ["Roofing"]
        assert profile.differentiators == ["Financing Available", "Free Estimates"]

    def test_missing_profile_safe(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = store.create(company_name="No Research Co", website="https://x.com")
        assert svc.hydrate_brand_profile(p) is None

    def test_research_does_not_mutate_source(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        before = dict(p.brand_profile)
        svc.hydrate_brand_profile(p)
        assert p.brand_profile == before


# ---------------------------------------------------------------------------
# CONCEPTS
# ---------------------------------------------------------------------------
class TestConcepts:
    def test_all_saved_concepts_load(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        concepts = svc.all_ad_concepts(p)
        assert len(concepts) == 2
        assert {c.concept_id for c in concepts} == {"concept-1", "concept-2"}

    def test_selected_concept_state(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        assert p.selected_concept_id == "concept-2"
        assert svc.hydrate_ad_concept(p).concept_id == "concept-2"

    def test_selecting_concept_persists(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.select_concept(p, "concept-1")
        reloaded = store.load(p.id)
        assert reloaded.selected_concept_id == "concept-1"

    def test_selection_adds_history(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        before = len(p.history)
        svc.select_concept(p, "concept-1")
        assert len(p.history) == before + 1
        assert p.history[-1].event_type == "concept_selected"

    def test_missing_selected_concept_handled(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        with pytest.raises(ValueError):
            svc.select_concept(p, "ghost-concept")


# ---------------------------------------------------------------------------
# ARTIFACTS
# ---------------------------------------------------------------------------
class TestArtifacts:
    def test_artifact_concept_association(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        art = p.register_artifact(
            artifact_type=ARTIFACT_TYPE_MOCKUP,
            path="mockups/x.png",
            concept_id="concept-1",
            scene_template="cart_corral",
        )
        store.save(p)
        reloaded = store.load(p.id)
        assert reloaded.artifacts[0].concept_id == "concept-1"
        assert reloaded.artifacts[0].artifact_id == art.artifact_id

    def test_resolve_artifact_path_relative(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        art = p.register_artifact(
            artifact_type=ARTIFACT_TYPE_ARTWORK, path="artwork/a.png"
        )
        resolved = svc.resolve_artifact_path(p, art)
        assert os.path.normpath(resolved) == os.path.normpath(
            os.path.join(p.root_dir, "artwork", "a.png")
        )


# ---------------------------------------------------------------------------
# OVERRIDES
# ---------------------------------------------------------------------------
class TestOverrides:
    def test_headline_override_persists(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.set_override(p, "headline", "New Headline")
        reloaded = store.load(p.id)
        assert reloaded.user_overrides["headline"] == "New Headline"

    def test_cta_override_persists(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.set_override(p, "cta", "Call 555")
        reloaded = store.load(p.id)
        assert reloaded.user_overrides["cta"] == "Call 555"

    def test_reset_override(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.set_override(p, "headline", "X")
        svc.reset_override(p, "headline")
        reloaded = store.load(p.id)
        assert "headline" not in reloaded.user_overrides

    def test_override_does_not_mutate_source(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        ad = svc.hydrate_ad_concept(p, "concept-1")
        original_headline = ad.headline
        svc.set_override(p, "headline", "OVERRIDE")
        render = svc.build_render_concept(ad, p.user_overrides)
        assert render.headline == "OVERRIDE"
        assert ad.headline == original_headline  # source untouched
        reloaded = store.load(p.id)
        source = svc.hydrate_ad_concept(reloaded, "concept-1")
        assert source.headline == original_headline

    def test_reopen_preserves_overrides(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.set_override(p, "headline", "Persisted")
        reloaded = store.load(p.id)
        assert reloaded.user_overrides["headline"] == "Persisted"


# ---------------------------------------------------------------------------
# STATUS
# ---------------------------------------------------------------------------
class TestStatus:
    def test_status_persists(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.set_status(p, "CONTACTED")
        reloaded = store.load(p.id)
        assert reloaded.status == "CONTACTED"

    def test_status_change_history(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        before = len(p.history)
        svc.set_status(p, "WON")
        assert p.history[-1].event_type == "status_changed"
        assert len(p.history) == before + 1

    def test_invalid_status_rejected(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        with pytest.raises(ValueError):
            svc.set_status(p, "NOT_A_STATUS")


# ---------------------------------------------------------------------------
# PERSISTENCE (close/reopen keeps state)
# ---------------------------------------------------------------------------
class TestPersistence:
    def test_reopen_keeps_selected_concept(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        reloaded = store.load(p.id)
        assert reloaded.selected_concept_id == "concept-2"

    def test_reopen_keeps_artifacts(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        p.register_artifact(artifact_type=ARTIFACT_TYPE_MOCKUP, path="mockups/m.png")
        store.save(p)
        reloaded = store.load(p.id)
        assert len(reloaded.artifacts) == 1

    def test_reopen_keeps_history(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.select_concept(p, "concept-1")
        reloaded = store.load(p.id)
        assert any(h.event_type == "concept_selected" for h in reloaded.history)

    def test_reopen_requires_no_scrape(self, tmp_path, monkeypatch) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())

        def _fail(*_a, **_k):  # pragma: no cover
            raise AssertionError("Scraper must not run")

        monkeypatch.setattr("engine.scraper.site.WebsiteScraper.run", _fail)
        reloaded = store.load(p.id)
        assert reloaded.brand_profile is not None


# ---------------------------------------------------------------------------
# MOCKUP GENERATION
# ---------------------------------------------------------------------------
class TestMockupGeneration:
    def test_effective_render_copy(self) -> None:
        svc = ProjectWorkspaceService()
        ad = _concept("c1", "Source")
        copy = svc.build_render_concept(ad, {"headline": "Override", "cta": "Go"})
        assert copy.headline == "Override"
        assert copy.cta == "Go"
        assert ad.headline == "Source"
        assert ad is not copy

    def test_generate_requires_concept(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = store.create(company_name="X", website="https://x.com")
        with pytest.raises(ValueError, match="No AdConcept"):
            svc.generate_mockup(p, "cart_corral")

    def test_generate_requires_profile(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = store.create(company_name="X", website="https://x.com")
        p.ad_concepts = [_concept().to_dict()]
        p.selected_concept_id = "concept-1"
        with pytest.raises(ValueError, match="no saved research"):
            svc.generate_mockup(p, "cart_corral")

    def test_generate_registers_artifacts(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        artifacts = svc.generate_mockup(p, "cart_corral", concept_id="concept-1")
        types = {a.artifact_type for a in artifacts}
        assert ARTIFACT_TYPE_ARTWORK in types
        assert ARTIFACT_TYPE_MOCKUP in types
        reloaded = store.load(p.id)
        assert len(reloaded.artifacts) == 2

    def test_generate_saves_project(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        svc.generate_mockup(p, "cart_corral", concept_id="concept-1")
        reloaded = store.load(p.id)
        assert any(h.event_type == "mockup_generated" for h in reloaded.history)

    def test_failure_leaves_project_consistent(self, tmp_path) -> None:
        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        # Missing concept -> raises before any artifact write.
        with pytest.raises(ValueError):
            svc.generate_mockup(p, "cart_corral", concept_id="ghost-concept")
        reloaded = store.load(p.id)
        assert reloaded.artifacts == []


# ---------------------------------------------------------------------------
# SCENE TEMPLATES
# ---------------------------------------------------------------------------
class TestSceneTemplates:
    def test_list_scene_templates(self) -> None:
        from gui.services.project_workspace import list_scene_templates

        templates = list_scene_templates()
        ids = {t["id"] for t in templates}
        assert "cart_corral" in ids
        assert "cart_nose" in ids
        assert all("name" in t and "artwork_size" in t for t in templates)


# ---------------------------------------------------------------------------
# CONTROLLER (Qt-guarded)
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


class TestController:
    def test_open_project_emits(self, tmp_path) -> None:
        _qapplication()
        from gui.controllers.project_controller import ProjectWorkspaceController

        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        ctrl = ProjectWorkspaceController(service=svc)
        opened = []

        ctrl.project_opened.connect(lambda proj: opened.append(proj))
        ctrl.open_project(p.id)
        assert len(opened) == 1
        assert opened[0].id == p.id
        assert ctrl.project is not None

    def test_controller_wiring_uses_worker_path(self, tmp_path) -> None:
        """Long generation uses a worker thread (not the GUI thread)."""
        import time

        app = _qapplication()
        from PySide6.QtCore import QThread
        from gui.controllers.project_controller import ProjectWorkspaceController

        svc, store = _service(tmp_path)
        p = _create_persisted_project(store, _profile())
        ctrl = ProjectWorkspaceController(service=svc)
        ctrl.open_project(p.id)
        ctrl.generate_mockup("cart_corral")
        assert ctrl._thread is not None
        assert isinstance(ctrl._thread, QThread)

        # Drive the event loop so queued finish/cleanup signals are delivered.
        deadline = time.time() + 30
        while ctrl.is_generating and time.time() < deadline:
            app.processEvents()
            if ctrl._thread is not None:
                ctrl._thread.wait(50)
        assert not ctrl.is_generating


# ---------------------------------------------------------------------------
# STATUS SELECTOR (Sprint 3B final patch, Qt-guarded)
# ---------------------------------------------------------------------------
class _WorkspaceHarness:
    """Build a ProjectWorkspacePage wired to a real controller + store."""

    def __init__(self, tmp_path, status: str = "NEW") -> None:
        _qapplication()
        from gui.controllers.project_controller import ProjectWorkspaceController
        from gui.views.project_workspace_page import ProjectWorkspacePage

        self.store = ProjectStore(root=str(tmp_path))
        self.svc = ProjectWorkspaceService(store=self.store)
        self.project = _create_persisted_project(self.store, _profile())
        self.project.status = status
        self.store.save(self.project)

        self.controller = ProjectWorkspaceController(service=self.svc)
        self.page = ProjectWorkspacePage(controller=self.controller)
        self.controller.open_project(self.project.id)
        self.page.set_project(self.controller.project)
        self.status_combo = self.page.status_combo
        self.received = []
        self.page.set_status_requested.connect(self.received.append)


class TestStatusSelector:
    def test_selector_populated_from_available_statuses(self, tmp_path) -> None:
        h = _WorkspaceHarness(tmp_path)
        expected = set(h.controller.available_statuses())
        actual = {h.status_combo.itemData(i) for i in range(h.status_combo.count())}
        assert expected <= actual

    def test_persisted_status_selected_on_open(self, tmp_path) -> None:
        h = _WorkspaceHarness(tmp_path, status="CONTACTED")
        assert h.status_combo.currentData() == "CONTACTED"

    def test_ui_status_change_calls_controller_path(self, tmp_path) -> None:
        h = _WorkspaceHarness(tmp_path, status="NEW")
        idx = h.status_combo.findData("WON")
        h.status_combo.setCurrentIndex(idx)
        assert h.received == ["WON"]

    def test_change_persists_after_reload(self, tmp_path) -> None:
        h = _WorkspaceHarness(tmp_path, status="NEW")
        idx = h.status_combo.findData("LOST")
        h.status_combo.setCurrentIndex(idx)
        # Persist via the controller path (emulate the MainWindow wiring).
        if h.received:
            h.controller.set_status(h.received[-1])
            h.page.set_project(h.controller.project)
        reloaded = h.store.load(h.project.id)
        assert reloaded.status == "LOST"

    def test_history_event_added_exactly_once(self, tmp_path) -> None:
        h = _WorkspaceHarness(tmp_path, status="NEW")
        idx = h.status_combo.findData("INTERESTED")
        h.status_combo.setCurrentIndex(idx)
        h.controller.set_status(h.received[-1])
        reloaded = h.store.load(h.project.id)
        events = [ev for ev in reloaded.history if ev.event_type == "status_changed"]
        assert len(events) == 1

    def test_initial_load_creates_no_status_change_event(self, tmp_path) -> None:
        h = _WorkspaceHarness(tmp_path, status="RESEARCHED")
        # Opening + refreshing the page must not emit a status-change signal.
        assert h.received == []
        reloaded = h.store.load(h.project.id)
        assert not any(ev.event_type == "status_changed" for ev in reloaded.history)