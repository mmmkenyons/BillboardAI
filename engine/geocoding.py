"""Sprint 5E core geocoding abstractions (pure, Qt-free, I/O-free).

This module is the **provider-neutral geocoding domain**:

- ``GeocodeResult``   — coordinates + provenance
- ``Geocoder``        — provider-neutral interface (Protocol)
- ``FakeGeocoder``    — deterministic in-memory fake for tests/verification
- Address normalization helpers

Design rules:
- No Qt, no web, no I/O.
- Provider implementations (real APIs) belong in separate adapter modules.
- Coordinates must pass validation: -90 <= lat <= 90, -180 <= lon <= 180.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Provenance source constants
# ---------------------------------------------------------------------------
SOURCE_MANUAL = "manual"
SOURCE_GEOCODED = "geocoded"
SOURCE_IMPORTED = "imported"
SOURCE_LEGACY = "legacy"
SOURCE_UNKNOWN = "unknown"

VALID_SOURCES: tuple = (
    SOURCE_MANUAL,
    SOURCE_GEOCODED,
    SOURCE_IMPORTED,
    SOURCE_LEGACY,
    SOURCE_UNKNOWN,
)


def utc_now_iso() -> str:
    """Return UTC now as ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_float(value: Any) -> Optional[float]:
    """Safe float coercion."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_coordinates(lat: float, lon: float) -> None:
    """Raise ValueError if coordinates are out of valid range."""
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude {lat} out of range [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude {lon} out of range [-180, 180]")
# ---------------------------------------------------------------------------
# GeocodeResult
# ---------------------------------------------------------------------------


@dataclass
class GeocodeResult:
    """Provider-neutral geocoding result with coordinates and provenance."""

    latitude: float
    longitude: float
    formatted_address: str = ""
    provider: str = ""
    provider_place_id: str = ""
    confidence: Optional[float] = None
    precision: str = ""
    queried_address: str = ""
    source: str = SOURCE_GEOCODED
    resolved_at: str = ""
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_coordinates(self.latitude, self.longitude)
        if self.source not in VALID_SOURCES:
            raise ValueError(f"Unknown source {self.source!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "formatted_address": self.formatted_address,
            "provider": self.provider,
            "provider_place_id": self.provider_place_id,
            "confidence": self.confidence,
            "precision": self.precision,
            "queried_address": self.queried_address,
            "source": self.source,
            "resolved_at": self.resolved_at,
            "raw_metadata": dict(self.raw_metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "GeocodeResult":
        data = data if isinstance(data, dict) else {}
        lat = _as_float(data.get("latitude"))
        lon = _as_float(data.get("longitude"))
        if lat is None:
            raise ValueError("latitude is required in GeocodeResult")
        if lon is None:
            raise ValueError("longitude is required in GeocodeResult")
        source = str(data.get("source") or SOURCE_GEOCODED)
        if source not in VALID_SOURCES:
            source = SOURCE_GEOCODED
        return cls(
            latitude=lat,
            longitude=lon,
            formatted_address=str(data.get("formatted_address") or ""),
            provider=str(data.get("provider") or ""),
            provider_place_id=str(data.get("provider_place_id") or ""),
            confidence=_as_float(data.get("confidence")),
            precision=str(data.get("precision") or ""),
            queried_address=str(data.get("queried_address") or ""),
            source=source,
            resolved_at=str(data.get("resolved_at") or ""),
            raw_metadata=dict(data.get("raw_metadata") or {}),
        )

    def provenance_label(self) -> str:
        """Human-readable provenance: e.g. 'Geocoded (fake)'."""
        provider = self.provider or "unknown"
        return f"{self.source.title()} ({provider})"

# ---------------------------------------------------------------------------
# Geocoder protocol (provider-neutral)
# ---------------------------------------------------------------------------


@runtime_checkable
class Geocoder(Protocol):
    """Provider-neutral geocoding interface.

    Production/domain code depends on this, not on specific providers.
    """

    def geocode(self, address: str) -> Optional[GeocodeResult]:
        """Resolve an address string to coordinates.

        Returns None when the address cannot be resolved.
        """
        ...


# ---------------------------------------------------------------------------
# Deterministic fake geocoder (test infrastructure)
# ---------------------------------------------------------------------------


class FakeGeocoder:
    """In-memory deterministic geocoder for tests and verification."""

    def __init__(self, mappings: Optional[Dict[str, GeocodeResult]] = None) -> None:
        self._mappings: Dict[str, GeocodeResult] = {}
        if mappings:
            for key, result in mappings.items():
                self._mappings[_normalize_cache_key(key)] = result
        self._call_count: int = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def geocode(self, address: str) -> Optional[GeocodeResult]:
        self._call_count += 1
        key = _normalize_cache_key(address)
        return self._mappings.get(key)

    def add_mapping(self, address: str, result: GeocodeResult) -> None:
        """Register a new mapping."""
        self._mappings[_normalize_cache_key(address)] = result


# ---------------------------------------------------------------------------
# Address normalization
# ---------------------------------------------------------------------------


def build_normalized_address(
    street: str = "",
    city: str = "",
    state: str = "",
    postal_code: str = "",
    country: str = "US",
) -> str:
    """Build a deterministic address string from structured fields."""
    parts: list[str] = []
    if street:
        parts.append(_clean_component(street))
    if city:
        parts.append(_clean_component(city))
    if state:
        parts.append(_clean_component(state))
    if postal_code:
        parts.append(_clean_component(postal_code))
    # Only append country when there are substantive components
    if parts and country:
        parts.append(_clean_component(country))
    return ", ".join(parts)


def normalize_cache_key(address: str) -> str:
    """Deterministic cache key from an address string."""
    return _normalize_cache_key(address)


def _normalize_cache_key(address: str) -> str:
    """Internal: produce a stable key for cache lookups."""
    if not address:
        return ""
    collapsed = " ".join(address.strip().split())
    return ", ".join(
        part.strip() for part in collapsed.split(",") if part.strip()
    ).lower()


def _clean_component(value: str) -> str:
    """Trim and collapse whitespace for a single address component."""
    if not value:
        return ""
    return " ".join(value.strip().split())

