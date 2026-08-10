"""Sprint 4B inventory workspace service (pure Python, Qt-free).

Owns the DOMAIN/BUSINESS logic for editing advertising inventory so it is
testable without a desktop:

    InventoryWorkspacePage
        -> InventoryController (Qt signals, selection)
            -> InventoryWorkspaceService  (logic + persistence)
                -> InventoryStore (JSON on disk)

Responsibilities: load inventory (empty when no file, never crash); list the
retailer/market/location/placement hierarchy; create/update entities with
relationship validation; archive placements; availability checks; effective
traffic lookup; scene-template options; deterministic summary counts.

Design rules honored:

- **No raw widgets.** This module never imports Qt.
- **No direct JSON writes.** Persistence flows through ``InventoryStore``.
- **No duplicated domain logic.** Availability, traffic inheritance and category
  normalization live in the domain model; the service only *calls* them and
  translates user input (dollars -> cents, comma lists -> normalized lists).
- **Explicit validation.** Invalid relationships, malformed money/traffic and
  unknown statuses raise :class:`InventoryValidationError` with concise messages.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gui.models.inventory import (
    PERIOD_MONTH,
    PERIOD_ONETIME,
    PERIOD_YEAR,
    PLACEMENT_STATUSES,
    PRICE_PERIODS,
    STATUS_AVAILABLE,
    STATUS_HELD,
    STATUS_SOLD,
    Money,
    Placement,
    Retailer,
    Market,
    Location,
)
from gui.models.inventory_store import (
    Inventory,
    InventoryStore,
)

logger = logging.getLogger(__name__)

# Sentinels distinguish "leave unchanged" from "set to None" internally.
_UNSET = object()


class InventoryValidationError(ValueError):
    """Raised when a user action would create an invalid inventory value."""


def _clean(value: Any) -> str:
    """Trim a value to a string (None -> empty)."""
    if value is None:
        return ""
    return str(value).strip()


def _norm_blocked(value: Any) -> List[str]:
    """Normalize a blocked-category input (list or comma-separated string).

    Entries are trimmed, empty entries dropped, and duplicates removed
    case-insensitively while preserving the first-seen casing.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    else:
        parts = [str(p).strip() for p in value]
    seen: List[str] = []
    for part in parts:
        if not part:
            continue
        if part.lower() not in {s.lower() for s in seen}:
            seen.append(part)
    return seen


class InventoryWorkspaceService:
    """Stateless (per-call) domain operations over an ``InventoryStore``."""

    def __init__(self, store: Optional[InventoryStore] = None) -> None:
        self._store = store or InventoryStore()
        self._loaded = False
        self._scene_cache: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Store / load
    # ------------------------------------------------------------------
    @property
    def store(self) -> InventoryStore:
        """The underlying repository (used by the controller for persistence)."""
        return self._store

    def ensure_loaded(self) -> Inventory:
        """Load once (fresh empty inventory when no file exists) and return it."""
        if not self._loaded:
            self.load()
        return self._store.inventory

    def load(self) -> Inventory:
        """Load from disk; a missing file yields an empty inventory (no crash)."""
        try:
            inventory = self._store.load()
        except FileNotFoundError:
            inventory = self._store.create_inventory()
        self._loaded = True
        return inventory

    def reload(self) -> Inventory:
        """Force a fresh load from disk (used after external changes)."""
        self._loaded = False
        return self.load()

    def save(self) -> None:
        """Persist the current snapshot through InventoryStore."""
        self._store.save()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list_retailers(self) -> List[Retailer]:
        return self._store.list_retailers()

    def list_markets(self) -> List[Market]:
        return self._store.list_markets()

    def list_locations(self) -> List[Location]:
        return self._store.list_locations()

    def list_placements(self) -> List[Placement]:
        return self._store.list_placements()

    def get_retailer(self, retailer_id: str) -> Optional[Retailer]:
        return self._store.inventory.get_retailer(retailer_id)

    def get_market(self, market_id: str) -> Optional[Market]:
        return self._store.inventory.get_market(market_id)

    def get_location(self, location_id: str) -> Optional[Location]:
        return self._store.inventory.get_location(location_id)

    def get_placement(self, placement_id: str) -> Optional[Placement]:
        return self._store.inventory.get_placement(placement_id)

    def scene_template_options(self) -> List[Dict[str, Any]]:
        """Return scene-template choices discovered dynamically (not hardcoded)."""
        if self._scene_cache is None:
            from gui.services.project_workspace import list_scene_templates

            self._scene_cache = list_scene_templates()
        return list(self._scene_cache)
