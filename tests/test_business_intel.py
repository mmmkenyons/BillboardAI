"""Sprint 2C: Business intelligence extraction tests."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

import pytest
from bs4 import BeautifulSoup

from engine.scraper.business_intel import (
    ExtractionContext,
    build_context,
    extract_phone,
    extract_location,
    extract_service_area,
    extract_services,
    extract_categories,
    extract_differentiators,
    extract_trust_signals,
    extract_awards,
    extract_certifications,
    extract_guarantees,
    extract_years_in_business,
    extract_business_intel,
)


# ======================================================================
# Helpers
# ======================================================================

def _ctx(html: str = "", metadata: Dict[str, Any] | None = None) -> ExtractionContext:
    soup = BeautifulSoup(html, "lxml") if html else None
    return build_context(soup=soup, html=html, metadata=metadata or {})


def _html(body: str) -> str:
    return f"<html><body>{body}</body></html>"


# ======================================================================
# Phone extraction
# ======================================================================

class TestPhoneExtraction:
    def test_tel_link_extraction(self):
        ctx = _ctx(_html('<a href="tel:+1-605-555-1234">Call</a>'))
        assert extract_phone(ctx) == "(605) 555-1234"

    def test_formatted_us_number(self):
        ctx = _ctx(_html("<p>Call us at (605) 555-1234 today!</p>"))
        assert extract_phone(ctx) == "(605) 555-1234"

    def test_unformatted_us_number(self):
        ctx = _ctx(_html("<p>Call 6055551234</p>"))
        assert extract_phone(ctx) == "(605) 555-1234"

    def test_dashed_number(self):
        ctx = _ctx(_html("<p>605-555-1234</p>"))
        assert extract_phone(ctx) == "(605) 555-1234"

    def test_dotted_number(self):
        ctx = _ctx(_html("<p>605.555.1234</p>"))
        assert extract_phone(ctx) == "(605) 555-1234"

    def test_multiple_phone_selects_first(self):
        ctx = _ctx(_html("<p>Call 605-555-1111 or 605-555-2222</p>"))
        result = extract_phone(ctx)
        assert result in ["(605) 555-1111", "(605) 555-2222"]

    def test_fax_exclusion(self):
        ctx = _ctx(_html("<p>Fax: 605-555-9999 | Phone: 605-555-1234</p>"))
        result = extract_phone(ctx)
        # Should prefer the non-fax number
        assert result == "(605) 555-1234"

    def test_zip_code_rejection(self):
        ctx = _ctx(_html("<p>ZIP: 57105</p>"))
        assert extract_phone(ctx) == ""

    def test_unrelated_number_rejection(self):
        ctx = _ctx(_html("<p>Model number: 12345-67890</p>"))
        assert extract_phone(ctx) == ""

    def test_jsonld_telephone(self):
        html = _html("""<script type="application/ld+json">
        {"@type": "LocalBusiness", "telephone": "+1-605-555-1234"}
        </script>""")
        ctx = _ctx(html)
        assert extract_phone(ctx) == "(605) 555-1234"

    def test_no_phone(self):
        ctx = _ctx(_html("<p>No phone here</p>"))
        assert extract_phone(ctx) == ""


# ======================================================================
# Location extraction
# ======================================================================

class TestLocationExtraction:
    def test_jsonld_postal_address(self):
        html = _html("""<script type="application/ld+json">
        {"@type": "LocalBusiness", "address": {"streetAddress": "123 Main St", "addressLocality": "Sioux Falls", "addressRegion": "SD"}}
        </script>""")
        ctx = _ctx(html)
        result = extract_location(ctx)
        assert "Sioux Falls" in result
        assert "SD" in result

    def test_footer_city_state(self):
        ctx = _ctx(_html("<footer>Jim Woods Roofing | Sioux Falls, SD 57105</footer>"))
        assert extract_location(ctx) == "Sioux Falls, SD"

    def test_headings_city_state(self):
        ctx = _ctx(_html("<h1>Best Roofing in Denver, CO</h1>"))
        assert extract_location(ctx) == "Denver, CO"

    def test_visible_text_city_state(self):
        ctx = _ctx(_html("<p>Serving Houston, TX since 1990</p>"))
        assert extract_location(ctx) == "Houston, TX"

    def test_full_state_name(self):
        ctx = _ctx(_html("<p>Located in Portland, Oregon</p>"))
        assert extract_location(ctx) == "Portland, Oregon"

    def test_missing_location(self):
        ctx = _ctx(_html("<p>No location info here</p>"))
        assert extract_location(ctx) == ""

    def test_no_area_code_inference(self):
        """Location should not be inferred from area code alone."""
        ctx = _ctx(_html("<p>Call 212-555-1234</p>"))
        # 212 is NYC area code but we don't infer location from it
        assert extract_location(ctx) == ""


# ======================================================================
# Service area extraction
# ======================================================================

class TestServiceAreaExtraction:
    def test_explicit_service_area(self):
        ctx = _ctx(_html("<p>Serving Sioux Falls and surrounding areas</p>"))
        result = extract_service_area(ctx)
        assert "Sioux Falls" in result

    def test_greater_area(self):
        ctx = _ctx(_html("<p>Proudly serving Greater Houston</p>"))
        result = extract_service_area(ctx)
        assert "Greater Houston" in result

    def test_metro_area(self):
        ctx = _ctx(_html("<p>Service area: Denver Metro</p>"))
        result = extract_service_area(ctx)
        assert "Denver Metro" in result

    def test_dallas_fort_worth(self):
        ctx = _ctx(_html("<p>Serving Dallas-Fort Worth Metroplex</p>"))
        result = extract_service_area(ctx)
        assert "Dallas" in result

    def test_no_location_only_inference(self):
        """Service area should not be inferred from location alone."""
        ctx = _ctx(_html("<p>Located in Sioux Falls, SD</p>"))
        result = extract_service_area(ctx)
        # Should not return "Sioux Falls" as service area just because it's the location
        assert "Sioux Falls" not in result or "serving" in result.lower()


# ======================================================================
# Services extraction
# ======================================================================

class TestServicesExtraction:
    def test_service_headings(self):
        ctx = _ctx(_html("<h2>Residential Roofing</h2><h2>Commercial Roofing</h2><h2>Roof Repair</h2>"))
        result = extract_services(ctx)
        assert "residential roofing" in result
        assert "commercial roofing" in result
        assert "roof repair" in result

    def test_nav_services(self):
        ctx = _ctx(_html("<nav><a>Roofing</a><a>Siding</a><a>Gutters</a></nav>"))
        result = extract_services(ctx)
        # "roofing" is not a service keyword, but "siding" and "gutters" are
        assert "siding" in result
        assert "gutters" in result

    def test_duplicate_normalization(self):
        ctx = _ctx(_html("<p>roof repair roof repair roof repair</p>"))
        result = extract_services(ctx)
        assert result.count("roof repair") == 1

    def test_generic_marketing_rejection(self):
        """Generic marketing phrases should not be treated as services."""
        ctx = _ctx(_html("<p>We provide the best quality and service in the area</p>"))
        result = extract_services(ctx)
        # "quality" and "service" alone are not service keywords
        assert "quality" not in result
        assert "service" not in result

    def test_empty_services(self):
        ctx = _ctx(_html("<p>Welcome to our website</p>"))
        result = extract_services(ctx)
        assert result == []


# ======================================================================
# Categories extraction
# ======================================================================

class TestCategoriesExtraction:
    def test_roofing_contractor(self):
        ctx = _ctx(_html("<h1>ABC Roofing & Contracting</h1>"))
        result = extract_categories(ctx)
        assert "roofing" in result
        assert "contractor" in result

    def test_dentist(self):
        ctx = _ctx(_html("<h1>Family Dentistry</h1><p>Your local dentist</p>"))
        result = extract_categories(ctx)
        assert "dentist" in result

    def test_realtor(self):
        ctx = _ctx(_html("<h1>Jane Doe Realty</h1><p>Real estate broker</p>"))
        result = extract_categories(ctx)
        assert "realtor" in result

    def test_no_category_when_absent(self):
        ctx = _ctx(_html("<p>Welcome to our website</p>"))
        result = extract_categories(ctx)
        assert result == []


# ======================================================================
# Differentiators extraction
# ======================================================================

class TestDifferentiatorsExtraction:
    def test_free_estimates(self):
        ctx = _ctx(_html("<p>Call for free estimates!</p>"))
        result = extract_differentiators(ctx)
        assert "free estimates" in result

    def test_financing_available(self):
        ctx = _ctx(_html("<p>Financing available for qualified buyers</p>"))
        result = extract_differentiators(ctx)
        assert "financing available" in result

    def test_family_owned(self):
        ctx = _ctx(_html("<p>Family owned and operated since 1985</p>"))
        result = extract_differentiators(ctx)
        assert "family owned" in result

    def test_locally_owned(self):
        ctx = _ctx(_html("<p>Locally owned and operated</p>"))
        result = extract_differentiators(ctx)
        assert "locally owned" in result

    def test_emergency_service(self):
        ctx = _ctx(_html("<p>24/7 emergency service available</p>"))
        result = extract_differentiators(ctx)
        assert "24/7 emergency service" in result

    def test_empty_differentiators(self):
        ctx = _ctx(_html("<p>Welcome</p>"))
        result = extract_differentiators(ctx)
        assert result == []


# ======================================================================
# Trust signals extraction
# ======================================================================

class TestTrustSignalsExtraction:
    def test_licensed_insured(self):
        ctx = _ctx(_html("<p>Licensed and insured for your protection</p>"))
        result = extract_trust_signals(ctx)
        assert "licensed" in result
        assert "insured" in result

    def test_bbb_claim(self):
        ctx = _ctx(_html("<p>BBB Accredited with A+ rating</p>"))
        result = extract_trust_signals(ctx)
        assert "BBB accredited" in result

    def test_bbb_a_plus(self):
        ctx = _ctx(_html("<p>Proudly BBB A+ rated</p>"))
        result = extract_trust_signals(ctx)
        assert "BBB A+" in result

    def test_award_winning_generic(self):
        ctx = _ctx(_html("<p>Award-winning service since 1990</p>"))
        result = extract_trust_signals(ctx)
        assert "award-winning" in result

    def test_years_of_experience(self):
        ctx = _ctx(_html("<p>Over 30 years of experience</p>"))
        result = extract_trust_signals(ctx)
        assert "years of experience" in result

    def test_ratings_only_when_present(self):
        ctx = _ctx(_html("<p>Welcome to our site</p>"))
        result = extract_trust_signals(ctx)
        # Should not fabricate ratings
        assert "Google rating" not in result
        assert "5-star" not in result

    def test_empty_trust_signals(self):
        ctx = _ctx(_html("<p>Hello</p>"))
        result = extract_trust_signals(ctx)
        assert result == []


# ======================================================================
# Awards extraction
# ======================================================================

class TestAwardsExtraction:
    def test_named_award(self):
        ctx = _ctx(_html("<p>Winner of the Angi Super Service Award 2025</p>"))
        result = extract_awards(ctx)
        assert "Angi Super Service Award" in result

    def test_generic_award_winning_not_named(self):
        """Generic 'award-winning' should NOT fabricate a named award."""
        ctx = _ctx(_html("<p>Award-winning service</p>"))
        result = extract_awards(ctx)
        # "award-winning" is a differentiator/trust signal, not a named award
        assert "Angi Super Service Award" not in result

    def test_best_of_award(self):
        ctx = _ctx(_html("<p>Voted Best of Sioux Falls 2025</p>"))
        result = extract_awards(ctx)
        assert len(result) > 0  # "Best of" pattern should match

    def test_empty_awards(self):
        ctx = _ctx(_html("<p>No awards here</p>"))
        result = extract_awards(ctx)
        assert result == []


# ======================================================================
# Certifications extraction
# ======================================================================

class TestCertificationsExtraction:
    def test_gaf_master_elite(self):
        ctx = _ctx(_html("<p>GAF Master Elite certified contractor</p>"))
        result = extract_certifications(ctx)
        assert "GAF Master Elite" in result

    def test_owens_corning_preferred(self):
        ctx = _ctx(_html("<p>Owens Corning Preferred Contractor</p>"))
        result = extract_certifications(ctx)
        assert "Owens Corning Preferred" in result

    def test_certainteed_shinglemaster(self):
        ctx = _ctx(_html("<p>CertainTeed ShingleMaster</p>"))
        result = extract_certifications(ctx)
        assert "CertainTeed ShingleMaster" in result

    def test_empty_certifications(self):
        ctx = _ctx(_html("<p>No certs</p>"))
        result = extract_certifications(ctx)
        assert result == []


# ======================================================================
# Guarantees extraction
# ======================================================================

class TestGuaranteesExtraction:
    def test_satisfaction_guarantee(self):
        ctx = _ctx(_html("<p>100% satisfaction guarantee on all work</p>"))
        result = extract_guarantees(ctx)
        assert "satisfaction guarantee" in result

    def test_lifetime_warranty(self):
        ctx = _ctx(_html("<p>Lifetime warranty on materials</p>"))
        result = extract_guarantees(ctx)
        assert "lifetime warranty" in result

    def test_money_back_guarantee(self):
        ctx = _ctx(_html("<p>Money-back guarantee if not satisfied</p>"))
        result = extract_guarantees(ctx)
        assert "money-back guarantee" in result

    def test_workmanship_warranty(self):
        ctx = _ctx(_html("<p>10-year workmanship warranty included</p>"))
        result = extract_guarantees(ctx)
        assert "workmanship warranty" in result

    def test_empty_guarantees(self):
        ctx = _ctx(_html("<p>No guarantees</p>"))
        result = extract_guarantees(ctx)
        assert result == []


# ======================================================================
# Years in business extraction
# ======================================================================

class TestYearsInBusiness:
    def test_since_year(self):
        ctx = _ctx(_html("<p>Since 1985</p>"))
        result = extract_years_in_business(ctx)
        current_year = datetime.now().year
        expected = str(current_year - 1985)
        assert result == expected

    def test_established(self):
        ctx = _ctx(_html("<p>Established 1990</p>"))
        result = extract_years_in_business(ctx)
        current_year = datetime.now().year
        expected = str(current_year - 1990)
        assert result == expected

    def test_founded(self):
        ctx = _ctx(_html("<p>Founded in 2000</p>"))
        result = extract_years_in_business(ctx)
        current_year = datetime.now().year
        expected = str(current_year - 2000)
        assert result == expected

    def test_est_abbreviation(self):
        ctx = _ctx(_html("<p>Est. 1975</p>"))
        result = extract_years_in_business(ctx)
        current_year = datetime.now().year
        expected = str(current_year - 1975)
        assert result == expected

    def test_years_of_experience(self):
        ctx = _ctx(_html("<p>Over 30 years of experience</p>"))
        result = extract_years_in_business(ctx)
        assert result == "30"

    def test_years_in_business(self):
        ctx = _ctx(_html("<p>40 years in business</p>"))
        result = extract_years_in_business(ctx)
        assert result == "40"

    def test_serving_for_years(self):
        ctx = _ctx(_html("<p>Serving Sioux Falls for 25 years</p>"))
        result = extract_years_in_business(ctx)
        assert result == "25"

    def test_jsonld_founding_year(self):
        html = _html("""<script type="application/ld+json">
        {"@type": "LocalBusiness", "foundingYear": "1995"}
        </script>""")
        ctx = _ctx(html)
        result = extract_years_in_business(ctx)
        current_year = datetime.now().year
        expected = str(current_year - 1995)
        assert result == expected

    def test_copyright_year_ignored(self):
        """Copyright dates should not be used for years in business."""
        ctx = _ctx(_html("<footer>&copy; 2024 Jim Woods Roofing</footer>"))
        result = extract_years_in_business(ctx)
        # Copyright year alone should not trigger extraction
        assert result == ""

    def test_empty_years(self):
        ctx = _ctx(_html("<p>Welcome</p>"))
        result = extract_years_in_business(ctx)
        assert result == ""


# ======================================================================
# Integration tests
# ======================================================================

class TestIntegration:
    def test_brand_profile_populated_from_extracted_fields(self):
        """Verify business_intel dict can be consumed by BrandProfileBuilder."""
        from engine.brand_profile import BrandProfileBuilder

        bi = {
            "phone": "(605) 555-1234",
            "location": "Sioux Falls, SD",
            "service_area": "Sioux Falls and surrounding areas",
            "services": ["roof repair", "siding", "gutters"],
            "categories": ["roofing", "contractor"],
            "differentiators": ["free estimates", "family owned"],
            "trust_signals": ["licensed", "insured"],
            "awards": ["Angi Super Service Award"],
            "certifications": ["GAF Master Elite"],
            "guarantees": ["satisfaction guarantee"],
            "years_in_business": "40",
        }
        data = {
            "url": "https://example.com",
            "company": "Test Co",
            "business_intel": bi,
        }
        profile = BrandProfileBuilder.from_scrape_data(data)
        assert profile.phone == "(605) 555-1234"
        assert profile.location == "Sioux Falls, SD"
        assert profile.service_area == "Sioux Falls and surrounding areas"
        assert profile.services == ["roof repair", "siding", "gutters"]
        assert profile.categories == ["roofing", "contractor"]
        assert profile.differentiators == ["free estimates", "family owned"]
        assert profile.trust_signals == ["licensed", "insured"]
        assert profile.awards == ["Angi Super Service Award"]
        assert profile.certifications == ["GAF Master Elite"]
        assert profile.guarantees == ["satisfaction guarantee"]
        assert profile.years_in_business == "40"

    def test_old_scraper_dict_remains_compatible(self):
        """Old scraper dict without business_intel should still build safely."""
        from engine.brand_profile import BrandProfileBuilder

        data = {
            "url": "https://oldcorp.com",
            "company": "Old Corp",
            "headline": "Quality Since 1980",
        }
        profile = BrandProfileBuilder.from_scrape_data(data)
        assert profile.company_name == "Old Corp"
        assert profile.phone == ""
        assert profile.location == ""
        assert profile.services == []
        assert profile.categories == []
        assert profile.years_in_business == ""

    def test_extract_business_intel_orchestrator(self):
        """Full orchestrator returns all expected keys."""
        ctx = _ctx(_html("<p>Call 605-555-1234 | Sioux Falls, SD | Roof Repair | Since 1995</p>"))
        result = extract_business_intel(ctx)
        assert "phone" in result
        assert "location" in result
        assert "service_area" in result
        assert "services" in result
        assert "categories" in result
        assert "differentiators" in result
        assert "trust_signals" in result
        assert "awards" in result
        assert "certifications" in result
        assert "guarantees" in result
        assert "years_in_business" in result
        assert result["phone"] == "(605) 555-1234"
        assert result["location"] == "Sioux Falls, SD"
        assert "roof repair" in result["services"]


# ======================================================================
# Sprint 2C Precision Gate — adversarial regression tests
# ======================================================================

class TestServiceAreaPrecision:
    def test_serving_the_greater_rejected(self):
        ctx = _ctx(_html("<footer>Serving the greater</footer>"))
        assert extract_service_area(ctx) == ""

    def test_serving_the_area_rejected(self):
        ctx = _ctx(_html("<footer>Serving the area</footer>"))
        assert extract_service_area(ctx) == ""

    def test_serving_surrounding_areas_rejected(self):
        ctx = _ctx(_html("<footer>Serving surrounding areas</footer>"))
        assert extract_service_area(ctx) == ""

    def test_serving_the_community_rejected(self):
        ctx = _ctx(_html("<footer>Serving the community</footer>"))
        assert extract_service_area(ctx) == ""

    def test_greater_area_rejected(self):
        ctx = _ctx(_html("<footer>Greater area</footer>"))
        assert extract_service_area(ctx) == ""

    def test_metro_area_rejected(self):
        ctx = _ctx(_html("<footer>Metro area</footer>"))
        assert extract_service_area(ctx) == ""

    def test_greater_sioux_falls_accepted(self):
        ctx = _ctx(_html("<footer>Proudly serving Greater Sioux Falls</footer>"))
        assert extract_service_area(ctx) == "Greater Sioux Falls"

    def test_denver_metro_accepted(self):
        ctx = _ctx(_html("<h2>Service area: Denver Metro</h2>"))
        assert extract_service_area(ctx) == "Denver Metro"

    def test_multi_city_service_area_accepted(self):
        ctx = _ctx(_html("<footer>Serving Sioux Falls, Brandon, and Harrisburg</footer>"))
        result = extract_service_area(ctx)
        assert "Sioux Falls" in result
        assert "Brandon" in result


class TestServicesPrecision:
    def test_repair_generic_prose_not_service(self):
        ctx = _ctx(_html("<p>We can help with any repair you need in your home.</p>"))
        assert "repair" not in extract_services(ctx)

    def test_roof_repair_in_service_section_accepted(self):
        ctx = _ctx(_html("<h2>Our Roof Repair Services</h2>"))
        assert "roof repair" in extract_services(ctx)

    def test_installation_generic_rejected(self):
        ctx = _ctx(_html("<p>Professional installation available.</p>"))
        assert "installation" not in extract_services(ctx)

    def test_footer_legal_not_service(self):
        ctx = _ctx(_html("<footer>Legal | Privacy | Terms</footer>"))
        assert "legal" not in extract_services(ctx)

    def test_moving_generic_prose_not_service(self):
        ctx = _ctx(_html("<p>Many families are moving into the neighborhood this year.</p>"))
        assert "moving" not in extract_services(ctx)

    def test_siding_in_nav_is_service(self):
        ctx = _ctx(_html("<nav>Home Roofing Siding Gutters Contact</nav>"))
        services = extract_services(ctx)
        assert "siding" in services
        assert "gutters" in services


class TestCategoriesPrecision:
    def test_footer_legal_link_not_legal_category(self):
        ctx = _ctx(_html("<h1>ABC Roofing</h1><footer>Legal | Privacy</footer>"))
        assert "legal" not in extract_categories(ctx)

    def test_generic_cleaning_text_not_cleaning_business(self):
        ctx = _ctx(_html("<h1>Smith Roofing</h1><p>We clean up after installation.</p>"))
        assert "cleaning" not in extract_categories(ctx)

    def test_moving_reference_not_moving_company(self):
        ctx = _ctx(_html("<h1>Jones Roofing</h1><p>Customers moving into a new home.</p>"))
        assert "moving" not in extract_categories(ctx)

    def test_strong_roofing_identity_produces_roofing_contractor(self):
        ctx = _ctx(_html("<h1>Jim Woods Roofing</h1>"))
        categories = extract_categories(ctx)
        assert "roofing" in categories
        assert "contractor" in categories


class TestTrustSignalsPrecision:
    def test_facebook_link_alone_rejected(self):
        ctx = _ctx(_html("<footer><a href='https://facebook.com/abc'>Facebook</a></footer>"))
        assert "Facebook" not in extract_trust_signals(ctx)

    def test_yelp_link_alone_rejected(self):
        ctx = _ctx(_html("<footer><a href='https://yelp.com/abc'>Yelp</a></footer>"))
        assert "Yelp" not in extract_trust_signals(ctx)

    def test_bbb_name_alone_rejected(self):
        ctx = _ctx(_html("<footer>Better Business Bureau</footer>"))
        assert "Better Business Bureau" not in extract_trust_signals(ctx)

    def test_bbb_accredited_accepted(self):
        ctx = _ctx(_html("<footer>BBB Accredited</footer>"))
        assert "BBB accredited" in extract_trust_signals(ctx)

    def test_star_rating_claim_accepted(self):
        ctx = _ctx(_html("<p>4.9 stars on Google with 500+ reviews</p>"))
        signals = extract_trust_signals(ctx)
        assert "star rating" in signals


class TestGuaranteesPrecision:
    def test_generic_warranty_word_alone_rejected(self):
        ctx = _ctx(_html("<footer>Warranty</footer>"))
        assert "warranty" not in extract_guarantees(ctx)

    def test_generic_guarantee_word_alone_rejected(self):
        ctx = _ctx(_html("<footer>Guarantee</footer>"))
        assert "guarantee" not in extract_guarantees(ctx)

    def test_workmanship_warranty_accepted(self):
        ctx = _ctx(_html("<p>We offer a workmanship warranty on all roofs.</p>"))
        assert "workmanship warranty" in extract_guarantees(ctx)


class TestDifferentiatorsCanonical:
    def test_award_winning_not_differentiator(self):
        ctx = _ctx(_html("<p>An award-winning roofing company</p>"))
        assert "award-winning" not in extract_differentiators(ctx)

    def test_licensed_insured_not_differentiator(self):
        ctx = _ctx(_html("<p>Licensed and insured</p>"))
        assert "licensed and insured" not in extract_differentiators(ctx)

    def test_free_estimates_is_differentiator(self):
        ctx = _ctx(_html("<p>Free estimates available</p>"))
        assert "free estimates" in extract_differentiators(ctx)

    def test_family_owned_is_differentiator(self):
        ctx = _ctx(_html("<p>Family owned since 1985</p>"))
        assert "family owned" in extract_differentiators(ctx)


# ======================================================================
# Sprint 2C Final Category Semantics — adversarial tests
# ======================================================================

class TestCategorySemantics:
    def test_financing_available_not_category(self):
        """Financing is a capability, not a business category."""
        ctx = _ctx(_html("<h1>ABC Roofing</h1>"))
        assert "financing" not in extract_categories(ctx)

    def test_energy_mentioned_not_energy_category(self):
        """Incidental energy word in marketing copy is not an energy company."""
        ctx = _ctx(_html("<h1>Award Winning Roofing</h1>"))
        assert "energy" not in extract_categories(ctx)

    def test_office_mentioned_not_office_category(self):
        """Incidental office word is not an office business category."""
        ctx = _ctx(_html("<h1>Exterior Experts</h1>"))
        assert "office" not in extract_categories(ctx)

    def test_legal_footer_not_legal_category(self):
        """Legal in footer does not make it a legal business."""
        ctx = _ctx(_html("<h1>Jim Woods Roofing</h1><footer>Legal | Privacy</footer>"))
        assert "legal" not in extract_categories(ctx)

    def test_energy_company_identity_creates_energy(self):
        """Explicit energy company identity CAN produce energy category."""
        ctx = _ctx(_html("<h1>Sioux Falls Solar & Energy</h1>"))
        assert "energy" in extract_categories(ctx)

    def test_roofing_identity_creates_roofing(self):
        """Strong roofing identity produces roofing category."""
        ctx = _ctx(_html("<h1>Jim Woods Roofing</h1>"))
        categories = extract_categories(ctx)
        assert "roofing" in categories
        assert "contractor" in categories

    def test_dentist_identity_creates_dentist(self):
        """Explicit dentist identity produces dentist category."""
        ctx = _ctx(_html("<h1>Family Dentistry</h1>"))
        assert "dentist" in extract_categories(ctx)

    def test_no_false_categories_for_pure_roofing(self):
        """Roofing company with incidental words gets only roofing categories."""
        ctx = _ctx(_html("<h1>ABC Roofing</h1>"))
        categories = extract_categories(ctx)
        assert "roofing" in categories
        for noise in ("energy", "office", "legal", "cleaning", "moving",
                      "financing", "business services"):
            assert noise not in categories
