"""Sprint 2E real-world verification: Jim Woods Roofing.

End-to-end pipeline exercised against the ACTUAL live website:
    WebsiteScraper.run()
        -> business_intel extraction (build_context + extract_business_intel)
        -> BrandProfileBuilder.from_scrape_data(business_intel)
        -> MessageStrategyEngine.generate(profile)
        -> AdConceptEngine.generate(profile, strategies)

The business-intelligence facts are produced by the real Sprint 2C extraction
pipeline over the live-scraped HTML. Nothing is hand-injected or "improved".
If the live site yields sparse evidence, the printed concepts reflect that
honest reality.

Run:
    python tools/sprint2e_verify.py
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

# Ensure the repo root is importable regardless of CWD.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.ad_concept import AdConcept, AdConceptEngine  # noqa: E402
from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from engine.message_strategy import MessageStrategy, MessageStrategyEngine  # noqa: E402
from engine.scraper.business_intel import build_context, extract_business_intel  # noqa: E402
from engine.scraper.site import WebsiteScraper  # noqa: E402

URL = "https://jimwoodsroofing.com"


def _fmt_list(items) -> str:
    if not items:
        return "(none)"
    return ", ".join(str(i) for i in items)


def _fmt_asset(asset) -> str:
    if asset is None:
        return "(none)"
    return (
        f"{asset.path} ({asset.width}x{asset.height}, "
        f"{asset.format or 'image'}, conf={asset.confidence:.2f})"
    )


def _print_profile(profile) -> None:
    print("=== BRANDPROFILE EVIDENCE SUMMARY ===")
    print(f"company_name      : {profile.company_name or '(none)'}")
    print(f"domain            : {profile.domain or '(none)'}")
    print(f"phone             : {profile.phone or '(none)'}")
    print(f"location          : {profile.location or '(none)'}")
    print(f"service_area      : {profile.service_area or '(none)'}")
    print(f"services          : {_fmt_list(profile.services)}")
    print(f"categories        : {_fmt_list(profile.categories)}")
    print(f"differentiators   : {_fmt_list(profile.differentiators)}")
    print(f"trust_signals     : {_fmt_list(profile.trust_signals)}")
    print(f"awards            : {_fmt_list(profile.awards)}")
    print(f"certifications    : {_fmt_list(profile.certifications)}")
    print(f"guarantees        : {_fmt_list(profile.guarantees)}")
    print(f"years_in_business : {profile.years_in_business or '(none)'}")
    print(f"logo asset        : {_fmt_asset(profile.logo)}")
    print(f"hero_url (proven) : {profile.hero_url or '(none)'}")
    print(f"hero_assets       : {len(profile.hero_assets)} normalized")
    print()


def _print_strategy(rank: int, s: MessageStrategy) -> None:
    print(f"--- Strategy Rank {rank} ---")
    print(f"  strategy_type    : {s.strategy_type or '(none)'}")
    print(f"  score            : {s.score:.3f}")
    print(f"  confidence       : {s.confidence:.3f}")
    print(f"  primary_message  : {s.primary_message or '(none)'}")
    print(f"  supporting_proof : {_fmt_list(s.supporting_proof)}")
    print(f"  cta              : {s.cta or '(none)'}")
    print(f"  evidence         : {_fmt_list(s.evidence)}")
    print(f"  geographic_focus : {s.geographic_focus or '(none)'}")
    print(f"  phone            : {s.phone or '(none)'}")
    print()


def _print_concept(rank: int, c: AdConcept) -> None:
    print(f"=== CONCEPT {rank} ===")
    print(f"concept rank       : {rank}")
    print(f"concept id         : {c.concept_id}")
    print(f"composition family : {c.composition_family}")
    print(f"source strategy    : {c.strategy_type}")
    print(f"concept score      : {c.score:.3f}")
    print(f"confidence         : {c.confidence:.3f}")
    print()
    print(f"headline           : {c.headline or '(none)'}")
    print(f"proof              : {_fmt_list(c.supporting_proof)}")
    print(f"cta                : {c.cta or '(none)'}")
    print()
    print(f"logo role          : {c.logo_role}")
    print(f"hero role          : {c.hero_role}")
    print(f"headline role      : {c.headline_role}")
    print(f"proof role         : {c.proof_role}")
    print(f"cta role           : {c.cta_role}")
    print()
    print(f"logo asset         : {_fmt_asset(c.logo_asset)}")
    print(f"hero asset         : {_fmt_asset(c.hero_asset)}")
    print()
    print(f"rationale          : {c.rationale}")
    print()


def main() -> int:
    # 1. Run the actual WebsiteScraper against the live site.
    print(f"Scraping {URL} ...")
    scraper = WebsiteScraper(URL)
    data = scraper.run()
    print(f"Scrape complete. html_len={len(data.get('html', ''))} "
          f"company={data.get('company')!r}\n")

    # 2. Run the real Sprint 2C business-intel extraction over the live HTML.
    soup = BeautifulSoup(data.get("html", ""), "lxml")
    ctx = build_context(
        soup=soup,
        html=data.get("html", ""),
        url=data.get("url", URL),
        metadata=data.get("metadata") or {},
        headline=data.get("headline") or "",
        company=data.get("company") or "",
    )
    business_intel = extract_business_intel(ctx)
    data["business_intel"] = business_intel

    # 3. Build the actual BrandProfile from the real extracted evidence.
    profile = BrandProfileBuilder.from_scrape_data(data)
    _print_profile(profile)

    # 4. Generate public MessageStrategy candidates.
    strategy_engine = MessageStrategyEngine()
    strategies = strategy_engine.generate(profile)
    print(f"=== GENERATED STRATEGIES ({len(strategies)}) ===")
    if not strategies:
        print("No strategies could be generated from the available evidence.\n")
    for rank, s in enumerate(strategies, start=1):
        _print_strategy(rank, s)

    # 5. Generate AdConcepts on top of the public strategies.
    concept_engine = AdConceptEngine()
    concepts = concept_engine.generate(profile, strategies)
    print(f"\n=== GENERATED CONCEPTS ({len(concepts)}) ===")
    if not concepts:
        print("No concepts could be generated from the available evidence.\n")
    for rank, c in enumerate(concepts, start=1):
        _print_concept(rank, c)

    return 0


if __name__ == "__main__":
    sys.exit(main())