# ------------------------------------------------------------------
    # Hierarchy
    # ------------------------------------------------------------------
    def hierarchy(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Build a deterministic, ordered tree for the workspace navigation.

        Returns a list of retailer nodes::

            {
                "retailer": Retailer,
                "markets": [
                    {
                        "market": Market | None,
                        "label": str,
                        "locations": [
                            {"location": Location, "placements": [Placement, ...]},
                        ],
                    },
                ],
            }

        ``status_filter`` (a placement status or None) restricts which
        placements appear under each location. Retailers/locations with no
        matching placements are still shown so the owner can add children.
        """
        inv = self.ensure_loaded()
        retailers = sorted(
            inv.retailers, key=lambda r: (r.parent_company, r.name, r.retailer_id)
        )

        nodes: List[Dict[str, Any]] = []
        for retailer in retailers:
            locs = [l for l in inv.locations if l.retailer_id == retailer.retailer_id]
            # Group this retailer's locations by market.
            market_groups: Dict[str, Dict[str, Any]] = {}
            for loc in sorted(locs, key=lambda l: (l.name, l.location_id)):
                key = loc.market_id or ""
                group = market_groups.setdefault(
                    key, {"market": None, "label": "", "locations": []}
                )
                market = inv.get_market(loc.market_id)
                group["market"] = market
                group["label"] = market.name if market else "(unknown market)"
                group["locations"].append(loc)

            markets: List[Dict[str, Any]] = []
            for _key, group in market_groups.items():
                location_nodes = []
                for loc in group["locations"]:
                    placements = inv.placements_by_location(loc.location_id)
                    if status_filter:
                        match = status_filter.upper()
                        placements = [p for p in placements if p.status == match]
                    location_nodes.append(
                        {"location": loc, "placements": placements}
                    )
                markets.append(
                    {
                        "market": group["market"],
                        "label": group["label"],
                        "locations": location_nodes,
                    }
                )
            markets.sort(
                key=lambda mn: (
                    mn["label"],
                    (mn["market"].market_id if mn["market"] else ""),
                )
            )
            nodes.append(
                {"retailer": retailer, "markets": markets, "locations": locs}
            )
        return nodes

    # ------------------------------------------------------------------
    # Orphan detection / relationship validation
    # ------------------------------------------------------------------
    def orphans(self) -> Dict[str, List[str]]:
        """Return lists of entity ids that reference missing parents.

        Never raises; callers display a warning but keep loading so older data
        with broken references does not crash the workspace.
        """
        inv = self.ensure_loaded()
        retailer_ids = {r.retailer_id for r in inv.retailers}
        market_ids = {m.market_id for m in inv.markets}
        location_ids = {l.location_id for l in inv.locations}

        orphan_locations = [
            l.location_id
            for l in inv.locations
            if (l.retailer_id and l.retailer_id not in retailer_ids)
            or (l.market_id and l.market_id not in market_ids)
        ]
        orphan_placements = [
            p.placement_id
            for p in inv.placements
            if p.location_id and p.location_id not in location_ids
        ]
        return {
            "locations": orphan_locations,
            "placements": orphan_placements,
        }

    def validate_relationships(self) -> None:
        """Raise :class:`InventoryValidationError` when orphans exist."""
        orphans = self.orphans()
        problems = []
        if orphans["locations"]:
            problems.append(
                f"location(s) reference missing retailer/market: "
                f"{orphans['locations']}"
            )
        if orphans["placements"]:
            problems.append(
                f"placement(s) reference missing location: "
                f"{orphans['placements']}"
            )
        if problems:
            raise InventoryValidationError(
                "Orphaned entities: " + "; ".join(problems)
            )
# ------------------------------------------------------------------
    # Money / input helpers
    # ------------------------------------------------------------------
    def _parse_money(self, value: Any) -> Optional[Money]:
        """Convert a human dollar value to integer-cent Money (None clears)."""
        if value is None or value is _UNSET:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        if isinstance(value, bool):
            raise InventoryValidationError("Invalid money value.")
        try:
            return Money.dollars(value)
        except Exception as exc:  # noqa: BLE001 - malformed money -> clear error
            raise InventoryValidationError(
                f"Invalid money value: {value!r}"
            ) from exc

    def _parse_optional_int(self, value: Any) -> Optional[int]:
        """Convert a whole-number input to int (None clears)."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise InventoryValidationError(
                f"Invalid whole number: {value!r}"
            ) from exc

    def _parse_optional_float(self, value: Any) -> Optional[float]:
        """Convert an optional coordinate to float (None clears)."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise InventoryValidationError(
                f"Invalid number: {value!r}"
            ) from exc

    def _validate_status(self, status: str) -> str:
        status = _clean(status).upper()
        if status not in PLACEMENT_STATUSES:
            raise InventoryValidationError(f"Invalid placement status: {status!r}")
        return status

    def _validate_period(self, period: str) -> str:
        period = _clean(period).upper()
        if period not in PRICE_PERIODS:
            raise InventoryValidationError(f"Invalid price period: {period!r}")
        return period

    def _validate_name(self, name: str) -> str:
        name = _clean(name)
        if not name:
            raise InventoryValidationError("Name is required.")
        return name

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    def create_retailer(
        self,
        *,
        name: str,
        parent_company: str = "",
        brand_name: str = "",
        website: str = "",
    ) -> Retailer:
        inv = self.ensure_loaded()
        retailer = Retailer(
            name=self._validate_name(name),
            parent_company=_clean(parent_company),
            brand_name=_clean(brand_name) or _clean(name),
            website=_clean(website),
        )
        inv.retailers.append(retailer)
        self.save()
        logger.info("Created retailer %s", retailer.retailer_id)
        return retailer

    def create_market(self, *, name: str, state: str = "", region: str = "") -> Market:
        inv = self.ensure_loaded()
        market = Market(
            name=self._validate_name(name),
            state=_clean(state),
            region=_clean(region),
        )
        inv.markets.append(market)
        self.save()
        logger.info("Created market %s", market.market_id)
        return market
    def create_location(
        self,
        *,
        retailer_id: str,
        market_id: str,
        name: str,
        store_number: str = "",
        address: str = "",
        city: str = "",
        state: str = "",
        postal_code: str = "",
        latitude: Any = None,
        longitude: Any = None,
        weekly_traffic: Any = None,
    ) -> Location:
        inv = self.ensure_loaded()
        if retailer_id and inv.get_retailer(retailer_id) is None:
            raise InventoryValidationError(
                f"Retailer {retailer_id!r} does not exist."
            )
        if market_id and inv.get_market(market_id) is None:
            raise InventoryValidationError(f"Market {market_id!r} does not exist.")
        location = Location(
            retailer_id=_clean(retailer_id),
            market_id=_clean(market_id),
            name=self._validate_name(name),
            store_number=_clean(store_number),
            address=_clean(address),
            city=_clean(city),
            state=_clean(state),
            postal_code=_clean(postal_code),
            latitude=self._parse_optional_float(latitude),
            longitude=self._parse_optional_float(longitude),
            weekly_traffic=self._parse_optional_int(weekly_traffic),
        )
        inv.locations.append(location)
        self.save()
        logger.info("Created location %s", location.location_id)
        return location

    def create_placement(
        self,
        *,
        location_id: str,
        name: str,
        placement_type: str = "",
        scene_template: str = "",
        status: str = STATUS_AVAILABLE,
        price: Any = _UNSET,
        price_period: str = PERIOD_YEAR,
        setup_fee: Any = _UNSET,
        exclusive_category: str = "",
        blocked_categories: Any = None,
        traffic_override: Any = None,
        start_date: Any = None,
        end_date: Any = None,
        notes: str = "",
    ) -> Placement:
        inv = self.ensure_loaded()
        if location_id and inv.get_location(location_id) is None:
            raise InventoryValidationError(
                f"Location {location_id!r} does not exist."
            )
        placement = Placement(
            location_id=_clean(location_id),
            name=self._validate_name(name),
            placement_type=_clean(placement_type),
            scene_template=_clean(scene_template),
            status=self._validate_status(status),
            price=self._parse_money(price),
            price_period=self._validate_period(price_period),
            setup_fee=self._parse_money(setup_fee),
            exclusive_category=_clean(exclusive_category),
            blocked_categories=_norm_blocked(blocked_categories),
            traffic_override=self._parse_optional_int(traffic_override),
            start_date=_clean(start_date) or None,
            end_date=_clean(end_date) or None,
            notes=_clean(notes),
        )
        inv.placements.append(placement)
        self.save()
        logger.info("Created placement %s", placement.placement_id)
        return placement
# ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update_retailer(
        self,
        retailer_id: str,
        *,
        name: str,
        parent_company: str = "",
        brand_name: str = "",
        website: str = "",
    ) -> Retailer:
        retailer = self._require_retailer(retailer_id)
        retailer.name = self._validate_name(name)
        retailer.parent_company = _clean(parent_company)
        retailer.brand_name = _clean(brand_name) or _clean(name)
        retailer.website = _clean(website)
        self.save()
        return retailer

    def update_market(
        self, market_id: str, *, name: str, state: str = "", region: str = ""
    ) -> Market:
        market = self._require_market(market_id)
        market.name = self._validate_name(name)
        market.state = _clean(state)
        market.region = _clean(region)
        self.save()
        return market

    def update_location(
        self,
        location_id: str,
        *,
        retailer_id: str,
        market_id: str,
        name: str,
        store_number: str = "",
        address: str = "",
        city: str = "",
        state: str = "",
        postal_code: str = "",
        latitude: Any = None,
        longitude: Any = None,
        weekly_traffic: Any = None,
    ) -> Location:
        inv = self.ensure_loaded()
        location = self._require_location(location_id)
        if retailer_id and inv.get_retailer(retailer_id) is None:
            raise InventoryValidationError(
                f"Retailer {retailer_id!r} does not exist."
            )
        if market_id and inv.get_market(market_id) is None:
            raise InventoryValidationError(f"Market {market_id!r} does not exist.")
        location.retailer_id = _clean(retailer_id)
        location.market_id = _clean(market_id)
        location.name = self._validate_name(name)
        location.store_number = _clean(store_number)
        location.address = _clean(address)
        location.city = _clean(city)
        location.state = _clean(state)
        location.postal_code = _clean(postal_code)
        location.latitude = self._parse_optional_float(latitude)
        location.longitude = self._parse_optional_float(longitude)
        location.weekly_traffic = self._parse_optional_int(weekly_traffic)
        self.save()
        return location

    def update_placement(
        self,
        placement_id: str,
        *,
        name: str,
        placement_type: str = "",
        scene_template: str = "",
        status: str = STATUS_AVAILABLE,
        price: Any = _UNSET,
        price_period: str = PERIOD_YEAR,
        setup_fee: Any = _UNSET,
        exclusive_category: str = "",
        blocked_categories: Any = None,
        traffic_override: Any = None,
        start_date: Any = None,
        end_date: Any = None,
        notes: str = "",
    ) -> Placement:
        placement = self._require_placement(placement_id)
        placement.name = self._validate_name(name)
        placement.placement_type = _clean(placement_type)
        placement.scene_template = _clean(scene_template)
        placement.status = self._validate_status(status)
        placement.price = self._parse_money(price)
        placement.price_period = self._validate_period(price_period)
        placement.setup_fee = self._parse_money(setup_fee)
        placement.exclusive_category = _clean(exclusive_category)
        placement.blocked_categories = _norm_blocked(blocked_categories)
        placement.traffic_override = self._parse_optional_int(traffic_override)
        placement.start_date = _clean(start_date) or None
        placement.end_date = _clean(end_date) or None
        placement.notes = _clean(notes)
        self.save()
        return placement
# ------------------------------------------------------------------
    # Status / archive / removal
    # ------------------------------------------------------------------
    def set_placement_status(self, placement_id: str, status: str) -> Placement:
        placement = self._require_placement(placement_id)
        placement.status = self._validate_status(status)
        self.save()
        return placement

    def archive_placement(self, placement_id: str) -> Placement:
        """Archive a placement (set status ARCHIVED). No cascade delete."""
        placement = self._require_placement(placement_id)
        placement.status = "ARCHIVED"
        self.save()
        return placement

    def remove_retailer(self, retailer_id: str) -> None:
        """Remove an empty retailer (no children). Raises if it has locations."""
        inv = self.ensure_loaded()
        self._require_retailer(retailer_id)
        if any(l.retailer_id == retailer_id for l in inv.locations):
            raise InventoryValidationError(
                "Cannot remove a retailer that still has locations."
            )
        inv.retailers = [r for r in inv.retailers if r.retailer_id != retailer_id]
        self.save()

    def remove_market(self, market_id: str) -> None:
        """Remove an empty market (no locations reference it)."""
        inv = self.ensure_loaded()
        self._require_market(market_id)
        if any(l.market_id == market_id for l in inv.locations):
            raise InventoryValidationError(
                "Cannot remove a market that is still referenced by locations."
            )
        inv.markets = [m for m in inv.markets if m.market_id != market_id]
        self.save()

    # ------------------------------------------------------------------
    # Availability / traffic / summary
    # ------------------------------------------------------------------
    def availability_details(self, placement_id: str, category: str) -> Dict[str, Any]:
        """Describe availability for a category (authoritative via domain model).

        Returns ``{"available": bool, "reason": str}``. The boolean comes from
        ``Placement.is_available_for``; the reason is a short presentational
        label derived from the same domain fields (never re-implemented).
        """
        placement = self._require_placement(placement_id)
        available = placement.is_available_for(category)
        norm = str(category or "").strip().lower()
        reason = "Available"
        if not norm:
            reason = "Enter a category"
        elif placement.status != "AVAILABLE":
            reason = f"Not available (status: {placement.status})"
        elif norm in {c.strip().lower() for c in placement.blocked_categories}:
            reason = "Blocked"
        elif str(placement.exclusive_category or "").strip().lower():
            reason = f"Not available (exclusive to {placement.exclusive_category})"
        return {"available": available, "reason": reason, "category": category}

    def check_availability(self, placement_id: str, category: str) -> bool:
        """Direct availability check (used by tests / callers)."""
        placement = self._require_placement(placement_id)
        return placement.is_available_for(category)

    def effective_traffic(self, placement_id: str) -> Optional[int]:
        """Return the placement's effective weekly traffic (override wins)."""
        placement = self._require_placement(placement_id)
        location = self._store.inventory.get_location(placement.location_id)
        return placement.effective_weekly_traffic(location)

    def summary(self) -> Dict[str, Any]:
        """Compact deterministic inventory summary (no analytics)."""
        inv = self.ensure_loaded()
        placements = inv.placements
        available = [p for p in placements if p.status == STATUS_AVAILABLE]
        annual_cents = sum(
            self._annual_value(p.price, p.price_period) for p in available
        )
        return {
            "total": len(placements),
            "available": len(available),
            "held": sum(1 for p in placements if p.status == STATUS_HELD),
            "sold": sum(1 for p in placements if p.status == STATUS_SOLD),
            "available_annual_cents": annual_cents,
        }

    @staticmethod
    def _annual_value(money: Optional[Money], period: str) -> int:
        """Deterministic annualized cents for a placement price (USD only)."""
        if money is None or (money.currency or "").upper() != "USD":
            return 0
        multiplier = {
            PERIOD_YEAR: 1,
            PERIOD_MONTH: 12,
            PERIOD_ONETIME: 1,
        }.get(period, 1)
        return money.amount_cents * multiplier

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _require_retailer(self, retailer_id: str) -> Retailer:
        retailer = self.get_retailer(retailer_id)
        if retailer is None:
            raise InventoryValidationError(f"Retailer {retailer_id!r} not found.")
        return retailer

    def _require_market(self, market_id: str) -> Market:
        market = self.get_market(market_id)
        if market is None:
            raise InventoryValidationError(f"Market {market_id!r} not found.")
        return market

    def _require_location(self, location_id: str) -> Location:
        location = self.get_location(location_id)
        if location is None:
            raise InventoryValidationError(f"Location {location_id!r} not found.")
        return location

    def _require_placement(self, placement_id: str) -> Placement:
        placement = self.get_placement(placement_id)
        if placement is None:
            raise InventoryValidationError(f"Placement {placement_id!r} not found.")
        return placement