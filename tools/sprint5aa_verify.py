"""Sprint 5AA deterministic verifier: person-aware creative asset selection."""

from __future__ import annotations

import os
import sys
import tempfile

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandAsset, BrandProfileBuilder  # noqa: E402
from gui.models.render_context import RenderContext  # noqa: E402


def _img(folder: str, name: str, size: tuple[int, int]) -> str:
    path = os.path.join(folder, name)
    Image.new("RGB", size, (60, 90, 130)).save(path)
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


def _ctx(folder: str, *, assets: list[dict], contact_name: str = "Jane Smith", url: str = "https://example.com/agent/jane-smith/", logo: dict | None = None) -> RenderContext:
    data = {
        "url": url,
        "company": "Example Realty",
        "headline": "Jane Smith, Real Estate Agent",
        "screenshot_path": _img(folder, "screenshot.png", (1400, 900)),
        "assets": assets,
        "metadata": {"title": "Jane Smith, Real Estate Agent | Example Realty"},
    }
    if contact_name:
        data["person_context"] = {"contact_name": contact_name}
    if logo:
        data["logo"] = logo
    return RenderContext.from_brand_profile(BrandProfileBuilder.from_scrape_data(data), template="realtor")


def _check(name: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"{status}: {name}{' - ' + detail if detail else ''}")
    return condition


def main() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as folder:
        headshot = _img(folder, "jane-smith-photo.jpg", (250, 250))
        ctx = _ctx(folder, assets=[_asset(headshot, "https://example.com/Jane-Smith-Photo.jpg", (250, 250))])
        ok &= _check("person image preferred over screenshot", ctx.hero_image == headshot, ctx.hero_image)

        listing = _img(folder, "listing.jpg", (1800, 1200))
        ctx = _ctx(folder, assets=[_asset(listing, "https://example.com/mls/listing-property-gallery.jpg", (1800, 1200))])
        ok &= _check("listing image rejected as person hero", ctx.hero_image.endswith("screenshot.png"), ctx.hero_image)

        hero = _img(folder, "business-hero.jpg", (1200, 700))
        ctx = _ctx(folder, assets=[_asset(hero, "https://example.com/business-hero.jpg", (1200, 700))], contact_name="", url="https://example.com/")
        ok &= _check("generic business behavior preserved", ctx.hero_image == hero, ctx.hero_image)

        logo = _img(folder, "logo.png", (300, 120))
        ctx = _ctx(folder, assets=[], logo=_asset(logo, "https://example.com/logo.png", (300, 120), "logo"))
        ok &= _check("logo handling", ctx.logo_image == logo, ctx.logo_image)

        missing = os.path.join(folder, "missing-photo.jpg")
        ctx = _ctx(folder, assets=[_asset(missing, "https://example.com/Jane-Smith-Photo.jpg", (250, 250))])
        ok &= _check("screenshot fallback", ctx.hero_image.endswith("screenshot.png"), ctx.hero_image)

        stronger = _img(folder, "jane-smith-agent-profile-photo.jpg", (300, 300))
        weaker = _img(folder, "jane-smith-photo-small.jpg", (220, 220))
        assets = [
            _asset(weaker, "https://example.com/Jane-Smith-Photo.jpg", (220, 220)),
            _asset(stronger, "https://example.com/agent/Jane-Smith-profile-photo.jpg", (300, 300)),
        ]
        first = _ctx(folder, assets=assets)
        second = _ctx(folder, assets=assets)
        ok &= _check("deterministic output", first.hero_image == second.hero_image == stronger, first.hero_image)

    print("Sprint 5AA verifier:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())