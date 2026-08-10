"""InventoryStore: repository abstraction for durable BillboardAI inventory.

Similar in spirit to ``ProjectStore``, this owns the on-disk layout and the
load/save lifecycle for the Sprint 4A inventory domain:

    <root>/
        inventory.json

The file is a single JSON document with a top-level ``schema_version`` and the
four entity collections (retailers, markets, locations, placements). A single
file keeps the format simple and maintainable while remaining forward
compatible: each model's ``from_dict`` ignores unknown fields and supplies safe
defaults for missing optional fields.

Design points:

- **Atomic writes** — a temporary file is written in the same directory and
  then ``os.replace``-d over the target, so a crash during save cannot easily
  corrupt the file.
- **Clear corruption errors** — malformed JSON raises ``InventoryCorruptionError``
  (a subclass of ``InventoryError``) with a descriptive message.
- **Missing file** — ``load()`` raises ``FileNotFoundError``; ``exists()`` lets a
  caller decide whether to create fresh.
- **Gilt-ignored by default** — the default path lives under ``output/inventory``
  (git-ignored), never inside source code.
The store is **JSON only** — no binary object serialization is ever used, so
the file is human-readable and portable.

The store is intentionally stateless with respect to the caller's objects: it
holds the current ``Inventory`` snapshot it manages, and ``save()`` writes that
snapshot. ``load()`` replaces the snapshot with the on-disk content.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from gui.models.inventory import (
    Location,
    Market,
    Placement,
    Retailer,
)

logger = logging.getLogger(__name__)

# Bump when the persisted schema changes incompatibly. Old files remain loadable
# because from_dict is forward compatible, but a bump lets us run migrations.
SCHEMA_VERSION = 1

# Default inventory file (git-ignored via output/).
DEFAULT_INVENTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "inventory",
)
DEFAULT_INVENTORY_PATH = os.path.join(DEFAULT_INVENTORY_DIR, "inventory.json")


class InventoryError(Exception):
    """Base error for inventory persistence."""


class InventoryCorruptionError(InventoryError):
    """Raised when the inventory file exists but cannot be parsed as valid inventory."""


class Inventory:
    """An in-memory snapshot of the full advertising inventory.

    Holds the four entity collections plus the schema version. Query helpers
    operate directly on the snapshot so callers can filter without touching the
    store/disk.
    """

    def __init__(
        self,
        retailers: Optional[List[Retailer]] = None,
        markets: Optional[List[Market]] = None,
        locations: Optional[List[Location]] = None,
        placements: Optional[List[Placement]] = None,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.retailers: List[Retailer] = list(retailers or [])
        self.markets: List[Market] = list(markets or [])
        self.locations: List[Location] = list(locations or [])
        self.placements: List[Placement] = list(placements or [])
        self.schema_version: int = schema_version

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "retailers": [r.to_dict() for r in self.retailers],
            "markets": [m.to_dict() for m in self.markets],
            "locations": [l.to_dict() for l in self.locations],
            "placements": [p.to_dict() for p in self.placements],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Inventory":
        if not isinstance(data, dict):
            raise InventoryCorruptionError(
                "inventory root must be a JSON object (got %s)" % type(data).__name__
            )
        schema = data.get("schema_version")
        try:
            schema_int = int(schema) if schema is not None else SCHEMA_VERSION
        except (TypeError, ValueError):
            schema_int = SCHEMA_VERSION
        return cls(
            retailers=[Retailer.from_dict(r) for r in data.get("retailers", [])],
            markets=[Market.from_dict(m) for m in data.get("markets", [])],
            locations=[Location.from_dict(l) for l in data.get("locations", [])],
            placements=[Placement.from_dict(p) for p in data.get("placements", [])],
            schema_version=schema_int,
        )
# ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_retailer(self, retailer_id: str) -> Optional[Retailer]:
        for r in self.retailers:
            if r.retailer_id == retailer_id:
                return r
        return None

    def get_market(self, market_id: str) -> Optional[Market]:
        for m in self.markets:
            if m.market_id == market_id:
                return m
        return None

    def get_location(self, location_id: str) -> Optional[Location]:
        for l in self.locations:
            if l.location_id == location_id:
                return l
        return None

    def get_placement(self, placement_id: str) -> Optional[Placement]:
        for p in self.placements:
            if p.placement_id == placement_id:
                return p
        return None

    # ------------------------------------------------------------------
    # Filtering (deterministic ordering by id)
    # ------------------------------------------------------------------

    @staticmethod
    def _sorted(seq: List[Any], key: str) -> List[Any]:
        return sorted(seq, key=lambda item: getattr(item, key))

    def placements_by_location(self, location_id: str) -> List[Placement]:
        return self._sorted(
            [p for p in self.placements if p.location_id == location_id], "placement_id"
        )

    def placements_by_status(self, status: str) -> List[Placement]:
        return self._sorted(
            [p for p in self.placements if p.status == status], "placement_id"
        )

    def placements_by_market(self, market_id: str) -> List[Placement]:
        location_ids = {l.location_id for l in self.locations if l.market_id == market_id}
        return self._sorted(
            [p for p in self.placements if p.location_id in location_ids], "placement_id"
        )

    def placements_by_retailer(self, retailer_id: str) -> List[Placement]:
        location_ids = {l.location_id for l in self.locations if l.retailer_id == retailer_id}
        return self._sorted(
            [p for p in self.placements if p.location_id in location_ids], "placement_id"
        )
# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class InventoryStore:
    """Create / save / load inventory snapshots, plus list & filter operations."""

    def __init__(
        self,
        path: Optional[Union[str, "os.PathLike[str]"]] = None,
        inventory: Optional[Inventory] = None,
    ) -> None:
        self._path = os.path.abspath(str(path)) if path else DEFAULT_INVENTORY_PATH
        self._inventory = inventory if inventory is not None else Inventory()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        """The absolute path to the inventory.json file."""
        return self._path

    @property
    def inventory(self) -> Inventory:
        """The current in-memory inventory snapshot managed by this store."""
        return self._inventory

    def exists(self) -> bool:
        """Return True when an inventory file exists on disk."""
        return os.path.isfile(self._path)

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    def set_inventory(self, inventory: Inventory) -> None:
        """Replace the store's managed snapshot in memory (no disk write)."""
        self._inventory = inventory

    def save(self) -> None:
        """Persist the current snapshot atomically (tmp file + os.replace)."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = self._inventory.to_dict()
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp_path, self._path)

    def load(self) -> Inventory:
        """Load inventory from disk, replacing the store's snapshot.

        Raises FileNotFoundError when the file is missing and
        InventoryCorruptionError when the file cannot be parsed.
        """
        if not os.path.isfile(self._path):
            raise FileNotFoundError(f"No inventory file found at {self._path!r}")
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise InventoryCorruptionError(
                f"Corrupted inventory file at {self._path!r}: {exc}"
            ) from exc
        self._inventory = Inventory.from_dict(data)
        return self._inventory

    def create_inventory(
        self,
        retailers: Optional[List[Retailer]] = None,
        markets: Optional[List[Market]] = None,
        locations: Optional[List[Location]] = None,
        placements: Optional[List[Placement]] = None,
    ) -> Inventory:
        """Build a fresh Inventory snapshot and adopt it as the store's current one."""
        self._inventory = Inventory(
            retailers=retailers or [],
            markets=markets or [],
            locations=locations or [],
            placements=placements or [],
        )
        return self._inventory

    # ------------------------------------------------------------------
    # List operations (deterministic ordering by id)
    # ------------------------------------------------------------------

    def list_retailers(self) -> List[Retailer]:
        return sorted(self._inventory.retailers, key=lambda r: r.retailer_id)

    def list_markets(self) -> List[Market]:
        return sorted(self._inventory.markets, key=lambda m: m.market_id)

    def list_locations(self) -> List[Location]:
        return sorted(self._inventory.locations, key=lambda l: l.location_id)

    def list_placements(self) -> List[Placement]:
        return sorted(self._inventory.placements, key=lambda p: p.placement_id)

    # ------------------------------------------------------------------
    # Filter helpers (delegate to the snapshot)
    # ------------------------------------------------------------------

    def placements_by_location(self, location_id: str) -> List[Placement]:
        return self._inventory.placements_by_location(location_id)

    def placements_by_market(self, market_id: str) -> List[Placement]:
        return self._inventory.placements_by_market(market_id)

    def placements_by_retailer(self, retailer_id: str) -> List[Placement]:
        return self._inventory.placements_by_retailer(retailer_id)

    def placements_by_status(self, status: str) -> List[Placement]:
        return self._inventory.placements_by_status(status)