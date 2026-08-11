"""Sprint 5E LocationEnrichmentService (pure Python, Qt-free).

Owns the orchestration that enriches Prospect and Inventory Location records
with geocoded coordinates:

    Prospect / Location address
            |
    GeocodeCache
            |
    Geocoder (provider abstraction)
            |
    GeocodeResult (validated coordinates + provenance)
            |
    Persist coordinates + geocode_metadata
            |
    OpportunityService (Haversine) uses coordinates downstream

Design rules:
- No Qt, no web, no network I/O in this service.
- Does NOT calculate distance, rank stores, or create Opportunities.
- Shares geocoding infrastructure between Prospects and Inventory Locations.
- Default: does NOT overwrite existing good coordinates (force_refresh opt-in).
- Geocoding is data enrichment, NOT opportunity scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from engine.geocoding import (
    SOURCE_MANUAL,
    GeocodeResult,
    Geocoder,
    build_normalized_address,
    utc_now_iso,
)
from gui.services.geocoding_cache import GeocodeCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enrichment error model
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentOutcome:
    """Result of a location enrichment operation."""

    success: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = ""
    provider: str = ""
    error_code: str = ""
    message: str = ""


# Error codes
ERR_ADDRESS_INCOMPLETE = "ADDRESS_INCOMPLETE"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
ERR_INVALID_RESULT = "INVALID_RESULT"
ERR_CACHE_CORRUPT = "CACHE_CORRUPT"
ERR_PERSISTENCE_FAILED = "PERSISTENCE_FAILED"


class LocationEnrichmentError(Exception):
    """Base enrichment error with code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_valid_coords(lat: Any, lon: Any) -> bool:
    """True if both lat/lon are valid floats in range."""
    try:
        lat_f = float(lat)  # type: ignore[arg-type]
        lon_f = float(lon)  # type: ignore[arg-type]
        return -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0
    except (TypeError, ValueError):
        return False


