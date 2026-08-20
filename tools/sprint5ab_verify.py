"""Sprint 5AB verifier -- person-aware copy and personalization intelligence.

Deterministic, offline, no live network. Proves structured source facts,
derived personalization, generated billboard copy, unsupported-claim safety,
generic-business regression, and deterministic output.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.brand_profile import BrandProfileBuilder  # noqa: E402
from engine.person_personalization import EXPERIENCE, choose_personalization  # noqa: E402
from gui.models.render_context import RenderContext  # noqa: E402


def check(name: str, condition: bool, counts: dict[str, int], detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + f": {name}{' - ' + detail if detail else ''}")
    counts["passed" if condition else "failed"] += 1


def _person() -> dict:
    return {
        "url": "https://example.com/agent/jane-smith/",
        "company": "Example Realty",
        "headline": "Jane Smith, Example Realty Real Estate Agent | Example Realty",
        "ad_copy": "Jane Smith, Example Realty Real Estate Agent | Example Realty",
        "metadata": {"title": "Jane Smith, Example Realty Real Estate Agent | Example Realty"},
        "person_context": {"contact_name": "Jane Smith", "contact_title": "Realtor"},
        "html": """
            <html><head><title>Jane Smith, Example Realty Real Estate Agent | Example Realty</title></head>
            <body><h1>Jane Smith</h1><h2>Realtor</h2>
            <p>18 years helping buyers and sellers.</p>
            <p>Provides staging guidance and professional photography. Experience with relocation and new construction.</p>
            </body></html>
        """,
        "business_intel": {"categories": ["realtor", "real estate agent"]},
    }


def _generic_business() -> dict:
    return {
        "url": "https://acmeroofing.example",
        "company": "Acme Roofing",
        "headline": "Acme Roofing | Roof Repair Pros",
        "ad_copy": "Storm Damage Pros",
        "metadata": {"title": "Acme Roofing | Roof Repair Pros"},
        "html": "<html><body><h1>Acme Roofing</h1><p>Roof repair and replacement.</p></body></html>",
    }


def main() -> int:
    counts = {"passed": 0, "failed": 0}

    result = choose_personalization(_person())
    check("structured person facts extracted", result.person_facts.contact_name == "Jane Smith" and result.person_facts.years_experience == "18", counts)
    check("supported personalization angle chosen", result.personalization_angle == EXPERIENCE, counts, result.personalization_angle)
    generated = " ".join([result.headline, result.cta, " ".join(result.person_facts.awards_or_roles)])
    check("unsupported facts not invented", "#1" not in generated and "Top Producer" not in generated and "Market Leader" not in generated, counts, generated)
    check("SEO title not used verbatim as headline", result.headline != _person()["headline"] and "|" not in result.headline, counts, result.headline)
    check("concise person-aware copy generated", len(result.headline) <= 42 and len(result.headline.split()) <= 7 and result.cta == "Contact Jane", counts, f"{result.headline} / {result.cta}")

    profile = BrandProfileBuilder.from_scrape_data(_person())
    ctx = RenderContext.from_brand_profile(profile, template="realtor")
    check("RenderContext uses person-aware headline", ctx.headline == result.headline, counts, ctx.headline)
    check("provenance retained", bool(profile.person_facts.provenance.get("years_experience")), counts)

    business_profile = BrandProfileBuilder.from_scrape_data(_generic_business())
    business_ctx = RenderContext.from_brand_profile(business_profile, template="contractor")
    check("generic-business behavior preserved", business_ctx.headline == "Storm Damage Pros" and not business_profile.personalized_headline, counts, business_ctx.headline)

    first = choose_personalization(_person()).to_dict()
    second = choose_personalization(_person()).to_dict()
    check("deterministic output", first == second, counts)

    print("SPRINT 5AB VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
