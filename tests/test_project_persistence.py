"""Sprint 3A persistence test suite for durable BillboardAI projects.

Covers Project construction, serialization, pipeline snapshots, artifact
registration, history, and the ProjectStore repository. Filesystem tests use
``tmp_path`` and never touch the real ``output/projects`` directory.

The structured pipeline tests exercise the real engine models (BrandProfile,
BrandAsset, MessageStrategy, AdConcept) so we prove that a reopened project
reconstructs equivalent structured state without re-scraping.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime

import pytest

from engine.ad_concept import BRAND_DOMINANT, AdConcept
from engine.brand_profile import BrandAsset, BrandProfile
from engine.message_strategy import MessageStrategy

from gui.models.project import SCHEMA_VERSION, Project
from gui.models.project_artifact import ProjectArtifact
from gui.models.project_history import ProjectHistory
from gui.models.project_store import ProjectStore


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
        file_size=1234,
        confidence=0.99,
    )


def _profile() -> BrandProfile:
    return BrandProfile(
        company_name="Example Co",
        website="https://example.com",
        domain="example.com",
        headline="Example Headline",
        colors=["#112233", "#FFFFFF"],
        logo=_brand_asset(),
        assets=[_brand_asset()],
    )


def _strategy() -> MessageStrategy:
    return MessageStrategy(
        strategy_type="TRUST_LED",
        primary_message="Trusted Since 1990",
        supporting_proof=["Licensed", "Insured"],
        cta="Call Now",
        rationale="Strong trust signals.",
        score=0.9,
        evidence=["differentiators"],
        confidence=0.85,
    )


def _concept() -> AdConcept:
    return AdConcept(
        concept_id="concept-1",
        composition_family=BRAND_DOMINANT,
        headline="Trusted Since 1990",
        cta="Call Now",
        supporting_proof=["Licensed"],
        strategy_type="TRUST_LED",
        score=0.9,
        logo_asset=_brand_asset(),
    )


def _project_from_dict(data: dict) -> Project:
    """Reconstruct a Project from a to_dict() payload via the real load path."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "project.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return Project.load(path)


def _store(tmp_path) -> ProjectStore:
    return ProjectStore(root=str(tmp_path))
# ---------------------------------------------------------------------------
# 1. Minimal construction / identity
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_minimal_project_construction(self) -> None:
        p = Project()
        assert p.id
        assert p.name == ""
        assert p.company == ""
        assert p.concepts == []
        assert p.ad_concepts == []
        assert p.artifacts == []
        assert p.history == []
        assert p.schema_version == SCHEMA_VERSION

    def test_unique_project_ids(self) -> None:
        ids = {Project().id for _ in range(100)}
        assert len(ids) == 100

    def test_filesystem_safe_ids(self) -> None:
        safe = re.compile(r"^[A-Za-z0-9_.-]+$")
        for _ in range(50):
            pid = Project().id
            assert safe.match(pid)
            assert pid == str(uuid.UUID(pid))


# ---------------------------------------------------------------------------
# 2. Serialization round-trips
# ---------------------------------------------------------------------------
class TestSerialization:
    def test_project_to_dict_from_dict(self) -> None:
        p = Project(name="Acme", company="Acme Inc", website="https://acme.com")
        data = p.to_dict()
        assert data["name"] == "Acme"
        assert data["company"] == "Acme Inc"
        assert data["schema_version"] == SCHEMA_VERSION

    def test_json_round_trip(self) -> None:
        p = Project(name="Acme", company="Acme Inc", website="https://acme.com")
        restored = _project_from_dict(p.to_dict())
        assert restored.company == "Acme Inc"
        assert restored.website == "https://acme.com"

    def test_unknown_fields_ignored(self) -> None:
        data = Project().to_dict()
        data["totally_unknown_field"] = {"nested": True}
        restored = _project_from_dict(data)
        assert not hasattr(restored, "totally_unknown_field")

    def test_missing_optional_fields_default(self) -> None:
        restored = _project_from_dict({})
        assert restored.schema_version == SCHEMA_VERSION
        assert restored.brand_profile is None
        assert restored.strategies == []
        assert restored.ad_concepts == []
        assert restored.artifacts == []
        assert restored.status == "active"

    def test_old_minimal_schema_loads_safely(self) -> None:
        legacy = {
            "id": "old-id",
            "version": "0.1",
            "name": "Legacy",
            "company": "Legacy Co",
            "website": "https://legacy.com",
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "concepts": [],
        }
        restored = _project_from_dict(legacy)
        assert restored.company == "Legacy Co"
        assert restored.schema_version == SCHEMA_VERSION
        assert restored.status == "active"