class LocationEnrichmentService:
    """Enriches Prospects and Inventory Locations with geocoded coordinates.

    Shares geocoding/cache infrastructure for both entity types.
    """

    def __init__(
        self,
        geocoder: Optional[Geocoder] = None,
        cache: Optional[GeocodeCache] = None,
    ) -> None:
        self._geocoder = geocoder  # None -> no provider (only cache hits)
        self._cache = cache or GeocodeCache()

    @property
    def cache(self) -> GeocodeCache:
        return self._cache

    # ------------------------------------------------------------------
    # Prospect enrichment
    # ------------------------------------------------------------------

    def enrich_prospect(
        self,
        prospect: Any,
        prospect_store: Any = None,
        *,
        force_refresh: bool = False,
    ) -> EnrichmentOutcome:
        """Enrich a Prospect with geocoded coordinates.

        Default: does NOT overwrite existing valid coordinates.
        Set force_refresh=True to override.
        """
        existing_lat = getattr(prospect, "latitude", None)
        existing_lon = getattr(prospect, "longitude", None)
        existing_geocode = getattr(prospect, "geocode_metadata", None) or {}

        if _has_valid_coords(existing_lat, existing_lon) and not force_refresh:
            src = existing_geocode.get("source", SOURCE_MANUAL)
            return EnrichmentOutcome(
                success=True,
                latitude=float(existing_lat),
                longitude=float(existing_lon),
                source=src,
                provider=existing_geocode.get("provider", ""),
                message="Existing coordinates preserved",
            )

        address = build_normalized_address(
            street=getattr(prospect, "address", ""),
            city=getattr(prospect, "city", ""),
            state=getattr(prospect, "state", ""),
            postal_code=getattr(prospect, "postal_code", ""),
        )
        if not address:
            return EnrichmentOutcome(
                success=False,
                error_code=ERR_ADDRESS_INCOMPLETE,
                message="Prospect has no structured address components",
            )

        try:
            result = self._resolve(address, force_refresh=force_refresh)
        except LocationEnrichmentError as exc:
            return EnrichmentOutcome(
                success=False, error_code=exc.code, message=exc.message
            )

        if result is None:
            return EnrichmentOutcome(
                success=False,
                error_code=ERR_NOT_FOUND,
                message=f"Address could not be resolved: {address}",
            )

        return self._apply_result_to_prospect(
            prospect, result, address, prospect_store
        )

    def _apply_result_to_prospect(
        self,
        prospect: Any,
        result: GeocodeResult,
        queried_address: str,
        prospect_store: Any = None,
    ) -> EnrichmentOutcome:
        """Apply geocode result to prospect fields and optionally persist."""
        prospect.latitude = result.latitude
        prospect.longitude = result.longitude
        prospect.geocode_metadata = {
            "source": result.source,
            "provider": result.provider,
            "provider_place_id": result.provider_place_id,
            "formatted_address": result.formatted_address,
            "confidence": result.confidence,
            "precision": result.precision,
            "queried_address": queried_address,
            "resolved_at": result.resolved_at or utc_now_iso(),
        }
        if hasattr(prospect, "touch"):
            prospect.touch()

        if prospect_store is not None:
            try:
                prospect_store.upsert(prospect)
                prospect_store.save()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to persist enriched prospect: %s", exc)
                return EnrichmentOutcome(
                    success=False,
                    error_code=ERR_PERSISTENCE_FAILED,
                    message=f"Coordinates resolved but save failed: {exc}",
                )

        return EnrichmentOutcome(
            success=True,
            latitude=result.latitude,
            longitude=result.longitude,
            source=result.source,
            provider=result.provider,
            message=f"Location resolved via {result.provenance_label()}",
        )
    # ------------------------------------------------------------------
    # Inventory Location enrichment
    # ------------------------------------------------------------------

    def enrich_location(
        self,
        location: Any,
        inventory_store: Any = None,
        *,
        force_refresh: bool = False,
    ) -> EnrichmentOutcome:
        """Enrich an Inventory Location with geocoded coordinates."""
        existing_lat = getattr(location, "latitude", None)
        existing_lon = getattr(location, "longitude", None)
        existing_geocode = getattr(location, "geocode_metadata", None) or {}

        if _has_valid_coords(existing_lat, existing_lon) and not force_refresh:
            src = existing_geocode.get("source", SOURCE_MANUAL)
            return EnrichmentOutcome(
                success=True,
                latitude=float(existing_lat),
                longitude=float(existing_lon),
                source=src,
                provider=existing_geocode.get("provider", ""),
                message="Existing coordinates preserved",
            )

        address = build_normalized_address(
            street=getattr(location, "address", ""),
            city=getattr(location, "city", ""),
            state=getattr(location, "state", ""),
            postal_code=getattr(location, "postal_code", ""),
        )
        if not address:
            return EnrichmentOutcome(
                success=False,
                error_code=ERR_ADDRESS_INCOMPLETE,
                message="Location has no structured address components",
            )

        try:
            result = self._resolve(address, force_refresh=force_refresh)
        except LocationEnrichmentError as exc:
            return EnrichmentOutcome(
                success=False, error_code=exc.code, message=exc.message
            )

        if result is None:
            return EnrichmentOutcome(
                success=False,
                error_code=ERR_NOT_FOUND,
                message=f"Address could not be resolved: {address}",
            )

        return self._apply_result_to_location(
            location, result, address, inventory_store
        )

    def _apply_result_to_location(
        self,
        location: Any,
        result: GeocodeResult,
        queried_address: str,
        inventory_store: Any = None,
    ) -> EnrichmentOutcome:
        """Apply geocode result to location and optionally persist."""
        location.latitude = result.latitude
        location.longitude = result.longitude
        location.geocode_metadata = {
            "source": result.source,
            "provider": result.provider,
            "provider_place_id": result.provider_place_id,
            "formatted_address": result.formatted_address,
            "confidence": result.confidence,
            "precision": result.precision,
            "queried_address": queried_address,
            "resolved_at": result.resolved_at or utc_now_iso(),
        }

        if inventory_store is not None:
            try:
                inventory_store.save()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to persist enriched location: %s", exc)
                return EnrichmentOutcome(
                    success=False,
                    error_code=ERR_PERSISTENCE_FAILED,
                    message=f"Coordinates resolved but save failed: {exc}",
                )

        return EnrichmentOutcome(
            success=True,
            latitude=result.latitude,
            longitude=result.longitude,
            source=result.source,
            provider=result.provider,
            message=f"Location resolved via {result.provenance_label()}",
        )

    # ------------------------------------------------------------------
    # Internal: resolve via cache + geocoder
    # ------------------------------------------------------------------

    def _resolve(self, address: str, force_refresh: bool = False) -> Optional[GeocodeResult]:
        """Resolve an address through cache then optional geocoder.

        When force_refresh=True, bypasses cache and calls provider directly.
        """
        if not force_refresh:
            try:
                cached = self._cache.get(address)
            except Exception as exc:  # noqa: BLE001
                raise LocationEnrichmentError(
                    ERR_CACHE_CORRUPT, f"Cache read failed: {exc}"
                ) from exc

            if cached is not None:
                return cached

        if self._geocoder is None:
            return None

        try:
            result = self._geocoder.geocode(address)
        except Exception as exc:  # noqa: BLE001
            raise LocationEnrichmentError(
                ERR_PROVIDER_UNAVAILABLE,
                f"Geocoding provider failed: {exc}",
            ) from exc

        if result is not None:
            self._cache.put(address, result)
            try:
                self._cache.save()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to persist geocode cache: %s", exc)

        return result


