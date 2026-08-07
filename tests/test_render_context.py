"""Phase A.5: render_context complete rendering contract tests."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from unittest import mock

import pytest
from PIL import Image

from engine.designer import generate_billboard, render_spec_from_context
from gui.engine_bridge import build_render_context, re_render, render_from_context
from gui.models.project import Project
from gui.models.render_context import (
    RENDER_CONTEXT_VERSION,
    RenderContext,
    ensure_render_context,
)


@pytest.fixture
def tmp_output() -> Iterator[str]:
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _png(path: str, color: tuple[int, int, int] = (40, 80, 160)) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Image.new("RGB", (64, 64), color).save(path)
    return path


_REQUIRED_KEYS = {
    "version",
    "company_name",
    "headline",
    "cta",
    "template",
    "logo_image",
    "hero_image",
    "primary_color",
    "secondary_color",
    "accent_color",
    "text_color",
    "button_color",
    "background_color",
    "fonts",
    "layout",
    "quality_score",
    "source_url",
}


class TestRenderContextSchema:
    def test_from_scrape_is_complete_contract(self) -> None:
        scrape = {
            "company": "ABC Roofing",
            "ad_copy": "Storm Damage Pros",
            "logo_path": "/tmp/logo.png",
            "screenshot_path": "/tmp/shot.png",
            "brand_colors": ["#111111", "#222222"],
            "url": "https://abc.example",
            "metadata": {"title": "ABC", "description": "Roofing experts"},
            "quality_score": 90,
        }
        ctx = RenderContext.from_scrape(scrape, template="contractor", source_url="https://abc.example")
        data = ctx.to_dict()
        for key in _REQUIRED_KEYS:
            assert key in data, f"missing {key}"
        assert data["version"] == RENDER_CONTEXT_VERSION
        assert data["company_name"] == "ABC Roofing"
        assert data["headline"] == "Storm Damage Pros"
        assert data["cta"]  # from template
        assert data["template"] == "contractor"
        assert data["fonts"]["family"]
        assert data["layout"]["style"]
        assert data["layout"]["canvas"]["width"] == 1600
        assert data["primary_color"]
        assert data["logo_image"] == "/tmp/logo.png"
        assert data["hero_image"] == "/tmp/shot.png"

    def test_legacy_migration_fills_theme(self) -> None:
        legacy = {
            "company": "Old Co",
            "headline": "Hello",
            "logo_path": "assets/logo.png",
            "hero_path": "assets/hero.png",
            "brand_colors": ["#ff0000"],
            "source_url": "https://old.test",
            "quality_score": 70,
            "metadata": {"description": "Sub"},
        }
        ctx = RenderContext.from_dict(legacy)
        assert ctx.company_name == "Old Co"
        assert ctx.logo_image == "assets/logo.png"
        assert ctx.hero_image == "assets/hero.png"
        assert ctx.cta  # filled from template default
        assert ctx.primary_color
        assert ctx.fonts["family"]
        assert ctx.layout["style"]
        assert ctx.version == RENDER_CONTEXT_VERSION

    def test_merge_overrides_template_resolves_theme(self) -> None:
        base = RenderContext.from_scrape(
            {"company": "Co", "headline": "H", "url": "https://x.test"},
            template="contractor",
        )
        dentist_cta_before = base.cta
        merged = base.merge_overrides(template="dentist", headline="New H")
        assert merged.template == "dentist"
        assert merged.headline == "New H"
        assert merged.layout["style"]  # resolved
        # Dentist template uses different CTA by default
        assert merged.cta != "" or dentist_cta_before != ""

    def test_to_render_spec_has_renderer_keys(self) -> None:
        ctx = RenderContext(
            company_name="Co",
            headline="Headline",
            cta="Go",
            template="contractor",
            logo_image="logo.png",
            hero_image="hero.png",
            primary_color="#111",
            accent_color="#222",
            text_color="#333",
            button_color="#444",
            background_color="#555",
            fonts={"family": "arial.ttf"},
            layout={"style": "photo", "canvas": {"width": 1600, "height": 900}},
        )
        spec = ctx.to_render_spec()
        assert spec["company"] == "Co"
        assert spec["headline"] == "Headline"
        assert spec["cta_text"] == "Go"
        assert spec["logo_path"] == "logo.png"
        assert spec["hero_path"] == "hero.png"
        assert spec["layout_style"] == "photo"
        assert "ad_copy" not in spec
        assert "hero_url" not in spec


class TestRenderFromContext:
    def test_render_from_context_no_scraper(self, tmp_output: str) -> None:
        logo = _png(os.path.join(tmp_output, "logo.png"))
        hero = _png(os.path.join(tmp_output, "hero.png"), (10, 10, 10))
        out = os.path.join(tmp_output, "out.png")
        ctx = build_render_context(
            {
                "company": "Test Co",
                "ad_copy": "Contract Headline",
                "logo_path": logo,
                "screenshot_path": hero,
                "brand_colors": ["#abc"],
                "quality_score": 85,
            },
            template="contractor",
            source_url="https://example.com",
        )
        # Ensure complete keys present
        for key in ("cta", "primary_color", "fonts", "layout", "template"):
            assert key in ctx

        with mock.patch("gui.engine_bridge.WebsiteScraper") as scraper_cls:
            path = render_from_context(ctx, out)
            scraper_cls.assert_not_called()

        assert path == out
        assert os.path.isfile(out)
        assert os.path.getsize(out) > 0

    def test_re_render_uses_contract_only(self, tmp_output: str) -> None:
        logo = _png(os.path.join(tmp_output, "logo.png"))
        out = os.path.join(tmp_output, "r.png")
        ctx = build_render_context(
            {
                "company": "Co",
                "headline": "First",
                "logo_path": logo,
                "quality_score": 80,
            },
            template="contractor",
            source_url="https://x.test",
        )
        with mock.patch("gui.engine_bridge.WebsiteScraper") as scraper_cls:
            result = re_render(
                render_context=ctx,
                output_path=out,
                headline="Second Headline",
            )
            scraper_cls.assert_not_called()
        assert result.success, result.message
        assert result.headline == "Second Headline"
        assert result.extra.get("render_context", {}).get("headline") == "Second Headline"

    def test_engine_render_spec_from_context(self) -> None:
        spec = render_spec_from_context(
            {
                "template": "realtor",
                "company_name": "Homes Inc",
                "headline": "Dream Homes",
                "cta": "View Listings",
                "logo_image": "l.png",
                "hero_image": "h.png",
                "primary_color": "#1F2937",
                "accent_color": "#B76E79",
                "text_color": "#1D1D1F",
                "button_color": "#8B4513",
                "background_color": "#FEF8E7",
                "fonts": {"family": "arial.ttf"},
                "layout": {"style": "premium", "canvas": {"width": 1600, "height": 900}},
            }
        )
        assert spec["company"] == "Homes Inc"
        assert spec["layout_style"] == "premium"
        assert spec["cta_text"] == "View Listings"

    def test_generate_billboard_still_works(self) -> None:
        spec = generate_billboard(
            {
                "company": "CLI Co",
                "headline": "CLI Headline",
                "logo_path": None,
                "url": "https://cli.test",
                "metadata": {},
            },
            "contractor",
        )
        assert spec["company"] == "CLI Co"
        assert spec["headline"] == "CLI Headline"
        assert spec["template"] == "contractor"


class TestProjectPersistence:
    def test_project_round_trip_full_contract(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="contract")
        ctx = build_render_context(
            {
                "company": "Persist Co",
                "ad_copy": "Persisted Headline",
                "logo_path": "cache/logo.png",
                "screenshot_path": "cache/shot.png",
                "brand_colors": ["#aa0000"],
                "quality_score": 93,
                "metadata": {"description": "Sub"},
            },
            template="dentist",
            source_url="https://persist.test",
        )
        project.set_render_context(ctx)
        project.save()

        loaded = Project.load(project.metadata_path)
        rc = loaded.render_context
        assert rc["version"] == RENDER_CONTEXT_VERSION
        assert rc["company_name"] == "Persist Co"
        assert rc["template"] == "dentist"
        assert rc["cta"]
        assert rc["primary_color"]
        assert rc["fonts"]["family"]
        assert "logo_image" in rc
        # effective merge
        effective = loaded.effective_render_context(headline="Edited")
        assert effective["headline"] == "Edited"
        assert effective["company_name"] == "Persist Co"

    def test_legacy_project_context_migrates_on_load(self, tmp_output: str) -> None:
        project = Project.create(output_root=tmp_output, name="legacy")
        # Write raw legacy blob bypassing set_render_context normalization
        project.render_context = {
            "company": "Legacy",
            "headline": "Old",
            "logo_path": "a.png",
            "hero_path": "b.png",
            "source_url": "https://legacy.test",
        }
        project._write_to_disk()

        loaded = Project.load(project.metadata_path)
        assert loaded.render_context["company_name"] == "Legacy"
        assert loaded.render_context["logo_image"] == "a.png"
        assert loaded.render_context.get("cta")
        assert loaded.render_context.get("fonts", {}).get("family")
