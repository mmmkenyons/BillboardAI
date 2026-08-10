"""Sprint 2G real-world verification: rectangular Creative Layout artwork.

Exercises the real Jim Woods roofing pipeline end-to-end:
    WebsiteScraper -> BrandProfile -> MessageStrategy -> AdConcept
    -> CreativeLayoutEngine -> CreativeLayoutSpec
    -> CreativeArtworkRenderer -> rectangular artwork PNG

Renders the MVP's three composition families (BRAND_DOMINANT, MESSAGE_DOMINANT,
LOCAL_AUTHORITY) at both target artwork sizes (752x300 and 552x400).

If the live site is unreachable, it falls back to the deterministic engines fed
with the real, documented Jim Woods evidence (never fabricated concepts). No
physical cart scene is rendered; output PNGs are saved under the git-ignored
output/creative_layout/ directory.

Run:
    python tools/sprint2g_verify.py
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
    AdConcept,
    AdConceptEngine,
)
from engine.brand_profile import BrandProfile, BrandProfileBuilder  # noqa: E402
from engine.layout import (  # noqa: E402
    CreativeArtworkRenderer,
    CreativeLayoutEngine,
    CreativeQualityChecker,
)
from engine.message_strategy import MessageStrategyEngine  # noqa: E402

URL = "https://jimwoodsroofing.com"
ARTWORK_SIZES = [(752, 300), (552, 400)]
FAMILIES = (BRAND_DOMINANT, MESSAGE_DOMINANT, LOCAL_AUTHORITY)
OUT_DIR = os.path.join(_ROOT, "output", "creative_layout")


# Real, documented Jim Woods evidence (used for the deterministic fallback).
def _fallback_profile() -> BrandProfile:
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
    )


def _concepts_from_profile(profile: BrandProfile):
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
    profile = BrandProfileBuilder.from_scrape_data(data)
    return _concepts_from_profile(profile), "live-scrape"


def main() -> int:
    print(f"=== SPRINT 2G VERIFY: Creative Layout Artwork ===\n")

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
    #    engines (never fabricated concepts).
    by_family = {}
    for concept in live_concepts:
        by_family.setdefault(concept.composition_family, concept)
    fallback_concepts = _concepts_from_profile(_fallback_profile())
    for concept in fallback_concepts:
        by_family.setdefault(concept.composition_family, concept)

    palette_profile = _fallback_profile()
    engine = CreativeLayoutEngine()
    renderer = CreativeArtworkRenderer()
    checker = CreativeQualityChecker()

    os.makedirs(OUT_DIR, exist_ok=True)
    generated = []

    for family in FAMILIES:
        concept = by_family.get(family)
        if concept is None:
            print(f"\n[{family}] no real concept produced -> skipped")
            continue
        print(f"\n[{family}]  headline={concept.headline!r}  cta={concept.cta!r}")
        for w, h in ARTWORK_SIZES:
            spec = engine.resolve(concept, palette_profile, w, h)
            result = checker.validate(spec)
            path = renderer.render_to_file(
                spec, os.path.join(OUT_DIR, f"{family}_{w}x{h}.png")
            )
            generated.append(path)
            print(
                f"  {w}x{h}: valid={spec.geometry_valid} "
                f"quality_passed={result.passed} score={result.score:.1f} "
                f"headline={spec.headline.font_size}px "
                f"proofs={len(spec.proofs)} cta={'yes' if spec.cta else 'no'} "
                f"logo={'yes' if spec.logo else 'no'} -> {os.path.basename(path)}"
            )

    print(f"\n=== SUMMARY ===")
    print(f"source           : {source}")
    print(f"concepts generated: {len(live_concepts)}")
    print(f"artwork PNGs saved: {len(generated)}")
    for g in generated:
        print(f"  {g}")
    print(f"\nOutput dir: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())