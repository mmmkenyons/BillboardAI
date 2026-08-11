"""Sprint 5B research pipeline test suite (Qt-free, no network).

Exercises :class:`gui.services.research_pipeline.ResearchPipelineService`
orchestrating the REAL settings: a real ``ProjectStore``, the real
``BrandProfileBuilder``, and injected message/ad-concept engines so tests never
launch a browser or depend on a live website. A real ``MessageStrategy()`` /
``AdConcept()`` are used (all fields defaulted) to deterministically verify
structured state is persisted into the Project.
"""

from __future__ import annotations

import os

import pytest

from engine.ad_concept import AdConcept
from engine.brand_profile import BrandProfile, BrandProfileBuilder
from engine.message_strategy import MessageStrategy
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect
from gui.services.research_pipeline import ResearchPipelineService

# ---------------------------------------------------------------------------
# Fake scraper (no network)
# ---------------------------------------------------------------------------


class _ScraperRecord:
    """Shared mutable state between the fake scraper instances and the tests."""

    calls: list = []
    fail: bool = False
    fail_next: int = 0


_SAMPLE = {
    "company": "Acme Roofing",
    "website": "https://acme.com",
    "url": "https://acme.com",
    "headline": "Trusted Local Roofing",
    "ad_copy": "Free estimates",
    "brand_colors": ["#111111", "#eeeeee"],
    "logo_url": "",
    "hero_url": "",
    "metadata": {},
    "logo_path": "",
    "asset_paths": [],
    "logo": None,
    "screenshot_path": "",
    "business_intel": {},
}


class _Scraper:
    def __init__(self, url: str) -> None:
        self.url = url
        self.run_count = 0

    def run(self, progress_callback=None):
        self.run_count += 1
        _ScraperRecord.calls.append(self.url)
        if _ScraperRecord.fail or _ScraperRecord.fail_next > 0:
            if _ScraperRecord.fail_next > 0:
                _ScraperRecord.fail_next -= 1
            raise TimeoutError("connection reset")
        return dict(_SAMPLE)


def _service(project_root: str) -> ResearchPipelineService:
    _ScraperRecord.calls.clear()
    _ScraperRecord.fail = False
    _ScraperRecord.fail_next = 0
    pstore = ProjectStore(root=project_root)
    return ResearchPipelineService(
        project_store=pstore,
        scraper_factory=lambda url: _Scraper(url),
        brand_builder=BrandProfileBuilder.from_scrape_data,
        message_engine=lambda profile: [MessageStrategy()],
        concept_engine=lambda profile, strategies: [AdConcept()],
    )


def _prospect(**kw) -> Prospect:
    base = dict(
        company_name="Acme Roofing",
        website="https://acme.com",
        domain="acme.com",
    )
    base.update(kw)
    return Prospect(**base)


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------


class TestPipeline:
    def test_scraper_invoked_exactly_once(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        pipe.run(_prospect())
        assert _ScraperRecord.calls == ["https://acme.com"]

    def test_brand_profile_built(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        result = pipe.run(_prospect())
        assert result.success
        assert result.brand_profile is not None
        assert isinstance(result.brand_profile, BrandProfile)

    def test_strategies_generated(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        result = pipe.run(_prospect())
        assert result.strategies
        assert isinstance(result.strategies[0], MessageStrategy)

    def test_concepts_generated(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        result = pipe.run(_prospect())
        assert result.concepts
        assert isinstance(result.concepts[0], AdConcept)

    def test_project_created_on_success(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        result = pipe.run(_prospect())
        assert result.project_id
        assert pipe.project_store.exists(result.project_id)

    def test_project_populated_with_structured_data(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        result = pipe.run(_prospect())
        project = pipe.project_store.load(result.project_id)
        assert project.brand_profile
        assert project.strategies
        assert project.ad_concepts

    def test_prospect_id_associated(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        prospect = _prospect()
        result = pipe.run(prospect)
        project = pipe.project_store.load(result.project_id)
        assert project.metadata.get("prospect_id") == prospect.prospect_id

    def test_no_project_created_on_failed_scrape(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        _ScraperRecord.fail = True
        result = pipe.run(_prospect())
        assert result.success is False
        assert result.retryable is True
        assert pipe.project_store.list() == []

    def test_rerun_reuses_existing_project(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        prospect = _prospect()
        first = pipe.run(prospect)
        second = pipe.run(prospect)
        assert first.project_id == second.project_id
        projects = pipe.project_store.list()
        assert len(projects) == 1

    def test_pipeline_returns_error_details(self, tmp_path) -> None:
        pipe = _service(str(tmp_path / "projects"))
        _ScraperRecord.fail = True
        result = pipe.run(_prospect())
        assert result.error_type == "scrape_transient"
        assert result.retryable is True
        assert result.error
        assert result.success is False