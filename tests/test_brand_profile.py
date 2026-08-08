"""Sprint 2B: BrandProfile foundation tests."""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict

import pytest

from engine.brand_profile import (
    BRAND_PROFILE_VERSION,
    BrandAsset,
    BrandProfile,
    BrandProfileBuilder,
)
from gui.models.render_context import RenderContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset_dict(
    path: str = "/tmp/logo.png",
    source_url: str = "https://example.com/logo.png",
    asset_type: str = "logo",
    **kwargs: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "path": path,
        "source_url": source_url,
        "asset_type": asset_type,
        "mime_type": "image/png",
        "format": "PNG",
        "width": 200,
        "height": 80,
        "aspect_ratio": 2.5,
        "has_alpha": True,
        "file_size": 4096,
        "quality_score": 0.0,
        "selection_score": 0.0,
        "confidence": 1.0,
    }
    base.update(kwargs)
    return base


def _new_scraper_dict() -> Dict[str, Any]:
    """Simulate NEW scraper output with structured BrandAsset data."""
    return {
        "url": "https://www.acmeroofing.com",
        "company": "Acme Roofing",
        "headline": "Your Roof, Our Promise",
        "ad_copy": "Trusted local roofing experts since 1995.",
        "brand_colors": ["#CC0000", "#333333", "#FFFFFF"],
        "logo": _make_asset_dict(path="/cache/logo_acme.png", asset_type="logo"),
        "logo_path": "/cache/logo_acme.png",
        "logo_url": "https://acmeroofing.com/logo.png",
        "logo_score": 85,
        "hero_url": "https://acmeroofing.com/hero.jpg",
        "assets": [
            _make_asset_dict(
                path="/cache/asset_hero.jpg",
                source_url="https://acmeroofing.com/hero.jpg",
                asset_type="generic",
                mime_type="image/jpeg",
                format="JPEG",
                width=1200,
                height=600,
                aspect_ratio=2.0,
                has_alpha=False,
            ),
            _make_asset_dict(
                path="/cache/asset_icon.png",
                source_url="https://acmeroofing.com/icon.png",
                asset_type="generic",
                width=64,
                height=64,
                aspect_ratio=1.0,
            ),
        ],
        "asset_paths": ["/cache/asset_hero.jpg", "/cache/asset_icon.png"],
        "screenshot_path": "/cache/acmeroofing_screenshot.png",
        "screenshot_file": "/cache/acmeroofing_screenshot.png",
        "metadata": {
            "title": "Acme Roofing | Best Roofers",
            "description": "Acme Roofing provides top-quality roofing services.",
        },
        "quality_score": 88,
        "vision_score": 72,
        "scraped_at": "2026-08-08T12:00:00Z",
    }


def _legacy_scraper_dict() -> Dict[str, Any]:
    """Simulate OLD scraper output with only string paths."""
    return {
        "url": "https://www.oldcorp.com",
        "company": "Old Corp",
        "headline": "Quality Since 1980",
        "ad_copy": "Family owned and operated.",
        "brand_colors": ["#0000AA"],
        "logo_path": "/cache/logo_old.png",
        "logo_url": "https://oldcorp.com/logo.png",
        "logo_score": 70,
        "hero_url": "https://oldcorp.com/banner.jpg",
        "asset_paths": ["/cache/asset1.jpg", "/cache/asset2.png"],
        "screenshot_path": "/cache/oldcorp_screenshot.png",
        "metadata": {"title": "Old Corp"},
        "quality_score": 65,
        "vision_score": 55,
    }


# ---------------------------------------------------------------------------
# 1. Minimal BrandProfile construction
# ---------------------------------------------------------------------------

class TestMinimalConstruction:
    def test_empty_profile(self) -> None:
        bp = BrandProfile()
        assert bp.version == BRAND_PROFILE_VERSION
        assert bp.company_name == ""
        assert bp.website == ""
        assert bp.domain == ""
        assert bp.headline == ""
        assert bp.ad_copy == ""
        assert bp.colors == []
        assert bp.logo is None
        assert bp.assets == []
        assert bp.hero_assets == []
        assert bp.source_metadata == {}
        assert bp.screenshot_path == ""
        assert bp.quality_score == 0.0
        assert bp.vision_score == 0.0
        assert bp.scraped_at == ""

    def test_minimal_fields(self) -> None:
        bp = BrandProfile(company_name="TestCo", website="https://testco.com")
        assert bp.company_name == "TestCo"
        assert bp.website == "https://testco.com"
        assert bp.domain == ""  # not auto-derived
        assert bp.colors == []


