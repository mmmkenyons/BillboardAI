"""Sprint 5E focused tests: geocoding abstractions, cache, and enrichment.

Covers: address normalization, result validation, cache, enrichment, downstream.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.geocoding import (
    FakeGeocoder,
    GeocodeResult,
    build_normalized_address,
    normalize_cache_key,
    utc_now_iso,
)
from engine.opportunity import OpportunityEngine
from gui.models.inventory import Location
from gui.models.prospect import Prospect
from gui.services.geocoding_cache import GeocodeCache, GeocodeCacheCorrupt
from gui.services.location_enrichment import (
    ERR_ADDRESS_INCOMPLETE,
    ERR_NOT_FOUND,
    EnrichmentOutcome,
    LocationEnrichmentService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prospect(
    prospect_id: str = "p1",
    city: str = "Castle Rock",
    state: str = "CO",
    postal_code: str = "80104",
    address: str = "123 Main St",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Prospect:
    return Prospect(
        prospect_id=prospect_id,
        company_name="Test Co",
        address=address,
        city=city,
        state=state,
        postal_code=postal_code,
        latitude=lat,
        longitude=lon,
    )


def _make_location(
    location_id: str = "loc1",
    city: str = "Castle Rock",
    state: str = "CO",
    postal_code: str = "80104",
    address: str = "456 Founders Pkwy",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Location:
    return Location(
        location_id=location_id,
        name="King Soopers #123",
        address=address,
        city=city,
        state=state,
        postal_code=postal_code,
        latitude=lat,
        longitude=lon,
    )


FAKE_RESULT = GeocodeResult(
    latitude=39.3722,
    longitude=-104.8561,
    provider="fake",
    formatted_address="123 Main St, Castle Rock, CO 80104, US",
    queried_address="123 Main St, Castle Rock, CO, 80104, US",
    resolved_at=utc_now_iso(),
)

# ---------------------------------------------------------------------------
# Address normalization
# ---------------------------------------------------------------------------


class TestAddressNormalization:
    """Tests 1-6: address normalization and cache keys."""

    def test_structured_builds_deterministic_query(self):
        q = build_normalized_address(
            street="123 Main St", city="Castle Rock", state="CO", postal_code="80104"
        )
        assert q == "123 Main St, Castle Rock, CO, 80104, US"

    def test_whitespace_normalized(self):
        q = build_normalized_address(
            street="  123  Main  St  ", city="  Castle Rock  ", state="CO"
        )
        assert q == "123 Main St, Castle Rock, CO, US"

    def test_missing_optional_components(self):
        q = build_normalized_address(city="Denver", state="CO")
        assert q == "Denver, CO, US"

    def test_empty_address(self):
        assert build_normalized_address() == ""

    def test_cache_key_deterministic(self):
        k1 = normalize_cache_key("123 Main St, Castle Rock, CO, 80104")
        k2 = normalize_cache_key("  123 Main St  ,  CASTLE ROCK , co , 80104  ")
        assert k1 == k2
        assert k1 == "123 main st, castle rock, co, 80104"

    def test_cache_key_empty(self):
        assert normalize_cache_key("") == ""


# ---------------------------------------------------------------------------
# GeocodeResult validation
# ---------------------------------------------------------------------------


class TestResultValidation:
    """Tests 6-10: coordinate validation."""

    def test_valid_coords_accepted(self):
        r = GeocodeResult(latitude=39.37, longitude=-104.86)
        assert r.latitude == 39.37

    def test_lat_below_minus_90_rejected(self):
        with pytest.raises(ValueError):
            GeocodeResult(latitude=-91.0, longitude=0.0)

    def test_lat_above_90_rejected(self):
        with pytest.raises(ValueError):
            GeocodeResult(latitude=91.0, longitude=0.0)

    def test_lon_below_minus_180_rejected(self):
        with pytest.raises(ValueError):
            GeocodeResult(latitude=0.0, longitude=-181.0)

    def test_lon_above_180_rejected(self):
        with pytest.raises(ValueError):
            GeocodeResult(latitude=0.0, longitude=181.0)

    def test_roundtrip(self):
        r = GeocodeResult(
            latitude=39.37, longitude=-104.86, provider="test", formatted_address="addr"
        )
        d = r.to_dict()
        r2 = GeocodeResult.from_dict(d)
        assert r2.latitude == r.latitude
        assert r2.provider == "test"

# ---------------------------------------------------------------------------
# Fake geocoder
# ---------------------------------------------------------------------------


class TestFakeGeocoder:
    def test_hit(self):
        fake = FakeGeocoder({"123 main st": FAKE_RESULT})
        result = fake.geocode("123 Main St")
        assert result is not None
        assert result.latitude == 39.3722

    def test_miss(self):
        fake = FakeGeocoder()
        assert fake.geocode("nowhere") is None

    def test_call_count(self):
        fake = FakeGeocoder({"addr": FAKE_RESULT})
        assert fake.call_count == 0
        fake.geocode("addr")
        assert fake.call_count == 1
        fake.geocode("addr")
        assert fake.call_count == 2

    def test_add_mapping(self):
        fake = FakeGeocoder()
        fake.add_mapping("test address", FAKE_RESULT)
        result = fake.geocode("  Test  Address  ")
        assert result is not None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestCache:
    """Tests 11-19: cache behavior."""

    def test_cache_miss_calls_provider(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        cache = GeocodeCache(path=cache_path)
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        outcome = svc.enrich_prospect(_make_prospect())
        assert outcome.success
        assert fake.call_count == 1

    def test_successful_result_persisted(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        cache = GeocodeCache(path=cache_path)
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        svc.enrich_prospect(_make_prospect())
        assert os.path.exists(cache_path)

    def test_second_lookup_hits_cache(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        cache = GeocodeCache(path=cache_path)
        fake = FakeGeocoder({"123 main st, castle rock, co, 80104, us": FAKE_RESULT})
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        svc.enrich_prospect(_make_prospect())
        call_count_after_first = fake.call_count
        # Reset prospect coords
        p = _make_prospect()
        p.latitude = None
        p.longitude = None
        svc.enrich_prospect(p)
        assert fake.call_count == call_count_after_first  # no new call

    def test_cache_hit_does_not_call_provider(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        cache = GeocodeCache(path=cache_path)
        fake = FakeGeocoder({"123 main st, castle rock, co, 80104, us": FAKE_RESULT})
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        svc.enrich_prospect(_make_prospect())
        assert fake.call_count == 1
        # New prospect with same address
        p = _make_prospect()
        p.latitude = None
        p.longitude = None
        svc.enrich_prospect(p)
        assert fake.call_count == 1  # cached

    def test_malformed_cache_surfaces_error(self, tmp_path):
        cache_path = str(tmp_path / "bad.json")
        with open(cache_path, "w") as f:
            f.write("not json")
        cache = GeocodeCache(path=cache_path)
        with pytest.raises(GeocodeCacheCorrupt):
            cache.load()

    def test_cache_roundtrip_preserves_provenance(self, tmp_path):
        cache_path = str(tmp_path / "cache.json")
        cache = GeocodeCache(path=cache_path)
        result = GeocodeResult(
            latitude=39.37, longitude=-104.86, provider="test-prov",
            formatted_address="addr", source="geocoded"
        )
        cache.put("addr", result)
        cache.save()
        cache2 = GeocodeCache(path=cache_path)
        r2 = cache2.get("addr")
# ---------------------------------------------------------------------------
# Prospect enrichment
# ---------------------------------------------------------------------------


class TestProspectEnrichment:
    """Tests 20-29: prospect enrichment."""

    def test_complete_address_enriched(self):
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        p = _make_prospect()
        outcome = svc.enrich_prospect(p)
        assert outcome.success
        assert p.latitude == 39.3722
        assert p.longitude == -104.8561

    def test_coordinates_persisted(self):
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        p = _make_prospect()
        svc.enrich_prospect(p)
        assert p.latitude == 39.3722

    def test_provenance_persisted(self):
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        p = _make_prospect()
        svc.enrich_prospect(p)
        gm = getattr(p, "geocode_metadata", {})
        assert gm.get("source") == "geocoded"
        assert gm.get("provider") == "fake"

    def test_existing_coords_avoid_provider(self, tmp_path):
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        cache = GeocodeCache(path=str(tmp_path / "cache.json"))
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        p = _make_prospect(lat=39.0, lon=-104.0)
        p.geocode_metadata = {"source": "manual"}
        outcome = svc.enrich_prospect(p)
        assert outcome.success
        assert p.latitude == 39.0
        assert fake.call_count == 0

    def test_force_refresh_replaces_coords(self, tmp_path):
        fake = FakeGeocoder(
            {"123 main st, castle rock, co, 80104, us": FAKE_RESULT}
        )
        cache = GeocodeCache(path=str(tmp_path / "cache.json"))
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        p = _make_prospect(lat=39.0, lon=-104.0)
        outcome = svc.enrich_prospect(p, force_refresh=True)
        assert outcome.success
        assert p.latitude == 39.3722
        assert fake.call_count == 1
    def test_incomplete_address_handled(self):
        svc = LocationEnrichmentService()
        p = _make_prospect(city="", state="", postal_code="", address="")
        outcome = svc.enrich_prospect(p)
        assert not outcome.success
        assert outcome.error_code == ERR_ADDRESS_INCOMPLETE

    def test_provider_not_found_handled(self, tmp_path):
        fake = FakeGeocoder()
        cache = GeocodeCache(path=str(tmp_path / "cache.json"))
        svc = LocationEnrichmentService(geocoder=fake, cache=cache)
        p = _make_prospect()
        outcome = svc.enrich_prospect(p)
        assert not outcome.success
        assert outcome.error_code == ERR_NOT_FOUND

    def test_no_geocoder_not_found(self, tmp_path):
        cache = GeocodeCache(path=str(tmp_path / "cache.json"))
        svc = LocationEnrichmentService(geocoder=None, cache=cache)
        p = _make_prospect()
        outcome = svc.enrich_prospect(p)
        assert not outcome.success
        assert outcome.error_code == ERR_NOT_FOUND

    def test_legacy_metadata_coords_usable(self):
        p = _make_prospect()
        p.metadata = {"latitude": 39.5, "longitude": -104.5}
        engine = OpportunityEngine()
        lat, lng = engine._prospect_coords(p)
        assert lat == 39.5
        assert lng == -104.5

    def test_persisted_old_json_still_loads(self):
        data = {
            "prospect_id": "p_old",
            "company_name": "Old Co",
            "city": "Denver",
            "state": "CO",
            "postal_code": "80202",
        }
        p = Prospect.from_dict(data)
        assert p.latitude is None
        assert p.longitude is None
# ---------------------------------------------------------------------------
# Inventory Location enrichment
# ---------------------------------------------------------------------------


class TestLocationEnrichment:
    """Tests 30-35: inventory location enrichment."""

    def test_location_can_be_enriched(self):
        fake = FakeGeocoder(
            {"456 founders pkwy, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        loc = _make_location()
        outcome = svc.enrich_location(loc)
        assert outcome.success
        assert loc.latitude == 39.3722

    def test_location_coords_persisted(self):
        fake = FakeGeocoder(
            {"456 founders pkwy, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        loc = _make_location()
        svc.enrich_location(loc)
        assert loc.latitude == 39.3722
        assert loc.longitude == -104.8561

    def test_location_provenance_persisted(self):
        fake = FakeGeocoder(
            {"456 founders pkwy, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        loc = _make_location()
        svc.enrich_location(loc)
        gm = getattr(loc, "geocode_metadata", {})
        assert gm.get("source") == "geocoded"

    def test_existing_coords_avoid_provider(self):
        fake = FakeGeocoder(
            {"456 founders pkwy, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        loc = _make_location(lat=39.0, lon=-104.0)
        loc.geocode_metadata = {"source": "manual"}
        svc.enrich_location(loc)
        assert loc.latitude == 39.0
        assert fake.call_count == 0

    def test_force_refresh_works(self):
        fake = FakeGeocoder(
            {"456 founders pkwy, castle rock, co, 80104, us": FAKE_RESULT}
        )
        svc = LocationEnrichmentService(geocoder=fake)
        loc = _make_location(lat=39.0, lon=-104.0)
        outcome = svc.enrich_location(loc, force_refresh=True)
        assert outcome.success
        assert loc.latitude == 39.3722

    def test_missing_address_handled(self, tmp_path):
        cache = GeocodeCache(path=str(tmp_path / "cache.json"))
        svc = LocationEnrichmentService(cache=cache)
        loc = _make_location(city="", state="", postal_code="", address="")
        outcome = svc.enrich_location(loc)
        assert not outcome.success
        assert outcome.error_code == ERR_ADDRESS_INCOMPLETE


# ---------------------------------------------------------------------------
# Downstream integration (Opportunity + StoreRecommendation)
# ---------------------------------------------------------------------------


class TestDownstreamDistance:
    """Tests 36-40: downstream Opportunity/Recommendation integration."""

    def test_enriched_prospect_location_produces_distance(self):
        engine = OpportunityEngine()
        prospect = _make_prospect(lat=39.3722, lon=-104.8561)
        loc = _make_location(lat=39.3743, lon=-104.8594)
        from gui.models.inventory import Placement

        placement = Placement(
            placement_id="pl1",
            location_id=loc.location_id,
            name="Front Cart Corral",
            placement_type="cart_corral",
        )
        opp = engine.evaluate(prospect, placement, loc)
        assert opp.distance_miles is not None
        assert opp.distance_source == "haversine"

    def test_haversine_seam_used(self):
        """Verify the existing Haversine function is used (not reimplemented)."""
        from engine.opportunity import haversine_miles as hm

        prospect = _make_prospect(lat=39.3722, lon=-104.8561)
        loc = _make_location(lat=39.3743, lon=-104.8594)
        engine = OpportunityEngine()
        from gui.models.inventory import Placement

        placement = Placement(
            placement_id="pl1",
            location_id=loc.location_id,
            name="Front Cart Corral",
            placement_type="cart_corral",
        )
        opp = engine.evaluate(prospect, placement, loc)
        expected = round(
            hm(39.3722, -104.8561, 39.3743, -104.8594), 1
        )
        assert opp.distance_miles == expected

    def test_store_recommendation_preserves_distance(self):
        """StoreRecommendation passes through distance from Opportunity."""
        prospect = _make_prospect(prospect_id="pdist", lat=39.37, lon=-104.86)
        loc = _make_location(
            location_id="l_dist", lat=39.38, lon=-104.85
        )
        from engine.opportunity import Opportunity
        from gui.services.store_recommendation import (
            StoreRecommendation,
            StoreRecommendationService,
        )

        # Build an opportunity manually with distance
        opp = Opportunity(
            opportunity_id="opp1",
            prospect_id=prospect.prospect_id,
            placement_id="pl1",
            location_id=loc.location_id,
            distance_miles=5.3,
            distance_source="haversine",
            eligible=True,
            score=80,
        )
        # Create a minimal service and test _build_recommendation
        svc = StoreRecommendationService()
        inv = svc._inventory_store
        inv.inventory.locations.append(loc)
        from gui.models.inventory import Placement

        placement = Placement(
            placement_id="pl1",
            location_id=loc.location_id,
            name="Front Cart Corral",
            placement_type="cart_corral",
        )
        inv.inventory.placements.append(placement)
        rec = svc._build_recommendation(opp)
        assert rec is not None
        assert rec.distance_miles == 5.3
        assert rec.distance_source == "haversine"

    def test_no_distance_fabricated_when_enrichment_unavailable(self):
        """Without coordinates, distance_miles remains None."""
        engine = OpportunityEngine()
        prospect = _make_prospect()  # no coords
        loc = _make_location()  # no coords
        from gui.models.inventory import Placement

        placement = Placement(
            placement_id="pl1",
            location_id=loc.location_id,
            name="Front Cart Corral",
            placement_type="cart_corral",
        )
        opp = engine.evaluate(prospect, placement, loc)
        assert opp.distance_miles is None
        assert opp.distance_source == ""

    def test_prefer_explicit_over_metadata(self):
        """Explicit lat/lon fields take priority over metadata."""
        p = _make_prospect(lat=39.0, lon=-104.0)
        p.metadata = {"latitude": 99.9, "longitude": 99.9}
        engine = OpportunityEngine()
        lat, lng = engine._prospect_coords(p)
        assert lat == 39.0
        assert lng == -104.0
