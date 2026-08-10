"""Sprint 2D real-world verification: Jim Woods Roofing.

End-to-end pipeline exercised against the ACTUAL live website:
    WebsiteScraper.run()
        -> business_intel extraction (build_context + extract_business_intel)
        -> BrandProfileBuilder.from_scrape_data(business_intel)
        -> MessageStrategyEngine.generate(profile)

The business-intelligence facts are produced by the real Sprint 2C
extraction pipeline over the live-scraped HTML. Nothing is hand-injected
or "improved". If the live site yields sparse evidence, the printed
strategies simply reflect that honest reality.

Run:
    python tools/sprint2d_verify.py
"""

from __future__ import annotations

import os
import sys

from bs4 import BeautifulSoup

# Ensure the repo root is importable regardless of CWD.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from engine.message_strategy import MessageStrategy, MessageStrategyEngine  # noqa: E402
from engine.scraper.business_intel import build_context, extract_business_intel  # noqa: E402
from engine.scraper.site import WebsiteScraper  # noqa: E402

URL = "https://jimwoodsroofing.com"


def _fmt_list(items) -> str:
    if not items:
        return "(none)"
    return ", ".join(str(i) for i in items)


def _print_profile(profile) -> None:
    """Print a concise BrandProfile evidence summary."""
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
    print()


def _print_strategy(rank: int, s: MessageStrategy) -> None:
    """Print a single ranked strategy."""
    print(f"--- Rank {rank} ---")
    print(f"  rank             : {rank}")
    print(f"  strategy_type    : {s.strategy_type or '(none)'}")
    print(f"  score            : {s.score:.3f}")
    print(f"  primary_message  : {s.primary_message or '(none)'}")
    print(f"  supporting_proof : {_fmt_list(s.supporting_proof)}")
    print(f"  cta              : {s.cta or '(none)'}")
    print(f"  rationale        : {s.rationale or '(none)'}")
    print(f"  evidence         : {_fmt_list(s.evidence)}")
    print(f"  service_focus    : {s.service_focus or '(none)'}")
    print(f"  geographic_focus : {s.geographic_focus or '(none)'}")
    print(f"  phone            : {s.phone or '(none)'}")
    print(f"  confidence       : {s.confidence:.3f}")
    print()


def main() -> int:
    # 1. Run the actual WebsiteScraper against the live site.
    print(f"Scraping {URL} ...")
    scraper = WebsiteScraper(URL)
    data = scraper.run()
    print(f"Scrape complete. html_len={len(data.get('html', ''))} "
          f"company={data.get('company')!r}\n")

    # 2. Run the real Sprint 2C business-intel extraction over the scraped HTML.
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

    # 4. Pass that profile straight into the MessageStrategyEngine.
    engine = MessageStrategyEngine()
    strategies = engine.generate(profile)

    # 5. Print each ranked strategy.
    print(f"=== GENERATED STRATEGIES ({len(strategies)}) ===")
    if not strategies:
        print("No strategies could be generated from the available evidence.")
    for rank, s in enumerate(strategies, start=1):
        _print_strategy(rank, s)

    return 0


if __name__ == "__main__":
    sys.exit(main())