# ---------------------------------------------------------------------------
# 2. Full BrandProfile construction
# ---------------------------------------------------------------------------

class TestFullConstruction:
    def test_full_profile(self) -> None:
        logo = BrandAsset(
            path="/tmp/logo.png",
            source_url="https://x.com/logo.png",
            asset_type="logo",
            mime_type="image/png",
            format="PNG",
            width=200,
            height=80,
            aspect_ratio=2.5,
            has_alpha=True,
            file_size=4096,
        )
        assets = [
            BrandAsset(
                path="/tmp/hero.jpg",
                source_url="https://x.com/hero.jpg",
                asset_type="generic",
                mime_type="image/jpeg",
                format="JPEG",
                width=1200,
                height=600,
                aspect_ratio=2.0,
            )
        ]
        bp = BrandProfile(
            company_name="Full Co",
            website="https://fullco.com",
            domain="fullco.com",
            headline="Best in Class",
            ad_copy="We deliver excellence.",
            colors=["#FF0000", "#00FF00"],
            logo=logo,
            assets=assets,
            hero_assets=assets,
            source_metadata={"title": "Full Co"},
            screenshot_path="/tmp/shot.png",
            quality_score=95.5,
            vision_score=88.0,
            scraped_at="2026-01-01T00:00:00Z",
        )
        assert bp.company_name == "Full Co"
        assert bp.website == "https://fullco.com"
        assert bp.domain == "fullco.com"
        assert bp.headline == "Best in Class"
        assert bp.ad_copy == "We deliver excellence."
        assert bp.colors == ["#FF0000", "#00FF00"]
        assert bp.logo is logo
        assert bp.logo.width == 200
        assert bp.assets == assets
        assert bp.hero_assets == assets
        assert bp.quality_score == 95.5
        assert bp.vision_score == 88.0


# ---------------------------------------------------------------------------
# 3. Nested BrandAsset serialization
# ---------------------------------------------------------------------------

class TestNestedSerialization:
    def test_logo_serializes_correctly(self) -> None:
        logo = BrandAsset(
            path="/tmp/logo.png",
            source_url="https://x.com/logo.png",
            asset_type="logo",
            mime_type="image/png",
            format="PNG",
            width=200,
            height=80,
            aspect_ratio=2.5,
            has_alpha=True,
            file_size=4096,
        )
        bp = BrandProfile(company_name="Co", logo=logo)
        d = bp.to_dict()
        assert d["logo"] is not None
        assert d["logo"]["path"] == "/tmp/logo.png"
        assert d["logo"]["format"] == "PNG"
        assert d["logo"]["width"] == 200
        assert d["logo"]["height"] == 80
        assert d["logo"]["has_alpha"] is True

    def test_assets_list_serializes(self) -> None:
        assets = [
            BrandAsset(path="/tmp/a.png", source_url="https://x.com/a.png"),
            BrandAsset(path="/tmp/b.jpg", source_url="https://x.com/b.jpg", format="JPEG"),
        ]
        bp = BrandProfile(company_name="Co", assets=assets)
        d = bp.to_dict()
        assert len(d["assets"]) == 2
        assert d["assets"][0]["path"] == "/tmp/a.png"
        assert d["assets"][1]["format"] == "JPEG"

    def test_none_logo_serializes_as_none(self) -> None:
        bp = BrandProfile(company_name="Co")
        d = bp.to_dict()
        assert d["logo"] is None


