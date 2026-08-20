from __future__ import annotations

import os

from PIL import Image

from engine.brand_profile import BrandAsset, BrandProfileBuilder
from gui.models.render_context import RenderContext


def _img(tmp_path, name: str, size: tuple[int, int]) -> str:
    path = os.path.join(str(tmp_path), name)
    Image.new("RGB", size, (80, 120, 160)).save(path)
    return path


def _asset(path: str, url: str, size: tuple[int, int], asset_type: str = "generic") -> dict:
    width, height = size
    return BrandAsset(
        path=path,
        source_url=url,
        asset_type=asset_type,
        mime_type="image/jpeg",
        format="JPEG",
        width=width,
        height=height,
        aspect_ratio=round(width / height, 6),
    ).to_dict()


def _scrape(tmp_path, *, assets: list[dict], person_context: dict | None = None, hero_url: str = "") -> dict:
    screenshot = _img(tmp_path, "screenshot.png", (1400, 900))
    return {
        "url": "https://example.com/agent/jane-smith/",
        "company": "Example Realty",
        "headline": "Jane Smith, Real Estate Agent",
        "assets": assets,
        "hero_url": hero_url,
        "screenshot_path": screenshot,
        "metadata": {"title": "Jane Smith, Real Estate Agent | Example Realty"},
        "person_context": person_context or {"contact_name": "Jane Smith"},
    }


def _ctx(data: dict) -> RenderContext:
    return RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(data), template="realtor")


def test_person_headshot_beats_large_screenshot(tmp_path) -> None:
    headshot = _img(tmp_path, "jane-smith-photo.jpg", (250, 250))
    ctx = _ctx(_scrape(tmp_path, assets=[_asset(headshot, "https://example.com/uploads/Jane-Smith-Photo.jpg", (250, 250))]))
    assert ctx.hero_image == headshot
    assert ctx.background_image.endswith("screenshot.png")
    assert ctx.opportunity_context["asset_selection"]["selected_hero_role"] == "PERSON_PROFILE"


def test_dom_alt_context_identifies_person_headshot(tmp_path) -> None:
    headshot = _img(tmp_path, "opaque-cdn-token.webp", (250, 250))
    asset = BrandAsset(
        path=headshot,
        source_url="https://cdn.example.net/opaque-token/f:webp/source.jpg",
        asset_type="generic",
        mime_type="image/webp",
        format="WEBP",
        width=250,
        height=250,
        aspect_ratio=1.0,
        evidence=["dom_context:Meridith Hoffman Photo profile agent"],
    ).to_dict()
    data = _scrape(
        tmp_path,
        assets=[asset],
        person_context={"contact_name": "Meridith Hoffman"},
    )
    data["url"] = "https://example.com/agent/meridith-hoffman/"
    data["metadata"] = {"title": "Meridith Hoffman, Real Estate Agent"}
    ctx = _ctx(data)
    assert ctx.hero_image == headshot
    assert ctx.opportunity_context["asset_selection"]["selected_hero_role"] == "PERSON_PROFILE"


def test_person_headshot_and_person_header_split_roles(tmp_path) -> None:
    headshot = _img(tmp_path, "jane-smith-photo.jpg", (250, 250))
    header = _img(tmp_path, "jane-smith-header.jpg", (1600, 800))
    ctx = _ctx(
        _scrape(
            tmp_path,
            assets=[
                _asset(headshot, "https://example.com/uploads/Jane-Smith-Photo.jpg", (250, 250)),
                _asset(header, "https://example.com/uploads/Jane-Smith-Header-Image.jpg", (1600, 800)),
            ],
        )
    )
    assert ctx.hero_image == headshot
    assert ctx.background_image == header


def test_listing_images_do_not_become_person_hero(tmp_path) -> None:
    listing = _img(tmp_path, "listing.jpg", (1800, 1200))
    ctx = _ctx(_scrape(tmp_path, assets=[_asset(listing, "https://example.com/mls/listing-property-gallery.jpg", (1800, 1200))]))
    assert ctx.hero_image.endswith("screenshot.png")
    assert ctx.opportunity_context["asset_selection"]["property_listing_candidates"] == 1


def test_named_tiny_avatar_rejected(tmp_path) -> None:
    tiny = _img(tmp_path, "jane-smith-avatar.jpg", (80, 80))
    ctx = _ctx(_scrape(tmp_path, assets=[_asset(tiny, "https://example.com/Jane-Smith-avatar.jpg", (80, 80))]))
    assert ctx.hero_image.endswith("screenshot.png")


def test_no_person_evidence_keeps_generic_hero_behavior(tmp_path) -> None:
    hero = _img(tmp_path, "business-hero.jpg", (1200, 700))
    data = _scrape(
        tmp_path,
        assets=[_asset(hero, "https://example.com/business-hero.jpg", (1200, 700))],
        person_context={},
        hero_url="https://example.com/business-hero.jpg",
    )
    data["url"] = "https://example.com/"
    data["metadata"] = {"title": "Example Realty"}
    data.pop("person_context", None)
    ctx = _ctx(data)
    assert ctx.hero_image == hero


def test_company_logo_reaches_render_context(tmp_path) -> None:
    logo = _img(tmp_path, "logo.png", (300, 120))
    data = _scrape(tmp_path, assets=[])
    data["logo"] = _asset(logo, "https://example.com/logo.png", (300, 120), asset_type="logo")
    data["logo_path"] = logo
    ctx = _ctx(data)
    assert ctx.logo_image == logo


def test_person_headshot_download_failure_falls_back_to_screenshot(tmp_path) -> None:
    missing = os.path.join(str(tmp_path), "missing-jane-smith-photo.jpg")
    ctx = _ctx(_scrape(tmp_path, assets=[_asset(missing, "https://example.com/Jane-Smith-Photo.jpg", (250, 250))]))
    assert ctx.hero_image.endswith("screenshot.png")


def test_multiple_person_candidates_are_deterministic(tmp_path) -> None:
    weaker = _img(tmp_path, "jane-smith-photo-small.jpg", (220, 220))
    stronger = _img(tmp_path, "jane-smith-agent-profile-photo.jpg", (300, 300))
    data = _scrape(
        tmp_path,
        assets=[
            _asset(weaker, "https://example.com/Jane-Smith-Photo.jpg", (220, 220)),
            _asset(stronger, "https://example.com/agent/Jane-Smith-profile-photo.jpg", (300, 300)),
        ],
    )
    first = _ctx(data)
    second = _ctx(data)
    assert first.hero_image == second.hero_image == stronger


def test_screenshot_remains_available_fallback(tmp_path) -> None:
    ctx = _ctx(_scrape(tmp_path, assets=[]))
    assert ctx.hero_image.endswith("screenshot.png")
    assert ctx.background_image.endswith("screenshot.png")