# ---------------------------------------------------------------------------
# 3. Structured pipeline reconstruction
# ---------------------------------------------------------------------------
class TestStructuredReconstruction:
    def test_brand_profile_reconstruction(self) -> None:
        p = Project()
        p.update_from_pipeline(brand_profile=_profile())
        restored = _project_from_dict(p.to_dict())
        assert restored.brand_profile["company_name"] == "Example Co"
        assert restored.brand_profile["domain"] == "example.com"

    def test_brand_asset_reconstruction_through_brand_profile(self) -> None:
        p = Project()
        p.update_from_pipeline(brand_profile=_profile())
        logo = p.brand_profile["logo"]
        assert logo["asset_type"] == "logo"
        assert logo["aspect_ratio"] == pytest.approx(400 / 120)
        assert logo["width"] == 400

    def test_message_strategy_list_reconstruction(self) -> None:
        p = Project()
        p.update_from_pipeline(strategies=[_strategy()])
        restored = _project_from_dict(p.to_dict())
        assert restored.strategies[0]["primary_message"] == "Trusted Since 1990"
        assert restored.strategies[0]["supporting_proof"] == ["Licensed", "Insured"]

    def test_ad_concept_list_reconstruction(self) -> None:
        p = Project()
        p.update_from_pipeline(concepts=[_concept()])
        restored = _project_from_dict(p.to_dict())
        assert restored.ad_concepts[0]["headline"] == "Trusted Since 1990"
        assert restored.ad_concepts[0]["composition_family"] == BRAND_DOMINANT

    def test_pipeline_update_does_not_mutate_brand_profile(self) -> None:
        profile = _profile()
        p = Project()
        p.update_from_pipeline(brand_profile=profile)
        profile.headline = "Changed"
        assert p.brand_profile["headline"] == "Example Headline"

    def test_pipeline_update_does_not_mutate_message_strategy(self) -> None:
        strategy = _strategy()
        p = Project()
        p.update_from_pipeline(strategies=[strategy])
        strategy.primary_message = "Changed"
        assert p.strategies[0]["primary_message"] == "Trusted Since 1990"

    def test_pipeline_update_does_not_mutate_ad_concept(self) -> None:
        concept = _concept()
        p = Project()
        p.update_from_pipeline(concepts=[concept])
        concept.headline = "Changed"
        assert p.ad_concepts[0]["headline"] == "Trusted Since 1990"

    def test_reload_reconstructs_equivalent_structured_state(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Example Co", website="https://example.com")
        project.update_from_pipeline(
            brand_profile=_profile(),
            strategies=[_strategy()],
            concepts=[_concept()],
        )
        project.selected_concept_id = "concept-1"
        store.save(project)

        reloaded = store.load(project.id)
        assert reloaded.brand_profile["company_name"] == "Example Co"
        assert reloaded.strategies[0]["strategy_type"] == "TRUST_LED"
        assert reloaded.ad_concepts[0]["concept_id"] == "concept-1"
        assert reloaded.selected_concept_id == "concept-1"
# ---------------------------------------------------------------------------
# 4. Overrides / history / artifacts persistence
# ---------------------------------------------------------------------------
class TestStatePersistence:
    def test_selected_concept_id_persistence(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        project.selected_concept_id = "concept-7"
        store.save(project)
        assert store.load(project.id).selected_concept_id == "concept-7"

    def test_user_overrides_persistence(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        project.user_overrides["headline"] = "Custom Headline"
        project.user_overrides["cta"] = "Custom CTA"
        store.save(project)
        restored = store.load(project.id)
        assert restored.user_overrides["headline"] == "Custom Headline"
        assert restored.user_overrides["cta"] == "Custom CTA"

    def test_history_persistence(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        project.append_history("concepts_generated", "Generated 3 concepts")
        store.save(project)
        restored = store.load(project.id)
        events = [h.event_type for h in restored.history]
        assert "project_created" in events
        assert "concepts_generated" in events

    def test_history_append(self) -> None:
        p = Project()
        entry = p.append_history("concept_selected", "Concept 2 selected")
        assert isinstance(entry, ProjectHistory)
        assert p.history[-1].event_type == "concept_selected"

    def test_artifact_persistence(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        project.register_artifact(
            artifact_type="mockup",
            path="mockups/acme_cart.png",
            concept_id="concept-1",
            scene_template="cart_corral",
        )
        store.save(project)
        restored = store.load(project.id)
        assert len(restored.artifacts) == 1
        assert restored.artifacts[0].artifact_type == "mockup"
        assert restored.artifacts[0].scene_template == "cart_corral"

    def test_schema_version_persistence(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        store.save(project)
        assert store.load(project.id).schema_version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 5. Artifact registration
# ---------------------------------------------------------------------------
class TestArtifacts:
    def test_artifact_registration(self) -> None:
        p = Project()
        artifact = p.register_artifact(artifact_type="artwork", path="artwork/a.png")
        assert artifact.artifact_id
        assert p.artifacts[0] is artifact

    def test_artifact_concept_association(self) -> None:
        p = Project()
        artifact = p.register_artifact(
            artifact_type="artwork",
            path="artwork/a.png",
            concept_id="concept-3",
        )
        assert artifact.concept_id == "concept-3"

    def test_artifact_scene_template_association(self) -> None:
        p = Project()
        artifact = p.register_artifact(
            artifact_type="mockup",
            path="mockups/m.png",
            scene_template="cart_nose",
            composition_family="BRAND_DOMINANT",
        )
        assert artifact.scene_template == "cart_nose"
        assert artifact.composition_family == "BRAND_DOMINANT"

    def test_get_artifact_by_id(self) -> None:
        p = Project()
        artifact = p.register_artifact(artifact_type="artwork", path="a.png")
        assert p.get_artifact(artifact.artifact_id) is artifact
        assert p.get_artifact("missing") is None
# ---------------------------------------------------------------------------
# 6. ProjectStore repository
# ---------------------------------------------------------------------------
class TestProjectStore:
    def test_create_project_directory(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        assert os.path.isdir(project.root_dir)
        assert os.path.isfile(project.metadata_path)

    def test_save_project_json(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        assert os.path.isfile(project.metadata_path)
        with open(project.metadata_path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["company"] == "Acme"

    def test_load_project(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme", website="https://acme.com")
        loaded = store.load(project.id)
        assert loaded.id == project.id
        assert loaded.company == "Acme"

    def test_list_projects(self, tmp_path) -> None:
        store = _store(tmp_path)
        p1 = store.create(company_name="One")
        p2 = store.create(company_name="Two")
        ids = {p.id for p in store.list()}
        assert ids == {p1.id, p2.id}

    def test_multiple_projects_same_company_allowed(self, tmp_path) -> None:
        store = _store(tmp_path)
        a = store.create(company_name="Acme")
        b = store.create(company_name="Acme")
        assert a.id != b.id
        assert len(store.list()) == 2

    def test_project_paths_isolated(self, tmp_path) -> None:
        store = _store(tmp_path)
        a = store.create(company_name="Acme")
        b = store.create(company_name="Beta")
        assert a.root_dir != b.root_dir
        assert os.path.commonpath([a.root_dir, b.root_dir]) == os.path.abspath(str(tmp_path))

    def test_artifact_directories_isolated(self, tmp_path) -> None:
        store = _store(tmp_path)
        a = store.create(company_name="Acme")
        b = store.create(company_name="Beta")
        assert os.path.isdir(os.path.join(a.root_dir, "artwork"))
        assert os.path.isdir(os.path.join(b.root_dir, "artwork"))
        assert os.path.join(a.root_dir, "artwork") != os.path.join(b.root_dir, "artwork")

    def test_atomic_save_behavior(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        before = sorted(os.listdir(project.root_dir))
        project.company = "Acme Updated"
        store.save(project)
        after = sorted(os.listdir(project.root_dir))
        assert not any(name.endswith(".tmp") for name in after)
        assert store.load(project.id).company == "Acme Updated"
        assert before == after

    def test_corrupted_json_fails_clearly(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        with open(project.metadata_path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not valid json")
        with pytest.raises(json.JSONDecodeError):
            Project.load(project.metadata_path)

    def test_missing_project_fails_clearly(self, tmp_path) -> None:
        store = _store(tmp_path)
        with pytest.raises(FileNotFoundError):
            store.load("does-not-exist")

    def test_exists(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        assert store.exists(project.id)
        assert not store.exists("missing")

    def test_project_path(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        assert store.project_path(project.id) == project.root_dir
        assert store.project_path("missing") is None

    def test_archive_delete_behavior(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        archived = store.archive(project.id)
        assert os.path.isdir(archived)
        assert not store.exists(project.id)
        assert os.path.isfile(os.path.join(archived, "project.json"))

    def test_repository_ignores_unrelated_entries(self, tmp_path) -> None:
        store = _store(tmp_path)
        store.create(company_name="Acme")
        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "not_a_project").mkdir()
        ids = [p.id for p in store.list()]
        assert len(ids) == 1

    def test_deterministic_listing(self, tmp_path) -> None:
        store = _store(tmp_path)
        store.create(company_name="B")
        store.create(company_name="A")
        store.create(company_name="C")
        first = [p.id for p in store.list()]
        second = [p.id for p in store.list()]
        assert first == sorted(first)
        assert first == second

    def test_store_creates_no_stray_name_directories(self, tmp_path) -> None:
        """Regression: the store must not leave name-based dirs alongside UUID dirs."""
        store = _store(tmp_path)
        store.create(company_name="Acme")
        # Every entry under the store root must be a UUID-named project dir
        # (plus nothing else), never a stray "acme" folder.
        entries = [e for e in os.listdir(tmp_path) if e != "_archive"]
        assert len(entries) == 1
        assert str(uuid.UUID(entries[0])) == entries[0]


# ---------------------------------------------------------------------------
# 7. modified_at / relative paths
# ---------------------------------------------------------------------------
class TestMisc:
    def test_project_modified_at_updates(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        original = project.modified
        project.register_artifact(artifact_type="artwork", path="a.png")
        assert project.modified >= original

    def test_relative_portable_artifact_path(self, tmp_path) -> None:
        store = _store(tmp_path)
        project = store.create(company_name="Acme")
        project.register_artifact(
            artifact_type="mockup",
            path="mockups/acme.png",  # relative, portable
        )
        store.save(project)
        reloaded = store.load(project.id)
        assert reloaded.artifacts[0].path == "mockups/acme.png"