# ---------------------------------------------------------------------------
# 4. BrandProfile round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_full_round_trip(self) -> None:
        logo = BrandAsset(
            path="/tmp/logo.png",
            source_url="https://x.com/logo.png",
            asset_type="logo",
            mime_type="image/png",
            format="PNG",
            width=200,
            height=80,
            aspect_ratio=2.5,
            has_alpha=True,
            file_size=4096,
        )
        assets = [
            BrandAsset(
                path="/tmp/hero.jpg",
                source_url="https://x.com/hero.jpg",
                mime_type="image/jpeg",
                format="JPEG",
                width=1200,
                height=600,
                aspect_ratio=2.0,
            )
        ]
        original = BrandProfile(
            company_name="RoundTrip Inc",
            website="https://roundtrip.com",
            domain="roundtrip.com",
            headline="We Go Both Ways",
            ad_copy="Roundtrip solutions.",
            colors=["#111", "#222"],
            logo=logo,
            assets=assets,
            hero_assets=assets,
            source_metadata={"key": "value"},
            screenshot_path="/tmp/shot.png",
            quality_score=77.7,
            vision_score=66.6,
            scraped_at="2026-06-06T06:06:06Z",
        )
        d = original.to_dict()
        restored = BrandProfile.from_dict(d)
        assert restored.company_name == original.company_name
        assert restored.website == original.website
        assert restored.domain == original.domain
        assert restored.headline == original.headline
        assert restored.ad_copy == original.ad_copy
        assert restored.colors == original.colors
        assert restored.logo is not None
        assert restored.logo.path == logo.path
        assert restored.logo.width == logo.width
        assert restored.logo.format == logo.format
        assert len(restored.assets) == 1
        assert restored.assets[0].path == assets[0].path
        assert restored.hero_assets[0].path == assets[0].path
        assert restored.source_metadata == {"key": "value"}
        assert restored.screenshot_path == "/tmp/shot.png"
        assert restored.quality_score == 77.7
        assert restored.vision_score == 66.6
        assert restored.scraped_at == "2026-06-06T06:06:06Z"

    def test_round_trip_via_json(self) -> None:
        bp = BrandProfile(
            company_name="JSON Co",
            website="https://jsonco.com",
            domain="jsonco.com",
            colors=["#ABC"],
        )
        json_str = json.dumps(bp.to_dict())
        restored = BrandProfile.from_dict(json.loads(json_str))
        assert restored.company_name == "JSON Co"
        assert restored.colors == ["#ABC"]

    def test_empty_round_trip(self) -> None:
        bp = BrandProfile()
        d = bp.to_dict()
        restored = BrandProfile.from_dict(d)
        assert restored.company_name == ""
        assert restored.logo is None
        assert restored.assets == []


# ---------------------------------------------------------------------------
# 5. Missing optional fields default safely
# ---------------------------------------------------------------------------

class TestMissingFields:
    def test_empty_dict(self) -> None:
        bp = BrandProfile.from_dict({})
        assert bp.company_name == ""
        assert bp.website == ""
        assert bp.logo is None
        assert bp.assets == []
        assert bp.colors == []
        assert bp.quality_score == 0.0

    def test_none_input(self) -> None:
        bp = BrandProfile.from_dict(None)
        assert bp.company_name == ""
        assert bp.version == BRAND_PROFILE_VERSION

    def test_partial_dict(self) -> None:
        bp = BrandProfile.from_dict({"company_name": "Partial"})
        assert bp.company_name == "Partial"
        assert bp.website == ""
        assert bp.headline == ""
        assert bp.logo is None


# ---------------------------------------------------------------------------
# 6. Unknown persisted fields ignored safely
# ---------------------------------------------------------------------------

class TestUnknownFields:
    def test_extra_keys_ignored(self) -> None:
        d = {
            "company_name": "SafeCo",
            "website": "https://safeco.com",
            "future_field_v99": "should be ignored",
            "nested_extra": {"a": 1, "b": 2},
            "another_unknown": [1, 2, 3],
        }
        bp = BrandProfile.from_dict(d)
        assert bp.company_name == "SafeCo"
        assert bp.website == "https://safeco.com"
        # Round-trip should not include unknown fields
        out = bp.to_dict()
        assert "future_field_v99" not in out
        assert "nested_extra" not in out
        assert "another_unknown" not in out

    def test_unknown_in_nested_asset(self) -> None:
        d = {
            "company_name": "Co",
            "logo": {
                "path": "/tmp/x.png",
                "source_url": "https://x.com/x.png",
                "unknown_asset_field": 999,
            },
        }
        bp = BrandProfile.from_dict(d)
        assert bp.logo is not None
        assert bp.logo.path == "/tmp/x.png"
        # unknown_asset_field should be filtered by BrandAsset.from_dict


# ---------------------------------------------------------------------------
# 7. New scraper dict builds profile
# ---------------------------------------------------------------------------

