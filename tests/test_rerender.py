"""Sprint 4B Phase A: local re-render and project ownership tests."""

from __future__ import annotations

import inspect
import os
import shutil
import tempfile
from collections.abc import Iterator
from unittest import mock

import pytest
from PIL import Image

from gui.engine_bridge import build_render_context, generate, re_render
from gui.models.mockup_concept import MockupConcept
from gui.models.mockup_request import MockupRequest
from gui.models.project import Project


@pytest.fixture
def tmp_output() -> Iterator[str]:
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_png(path: str, color: tuple[int, int, int] = (200, 40, 40)) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Image.new("RGB", (80, 80), color).save(path)
    return path


class TestBridgeOwnership:
    def test_generate_source_has_no_create_project(self) -> None:
        source = inspect.getsource(generate)
        assert "create_project" not in source
        assert "Project.create" not in source

    def test_generate_requires_output_path(self) -> None:
        result = generate(MockupRequest(url="https://example.com", template="contractor"))
        assert result.success is False
        assert "output_path" in result.message.lower()

    def test_re_render_source_has_no_scraper(self) -> None:
        source = inspect.getsource(re_render)
        # Ignore docstring mentions; assert no runtime scraper usage.
        body = source.split('"""', 2)[-1] if '"""' in source else source
        assert "WebsiteScraper(" not in body
        assert "WebsiteScraper" not in body
        assert "sync_playwright" not in body
        assert "playwright" not in body.lower()



class TestReRender:
    def test_re_render_writes_image_without_scraper(self, tmp_output: str) -> None:
        logo = _make_png(os.path.join(tmp_output, "logo.png"), (10, 120, 200))
        hero = _make_png(os.path.join(tmp_output, "hero.png"), (30, 30, 30))
        out = os.path.join(tmp_output, "concept_001.png")

        ctx = {
            "company": "Test Co",
            "subtitle": "Trusted locally",
            "logo_path": logo,
            "hero_path": hero,
            "screenshot_path": hero,
            "brand_colors": ["#112233"],
            "source_url": "https://example.com",
            "metadata": {"title": "Test Co", "description": "Trusted locally"},
            "quality_score": 88,
        }

        with mock.patch("gui.engine_bridge.WebsiteScraper") as scraper_cls:
            result = re_render(
                render_context=ctx,
                template="contractor",
                headline="Brand New Headline",
                cta="Call Today",
                company="Test Co",
                logo_path=logo,
                output_path=out,
            )
            scraper_cls.assert_not_called()


        assert result.success is True, result.message
        assert result.headline == "Brand New Headline"
        assert result.cta == "Call Today"
        assert os.path.isfile(out)
        assert os.path.getsize(out) > 0
        assert result.extra.get("local_rerender") is True

    def test_re_render_headline_change_rewrites_file(self, tmp_output: str) -> None:
        logo = _make_png(os.path.join(tmp_output, "logo.png"))
        out = os.path.join(tmp_output, "out.png")
        ctx = {
            "company": "Co",
            "logo_path": logo,
            "hero_path": "",
            "screenshot_path": "",
            "brand_colors": [],
            "source_url": "https://x.test",
            "metadata": {},
            "quality_score": 70,
        }

        r1 = re_render(
            render_context=ctx,
            template="contractor",
            headline="First",
            cta="Go",
            company="Co",
            logo_path=logo,
            output_path=out,
        )
        assert r1.success
        mtime1 = os.path.getmtime(out)
        size1 = os.path.getsize(out)

        import time

        time.sleep(0.05)

        r2 = re_render(
            render_context=ctx,
            template="contractor",
            headline="Second Headline Completely Different",
            cta="Go",
            company="Co",
            logo_path=logo,
            output_path=out,
        )
        assert r2.success
        assert os.path.getmtime(out) >= mtime1
        # File should still be a valid non-empty PNG after rewrite.
        assert os.path.getsize(out) > 0
        assert size1 > 0


class TestRenderContextPersistence:
    def test_build_and_round_trip_on_project(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="ctx_test")
        data = {
            "company": "ABC Roofing",
            "ad_copy": "Storm Damage Pros",
            "logo_path": "/tmp/logo.png",
            "screenshot_path": "/tmp/shot.png",
            "brand_colors": ["#ff0000", "#00ff00"],
            "url": "https://abc.example",
            "metadata": {"title": "ABC", "description": "Roofing"},
            "quality_score": 91,
        }
        ctx = build_render_context(
            data, template="contractor", source_url="https://abc.example"
        )
        project.set_render_context(ctx)
        project.logo_override = "/proj/assets/logo.png"
        c = MockupConcept.create(
            image_path="images/concept_001.png",
            template="contractor",
            headline="Storm Damage Pros",
            cta="Free Estimate",
            quality_score=91,
            company_name="ABC Roofing",
        )
        project.add_concept(c)
        project.save()

        loaded = Project.load(project.metadata_path)
        assert loaded.render_context["company_name"] == "ABC Roofing"
        assert loaded.render_context["brand_colors"] == ["#ff0000", "#00ff00"]
        assert loaded.render_context["source_url"] == "https://abc.example"
        assert loaded.render_context["template"] == "contractor"
        assert loaded.render_context["cta"]
        assert loaded.concepts[0].headline == "Storm Damage Pros"


    def test_update_selected_concept_marks_user_modified(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="edit_test")
        c = MockupConcept.create("a.png", "contractor", "Old", "CTA", 80, company_name="Co")
        project.add_concept(c)
        updated = project.update_selected_concept(headline="New Headline")
        assert updated is not None
        assert updated.headline == "New Headline"
        assert updated.user_modified is True
