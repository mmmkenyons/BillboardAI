"""Tests for Sprint 4A: Project-based workflow models."""

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from datetime import datetime

import pytest

from gui.models.mockup_concept import MockupConcept
from gui.models.project import PROJECT_VERSION, Project


# ---------------------------------------------------------------------------
# MockupConcept tests
# ---------------------------------------------------------------------------
class TestMockupConcept:
    def test_create_assigns_uuid(self) -> None:
        concept = MockupConcept.create(
            image_path="/tmp/concept_001.png",
            template="contractor",
            headline="Test Headline",
            cta="Call Now",
            quality_score=92,
        )
        assert concept.id
        assert len(concept.id) == 36  # UUID4 length

    def test_create_sets_defaults(self) -> None:
        concept = MockupConcept.create(
            image_path="images/concept_001.png",
            template="realtor",
            headline="Test",
            cta="Click",
            quality_score=88,
        )
        assert concept.company_name == ""
        assert concept.user_modified is False
        assert concept.selected is False
        assert concept.extra == {}

    def test_to_dict_round_trip(self) -> None:
        original = MockupConcept(
            id="test-id-123",
            image_path="images/concept_001.png",
            template="contractor",
            headline="Colorado's Trusted Roofer",
            cta="Free Estimate",
            quality_score=94,
            company_name="ABC Roofing",
            created_at=datetime(2024, 1, 15, 10, 30, 0),
            user_modified=False,
            selected=True,
            extra={"foo": "bar"},
        )
        data = original.to_dict()
        restored = MockupConcept.from_dict(data)

        assert restored.id == original.id
        assert restored.image_path == original.image_path
        assert restored.template == original.template
        assert restored.headline == original.headline
        assert restored.cta == original.cta
        assert restored.quality_score == original.quality_score
        assert restored.company_name == original.company_name
        assert restored.created_at == original.created_at
        assert restored.user_modified == original.user_modified
        assert restored.selected == original.selected
        assert restored.extra == original.extra

    def test_from_dict_handles_missing_optional_fields(self) -> None:
        data = {
            "id": "abc",
            "image_path": "a.png",
            "template": "contractor",
            "headline": "H",
            "cta": "C",
            "quality_score": 90,
        }
        concept = MockupConcept.from_dict(data)
        assert concept.company_name == ""
        assert concept.user_modified is False
        assert concept.selected is False
        assert concept.extra == {}