class TestNewScraperDict:
    def test_builds_from_new_scraper(self) -> None:
        data = _new_scraper_dict()
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.company_name == "Acme Roofing"
        assert bp.website == "https://www.acmeroofing.com"
        assert bp.domain == "acmeroofing.com"
        assert bp.headline == "Your Roof, Our Promise"
        assert bp.ad_copy == "Trusted local roofing experts since 1995."
        assert bp.colors == ["#CC0000", "#333333", "#FFFFFF"]
        assert bp.logo is not None
        assert bp.logo.path == "/cache/logo_acme.png"
        assert bp.logo.format == "PNG"
        assert bp.logo.width == 200
        assert bp.logo.height == 80
        assert len(bp.assets) == 2
        assert bp.assets[0].path == "/cache/asset_hero.jpg"
        assert bp.assets[1].path == "/cache/asset_icon.png"
        assert len(bp.hero_assets) == 1
        assert bp.hero_assets[0].source_url == "https://acmeroofing.com/hero.jpg"
        assert bp.screenshot_path == "/cache/acmeroofing_screenshot.png"
        assert bp.quality_score == 88.0
        assert bp.vision_score == 72.0
        assert bp.scraped_at == "2026-08-08T12:00:00Z"
        assert bp.source_metadata["title"] == "Acme Roofing | Best Roofers"

    def test_legacy_paths_preserved_in_metadata(self) -> None:
        data = _new_scraper_dict()
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.source_metadata.get("legacy_logo_path") == "/cache/logo_acme.png"
        assert bp.source_metadata.get("legacy_asset_paths") == [
            "/cache/asset_hero.jpg",
            "/cache/asset_icon.png",
        ]


# ---------------------------------------------------------------------------
# 8. Legacy scraper dict builds profile
# ---------------------------------------------------------------------------

class TestLegacyScraperDict:
    def test_builds_from_legacy_scraper(self) -> None:
        data = _legacy_scraper_dict()
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.company_name == "Old Corp"
        assert bp.website == "https://www.oldcorp.com"
        assert bp.domain == "oldcorp.com"
        assert bp.headline == "Quality Since 1980"
        assert bp.ad_copy == "Family owned and operated."
        assert bp.colors == ["#0000AA"]
        # No structured logo — should be None
        assert bp.logo is None
        # No structured assets — should be empty
        assert bp.assets == []
        assert bp.hero_assets == []
        # Legacy paths preserved in source_metadata
        assert bp.source_metadata.get("legacy_logo_path") == "/cache/logo_old.png"
        assert bp.source_metadata.get("legacy_asset_paths") == [
            "/cache/asset1.jpg",
            "/cache/asset2.png",
        ]
        assert bp.screenshot_path == "/cache/oldcorp_screenshot.png"
        assert bp.quality_score == 65.0
        assert bp.vision_score == 55.0

    def test_legacy_no_fake_brand_assets(self) -> None:
        """Legacy scraper output should NOT fabricate BrandAsset objects."""
        data = _legacy_scraper_dict()
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.logo is None
        assert bp.assets == []
        assert bp.hero_assets == []


# ---------------------------------------------------------------------------
# 9. Company mapping
# ---------------------------------------------------------------------------

class TestCompanyMapping:
    def test_company_maps_to_company_name(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"company": "Mapped Co"})
        assert bp.company_name == "Mapped Co"

    def test_missing_company_defaults_empty(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.company_name == ""

    def test_company_none(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"company": None})
        assert bp.company_name == ""


# ---------------------------------------------------------------------------
# 10. Website/domain normalization
# ---------------------------------------------------------------------------

class TestWebsiteDomain:
    def test_url_maps_to_website(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"url": "https://www.example.com"}
        )
        assert bp.website == "https://www.example.com"

    def test_domain_extracted(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"url": "https://www.example.com/page"}
        )
        assert bp.domain == "example.com"

    def test_domain_strips_www(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"url": "https://www.example.com"}
        )
        # The _extract_domain method strips www.
        assert bp.domain == "example.com"

    def test_no_url(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.website == ""
        assert bp.domain == ""

    def test_bare_domain(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"url": "https://example.com"})
        assert bp.domain == "example.com"


# ---------------------------------------------------------------------------
# 11. Colors mapping
# ---------------------------------------------------------------------------

class TestColorsMapping:
    def test_colors_mapped(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"brand_colors": ["#FF0000", "#00FF00", "#0000FF"]}
        )
        assert bp.colors == ["#FF0000", "#00FF00", "#0000FF"]

    def test_colors_missing(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.colors == []

    def test_colors_not_a_list(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"brand_colors": "not-a-list"})
        assert bp.colors == []


# ---------------------------------------------------------------------------
# 12. Logo structured mapping
# ---------------------------------------------------------------------------

