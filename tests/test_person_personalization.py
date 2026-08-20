from __future__ import annotations

import json

from engine.ad_concept import AdConcept
from engine.brand_profile import BrandProfile, BrandProfileBuilder
from engine.person_personalization import (
    DISTINCTIVE_TAGLINE,
    EXPERIENCE,
    GENERIC_PERSON_BRAND,
    PROPERTY_TYPE_EXPERTISE,
    choose_personalization,
)
from gui.models.project import Project
from gui.models.render_context import RenderContext


def _person_scrape(**overrides):
    html = overrides.pop(
        "html",
        """
        <html><head><title>Jane Smith, Example Realty Real Estate Agent | Example Realty</title></head>
        <body>
          <h1>Jane Smith</h1>
          <h2>Realtor, Top Sales Leader</h2>
          <p>18 years helping buyers and sellers. Provides staging guidance and professional photography.</p>
          <p>Experience with relocation and new construction.</p>
        </body></html>
        """,
    )
    data = {
        "url": "https://example.com/agent/jane-smith/",
        "company": "Example Realty",
        "headline": "Jane Smith, Example Realty Real Estate Agent | Example Realty",
        "ad_copy": "Jane Smith, Example Realty Real Estate Agent | Example Realty",
        "html": html,
        "metadata": {"title": "Jane Smith, Example Realty Real Estate Agent | Example Realty"},
        "person_context": {
            "contact_name": "Jane Smith",
            "contact_title": "Realtor, Top Sales Leader",
            "resolved_profile_url": "https://example.com/agent/jane-smith/",
        },
        "business_intel": {"categories": ["realtor", "real estate agent"]},
    }
    data.update(overrides)
    return data


def test_person_profile_with_experience_influences_headline() -> None:
    result = choose_personalization(_person_scrape())
    assert result.personalization_angle == EXPERIENCE
    assert result.person_facts.years_experience == "18"
    assert "18 Years" in result.headline
    assert result.headline != "Jane Smith, Example Realty Real Estate Agent | Example Realty"


def test_person_profile_with_specialty_influences_angle() -> None:
    data = _person_scrape(html="""
        <html><head><title>Jane Smith | Example Realty</title></head><body>
        <h1>Jane Smith</h1><p>Jane specializes in relocation and new construction homes.</p>
        </body></html>
    """)
    result = choose_personalization(data)
    assert result.personalization_angle == PROPERTY_TYPE_EXPERTISE
    assert "new construction" in result.person_facts.specialties
    assert "Guide" in result.headline or "Expertise" in result.headline


def test_unsupported_superlative_not_invented() -> None:
    data = _person_scrape(html="""
        <html><head><title>Jane Smith | Example Realty</title></head><body>
        <h1>Jane Smith</h1><p>Jane helps buyers and sellers make confident moves.</p>
        </body></html>
    """)
    result = choose_personalization(data)
    generated = " ".join([result.headline, result.cta, " ".join(result.person_facts.awards_or_roles)])
    assert "#1" not in generated
    assert "Top Producer" not in generated
    assert "Market Leader" not in generated
    assert result.personalization_angle == GENERIC_PERSON_BRAND


def test_seo_page_title_not_copied_verbatim_as_billboard_headline() -> None:
    profile = BrandProfileBuilder.from_scrape_data(_person_scrape())
    ctx = RenderContext.from_brand_profile(profile, template="realtor")
    assert ctx.headline != "Jane Smith, Example Realty Real Estate Agent | Example Realty"
    assert "|" not in ctx.headline
    assert len(ctx.headline) <= 42


def test_duplicate_company_person_title_simplified() -> None:
    result = choose_personalization(_person_scrape())
    assert result.headline.count("Example Realty") == 0
    assert result.headline.count("Jane Smith") == 0
    assert "Real Estate Agent |" not in result.headline


def test_person_specific_tagline_can_influence_copy() -> None:
    data = _person_scrape(html="""
        <html><head><title>Jane Smith | Example Realty</title></head><body>
        <h1>Jane Smith</h1><h2>SPARKLE IN THE MARKET!</h2>
        <p>Jane helps buyers and sellers make confident moves.</p>
        </body></html>
    """)
    result = choose_personalization(data)
    assert result.personalization_angle == DISTINCTIVE_TAGLINE
    assert "Sparkle" in result.headline
    assert result.person_facts.provenance["person_tagline"]


def test_weak_person_facts_safe_generic_person_fallback() -> None:
    data = _person_scrape(html="""
        <html><head><title>Jane Smith | Example Realty</title></head><body>
        <h1>Jane Smith</h1><p>Welcome to Jane's profile.</p>
        </body></html>
    """)
    result = choose_personalization(data)
    assert result.personalization_angle == GENERIC_PERSON_BRAND
    assert result.headline == "Work With Jane"
    assert result.cta in {"Let's Talk", "Contact Jane"}


def test_generic_business_page_preserves_business_oriented_behavior() -> None:
    data = {
        "url": "https://acmeroofing.example",
        "company": "Acme Roofing",
        "headline": "Acme Roofing | Roof Repair Pros",
        "ad_copy": "Storm Damage Pros",
        "html": "<html><body><h1>Acme Roofing</h1><p>Roof repair and replacement.</p></body></html>",
        "metadata": {"title": "Acme Roofing | Roof Repair Pros"},
    }
    profile = BrandProfileBuilder.from_scrape_data(data)
    ctx = RenderContext.from_brand_profile(profile, template="contractor")
    assert profile.person_facts.contact_name == ""
    assert profile.personalized_headline == ""
    assert ctx.headline == "Storm Damage Pros"


def test_cta_varies_by_context() -> None:
    exp = choose_personalization(_person_scrape())
    weak = choose_personalization(_person_scrape(html="""
        <html><head><title>Jane Smith | Example Realty</title></head><body><h1>Jane Smith</h1></body></html>
    """))
    phone = choose_personalization(_person_scrape(person_context={"contact_name": "Jane Smith"}, html="""
        <html><head><title>Jane Smith | Example Realty</title></head><body>
        <script type="application/ld+json">{"@type":"Person","name":"Jane Smith","telephone":"555-111-2222"}</script>
        <h1>Jane Smith</h1><p>18 years helping buyers and sellers.</p></body></html>
    """))
    assert exp.cta == "Contact Jane"
    assert weak.cta == "Let's Talk"
    assert phone.cta == "Call Jane"


def test_provenance_person_facts_survive_serialization_and_project_persistence(tmp_path) -> None:
    profile = BrandProfileBuilder.from_scrape_data(_person_scrape())
    payload = profile.to_dict()
    restored = BrandProfile.from_dict(json.loads(json.dumps(payload)))
    assert restored.person_facts.years_experience == "18"
    assert restored.person_facts.provenance["years_experience"]
    assert restored.personalization_angle == EXPERIENCE

    concept = AdConcept(headline=profile.personalized_headline, cta=profile.personalized_cta, person_facts=profile.person_facts.to_dict(), personalization_angle=profile.personalization_angle, personalization_basis=profile.personalization_basis)
    project = Project.create(output_root=str(tmp_path), name="person")
    project.update_from_pipeline(brand_profile=profile, concepts=[concept])
    project.save()
    loaded = Project.load(project.metadata_path)
    assert loaded.brand_profile["person_facts"]["years_experience"] == "18"
    assert loaded.ad_concepts[0]["personalization_angle"] == EXPERIENCE


def test_generated_copy_deterministic_under_fixture_inputs() -> None:
    first = choose_personalization(_person_scrape()).to_dict()
    second = choose_personalization(_person_scrape()).to_dict()
    assert first == second
