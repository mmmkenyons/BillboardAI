"""Sprint 2D: Message Strategy Engine tests."""
from __future__ import annotations

import copy
import json
from typing import Any, Dict

import pytest

from engine.brand_profile import BrandProfile
from engine.message_strategy import (
    TRUST_LED,
    SERVICE_LED,
    OFFER_LED,
    LOCAL_AUTHORITY,
    PROBLEM_LED,
    STRATEGY_TYPES,
    MessageStrategy,
    MessageStrategyEngine,
    _select_primary_service,
    _select_cta,
    _select_supporting_proof,
    _has_trust_evidence,
    _has_service_evidence,
    _has_offer_evidence,
    _has_local_evidence,
    _has_problem_evidence,
    _score_strategy,
    _compute_confidence,
    _deduplicate_strategies,
    _problem_frame_for_service,
    _PROBLEM_FRAME_MAP,
    _ANCILLARY_SERVICES,
    _CORE_SERVICE_PRIORITY,
)


# ======================================================================
# Helpers
# ======================================================================

def _profile(**kwargs: Any) -> BrandProfile:
    """Create a BrandProfile with defaults, overridden by kwargs."""
    defaults: Dict[str, Any] = {
        "company_name": "TestCo",
        "website": "https://testco.com",
        "domain": "testco.com",
    }
    defaults.update(kwargs)
    return BrandProfile(**defaults)