class TestLogoMapping:
    def test_structured_logo(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"logo": _make_asset_dict(path="/cache/logo.png", asset_type="logo")}
        )
        assert bp.logo is not None
        assert bp.logo.path == "/cache/logo.png"
        assert bp.logo.asset_type == "logo"
        assert bp.logo.format == "PNG"

    def test_logo_none(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"logo": None})
        assert bp.logo is None

    def test_logo_missing(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.logo is None

    def test_logo_invalid_dict(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"logo": {"not": "valid"}})
        assert bp.logo is None


# ---------------------------------------------------------------------------
# 13. Legacy logo_path fallback
# ---------------------------------------------------------------------------

class TestLegacyLogoFallback:
    def test_legacy_logo_path_preserved(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"logo_path": "/cache/old_logo.png"}
        )
        assert bp.logo is None  # No structured logo
        assert bp.source_metadata.get("legacy_logo_path") == "/cache/old_logo.png"

    def test_both_structured_and_legacy(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {
                "logo": _make_asset_dict(path="/cache/new_logo.png"),
                "logo_path": "/cache/old_logo.png",
            }
        )
        assert bp.logo is not None
        assert bp.logo.path == "/cache/new_logo.png"
        # Legacy path still preserved
        assert bp.source_metadata.get("legacy_logo_path") == "/cache/old_logo.png"


# ---------------------------------------------------------------------------
# 14. Asset list mapping
# ---------------------------------------------------------------------------