# ---------------------------------------------------------------------------
# Project tests
# ---------------------------------------------------------------------------
class TestProject:
    @pytest.fixture
    def tmp_output(self) -> Iterator[str]:
        """Create a temporary output directory."""
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def test_create_makes_directory_structure(self, tmp_output: str) -> None:
        project = Project.create(
            output_root=tmp_output, name="abc_roofing"
        )
        assert os.path.isdir(project.root_dir)
        assert os.path.isdir(project.image_path)
        assert os.path.isdir(project.assets_path)
        assert os.path.isdir(project.exports_path)
        assert project.metadata_path == os.path.join(project.root_dir, "project.json")
        assert project.version == PROJECT_VERSION
        assert project.id != ""
        assert project.company == "Abc Roofing"

    def test_create_sanitizes_name(self, tmp_output: str) -> None:
        project = Project.create(
            output_root=tmp_output, name="ABC Roofing, LLC!",
            company="ABC Roofing, LLC"
        )
        assert "ABC_Roofing_LLC" in project.root_dir
        assert project.company == "ABC Roofing, LLC"

    def test_next_concept_filename_increments(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="test")
        assert project.next_concept_filename() == "concept_001.png"

        concept = MockupConcept.create(
            image_path="a.png",
            template="contractor",
            headline="H",
            cta="C",
            quality_score=90,
        )
        project.concepts.append(concept)
        assert project.next_concept_filename() == "concept_002.png"

    def test_add_concept_selects_and_deselects(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="test")
        c1 = MockupConcept.create("a.png", "contractor", "H1", "C1", 90)
        c2 = MockupConcept.create("b.png", "realtor", "H2", "C2", 85)

        project.add_concept(c1)
        assert c1.selected is True
        assert project.selected_concept_id == c1.id
        assert len(project.concepts) == 1

        project.add_concept(c2)
        assert c1.selected is False
        assert c2.selected is True
        assert project.selected_concept_id == c2.id
        assert len(project.concepts) == 2

    def test_select_concept(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="test")
        c1 = MockupConcept.create("a.png", "contractor", "H1", "C1", 90)
        c2 = MockupConcept.create("b.png", "realtor", "H2", "C2", 85)
        project.concepts.extend([c1, c2])
        project.selected_concept_id = c1.id
        project.concepts[0].selected = True

        result = project.select_concept(c2.id)
        assert result is c2
        assert c2.selected is True
        assert c1.selected is False
        assert project.selected_concept_id == c2.id

    def test_select_nonexistent_concept_returns_none(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="test")
        result = project.select_concept("nonexistent")
        assert result is None
        assert project.selected_concept_id is None

    def test_get_selected_concept(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="test")
        assert project.get_selected_concept() is None

        c = MockupConcept.create("a.png", "contractor", "H", "C", 90)
        project.concepts.append(c)
        project.selected_concept_id = c.id
        assert project.get_selected_concept() is c

    def test_to_dict_includes_version_and_id(self, tmp_output: str) -> None:
        project = Project.create(
            output_root=tmp_output, name="test", website="https://example.com"
        )
        data = project.to_dict()
        assert data["version"] == PROJECT_VERSION
        assert data["id"] != ""
        assert data["website"] == "https://example.com"
        assert data["concepts"] == []
        assert data["selected_concept_id"] is None

    def test_save_and_load_round_trip(self, tmp_output: str) -> None:
        project = Project.create(
            output_root=tmp_output, name="round_trip", website="https://test.com"
        )
        c = MockupConcept.create("images/concept_001.png", "contractor", "H", "C", 95)
        project.concepts.append(c)
        project.selected_concept_id = c.id
        project.concepts[0].selected = True
        project.logo_override = "assets/logo.png"

        project._write_to_disk()
        assert os.path.isfile(project.metadata_path)

        loaded = Project.load(project.metadata_path)
        assert loaded.id == project.id
        assert loaded.version == project.version
        assert loaded.company == project.company
        assert loaded.website == project.website
        assert loaded.logo_override == "assets/logo.png"
        assert len(loaded.concepts) == 1
        assert loaded.selected_concept_id == c.id
        assert loaded.concepts[0].headline == "H"
        assert loaded.concepts[0].quality_score == 95

    def test_load_preserves_concept_selection(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="persist")
        c1 = MockupConcept.create("a.png", "contractor", "H1", "C1", 90)
        c2 = MockupConcept.create("b.png", "realtor", "H2", "C2", 85)
        project.concepts.extend([c1, c2])
        project.selected_concept_id = c2.id
        c2.selected = True
        c1.selected = False
        project._write_to_disk()

        loaded = Project.load(project.metadata_path)
        assert loaded.selected_concept_id == c2.id
        assert loaded.concepts[0].selected is False
        assert loaded.concepts[1].selected is True

    def test_logo_override_persistence_and_clear(self, tmp_output: str) -> None:
        """Regression test for reload → reset logo (Sprint 4B Phase D).

        Ensures set_logo_override persists, clear_logo_override resets without
        screenshot fallback, and revision prevents stale re-renders.
        """
        project = Project.create(output_root=tmp_output, name="logo_test")
        dummy_logo = os.path.join(tmp_output, "scraped_logo.png")
        os.makedirs(os.path.dirname(dummy_logo), exist_ok=True)
        with open(dummy_logo, "w") as f:
            f.write("dummy")  # not real image, but for path test

        # Set override
        project.set_logo_override(dummy_logo)
        assert project.logo_override
        assert project.render_context.get("logo_image") == project.logo_override
        initial_revision = project.get_render_revision()
        assert initial_revision > 0

        project.save()

        # Load and verify persistence
        loaded = Project.load(project.metadata_path)
        assert loaded.logo_override == project.logo_override
        assert loaded.render_context.get("logo_image") == project.logo_override

        # Clear override (regression: no screenshot fallback)
        loaded.clear_logo_override()
        assert loaded.logo_override == ""
        assert loaded.render_context.get("logo_image") == ""

        # Effective context prefers empty (no screenshot)
        effective = loaded.effective_render_context()
        assert effective.get("logo_image") == ""

        loaded.save()
        reloaded = Project.load(loaded.metadata_path)
        assert reloaded.logo_override == ""
        assert reloaded.render_context.get("logo_image") == ""