def _roofing_profile() -> BrandProfile:
    """Synthetic roofing profile with rich evidence."""
    return _profile(
        company_name="Jim Woods Roofing",
        website="https://jimwoodsroofing.com",
        domain="jimwoodsroofing.com",
        phone="(605) 555-1234",
        location="Sioux Falls, SD",
        service_area="Greater Sioux Falls",
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
    """Synthetic dentist profile."""
    return _profile(
        company_name="Bright Smile Dental",
        website="https://brightsmiledental.com",
        domain="brightsmiledental.com",
        phone="(555) 999-8888",
        location="Austin, TX",
        service_area="Austin Metro",
        services=[
            "general dentistry",
            "cosmetic dentistry",
            "dental implants",
            "teeth whitening",
        ],
        categories=["dentist", "cosmetic dentist"],
        differentiators=[
            "free consultation",
            "evening appointments",
            "online booking",
        ],
        trust_signals=["licensed", "5-star rated"],
        awards=[],
        certifications=["ADA Member"],
        guarantees=["satisfaction guarantee"],
        years_in_business="15",
    )


def _realtor_profile() -> BrandProfile:
    """Synthetic realtor profile."""
    return _profile(
        company_name="HomeTown Realty",
        website="https://hometownrealty.com",
        domain="hometownrealty.com",
        phone="(555) 777-6666",
        location="Nashville, TN",
        service_area="Greater Nashville",
        services=["real estate", "property management", "home staging"],
        categories=["real estate agent", "property management"],
        differentiators=[
            "free consultation",
            "locally owned",
            "personalized service",
        ],
        trust_signals=["licensed", "5-star rated", "chamber of commerce"],
        awards=["top rated agent 2024"],
        certifications=["CRS Certified"],
        guarantees=[],
        years_in_business="10",
    )


def _empty_profile() -> BrandProfile:
    """Profile with no business intelligence."""
    return _profile(company_name="EmptyCo")


# ======================================================================
# Model / Serialization
# ======================================================================

class TestMessageStrategyModel:
    """MessageStrategy dataclass and serialization."""

    def test_default_construction(self):
        ms = MessageStrategy()
        assert ms.strategy_type == ""
        assert ms.primary_message == ""
        assert ms.supporting_proof == []
        assert ms.cta == ""
        assert ms.rationale == ""
        assert ms.score == 0.0
        assert ms.evidence == []
        assert ms.service_focus == ""
        assert ms.geographic_focus == ""
        assert ms.phone == ""
        assert ms.confidence == 0.0

    def test_full_construction(self):
        ms = MessageStrategy(
            strategy_type=TRUST_LED,
            primary_message="25 Years of Experience",
            supporting_proof=["Award-Winning", "Free Estimates"],
            cta="Call (605) 555-1234",
            rationale="Lead with credibility.",
            score=0.85,
            evidence=["years_in_business", "awards"],
            service_focus="Roof Replacement",
            geographic_focus="Sioux Falls",
            phone="(605) 555-1234",
            confidence=0.75,
        )
        assert ms.strategy_type == TRUST_LED
        assert ms.primary_message == "25 Years of Experience"
        assert len(ms.supporting_proof) == 2
        assert ms.cta == "Call (605) 555-1234"
        assert ms.score == 0.85
        assert ms.confidence == 0.75

    def test_to_dict_roundtrip(self):
        ms = MessageStrategy(
            strategy_type=SERVICE_LED,
            primary_message="Roof Replacement",
            supporting_proof=["25 Years in Business"],
            cta="Call (605) 555-1234",
            rationale="Lead with core service.",
            score=0.70,
            evidence=["services"],
            service_focus="Roof Replacement",
            phone="(605) 555-1234",
            confidence=0.55,
        )
        d = ms.to_dict()
        assert d["strategy_type"] == SERVICE_LED
        assert d["primary_message"] == "Roof Replacement"
        assert d["supporting_proof"] == ["25 Years in Business"]
        assert d["score"] == 0.70
        assert d["confidence"] == 0.55

    def test_from_dict_roundtrip(self):
        original = MessageStrategy(
            strategy_type=OFFER_LED,
            primary_message="Free Estimates",
            supporting_proof=["25 Years in Business", "Award-Winning"],
            cta="Get a Free Estimate",
            rationale="Lead with offer.",
            score=0.65,
            evidence=["differentiators"],
            confidence=0.45,
        )
        d = original.to_dict()
        restored = MessageStrategy.from_dict(d)
        assert restored.strategy_type == original.strategy_type
        assert restored.primary_message == original.primary_message
        assert restored.supporting_proof == original.supporting_proof
        assert restored.cta == original.cta
        assert restored.rationale == original.rationale
        assert restored.score == original.score
        assert restored.evidence == original.evidence
        assert restored.confidence == original.confidence

    def test_from_dict_empty(self):
        ms = MessageStrategy.from_dict({})
        assert ms.strategy_type == ""
        assert ms.primary_message == ""

    def test_from_dict_none(self):
        ms = MessageStrategy.from_dict(None)
        assert ms.strategy_type == ""

    def test_from_dict_unknown_fields_ignored(self):
        ms = MessageStrategy.from_dict({
            "strategy_type": TRUST_LED,
            "primary_message": "Test",
            "unknown_field": "should be ignored",
            "another_unknown": 42,
        })
        assert ms.strategy_type == TRUST_LED
        assert ms.primary_message == "Test"

    def test_from_dict_coerces_list_fields(self):
        ms = MessageStrategy.from_dict({
            "strategy_type": TRUST_LED,
            "supporting_proof": "not a list",
            "evidence": None,
        })
        assert ms.supporting_proof == []
        assert ms.evidence == []

    def test_from_dict_coerces_float_fields(self):
        ms = MessageStrategy.from_dict({
            "strategy_type": TRUST_LED,
            "score": "0.85",
            "confidence": "not a number",
        })
        assert ms.score == 0.85
        assert ms.confidence == 0.0

    def test_from_dict_coerces_string_fields(self):
        ms = MessageStrategy.from_dict({
            "strategy_type": TRUST_LED,
            "primary_message": 123,
            "cta": None,
        })
        assert ms.primary_message == "123"
        assert ms.cta == ""

    def test_to_dict_is_json_serializable(self):
        ms = MessageStrategy(
            strategy_type=TRUST_LED,
            primary_message="Test",
            supporting_proof=["Proof A", "Proof B"],
            evidence=["years_in_business"],
            score=0.75,
            confidence=0.60,
        )
        d = ms.to_dict()
        json_str = json.dumps(d)
        restored = json.loads(json_str)
        assert restored["strategy_type"] == TRUST_LED
        assert restored["score"] == 0.75


# ======================================================================
# Evidence safeguards
# ======================================================================

class TestEvidenceSafeguards:
    """Evidence must be traceable to BrandProfile fields."""

    def test_empty_profile_produces_no_strategies(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_empty_profile())
        assert results == []

    def test_none_profile_produces_empty(self):
        engine = MessageStrategyEngine()
        results = engine.generate(None)
        assert results == []

    def test_trust_evidence_requires_real_data(self):
        assert not _has_trust_evidence(_empty_profile())
        assert _has_trust_evidence(_profile(years_in_business="10"))
        assert _has_trust_evidence(_profile(awards=["award-winning"]))
        assert _has_trust_evidence(_profile(certifications=["Certified"]))
        assert _has_trust_evidence(_profile(guarantees=["warranty"]))
        assert _has_trust_evidence(_profile(trust_signals=["licensed"]))

    def test_service_evidence_requires_real_data(self):
        assert not _has_service_evidence(_empty_profile())
        assert _has_service_evidence(_profile(services=["roofing"]))
        assert _has_service_evidence(_profile(categories=["contractor"]))

    def test_offer_evidence_requires_real_data(self):
        assert not _has_offer_evidence(_empty_profile())
        assert _has_offer_evidence(_profile(differentiators=["free estimates"]))
        assert _has_offer_evidence(_profile(differentiators=["financing available"]))
        assert _has_offer_evidence(_profile(guarantees=["money-back guarantee"]))

    def test_local_evidence_requires_real_data(self):
        assert not _has_local_evidence(_empty_profile())
        assert _has_local_evidence(_profile(service_area="Dallas"))
        assert _has_local_evidence(_profile(location="Dallas"))

    def test_problem_evidence_requires_mapped_service(self):
        assert not _has_problem_evidence(_empty_profile())
        assert not _has_problem_evidence(_profile(services=["nonexistent service"]))
        assert _has_problem_evidence(_profile(services=["roof replacement"]))

    def test_problem_frame_only_exact_matches(self):
        assert _problem_frame_for_service("roof replacement") == "Need a New Roof?"
        assert _problem_frame_for_service("Roof Replacement") == "Need a New Roof?"
        assert _problem_frame_for_service("nonexistent") is None
        assert _problem_frame_for_service("") is None

    def test_every_claim_has_evidence_field(self):
        engine = MessageStrategyEngine()
        profile = _roofing_profile()
        results = engine.generate(profile)
        for s in results:
            assert s.evidence, f"{s.strategy_type} has no evidence"
            assert all(isinstance(e, str) and e for e in s.evidence), \
                f"{s.strategy_type} has empty evidence entry"

    def test_primary_message_not_empty_when_evidence_exists(self):
        engine = MessageStrategyEngine()
        profile = _roofing_profile()
        results = engine.generate(profile)
        for s in results:
            assert s.primary_message, f"{s.strategy_type} has empty primary_message"


# ======================================================================
# TRUST_LED
# ======================================================================

class TestTrustLed:
    """TRUST_LED strategy generation."""

    def test_years_in_business_becomes_primary(self):
        engine = MessageStrategyEngine()
        profile = _profile(years_in_business="30")
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 1
        assert trust[0].primary_message == "30 Years of Experience"
        assert "years_in_business" in trust[0].evidence

    def test_award_becomes_primary_when_no_years(self):
        engine = MessageStrategyEngine()
        profile = _profile(awards=["award-winning service"])
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 1
        assert "Award-Winning" in trust[0].primary_message

    def test_certifications_fallback(self):
        engine = MessageStrategyEngine()
        profile = _profile(certifications=["GAF Master Elite"])
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 1
        assert "Certified" in trust[0].primary_message

    def test_guarantees_fallback(self):
        engine = MessageStrategyEngine()
        profile = _profile(guarantees=["workmanship warranty"])
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 1
        assert "Workmanship" in trust[0].primary_message

    def test_licensed_insured_fallback(self):
        engine = MessageStrategyEngine()
        profile = _profile(trust_signals=["licensed", "insured"])
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 1
        # When licensed+insured are separate entries, falls through to "Trusted Service"
        assert trust[0].primary_message == "Trusted Service"

    def test_no_trust_evidence_no_candidate(self):
        engine = MessageStrategyEngine()
        profile = _profile()
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 0

    def test_trust_led_has_rationale(self):
        engine = MessageStrategyEngine()
        profile = _profile(years_in_business="20")
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        assert len(trust) == 1
        assert "credibility" in trust[0].rationale.lower()
        assert "Evidence:" in trust[0].rationale


# ======================================================================
# SERVICE_LED
# ======================================================================

class TestServiceLed:
    """SERVICE_LED strategy generation."""

    def test_service_becomes_primary(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["roof replacement"])
        results = engine.generate(profile)
        svc = [s for s in results if s.strategy_type == SERVICE_LED]
        assert len(svc) == 1
        assert "Roof Replacement" in svc[0].primary_message

    def test_category_fallback_when_no_services(self):
        engine = MessageStrategyEngine()
        profile = _profile(categories=["roofing contractor"])
        results = engine.generate(profile)
        svc = [s for s in results if s.strategy_type == SERVICE_LED]
        assert len(svc) == 1
        assert "Roofing Contractor" in svc[0].primary_message

    def test_no_service_evidence_no_candidate(self):
        engine = MessageStrategyEngine()
        profile = _profile()
        results = engine.generate(profile)
        svc = [s for s in results if s.strategy_type == SERVICE_LED]
        assert len(svc) == 0

    def test_service_focus_set(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["roof replacement"])
        results = engine.generate(profile)
        svc = [s for s in results if s.strategy_type == SERVICE_LED]
        assert len(svc) == 1
        assert svc[0].service_focus

    def test_primary_service_prefers_core_over_ancillary(self):
        profile = _profile(services=["siding", "roof replacement"])
        primary = _select_primary_service(profile)
        assert primary == "roof replacement"

    def test_primary_service_multi_word_bonus(self):
        profile = _profile(services=["roofing", "residential roofing"])
        primary = _select_primary_service(profile)
        assert primary == "residential roofing"

    def test_primary_service_category_alignment(self):
        """Category-aligned service gets bonus, but base priority still matters."""
        profile = _profile(
            services=["roof replacement", "residential roofing"],
            categories=["roofing contractor"],
        )
        primary = _select_primary_service(profile)
        # residential roofing: priority 10 + 3 (3-word bonus) + 3 (category) = 16
        # roof replacement: priority 9 + 2 (2-word bonus) + 3 (category) = 14
        assert primary == "residential roofing"

    def test_primary_service_empty_services(self):
        assert _select_primary_service(_profile()) == ""


# ======================================================================
# OFFER_LED
# ======================================================================

class TestOfferLed:
    """OFFER_LED strategy generation."""

    def test_free_estimates_becomes_primary(self):
        engine = MessageStrategyEngine()
        profile = _profile(differentiators=["free estimates"])
        results = engine.generate(profile)
        offer = [s for s in results if s.strategy_type == OFFER_LED]
        assert len(offer) == 1
        assert offer[0].primary_message == "Free Estimates"

    def test_financing_available(self):
        engine = MessageStrategyEngine()
        profile = _profile(differentiators=["financing available"])
        results = engine.generate(profile)
        offer = [s for s in results if s.strategy_type == OFFER_LED]
        assert len(offer) == 1
        assert offer[0].primary_message == "Financing Available"

    def test_money_back_from_guarantees(self):
        engine = MessageStrategyEngine()
        profile = _profile(guarantees=["money-back guarantee"])
        results = engine.generate(profile)
        offer = [s for s in results if s.strategy_type == OFFER_LED]
        assert len(offer) == 1
        assert "Money-Back" in offer[0].primary_message

    def test_no_offer_evidence_no_candidate(self):
        engine = MessageStrategyEngine()
        profile = _profile()
        results = engine.generate(profile)
        offer = [s for s in results if s.strategy_type == OFFER_LED]
        assert len(offer) == 0

    def test_offer_priority_free_estimates_first(self):
        engine = MessageStrategyEngine()
        profile = _profile(differentiators=[
            "discounts available",
            "free estimates",
            "financing available",
        ])
        results = engine.generate(profile)
        offer = [s for s in results if s.strategy_type == OFFER_LED]
        assert len(offer) == 1
        assert offer[0].primary_message == "Free Estimates"


# ======================================================================
# LOCAL_AUTHORITY
# ======================================================================

class TestLocalAuthority:
    """LOCAL_AUTHORITY strategy generation."""

    def test_service_area_becomes_primary(self):
        engine = MessageStrategyEngine()
        profile = _profile(service_area="Greater Dallas")
        results = engine.generate(profile)
        local = [s for s in results if s.strategy_type == LOCAL_AUTHORITY]
        assert len(local) == 1
        assert local[0].primary_message == "Greater Dallas"

    def test_location_fallback(self):
        engine = MessageStrategyEngine()
        profile = _profile(location="Dallas, TX")
        results = engine.generate(profile)
        local = [s for s in results if s.strategy_type == LOCAL_AUTHORITY]
        assert len(local) == 1
        assert local[0].primary_message == "Dallas, TX"

    def test_service_area_preferred_over_location(self):
        engine = MessageStrategyEngine()
        profile = _profile(service_area="DFW Metroplex", location="Dallas, TX")
        results = engine.generate(profile)
        local = [s for s in results if s.strategy_type == LOCAL_AUTHORITY]
        assert len(local) == 1
        assert local[0].primary_message == "DFW Metroplex"

    def test_no_local_evidence_no_candidate(self):
        engine = MessageStrategyEngine()
        profile = _profile()
        results = engine.generate(profile)
        local = [s for s in results if s.strategy_type == LOCAL_AUTHORITY]
        assert len(local) == 0

    def test_geographic_focus_set(self):
        engine = MessageStrategyEngine()
        profile = _profile(service_area="Austin Metro")
        results = engine.generate(profile)
        local = [s for s in results if s.strategy_type == LOCAL_AUTHORITY]
        assert len(local) == 1
        assert local[0].geographic_focus == "Austin Metro"


# ======================================================================
# PROBLEM_LED safety
# ======================================================================

class TestProblemLed:
    """PROBLEM_LED strategy generation and safety."""

    def test_roof_replacement_problem_frame(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["roof replacement"])
        results = engine.generate(profile)
        problem = [s for s in results if s.strategy_type == PROBLEM_LED]
        assert len(problem) == 1
        assert problem[0].primary_message == "Need a New Roof?"

    def test_roof_repair_problem_frame(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["roof repair"])
        results = engine.generate(profile)
        problem = [s for s in results if s.strategy_type == PROBLEM_LED]
        assert len(problem) == 1
        assert problem[0].primary_message == "Roof Problems?"

    def test_no_problem_frame_for_unmapped_service(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["custom software development"])
        results = engine.generate(profile)
        problem = [s for s in results if s.strategy_type == PROBLEM_LED]
        assert len(problem) == 0

    def test_problem_led_never_invents(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["landscaping services"])
        results = engine.generate(profile)
        problem = [s for s in results if s.strategy_type == PROBLEM_LED]
        assert len(problem) == 0

    def test_problem_led_has_service_focus(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["roof replacement"])
        results = engine.generate(profile)
        problem = [s for s in results if s.strategy_type == PROBLEM_LED]
        assert len(problem) == 1
        assert problem[0].service_focus == "roof replacement"

    def test_problem_frame_map_is_bounded(self):
        assert len(_PROBLEM_FRAME_MAP) < 50, \
            "PROBLEM_FRAME_MAP should remain bounded"

    def test_problem_frame_map_keys_are_lowercase(self):
        for key in _PROBLEM_FRAME_MAP:
            assert key == key.lower(), f"Key {key!r} should be lowercase"

    def test_problem_frame_map_values_are_questions(self):
        for value in _PROBLEM_FRAME_MAP.values():
            assert "?" in value, f"Value {value!r} should be a question"


# ======================================================================
# CTA
# ======================================================================

class TestCTA:
    """CTA selection rules."""

    def test_phone_cta(self):
        cta, phone = _select_cta(_profile(phone="(605) 555-1234"))
        assert cta == "Call (605) 555-1234"
        assert phone == "(605) 555-1234"

    def test_free_estimates_cta(self):
        cta, phone = _select_cta(_profile(
            phone="",
            differentiators=["free estimates"],
        ))
        assert cta == "Get a Free Estimate"
        assert phone == ""

    def test_default_cta(self):
        cta, phone = _select_cta(_profile(phone=""))
        assert cta == "Learn More"
        assert phone == ""

    def test_phone_priority_over_free_estimates(self):
        cta, phone = _select_cta(_profile(
            phone="(605) 555-1234",
            differentiators=["free estimates"],
        ))
        assert cta == "Call (605) 555-1234"

    def test_cta_never_invents_url(self):
        cta, _ = _select_cta(_profile(phone=""))
        assert "http" not in cta.lower()
        assert ".com" not in cta.lower()

    def test_cta_never_invents_urgency(self):
        cta, _ = _select_cta(_profile(phone=""))
        assert "now" not in cta.lower()
        assert "today" not in cta.lower()
        assert "limited" not in cta.lower()

    def test_cta_in_strategy_uses_phone(self):
        engine = MessageStrategyEngine()
        profile = _profile(phone="(605) 555-1234", years_in_business="20")
        results = engine.generate(profile)
        for s in results:
            if s.phone:
                assert s.phone == "(605) 555-1234"
                assert "Call" in s.cta


# ======================================================================
# Scoring
# ======================================================================

class TestScoring:
    """Deterministic scoring rules."""

    def test_score_in_range(self):
        engine = MessageStrategyEngine()
        profile = _roofing_profile()
        results = engine.generate(profile)
        for s in results:
            assert 0.0 <= s.score <= 1.0, \
                f"{s.strategy_type} score {s.score} out of range"

    def test_trust_led_scores_higher_than_problem_led(self):
        engine = MessageStrategyEngine()
        profile = _roofing_profile()
        results = engine.generate(profile)
        trust = [s for s in results if s.strategy_type == TRUST_LED]
        problem = [s for s in results if s.strategy_type == PROBLEM_LED]
        if trust and problem:
            assert trust[0].score > problem[0].score, \
                f"TRUST_LED ({trust[0].score}) should outscore PROBLEM_LED ({problem[0].score})"

    def test_more_evidence_higher_score(self):
        score_rich = _score_strategy(
            _roofing_profile(), TRUST_LED, "25 Years",
            ["Award-Winning", "Free Estimates"],
            ["years_in_business", "awards", "differentiators"],
        )
        score_poor = _score_strategy(
            _profile(years_in_business="5"), TRUST_LED, "5 Years",
            [],
            ["years_in_business"],
        )
        assert score_rich > score_poor, \
            f"Rich ({score_rich}) should outscore poor ({score_poor})"

    def test_generic_message_penalized(self):
        score_generic = _score_strategy(
            _profile(), TRUST_LED, "Trusted Service", [], ["trust_signals"],
        )
        score_specific = _score_strategy(
            _profile(), TRUST_LED, "25 Years of Experience", [], ["years_in_business"],
        )
        assert score_specific >= score_generic

    def test_long_message_penalized(self):
        score_long = _score_strategy(
            _profile(), TRUST_LED,
            "We Are The Very Best Roofing Company In The Entire Region",
            [], ["trust_signals"],
        )
        score_short = _score_strategy(
            _profile(), TRUST_LED, "Best Roofing", [], ["trust_signals"],
        )
        assert score_short > score_long

    def test_ancillary_service_penalized(self):
        score_ancillary = _score_strategy(
            _profile(), SERVICE_LED, "Siding", [], ["services"],
        )
        score_core = _score_strategy(
            _profile(), SERVICE_LED, "Roof Replacement", [], ["services"],
        )
        assert score_core > score_ancillary

    def test_confidence_in_range(self):
        conf = _compute_confidence(_roofing_profile(), [
            "years_in_business", "awards", "certifications",
        ])
        assert 0.0 <= conf <= 1.0

    def test_confidence_higher_with_more_evidence(self):
        conf_rich = _compute_confidence(_roofing_profile(), [
            "years_in_business", "awards", "certifications", "guarantees",
        ])
        conf_poor = _compute_confidence(_profile(), ["services"])
        assert conf_rich > conf_poor

    def test_scores_are_deterministic(self):
        engine = MessageStrategyEngine()
        profile = _roofing_profile()
        results1 = engine.generate(profile)
        results2 = engine.generate(profile)
        assert len(results1) == len(results2)
        for s1, s2 in zip(results1, results2):
            assert s1.score == s2.score
            assert s1.strategy_type == s2.strategy_type
            assert s1.primary_message == s2.primary_message


# ======================================================================
# Deduplication
# ======================================================================

class TestDeduplication:
    """Strategy deduplication rules."""

    def test_identical_strategies_deduplicated(self):
        s1 = MessageStrategy(
            strategy_type=TRUST_LED,
            primary_message="25 Years",
            score=0.80,
        )
        s2 = MessageStrategy(
            strategy_type=TRUST_LED,
            primary_message="25 Years",
            score=0.70,
        )
        result = _deduplicate_strategies([s1, s2])
        assert len(result) == 1
        assert result[0].score == 0.80

    def test_different_types_not_deduplicated(self):
        s1 = MessageStrategy(strategy_type=TRUST_LED, primary_message="Test", score=0.80)
        s2 = MessageStrategy(strategy_type=SERVICE_LED, primary_message="Test", score=0.70)
        result = _deduplicate_strategies([s1, s2])
        assert len(result) == 2

    def test_different_messages_not_deduplicated(self):
        s1 = MessageStrategy(strategy_type=TRUST_LED, primary_message="Msg A", score=0.80)
        s2 = MessageStrategy(strategy_type=TRUST_LED, primary_message="Msg B", score=0.70)
        result = _deduplicate_strategies([s1, s2])
        assert len(result) == 2

    def test_case_insensitive_dedup(self):
        s1 = MessageStrategy(strategy_type=TRUST_LED, primary_message="Test Msg", score=0.80)
        s2 = MessageStrategy(strategy_type=TRUST_LED, primary_message="test msg", score=0.70)
        result = _deduplicate_strategies([s1, s2])
        assert len(result) == 1
        assert result[0].score == 0.80

    def test_empty_list(self):
        assert _deduplicate_strategies([]) == []

    def test_engine_output_has_no_duplicates(self):
        engine = MessageStrategyEngine()
        profile = _roofing_profile()
        results = engine.generate(profile)
        seen = set()
        for s in results:
            key = (s.strategy_type, s.primary_message.lower())
            assert key not in seen, f"Duplicate: {key}"
            seen.add(key)


# ======================================================================
# Supporting proof
# ======================================================================

class TestSupportingProof:
    """Supporting proof selection."""

    def test_years_in_business_selected(self):
        proof = _select_supporting_proof(_profile(years_in_business="30"), TRUST_LED)
        assert any("30 Years" in p for p in proof)

    def test_awards_selected(self):
        proof = _select_supporting_proof(
            _profile(awards=["award-winning service"]), TRUST_LED,
        )
        assert any("Award-Winning" in p for p in proof)

    def test_guarantees_selected(self):
        proof = _select_supporting_proof(
            _profile(guarantees=["workmanship warranty"]), TRUST_LED,
        )
        assert any("Workmanship" in p for p in proof)

    def test_differentiators_selected(self):
        proof = _select_supporting_proof(
            _profile(differentiators=["free estimates", "family owned"]), TRUST_LED,
        )
        assert any("Free Estimates" in p for p in proof)

    def test_max_two_proof_items(self):
        proof = _select_supporting_proof(_roofing_profile(), TRUST_LED)
        assert len(proof) <= 2

    def test_no_duplicate_proof(self):
        proof = _select_supporting_proof(_roofing_profile(), TRUST_LED)
        assert len(proof) == len(set(p.lower() for p in proof))

    def test_empty_profile_returns_empty(self):
        proof = _select_supporting_proof(_empty_profile(), TRUST_LED)
        assert proof == []

    def test_service_area_in_proof(self):
        proof = _select_supporting_proof(
            _profile(service_area="Greater Dallas"), LOCAL_AUTHORITY,
        )
        assert any("Serving" in p for p in proof)

    def test_certifications_in_proof(self):
        proof = _select_supporting_proof(
            _profile(certifications=["GAF Master Elite"]), TRUST_LED,
        )
        assert any("GAF Master Elite" in p for p in proof)


# ======================================================================
# Synthetic profiles (roofing / dentist / realtor)
# ======================================================================

class TestSyntheticProfiles:
    """End-to-end tests with synthetic industry profiles."""

    def test_roofing_profile_generates_all_five_types(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_roofing_profile())
        types = {s.strategy_type for s in results}
        assert types == set(STRATEGY_TYPES), \
            f"Expected all 5 types, got {types}"

    def test_roofing_profile_trust_led_is_top(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_roofing_profile())
        assert results[0].strategy_type == TRUST_LED, \
            f"Expected TRUST_LED first, got {results[0].strategy_type}"

    def test_roofing_profile_sorted_by_score(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_roofing_profile())
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score, \
                f"Results not sorted: {results[i].score} < {results[i+1].score}"

    def test_dentist_profile_generates_strategies(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_dentist_profile())
        assert len(results) >= 3
        types = {s.strategy_type for s in results}
        assert TRUST_LED in types
        assert SERVICE_LED in types

    def test_dentist_service_is_general_dentistry(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_dentist_profile())
        svc = [s for s in results if s.strategy_type == SERVICE_LED]
        assert len(svc) == 1
        assert "General Dentistry" in svc[0].primary_message

    def test_realtor_profile_generates_strategies(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_realtor_profile())
        assert len(results) >= 3
        types = {s.strategy_type for s in results}
        assert TRUST_LED in types
        assert SERVICE_LED in types
        assert LOCAL_AUTHORITY in types

    def test_realtor_service_is_real_estate(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_realtor_profile())
        svc = [s for s in results if s.strategy_type == SERVICE_LED]
        assert len(svc) == 1
        assert "Real Estate" in svc[0].primary_message

    def test_all_profiles_produce_concise_messages(self):
        for profile in [_roofing_profile(), _dentist_profile(), _realtor_profile()]:
            engine = MessageStrategyEngine()
            results = engine.generate(profile)
            for s in results:
                word_count = len(s.primary_message.split())
                assert word_count <= 10, \
                    f"{s.strategy_type} message too long: {s.primary_message!r} ({word_count} words)"


# ======================================================================
# BrandProfile immutability
# ======================================================================

class TestBrandProfileImmutability:
    """MessageStrategyEngine must not modify the input BrandProfile."""

    def test_engine_does_not_modify_profile(self):
        profile = _roofing_profile()
        original = copy.deepcopy(profile)
        engine = MessageStrategyEngine()
        engine.generate(profile)
        assert profile.company_name == original.company_name
        assert profile.phone == original.phone
        assert profile.services == original.services
        assert profile.years_in_business == original.years_in_business
        assert profile.awards == original.awards
        assert profile.certifications == original.certifications
        assert profile.guarantees == original.guarantees
        assert profile.differentiators == original.differentiators
        assert profile.trust_signals == original.trust_signals
        assert profile.categories == original.categories
        assert profile.service_area == original.service_area
        assert profile.location == original.location

    def test_engine_does_not_modify_empty_profile(self):
        profile = _empty_profile()
        original = copy.deepcopy(profile)
        engine = MessageStrategyEngine()
        engine.generate(profile)
        assert profile.company_name == original.company_name
        assert profile.services == original.services

    def test_repeated_generation_same_result(self):
        profile = _roofing_profile()
        engine = MessageStrategyEngine()
        results1 = engine.generate(profile)
        results2 = engine.generate(profile)
        assert len(results1) == len(results2)
        for s1, s2 in zip(results1, results2):
            assert s1.to_dict() == s2.to_dict()


# ======================================================================
# Strategy type constants
# ======================================================================

class TestStrategyTypes:
    """Strategy type constants."""

    def test_all_five_types_defined(self):
        assert len(STRATEGY_TYPES) == 5
        assert TRUST_LED in STRATEGY_TYPES
        assert SERVICE_LED in STRATEGY_TYPES
        assert OFFER_LED in STRATEGY_TYPES
        assert LOCAL_AUTHORITY in STRATEGY_TYPES
        assert PROBLEM_LED in STRATEGY_TYPES

    def test_types_are_strings(self):
        for t in STRATEGY_TYPES:
            assert isinstance(t, str)

    def test_types_are_distinct(self):
        assert len(set(STRATEGY_TYPES)) == 5


# ======================================================================
# Edge cases
# ======================================================================

class TestEdgeCases:
    """Edge case handling."""

    def test_non_numeric_years_in_business(self):
        engine = MessageStrategyEngine()
        profile = _profile(years_in_business="since 1990")
        results = engine.generate(profile)
        assert isinstance(results, list)

    def test_very_long_award_name(self):
        engine = MessageStrategyEngine()
        profile = _profile(awards=["This is an extremely long award name that goes on and on and on"])
        results = engine.generate(profile)
        assert isinstance(results, list)

    def test_unicode_in_profile(self):
        engine = MessageStrategyEngine()
        profile = _profile(
            company_name="Cafe Creme",
            location="Sao Paulo, BR",
            services=["cafe service"],
        )
        results = engine.generate(profile)
        assert isinstance(results, list)

    def test_services_with_special_characters(self):
        engine = MessageStrategyEngine()
        profile = _profile(services=["HVAC repair & installation"])
        results = engine.generate(profile)
        assert isinstance(results, list)

    def test_empty_strings_in_lists(self):
        engine = MessageStrategyEngine()
        profile = _profile(
            services=["roof replacement", "", "  "],
            differentiators=["", "free estimates"],
        )
        results = engine.generate(profile)
        assert isinstance(results, list)

    def test_whitespace_only_years(self):
        engine = MessageStrategyEngine()
        profile = _profile(years_in_business="   ")
        results = engine.generate(profile)
        assert isinstance(results, list)

    def test_ancillary_services_set_is_reasonable(self):
        assert len(_ANCILLARY_SERVICES) < 50, \
            "Ancillary services set should remain bounded"

    def test_core_service_priority_is_reasonable(self):
        assert 200 <= len(_CORE_SERVICE_PRIORITY) <= 400, \
            f"Core service priority has {len(_CORE_SERVICE_PRIORITY)} entries"


# ======================================================================
# MessageStrategyEngine API
# ======================================================================

class TestMessageStrategyEngine:
    """MessageStrategyEngine class behavior."""

    def test_engine_instantiation(self):
        engine = MessageStrategyEngine()
        assert engine is not None

    def test_generate_returns_list(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_roofing_profile())
        assert isinstance(results, list)
        assert all(isinstance(s, MessageStrategy) for s in results)

    def test_generate_returns_3_to_5_candidates(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_roofing_profile())
        assert 3 <= len(results) <= 5, \
            f"Expected 3-5 candidates, got {len(results)}"

    def test_generate_minimal_profile_returns_fewer(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_profile(services=["roof replacement"]))
        assert 1 <= len(results) <= 3

    def test_each_candidate_has_unique_type(self):
        engine = MessageStrategyEngine()
        results = engine.generate(_roofing_profile())
        types = [s.strategy_type for s in results]
        assert len(types) == len(set(types)), \
            f"Duplicate strategy types: {types}"