class TestAssetListMapping:
    def test_assets_mapped(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {
                "assets": [
                    _make_asset_dict(path="/cache/a.png"),
                    _make_asset_dict(path="/cache/b.jpg", format="JPEG"),
                ]
            }
        )
        assert len(bp.assets) == 2
        assert bp.assets[0].path == "/cache/a.png"
        assert bp.assets[1].format == "JPEG"

    def test_assets_empty(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"assets": []})
        assert bp.assets == []

    def test_assets_missing(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.assets == []

    def test_assets_with_invalid_entries(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {
                "assets": [
                    _make_asset_dict(path="/cache/good.png"),
                    {"not": "valid"},
                    None,
                    "string_instead_of_dict",
                ]
            }
        )
        assert len(bp.assets) == 1
        assert bp.assets[0].path == "/cache/good.png"


# ---------------------------------------------------------------------------
# 15. Metadata mapping
# ---------------------------------------------------------------------------

class TestMetadataMapping:
    def test_metadata_mapped(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"metadata": {"title": "Test", "description": "Desc"}}
        )
        assert bp.source_metadata == {"title": "Test", "description": "Desc"}

    def test_metadata_missing(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.source_metadata == {}

    def test_metadata_not_a_dict(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({"metadata": "string"})
        assert bp.source_metadata == {}


# ---------------------------------------------------------------------------
# 16. Quality/vision score mapping
# ---------------------------------------------------------------------------

class TestScoreMapping:
    def test_scores_mapped(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"quality_score": 88, "vision_score": 72}
        )
        assert bp.quality_score == 88.0
        assert bp.vision_score == 72.0

    def test_scores_missing(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data({})
        assert bp.quality_score == 0.0
        assert bp.vision_score == 0.0

    def test_scores_invalid(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"quality_score": "not-a-number", "vision_score": None}
        )
        assert bp.quality_score == 0.0
        assert bp.vision_score == 0.0


# ---------------------------------------------------------------------------
# 17. Raw HTML is not stored in BrandProfile
# ---------------------------------------------------------------------------

class TestNoRawHtml:
    def test_html_not_stored(self) -> None:
        data = _new_scraper_dict()
        data["html"] = "<html><body>HUGE PAGE CONTENT...</body></html>"
        bp = BrandProfileBuilder.from_scrape_data(data)
        d = bp.to_dict()
        assert "html" not in d
        # source_metadata should not contain html either
        assert "html" not in bp.source_metadata

    def test_html_not_in_source_metadata(self) -> None:
        bp = BrandProfileBuilder.from_scrape_data(
            {"metadata": {"html": "<p>should not leak</p>"}}
        )
        # The metadata dict itself could have an "html" key if the scraper put it there,
        # but BrandProfileBuilder doesn't add raw HTML from the top-level "html" key.
        # The top-level "html" key is simply not mapped.
        data = _new_scraper_dict()
        data["html"] = "<massive>content</massive>"
        bp = BrandProfileBuilder.from_scrape_data(data)
        d = bp.to_dict()
        assert "html" not in d


# ---------------------------------------------------------------------------
# 18. RenderContext.from_brand_profile()
# ---------------------------------------------------------------------------

class TestRenderContextFromBrandProfile:
    def test_basic_mapping(self) -> None:
        logo = BrandAsset(
            path="/tmp/logo.png",
            source_url="https://x.com/logo.png",
            asset_type="logo",
            mime_type="image/png",
            format="PNG",
            width=200,
            height=80,
            aspect_ratio=2.5,
        )
        hero = BrandAsset(
            path="/tmp/hero.jpg",
            source_url="https://x.com/hero.jpg",
            mime_type="image/jpeg",
            format="JPEG",
            width=1200,
            height=600,
            aspect_ratio=2.0,
        )
        bp = BrandProfile(
            company_name="Test Brand",
            website="https://testbrand.com",
            domain="testbrand.com",
            headline="Amazing Products",
            ad_copy="Buy our amazing products today.",
            colors=["#FF0000", "#0000FF"],
            logo=logo,
            hero_assets=[hero],
            source_metadata={"description": "Test description"},
            screenshot_path="/tmp/screenshot.png",
            quality_score=92.0,
            vision_score=85.0,
        )
        ctx = RenderContext.from_brand_profile(bp, template="contractor")
        assert ctx.company_name == "Test Brand"
        assert ctx.headline == "Buy our amazing products today."
        assert ctx.logo_image == "/tmp/logo.png"
        assert ctx.hero_image == "/tmp/hero.jpg"
        assert ctx.background_image == "/tmp/screenshot.png"
        assert ctx.quality_score == 92.0
        assert ctx.source_url == "https://testbrand.com"
        assert ctx.brand_colors == ["#FF0000", "#0000FF"]
        assert ctx.template == "contractor"
        assert ctx.cta  # from template
        assert ctx.primary_color
        assert ctx.fonts["family"]

    def test_logo_fallback_to_legacy(self) -> None:
        bp = BrandProfile(
            company_name="Legacy Brand",
            source_metadata={"legacy_logo_path": "/cache/old_logo.png"},
        )
        ctx = RenderContext.from_brand_profile(bp, template="contractor")
        assert ctx.logo_image == "/cache/old_logo.png"

    def test_hero_fallback_to_screenshot(self) -> None:
        bp = BrandProfile(
            company_name="No Hero",
            screenshot_path="/tmp/screenshot.png",
        )
        ctx = RenderContext.from_brand_profile(bp, template="contractor")
        assert ctx.hero_image == "/tmp/screenshot.png"

    def test_subtitle_from_metadata(self) -> None:
        bp = BrandProfile(
            company_name="Sub Co",
            headline="Main Headline",
            source_metadata={"description": "A great subtitle"},
        )
        ctx = RenderContext.from_brand_profile(bp, template="contractor")
        assert ctx.subtitle == "A great subtitle"

    def test_subtitle_deduped_from_headline(self) -> None:
        bp = BrandProfile(
            company_name="Dedup Co",
            headline="Same Text",
            source_metadata={"description": "Same Text"},
        )
        ctx = RenderContext.from_brand_profile(bp, template="contractor")
        assert ctx.subtitle == ""

    def test_type_error_on_wrong_type(self) -> None:
        with pytest.raises(TypeError):
            RenderContext.from_brand_profile({"not": "a profile"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 19. RenderContext.from_scrape() backward compatibility
# ---------------------------------------------------------------------------

class TestFromScrapeBackwardCompat:
    def test_from_scrape_still_works(self) -> None:
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
        assert ctx.company_name == "ABC Roofing"
        assert ctx.headline == "Storm Damage Pros"
        assert ctx.logo_image == "/tmp/logo.png"
        assert ctx.hero_image == "/tmp/shot.png"
        assert ctx.quality_score == 90.0
        assert ctx.source_url == "https://abc.example"
        assert ctx.brand_colors == ["#111111", "#222222"]
        assert ctx.cta  # from template

    def test_from_scrape_with_structured_logo(self) -> None:
        scrape = {
            "company": "Modern Co",
            "headline": "Modern Solutions",
            "url": "https://modern.example",
            "logo": _make_asset_dict(path="/cache/modern_logo.png"),
            "logo_path": "/cache/modern_logo.png",
            "screenshot_path": "/cache/shot.png",
            "brand_colors": ["#ABC"],
            "quality_score": 80,
        }
        ctx = RenderContext.from_scrape(scrape, template="contractor")
        assert ctx.company_name == "Modern Co"
        assert ctx.logo_image == "/cache/modern_logo.png"

    def test_from_scrape_legacy_no_logo(self) -> None:
        scrape = {
            "company": "Old School",
            "headline": "Old Ways",
            "url": "https://old.example",
            "logo_path": "/cache/old_logo.png",
            "screenshot_path": "/cache/shot.png",
            "quality_score": 60,
        }
        ctx = RenderContext.from_scrape(scrape, template="contractor")
        assert ctx.company_name == "Old School"
        assert ctx.logo_image == "/cache/old_logo.png"


# ---------------------------------------------------------------------------
# 20. EngineBridge generation path uses BrandProfile
# ---------------------------------------------------------------------------

class TestEngineBridgeBrandProfile:
    def test_build_render_context_uses_brand_profile(self) -> None:
        """Verify build_render_context internally uses BrandProfile path."""
        from gui.engine_bridge import build_render_context

        data = _new_scraper_dict()
        ctx = build_render_context(data, template="contractor", source_url=data["url"])
        assert ctx["company_name"] == "Acme Roofing"
        assert ctx["headline"] == "Trusted local roofing experts since 1995."
        assert ctx["logo_image"] == "/cache/logo_acme.png"
        assert ctx["hero_image"] == "/cache/asset_hero.jpg"
        assert ctx["quality_score"] == 88.0
        assert ctx["source_url"] == "https://www.acmeroofing.com"
        assert ctx["brand_colors"] == ["#CC0000", "#333333", "#FFFFFF"]
        assert ctx["version"] == 1
        assert ctx["cta"]

    def test_build_render_context_legacy(self) -> None:
        from gui.engine_bridge import build_render_context

        data = _legacy_scraper_dict()
        ctx = build_render_context(data, template="contractor", source_url=data["url"])
        assert ctx["company_name"] == "Old Corp"
        assert ctx["headline"] == "Family owned and operated."
        assert ctx["logo_image"] == "/cache/logo_old.png"
        assert ctx["hero_image"] == "/cache/oldcorp_screenshot.png"
        assert ctx["quality_score"] == 65.0


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 21. Hero URL preservation (Sprint 2B final patch)
# ---------------------------------------------------------------------------

class TestHeroUrlPreservation:
    def test_hero_url_preserved_when_no_matching_asset(self) -> None:
        """hero_url is preserved even when no BrandAsset matches."""
        data = _new_scraper_dict()
        # hero_url is set but no asset has that source_url
        data["hero_url"] = "https://acmeroofing.com/hero.jpg"
        # Remove the matching asset so there's no match
        data["assets"] = []
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.hero_url == "https://acmeroofing.com/hero.jpg"
        assert bp.hero_assets == []

    def test_hero_url_preserved_when_matching_asset_exists(self) -> None:
        """hero_url is preserved alongside a matching BrandAsset."""
        data = _new_scraper_dict()
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.hero_url == "https://acmeroofing.com/hero.jpg"
        assert len(bp.hero_assets) == 1
        assert bp.hero_assets[0].source_url == "https://acmeroofing.com/hero.jpg"

    def test_matching_asset_populates_hero_assets(self) -> None:
        """When hero_url matches an asset's source_url, it goes into hero_assets."""
        data = _new_scraper_dict()
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert len(bp.hero_assets) == 1
        assert bp.hero_assets[0].path == "/cache/asset_hero.jpg"
        assert bp.hero_assets[0].format == "JPEG"

    def test_unmatched_hero_does_not_create_fake_brand_asset(self) -> None:
        """No BrandAsset is fabricated when hero_url has no match."""
        data = _new_scraper_dict()
        data["hero_url"] = "https://other.com/hero.jpg"
        data["assets"] = []  # no assets at all
        bp = BrandProfileBuilder.from_scrape_data(data)
        assert bp.hero_url == "https://other.com/hero.jpg"
        assert bp.hero_assets == []
        # Verify no fake BrandAsset was created
        assert bp.logo is not None  # logo still exists
        assert bp.assets == []

    def test_hero_url_serialization_round_trip(self) -> None:
        """hero_url survives to_dict → from_dict round-trip."""
        bp = BrandProfile(
            company_name="HeroTest",
            hero_url="https://example.com/hero.jpg",
            hero_assets=[
                BrandAsset(
                    path="/tmp/hero.jpg",
                    source_url="https://example.com/hero.jpg",
                    mime_type="image/jpeg",
                    format="JPEG",
                    width=1200,
                    height=600,
                    aspect_ratio=2.0,
                )
            ],
        )
        d = bp.to_dict()
        assert d["hero_url"] == "https://example.com/hero.jpg"
        assert len(d["hero_assets"]) == 1

        restored = BrandProfile.from_dict(d)
        assert restored.hero_url == "https://example.com/hero.jpg"
        assert len(restored.hero_assets) == 1
        assert restored.hero_assets[0].source_url == "https://example.com/hero.jpg"

    def test_old_profile_without_hero_url_still_loads(self) -> None:
        """Old persisted data without hero_url deserializes safely."""
        d = {
            "company_name": "OldProfile",
            "website": "https://old.example",
            "headline": "Old Headline",
            "colors": ["#111"],
            "hero_assets": [],
            "quality_score": 50,
        }
        bp = BrandProfile.from_dict(d)
        assert bp.company_name == "OldProfile"
        assert bp.hero_url == ""  # default
        assert bp.hero_assets == []

    def test_render_context_hero_behavior_unchanged(self) -> None:
        """RenderContext.from_brand_profile hero behavior is backward-compatible."""
        # Case 1: hero_assets present → uses hero_assets[0].path
        hero = BrandAsset(
            path="/tmp/hero.jpg",
            source_url="https://x.com/hero.jpg",
            mime_type="image/jpeg",
            format="JPEG",
            width=1200,
            height=600,
            aspect_ratio=2.0,
        )
        bp = BrandProfile(
            company_name="HeroCo",
            hero_url="https://x.com/hero.jpg",
            hero_assets=[hero],
            screenshot_path="/tmp/screenshot.png",
        )
        ctx = RenderContext.from_brand_profile(bp, template="contractor")
        assert ctx.hero_image == "/tmp/hero.jpg"

        # Case 2: no hero_assets → falls back to screenshot
        bp2 = BrandProfile(
            company_name="NoHeroCo",
            hero_url="https://x.com/hero.jpg",
            hero_assets=[],
            screenshot_path="/tmp/screenshot.png",
        )
        ctx2 = RenderContext.from_brand_profile(bp2, template="contractor")
        assert ctx2.hero_image == "/tmp/screenshot.png"

        # Case 3: hero_url is a remote URL — never used as local render path
        bp3 = BrandProfile(
            company_name="RemoteHero",
            hero_url="https://x.com/remote.jpg",
            hero_assets=[],
            screenshot_path="",
        )
        ctx3 = RenderContext.from_brand_profile(bp3, template="contractor")
        # hero_image should be empty (no local hero, no screenshot)
        assert ctx3.hero_image == ""


# Future field defaults (Sprint 2C readiness)
# ---------------------------------------------------------------------------

class TestFutureFields:
    def test_future_fields_have_safe_defaults(self) -> None:
        bp = BrandProfile()
        assert bp.phone == ""
        assert bp.location == ""
        assert bp.service_area == ""
        assert bp.services == []
        assert bp.categories == []
        assert bp.differentiators == []
        assert bp.trust_signals == []
        assert bp.awards == []
        assert bp.certifications == []
        assert bp.guarantees == []
        assert bp.years_in_business == ""

    def test_future_fields_survive_round_trip(self) -> None:
        bp = BrandProfile(
            company_name="FutureCo",
            phone="555-0100",
            location="Austin, TX",
            services=["Roofing", "Siding"],
            years_in_business="25",
        )
        d = bp.to_dict()
        assert d["phone"] == "555-0100"
        assert d["location"] == "Austin, TX"
        assert d["services"] == ["Roofing", "Siding"]
        assert d["years_in_business"] == "25"

        restored = BrandProfile.from_dict(d)
        assert restored.phone == "555-0100"
        assert restored.location == "Austin, TX"
        assert restored.services == ["Roofing", "Siding"]
        assert restored.years_in_business == "25"

    def test_future_fields_not_extracted_from_scraper(self) -> None:
        """Builder should NOT extract future fields in Sprint 2B."""
        data = _new_scraper_dict()
        data["phone"] = "555-1234"  # If scraper happened to have it
        bp = BrandProfileBuilder.from_scrape_data(data)
        # Builder does not map phone — it stays default
        assert bp.phone == ""