"""Sprint 2H real-world verification: final physical sales mockups.

Exercises the REAL Jim Woods pipeline end-to-end through the one clean
orchestration path added in Sprint 2H:

    WebsiteScraper
        -> BrandProfile
        -> MessageStrategy
        -> AdConcept
        -> CreativeLayoutEngine -> CreativeLayoutSpec
        -> CreativeArtworkRenderer -> rectangular artwork (at the physical
           template's intended aspect ratio)
        -> renderer.render_artwork_into_scene -> perspective warp -> mockup

Renders 3 composition families (BRAND_DOMINANT, MESSAGE_DOMINANT,
LOCAL_AUTHORITY) x 2 calibrated physical templates = 6 FINAL SALES MOCKUPS.

If the live site is unreachable, it falls back to the deterministic engines fed
with the real, documented Jim Woods evidence (never fabricated concepts), exactly
like the Sprint 2G verifier. The 6 output PNGs are saved under the git-ignored
output/mockups/sprint2h/ directory for HUMAN REVIEW.

Run:
    python tools/sprint2h_verify.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.ad_concept import (  # noqa: E402
    BRAND_DOMINANT,
    LOCAL_AUTHORITY,
    MESSAGE_DOMINANT,
)
from engine.brand_profile import BrandAsset, BrandProfile  # noqa: E402
from engine.mockup import render_concept_mockup  # noqa: E402
from engine.message_strategy import MessageStrategyEngine  # noqa: E402

URL = "https://jimwoodsroofing.com"
FAMILIES = (BRAND_DOMINANT, MESSAGE_DOMINANT, LOCAL_AUTHORITY)
SCENE_TEMPLATES = ("cart_corral", "cart_nose")
OUT_DIR = os.path.join(_ROOT, "output", "mockups", "sprint2h")


def _synthetic_logo() -> BrandAsset:
    """A deterministic placeholder logo (verification fixture only).

    BRAND_DOMINANT requires a usable logo asset. The real Jim Woods site's logo
    is not bundled in the repo, so the verifier synthesizes a small representative
    brand mark (navy field + 'JWR' wordmark) to exercise the full pipeline. This is
    a fixture for visualization — it is NOT part of the domain engines and is not
    meant to be a final brand asset.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    logo_path = os.path.join(OUT_DIR, "_assets", "jimwoods_logo.png")
    if not os.path.exists(logo_path):
        from PIL import Image, ImageDraw, ImageFont

        os.makedirs(os.path.dirname(logo_path), exist_ok=True)

        w, h = 400, 120
        img = Image.new("RGBA", (w, h), (27, 42, 74, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 56)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        draw.text((20, 28), "JWR", font=font, fill=(244, 244, 244, 255))
        img.save(logo_path)

    return BrandAsset(
        path=logo_path,
        source_url="https://jimwoodsroofing.com",
        asset_type="logo",
        mime_type="image/png",
        format="PNG",
        width=400,
        height=120,
        aspect_ratio=400 / 120,
        has_alpha=True,
        confidence=1.0,
    )


# Real, documented Jim Woods evidence (used for the deterministic fallback).
def _fallback_profile(logo: bool = True) -> BrandProfile:
    return BrandProfile(
        company_name="Jim Woods Roofing",
        website=URL,
        domain="jimwoodsroofing.com",
        location="Sioux Falls, SD",
        service_area="Sioux Falls",
        services=["Roofing"],
        categories=["Roofing"],
        phone="605-764-9517",
        years_in_business="27",
        differentiators=["Financing Available", "Free Estimates"],
        guarantees=["Manufacturer Warranty"],
        trust_signals=["27 Years in Business"],
        colors=["#1B2A4A", "#F4F4F4"],
        logo=_synthetic_logo() if logo else None,
    )


def _concepts_from_profile(profile: BrandProfile):
    from engine.ad_concept import AdConceptEngine

    strategy_engine = MessageStrategyEngine()
    strategies = strategy_engine.generate(profile)
    concept_engine = AdConceptEngine()
    return concept_engine.generate(profile, strategies)


def _try_live_concepts():
    """Run the real live pipeline; return (concepts, source_label)."""
    from bs4 import BeautifulSoup
    from engine.scraper.business_intel import build_context, extract_business_intel
    from engine.scraper.site import WebsiteScraper

    scraper = WebsiteScraper(URL)
    data = scraper.run()
    soup = BeautifulSoup(data.get("html", ""), "lxml")
    ctx = build_context(
        soup=soup,
        html=data.get("html", ""),
        url=data.get("url", URL),
        metadata=data.get("metadata") or {},
        headline=data.get("headline") or "",
        company=data.get("company") or "",
    )
    data["business_intel"] = extract_business_intel(ctx)
    from engine.brand_profile import BrandProfileBuilder

    profile = BrandProfileBuilder.from_scrape_data(data)
    return _concepts_from_profile(profile), "live-scrape"


def main() -> int:
    print("=== SPRINT 2H VERIFY: Final Physical Sales Mockups ===\n")

    # 1. Prefer live pipeline; fall back to real documented evidence.
    live_concepts = []
    source = ""
    try:
        live_concepts, source = _try_live_concepts()
        print(f"Live scrape OK ({source}): {len(live_concepts)} concepts")
    except Exception as exc:  # noqa: BLE001
        print(f"Live scrape unavailable ({type(exc).__name__}): {exc}")
        print("Falling back to deterministic engines with real Jim Woods evidence.")
        source = "real-evidence-fallback"

    # 2. Pick one concept per MVP family. Prefer live concepts; fill any missing
    #    family from the real documented evidence through the same deterministic
    #    engines (never fabricated concepts). BRAND_DOMINANT needs a usable logo,
    #    while MESSAGE_DOMINANT is produced from the same evidence without one, so
    #    we union concepts derived from both a logo-enabled and a no-logo profile.
    by_family = {}
    for concept in live_concepts:
        by_family.setdefault(concept.composition_family, concept)
    for concept in _concepts_from_profile(_fallback_profile(logo=True)):
        by_family.setdefault(concept.composition_family, concept)
    for concept in _concepts_from_profile(_fallback_profile(logo=False)):
        by_family.setdefault(concept.composition_family, concept)

    os.makedirs(OUT_DIR, exist_ok=True)
    generated = []

    for family in FAMILIES:
        concept = by_family.get(family)
        if concept is None:
            print(f"\n[{family}] no concept produced -> skipped")
            continue
        print(
            f"\n[{family}]  headline={concept.headline!r}  "
            f"cta={concept.cta!r}  proofs={list(concept.supporting_proof)!r}"
        )
        for scene_template in SCENE_TEMPLATES:
            name = (
                f"jimwoods_{family.lower()}_{scene_template}.png"
            )
            path = os.path.join(OUT_DIR, name)
            out = render_concept_mockup(concept, _fallback_profile(), scene_template, path)
            generated.append(out)
            print(f"  {scene_template}: -> {os.path.basename(out)}")

    print(f"\n=== SUMMARY ===")
    print(f"source            : {source}")
    print(f"concepts generated: {len(live_concepts)}")
    print(f"final mockups     : {len(generated)}")
    for g in generated:
        print(f"  {g}")
    print(f"\nOutput dir: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())