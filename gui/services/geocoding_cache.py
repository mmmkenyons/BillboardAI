"""Sprint 5E geocoding cache (Qt-free, durable JSON persistence).

Cache location: output/geocoding/geocode_cache.json (git-ignored).

Design rules:
- JSON only, not pickle.
- schema_version for forward compatibility.
- Atomic writes.
- Cache only successful results (no permanent negative caching in MVP).
- Deterministic cache key from normalized address.
- No API secrets stored.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from engine.geocoding import (
    GeocodeResult,
    normalize_cache_key,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output",
    "geocoding",
)
DEFAULT_CACHE_PATH = os.path.join(DEFAULT_CACHE_DIR, "geocode_cache.json")


class GeocodeCacheError(Exception):
    """Base error for cache operations."""


class GeocodeCacheCorrupt(GeocodeCacheError):
    """Malformed or unreadable cache file."""


class GeocodeCache:
    """Durable JSON cache for geocoding results.

    Usage::

        cache = GeocodeCache()
        cache.load()  # optional; get() loads lazily if needed
        result = cache.get("123 main st, castle rock, co, 80104")
        if result is None:
            result = provider.geocode(address)
            if result is not None:
                cache.put(address, result)
                cache.save()
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or DEFAULT_CACHE_PATH
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._loaded: bool = False

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load cache entries from disk."""
        if not os.path.exists(self._path):
            self._entries = {}
            self._loaded = True
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise GeocodeCacheCorrupt(
                f"Geocode cache JSON is malformed: {exc}"
            ) from exc
        except OSError as exc:
            raise GeocodeCacheError(f"Cannot read geocode cache: {exc}") from exc

        if not isinstance(raw, dict):
            raise GeocodeCacheCorrupt("Geocode cache root is not a dict")

        version = raw.get("schema_version")
        if version is None or not isinstance(version, int):
            logger.warning(
                "Geocode cache missing schema_version; treating as empty"
            )
            self._entries = {}
            self._loaded = True
            return

        entries_raw = raw.get("entries")
        if not isinstance(entries_raw, dict):
            self._entries = {}
            self._loaded = True
            return

        self._entries = {}
        for key, value in entries_raw.items():
            if not isinstance(value, dict):
                logger.warning("Skipping non-dict cache entry for key %r", key)
                continue
            try:
                GeocodeResult.from_dict(value)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping invalid cache entry %r: %s", key, exc)
                continue
            self._entries[key] = value
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def save(self) -> None:
        """Atomically write cache to disk."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        doc: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "entries": dict(self._entries),
        }
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError as exc:
            raise GeocodeCacheError(f"Cannot write geocode cache: {exc}") from exc

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    def get(self, address: str) -> Optional[GeocodeResult]:
        """Return cached result for address, or None on miss."""
        self._ensure_loaded()
        key = normalize_cache_key(address)
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            return GeocodeResult.from_dict(entry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Corrupt cache entry for %r, removing: %s", key, exc)
            del self._entries[key]
            return None

    def put(self, address: str, result: GeocodeResult) -> None:
        """Store a geocoding result in the cache."""
        self._ensure_loaded()
        key = normalize_cache_key(address)
        self._entries[key] = result.to_dict()

    def remove(self, address: str) -> None:
        """Remove a cached entry."""
        self._ensure_loaded()
        key = normalize_cache_key(address)
        self._entries.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._entries = {}
        self._loaded = True
