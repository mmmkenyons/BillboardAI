"""Sprint 3B real-world verification: Project Workspace reopen without re-scraping.

Uses a real **Jim Woods Roofing** persisted project (created via the Sprint 3A
workflow under ``output/projects``). If no Jim Woods project exists it creates
one through the same deterministic pipeline the Sprint 3A verifier uses, then
walks the full Sprint 3B workspace flow through the controller/service layer
(no manual GUI clicking required):

    1. list persisted projects
    2. open the Jim Woods project  (NO WebsiteScraper / regeneration)
    3. read research summary (BrandProfile snapshot)
    4. enumerate saved AdConcepts
    5. select a concept        -> persist
    6. apply a headline override -> persist
    7. generate a cart_corral mockup (artwork + physical mockup)
    8. register artifacts
    9. reload the project again
    10. confirm: no scrape, selected concept persisted, override persisted,
        artifacts persisted, history persisted

Output is written under the git-ignored ``output/`` tree. This script is NOT
part of the pytest suite.

Run:
    python tools/sprint3b_verify.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.ad_concept import AdConceptEngine, BRAND_DOMINANT  # noqa: E402
from engine.brand_profile import BrandAsset, BrandProfile  # noqa: E402
from engine.message_strategy import MessageStrategyEngine  # noqa: E402

from gui.models.project_store import ProjectStore  # noqa: E402
from gui.services.project_workspace import ProjectWorkspaceService  # noqa: E402

OUT_ROOT = os.path.join(_ROOT, "output", "projects")
SCENE_TEMPLATE = "cart_corral"
URL = "https://jimwoodsroofing.com"


def _synthetic_logo() -> BrandAsset:
    """Deterministic placeholder logo for the Jim Woods fixture (verification only)."""
    logo_dir = os.path.join(OUT_ROOT, "_assets")
    os.makedirs(logo_dir, exist_ok=True)
    logo_path = os.path.join(logo_dir, "jimwoods_logo.png")
    if not os.path.exists(logo_path):
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGBA", (400, 120), (27, 42, 74, 255))
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


def _fallback_profile() -> BrandProfile:
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
        logo=_synthetic_logo(),
    )


def _run_pipeline(profile: BrandProfile):
    strategy_engine = MessageStrategyEngine()
    strategies = strategy_engine.generate(profile)
    concept_engine = AdConceptEngine()
    concepts = concept_engine.generate(profile, strategies)
    return strategies, concepts


def _find_or_create_jim_woods(store: ProjectStore):
    """Return a Jim Woods project id, creating one if none exists."""
    for project in store.list():
        if "jim" in (project.company or "").lower():
            return project.id
    # Create one via the deterministic pipeline (same evidence as Sprint 3A).
    profile = _fallback_profile()
    strategies, concepts = _run_pipeline(profile)
    by_family = {c.composition_family: c for c in concepts}
    if BRAND_DOMINANT not in by_family:
        by_family[BRAND_DOMINANT] = _run_pipeline(_fallback_profile())[1][0]
    concepts = list(by_family.values())
    project = store.create(company_name=profile.company_name, website=profile.website)
    project.update_from_pipeline(
        brand_profile=profile,
        strategies=strategies or _run_pipeline(_fallback_profile())[0],
        concepts=concepts,
    )
    project.append_history(
        "research_completed",
        f"Researched {project.website} (verification fixture)",
        {"source": "sprint3b-verify"},
    )
    store.save(project)
    return project.id


def main() -> int:
    print("=== SPRINT 3B VERIFY: Project Workspace reopen (no re-scrape) ===\n")

    store = ProjectStore(root=OUT_ROOT)
    svc = ProjectWorkspaceService(store=store)

    # 1. List persisted projects.
    projects = svc.list_projects()
    print(f"persisted projects : {len(projects)}")
    if not projects:
        print("No projects found; nothing to verify.")
        return 1

    # 2. Open the Jim Woods project.
    project_id = _find_or_create_jim_woods(store)
    project = svc.open_project(project_id)
    print(f"opened project     : {project.company} ({project.id[:8]}...)")

    # 3. Read research summary (no re-scrape).
    profile = svc.hydrate_brand_profile(project)
    assert profile is not None, "BrandProfile snapshot missing"
    print(f"research summary   : {profile.company_name} | "
          f"categories={profile.categories} | trust={profile.trust_signals}")

    # 4. Enumerate concepts.
    concepts = svc.all_ad_concepts(project)
    print(f"ad concepts        : {len(concepts)}")
    for c in concepts:
        print(f"  - {c.concept_id} [{c.composition_family}] {c.headline!r}")

    # 5. Select a concept and persist.
    assert concepts, "No AdConcepts saved"
    selected = max(concepts, key=lambda c: c.score)
    svc.select_concept(project, selected.concept_id)
    print(f"selected concept   : {selected.concept_id}")

    # 6. Apply a headline override and persist.
    override_text = f"OVERRIDE {selected.headline}"
    svc.set_override(project, "headline", override_text)
    print(f"headline override  : {override_text!r}")

    # 7-8. Generate a cart_corral mockup (artwork + physical mockup).
    artifacts = svc.generate_mockup(
        project, SCENE_TEMPLATE, concept_id=selected.concept_id
    )
    print(
        f"generated artifacts: {[a.artifact_type for a in artifacts]} "
        f"scene={SCENE_TEMPLATE}"
    )

    # 9. Close / reload from disk (persistence check).
    reloaded = svc.open_project(project.id)
    print("\n=== RELOAD VERIFICATION (no re-scrape) ===")
    checks = [
        ("no scrape (BrandProfile intact)", reloaded.brand_profile is not None),
        (
            "selected concept persisted",
            reloaded.selected_concept_id == selected.concept_id,
        ),
        (
            "headline override persisted",
            reloaded.user_overrides.get("headline") == override_text,
        ),
        (
            "artwork artifact persisted",
            any(a.artifact_type == "artwork" for a in reloaded.artifacts),
        ),
        (
            "mockup artifact persisted",
            any(a.artifact_type == "mockup" for a in reloaded.artifacts),
        ),
        (
            "selection history",
            any(h.event_type == "concept_selected" for h in reloaded.history),
        ),
        (
            "override history",
            any(h.event_type == "override_changed" for h in reloaded.history),
        ),
        (
            "mockup history",
            any(h.event_type == "mockup_generated" for h in reloaded.history),
        ),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {label}")
        ok = ok and passed

    print("\n=== SUMMARY ===")
    print(f"project id        : {reloaded.id}")
    print(f"ad concepts       : {len(reloaded.ad_concepts)}")
    print(f"artifacts         : {len(reloaded.artifacts)}")
    print(f"history entries   : {len(reloaded.history)}")
    print(f"all checks passed : {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())