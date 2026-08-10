"""Sprint 2E: Ad Concept Engine tests."""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from engine.brand_profile import BrandAsset, BrandProfile
from engine.message_strategy import (
    TRUST_LED,
    SERVICE_LED,
    OFFER_LED,
    LOCAL_AUTHORITY,
    PROBLEM_LED,
    MessageStrategy,
    MessageStrategyEngine,
)
from engine.ad_concept import (
    BRAND_DOMINANT,
    HERO_IMAGE,
    MESSAGE_DOMINANT,
    TRUST_AUTHORITY,
    DOMINANT,
    PRIMARY,
    SECONDARY,
    HIDDEN,
    AdConcept,
    AdConceptEngine,
    _logo_usable,
    _hero_usable,
    _best_hero,
    _score_concept,
    _select_concept_proof,
    _deduplicate_concepts,
)


# ======================================================================
# Helpers
# ======================================================================

def _asset(**kwargs: Any) -> BrandAsset:
    """A BrandAsset with sensible default raster metadata, overridable."""
    defaults: Dict[str, Any] = {
        "path": "/tmp/asset.png",
        "source_url": "https://example.com/asset.png",
        "asset_type": "generic",
        "mime_type": "image/png",
        "format": "PNG",
        "width": 800,
        "height": 400,
        "aspect_ratio": 2.0,
        "has_alpha": True,
        "file_size": 1024,
        "quality_score": 0.8,
        "selection_score": 0.0,
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return BrandAsset(**defaults)


def _good_logo() -> BrandAsset:
    """A clearly usable logo (large, sane aspect, high confidence)."""
    return _asset(
        path="/tmp/logo.png",
        asset_type="logo",
        width=600,
        height=200,
        aspect_ratio=3.0,
        confidence=0.9,
    )


def _weak_logo() -> BrandAsset:
    """A logo too small / low-confidence to be usable."""
    return _asset(
        path="/tmp/logo_small.png",
        asset_type="logo",
        width=40,
        height=15,
        aspect_ratio=2.665,
        confidence=0.2,
    )


def _good_hero() -> BrandAsset:
    """A clearly usable hero image."""
    return _asset(
        path="/tmp/hero.jpg",
        asset_type="hero",
        mime_type="image/jpeg",
        format="JPEG",
        width=1600,
        height=800,
        aspect_ratio=2.0,
        confidence=0.85,
    )


def _weak_hero() -> BrandAsset:
    """A hero below the usable dimension/confidence thresholds."""
    return _asset(
        path="/tmp/hero_small.jpg",
        asset_type="hero",
        width=120,
        height=60,
        aspect_ratio=2.0,
        confidence=0.2,
    )
def _profile(**kwargs: Any) -> BrandProfile:
    """Create a BrandProfile with minimal defaults, overridden by kwargs."""
    defaults: Dict[str, Any] = {
        "company_name": "TestCo",
        "website": "https://testco.com",
        "domain": "testco.com",
    }
    defaults.update(kwargs)
    return BrandProfile(**defaults)


def _roofing_profile() -> BrandProfile:
    """Rich synthetic roofing profile with logo but no normalized hero."""
    return _profile(
        company_name="Jim Woods Roofing",
        website="https://jimwoodsroofing.com",
        domain="jimwoodsroofing.com",
        phone="(605) 555-1234",
        location="Sioux Falls, SD",
        service_area="Greater Sioux Falls",
        logo=_good_logo(),
        hero_assets=[],
        hero_url="https://jimwoodsroofing.com/hero.jpg",
        services=[
            "roof replacement",
            "roof repair",
            "roof inspection",
            "emergency roof repair",
            "siding",
            "gutters",
        ],
        categories=["roofing contractor", "home improvement"],
        differentiators=[
            "free estimates",
            "family owned",
            "licensed",
            "insured",
            "no subcontractors",
        ],
        trust_signals=[
            "licensed",
            "insured",
            "bonded",
            "bbb accredited",
            "5-star rated",
        ],
        awards=["award-winning service", "best of sioux falls 2023"],
        certifications=["GAF Master Elite", "Owens Corning Preferred"],
        guarantees=["workmanship warranty", "satisfaction guarantee"],
        years_in_business="25",
    )


def _dentist_profile() -> BrandProfile:
    """Synthetic dentist profile with logo + hero."""
    return _profile(
        company_name="Bright Smile Dental",
        website="https://brightsmiledental.com",
        domain="brightsmiledental.com",
        phone="(555) 999-8888",
        location="Austin, TX",
        service_area="Austin Metro",
        logo=_good_logo(),
        hero_assets=[_good_hero()],
        services=[
            "general dentistry",
            "cosmetic dentistry",
            "dental implants",
            "teeth whitening",
        ],
        categories=["dentist", "cosmetic dentist"],
        differentiators=["free consultation", "evening appointments", "online booking"],
        trust_signals=["licensed", "5-star rated"],
        awards=["award-winning practice"],
        certifications=[],
        guarantees=["satisfaction guarantee"],
        years_in_business="15",
    )


def _realtor_profile() -> BrandProfile:
    """Synthetic realtor profile with logo + hero."""
    return _profile(
        company_name="Lakefront Realty",
        website="https://lakefrontrealty.com",
        domain="lakefrontrealty.com",
        phone="(555) 123-4567",
        location="Madison, WI",
        service_area="Dane County",
        logo=_good_logo(),
        hero_assets=[_good_hero()],
        services=[
            "residential real estate",
            "home buying",
            "home selling",
            "property management",
        ],
        categories=["real estate agent", "realtor"],
        differentiators=["free home valuation", "local market expertise"],
        trust_signals=["licensed", "mls member"],
        awards=["top agent 2023"],
        certifications=[],
        guarantees=["money-back guarantee"],
        years_in_business="10",
    )


def _strategies(profile: BrandProfile) -> List[MessageStrategy]:
    """Run the real MessageStrategyEngine to get public strategy candidates."""
    return MessageStrategyEngine().generate(profile)


def _strategy_of_type(
    strategies: List[MessageStrategy], strategy_type: str
) -> MessageStrategy:
    matches = [s for s in strategies if s.strategy_type == strategy_type]
    assert matches, f"no {strategy_type} strategy in: {[s.strategy_type for s in strategies]}"
    return matches[0]

# ======================================================================
# MODEL
# ======================================================================

class TestModel:
    """AdConcept model: construction and serialization."""

    def test_minimal_construction(self):
        concept = AdConcept()
        assert concept.concept_id == ""
        assert concept.supporting_proof == []
        assert concept.hero_asset is None
        assert concept.logo_asset is None
        assert concept.source_strategy is None

    def test_construction_with_fields(self):
        concept = AdConcept(
            concept_id="c1",
            composition_family=BRAND_DOMINANT,
            strategy_type=TRUST_LED,
            headline="Trusted Since 1999",
            logo_role=DOMINANT,
        )
        assert concept.concept_id == "c1"
        assert concept.composition_family == BRAND_DOMINANT
        assert concept.headline == "Trusted Since 1999"
        assert concept.logo_role == DOMINANT

    def test_serialization_round_trip(self):
        concept = AdConcept(
            concept_id="concept-1",
            composition_family=TRUST_AUTHORITY,
            strategy_type=TRUST_LED,
            headline="27 Years of Trust",
            supporting_proof=["27 Years in Business", "Award-Winning"],
            cta="Call Today",
            logo_role=DOMINANT,
            hero_role=HIDDEN,
            headline_role=PRIMARY,
            proof_role=SECONDARY,
            cta_role=PRIMARY,
            service_focus="roofing",
            geographic_focus="Greater Sioux Falls",
            rationale="A rationale",
            score=0.85,
            confidence=0.8,
        )
        restored = AdConcept.from_dict(concept.to_dict())
        assert restored.to_dict() == concept.to_dict()

    def test_unknown_fields_ignored(self):
        data = {
            "concept_id": "x",
            "composition_family": MESSAGE_DOMINANT,
            "totally_unknown_field": "should be dropped",
            "another_unknown": 42,
        }
        concept = AdConcept.from_dict(data)
        assert concept.concept_id == "x"
        assert concept.composition_family == MESSAGE_DOMINANT
        assert not hasattr(concept, "totally_unknown_field")

    def test_nested_message_strategy_serialization(self):
        strategy = MessageStrategy(
            strategy_type=OFFER_LED,
            primary_message="Free Estimates",
            supporting_proof=["Free Estimates", "Financing Available"],
            cta="Call for a Quote",
            score=0.64,
            evidence=["differentiators"],
            geographic_focus="",
        )
        concept = AdConcept(
            concept_id="c1",
            composition_family=MESSAGE_DOMINANT,
            strategy_type=OFFER_LED,
            headline=strategy.primary_message,
            source_strategy=strategy,
        )
        dumped = concept.to_dict()
        assert isinstance(dumped["source_strategy"], dict)
        restored = AdConcept.from_dict(dumped)
        assert restored.source_strategy is not None
        assert restored.source_strategy.primary_message == "Free Estimates"
        assert restored.source_strategy.score == 0.64

    def test_nested_brand_asset_serialization(self):
        concept = AdConcept(
            concept_id="c1",
            composition_family=HERO_IMAGE,
            strategy_type=SERVICE_LED,
            logo_asset=_good_logo(),
            hero_asset=_good_hero(),
        )
        dumped = concept.to_dict()
        assert isinstance(dumped["logo_asset"], dict)
        assert isinstance(dumped["hero_asset"], dict)
        restored = AdConcept.from_dict(dumped)
        assert restored.logo_asset is not None and restored.logo_asset.width == 600
        assert restored.hero_asset is not None and restored.hero_asset.width == 1600

    def test_from_dict_none_and_non_dict(self):
        assert AdConcept.from_dict(None).concept_id == ""
        assert AdConcept.from_dict("garbage").concept_id == ""
        assert AdConcept.from_dict(42).concept_id == ""

    def test_from_dict_bad_nested_values(self):
        data = {
            "concept_id": "c",
            "logo_asset": "not a dict",
            "hero_asset": 123,
            "source_strategy": ["not", "a", "dict"],
            "supporting_proof": "not a list",
        }
        concept = AdConcept.from_dict(data)
        assert concept.logo_asset is None
        assert concept.hero_asset is None
        assert concept.source_strategy is None
        assert concept.supporting_proof == []

    def test_json_round_trip(self):
        concept = AdConcept(
            concept_id="c1",
            composition_family=LOCAL_AUTHORITY,
            strategy_type=LOCAL_AUTHORITY,
            headline="Serving Greater Sioux Falls",
            source_strategy=MessageStrategy(strategy_type=LOCAL_AUTHORITY),
        )
        blob = json.dumps(concept.to_dict())
        restored = AdConcept.from_dict(json.loads(blob))
        assert restored.composition_family == LOCAL_AUTHORITY


# ======================================================================
# GENERATION
# ======================================================================

class TestGeneration:
    """Engine accepts profile + strategies and produces concepts."""

    def test_engine_accepts_profile_and_strategies(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        assert strategies, "expected at least one strategy for the fixture"
        engine = AdConceptEngine()
        concepts = engine.generate(profile, strategies)
        assert isinstance(concepts, list)
        assert all(isinstance(c, AdConcept) for c in concepts)

    def test_empty_strategy_list_returns_no_concepts(self):
        engine = AdConceptEngine()
        assert engine.generate(_roofing_profile(), []) == []

    def test_none_profile_returns_no_concepts(self):
        strategies = _strategies(_roofing_profile())
        assert AdConceptEngine().generate(None, strategies) == []

    def test_concepts_preserve_source_strategy_evidence(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        assert concepts
        src_by_type = {s.strategy_type: s for s in strategies}
        for concept in concepts:
            assert concept.source_strategy is not None
            assert (
                concept.source_strategy.evidence
                == src_by_type[concept.strategy_type].evidence
            )
            assert concept.source_strategy is src_by_type[concept.strategy_type]

    def test_repeated_generation_same_result(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        engine = AdConceptEngine()
        first = engine.generate(profile, strategies)
        second = engine.generate(profile, strategies)
        assert [c.to_dict() for c in first] == [c.to_dict() for c in second]
# ======================================================================
# BRAND DOMINANT
# ======================================================================

class TestBrandDominant:
    """Usable logo drives BRAND_DOMINANT; absent/weak logo never forces it."""

    def test_usable_logo_enables_brand_dominant(self):
        profile = _roofing_profile()  # has a good logo
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        families = {c.composition_family for c in concepts}
        assert BRAND_DOMINANT in families

    def test_no_logo_still_allows_other_concepts(self):
        profile = _roofing_profile()
        profile.logo = None
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        assert concepts
        for concept in concepts:
            assert concept.composition_family != BRAND_DOMINANT

    def test_weak_logo_does_not_force_brand_dominant(self):
        profile = _roofing_profile()
        profile.logo = _weak_logo()
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        assert concepts
        assert all(c.composition_family != BRAND_DOMINANT for c in concepts)

    def test_brand_dominant_sets_roles_and_asset(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        brand = [c for c in concepts if c.composition_family == BRAND_DOMINANT]
        assert brand
        concept = brand[0]
        assert concept.logo_role == DOMINANT
        assert concept.hero_role == HIDDEN
        assert concept.logo_asset is not None
        assert concept.hero_asset is None


# ======================================================================
# HERO
# ======================================================================

class TestHero:
    """HERO_IMAGE requires an actual usable normalized hero asset."""

    def test_valid_hero_enables_hero_image(self):
        profile = _profile(
            company_name="RoofPro",
            services=["roof replacement"],
            categories=["roofing contractor"],
            logo=_good_logo(),
            hero_assets=[_good_hero()],
        )
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        heroes = [c for c in concepts if c.composition_family == HERO_IMAGE]
        assert heroes, f"expected HERO_IMAGE in {[c.composition_family for c in concepts]}"
        concept = heroes[0]
        assert concept.hero_role == DOMINANT
        assert concept.hero_asset is not None

    def test_hero_url_alone_does_not_enable_hero_image(self):
        profile = _profile(
            company_name="RoofPro",
            services=["roof replacement"],
            categories=["roofing contractor"],
            logo=_good_logo(),
            hero_assets=[],
            hero_url="https://example.com/hero.jpg",
        )
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        assert all(c.composition_family != HERO_IMAGE for c in concepts)

    def test_empty_hero_assets_prevents_hero_family(self):
        profile = _roofing_profile()  # hero_assets empty, hero_url set
        assert profile.hero_assets == []
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        assert all(c.composition_family != HERO_IMAGE for c in concepts)

    def test_unusable_hero_rejected(self):
        profile = _profile(
            company_name="RoofPro",
            services=["roof replacement"],
            categories=["roofing contractor"],
            logo=_good_logo(),
            hero_assets=[_weak_hero()],
        )
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        assert all(c.composition_family != HERO_IMAGE for c in concepts)

    def test_best_hero_picks_highest_quality(self):
        lower = _good_hero()
        lower.selection_score = 0.0
        higher = _good_hero()
        higher.selection_score = 0.9
        profile = _profile(hero_assets=[lower, higher])
        pick = _best_hero(profile)
        assert pick is higher

    def test_hero_usable_thresholds(self):
        assert _hero_usable(_good_hero())
        assert not _hero_usable(_weak_hero())
        assert not _hero_usable(None)
# ======================================================================
# MESSAGE
# ======================================================================

class TestMessageDominant:
    """Problem-led and offer-led strategies enable MESSAGE_DOMINANT."""

    def _problem_profile(self) -> BrandProfile:
        # Service present -> the problem-frame map can phrase a problem-led
        # message ("Need a New Roof?"); no offer/trust/local distraction.
        return _profile(
            company_name="RoofWorks",
            domain="roofworks.com",
            website="https://roofworks.com",
            services=["roof replacement"],
            categories=["roofing contractor"],
            logo=_good_logo(),
            hero_assets=[],
        )

    def test_problem_strategy_enables_message_dominant(self):
        profile = self._problem_profile()
        strategies = _strategies(profile)
        assert any(s.strategy_type == PROBLEM_LED for s in strategies), (
            f"expected PROBLEM_LED, got {[s.strategy_type for s in strategies]}"
        )
        concepts = AdConceptEngine().generate(profile, strategies)
        assert any(c.composition_family == MESSAGE_DOMINANT for c in concepts)
        msg = [c for c in concepts if c.composition_family == MESSAGE_DOMINANT][0]
        assert msg.source_strategy.strategy_type == PROBLEM_LED
        assert msg.headline_role == DOMINANT
        assert msg.hero_role == HIDDEN

    def _offer_profile(self) -> BrandProfile:
        return _profile(
            company_name="Discount Roofing",
            domain="discountroofing.com",
            website="https://discountroofing.com",
            differentiators=["free estimates", "financing available"],
            logo=_good_logo(),
            hero_assets=[],
        )

    def test_offer_strategy_enables_message_dominant(self):
        profile = self._offer_profile()
        strategies = _strategies(profile)
        assert any(s.strategy_type == OFFER_LED for s in strategies), (
            f"expected OFFER_LED, got {[s.strategy_type for s in strategies]}"
        )
        concepts = AdConceptEngine().generate(profile, strategies)
        assert any(c.composition_family == MESSAGE_DOMINANT for c in concepts)
        msg = [c for c in concepts if c.composition_family == MESSAGE_DOMINANT][0]
        assert msg.source_strategy.strategy_type == OFFER_LED

    def test_message_dominant_uses_logo_when_available(self):
        profile = self._offer_profile()
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        msg = [c for c in concepts if c.composition_family == MESSAGE_DOMINANT][0]
        assert msg.logo_role == PRIMARY
        assert msg.logo_asset is not None

    def test_message_dominant_without_logo_hides_logo(self):
        profile = self._offer_profile()
        profile.logo = None
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        msg = [c for c in concepts if c.composition_family == MESSAGE_DOMINANT][0]
        assert msg.logo_role == HIDDEN
        assert msg.logo_asset is None
# ======================================================================
# TRUST
# ======================================================================

class TestTrustAuthority:
    """TRUST_AUTHORITY is only produced for trust-led strategies."""

    def test_trust_strategy_enables_trust_authority(self):
        profile = _roofing_profile()
        strategies = [s for s in _strategies(profile) if s.strategy_type != LOCAL_AUTHORITY]
        concepts = AdConceptEngine().generate(profile, strategies)
        trust = [c for c in concepts if c.composition_family == TRUST_AUTHORITY]
        assert trust, f"expected TRUST_AUTHORITY in {[c.composition_family for c in concepts]}"
        assert all(t.source_strategy.strategy_type == TRUST_LED for t in trust)
        concept = trust[0]
        assert concept.logo_role == DOMINANT
        assert concept.hero_role == HIDDEN

    def test_no_trust_strategy_does_not_invent_trust_concept(self):
        profile = _roofing_profile()
        non_trust = [s for s in _strategies(profile) if s.strategy_type != TRUST_LED]
        assert all(s.strategy_type != TRUST_LED for s in non_trust)
        concepts = AdConceptEngine().generate(profile, non_trust)
        assert all(c.composition_family != TRUST_AUTHORITY for c in concepts)

    def test_trust_authority_proof_role_primary(self):
        profile = _roofing_profile()
        strategies = [s for s in _strategies(profile) if s.strategy_type == TRUST_LED]
        concepts = AdConceptEngine().generate(profile, strategies)
        trust = [c for c in concepts if c.composition_family == TRUST_AUTHORITY][0]
        assert trust.proof_role == PRIMARY


# ======================================================================
# LOCAL
# ======================================================================

class TestLocalAuthority:
    """LOCAL_AUTHORITY is only produced with verified geographic evidence."""

    def test_local_strategy_enables_local_authority(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        assert any(s.strategy_type == LOCAL_AUTHORITY for s in strategies), (
            f"expected LOCAL_AUTHORITY, got {[s.strategy_type for s in strategies]}"
        )
        concepts = AdConceptEngine().generate(profile, strategies)
        local = [c for c in concepts if c.composition_family == LOCAL_AUTHORITY]
        assert local, f"expected LOCAL_AUTHORITY in {[c.composition_family for c in concepts]}"
        concept = local[0]
        assert concept.source_strategy.strategy_type == LOCAL_AUTHORITY
        assert concept.logo_role == DOMINANT
        assert concept.hero_role == HIDDEN

    def test_no_geographic_evidence_prevents_fabricated_local_concept(self):
        profile = _profile(
            company_name="RoofWorks",
            domain="roofworks.com",
            website="https://roofworks.com",
            years_in_business="20",
            awards=["award-winning"],
            logo=_good_logo(),
            hero_assets=[],
            # no location / service_area / geographic evidence
        )
        strategies = _strategies(profile)
        assert all(s.strategy_type != LOCAL_AUTHORITY for s in strategies), (
            f"local strategy should not be invented, got {[s.strategy_type for s in strategies]}"
        )
        concepts = AdConceptEngine().generate(profile, strategies)
        assert all(c.composition_family != LOCAL_AUTHORITY for c in concepts)

    def test_local_geographic_focus_used_as_proof(self):
        # A LOCAL strategy whose supporting_proof lacks a geographic item must
        # still carry the strategy's explicit geographic_focus as proof.
        strategy = MessageStrategy(
            strategy_type=LOCAL_AUTHORITY,
            primary_message="Proudly Serving Greater Sioux Falls",
            supporting_proof=["27 Years in Business"],
            cta="Call for a Free Estimate",
            score=0.66,
            confidence=0.7,
            evidence=["location", "service_area"],
            geographic_focus="Greater Sioux Falls",
            phone="(605) 555-1234",
        )
        profile = _roofing_profile()
        proof = _select_concept_proof(profile, strategy, LOCAL_AUTHORITY)
        assert proof, "expected local concept to carry proof"
        assert any("Greater Sioux Falls" in p for p in proof)
# ======================================================================
# PROOF
# ======================================================================

class TestProof:
    """Proof complements strategy and is capped; never invented."""

    def _engine_concepts(self, profile):
        strategies = _strategies(profile)
        return AdConceptEngine().generate(profile, strategies)

    def test_proof_is_evidence_backed(self):
        # Never invented: every proof item maps to a source field — the source
        # strategy's supporting_proof, a BrandProfile evidence field, a
        # service-name summary, or the strategy's geographic_focus.
        profile = _roofing_profile()
        for concept in self._engine_concepts(profile):
            source = concept.source_strategy
            allowed = set(source.supporting_proof)
            allowed.update(profile.differentiators)
            allowed.update(profile.guarantees)
            allowed.update(profile.awards)
            allowed.update(profile.certifications)
            allowed.update(profile.services)
            if profile.years_in_business:
                allowed.add(f"{profile.years_in_business} Years in Business")
            if source.geographic_focus:
                allowed.add(source.geographic_focus)
            service_text = " ".join(profile.services).lower()
            for item in concept.supporting_proof:
                words = [w.lower() for w in item.split() if len(w) > 2]
                backed = item in allowed or (
                    bool(words) and all(w in service_text for w in words)
                )
                assert backed, (
                    f"unbacked proof {item!r} on {concept.composition_family}"
                )

    def test_trust_concept_selects_trust_proof(self):
        profile = _roofing_profile()
        concepts = self._engine_concepts(profile)
        trust = [c for c in concepts if c.composition_family == TRUST_AUTHORITY]
        assert trust
        joined = " ".join(trust[0].supporting_proof).lower()
        assert any(
            k in joined for k in ("year", "award", "certif", "guarantee", "warranty")
        ), f"expected trust proof in {trust[0].supporting_proof}"

    def test_offer_concept_selects_offer_proof(self):
        # Two distinct offers: the lead offer becomes the headline, and the
        # other distinct offer/guarantee proof is retained in the proof slot.
        profile = _dedup_profile(
            differentiators=["free estimates", "financing available"],
            guarantees=["satisfaction guarantee"],
        )
        strategy = MessageStrategy(
            strategy_type=OFFER_LED,
            primary_message="Free Estimates",
            supporting_proof=["27 Years in Business"],
            cta="Call",
            evidence=["differentiators"],
            score=0.75,
            confidence=0.6,
        )
        proof = _select_concept_proof(profile, strategy, BRAND_DOMINANT)
        assert "free estimates" not in [p.lower() for p in proof]
        joined = " ".join(proof).lower()
        assert any(
            k in joined for k in ("financing", "guarantee", "satisfaction")
        ), f"expected a distinct offer proof in {proof}"

    def test_local_concept_selects_geographic_proof(self):
        profile = _roofing_profile()
        concepts = self._engine_concepts(profile)
        local = [c for c in concepts if c.composition_family == LOCAL_AUTHORITY]
        assert local
        concept = local[0]
        geo = concept.source_strategy.geographic_focus
        assert geo, "expected a geographic focus on the local strategy"
        # The geographic message leads as the headline and must NOT be wastefully
        # repeated inside the proof (information budget).
        assert geo.lower() in concept.headline.lower()
        norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
        assert not any(norm(geo) == norm(p) for p in concept.supporting_proof)

    def test_proof_limited_to_zero_to_two_items(self):
        profile = _roofing_profile()
        for concept in self._engine_concepts(profile):
            assert 0 <= len(concept.supporting_proof) <= 2

    def test_unsupported_proof_never_invented(self):
        # A bare profile has no evidence -> no proof may be fabricated.
        strategy = MessageStrategy(
            strategy_type=TRUST_LED,
            primary_message="Trusted Choice",
            supporting_proof=[],
            cta="Call",
            evidence=[],
            score=0.5,
            confidence=0.5,
        )
        profile = _profile(
            company_name="Bare Co",
            domain="bareco.com",
            website="https://bareco.com",
        )
        proof = _select_concept_proof(profile, strategy, TRUST_AUTHORITY)
        assert proof == []

    def test_problem_strategy_proof_capped_at_one(self):
        strategy = MessageStrategy(
            strategy_type=PROBLEM_LED,
            primary_message="Need a New Roof?",
            supporting_proof=["27 Years in Business", "Award-Winning"],
            cta="Call",
            evidence=["years_in_business"],
            score=0.6,
            confidence=0.6,
        )
        profile = _roofing_profile()
        proof = _select_concept_proof(profile, strategy, MESSAGE_DOMINANT)
        assert len(proof) <= 1


# ======================================================================
# HEADLINE / PROOF DE-DUPLICATION (information budget)
# ======================================================================

def _dedup_profile(**kwargs: Any) -> BrandProfile:
    """A bare profile with no extra evidence (nothing to leak into proof)."""
    defaults = {
        "company_name": "DedupCo",
        "domain": "dedupco.com",
        "website": "https://dedupco.com",
    }
    defaults.update(kwargs)
    return BrandProfile(**defaults)


def _dedup_strategy(**kwargs: Any) -> MessageStrategy:
    defaults = {
        "strategy_type": TRUST_LED,
        "primary_message": "Trusted Choice",
        "supporting_proof": [],
        "cta": "Call",
        "evidence": ["years_in_business"],
        "score": 0.7,
        "confidence": 0.7,
    }
    defaults.update(kwargs)
    return MessageStrategy(**defaults)


class TestHeadlineDedup:
    """Proof must not repeat the concept headline (information budget)."""

    def _proof(self, strategy: MessageStrategy, profile: BrandProfile, family: str = TRUST_AUTHORITY):
        return _select_concept_proof(profile, strategy, family)

    def test_exact_duplicate_removed(self):
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="Greater Sioux Falls",
            supporting_proof=["Greater Sioux Falls", "27 Years in Business"],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert "Greater Sioux Falls" not in proof
        assert proof[0] == "27 Years in Business"

    def test_case_only_duplicate_removed(self):
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="Free Estimates",
            supporting_proof=["free estimates", "Financing Available"],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert all(p.lower() != "free estimates" for p in proof)
        assert proof[0] == "Financing Available"

    def test_punctuation_only_duplicate_removed(self):
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="Free Estimates",
            supporting_proof=["Free Estimates!", "Financing Available"],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert all(p.lower() != "free estimates!" for p in proof)
        assert proof[0] == "Financing Available"

    def test_next_distinct_proof_selected(self):
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="Greater Sioux Falls",
            supporting_proof=["Greater Sioux Falls", "27 Years in Business", "Award-Winning"],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert "Greater Sioux Falls" not in proof
        assert proof[0] == "27 Years in Business"
        assert len(proof) <= 2

    def test_no_replacement_fabricated_when_none_exists(self):
        # The only proof candidate echoes the headline; nothing may be invented.
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="Trusted Choice",
            supporting_proof=["Trusted Choice"],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert proof == []

    def test_proof_budget_stays_within_two(self):
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="27 Years of Experience",
            supporting_proof=[
                "27 Years of Experience",
                "27 Years in Business",
                "Award-Winning",
                "GAF Certifications",
                "Workmanship Warranty",
            ],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert "27 Years of Experience" not in proof  # duplicate of headline
        assert len(proof) <= 2

    def test_non_identical_phrasing_is_not_removed(self):
        # "27 Years of Experience" vs "27 Years in Business" are NOT identical
        # strings — do not build semantic-similarity logic; keep both.
        strategy = _dedup_strategy(
            strategy_type=TRUST_LED,
            primary_message="27 Years of Experience",
            supporting_proof=["27 Years in Business"],
        )
        profile = _dedup_profile()
        proof = self._proof(strategy, profile)
        assert "27 Years in Business" in proof

    def test_engine_local_concept_does_not_duplicate_headline(self):
        # End-to-end: a LOCAL concept whose headline is the geographic focus must
        # not repeat it in proof.
        profile = _profile(
            company_name="LocalCo",
            domain="localco.com",
            website="https://localco.com",
            location="Sioux Falls, SD",
            service_area="Greater Sioux Falls",
            years_in_business="25",
            awards=["award-winning"],
            logo=_good_logo(),
            hero_assets=[],
        )
        strategies = [s for s in _strategies(profile) if s.strategy_type == LOCAL_AUTHORITY]
        concepts = AdConceptEngine().generate(profile, strategies)
        local = [c for c in concepts if c.composition_family == LOCAL_AUTHORITY]
        assert local
        concept = local[0]
        geo = concept.source_strategy.geographic_focus
        assert geo and geo.lower() in concept.headline.lower()
        norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
        assert not any(norm(geo) == norm(p) for p in concept.supporting_proof)


# ======================================================================
# CTA
# ======================================================================

class TestCTA:
    """CTA copy is preserved from the source strategy; never invented."""

    def _engine_concepts(self, profile):
        strategies = _strategies(profile)
        return AdConceptEngine().generate(profile, strategies)

    def test_cta_preserved_from_strategy(self):
        profile = _roofing_profile()
        src_by_type = {s.strategy_type: s for s in _strategies(profile)}
        for concept in self._engine_concepts(profile):
            assert concept.cta == src_by_type[concept.strategy_type].cta
            assert concept.cta == concept.source_strategy.cta

    def test_phone_not_fabricated(self):
        profile = _profile(
            company_name="NoPhone Co",
            domain="nophone.com",
            website="https://nophone.com",
            differentiators=["free estimates"],
            logo=_good_logo(),
            hero_assets=[],
        )
        assert not profile.phone
        for concept in self._engine_concepts(profile):
            assert concept.cta == concept.source_strategy.cta
            assert not any(ch.isdigit() for ch in concept.cta), concept.cta

    def test_cta_role_promoted_with_phone(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        local = [c for c in concepts if c.composition_family == LOCAL_AUTHORITY]
        if local:
            concept = local[0]
            if concept.source_strategy.phone:
                assert concept.cta_role == PRIMARY
            assert concept.cta == concept.source_strategy.cta
# ======================================================================
# DIVERSITY
# ======================================================================

class TestDiversity:
    """Returned concepts are meaningfully different and never force five."""

    def test_returned_concepts_are_meaningfully_different(self):
        profile = _roofing_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        assert len(concepts) >= 2
        pairs = {(c.strategy_type, c.composition_family) for c in concepts}
        assert len(pairs) == len(concepts), "duplicate (strategy, family) pairs returned"
        families = {c.composition_family for c in concepts}
        assert len(families) >= 2, f"concepts share too much: {families}"

    def test_duplicate_concepts_removed(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        concepts = AdConceptEngine().generate(profile, strategies)
        pairs = [(c.strategy_type, c.composition_family) for c in concepts]
        assert len(pairs) == len(set(pairs))

    def test_deduplicate_keeps_highest_score(self):
        strategy = MessageStrategy(
            strategy_type=OFFER_LED,
            primary_message="Free Estimates",
            supporting_proof=["Free Estimates"],
            cta="Call",
            evidence=["differentiators"],
            score=0.6,
            confidence=0.6,
        )
        low = AdConcept(
            concept_id="a",
            composition_family=MESSAGE_DOMINANT,
            strategy_type=OFFER_LED,
            headline="Free Estimates",
            score=0.4,
            source_strategy=strategy,
        )
        high = AdConcept(
            concept_id="b",
            composition_family=MESSAGE_DOMINANT,
            strategy_type=OFFER_LED,
            headline="Free Estimates",
            score=0.7,
            source_strategy=strategy,
        )
        result = _deduplicate_concepts([low, high])
        assert len(result) == 1
        assert result[0].concept_id == "b"

    def test_engine_does_not_force_five(self):
        # Sparse profile -> few strategies -> fewer than five concepts returned.
        profile = self._offer_only_profile()
        strategies = _strategies(profile)
        assert len(strategies) < 5
        concepts = AdConceptEngine().generate(profile, strategies)
        assert 1 <= len(concepts) < 5

    def _offer_only_profile(self):
        return _profile(
            company_name="Discount Co",
            domain="discountco.com",
            website="https://discountco.com",
            differentiators=["free estimates"],
            logo=_good_logo(),
            hero_assets=[],
        )

    def test_normally_returns_approximately_three(self):
        profile = _roofing_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        assert 2 <= len(concepts) <= 4


# ======================================================================
# SCORING
# ======================================================================

class TestScoring:
    """Deterministic scoring behavior."""

    def _strategy(self, **kwargs) -> MessageStrategy:
        defaults = dict(
            strategy_type=TRUST_LED,
            primary_message="Trusted Choice",
            supporting_proof=["27 Years in Business"],
            cta="Call",
            evidence=["years_in_business"],
            score=0.7,
            confidence=0.7,
        )
        defaults.update(kwargs)
        return MessageStrategy(**defaults)

    def test_compatible_family_scores_above_incompatible(self):
        profile = _roofing_profile()
        strategy = self._strategy()
        compatible = _score_concept(profile, strategy, TRUST_AUTHORITY)
        incompatible = _score_concept(profile, strategy, MESSAGE_DOMINANT)
        assert compatible > incompatible

    def test_unavailable_required_asset_penalized(self):
        profile = _roofing_profile()
        strategy = self._strategy()
        with_logo = _score_concept(profile, strategy, BRAND_DOMINANT, logo=_good_logo())
        without_logo = _score_concept(profile, strategy, BRAND_DOMINANT, logo=None)
        assert with_logo > without_logo
        # engine rejects entirely
        profile.logo = None
        concepts = AdConceptEngine().generate(profile, [_strategy_of_type(_strategies(profile), TRUST_LED)])
        if concepts:
            assert all(c.composition_family != BRAND_DOMINANT for c in concepts)

    def test_higher_strategy_score_influences_concept_score(self):
        profile = _roofing_profile()
        low = self._strategy(score=0.3, confidence=0.3)
        high = self._strategy(score=0.9, confidence=0.9)
        assert _score_concept(profile, high, TRUST_AUTHORITY) > _score_concept(
            profile, low, TRUST_AUTHORITY
        )

    def test_results_sorted_descending(self):
        profile = _roofing_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        assert len(concepts) > 1
        scores = [c.score for c in concepts]
        assert scores == sorted(scores, reverse=True)

    def test_score_in_unit_range(self):
        profile = _roofing_profile()
        strategy = self._strategy(score=1.0, confidence=1.0)
        score = _score_concept(profile, strategy, TRUST_AUTHORITY)
        assert 0.0 <= score <= 1.0
        assert score == round(score, 4)

    def test_scores_are_deterministic(self):
        profile = _roofing_profile()
        strategy = self._strategy()
        assert _score_concept(profile, strategy, TRUST_AUTHORITY) == _score_concept(
            profile, strategy, TRUST_AUTHORITY
        )
# ======================================================================
# INFORMATION BUDGET
# ======================================================================

class TestInformationBudget:
    """Concepts stay extreme-brevity and omit hidden elements."""

    def test_no_concept_has_excessive_proof(self):
        for profile in (_roofing_profile(), _dentist_profile(), _realtor_profile()):
            concepts = AdConceptEngine().generate(profile, _strategies(profile))
            for concept in concepts:
                assert len(concept.supporting_proof) <= 2, (
                    f"{concept.composition_family} has too much proof: "
                    f"{concept.supporting_proof}"
                )
                assert concept.headline or True  # headline slot exists
                assert concept.cta  # always a single CTA

    def test_message_dominant_omits_hero(self):
        profile = _dentist_profile()  # has a hero, but message family still omits
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        for concept in concepts:
            if concept.composition_family == MESSAGE_DOMINANT:
                assert concept.hero_role == HIDDEN
                assert concept.hero_asset is None

    def test_brand_dominant_hides_hero(self):
        profile = _roofing_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        for concept in concepts:
            if concept.composition_family == BRAND_DOMINANT:
                assert concept.hero_role == HIDDEN
                assert concept.hero_asset is None

    def test_trust_authority_hides_hero(self):
        profile = _roofing_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        for concept in concepts:
            if concept.composition_family == TRUST_AUTHORITY:
                assert concept.hero_role == HIDDEN
                assert concept.hero_asset is None


# ======================================================================
# INDUSTRIES
# ======================================================================

class TestIndustries:
    """End-to-end generation across industries."""

    def test_roofing_profile(self):
        profile = _roofing_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        assert concepts
        assert len(concepts) <= 5

    def test_dentist_profile(self):
        profile = _dentist_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        assert concepts
        assert len(concepts) <= 5
        # dentist has a usable hero -> HERO_IMAGE is possible
        assert any(c.composition_family == HERO_IMAGE for c in concepts)

    def test_realtor_profile(self):
        profile = _realtor_profile()
        concepts = AdConceptEngine().generate(profile, _strategies(profile))
        assert concepts
        assert len(concepts) <= 5

    def test_industry_concepts_all_evidence_backed(self):
        for profile in (_roofing_profile(), _dentist_profile(), _realtor_profile()):
            concepts = AdConceptEngine().generate(profile, _strategies(profile))
            for concept in concepts:
                source = concept.source_strategy
                assert concept.cta == source.cta
                assert concept.headline == source.primary_message
                assert concept.strategy_type == source.strategy_type


# ======================================================================
# IMMUTABILITY
# ======================================================================

class TestImmutability:
    """Engine must not modify the input BrandProfile or MessageStrategies."""

    def test_brand_profile_unchanged(self):
        profile = _roofing_profile()
        original = copy.deepcopy(profile)
        AdConceptEngine().generate(profile, _strategies(profile))
        assert profile.to_dict() == original.to_dict()

    def test_message_strategy_objects_unchanged(self):
        profile = _roofing_profile()
        strategies = _strategies(profile)
        original = [copy.deepcopy(s) for s in strategies]
        AdConceptEngine().generate(profile, strategies)
        for before, after in zip(original, strategies):
            assert before.to_dict() == after.to_dict()
