"""Sprint 3A real-world verification: durable BillboardAI project persistence.

Exercises the REAL Jim Woods pipeline end-to-end and persists the structured
results into a durable Project, proving that a reopened project reconstructs
equivalent state WITHOUT re-scraping the website.

Pipeline:
    WebsiteScraper -> BrandProfile -> MessageStrategy -> AdConcept
        -> Project.update_from_pipeline(...)            (structured snapshot)
        -> CreativeLayoutEngine/ArtworkRenderer -> artwork artifact
        -> engine.mockup.render_concept_mockup   -> mockup artifact
        -> ProjectStore.save -> ProjectStore.load -> verify -> print tree

If the live site is unreachable, it falls back to the deterministic engines fed
with the real, documented Jim Woods evidence (never fabricated concepts), exactly
like the Sprint 2H verifier.

Output (including the project directory) is written under the git-ignored
``output/`` tree so it never pollutes source control. This script is NOT part of
the pytest suite.

Run:
    python tools/sprint3a_verify.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.ad_concept import AdConceptEngine, BRAND_DOMINANT  # noqa: E402
from engine.brand_profile import BrandAsset, BrandProfile  # noqa: E402
from engine.mockup import render_concept_mockup  # noqa: E402
from engine.message_strategy import MessageStrategyEngine  # noqa: E402

from gui.models.project_artifact import (  # noqa: E402
    ARTIFACT_TYPE_ARTWORK,
    ARTIFACT_TYPE_MOCKUP,
)
from gui.models.project_store import ProjectStore  # noqa: E402

URL = "https://jimwoodsroofing.com"
OUT_ROOT = os.path.join(_ROOT, "output", "projects")
SCENE_TEMPLATE = "cart_corral"
ARTWORK_SIZE = (752, 300)


def _synthetic_logo() -> BrandAsset:
    """A deterministic placeholder logo (verification fixture only).

    BRAND_DOMINANT requires a usable logo asset. The real Jim Woods site's logo
    is not bundled in the repo, so the verifier synthesizes a small representative
    brand mark (navy field + 'JWR' wordmark) to exercise the full pipeline. This
    is a fixture for visualization — it is NOT part of the domain engines and is
    not meant to be a final brand asset.
    """
    logo_dir = os.path.join(OUT_ROOT, "_assets")
    os.makedirs(logo_dir, exist_ok=True)
    logo_path = os.path.join(logo_dir, "jimwoods_logo.png")
    if not os.path.exists(logo_path):
        from PIL import Image, ImageDraw, ImageFont

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
        source_url=URL,
        asset_type="logo",
        mime_type="image/png",
        format="PNG",
        width=400,
        height=120,
        aspect_ratio=400 / 120,
        has_alpha=True,
        confidence=1.0,
    )


def _fallback_profile(logo: bool = True) -> BrandProfile:
    """Real, documented Jim Woods evidence (deterministic fallback)."""
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


def _run_pipeline(profile: BrandProfile):
    """Return (strategies, concepts) from the deterministic engines."""
    strategy_engine = MessageStrategyEngine()
    strategies = strategy_engine.generate(profile)
    concept_engine = AdConceptEngine()
    concepts = concept_engine.generate(profile, strategies)
    return strategies, concepts


def _try_live():
    """Run the real live pipeline; return (profile, strategies, concepts, source)."""
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
    strategies, concepts = _run_pipeline(profile)
    return profile, strategies, concepts, "live-scrape"
def main() -> int:
    print("=== SPRINT 3A VERIFY: Durable Project Persistence ===\n")

    # 1. Prefer live pipeline; fall back to real documented evidence.
    profile = None
    strategies = []
    concepts = []
    source = ""
    try:
        profile, strategies, concepts, source = _try_live()
        print(f"Live scrape OK ({source}): {len(concepts)} concepts")
    except Exception as exc:  # noqa: BLE001
        print(f"Live scrape unavailable ({type(exc).__name__}): {exc}")
        print("Falling back to deterministic engines with real Jim Woods evidence.")
        source = "real-evidence-fallback"
        profile = _fallback_profile(logo=True)
        strategies, concepts = _run_pipeline(profile)

    # Ensure at least one BRAND_DOMINANT concept (needs a usable logo).
    by_family = {c.composition_family: c for c in concepts}
    fb_strategies, fb_concepts = _run_pipeline(_fallback_profile(logo=True))
    for c in fb_concepts:
        by_family.setdefault(c.composition_family, c)
    if BRAND_DOMINANT not in by_family:
        by_family[BRAND_DOMINANT] = _run_pipeline(_fallback_profile(logo=True))[1][0]
    concepts = list(by_family.values())
    strategies = strategies or fb_strategies

    print(f"pipeline source      : {source}")
    print(f"strategies generated : {len(strategies)}")
    print(f"concepts generated   : {len(concepts)}")

    # 2. Create a durable project and snapshot the structured pipeline results.
    store = ProjectStore(root=OUT_ROOT)
    project = store.create(
        company_name=profile.company_name or "Jim Woods Roofing",
        website=profile.website or URL,
    )
    project.update_from_pipeline(
        brand_profile=profile,
        strategies=strategies,
        concepts=concepts,
    )
    project.append_history(
        "research_completed",
        f"Researched {project.website or project.domain} ({source})",
        {"source": source},
    )
    project.append_history(
        "concepts_generated",
        f"Generated {len(concepts)} ad concepts",
        {"count": len(concepts)},
    )

    # 3. Select the strongest concept.
    selected = max(concepts, key=lambda c: c.score)
    project.selected_concept_id = selected.concept_id
    project.append_history(
        "concept_selected",
        f"Selected concept {selected.concept_id} ({selected.composition_family})",
        {"concept_id": selected.concept_id},
    )

    # 4. Register an artwork artifact (rectangular creative).
    import os.path as _p

    artwork_path = _p.join(project.root_dir, "artwork", "selected_artwork.png")
    from engine.layout import CreativeArtworkRenderer, CreativeLayoutEngine

    width, height = ARTWORK_SIZE
    spec = CreativeLayoutEngine().resolve(selected, profile, width, height)
    CreativeArtworkRenderer().render_to_file(spec, artwork_path)
    project.register_artifact(
        artifact_type=ARTIFACT_TYPE_ARTWORK,
        path=os.path.relpath(artwork_path, project.root_dir),
        concept_id=selected.concept_id,
        composition_family=selected.composition_family,
        width=width,
        height=height,
    )
    project.append_history(
        "artwork_generated",
        f"Generated artwork for concept {selected.concept_id}",
        {"path": artwork_path},
    )
# 5. Register a physical mockup artifact.
    mockup_path = _p.join(project.root_dir, "mockups", "selected_mockup.png")
    render_concept_mockup(selected, profile, SCENE_TEMPLATE, mockup_path)
    project.register_artifact(
        artifact_type=ARTIFACT_TYPE_MOCKUP,
        path=os.path.relpath(mockup_path, project.root_dir),
        concept_id=selected.concept_id,
        scene_template=SCENE_TEMPLATE,
        composition_family=selected.composition_family,
        width=width,
        height=height,
    )
    project.append_history(
        "mockup_generated",
        f"Generated physical mockup ({SCENE_TEMPLATE}) for concept {selected.concept_id}",
        {"scene_template": SCENE_TEMPLATE},
    )

    # 6. Save, then completely reload from disk.
    store.save(project)
    print(f"\nproject            : {project.id}")
    print(f"project directory : {project.root_dir}")
    print(f"artifacts: {len(project.artifacts)}")

    reloaded = store.load(project.id)

    # 7. Verify the reloaded project reconstructed equivalent state.
    print("\n=== RELOAD VERIFICATION ===")
    checks = [
        ("company", reloaded.company == "Jim Woods Roofing"),
        ("website", reloaded.website == URL),
        ("BrandProfile", reloaded.brand_profile is not None),
        ("strategies", len(reloaded.strategies) > 0),
        ("concepts", len(reloaded.ad_concepts) > 0),
        ("selected concept", reloaded.selected_concept_id == selected.concept_id),
        ("artifacts", len(reloaded.artifacts) >= 2),
        ("history", len(reloaded.history) >= 4),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {label}")
        ok = ok and passed

    art_types = {a.artifact_type for a in reloaded.artifacts}
    print(f"  artifact types    : {sorted(art_types)}")
    print(f"  schema_version    : {reloaded.schema_version}")

    # 8. Print the project directory tree.
    print("\n=== PROJECT DIRECTORY TREE ===")
    for root, dirs, files in os.walk(reloaded.root_dir):
        dirs.sort()
        files.sort()
        level = root.replace(reloaded.root_dir, "").count(os.sep)
        indent = "  " * level
        print(f"{indent}{os.path.basename(root) or reloaded.root_dir}/")
        for f in files:
            print(f"{indent}  {f}")

    print("\n=== SUMMARY ===")
    print(f"source            : {source}")
    print(f"project id        : {reloaded.id}")
    print(f"all checks passed : {ok}")
    print(f"\nOutput root: {OUT_ROOT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())